"""Tests for the web admin backend (core/webapp.py)."""

import hashlib
import hmac
import json
import time
import types
from urllib.parse import urlencode

import pytest

from core.database import Database
from core.webapp import _verify_init_data, create_app

# ── initData validation helpers ───────────────────────────────────────────────

_TOKEN = "test_token_1234567890:ABCdef"


def _make_init_data(user_id: int, token: str = _TOKEN,
                    auth_date: int | None = None) -> str:
    """Build a valid Telegram WebApp initData string for testing."""
    if auth_date is None:
        auth_date = int(time.time())
    user_str = json.dumps({"id": user_id, "first_name": "Test"})
    params = {
        "auth_date": str(auth_date),
        "user":      user_str,
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    hash_val   = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    params["hash"] = hash_val
    return urlencode(params)


def test_verify_init_data_valid():
    init_data = _make_init_data(42)
    result = _verify_init_data(init_data, _TOKEN)
    assert result is not None
    user = json.loads(result["user"])
    assert user["id"] == 42


def test_verify_init_data_wrong_token():
    init_data = _make_init_data(42)
    assert _verify_init_data(init_data, "wrong_token") is None


def test_verify_init_data_tampered():
    init_data = _make_init_data(42) + "&extra=tamper"
    assert _verify_init_data(init_data, _TOKEN) is None


def test_verify_init_data_missing_hash():
    assert _verify_init_data("auth_date=1234", _TOKEN) is None


def test_verify_init_data_empty():
    assert _verify_init_data("", _TOKEN) is None


def test_verify_init_data_stale():
    """initData with an auth_date more than 1 hour old must be rejected."""
    stale_init_data = _make_init_data(42, auth_date=int(time.time()) - 7200)
    assert _verify_init_data(stale_init_data, _TOKEN) is None


# ── aiohttp app API routes ─────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    Database._instance = None
    database = Database(db_path=str(tmp_path / "test.db"))
    yield database
    Database._instance = None


@pytest.fixture
def tenant_id(db):
    """Create a test tenant and return its id."""
    return db.add_tenant(
        token=_TOKEN,
        owner_user_id=42,
        bot_id=999,
        bot_username="testbot",
        bot_name="Test Bot",
    )


@pytest.fixture
def init_data_header(tenant_id):
    return _make_init_data(42)


@pytest.fixture
def app(db):
    return create_app()


@pytest.mark.asyncio
async def test_get_settings_ok(aiohttp_client, app, db, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    data = await resp.json()
    assert "welcome_text" in data
    assert "antiflood" in data
    assert data["flood_max_msgs"] == 5
    assert data["flood_window"] == 5


@pytest.mark.asyncio
async def test_get_settings_wrong_user(aiohttp_client, app, db, tenant_id):
    # Different user_id → not the owner → 403
    bad_init_data = _make_init_data(999)
    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": bad_init_data},
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_post_settings_ok(aiohttp_client, app, db, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"welcome_text": "Hello!", "antiflood": False},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True
    # Verify it was stored
    assert db.get_setting(tenant_id, "welcome_text") == "Hello!"
    assert db.get_bool_setting(tenant_id, "antiflood", True) is False


@pytest.mark.asyncio
async def test_post_settings_supports_flood_limit(aiohttp_client, app, db, tenant_id,
                                                    init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"flood_max_msgs": 10, "flood_window": 20},
    )
    assert resp.status == 200
    assert db.get_int_setting(tenant_id, "flood_max_msgs", 0) == 10
    assert db.get_int_setting(tenant_id, "flood_window", 0) == 20
    # 读取时也应返回自定义值
    resp2 = await client.get(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
    )
    data2 = await resp2.json()
    assert data2["flood_max_msgs"] == 10
    assert data2["flood_window"] == 20


@pytest.mark.asyncio
async def test_post_settings_clamps_flood_limit(aiohttp_client, app, db, tenant_id,
                                                 init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"flood_max_msgs": 9999, "flood_window": -5},
    )
    assert resp.status == 200
    assert db.get_int_setting(tenant_id, "flood_max_msgs", 0) == 50
    assert db.get_int_setting(tenant_id, "flood_window", 0) == 1


@pytest.mark.asyncio
async def test_post_settings_rejects_invalid_flood_limit(aiohttp_client, app, db, tenant_id,
                                                           init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"flood_max_msgs": "abc"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_post_settings_supports_welcome_buttons(aiohttp_client, app, db, tenant_id,
                                                      init_data_header):
    client = await aiohttp_client(app)
    buttons_text = "频道 - https://t.me/a && 客服 - https://t.me/b"
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"welcome_btns_text": buttons_text},
    )
    assert resp.status == 200
    stored = json.loads(db.get_setting(tenant_id, "welcome_buttons"))
    assert [btn["text"] for btn in stored[0]] == ["频道", "客服"]

    resp = await client.get(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
    )
    data = await resp.json()
    assert data["welcome_btns_text"] == buttons_text


