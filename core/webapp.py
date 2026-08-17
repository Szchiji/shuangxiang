"""Web admin backend for bot management (Telegram Mini App).

Provides an aiohttp web server that serves a Telegram WebApp-based admin panel,
allowing bot admins to manage their bots via a browser interface instead of
private chat commands.

Authentication uses Telegram's WebApp initData HMAC-SHA256 validation:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qsl

import aiohttp as _aiohttp
from aiohttp import web

from core.database import Database
from modules.auto_reply_module import SK_ALPHABET_LATIN, SK_ANTIFLOOD
from modules.customize_module import (
    SK_FORCE_SUB,
    SK_FORCE_SUB_ON,
    SK_WELCOME_BTNS,
    SK_WELCOME_TEXT,
    parse_buttons,
)

logger = logging.getLogger("shuangxiang.webapp")

# Directory that contains static assets (index.html, app.js, style.css)
_WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "..", "webapp")

# Maximum age (seconds) of a valid initData auth_date. Rejects replayed tokens.
_INIT_DATA_MAX_AGE = 3600  # 1 hour

# Allowed values for auto-reply match_type.
_VALID_MATCH_TYPES = frozenset({"contains", "exact", "startswith", "regex"})


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


def _normalize_chat(chat: str):
    chat = (chat or "").strip()
    if not chat:
        return None
    if chat.lstrip("-").isdigit():
        return int(chat)
    return chat if chat.startswith("@") else "@" + chat


def _default_join_url(chat) -> str:
    chat = str(chat or "").strip()
    if chat.startswith("@"):
        return "https://t.me/" + chat[1:]
    return ""


def _force_sub_rows_to_text(raw) -> str:
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
        chat = _normalize_chat(str(row.get("chat", "")))
        url = _clean_text(row.get("url", ""), max_len=500, allow_empty=False)
        if title is None or chat is None or url is None:
            continue
        lines.append(f"{title or str(chat)} | {chat} | {url}")
    return "\n".join(lines)


def _normalize_force_sub_text(raw, *, max_len: int) -> str:
    text = _clean_text(raw, max_len=max_len)
    if text is None:
        raise ValueError("force_sub_text invalid")
    if not text:
        return ""
    channels = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 1:
            title, chat, url = "", parts[0], ""
        else:
            title, chat = parts[0], parts[1]
            url = parts[2] if len(parts) > 2 else ""
        chat_norm = _normalize_chat(chat)
        if chat_norm is None:
            raise ValueError("force_sub_text invalid")
        title = title or str(chat_norm)
        url = url or _default_join_url(chat_norm)
        if not url.startswith(("http://", "https://", "tg://")):
            raise ValueError("force_sub_text invalid")
        channels.append({"title": title, "chat": str(chat_norm), "url": url})
    return json.dumps(channels, ensure_ascii=False)


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
        "force_sub_text": _force_sub_rows_to_text(force_sub),
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
            force_sub_json = _normalize_force_sub_text(body["force_sub_text"], max_len=5000)
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


async def _put_auto_reply(request: web.Request):
    tenant = _auth(request)
    try:
        rid = int(request.match_info["rid"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid id"}, status=400)
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
    Database().update_auto_reply(
        tenant["id"], rid, keyword, reply, match_type, buttons=buttons_json)
    return web.json_response({"ok": True})


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


async def _do_broadcast(
    user_ids: list, token: str, text: str, *,
    photo: str | None = None,
    reply_markup: dict | None = None,
    silent: bool = False,
) -> None:
    """Send message to all user_ids concurrently (max 20 at a time) using the Bot API.

    When *photo* is provided a photo message is sent (caption = text).
    *reply_markup* adds inline keyboard buttons.
    *silent* disables sound/vibration notifications.
    """
    if photo:
        api_method = "sendPhoto"
        base_payload: dict = {"photo": photo, "parse_mode": "HTML"}
        if text:
            base_payload["caption"] = text
    else:
        api_method = "sendMessage"
        base_payload = {"text": text, "parse_mode": "HTML"}

    if reply_markup:
        base_payload["reply_markup"] = reply_markup
    if silent:
        base_payload["disable_notification"] = True

    api_url = f"https://api.telegram.org/bot{token}/{api_method}"
    sem = asyncio.Semaphore(20)

    async def _send(uid):
        async with sem:
            try:
                async with _aiohttp.ClientSession() as session:
                    async with session.post(
                        api_url,
                        json={**base_payload, "chat_id": uid},
                        timeout=_aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        data = await resp.json()
                        return bool(data.get("ok"))
            except Exception:
                return False

    await asyncio.gather(*(_send(uid) for uid in user_ids))


async def _post_broadcast(request: web.Request):
    tenant = _auth(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    text = _clean_text(body.get("text", ""), max_len=4096)
    if text is None:
        return web.json_response({"error": "text too long (max 4096 chars)"}, status=400)
    photo = _clean_text(body.get("photo", ""), max_len=500)
    if photo is None:
        return web.json_response({"error": "photo url too long"}, status=400)
    if photo and not photo.startswith(("http://", "https://")):
        return web.json_response({"error": "photo must be a http/https URL"}, status=400)
    if not text and not photo:
        return web.json_response({"error": "text or photo required"}, status=400)
    # Caption text is required for sendPhoto with HTML parse_mode when buttons are used;
    # allow empty caption but photo is mandatory.
    silent = bool(body.get("silent", False))
    # Parse optional inline keyboard
    reply_markup: dict | None = None
    buttons_raw = body.get("buttons", "")
    if buttons_raw:
        try:
            buttons_json = _normalize_button_text(buttons_raw, max_len=2000)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        if buttons_json:
            try:
                rows = json.loads(buttons_json)
                inline_keyboard = [
                    [{"text": btn["text"], "url": btn["url"]} for btn in row]
                    for row in rows
                ]
            except (KeyError, TypeError, ValueError):
                return web.json_response({"error": "buttons invalid"}, status=400)
            reply_markup = {"inline_keyboard": inline_keyboard}
    user_ids = Database().get_tenant_user_ids(tenant["id"], only_active=True)
    asyncio.create_task(_do_broadcast(
        user_ids, tenant["token"], text,
        photo=photo or None,
        reply_markup=reply_markup,
        silent=silent,
    ))
    return web.json_response({"ok": True, "queued": len(user_ids)}, status=202)


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
        "/api/{tenant_id}/auto_replies",       _get_auto_replies)
    app.router.add_post(
        "/api/{tenant_id}/auto_replies",       _post_auto_reply)
    app.router.add_put(
        "/api/{tenant_id}/auto_replies/{rid}", _put_auto_reply)
    app.router.add_delete(
        "/api/{tenant_id}/auto_replies/{rid}", _delete_auto_reply)
    app.router.add_get(
        "/api/{tenant_id}/banned",             _get_banned)
    app.router.add_post(
        "/api/{tenant_id}/unban/{uid}",        _post_unban)
    app.router.add_post(
        "/api/{tenant_id}/broadcast",          _post_broadcast)

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
