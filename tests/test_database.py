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


# ── 拦截日志 ───────────────────────────────────────────────────

def test_add_and_get_intercept_log(db):
    db.add_intercept_log(
        1, "filter", user_id=7, username="a", full_name="Alice",
        rule="违禁词", message_summary="包含违禁词的消息",
        via_bot_id=555, via_bot_username="PostBot", auto_banned=True)
    rows = db.get_intercept_logs(1)
    assert len(rows) == 1
    row = rows[0]
    assert row["reason"] == "filter"
    assert row["user_id"] == 7
    assert row["rule"] == "违禁词"
    assert row["via_bot_id"] == 555
    assert row["auto_banned"] == 1


def test_intercept_logs_isolated_by_tenant(db):
    db.add_intercept_log(1, "antiflood", user_id=1)
    db.add_intercept_log(2, "antiflood", user_id=2)
    assert len(db.get_intercept_logs(1)) == 1
    assert len(db.get_intercept_logs(2)) == 1


def test_intercept_logs_most_recent_first(db):
    db.add_intercept_log(1, "antiflood", user_id=1, message_summary="first")
    db.add_intercept_log(1, "antiflood", user_id=1, message_summary="second")
    rows = db.get_intercept_logs(1)
    assert rows[0]["message_summary"] == "second"
    assert rows[1]["message_summary"] == "first"


def test_intercept_logs_capped_per_tenant(db, monkeypatch):
    monkeypatch.setattr(db, "_INTERCEPT_LOG_MAX_PER_TENANT", 5)
    for i in range(10):
        db.add_intercept_log(1, "antiflood", user_id=1, message_summary=str(i))
    rows = db.get_intercept_logs(1, limit=100)
    assert len(rows) == 5
    # 应保留最新的 5 条
    assert {r["message_summary"] for r in rows} == {"5", "6", "7", "8", "9"}


def test_delete_tenant_purges_intercept_logs(db):
    db.add_intercept_log(5, "antiflood", user_id=1)
    db.delete_tenant(5)
    assert db.get_intercept_logs(5) == []


def test_scheduled_message_crud(db):
    sid = db.add_scheduled_message(
        1, target_type="group", target_chat_id=-100123, target_name="测试群",
        msg_type="text", content="hello", interval_minutes=30, remark="备注A")
    row = db.get_scheduled_message(1, sid)
    assert row["target_chat_id"] == "-100123"
    assert row["content"] == "hello"
    assert row["enabled"] == 1

    db.update_scheduled_message(
        1, sid, target_type="channel", target_chat_id="@mychannel",
        target_name="频道", msg_type="text", content="updated",
        interval_minutes=60, remark="备注B")
    row = db.get_scheduled_message(1, sid)
    assert row["target_type"] == "channel"
    assert row["target_chat_id"] == "@mychannel"
    assert row["content"] == "updated"

    db.set_scheduled_message_enabled(1, sid, False)
    assert db.get_scheduled_message(1, sid)["enabled"] == 0

    db.delete_scheduled_message(1, sid)
    assert db.get_scheduled_message(1, sid) is None


def test_scheduled_messages_isolated_by_tenant(db):
    db.add_scheduled_message(1, target_type="group", target_chat_id=-1, content="a")
    db.add_scheduled_message(2, target_type="group", target_chat_id=-2, content="b")
    assert len(db.get_scheduled_messages(1)) == 1
    assert len(db.get_scheduled_messages(2)) == 1


def test_scheduled_messages_bulk_delete(db):
    ids = [
        db.add_scheduled_message(1, target_type="group", target_chat_id=-1, content=str(i))
        for i in range(3)
    ]
    deleted = db.delete_scheduled_messages(1, ids[:2])
    assert deleted == 2
    remaining = db.get_scheduled_messages(1)
    assert len(remaining) == 1
    assert remaining[0]["id"] == ids[2]


def test_due_scheduled_messages_respects_next_run_at(db):
    due_id = db.add_scheduled_message(
        1, target_type="group", target_chat_id=-1, content="due")
    future_id = db.add_scheduled_message(
        1, target_type="group", target_chat_id=-1, content="future",
        next_run_at="2999-01-01 00:00:00")
    due = {r["id"] for r in db.get_due_scheduled_messages(1)}
    assert due_id in due
    assert future_id not in due

    db.set_scheduled_message_enabled(1, due_id, False)
    due = {r["id"] for r in db.get_due_scheduled_messages(1)}
    assert due_id not in due


def test_mark_scheduled_message_sent_updates_state(db):
    sid = db.add_scheduled_message(
        1, target_type="group", target_chat_id=-1, content="hi")
    db.mark_scheduled_message_sent(
        1, sid, message_id=42, next_run_at="2999-01-01 00:00:00")
    row = db.get_scheduled_message(1, sid)
    assert row["last_message_id"] == 42
    assert row["next_run_at"] == "2999-01-01 00:00:00"
    assert row["enabled"] == 1

    db.mark_scheduled_message_sent(
        1, sid, message_id=43, next_run_at=None, disable_if_once=True)
    row = db.get_scheduled_message(1, sid)
    assert row["enabled"] == 0
    assert row["last_message_id"] == 43


def test_delete_tenant_purges_scheduled_messages(db):
    db.add_scheduled_message(6, target_type="group", target_chat_id=-1, content="x")
    db.delete_tenant(6)
    assert db.get_scheduled_messages(6) == []