@pytest.mark.asyncio
async def test_post_settings_supports_force_sub_text(aiohttp_client, app, db, tenant_id,
                                                     init_data_header):
    client = await aiohttp_client(app)
    channels_text = "官方频道 | @mychan | https://t.me/mychan\n交流群 | @groupchat"
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"force_sub_text": channels_text},
    )
    assert resp.status == 200
    stored = json.loads(db.get_setting(tenant_id, "force_sub"))
    assert stored[0]["chat"] == "@mychan"
    assert stored[0]["url"] == "https://t.me/mychan"
    assert stored[1]["url"] == "https://t.me/groupchat"

    resp = await client.get(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
    )
    data = await resp.json()
    assert "https://t.me/mychan" in data["force_sub_text"]


@pytest.mark.asyncio
async def test_post_settings_rejects_invalid_welcome_buttons(aiohttp_client, app, tenant_id,
                                                             init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"welcome_btns_text": "坏按钮 - ftp://bad"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_post_settings_rejects_invalid_force_sub_text(aiohttp_client, app, tenant_id,
                                                           init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"force_sub_text": "坏频道 | @chan | ftp://bad"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_post_settings_rejects_invalid_welcome_text(aiohttp_client, app, tenant_id,
                                                          init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"welcome_text": ["bad"]},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_post_settings_validates_legacy_welcome_buttons_payload(aiohttp_client, app, db,
                                                                      tenant_id,
                                                                      init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"welcome_buttons": [[{"text": "频道", "url": "https://t.me/a"}]]},
    )
    assert resp.status == 200
    assert db.get_setting(tenant_id, "welcome_buttons")


@pytest.mark.asyncio
async def test_post_settings_accepts_empty_legacy_welcome_buttons_payload(aiohttp_client, app, db,
                                                                          tenant_id,
                                                                          init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"welcome_buttons": "[]"},
    )
    assert resp.status == 200
    assert db.get_setting(tenant_id, "welcome_buttons") == ""


