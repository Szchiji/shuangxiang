"""Web admin backend for bot management (Telegram Mini App).

Provides an aiohttp web server that serves a Telegram WebApp-based admin panel,
allowing bot admins to manage their bots via a browser interface instead of
private chat commands.

Authentication uses Telegram's WebApp initData HMAC-SHA256 validation:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import copy
import hashlib
import hmac
import json
import logging
import os
import re
import time
from urllib.parse import parse_qsl

from aiohttp import web

from core.database import Database
from modules.auto_reply_module import SK_ALPHABET_LATIN, SK_ANTIFLOOD
from modules.customize_module import (
    SK_FORCE_SUB,
    SK_FORCE_SUB_ON,
    SK_WELCOME_BTNS,
    SK_WELCOME_TEXT,
    _default_join_url,
    _normalize_chat,
    parse_buttons,
)

logger = logging.getLogger("shuangxiang.webapp")

# Directory that contains static assets (index.html, app.js, style.css)
_WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "..", "webapp")

# Maximum age (seconds) of a valid initData auth_date. Rejects replayed tokens.
_INIT_DATA_MAX_AGE = 3600  # 1 hour

# Allowed values for auto-reply match_type.
_VALID_MATCH_TYPES = frozenset({"contains", "exact", "startswith", "regex"})
_VALID_FORM_FIELD_TYPES = frozenset({"text", "textarea", "select", "datetime", "image"})
_VALID_PAGE_MODULES = frozenset({"welcome", "auto_reply", "banned", "stats", "content"})
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_CHAT_USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]{1,32}$")

SK_PAGE_CONFIG = "webapp_page_config"
SK_FORM_CONFIG = "webapp_form_config"
SK_CONTENT_MANAGEMENT = "webapp_content_management"

_DEFAULT_PAGE_CONFIG = {
    "announcement": "",
    "theme_color": "",
    "modules": {
        "welcome": True,
        "auto_reply": True,
        "banned": True,
        "stats": True,
        "content": True,
    },
    "banners": [],
    "quick_navs": [],
}
_DEFAULT_FORM_CONFIG = {"intro": "", "fields": []}
_DEFAULT_CONTENT_CONFIG = {"help_text": "", "activity_title": "", "activity_content": "", "faq": []}


# ── Telegram initData validation ─────────────────────────────────────────────

def _verify_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram WebApp initData. Returns parsed params dict or None."""
    try:
        params = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    received_hash = params.pop("hash", None)
    if not received_hash:
        return None
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        return None
    # Reject stale tokens to prevent replay attacks.
    try:
        auth_date = int(params.get("auth_date", "0"))
    except (ValueError, TypeError):
        return None
    if time.time() - auth_date > _INIT_DATA_MAX_AGE:
        return None
    return params


def _extract_tg_user(params: dict) -> dict | None:
    """Extract the Telegram user object from parsed initData params."""
    try:
        return json.loads(params.get("user", "{}")) or None
    except Exception:
        return None


def _clean_text(value, *, max_len: int, allow_empty: bool = True) -> str | None:
    if value is None:
        s = ""
    elif isinstance(value, str):
        s = value.strip()
    else:
        return None
    if not allow_empty and not s:
        return None
    if len(s) > max_len:
        return None
    return s


def _normalize_page_config(raw: dict | None) -> dict:
    cfg = copy.deepcopy(_DEFAULT_PAGE_CONFIG)
    raw = raw or {}
    announcement = _clean_text(raw.get("announcement", ""), max_len=300)
    theme_color = _clean_text(raw.get("theme_color", ""), max_len=16)
    if announcement is None or theme_color is None:
        raise ValueError("invalid text length")
    if theme_color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", theme_color):
        raise ValueError("theme_color must be hex like #2563eb")
    cfg["announcement"] = announcement
    cfg["theme_color"] = theme_color

    raw_modules = raw.get("modules")
    if isinstance(raw_modules, dict):
        for key in _VALID_PAGE_MODULES:
            if key in raw_modules:
                cfg["modules"][key] = bool(raw_modules[key])

    for field, limit in (("banners", 6), ("quick_navs", 10)):
        rows = raw.get(field, [])
        if not isinstance(rows, list) or len(rows) > limit:
            raise ValueError(f"{field} invalid")
        cleaned = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{field} item invalid")
            title = _clean_text(row.get("title", ""), max_len=40, allow_empty=False)
            url = _clean_text(row.get("url", ""), max_len=500, allow_empty=False)
            if title is None or url is None:
                raise ValueError(f"{field} title/url invalid")
            cleaned.append({
                "title": title,
                "url": url,
                "enabled": bool(row.get("enabled", True)),
            })
        cfg[field] = cleaned
    return cfg


