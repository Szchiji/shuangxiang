import json
import sqlite3
import threading
from typing import Optional


class Database:
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
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT, interval_s INTEGER, target TEXT DEFAULT 'all',
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS broadcast_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT, recipient_count INTEGER,
                    sent_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS tenants (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    token         TEXT NOT NULL UNIQUE,
                    bot_username  TEXT,
                    bot_name      TEXT,
                    owner_user_id INTEGER NOT NULL,
                    admin_id      INTEGER NOT NULL,
                    plan          TEXT DEFAULT 'free',
                    is_active     INTEGER DEFAULT 1,
                    created_at    TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS categories (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    name      TEXT NOT NULL,
                    emoji     TEXT DEFAULT '📦',
                    sort_order INTEGER DEFAULT 0,
                    is_active  INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS products (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id   INTEGER,
                    category_id INTEGER,
                    name        TEXT NOT NULL,
                    description TEXT,
                    price       REAL NOT NULL,
                    stock       INTEGER DEFAULT -1,
                    image_url   TEXT,
                    is_active   INTEGER DEFAULT 1,
                    created_at  TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (category_id) REFERENCES categories(id)
                );
                CREATE TABLE IF NOT EXISTS cart_items (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    tenant_id  INTEGER,
                    product_id INTEGER NOT NULL,
                    quantity   INTEGER DEFAULT 1,
                    added_at   TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    tenant_id  INTEGER,
                    total      REAL NOT NULL,
                    status     TEXT DEFAULT 'pending',
                    note       TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS order_items (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id   INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    quantity   INTEGER NOT NULL,
                    price      REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forms (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id   INTEGER,
                    slug        TEXT NOT NULL,
                    title       TEXT NOT NULL,
                    description TEXT,
                    is_active   INTEGER DEFAULT 1,
                    created_at  TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS form_steps (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    form_id     INTEGER NOT NULL,
                    step_number INTEGER NOT NULL,
                    field_name  TEXT NOT NULL,
                    prompt      TEXT NOT NULL,
                    input_type  TEXT DEFAULT 'text',
                    choices     TEXT,
                    is_required INTEGER DEFAULT 1,
                    FOREIGN KEY (form_id) REFERENCES forms(id)
                );
                CREATE TABLE IF NOT EXISTS form_responses (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    form_id      INTEGER NOT NULL,
                    user_id      INTEGER NOT NULL,
                    tenant_id    INTEGER,
                    responses    TEXT NOT NULL,
                    submitted_at TEXT DEFAULT (datetime('now'))
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

    # ── 管理员 ───────────────────────────────────────────────

    def add_admin(self, uid, role, granted_by, note=""):
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

    def update_admin_role(self, uid, role):
        with self._conn() as c:
            c.execute("UPDATE admins SET role=? WHERE id=?", (role, uid))

    def is_admin(self, uid):
        return self.get_admin_role(uid) >= 1

    # ── 定时任务 ─────────────────────────────────────────────

    def add_schedule(self, content, interval_s, target="all"):
        with self._conn() as c:
            return c.execute(
                "INSERT INTO scheduled_messages(content,interval_s,target) VALUES(?,?,?)",
                (content, interval_s, target)).lastrowid

    def get_active_schedules(self):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM scheduled_messages WHERE is_active=1").fetchall()

    def delete_schedule(self, sid):
        with self._conn() as c:
            c.execute("DELETE FROM scheduled_messages WHERE id=?", (sid,))

    def log_broadcast(self, content, count):
        with self._conn() as c:
            c.execute("INSERT INTO broadcast_log(content,recipient_count) VALUES(?,?)",
                      (content, count))

    # ── 多租户 ───────────────────────────────────────────────

    def add_tenant(self, token, bot_username, bot_name, owner_user_id, admin_id) -> int:
        with self._conn() as c:
            return c.execute("""INSERT INTO tenants
                (token,bot_username,bot_name,owner_user_id,admin_id)
                VALUES(?,?,?,?,?)""",
                (token, bot_username, bot_name, owner_user_id, admin_id)).lastrowid

    def get_active_tenants(self):
        with self._conn() as c:
            return c.execute("SELECT * FROM tenants WHERE is_active=1").fetchall()

    def get_tenant(self, tid):
        with self._conn() as c:
            return c.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()

    def get_all_tenants(self):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM tenants ORDER BY created_at DESC").fetchall()

    def get_user_tenants(self, owner_user_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM tenants WHERE owner_user_id=?",
                (owner_user_id,)).fetchall()

    def deactivate_tenant(self, tid):
        with self._conn() as c:
            c.execute("UPDATE tenants SET is_active=0 WHERE id=?", (tid,))

    def activate_tenant(self, tid):
        with self._conn() as c:
            c.execute("UPDATE tenants SET is_active=1 WHERE id=?", (tid,))

    # ── 商店：分类 ───────────────────────────────────────────

    def get_categories(self, tenant_id=None):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM categories WHERE tenant_id IS ? AND is_active=1 ORDER BY sort_order",
                (tenant_id,)).fetchall()

    def get_category(self, cid):
        with self._conn() as c:
            return c.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()

    def add_category(self, tenant_id, name, emoji="📦"):
        with self._conn() as c:
            return c.execute(
                "INSERT INTO categories(tenant_id,name,emoji) VALUES(?,?,?)",
                (tenant_id, name, emoji)).lastrowid

    def delete_category(self, cid):
        with self._conn() as c:
            c.execute("UPDATE categories SET is_active=0 WHERE id=?", (cid,))

    # ── 商店：商品 ───────────────────────────────────────────

    def get_products(self, category_id, tenant_id=None, page=1, per_page=5):
        offset = (page - 1) * per_page
        with self._conn() as c:
            rows = c.execute("""SELECT * FROM products
                WHERE category_id=? AND tenant_id IS ? AND is_active=1
                ORDER BY id LIMIT ? OFFSET ?""",
                (category_id, tenant_id, per_page, offset)).fetchall()
            total = c.execute("""SELECT COUNT(*) FROM products
                WHERE category_id=? AND tenant_id IS ? AND is_active=1""",
                (category_id, tenant_id)).fetchone()[0]
            return rows, total

    def get_all_products(self, tenant_id=None):
        with self._conn() as c:
            return c.execute("""SELECT p.*,c.name AS cat_name FROM products p
                LEFT JOIN categories c ON p.category_id=c.id
                WHERE p.tenant_id IS ? AND p.is_active=1 ORDER BY p.id""",
                (tenant_id,)).fetchall()

    def get_product(self, pid):
        with self._conn() as c:
            return c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()

    def add_product(self, tenant_id, category_id, name, description, price,
                    stock=-1, image_url=""):
        with self._conn() as c:
            return c.execute("""INSERT INTO products
                (tenant_id,category_id,name,description,price,stock,image_url)
                VALUES(?,?,?,?,?,?,?)""",
                (tenant_id, category_id, name, description,
                 price, stock, image_url)).lastrowid

    def delete_product(self, pid):
        with self._conn() as c:
            c.execute("UPDATE products SET is_active=0 WHERE id=?", (pid,))

    # ── 商店：购物车 ─────────────────────────────────────────

    def get_cart_items(self, user_id, tenant_id=None):
        with self._conn() as c:
            return c.execute("""SELECT ci.id AS cart_id, ci.quantity,
                p.id AS product_id, p.name, p.price
                FROM cart_items ci JOIN products p ON ci.product_id=p.id
                WHERE ci.user_id=? AND ci.tenant_id IS ?""",
                (user_id, tenant_id)).fetchall()

    def add_to_cart(self, user_id, product_id, tenant_id=None):
        with self._conn() as c:
            existing = c.execute("""SELECT id,quantity FROM cart_items
                WHERE user_id=? AND product_id=? AND tenant_id IS ?""",
                (user_id, product_id, tenant_id)).fetchone()
            if existing:
                c.execute("UPDATE cart_items SET quantity=? WHERE id=?",
                          (existing["quantity"] + 1, existing["id"]))
            else:
                c.execute(
                    "INSERT INTO cart_items(user_id,product_id,tenant_id) VALUES(?,?,?)",
                    (user_id, product_id, tenant_id))

    def remove_cart_item(self, cart_id):
        with self._conn() as c:
            c.execute("DELETE FROM cart_items WHERE id=?", (cart_id,))

    def clear_cart(self, user_id, tenant_id=None):
        with self._conn() as c:
            c.execute("DELETE FROM cart_items WHERE user_id=? AND tenant_id IS ?",
                      (user_id, tenant_id))

    # ── 商店：订单 ───────────────────────────────────────────

    def create_order(self, user_id, tenant_id, items) -> int:
        total = sum(i["price"] * i["quantity"] for i in items)
        with self._conn() as c:
            oid = c.execute(
                "INSERT INTO orders(user_id,tenant_id,total) VALUES(?,?,?)",
                (user_id, tenant_id, total)).lastrowid
            for item in items:
                c.execute("""INSERT INTO order_items
                    (order_id,product_id,quantity,price) VALUES(?,?,?,?)""",
                    (oid, item["product_id"], item["quantity"], item["price"]))
            return oid

    def get_orders(self, user_id=None, tenant_id=None, limit=50):
        with self._conn() as c:
            if user_id:
                return c.execute("""SELECT o.*,u.full_name,u.username FROM orders o
                    LEFT JOIN users u ON o.user_id=u.id
                    WHERE o.user_id=? AND o.tenant_id IS ?
                    ORDER BY o.created_at DESC LIMIT ?""",
                    (user_id, tenant_id, limit)).fetchall()
            return c.execute("""SELECT o.*,u.full_name,u.username FROM orders o
                LEFT JOIN users u ON o.user_id=u.id
                WHERE o.tenant_id IS ?
                ORDER BY o.created_at DESC LIMIT ?""",
                (tenant_id, limit)).fetchall()

    def get_order_items(self, order_id):
        with self._conn() as c:
            return c.execute("""SELECT oi.*,p.name FROM order_items oi
                JOIN products p ON oi.product_id=p.id WHERE oi.order_id=?""",
                (order_id,)).fetchall()

    def update_order_status(self, order_id, status):
        with self._conn() as c:
            c.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))

    # ── 表单 ─────────────────────────────────────────────────

    def get_forms(self, tenant_id=None):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM forms WHERE tenant_id IS ? AND is_active=1",
                (tenant_id,)).fetchall()

    def get_form(self, fid):
        with self._conn() as c:
            return c.execute("SELECT * FROM forms WHERE id=?", (fid,)).fetchone()

    def get_form_by_slug(self, slug, tenant_id=None):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM forms WHERE slug=? AND tenant_id IS ? AND is_active=1",
                (slug, tenant_id)).fetchone()

    def add_form(self, tenant_id, slug, title, description=""):
        with self._conn() as c:
            return c.execute(
                "INSERT INTO forms(tenant_id,slug,title,description) VALUES(?,?,?,?)",
                (tenant_id, slug, title, description)).lastrowid

    def delete_form(self, fid):
        with self._conn() as c:
            c.execute("UPDATE forms SET is_active=0 WHERE id=?", (fid,))

    def get_form_steps(self, form_id):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM form_steps WHERE form_id=? ORDER BY step_number",
                (form_id,)).fetchall()

    def add_form_step(self, form_id, step_number, field_name, prompt,
                      input_type="text", choices=None, is_required=1):
        with self._conn() as c:
            return c.execute("""INSERT INTO form_steps
                (form_id,step_number,field_name,prompt,input_type,choices,is_required)
                VALUES(?,?,?,?,?,?,?)""",
                (form_id, step_number, field_name, prompt, input_type,
                 json.dumps(choices) if choices else None, is_required)).lastrowid

    def delete_form_step(self, step_id):
        with self._conn() as c:
            c.execute("DELETE FROM form_steps WHERE id=?", (step_id,))

    def save_form_response(self, form_id, user_id, tenant_id, responses: str):
        with self._conn() as c:
            c.execute("""INSERT INTO form_responses
                (form_id,user_id,tenant_id,responses) VALUES(?,?,?,?)""",
                (form_id, user_id, tenant_id, responses))

    def get_form_responses(self, form_id, limit=100):
        with self._conn() as c:
            return c.execute("""SELECT fr.*,u.full_name,u.username
                FROM form_responses fr
                LEFT JOIN users u ON fr.user_id=u.id
                WHERE fr.form_id=?
                ORDER BY fr.submitted_at DESC LIMIT ?""",
                (form_id, limit)).fetchall()
