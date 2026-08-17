"""Web admin backend for bot management (Telegram Mini App).

Provides an aiohttp web server that serves a Telegram WebApp-based admin panel,
allowing bot admins to manage their bots via a browser interface instead of
private chat commands.

Authentication uses Telegram's WebApp initData HMAC-SHA256 validation:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web

from core.database import Database
from modules.auto_reply_module import SK_ALPHABET_LATIN, SK_ANTIFLOOD
from modules.customize_module import (
    SK_FORCE_SUB_ON,
    SK_WELCOME_BTNS,
    SK_WELCOME_TEXT,
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
    return web.json_response({
        "welcome_text":   db.get_setting(tid, SK_WELCOME_TEXT, "") or "",
        "welcome_btns":   db.get_setting(tid, SK_WELCOME_BTNS, "") or "",
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
    for key in (SK_WELCOME_TEXT, SK_WELCOME_BTNS):
        if key in body:
            db.set_setting(tid, key, str(body[key]))
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
    return web.json_response([dict(r) for r in rows])


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
    rid = Database().add_auto_reply(tenant["id"], keyword, reply, match_type)
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