def _normalize_form_config(raw: dict | None) -> dict:
    raw = raw or {}
    intro = _clean_text(raw.get("intro", ""), max_len=500)
    if intro is None:
        raise ValueError("intro invalid")
    fields = raw.get("fields", [])
    if not isinstance(fields, list) or len(fields) > 30:
        raise ValueError("fields invalid")
    cleaned = []
    for item in fields:
        if not isinstance(item, dict):
            raise ValueError("field item invalid")
        key = _clean_text(item.get("key", ""), max_len=32, allow_empty=False)
        label = _clean_text(item.get("label", ""), max_len=40, allow_empty=False)
        field_type = _clean_text(item.get("type", ""), max_len=20, allow_empty=False)
        if key is None or label is None or field_type is None:
            raise ValueError("field key/label/type required")
        if not _KEY_RE.fullmatch(key):
            raise ValueError("field key format invalid")
        if field_type not in _VALID_FORM_FIELD_TYPES:
            raise ValueError("field type invalid")
        default_value = _clean_text(item.get("default", ""), max_len=200)
        if default_value is None:
            raise ValueError("field default invalid")
        row = {
            "key": key,
            "label": label,
            "type": field_type,
            "required": bool(item.get("required", False)),
            "default": default_value,
        }
        if field_type == "select":
            options = item.get("options", [])
            if not isinstance(options, list) or not options or len(options) > 20:
                raise ValueError("select options invalid")
            cleaned_options = []
            for opt in options:
                opt_text = _clean_text(opt, max_len=30, allow_empty=False)
                if opt_text is None:
                    raise ValueError("select option invalid")
                cleaned_options.append(opt_text)
            row["options"] = cleaned_options
        cleaned.append(row)
    return {"intro": intro, "fields": cleaned}


def _normalize_content_config(raw: dict | None) -> dict:
    raw = raw or {}
    help_text = _clean_text(raw.get("help_text", ""), max_len=2000)
    activity_title = _clean_text(raw.get("activity_title", ""), max_len=80)
    activity_content = _clean_text(raw.get("activity_content", ""), max_len=4000)
    if help_text is None or activity_title is None or activity_content is None:
        raise ValueError("content text invalid")
    faq = raw.get("faq", [])
    if not isinstance(faq, list) or len(faq) > 30:
        raise ValueError("faq invalid")
    cleaned_faq = []
    for item in faq:
        if not isinstance(item, dict):
            raise ValueError("faq item invalid")
        q = _clean_text(item.get("question", ""), max_len=120, allow_empty=False)
        a = _clean_text(item.get("answer", ""), max_len=1000, allow_empty=False)
        if q is None or a is None:
            raise ValueError("faq question/answer required")
        cleaned_faq.append({"question": q, "answer": a})
    return {
        "help_text": help_text,
        "activity_title": activity_title,
        "activity_content": activity_content,
        "faq": cleaned_faq,
    }


def _button_rows_to_text(raw) -> str:
    if not raw:
        return ""
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return ""
    lines = []
    for row in rows or []:
        if not isinstance(row, list):
            continue
        parts = []
        for btn in row:
            if not isinstance(btn, dict):
                continue
            text = _clean_text(btn.get("text", ""), max_len=80, allow_empty=False)
            url = _clean_text(btn.get("url", ""), max_len=500, allow_empty=False)
            if text is None or url is None:
                continue
            parts.append(f"{text} - {url}")
        if parts:
            lines.append(" && ".join(parts))
    return "\n".join(lines)


def _normalize_button_text(raw, *, max_len: int) -> str:
    text = _clean_text(raw, max_len=max_len)
    if text is None:
        raise ValueError("button text invalid")
    if not text:
        return ""
    try:
        rows = parse_buttons(text)
    except Exception as e:
        raise ValueError("buttons invalid") from e
    if not rows:
        raise ValueError("buttons invalid")
    return json.dumps(rows, ensure_ascii=False)


def _normalize_button_payload(raw, *, max_len: int) -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):
        text = _button_rows_to_text(raw)
        if raw and not text:
            raise ValueError("buttons invalid")
        return _normalize_button_text(text, max_len=max_len)
    if not isinstance(raw, str):
        raise ValueError("buttons invalid")
    stripped = raw.strip()
    if not stripped:
        return ""
    try:
        parsed = json.loads(stripped)
    except ValueError:
        pass
    else:
        if not isinstance(parsed, list):
            raise ValueError("buttons invalid")
        return _normalize_button_payload(parsed, max_len=max_len)
    return _normalize_button_text(raw, max_len=max_len)


