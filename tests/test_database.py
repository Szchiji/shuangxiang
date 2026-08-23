"""数据库加固与设置相关测试。"""

import sqlite3

from core.database import DEFAULT_FILTER_KEYWORDS


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


# ── 过滤词：默认词库预置 / 正则支持 ───────────────────────────

def test_add_tenant_seeds_default_filters(db):
    tid = db.add_tenant("123:TOKEN", owner_user_id=1)
    rows = db.get_filters(tid)
    keywords = {r["keyword"] for r in rows}
    assert keywords == set(DEFAULT_FILTER_KEYWORDS)
    assert all(r["match_type"] == "contains" for r in rows)


def test_default_filters_not_reseeded_after_deletion(db):
    tid = db.add_tenant("123:TOKEN", owner_user_id=1)
    rows = db.get_filters(tid)
    db.delete_filter(tid, rows[0]["id"])
    # 模拟重启：再次触发预置逻辑，已删除的默认词不应被重新插入。
    db._seed_default_filters_for_all_tenants()
    remaining = {r["keyword"] for r in db.get_filters(tid)}
    assert rows[0]["keyword"] not in remaining
    assert len(remaining) == len(DEFAULT_FILTER_KEYWORDS) - 1


def test_add_filter_supports_regex_match_type(db):
    fid = db.add_filter(1, r"PC\d+", "regex")
    rows = db.get_filters(1)
    assert rows[0]["id"] == fid
    assert rows[0]["match_type"] == "regex"


def test_add_filter_defaults_to_contains(db):
    db.add_filter(1, "违禁词")
    rows = db.get_filters(1)
    assert rows[0]["match_type"] == "contains"
