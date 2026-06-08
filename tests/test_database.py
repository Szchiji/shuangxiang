"""数据库加固与设置相关测试。"""

import sqlite3


def test_wal_enabled(db, tmp_path):
    jm = sqlite3.connect(db._db_path).execute("PRAGMA journal_mode").fetchone()[0]
    assert jm.lower() == "wal"


def test_bool_setting_default_and_override(db):
    # 默认值
    assert db.get_bool_setting(1, "antiflood", True) is True
    assert db.get_bool_setting(1, "alphabet_latin", False) is False
    # 写入后覆盖
    db.set_setting(1, "antiflood", "0")
    assert db.get_bool_setting(1, "antiflood", True) is False
    db.set_setting(1, "alphabet_latin", "1")
    assert db.get_bool_setting(1, "alphabet_latin", False) is True


def test_settings_isolated_by_tenant(db):
    db.set_setting(1, "antiflood", "0")
    assert db.get_bool_setting(2, "antiflood", True) is True


def test_delete_tenant_clears_kv(db):
    db.set_setting(5, "antiflood", "0")
    db.delete_tenant(5)
    assert db.get_setting(5, "antiflood") is None
