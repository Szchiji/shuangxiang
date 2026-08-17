import http.client
from urllib.parse import urlencode

from core.admin_web import AdminWebServer, make_autologin_token


def _request(port: int, method: str, path: str, data: dict | None = None, cookie: str = ""):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = urlencode(data or {})
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Content-Length"] = str(len(body.encode("utf-8")))
    if cookie:
        headers["Cookie"] = cookie
    conn.request(method, path, body=body if data is not None else None, headers=headers)
    res = conn.getresponse()
    payload = res.read().decode("utf-8", errors="ignore")
    out = (res.status, dict(res.getheaders()), payload)
    conn.close()
    return out


def test_admin_web_login_and_settings(db):
    token = "123456:ABCDEF"
    tid = db.add_tenant(token=token, owner_user_id=42, bot_username="robot", bot_name="R")
    server = AdminWebServer(db, host="127.0.0.1", port=0, session_ttl=600)
    server.start()
    try:
        status, _, html = _request(server.bound_port, "GET", "/admin")
        assert status == 200
        assert "机器人 Token" in html

        status, _, _ = _request(
            server.bound_port, "POST", "/admin/login", data={"token": "bad-token"}
        )
        assert status == 401

        status, headers, _ = _request(server.bound_port, "POST", "/admin/login", data={"token": token})
        assert status == 303
        cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
        assert "sx_admin_session=" in cookie

        status, _, _ = _request(
            server.bound_port,
            "POST",
            "/admin/settings",
            data={"welcome_text": "hello", "antiflood": "on"},
            cookie=cookie,
        )
        assert status == 303
        assert db.get_setting(tid, "welcome_text") == "hello"
        assert db.get_bool_setting(tid, "antiflood", False) is True
        assert db.get_bool_setting(tid, "alphabet_latin", True) is False
    finally:
        server.stop()


def test_admin_web_auto_reply_and_filters(db):
    token = "111111:ABCDEF"
    tid = db.add_tenant(token=token, owner_user_id=7, bot_username="robot", bot_name="R")
    server = AdminWebServer(db, host="127.0.0.1", port=0, session_ttl=600)
    server.start()
    try:
        _, headers, _ = _request(server.bound_port, "POST", "/admin/login", data={"token": token})
        cookie = headers.get("Set-Cookie", "").split(";", 1)[0]

        _request(
            server.bound_port,
            "POST",
            "/admin/auto_replies/add",
            data={"keyword": "价格", "reply": "见官网", "match_type": "regex", "stop": "on"},
            cookie=cookie,
        )
        rows = db.get_auto_replies(tid)
        assert len(rows) == 1
        assert rows[0]["match_type"] == "regex"
        assert rows[0]["stop"] == 1

        _request(
            server.bound_port,
            "POST",
            "/admin/auto_replies/delete",
            data={"id": str(rows[0]["id"])},
            cookie=cookie,
        )
        assert db.get_auto_replies(tid) == []

        _request(
            server.bound_port,
            "POST",
            "/admin/filters/add",
            data={"keyword": "违禁"},
            cookie=cookie,
        )
        filters = db.get_filters(tid)
        assert len(filters) == 1

        _request(
            server.bound_port,
            "POST",
            "/admin/filters/delete",
            data={"id": str(filters[0]["id"])},
            cookie=cookie,
        )
        assert db.get_filters(tid) == []
    finally:
        server.stop()


def test_admin_web_autologin_endpoint(db):
    token = "222222:ABCDEF"
    tid = db.add_tenant(token=token, owner_user_id=8, bot_username="robot", bot_name="R")
    secret = "test-secret"
    server = AdminWebServer(
        db, host="127.0.0.1", port=0, session_ttl=600, autologin_secret=secret
    )
    server.start()
    try:
        login_token = make_autologin_token(secret, tid, ttl_seconds=120)
        status, headers, _ = _request(
            server.bound_port, "GET", f"/admin/auto-login?t={login_token}"
        )
        assert status == 303
        cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
        assert "sx_admin_session=" in cookie

        status, _, html = _request(server.bound_port, "GET", "/admin", cookie=cookie)
        assert status == 200
        assert "当前机器人" in html
    finally:
        server.stop()
