"""数据库迁移测试：旧 schema 兼容。"""

import sqlite3

from core.database import Database


def test_rebuild_legacy_tenants_admin_id(tmp_path):
    """带遗留 admin_id NOT NULL 列的旧库应被重建，add_tenant 不再报错。"""
    db_path = str(tmp_path / "legacy.db")
    # 构造早期版本的 tenants 表（含 admin_id NOT NULL，无 owner_user_id）。
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE tenants (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            token        TEXT NOT NULL UNIQUE,
            bot_username TEXT,
            admin_id     INTEGER NOT NULL
        );
        INSERT INTO tenants (token, bot_username, admin_id)
        VALUES ('111:OLD', 'oldbot', 42);
        """
    )
    conn.commit()
    conn.close()

    Database._instance = None
    try:
        db = Database(db_path=db_path)
        # 旧行的 admin_id 被迁移到 owner_user_id。
        row = db.get_tenant(1)
        assert row["owner_user_id"] == 42
        # 关键：新插入不再因 admin_id NOT NULL 失败。
        tid = db.add_tenant("222:NEW", 7, bot_id=222,
                            bot_username="newbot", bot_name="New")
        assert db.get_tenant(tid)["owner_user_id"] == 7
        cols = {r["name"] for r in
                db._conn().execute("PRAGMA table_info(tenants)").fetchall()}
        assert "admin_id" not in cols
    finally:
        Database._instance = None
