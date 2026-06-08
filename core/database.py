import logging
import sqlite3
import threading

logger = logging.getLogger("shuangxiang.db")


class Database:
    """SQLite 单例。承载多租户机器人平台的全部数据。

    平台级： users / admins / messages
    租户级（均按 tenant_id 隔离）：
      • tenants        —— 用户创建的机器人
      • tenant_users   —— 各机器人下的终端用户（封禁状态等）
      • tenant_settings—— 各机器人设置（Topics 管理群等）
      • message_map    —— 「管理员侧消息 → 原始用户」映射
      • topic_map      —— 「论坛话题(thread) ↔ 用户」映射
      • auto_replies / filters        —— 自动回复 / 关键词过滤
      • menu_items                    —— 菜单 / 子菜单
      • forms / form_steps / form_responses —— 引导式表单
      • categories / products / cart_items / orders / order_items —— 数字商店
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
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY, role INTEGER DEFAULT 1,
                    granted_by INTEGER, note TEXT,
                    granted_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER, direction TEXT, content TEXT,
                    sent_at TEXT DEFAULT (datetime('now'))
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
                CREATE TABLE IF NOT EXISTS menu_items (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    parent_id INTEGER DEFAULT 0,
                    label     TEXT NOT NULL,
                    content   TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS forms (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id  INTEGER NOT NULL,
                    title      TEXT NOT NULL,
                    is_active  INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS form_steps (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    form_id     INTEGER NOT NULL,
                    step_number INTEGER NOT NULL,
                    prompt      TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS form_responses (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    form_id      INTEGER NOT NULL,
                    tenant_id    INTEGER NOT NULL,
                    user_id      INTEGER NOT NULL,
                    responses    TEXT NOT NULL,
                    submitted_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS categories (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    name      TEXT NOT NULL,
                    emoji     TEXT DEFAULT '📦'
                );
                CREATE TABLE IF NOT EXISTS products (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id   INTEGER NOT NULL,
                    category_id INTEGER NOT NULL,
                    name        TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    price       REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cart_items (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id  INTEGER NOT NULL,
                    user_id    INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    quantity   INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id  INTEGER NOT NULL,
                    user_id    INTEGER NOT NULL,
                    total      REAL NOT NULL,
                    status     TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS order_items (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id   INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    name       TEXT NOT NULL,
                    quantity   INTEGER NOT NULL,
                    price      REAL NOT NULL
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

    # ── 平台用户 / 消息日志 ─────────────────────────────────

    def upsert_user(self, uid, username, full_name):
        with self._conn() as c:
            c.execute("""INSERT INTO users (id,username,full_name) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                username=excluded.username, full_name=excluded.full_name,
                last_seen=datetime('now')""", (uid, username, full_name))

    def get_user(self, uid):
        with self._conn() as c:
            return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    def log_message(self, uid, direction, content):
        with self._conn() as c:
            c.execute("INSERT INTO messages(user_id,direction,content) VALUES(?,?,?)",
                      (uid, direction, content))

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
            # 先删除通过外键间接关联到本租户的子表数据
            c.execute(
                "DELETE FROM form_steps WHERE form_id IN "
                "(SELECT id FROM forms WHERE tenant_id=?)", (tid,))
            c.execute(
                "DELETE FROM order_items WHERE order_id IN "
                "(SELECT id FROM orders WHERE tenant_id=?)", (tid,))
            for tbl in ("tenants", "tenant_settings", "tenant_users", "message_map",
                        "topic_map", "auto_replies", "filters", "menu_items",
                        "forms", "form_responses", "categories", "products",
                        "cart_items", "orders", "tenant_kv"):
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

    # ── 菜单 / 子菜单 ───────────────────────────────────────

    def add_menu_item(self, tenant_id, parent_id, label, content=""):
        with self._conn() as c:
            return c.execute(
                """INSERT INTO menu_items(tenant_id,parent_id,label,content)
                   VALUES(?,?,?,?)""",
                (tenant_id, parent_id, label, content)).lastrowid

    def get_menu_item(self, tenant_id, item_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM menu_items WHERE tenant_id=? AND id=?",
                (tenant_id, item_id)).fetchone()

    def get_menu_children(self, tenant_id, parent_id):
        with self._conn() as c:
            return c.execute(
                """SELECT * FROM menu_items WHERE tenant_id=? AND parent_id=?
                   ORDER BY sort_order, id""",
                (tenant_id, parent_id)).fetchall()

    def delete_menu_item(self, tenant_id, item_id):
        with self._conn() as c:
            c.execute("DELETE FROM menu_items WHERE tenant_id=? AND id=?",
                      (tenant_id, item_id))

    # ── 表单 ────────────────────────────────────────────────

    def add_form(self, tenant_id, title):
        with self._conn() as c:
            return c.execute(
                "INSERT INTO forms(tenant_id,title) VALUES(?,?)",
                (tenant_id, title)).lastrowid

    def get_forms(self, tenant_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM forms WHERE tenant_id=? AND is_active=1 ORDER BY id",
                (tenant_id,)).fetchall()

    def get_form(self, tenant_id, form_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM forms WHERE tenant_id=? AND id=?",
                (tenant_id, form_id)).fetchone()

    def delete_form(self, tenant_id, form_id):
        with self._conn() as c:
            c.execute("DELETE FROM forms WHERE tenant_id=? AND id=?", (tenant_id, form_id))
            c.execute("DELETE FROM form_steps WHERE form_id=?", (form_id,))

    def add_form_step(self, form_id, prompt):
        with self._conn() as c:
            n = c.execute(
                "SELECT COALESCE(MAX(step_number),0)+1 FROM form_steps WHERE form_id=?",
                (form_id,)).fetchone()[0]
            c.execute(
                "INSERT INTO form_steps(form_id,step_number,prompt) VALUES(?,?,?)",
                (form_id, n, prompt))
            return n

    def get_form_steps(self, form_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM form_steps WHERE form_id=? ORDER BY step_number",
                (form_id,)).fetchall()

    def save_form_response(self, form_id, tenant_id, user_id, responses):
        with self._conn() as c:
            return c.execute(
                """INSERT INTO form_responses(form_id,tenant_id,user_id,responses)
                   VALUES(?,?,?,?)""",
                (form_id, tenant_id, user_id, responses)).lastrowid

    # ── 数字商店 ─────────────────────────────────────────────

    def add_category(self, tenant_id, name, emoji="📦"):
        with self._conn() as c:
            return c.execute(
                "INSERT INTO categories(tenant_id,name,emoji) VALUES(?,?,?)",
                (tenant_id, name, emoji)).lastrowid

    def get_categories(self, tenant_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM categories WHERE tenant_id=? ORDER BY id",
                (tenant_id,)).fetchall()

    def get_category(self, tenant_id, cid):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM categories WHERE tenant_id=? AND id=?",
                (tenant_id, cid)).fetchone()

    def delete_category(self, tenant_id, cid):
        with self._conn() as c:
            c.execute("DELETE FROM categories WHERE tenant_id=? AND id=?", (tenant_id, cid))
            c.execute("DELETE FROM products WHERE tenant_id=? AND category_id=?",
                      (tenant_id, cid))

    def add_product(self, tenant_id, category_id, name, description, price):
        with self._conn() as c:
            return c.execute(
                """INSERT INTO products(tenant_id,category_id,name,description,price)
                   VALUES(?,?,?,?,?)""",
                (tenant_id, category_id, name, description, price)).lastrowid

    def get_products(self, tenant_id, category_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM products WHERE tenant_id=? AND category_id=? ORDER BY id",
                (tenant_id, category_id)).fetchall()

    def get_product(self, tenant_id, pid):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM products WHERE tenant_id=? AND id=?",
                (tenant_id, pid)).fetchone()

    def delete_product(self, tenant_id, pid):
        with self._conn() as c:
            c.execute("DELETE FROM products WHERE tenant_id=? AND id=?", (tenant_id, pid))

    def add_to_cart(self, tenant_id, user_id, product_id):
        with self._conn() as c:
            row = c.execute(
                """SELECT id,quantity FROM cart_items
                   WHERE tenant_id=? AND user_id=? AND product_id=?""",
                (tenant_id, user_id, product_id)).fetchone()
            if row:
                c.execute("UPDATE cart_items SET quantity=quantity+1 WHERE id=?",
                          (row["id"],))
            else:
                c.execute(
                    """INSERT INTO cart_items(tenant_id,user_id,product_id,quantity)
                       VALUES(?,?,?,1)""",
                    (tenant_id, user_id, product_id))

    def get_cart(self, tenant_id, user_id):
        with self._conn() as c:
            return c.execute(
                """SELECT ci.id, ci.quantity, p.name, p.price, p.id AS product_id
                   FROM cart_items ci JOIN products p ON ci.product_id=p.id
                   WHERE ci.tenant_id=? AND ci.user_id=?""",
                (tenant_id, user_id)).fetchall()

    def clear_cart(self, tenant_id, user_id):
        with self._conn() as c:
            c.execute("DELETE FROM cart_items WHERE tenant_id=? AND user_id=?",
                      (tenant_id, user_id))

    def create_order(self, tenant_id, user_id, cart_rows) -> int:
        total = sum(r["price"] * r["quantity"] for r in cart_rows)
        with self._conn() as c:
            oid = c.execute(
                "INSERT INTO orders(tenant_id,user_id,total) VALUES(?,?,?)",
                (tenant_id, user_id, total)).lastrowid
            for r in cart_rows:
                c.execute(
                    """INSERT INTO order_items(order_id,product_id,name,quantity,price)
                       VALUES(?,?,?,?,?)""",
                    (oid, r["product_id"], r["name"], r["quantity"], r["price"]))
        return oid

    def get_order(self, tenant_id, oid):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM orders WHERE tenant_id=? AND id=?",
                (tenant_id, oid)).fetchone()

    # ── 管理员（平台级）─────────────────────────────────────

    def get_admin_role(self, uid):
        with self._conn() as c:
            r = c.execute("SELECT role FROM admins WHERE id=?", (uid,)).fetchone()
            return r["role"] if r else 0

    def is_admin(self, uid):
        return self.get_admin_role(uid) >= 1