def _force_sub_to_text(raw) -> str:
    if not raw:
        return ""
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return ""
    lines = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = _clean_text(row.get("title", ""), max_len=80)
        chat = _clean_text(row.get("chat", ""), max_len=120, allow_empty=False)
        url = _clean_text(row.get("url", ""), max_len=500, allow_empty=False)
        if chat is None or url is None:
            continue
        parts = [chat, url] if not title or title == chat else [title, chat, url]
        lines.append(" | ".join(part for part in parts if part))
    return "\n".join(lines)


def _normalize_force_sub_text(raw, *, max_len: int) -> str:
    text = _clean_text(raw, max_len=max_len)
    if text is None:
        raise ValueError("force_sub text invalid")
    if not text:
        return ""
    channels = []
    for idx, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        parts = [part.strip() for part in stripped.split("|")]
        if len(parts) == 1:
            title, chat, url = "", parts[0], ""
        elif len(parts) == 2:
            if parts[1].startswith(("http://", "https://", "tg://")):
                title, chat, url = "", parts[0], parts[1]
            else:
                title, chat, url = parts[0], parts[1], ""
        elif len(parts) == 3:
            title, chat, url = parts
        else:
            raise ValueError(f"force_sub line {idx} invalid")
        norm_chat = _normalize_chat(chat)
        if norm_chat is None:
            raise ValueError(f"force_sub line {idx} invalid")
        chat_value = str(norm_chat)
        if not (chat_value.lstrip("-").isdigit() or _CHAT_USERNAME_RE.fullmatch(chat_value)):
            raise ValueError(f"force_sub line {idx} invalid")
        title = _clean_text(title or chat_value, max_len=80, allow_empty=False)
        url = _clean_text(url or _default_join_url(chat_value), max_len=500, allow_empty=False)
        if title is None or url is None or not url.startswith(("http://", "https://", "tg://")):
            raise ValueError(f"force_sub line {idx} invalid")
        channels.append({"title": title, "chat": chat_value, "url": url})
    return json.dumps(channels, ensure_ascii=False) if channels else ""


def _normalize_force_sub_payload(raw, *, max_len: int) -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):
        text = _force_sub_to_text(raw)
        if raw and not text:
            raise ValueError("force_sub invalid")
        return _normalize_force_sub_text(text, max_len=max_len)
    if not isinstance(raw, str):
        raise ValueError("force_sub invalid")
    stripped = raw.strip()
    if not stripped:
        return ""
    try:
        parsed = json.loads(stripped)
    except ValueError:
        pass
    else:
        if not isinstance(parsed, list):
            raise ValueError("force_sub invalid")
        return _normalize_force_sub_payload(parsed, max_len=max_len)
    return _normalize_force_sub_text(raw, max_len=max_len)


# ── Middleware ────────────────────────────────────────────────────────────────

@web.middleware
async def _tenant_middleware(request: web.Request, handler):
    """Parse tenant_id from path for /api/** routes."""
    if request.path.startswith("/api/"):
        raw = (request.match_info.get("tenant_id")
               or request.rel_url.query.get("tenant_id", ""))
        try:
            request["tenant_id"] = int(raw)
        except (ValueError, TypeError):
            return web.json_response(
                {"error": "missing or invalid tenant_id"}, status=400)
    return await handler(request)


# ── Auth helper ───────────────────────────────────────────────────────────────

def _auth(request: web.Request):
    """Verify initData and return the tenant db row.

    Raises HTTPForbidden if authentication or authorisation fails.
    """
    db = Database()
    tenant = db.get_tenant(request["tenant_id"])
    if tenant is None:
        raise web.HTTPForbidden(reason="unknown tenant")
    init_data = (request.headers.get("X-Init-Data", "")
                 or request.rel_url.query.get("init_data", ""))
    params = _verify_init_data(init_data, tenant["token"])
    if params is None:
        raise web.HTTPForbidden(reason="invalid init_data")
    user = _extract_tg_user(params)
    if not user or user.get("id") != tenant["owner_user_id"]:
        raise web.HTTPForbidden(reason="not the owner")
    return tenant


# ── API handlers ──────────────────────────────────────────────────────────────