@pytest.mark.asyncio
async def test_get_stats_ok(aiohttp_client, app, db, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/{tenant_id}/stats",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    data = await resp.json()
    assert "total" in data


@pytest.mark.asyncio
async def test_auto_replies_invalid_match_type(aiohttp_client, app, db, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/auto_replies",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": "hi", "reply": "hello", "match_type": "invalid_type"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_auto_replies_crud(aiohttp_client, app, db, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    # Add
    resp = await client.post(
        f"/api/{tenant_id}/auto_replies",
        headers={"X-Init-Data": init_data_header},
        json={
            "keyword": "hi",
            "reply": "hello",
            "buttons_text": "官网 - https://example.com",
        },
    )
    assert resp.status == 200
    data = await resp.json()
    rid = data["id"]
    assert rid
    assert json.loads(db.get_auto_replies(tenant_id)[0]["buttons"])[0][0]["url"] == "https://example.com"

    # List
    resp = await client.get(
        f"/api/{tenant_id}/auto_replies",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    items = await resp.json()
    row = next(r for r in items if r["id"] == rid)
    assert row["buttons_text"] == "官网 - https://example.com"

    # Delete
    resp = await client.delete(
        f"/api/{tenant_id}/auto_replies/{rid}",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    assert (await resp.json())["ok"] is True


@pytest.mark.asyncio
async def test_auto_replies_reject_invalid_buttons(aiohttp_client, app, tenant_id,
                                                   init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/auto_replies",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": "hi", "reply": "hello", "buttons_text": "坏 - ftp://bad"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_filters_crud(aiohttp_client, app, db, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    # 新建租户会预置默认过滤词；额外添加自定义词
    resp = await client.post(
        f"/api/{tenant_id}/filters",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": "自定义违禁", "match_type": "contains"},
    )
    assert resp.status == 200
    data = await resp.json()
    fid = data["id"]
    assert data.get("ok") is True
    assert data["keyword"] == "自定义违禁"
    assert data["match_type"] == "contains"

    resp = await client.get(
        f"/api/{tenant_id}/filters",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    items = await resp.json()
    assert any(r["id"] == fid and r["keyword"] == "自定义违禁" for r in items)
    # 列表必须可见且带 id，供后台编辑/删除
    assert all("id" in r and "keyword" in r for r in items)
    assert len(items) >= 1

    resp = await client.put(
        f"/api/{tenant_id}/filters/{fid}",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": "已修改违禁", "match_type": "regex"},
    )
    assert resp.status == 200
    updated = await resp.json()
    assert updated.get("ok") is True
    assert updated["keyword"] == "已修改违禁"
    assert updated["match_type"] == "regex"
    row = db.get_filter(tenant_id, fid)
    assert row is not None and row["keyword"] == "已修改违禁"
    assert row["match_type"] == "regex"

    bad_put = await client.put(
        f"/api/{tenant_id}/filters/{fid}",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": "(", "match_type": "regex"},
    )
    assert bad_put.status == 400

    missing = await client.put(
        f"/api/{tenant_id}/filters/999999",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": "x"},
    )
    assert missing.status == 404

    resp = await client.delete(
        f"/api/{tenant_id}/filters/{fid}",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    assert (await resp.json())["ok"] is True
    remaining = {r["keyword"] for r in db.get_filters(tenant_id)}
    assert "已修改违禁" not in remaining
    assert "自定义违禁" not in remaining

    gone = await client.delete(
        f"/api/{tenant_id}/filters/{fid}",
        headers={"X-Init-Data": init_data_header},
    )
    assert gone.status == 404


@pytest.mark.asyncio
async def test_filters_add_regex_and_reject_invalid(aiohttp_client, app, db, tenant_id,
                                                    init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/filters",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": r"PC\d+", "match_type": "regex"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["match_type"] == "regex"
    assert data.get("ok") is True

    bad = await client.post(
        f"/api/{tenant_id}/filters",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": "(", "match_type": "regex"},
    )
    assert bad.status == 400

    empty = await client.post(
        f"/api/{tenant_id}/filters",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": "  "},
    )
    assert empty.status == 400

    bad_type = await client.post(
        f"/api/{tenant_id}/filters",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": "x", "match_type": "exact"},
    )
    assert bad_type.status == 400

    not_obj = await client.post(
        f"/api/{tenant_id}/filters",
        headers={"X-Init-Data": init_data_header},
        json=["not", "an", "object"],
    )
    assert not_obj.status == 400


@pytest.mark.asyncio
async def test_banned_and_unban(aiohttp_client, app, db, tenant_id, init_data_header):
    # Add and ban a user
    db.upsert_tenant_user(tenant_id, 55, "user55", "User55")
    db.ban_user(tenant_id, 55)

    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/{tenant_id}/banned",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    banned = await resp.json()
    assert any(u["user_id"] == 55 for u in banned)

    # Unban
    resp = await client.post(
        f"/api/{tenant_id}/unban/55",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    assert (await resp.json())["ok"] is True
    assert not db.is_banned(tenant_id, 55)


@pytest.mark.asyncio
async def test_missing_tenant_id(aiohttp_client, app, db, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.get(
        "/api/notanumber/settings",
        headers={"X-Init-Data": "x=1"},
    )
    assert resp.status in (400, 403, 404)


# ── 拦截日志 / 自动封禁 / 第三方机器人拦截开关 ─────────────────────────────────

@pytest.mark.asyncio
async def test_get_settings_includes_new_toggles_default_off(aiohttp_client, app, db, tenant_id,
                                                              init_data_header):
    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
    )
    data = await resp.json()
    # 保守默认值：不应影响现有普通用户。
    assert data["filter_auto_ban"] is False
    assert data["block_via_bot"] is False


@pytest.mark.asyncio
async def test_post_settings_supports_new_toggles(aiohttp_client, app, db, tenant_id,
                                                   init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"filter_auto_ban": True, "block_via_bot": True},
    )
    assert resp.status == 200
    assert db.get_bool_setting(tenant_id, "filter_auto_ban", False) is True
    assert db.get_bool_setting(tenant_id, "block_via_bot", False) is True


@pytest.mark.asyncio
async def test_get_intercept_logs_ok(aiohttp_client, app, db, tenant_id, init_data_header):
    db.add_intercept_log(
        tenant_id, "filter", user_id=55, rule="违禁词",
        message_summary="包含违禁词的消息")
    db.add_intercept_log(tenant_id, "antiflood", user_id=56, message_summary="刷屏")
    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/{tenant_id}/intercept_logs",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    payload = await resp.json()
    assert "items" in payload
    logs = payload["items"]
    assert payload["total"] == 2
    assert len(logs) == 2
    assert logs[0]["reason"] in ("filter", "antiflood")

    filtered = await client.get(
        f"/api/{tenant_id}/intercept_logs?reason=filter",
        headers={"X-Init-Data": init_data_header},
    )
    assert filtered.status == 200
    fdata = await filtered.json()
    assert fdata["total"] == 1
    assert fdata["items"][0]["reason"] == "filter"
    assert fdata["items"][0]["rule"] == "违禁词"


@pytest.mark.asyncio
async def test_get_intercept_logs_wrong_user(aiohttp_client, app, db, tenant_id):
    bad_init_data = _make_init_data(999)
    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/{tenant_id}/intercept_logs",
        headers={"X-Init-Data": bad_init_data},
    )
    assert resp.status == 403


# ── Scheduled messages ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scheduled_messages_crud(aiohttp_client, app, db, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    # Create
    resp = await client.post(
        f"/api/{tenant_id}/scheduled_messages",
        headers={"X-Init-Data": init_data_header},
        json={
            "target_type": "group",
            "target_chat_id": "-1001234567890",
            "target_name": "测试群",
            "msg_type": "text",
            "content": "hello",
            "interval_minutes": 30,
            "buttons_text": "官网 - https://example.com",
            "remark": "备注A",
        },
    )
    assert resp.status == 200
    data = await resp.json()
    sid = data["id"]
    assert sid

    # List
    resp = await client.get(
        f"/api/{tenant_id}/scheduled_messages",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    items = await resp.json()
    row = next(r for r in items if r["id"] == sid)
    assert row["content"] == "hello"
    assert row["buttons_text"] == "官网 - https://example.com"
    assert row["remark"] == "备注A"

    # Update
    resp = await client.put(
        f"/api/{tenant_id}/scheduled_messages/{sid}",
        headers={"X-Init-Data": init_data_header},
        json={
            "target_type": "channel",
            "target_chat_id": "@mychannel",
            "msg_type": "text",
            "content": "updated",
            "interval_minutes": 45,
        },
    )
    assert resp.status == 200
    assert (await resp.json())["ok"] is True
    row = db.get_scheduled_message(tenant_id, sid)
    assert row["target_type"] == "channel"
    assert row["content"] == "updated"

    # Toggle
    resp = await client.post(
        f"/api/{tenant_id}/scheduled_messages/{sid}/toggle",
        headers={"X-Init-Data": init_data_header},
        json={"enabled": False},
    )
    assert resp.status == 200
    assert db.get_scheduled_message(tenant_id, sid)["enabled"] == 0

    # Delete
    resp = await client.delete(
        f"/api/{tenant_id}/scheduled_messages/{sid}",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    assert (await resp.json())["ok"] is True
    assert db.get_scheduled_message(tenant_id, sid) is None


@pytest.mark.asyncio
async def test_scheduled_messages_reject_missing_content(aiohttp_client, app, tenant_id,
                                                          init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/scheduled_messages",
        headers={"X-Init-Data": init_data_header},
        json={"target_type": "group", "target_chat_id": "-1001", "msg_type": "text"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_scheduled_messages_reject_missing_target(aiohttp_client, app, tenant_id,
                                                         init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/scheduled_messages",
        headers={"X-Init-Data": init_data_header},
        json={"target_type": "group", "target_chat_id": "", "content": "hi"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_scheduled_messages_bulk_delete(aiohttp_client, app, db, tenant_id,
                                              init_data_header):
    ids = [
        db.add_scheduled_message(tenant_id, target_type="group", target_chat_id=-1,
                                 content=str(i))
        for i in range(3)
    ]
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/scheduled_messages/bulk_delete",
        headers={"X-Init-Data": init_data_header},
        json={"ids": ids[:2]},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["deleted"] == 2
    assert len(db.get_scheduled_messages(tenant_id)) == 1


@pytest.mark.asyncio
async def test_scheduled_messages_export_import(aiohttp_client, app, db, tenant_id,
                                                 init_data_header):
    db.add_scheduled_message(
        tenant_id, target_type="group", target_chat_id=-1001,
        target_name="群A", content="hi", interval_minutes=15)
    client = await aiohttp_client(app)

    resp = await client.get(
        f"/api/{tenant_id}/scheduled_messages/export",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    exported = await resp.json()
    assert len(exported["items"]) == 1
    assert "id" not in exported["items"][0]

    # Import into a fresh tenant to verify round-trip
    other_tenant_id = db.add_tenant(
        token="other_token:XYZ", owner_user_id=77, bot_id=1000,
        bot_username="otherbot", bot_name="Other Bot")
    other_init_data = _make_init_data(77, token="other_token:XYZ")
    resp = await client.post(
        f"/api/{other_tenant_id}/scheduled_messages/import",
        headers={"X-Init-Data": other_init_data},
        json=exported,
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["imported"] == 1
    assert len(db.get_scheduled_messages(other_tenant_id)) == 1


@pytest.mark.asyncio
async def test_scheduled_messages_wrong_user(aiohttp_client, app, tenant_id):
    bad_init_data = _make_init_data(999)
    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/{tenant_id}/scheduled_messages",
        headers={"X-Init-Data": bad_init_data},
    )
    assert resp.status == 403


# ── PrivateChatModule cmd_start with webapp ───────────────────────────────────

@pytest.mark.asyncio
async def test_admin_start_with_webapp_shows_button(db):
    """When webapp.url is configured, admin /start sends a WebApp button message."""
    from modules.private_chat_module import PrivateChatModule

    captured = {}

    class FakeMsg:
        async def reply_text(self, text, **kw):
            captured["text"] = text
            captured["markup"] = kw.get("reply_markup")

    mod = PrivateChatModule.__new__(PrivateChatModule)
    mod.db = db
    mod.tenant_id = 7
    mod.admin_id = 42
    mod._webapp_url = "https://example.com"
    mod.admin_welcome = "welcome"
    mod.admin_onboarding = " onboard"

    update = types.SimpleNamespace(
        effective_chat=types.SimpleNamespace(type="private"),
        effective_user=types.SimpleNamespace(id=42),
        message=FakeMsg(),
    )
    await mod.cmd_start(update, None)

    assert "管理后台" in captured["text"]
    # Verify a WebApp button was included
    markup = captured["markup"]
    assert markup is not None
    btn = markup.inline_keyboard[0][0]
    assert btn.web_app is not None
    assert "tenant_id=7" in btn.web_app.url


@pytest.mark.asyncio
async def test_admin_start_without_webapp_shows_panel(db):
    """When no webapp URL is set, admin /start falls back to the old inline panel."""
    from modules.private_chat_module import PrivateChatModule

    captured = {}

    class FakeMsg:
        async def reply_text(self, text, **kw):
            captured["text"] = text
            captured["markup"] = kw.get("reply_markup")

    mod = PrivateChatModule.__new__(PrivateChatModule)
    mod.db = db
    mod.tenant_id = 8
    mod.admin_id = 42
    mod._webapp_url = ""
    mod.admin_welcome = "welcome"
    mod.admin_onboarding = " onboard"

    update = types.SimpleNamespace(
        effective_chat=types.SimpleNamespace(type="private"),
        effective_user=types.SimpleNamespace(id=42),
        message=FakeMsg(),
    )
    await mod.cmd_start(update, None)

    assert "welcome" in captured["text"]
    # Should have returned the inline panel (not a WebApp button)
    markup = captured["markup"]
    assert markup is not None
    # None of the buttons should be a WebApp button
    all_buttons = [btn for row in markup.inline_keyboard for btn in row]
    assert all(btn.web_app is None for btn in all_buttons)


# ── P0 alignment: welcome media / AR media+stop / ban / users / filters IO ─────


@pytest.mark.asyncio
async def test_settings_welcome_media(aiohttp_client, app, db, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"welcome_media_type": "photo", "welcome_media_id": "AgAC_test_file"},
    )
    assert resp.status == 200
    assert db.get_setting(tenant_id, "welcome_media_type") == "photo"
    assert db.get_setting(tenant_id, "welcome_media_id") == "AgAC_test_file"

    got = await client.get(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
    )
    data = await got.json()
    assert data["welcome_media_type"] == "photo"
    assert data["welcome_media_id"] == "AgAC_test_file"
    assert data["topics_enabled"] is False

    bad = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"welcome_media_type": "photo", "welcome_media_id": ""},
    )
    assert bad.status == 400


@pytest.mark.asyncio
async def test_auto_replies_media_and_stop(aiohttp_client, app, db, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/auto_replies",
        headers={"X-Init-Data": init_data_header},
        json={
            "keyword": "价格",
            "reply": "请看官网",
            "match_type": "contains",
            "stop": True,
            "media_type": "photo",
            "media_id": "FILE_ABC",
        },
    )
    assert resp.status == 200
    rid = (await resp.json())["id"]
    row = next(r for r in db.get_auto_replies(tenant_id) if r["id"] == rid)
    assert row["stop"] == 1
    assert row["media_type"] == "photo"
    assert row["media_id"] == "FILE_ABC"

    resp = await client.put(
        f"/api/{tenant_id}/auto_replies/{rid}",
        headers={"X-Init-Data": init_data_header},
        json={
            "keyword": "价格",
            "reply": "请看官网",
            "stop": False,
            "media_type": "",
            "media_id": "",
        },
    )
    assert resp.status == 200
    row = next(r for r in db.get_auto_replies(tenant_id) if r["id"] == rid)
    assert row["stop"] == 0
    assert (row["media_type"] or "") == ""


@pytest.mark.asyncio
async def test_ban_and_users_search(aiohttp_client, app, db, tenant_id, init_data_header):
    db.upsert_tenant_user(tenant_id, 101, "alice", "Alice")
    db.upsert_tenant_user(tenant_id, 102, "bob", "Bob")
    client = await aiohttp_client(app)

    resp = await client.post(
        f"/api/{tenant_id}/ban/101",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    assert db.is_banned(tenant_id, 101)

    users = await client.get(
        f"/api/{tenant_id}/users?q=ali",
        headers={"X-Init-Data": init_data_header},
    )
    assert users.status == 200
    payload = await users.json()
    rows = payload["items"] if isinstance(payload, dict) else payload
    assert any(u["user_id"] == 101 and u["is_banned"] for u in rows)


@pytest.mark.asyncio
async def test_filters_export_import(aiohttp_client, app, db, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    await client.post(
        f"/api/{tenant_id}/filters",
        headers={"X-Init-Data": init_data_header},
        json={"keyword": "导出词", "match_type": "contains"},
    )
    exp = await client.get(
        f"/api/{tenant_id}/filters/export",
        headers={"X-Init-Data": init_data_header},
    )
    assert exp.status == 200
    payload = await exp.json()
    assert any(i["keyword"] == "导出词" for i in payload["items"])

    imp = await client.post(
        f"/api/{tenant_id}/filters/import",
        headers={"X-Init-Data": init_data_header},
        json={"items": [{"keyword": "导入词", "match_type": "contains"}, "纯文本词"]},
    )
    assert imp.status == 200
    data = await imp.json()
    assert data["imported"] >= 2
    kws = {r["keyword"] for r in db.get_filters(tenant_id)}
    assert "导入词" in kws
    assert "纯文本词" in kws


@pytest.mark.asyncio
async def test_broadcast_returns_job_id(aiohttp_client, app, db, tenant_id, init_data_header,
                                         monkeypatch):
    db.upsert_tenant_user(tenant_id, 201, "u201", "U201")
    client = await aiohttp_client(app)

    async def _noop_broadcast(job_id, user_ids, token, text, **kwargs):
        from core import webapp as wa
        job = wa._broadcast_jobs.get(job_id)
        if job:
            job["status"] = "done"
            job["done"] = len(user_ids)
            job["success"] = len(user_ids)
            job["failed"] = 0

    monkeypatch.setattr("core.webapp._do_broadcast", _noop_broadcast)

    resp = await client.post(
        f"/api/{tenant_id}/broadcast",
        headers={"X-Init-Data": init_data_header},
        json={"text": "hello all"},
    )
    assert resp.status == 202
    data = await resp.json()
    assert data["ok"] is True
    assert data["queued"] >= 1
    assert data["job_id"]

    job = await client.get(
        f"/api/{tenant_id}/broadcast/{data['job_id']}",
        headers={"X-Init-Data": init_data_header},
    )
    assert job.status == 200
    j = await job.json()
    assert j["total"] >= 1

    est = await client.get(
        f"/api/{tenant_id}/broadcast/estimate",
        headers={"X-Init-Data": init_data_header},
    )
    assert est.status == 200
    assert (await est.json())["active_users"] >= 1


@pytest.mark.asyncio
async def test_stats_extended_fields(aiohttp_client, app, db, tenant_id, init_data_header):
    db.upsert_tenant_user(tenant_id, 301, "s1", "S1")
    db.add_intercept_log(tenant_id, "filter", user_id=301)
    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/{tenant_id}/stats",
        headers={"X-Init-Data": init_data_header},
    )
    assert resp.status == 200
    data = await resp.json()
    for key in ("total", "new_today", "intercept_today", "auto_replies", "filters",
                "messages_today", "intercept_by_reason"):
        assert key in data


# ── P1/P2: staff, quick replies, user profile, away, platform ────────────────


@pytest.mark.asyncio
async def test_staff_member_can_access_and_owner_manages(
        aiohttp_client, app, db, tenant_id, init_data_header):
    db.upsert_staff(tenant_id, 88, role="support")
    support_init = _make_init_data(88)
    client = await aiohttp_client(app)

    # support can read settings
    resp = await client.get(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": support_init},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["auth_role"] == "support"

    # support cannot change settings
    bad = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": support_init},
        json={"away_on": True, "away_msg": "busy"},
    )
    assert bad.status == 403

    # owner can change away
    ok = await client.post(
        f"/api/{tenant_id}/settings",
        headers={"X-Init-Data": init_data_header},
        json={"away_on": True, "away_msg": "稍后回复"},
    )
    assert ok.status == 200
    assert db.get_bool_setting(tenant_id, "away_on", False) is True

    # owner adds admin staff
    add = await client.post(
        f"/api/{tenant_id}/staff",
        headers={"X-Init-Data": init_data_header},
        json={"user_id": 77, "role": "admin"},
    )
    assert add.status == 200
    staff = await client.get(
        f"/api/{tenant_id}/staff",
        headers={"X-Init-Data": init_data_header},
    )
    items = (await staff.json())["items"]
    assert any(s["user_id"] == 77 and s["role"] == "admin" for s in items)

    # support cannot manage staff
    denied = await client.post(
        f"/api/{tenant_id}/staff",
        headers={"X-Init-Data": support_init},
        json={"user_id": 99, "role": "support"},
    )
    assert denied.status == 403


@pytest.mark.asyncio
async def test_user_profile_and_quick_replies(
        aiohttp_client, app, db, tenant_id, init_data_header):
    db.upsert_tenant_user(tenant_id, 501, "vipuser", "VIP User")
    client = await aiohttp_client(app)

    patch = await client.patch(
        f"/api/{tenant_id}/users/501",
        headers={"X-Init-Data": init_data_header},
        json={"notes": "重点客户", "tags": "VIP, 已成交", "session_status": "pending"},
    )
    assert patch.status == 200
    body = await patch.json()
    assert body["user"]["notes"] == "重点客户"
    assert "VIP" in body["user"]["tags"]
    assert body["user"]["session_status"] == "pending"

    detail = await client.get(
        f"/api/{tenant_id}/users/501",
        headers={"X-Init-Data": init_data_header},
    )
    assert detail.status == 200
    assert (await detail.json())["session_status"] == "pending"

    # session filter
    filtered = await client.get(
        f"/api/{tenant_id}/users?session_status=pending",
        headers={"X-Init-Data": init_data_header},
    )
    assert filtered.status == 200
    items = (await filtered.json())["items"]
    assert any(u["user_id"] == 501 for u in items)

    qr = await client.post(
        f"/api/{tenant_id}/quick_replies",
        headers={"X-Init-Data": init_data_header},
        json={"title": "问候", "content": "您好，请问有什么可以帮您？"},
    )
    assert qr.status == 201
    qid = (await qr.json())["id"]
    listed = await client.get(
        f"/api/{tenant_id}/quick_replies",
        headers={"X-Init-Data": init_data_header},
    )
    assert any(r["id"] == qid for r in await listed.json())
    deleted = await client.delete(
        f"/api/{tenant_id}/quick_replies/{qid}",
        headers={"X-Init-Data": init_data_header},
    )
    assert deleted.status == 200


@pytest.mark.asyncio
async def test_platform_api(aiohttp_client, db):
    platform_token = "platform_token:AAA"
    platform_admin = 1
    app = create_app(platform_token=platform_token, platform_admin_id=platform_admin)
    # create a tenant
    db.add_tenant("t_token:BBB", owner_user_id=9, bot_username="tbot", bot_name="T")
    db.set_tenant_health(1, last_error="boom") if db.get_tenant(1) else None
    tid = db.add_tenant("t2:CCC", owner_user_id=10, bot_username="t2", bot_name="T2")
    db.set_tenant_health(tid, last_error="token fail")

    client = await aiohttp_client(app)
    init_data = _make_init_data(platform_admin, token=platform_token)
    stats = await client.get(
        "/api/platform/stats",
        headers={"X-Init-Data": init_data},
    )
    assert stats.status == 200
    s = await stats.json()
    assert s["tenants_total"] >= 1

    listed = await client.get(
        "/api/platform/tenants",
        headers={"X-Init-Data": init_data},
    )
    assert listed.status == 200
    payload = await listed.json()
    assert payload["total"] >= 1

    # wrong user
    bad = await client.get(
        "/api/platform/stats",
        headers={"X-Init-Data": _make_init_data(999, token=platform_token)},
    )
    assert bad.status == 403

    deact = await client.post(
        f"/api/platform/tenants/{tid}/deactivate",
        headers={"X-Init-Data": init_data},
    )
    assert deact.status == 200
    assert db.get_tenant(tid)["is_active"] == 0


@pytest.mark.asyncio
async def test_away_reply_on_incoming(db):
    from modules.private_chat_module import SK_AWAY_MSG, SK_AWAY_ON, PrivateChatModule

    tid = db.add_tenant("tok:away", owner_user_id=1, bot_id=1)
    db.set_setting(tid, SK_AWAY_ON, "1")
    db.set_setting(tid, SK_AWAY_MSG, "管理员离开了")

    mod = PrivateChatModule.__new__(PrivateChatModule)
    mod.db = db
    mod.tenant_id = tid
    mod.admin_id = 1
    mod._away_sent = {}
    mod.bot_forward_blocked = "no"
    mod._manage_group = lambda: None
    mod._buffer_album = lambda *a, **k: None
    mod._is_forwarded_from_bot = lambda m: False

    replies = []

    class FakeMsg:
        media_group_id = None
        via_bot = None
        message_id = 1
        chat_id = 50

        async def reply_text(self, text, **kw):
            replies.append(text)
            return types.SimpleNamespace(message_id=2)

        async def copy(self, *a, **k):
            return types.SimpleNamespace(message_id=3)

    class FakeBot:
        async def send_message(self, **k):
            return types.SimpleNamespace(message_id=9)

        async def copy_message(self, **k):
            return types.SimpleNamespace(message_id=10)

        async def forward_message(self, **k):
            return types.SimpleNamespace(message_id=11)

    # Patch _incoming_user path partially via _maybe_send_away
    msg = FakeMsg()
    await mod._maybe_send_away(msg, 50)
    assert replies == ["管理员离开了"]
    # cooldown
    await mod._maybe_send_away(msg, 50)
    assert len(replies) == 1


# ── Web admin SPA structure (filter/staff add + sidebar) ───────────────────────

def test_webapp_html_has_filter_and_staff_add_ui():
    """Regression: add buttons must open dedicated editor panels (not no-ops)."""
    from pathlib import Path

    html = Path(__file__).resolve().parents[1].joinpath("webapp", "index.html").read_text(
        encoding="utf-8"
    )
    js = Path(__file__).resolve().parents[1].joinpath("webapp", "app.js").read_text(
        encoding="utf-8"
    )
    css = Path(__file__).resolve().parents[1].joinpath("webapp", "style.css").read_text(
        encoding="utf-8"
    )

    for needle in (
        'id="fl-start-create"',
        'data-action="fl-start-create"',
        'id="fl-editor-card"',
        'id="fl-keyword"',
        'id="fl-submit"',
        'id="fl-cancel"',
        'id="fl-back"',
        'id="staff-start-create"',
        'data-action="staff-start-create"',
        'id="staff-editor-card"',
        'id="staff-uid"',
        'id="staff-add"',
        'id="staff-cancel"',
        'id="sidebar"',
        'id="sidebar-toggle"',
        'id="sidebar-hide"',
        'id="sidebar-reopen"',
    ):
        assert needle in html, f"missing markup: {needle}"

    for needle in (
        "function startCreateFl",
        "function startCreateStaff",
        "function showFlEditorView",
        "function showStaffEditorView",
        "function bindFilterUi",
        "function bindStaffUi",
        "function bindGlobalActions",
        "function initSidebar",
        "function revealPanel",
        "bh_sidebar_mode",
    ):
        assert needle in js, f"missing JS: {needle}"

    assert "sidebar.collapsed" in css or ".sidebar.collapsed" in css
    assert "sidebar.hidden" in css or ".sidebar.hidden" in css
    assert "drawer-open" in css
    # cache-bust query on assets
    assert "/static/app.js?v=" in html
    assert "/static/style.css?v=" in html


@pytest.mark.asyncio
async def test_index_and_static_cache_headers(aiohttp_client, app):
    """HTML must not be cached; static assets get short private cache."""
    client = await aiohttp_client(app)

    index = await client.get("/")
    assert index.status == 200
    assert "text/html" in index.headers.get("Content-Type", "")
    cc = index.headers.get("Cache-Control", "")
    assert "no-store" in cc or "no-cache" in cc
    body = await index.text()
    assert "fl-start-create" in body
    assert "staff-start-create" in body

    static_js = await client.get("/static/app.js")
    assert static_js.status == 200
    js_cc = static_js.headers.get("Cache-Control", "")
    assert "max-age" in js_cc or "must-revalidate" in js_cc
    js_body = await static_js.text()
    assert "function startCreateFl" in js_body
    assert "function startCreateStaff" in js_body
    assert "function initSidebar" in js_body
