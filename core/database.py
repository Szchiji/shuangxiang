import logging
import sqlite3
import threading

logger = logging.getLogger("shuangxiang.db")


class Database:
    """SQLite 单例。承载多租户机器人平台的全部数据。

    平台级： users
    租户级（均按 tenant_id 隔离）：
      • tenants        —— 用户创建的机器人
      • tenant_users   —— 各机器人下的终端用户（封禁状态等）
      • tenant_settings—— 各机器人设置（Topics 管理群等）
      • message_map    —— 「管理员侧消息 → 原始用户」映射
      • topic_map      —— 「论坛话题(thread) ↔ 用户」映射
      • auto_replies / filters        —— 自动回复 / 关键词过滤
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = "bot.db"):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._db_path = db_path
                cls._instance._init_pragmas()
                cls._instance._init_db()
                cls._instance._migrate()
        return cls._instance

    def _conn(self) -> sqlite3.Connection:
        # timeout 配合 busy_timeout，缓解多租户高并发下的 "database is locked"
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_pragmas(self) -> None:
        """开启 WAL 等持久化 PRAGMA（WAL 为数据库级设置，仅需设置一次）。"""
        try:
            conn = sqlite3.connect(self._db_path, timeout=30.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.warning("设置 WAL PRAGMA 失败: %s", e)

    def _init_db(self) -> None:
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id        INTEGER PRIMARY KEY, username TEXT,
                    full_name TEXT,
                    joined_at TEXT DEFAULT (datetime('now')),
                    last_seen TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS tenants (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    token         TEXT NOT NULL UNIQUE,
                    bot_id        INTEGER,
                    bot_username  TEXT,
                    bot_name      TEXT,
                    owner_user_id INTEGER NOT NULL,
                    is_active     INTEGER DEFAULT 1,
                    created_at    TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS tenant_settings (
                    tenant_id    INTEGER PRIMARY KEY,
                    manage_group INTEGER,
                    welcome      TEXT
                );
                CREATE TABLE IF NOT EXISTS tenant_users (
                    tenant_id INTEGER NOT NULL,
                    user_id   INTEGER NOT NULL,
                    username  TEXT,
                    full_name TEXT,
                    is_banned INTEGER DEFAULT 0,
                    joined_at TEXT DEFAULT (datetime('now')),
                    last_seen TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (tenant_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS message_map (
                    tenant_id    INTEGER NOT NULL DEFAULT 0,
                    admin_msg_id INTEGER NOT NULL,
                    user_id      INTEGER NOT NULL,
                    user_msg_id  INTEGER,
                    created_at   TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (tenant_id, admin_msg_id)
                );
                CREATE TABLE IF NOT EXISTS topic_map (
                    tenant_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    user_id   INTEGER NOT NULL,
                    PRIMARY KEY (tenant_id, thread_id)
                );
                CREATE TABLE IF NOT EXISTS auto_replies (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id  INTEGER NOT NULL,
                    keyword    TEXT NOT NULL,
                    reply      TEXT NOT NULL,
                    match_type TEXT DEFAULT 'contains',
                    stop       INTEGER DEFAULT 0,
                    buttons    TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS filters (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    keyword   TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tenant_kv (
                    tenant_id INTEGER NOT NULL,
                    key       TEXT NOT NULL,
                    value     TEXT,
                    PRIMARY KEY (tenant_id, key)
                );
            """)
        logger.info("数据库初始化完成 (db=%s)", self._db_path)

    def _migrate(self) -> None:
        """对早期版本创建的数据库补充后续新增的列 / 重建不兼容的旧表。

        ``CREATE TABLE IF NOT EXISTS`` 不会修改已存在的表，因此旧库可能：
          • 缺少诸如 ``tenants.bot_id`` 等后来新增的字段；
          • 残留早期 schema 的 ``tenants.admin_id NOT NULL`` 列——新版 INSERT 不再
            写入该列，导致 ``NOT NULL constraint failed: tenants.admin_id``。
        这里先重建带有遗留列的 tenants 表，再通过 PRAGMA table_info 检测缺失列并用
        ALTER TABLE ADD COLUMN 补齐（均为幂等，可重复执行）。
        """
        self._rebuild_legacy_tenants()
        expected_columns = {
            "tenants": [
                ("bot_id", "INTEGER"),
                ("bot_username", "TEXT"),
                ("bot_name", "TEXT"),
                ("is_active", "INTEGER DEFAULT 1"),
                ("created_at", "TEXT"),
            ],
            "tenant_settings": [
                ("manage_group", "INTEGER"),
                ("welcome", "TEXT"),
            ],
            "auto_replies": [
                ("buttons", "TEXT DEFAULT ''"),
            ],
        }
        with self._conn() as c:
            for table, columns in expected_columns.items():
                existing = {
                    row["name"]
                    for row in c.execute(f"PRAGMA table_info({table})").fetchall()
                }
                if not existing:
                    # 表不存在（理论上 _init_db 已创建），跳过。
                    continue
                for name, definition in columns:
                    if name not in existing:
                        c.execute(
                            f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                        logger.info("数据库迁移：为 %s 增加列 %s", table, name)

    def _rebuild_legacy_tenants(self) -> None:
        """重建残留早期 ``admin_id`` 列的 tenants 表。

        早期版本的 ``tenants`` 表带有 ``admin_id NOT NULL`` 列；新版 ``add_tenant``
        不再写入该列，旧库插入时会触发
        ``NOT NULL constraint failed: tenants.admin_id``。这里把旧表数据迁移到符合
        当前 schema 的新表（如 ``owner_user_id`` 缺失/为空则回退使用 ``admin_id``），
        然后用新表替换旧表。幂等：表中已无 ``admin_id`` 列时直接返回。
        """
        # 单独使用一条连接，便于在事务外关闭外键约束以安全地重命名/替换表。
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=30000")
            cols = {row["name"] for row in
                    conn.execute("PRAGMA table_info(tenants)").fetchall()}
            if not cols or "admin_id" not in cols:
                return  # 表不存在或无遗留列，无需重建。

            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("BEGIN")
            conn.execute("""
                CREATE TABLE tenants__new (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    token         TEXT NOT NULL UNIQUE,
                    bot_id        INTEGER,
                    bot_username  TEXT,
                    bot_name      TEXT,
                    owner_user_id INTEGER NOT NULL,
                    is_active     INTEGER DEFAULT 1,
                    created_at    TEXT DEFAULT (datetime('now'))
                )""")
            # 仅复制两张表共有的列；owner_user_id 缺失/为空时回退到 admin_id。
            owner_expr = ("COALESCE(owner_user_id, admin_id)"
                          if "owner_user_id" in cols else "admin_id")
            select_cols = ", ".join([
                "id",
                "token",
                "bot_id" if "bot_id" in cols else "NULL",
                "bot_username" if "bot_username" in cols else "NULL",
                "bot_name" if "bot_name" in cols else "NULL",
                owner_expr,
                "is_active" if "is_active" in cols else "1",
                "created_at" if "created_at" in cols else "datetime('now')",
            ])
            conn.execute(
                f"""INSERT INTO tenants__new
                    (id, token, bot_id, bot_username, bot_name,
                     owner_user_id, is_active, created_at)
                    SELECT {select_cols} FROM tenants""")
            conn.execute("DROP TABLE tenants")
            conn.execute("ALTER TABLE tenants__new RENAME TO tenants")
            conn.execute("COMMIT")
            logger.info("数据库迁移：重建 tenants 表以移除遗留列 admin_id")
        except sqlite3.Error:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    # ── 通用租户键值设置（用于过滤器开关等）─────────────────

    def set_setting(self, tenant_id, key, value):
        with self._conn() as c:
            c.execute(
                """INSERT INTO tenant_kv(tenant_id,key,value) VALUES(?,?,?)
                   ON CONFLICT(tenant_id,key) DO UPDATE SET value=excluded.value""",
                (tenant_id, key, str(value)))

    def get_setting(self, tenant_id, key, default=None):
        with self._conn() as c:
            r = c.execute(
                "SELECT value FROM tenant_kv WHERE tenant_id=? AND key=?",
                (tenant_id, key)).fetchone()
            return r["value"] if r else default

    def get_bool_setting(self, tenant_id, key, default: bool) -> bool:
        v = self.get_setting(tenant_id, key, None)
        if v is None:
            return default
        return v in ("1", "true", "True", "on", "yes")

    # ── 平台用户 ───────────────────────────────────────────

    def upsert_user(self, uid, username, full_name):
        with self._conn() as c:
            c.execute("""INSERT INTO users (id,username,full_name) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                username=excluded.username, full_name=excluded.full_name,
                last_seen=datetime('now')""", (uid, username, full_name))

    # ── 租户（用户创建的机器人）─────────────────────────────

    def add_tenant(self, token, owner_user_id, bot_id=None,
                   bot_username="", bot_name="") -> int:
        with self._conn() as c:
            return c.execute(
                """INSERT INTO tenants(token,bot_id,bot_username,bot_name,owner_user_id)
                   VALUES(?,?,?,?,?)""",
                (token, bot_id, bot_username, bot_name, owner_user_id)).lastrowid

    def get_tenant(self, tid):
        with self._conn() as c:
            return c.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()

    def get_tenant_by_token(self, token):
        with self._conn() as c:
            return c.execute("SELECT * FROM tenants WHERE token=?", (token,)).fetchone()

    def get_active_tenants(self):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM tenants WHERE is_active=1 ORDER BY id").fetchall()

    def get_user_tenants(self, owner_user_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM tenants WHERE owner_user_id=? ORDER BY id",
                (owner_user_id,)).fetchall()

    def deactivate_tenant(self, tid):
        with self._conn() as c:
            c.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tid,))

    def delete_tenant(self, tid):
        with self._conn() as c:
            for tbl in ("tenants", "tenant_settings", "tenant_users", "message_map",
                        "topic_map", "auto_replies", "filters", "tenant_kv"):
                col = "id" if tbl == "tenants" else "tenant_id"
                c.execute(f"DELETE FROM {tbl} WHERE {col}=?", (tid,))

    # ── 租户设置 ─────────────────────────────────────────────

    def set_manage_group(self, tenant_id, group_id):
        with self._conn() as c:
            c.execute(
                """INSERT INTO tenant_settings(tenant_id,manage_group) VALUES(?,?)
                   ON CONFLICT(tenant_id) DO UPDATE SET manage_group=excluded.manage_group""",
                (tenant_id, group_id))

    def get_manage_group(self, tenant_id):
        with self._conn() as c:
            r = c.execute(
                "SELECT manage_group FROM tenant_settings WHERE tenant_id=?",
                (tenant_id,)).fetchone()
            return r["manage_group"] if r else None

    # ── 租户终端用户（按租户隔离）───────────────────────────

    def upsert_tenant_user(self, tenant_id, uid, username, full_name):
        with self._conn() as c:
            c.execute(
                """INSERT INTO tenant_users(tenant_id,user_id,username,full_name)
                   VALUES(?,?,?,?)
                   ON CONFLICT(tenant_id,user_id) DO UPDATE SET
                   username=excluded.username, full_name=excluded.full_name,
                   last_seen=datetime('now')""",
                (tenant_id, uid, username, full_name))

    def get_tenant_user(self, tenant_id, uid):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM tenant_users WHERE tenant_id=? AND user_id=?",
                (tenant_id, uid)).fetchone()

    def ban_user(self, tenant_id, uid):
        with self._conn() as c:
            c.execute(
                "UPDATE tenant_users SET is_banned=1 WHERE tenant_id=? AND user_id=?",
                (tenant_id, uid))

    def unban_user(self, tenant_id, uid):
        with self._conn() as c:
            c.execute(
                "UPDATE tenant_users SET is_banned=0 WHERE tenant_id=? AND user_id=?",
                (tenant_id, uid))

    def is_banned(self, tenant_id, uid):
        u = self.get_tenant_user(tenant_id, uid)
        return bool(u and u["is_banned"])

    def get_tenant_user_count(self, tenant_id):
        with self._conn() as c:
            total = c.execute(
                "SELECT COUNT(*) FROM tenant_users WHERE tenant_id=?",
                (tenant_id,)).fetchone()[0]
            banned = c.execute(
                "SELECT COUNT(*) FROM tenant_users WHERE tenant_id=? AND is_banned=1",
                (tenant_id,)).fetchone()[0]
            active_7d = c.execute(
                "SELECT COUNT(*) FROM tenant_users "
                "WHERE tenant_id=? AND last_seen >= datetime('now','-7 days')",
                (tenant_id,)).fetchone()[0]
            new_7d = c.execute(
                "SELECT COUNT(*) FROM tenant_users "
                "WHERE tenant_id=? AND joined_at >= datetime('now','-7 days')",
                (tenant_id,)).fetchone()[0]
            return {
                "total": total,
                "active": total - banned,
                "banned": banned,
                "active_7d": active_7d,
                "new_7d": new_7d,
            }

    def get_banned_tenant_users(self, tenant_id, limit=20):
        """返回该租户下已封禁的用户（最近封禁的在前），用于控制面板的封禁管理。"""
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM tenant_users "
                "WHERE tenant_id=? AND is_banned=1 "
                "ORDER BY last_seen DESC LIMIT ?",
                (tenant_id, limit)).fetchall()

    def get_tenant_user_ids(self, tenant_id, only_active=True):
        """返回该租户下的用户 ID 列表，用于群发广播。默认排除已封禁用户。"""
        sql = "SELECT user_id FROM tenant_users WHERE tenant_id=?"
        if only_active:
            sql += " AND is_banned=0"
        with self._conn() as c:
            return [r["user_id"] for r in c.execute(sql, (tenant_id,)).fetchall()]

    # ── 双向私聊消息映射（按租户隔离）───────────────────────

    def save_message_map(self, tenant_id, admin_msg_id, user_id, user_msg_id=None):
        with self._conn() as c:
            c.execute(
                """INSERT INTO message_map(tenant_id,admin_msg_id,user_id,user_msg_id)
                   VALUES(?,?,?,?)
                   ON CONFLICT(tenant_id,admin_msg_id) DO UPDATE SET
                   user_id=excluded.user_id, user_msg_id=excluded.user_msg_id""",
                (tenant_id, admin_msg_id, user_id, user_msg_id))

    def get_mapped_user(self, tenant_id, admin_msg_id):
        with self._conn() as c:
            r = c.execute(
                "SELECT user_id FROM message_map WHERE tenant_id=? AND admin_msg_id=?",
                (tenant_id, admin_msg_id)).fetchone()
            return r["user_id"] if r else None

    # ── Topics（论坛话题 ↔ 用户）──────────────────────────

    def set_topic(self, tenant_id, thread_id, user_id):
        with self._conn() as c:
            c.execute(
                """INSERT INTO topic_map(tenant_id,thread_id,user_id) VALUES(?,?,?)
                   ON CONFLICT(tenant_id,thread_id) DO UPDATE SET user_id=excluded.user_id""",
                (tenant_id, thread_id, user_id))

    def get_topic_user(self, tenant_id, thread_id):
        with self._conn() as c:
            r = c.execute(
                "SELECT user_id FROM topic_map WHERE tenant_id=? AND thread_id=?",
                (tenant_id, thread_id)).fetchone()
            return r["user_id"] if r else None

    def get_user_topic(self, tenant_id, user_id):
        with self._conn() as c:
            r = c.execute(
                "SELECT thread_id FROM topic_map WHERE tenant_id=? AND user_id=?",
                (tenant_id, user_id)).fetchone()
            return r["thread_id"] if r else None

    # ── 自动回复 / 过滤 ─────────────────────────────────────

    def add_auto_reply(self, tenant_id, keyword, reply, match_type="contains", stop=0,
                       buttons=""):
        with self._conn() as c:
            return c.execute(
                """INSERT INTO auto_replies(tenant_id,keyword,reply,match_type,stop,buttons)
                   VALUES(?,?,?,?,?,?)""",
                (tenant_id, keyword, reply, match_type, stop, buttons)).lastrowid

    def get_auto_replies(self, tenant_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM auto_replies WHERE tenant_id=? ORDER BY id",
                (tenant_id,)).fetchall()

    def delete_auto_reply(self, tenant_id, rid):
        with self._conn() as c:
            c.execute("DELETE FROM auto_replies WHERE tenant_id=? AND id=?",
                      (tenant_id, rid))

    def add_filter(self, tenant_id, keyword):
        with self._conn() as c:
            return c.execute(
                "INSERT INTO filters(tenant_id,keyword) VALUES(?,?)",
                (tenant_id, keyword)).lastrowid

    def get_filters(self, tenant_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM filters WHERE tenant_id=? ORDER BY id",
                (tenant_id,)).fetchall()

    def delete_filter(self, tenant_id, fid):
        with self._conn() as c:
            c.execute("DELETE FROM filters WHERE tenant_id=? AND id=?", (tenant_id, fid))