async def _get_settings(request: web.Request):
    tenant = _auth(request)
    tid, db = tenant["id"], Database()
    welcome_btns = db.get_setting(tid, SK_WELCOME_BTNS, "") or ""
    force_sub = db.get_setting(tid, SK_FORCE_SUB, "") or ""
    return web.json_response({
        "welcome_text":   db.get_setting(tid, SK_WELCOME_TEXT, "") or "",
        "welcome_btns":   welcome_btns,
        "welcome_btns_text": _button_rows_to_text(welcome_btns),
        "force_sub":      force_sub,
        "force_sub_text": _force_sub_to_text(force_sub),
        "antiflood":      db.get_bool_setting(tid, SK_ANTIFLOOD, True),
        "alphabet_latin": db.get_bool_setting(tid, SK_ALPHABET_LATIN, False),
        "force_sub_on":   db.get_bool_setting(tid, SK_FORCE_SUB_ON, False),
        "manage_group":   db.get_manage_group(tid),
        "bot_username":   tenant["bot_username"] or "",
        "bot_name":       tenant["bot_name"] or "",
    })


async def _post_settings(request: web.Request):
    tenant = _auth(request)
    tid, db = tenant["id"], Database()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    if SK_WELCOME_TEXT in body:
        welcome_text = _clean_text(body[SK_WELCOME_TEXT], max_len=4000)
        if welcome_text is None:
            return web.json_response({"error": "welcome_text invalid"}, status=400)
        db.set_setting(tid, SK_WELCOME_TEXT, welcome_text)
    if "welcome_btns_text" in body:
        try:
            buttons_json = _normalize_button_text(body["welcome_btns_text"], max_len=2000)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        db.set_setting(tid, SK_WELCOME_BTNS, buttons_json)
    elif SK_WELCOME_BTNS in body:
        try:
            buttons_json = _normalize_button_payload(body[SK_WELCOME_BTNS], max_len=2000)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        db.set_setting(tid, SK_WELCOME_BTNS, buttons_json)
    if "force_sub_text" in body:
        try:
            force_sub_json = _normalize_force_sub_text(body["force_sub_text"], max_len=4000)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        db.set_setting(tid, SK_FORCE_SUB, force_sub_json)
    elif "force_sub" in body:
        try:
            force_sub_json = _normalize_force_sub_payload(body["force_sub"], max_len=4000)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        db.set_setting(tid, SK_FORCE_SUB, force_sub_json)
    for key in (SK_ANTIFLOOD, SK_ALPHABET_LATIN, SK_FORCE_SUB_ON):
        if key in body:
            db.set_setting(tid, key, "1" if body[key] else "0")
    return web.json_response({"ok": True})


async def _get_stats(request: web.Request):
    tenant = _auth(request)
    return web.json_response(Database().get_tenant_user_count(tenant["id"]))


async def _get_page_config(request: web.Request):
    tenant = _auth(request)
    db = Database()
    raw = db.get_json_setting(
        tenant["id"], SK_PAGE_CONFIG, copy.deepcopy(_DEFAULT_PAGE_CONFIG))
    try:
        data = _normalize_page_config(raw)
    except ValueError:
        data = copy.deepcopy(_DEFAULT_PAGE_CONFIG)
    return web.json_response(data)


async def _post_page_config(request: web.Request):
    tenant = _auth(request)
    db = Database()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    try:
        payload = _normalize_page_config(body)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    db.set_json_setting(tenant["id"], SK_PAGE_CONFIG, payload)
    return web.json_response({"ok": True})


async def _get_form_config(request: web.Request):
    tenant = _auth(request)
    db = Database()
    raw = db.get_json_setting(
        tenant["id"], SK_FORM_CONFIG, copy.deepcopy(_DEFAULT_FORM_CONFIG))
    try:
        data = _normalize_form_config(raw)
    except ValueError:
        data = copy.deepcopy(_DEFAULT_FORM_CONFIG)
    return web.json_response(data)


async def _post_form_config(request: web.Request):
    tenant = _auth(request)
    db = Database()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    try:
        payload = _normalize_form_config(body)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    db.set_json_setting(tenant["id"], SK_FORM_CONFIG, payload)
    return web.json_response({"ok": True})


async def _get_contents(request: web.Request):
    tenant = _auth(request)
    db = Database()
    raw = db.get_json_setting(
        tenant["id"], SK_CONTENT_MANAGEMENT, copy.deepcopy(_DEFAULT_CONTENT_CONFIG))
    try:
        data = _normalize_content_config(raw)
    except ValueError:
        data = copy.deepcopy(_DEFAULT_CONTENT_CONFIG)
    return web.json_response(data)


