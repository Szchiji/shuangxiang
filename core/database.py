import sqlite3
import threading


class Database:
    """SQLite 单例。

    存储平台用户、管理员、平台消息日志，以及多租户机器人相关数据：
      • tenants       —— 用户创建的双向私聊机器人（每个一行）
      • tenant_users  —— 各租户机器人下的终端用户（按租户隔离封禁等状态）
      • message_map   —— 「管理员侧消息 → 原始用户」映射（按租户隔离）
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = "bot.db"):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._db_path = db_path
                cls._instance._init_db()
        return cls._instance

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id        INTEGER PRIMARY KEY, username TEXT,
                    full_name TEXT, is_banned INTEGER DEFAULT 0,
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
            """)
        print("[DB] ✅ 数据库初始化完成")

    # ── 平台用户 ─────────────────────────────────────────────

    def upsert_user(self, uid, username, full_name):
        with self._conn() as c:
            c.execute("""INSERT INTO users (id,username,full_name) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                username=excluded.username, full_name=excluded.full_name,
                last_seen=datetime('now')""", (uid, username, full_name))

    def get_user(self, uid):
        with self._conn() as c:
            return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    # ── 平台消息日志 ─────────────────────────────────────────

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
            c.execute("DELETE FROM tenants WHERE id=?", (tid,))
            c.execute("DELETE FROM tenant_users WHERE tenant_id=?", (tid,))
            c.execute("DELETE FROM message_map WHERE tenant_id=?", (tid,))

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
            return {"total": total, "active": total - banned, "banned": banned}

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

    # ── 管理员（平台级）─────────────────────────────────────

    def get_admin_role(self, uid):
        with self._conn() as c:
            r = c.execute("SELECT role FROM admins WHERE id=?", (uid,)).fetchone()
            return r["role"] if r else 0

    def is_admin(self, uid):
        return self.get_admin_role(uid) >= 1
