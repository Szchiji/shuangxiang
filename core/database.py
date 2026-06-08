import sqlite3
import threading


class Database:
    """SQLite 单例，存储用户、管理员、消息及双向消息映射。"""

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
                CREATE TABLE IF NOT EXISTS message_map (
                    admin_msg_id INTEGER PRIMARY KEY,
                    user_id      INTEGER NOT NULL,
                    user_msg_id  INTEGER,
                    created_at   TEXT DEFAULT (datetime('now'))
                );
            """)
        print("[DB] ✅ 数据库初始化完成")

    # ── 用户 ─────────────────────────────────────────────────

    def upsert_user(self, uid, username, full_name):
        with self._conn() as c:
            c.execute("""INSERT INTO users (id,username,full_name) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                username=excluded.username, full_name=excluded.full_name,
                last_seen=datetime('now')""", (uid, username, full_name))

    def get_user(self, uid):
        with self._conn() as c:
            return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    def get_all_users(self, include_banned=False):
        with self._conn() as c:
            if include_banned:
                return c.execute("SELECT * FROM users").fetchall()
            return c.execute("SELECT * FROM users WHERE is_banned=0").fetchall()

    def get_user_count(self):
        with self._conn() as c:
            total  = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            banned = c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
            return {"total": total, "active": total - banned, "banned": banned}

    def ban_user(self, uid):
        with self._conn() as c:
            c.execute("UPDATE users SET is_banned=1 WHERE id=?", (uid,))

    def unban_user(self, uid):
        with self._conn() as c:
            c.execute("UPDATE users SET is_banned=0 WHERE id=?", (uid,))

    def is_banned(self, uid):
        u = self.get_user(uid)
        return bool(u and u["is_banned"])

    # ── 消息 ─────────────────────────────────────────────────

    def log_message(self, uid, direction, content):
        with self._conn() as c:
            c.execute("INSERT INTO messages(user_id,direction,content) VALUES(?,?,?)",
                      (uid, direction, content))

    def get_user_messages(self, uid, limit=10):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM messages WHERE user_id=? ORDER BY sent_at DESC LIMIT ?",
                (uid, limit)).fetchall()

    # ── 双向私聊消息映射 ─────────────────────────────────────
    # 记录「转发到管理员的消息 → 原始用户」的映射，
    # 使管理员可以直接回复任意消息（含图片/语音等）给对应用户。

    def save_message_map(self, admin_msg_id, user_id, user_msg_id=None):
        with self._conn() as c:
            c.execute(
                """INSERT INTO message_map(admin_msg_id,user_id,user_msg_id)
                   VALUES(?,?,?)
                   ON CONFLICT(admin_msg_id) DO UPDATE SET
                   user_id=excluded.user_id, user_msg_id=excluded.user_msg_id""",
                (admin_msg_id, user_id, user_msg_id))

    def get_mapped_user(self, admin_msg_id):
        with self._conn() as c:
            r = c.execute(
                "SELECT user_id FROM message_map WHERE admin_msg_id=?",
                (admin_msg_id,)).fetchone()
            return r["user_id"] if r else None

    # ── 管理员 ───────────────────────────────────────────────

    def add_admin(self, uid, role=1, granted_by=None, note=""):
        with self._conn() as c:
            c.execute("""INSERT INTO admins(id,role,granted_by,note) VALUES(?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET role=excluded.role,
                granted_by=excluded.granted_by, note=excluded.note,
                granted_at=datetime('now')""", (uid, role, granted_by, note))

    def remove_admin(self, uid):
        with self._conn() as c:
            c.execute("DELETE FROM admins WHERE id=?", (uid,))

    def get_admin_role(self, uid):
        with self._conn() as c:
            r = c.execute("SELECT role FROM admins WHERE id=?", (uid,)).fetchone()
            return r["role"] if r else 0

    def get_all_admins(self):
        with self._conn() as c:
            return c.execute("""SELECT a.*,u.username,u.full_name FROM admins a
                LEFT JOIN users u ON a.id=u.id ORDER BY a.role DESC""").fetchall()

    def is_admin(self, uid):
        return self.get_admin_role(uid) >= 1