async def _post_contents(request: web.Request):
    tenant = _auth(request)
    db = Database()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    try:
        payload = _normalize_content_config(body)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    db.set_json_setting(tenant["id"], SK_CONTENT_MANAGEMENT, payload)
    return web.json_response({"ok": True})


async def _get_auto_replies(request: web.Request):
    tenant = _auth(request)
    rows = Database().get_auto_replies(tenant["id"])
    return web.json_response([
        {
            **dict(r),
            "buttons_text": _button_rows_to_text(r["buttons"] or ""),
        }
        for r in rows
    ])


async def _post_auto_reply(request: web.Request):
    tenant = _auth(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    keyword = str(body.get("keyword", "")).strip()
    reply   = str(body.get("reply", "")).strip()
    if not keyword or not reply:
        return web.json_response({"error": "keyword and reply required"}, status=400)
    match_type = str(body.get("match_type", "contains"))
    if match_type not in _VALID_MATCH_TYPES:
        return web.json_response(
            {"error": f"match_type must be one of {sorted(_VALID_MATCH_TYPES)}"}, status=400)
    try:
        buttons_json = _normalize_button_text(body.get("buttons_text", ""), max_len=2000)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    rid = Database().add_auto_reply(
        tenant["id"], keyword, reply, match_type, buttons=buttons_json)
    return web.json_response({"id": rid})


async def _delete_auto_reply(request: web.Request):
    tenant = _auth(request)
    try:
        rid = int(request.match_info["rid"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid id"}, status=400)
    Database().delete_auto_reply(tenant["id"], rid)
    return web.json_response({"ok": True})


async def _get_banned(request: web.Request):
    tenant = _auth(request)
    rows = Database().get_banned_tenant_users(tenant["id"])
    return web.json_response([
        {
            "user_id":   r["user_id"],
            "username":  r["username"],
            "full_name": r["full_name"],
        }
        for r in rows
    ])


async def _post_unban(request: web.Request):
    tenant = _auth(request)
    try:
        uid = int(request.match_info["uid"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid uid"}, status=400)
    Database().unban_user(tenant["id"], uid)
    return web.json_response({"ok": True})


# ── Static files ──────────────────────────────────────────────────────────────

async def _serve_index(_request: web.Request):
    path = os.path.join(_WEBAPP_DIR, "index.html")
    if not os.path.exists(path):
        raise web.HTTPNotFound()
    with open(path, encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")


# ── Application factory / runner ──────────────────────────────────────────────

def create_app() -> web.Application:
    """Build and return the aiohttp Application (not yet running)."""
    app = web.Application(middlewares=[_tenant_middleware])

    # Serve the admin panel SPA
    app.router.add_get("/", _serve_index)
    app.router.add_get("/index.html", _serve_index)

    # Static assets (JS / CSS served from the webapp/ directory)
    if os.path.isdir(_WEBAPP_DIR):
        app.router.add_static("/static", _WEBAPP_DIR)

    # REST API endpoints
    app.router.add_get(
        "/api/{tenant_id}/settings",           _get_settings)
    app.router.add_post(
        "/api/{tenant_id}/settings",           _post_settings)
    app.router.add_get(
        "/api/{tenant_id}/stats",              _get_stats)
    app.router.add_get(
        "/api/{tenant_id}/page_config",        _get_page_config)
    app.router.add_post(
        "/api/{tenant_id}/page_config",        _post_page_config)
    app.router.add_get(
        "/api/{tenant_id}/form_config",        _get_form_config)
    app.router.add_post(
        "/api/{tenant_id}/form_config",        _post_form_config)
    app.router.add_get(
        "/api/{tenant_id}/contents",           _get_contents)
    app.router.add_post(
        "/api/{tenant_id}/contents",           _post_contents)
    app.router.add_get(
        "/api/{tenant_id}/auto_replies",       _get_auto_replies)
    app.router.add_post(
        "/api/{tenant_id}/auto_replies",       _post_auto_reply)
    app.router.add_delete(
        "/api/{tenant_id}/auto_replies/{rid}", _delete_auto_reply)
    app.router.add_get(
        "/api/{tenant_id}/banned",             _get_banned)
    app.router.add_post(
        "/api/{tenant_id}/unban/{uid}",        _post_unban)

    return app


async def start_webapp(host: str, port: int) -> web.AppRunner:
    """Start the web admin server. Returns the runner for graceful shutdown."""
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("管理后台已启动 http://%s:%d", host, port)
    return runner
