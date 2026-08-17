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
async def test_page_config_get_and_post(aiohttp_client, app, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/page_config",
        headers={"X-Init-Data": init_data_header},
        json={
            "announcement": "系统升级通知",
            "theme_color": "#2563eb",
            "modules": {"stats": False},
            "banners": [{"title": "活动", "url": "https://example.com", "enabled": True}],
            "quick_navs": [{"title": "帮助", "url": "https://example.com/help", "enabled": True}],
        },
    )
    assert resp.status == 200
    assert (await resp.json())["ok"] is True

    resp = await client.get(
        f"/api/{tenant_id}/page_config",
        headers={"X-Init-Data": init_data_header},
    )
    data = await resp.json()
    assert data["announcement"] == "系统升级通知"
    assert data["theme_color"] == "#2563eb"
    assert data["modules"]["stats"] is False
    assert data["banners"][0]["title"] == "活动"


@pytest.mark.asyncio
async def test_page_config_invalid_theme(aiohttp_client, app, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/page_config",
        headers={"X-Init-Data": init_data_header},
        json={"theme_color": "blue"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_page_config_invalid_empty_url(aiohttp_client, app, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/page_config",
        headers={"X-Init-Data": init_data_header},
        json={"banners": [{"title": "活动", "url": ""}]},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_page_config_invalid_non_string_text(aiohttp_client, app, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/page_config",
        headers={"X-Init-Data": init_data_header},
        json={"announcement": ["bad"]},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_form_config_get_and_post(aiohttp_client, app, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    payload = {
        "intro": "请填写报名信息",
        "fields": [
            {"key": "name", "label": "姓名", "type": "text", "required": True},
            {"key": "when", "label": "预约时间", "type": "datetime", "required": True},
            {"key": "type", "label": "服务类型", "type": "select",
             "required": False, "options": ["A", "B"]},
        ],
    }
    resp = await client.post(
        f"/api/{tenant_id}/form_config",
        headers={"X-Init-Data": init_data_header},
        json=payload,
    )
    assert resp.status == 200
    assert (await resp.json())["ok"] is True
    resp = await client.get(
        f"/api/{tenant_id}/form_config",
        headers={"X-Init-Data": init_data_header},
    )
    data = await resp.json()
    assert data["intro"] == "请填写报名信息"
    assert len(data["fields"]) == 3
    assert data["fields"][2]["options"] == ["A", "B"]


@pytest.mark.asyncio
async def test_form_config_invalid_key(aiohttp_client, app, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/form_config",
        headers={"X-Init-Data": init_data_header},
        json={"fields": [{"key": "1bad", "label": "x", "type": "text"}]},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_form_config_invalid_default_length(aiohttp_client, app, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/form_config",
        headers={"X-Init-Data": init_data_header},
        json={"fields": [{"key": "name", "label": "姓名", "type": "text", "default": "x" * 201}]},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_content_config_get_and_post(aiohttp_client, app, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    payload = {
        "help_text": "帮助中心内容",
        "activity_title": "九月活动",
        "activity_content": "活动详情",
        "faq": [{"question": "怎么联系管理员？", "answer": "直接发消息"}],
    }
    resp = await client.post(
        f"/api/{tenant_id}/contents",
        headers={"X-Init-Data": init_data_header},
        json=payload,
    )
    assert resp.status == 200
    assert (await resp.json())["ok"] is True
    resp = await client.get(
        f"/api/{tenant_id}/contents",
        headers={"X-Init-Data": init_data_header},
    )
    data = await resp.json()
    assert data["activity_title"] == "九月活动"
    assert data["faq"][0]["question"] == "怎么联系管理员？"


@pytest.mark.asyncio
async def test_content_config_invalid_faq(aiohttp_client, app, tenant_id, init_data_header):
    client = await aiohttp_client(app)
    resp = await client.post(
        f"/api/{tenant_id}/contents",
        headers={"X-Init-Data": init_data_header},
        json={"faq": [{"question": "", "answer": "x"}]},
    )
    assert resp.status == 400


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
