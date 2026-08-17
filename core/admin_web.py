"""轻量级网页管理后台：机器人拥有者可用 Bot Token 进行配置。"""

from __future__ import annotations

import html
import secrets
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from core.database import Database

SK_WELCOME_TEXT = "welcome_text"
SK_ANTIFLOOD = "antiflood"
SK_ALPHABET_LATIN = "alphabet_latin"


def _to_bool(v: str) -> bool:
    return v in ("1", "true", "True", "on", "yes")


class AdminWebServer:
    """本地 HTTP 管理后台（无额外依赖）。"""

    def __init__(
        self,
        db: Database,
        host: str = "127.0.0.1",
        port: int = 8080,
        session_ttl: int = 3600,
    ) -> None:
        self.db = db
        self.host = host
        self.port = int(port)
        self.session_ttl = max(300, int(session_ttl))
        self._sessions: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._httpd is not None:
            return
        self._httpd = ThreadingHTTPServer((self.host, self.port), self._handler_cls())
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="admin-web-server",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def bound_port(self) -> int:
        if self._httpd is None:
            return self.port
        return int(self._httpd.server_address[1])

    def _handler_cls(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ShuangxiangAdmin/1.0"

            def log_message(self, fmt, *args):  # noqa: A003
                return

            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/admin/logout"):
                    self._logout()
                    return
                if self.path.startswith("/healthz"):
                    self._send_html("ok")
                    return
                if not self.path.startswith("/admin"):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                tenant_id = self._tenant_id_from_session()
                if tenant_id is None:
                    self._send_html(self._login_page())
                    return
                self._send_html(self._dashboard_page(tenant_id))

            def do_POST(self) -> None:  # noqa: N802
                if self.path == "/admin/login":
                    self._login()
                    return
                tenant_id = self._tenant_id_from_session()
                if tenant_id is None:
                    self._redirect("/admin")
                    return
                if self.path == "/admin/settings":
                    self._save_settings(tenant_id)
                elif self.path == "/admin/auto_replies/add":
                    self._add_auto_reply(tenant_id)
                elif self.path == "/admin/auto_replies/delete":
                    self._delete_auto_reply(tenant_id)
                elif self.path == "/admin/filters/add":
                    self._add_filter(tenant_id)
                elif self.path == "/admin/filters/delete":
                    self._delete_filter(tenant_id)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)

            def _read_form(self) -> dict[str, str]:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length).decode("utf-8", errors="ignore")
                parsed = parse_qs(raw, keep_blank_values=True)
                return {k: (v[0] if v else "") for k, v in parsed.items()}

            def _send_html(self, body: str, status: int = 200, headers: dict | None = None) -> None:
                payload = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                if headers:
                    for k, v in headers.items():
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(payload)

            def _redirect(self, to: str, headers: dict | None = None) -> None:
                hdrs = {"Location": to}
                if headers:
                    hdrs.update(headers)
                self._send_html("", status=HTTPStatus.SEE_OTHER, headers=hdrs)

            def _session_cookie(self) -> str | None:
                raw = self.headers.get("Cookie", "")
                if not raw:
                    return None
                c = SimpleCookie()
                c.load(raw)
                morsel = c.get("sx_admin_session")
                return morsel.value if morsel else None

            def _tenant_id_from_session(self) -> int | None:
                sid = self._session_cookie()
                if not sid:
                    return None
                now = time.time()
                with outer._lock:
                    item = outer._sessions.get(sid)
                    if not item:
                        return None
                    tenant_id, expire_at = item
                    if expire_at <= now:
                        outer._sessions.pop(sid, None)
                        return None
                    outer._sessions[sid] = (tenant_id, now + outer.session_ttl)
                return tenant_id

            def _new_session(self, tenant_id: int) -> str:
                sid = secrets.token_urlsafe(32)
                now = time.time()
                with outer._lock:
                    expired = [k for k, (_, exp) in outer._sessions.items() if exp <= now]
                    for k in expired:
                        outer._sessions.pop(k, None)
                    outer._sessions[sid] = (tenant_id, now + outer.session_ttl)
                return sid

            def _clear_session(self) -> None:
                sid = self._session_cookie()
                if not sid:
                    return
                with outer._lock:
                    outer._sessions.pop(sid, None)

            @staticmethod
            def _cookie_header(value: str, max_age: int) -> str:
                return (
                    f"sx_admin_session={value}; Path=/; Max-Age={max_age}; "
                    "HttpOnly; SameSite=Lax"
                )

            def _login(self) -> None:
                form = self._read_form()
                token = (form.get("token", "") or "").strip()
                tenant = outer.db.get_tenant_by_token(token) if token else None
                if not tenant:
                    self._send_html(self._login_page("Token 无效，请重试。"), status=401)
                    return
                sid = self._new_session(int(tenant["id"]))
                self._redirect(
                    "/admin",
                    headers={"Set-Cookie": self._cookie_header(sid, outer.session_ttl)},
                )

            def _logout(self) -> None:
                self._clear_session()
                self._redirect(
                    "/admin",
                    headers={"Set-Cookie": self._cookie_header("deleted", 0)},
                )

            def _save_settings(self, tenant_id: int) -> None:
                form = self._read_form()
                welcome_text = (form.get("welcome_text", "") or "").strip()
                outer.db.set_setting(tenant_id, SK_WELCOME_TEXT, welcome_text)
                outer.db.set_setting(
                    tenant_id, SK_ANTIFLOOD, "1" if form.get("antiflood") == "on" else "0"
                )
                outer.db.set_setting(
                    tenant_id,
                    SK_ALPHABET_LATIN,
                    "1" if form.get("alphabet_latin") == "on" else "0",
                )
                self._redirect("/admin")

            def _add_auto_reply(self, tenant_id: int) -> None:
                form = self._read_form()
                keyword = (form.get("keyword", "") or "").strip()
                reply = (form.get("reply", "") or "").strip()
                if keyword and reply:
                    stop = 1 if form.get("stop") == "on" else 0
                    match_type = "regex" if form.get("match_type") == "regex" else "contains"
                    outer.db.add_auto_reply(
                        tenant_id=tenant_id,
                        keyword=keyword,
                        reply=reply,
                        match_type=match_type,
                        stop=stop,
                    )
                self._redirect("/admin")

            def _delete_auto_reply(self, tenant_id: int) -> None:
                form = self._read_form()
                rid = form.get("id", "")
                if rid.isdigit():
                    outer.db.delete_auto_reply(tenant_id, int(rid))
                self._redirect("/admin")

            def _add_filter(self, tenant_id: int) -> None:
                form = self._read_form()
                keyword = (form.get("keyword", "") or "").strip()
                if keyword:
                    outer.db.add_filter(tenant_id, keyword)
                self._redirect("/admin")

            def _delete_filter(self, tenant_id: int) -> None:
                form = self._read_form()
                fid = form.get("id", "")
                if fid.isdigit():
                    outer.db.delete_filter(tenant_id, int(fid))
                self._redirect("/admin")

            @staticmethod
            def _layout(title: str, body: str) -> str:
                return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:980px;
         margin:24px auto;padding:0 16px;line-height:1.45;color:#1f2937}}
    h1,h2{{margin:0 0 12px}}
    .card{{border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin:14px 0}}
    textarea,input,select{{width:100%;padding:8px;margin:6px 0 10px;box-sizing:border-box}}
    button{{padding:8px 12px;cursor:pointer}}
    table{{width:100%;border-collapse:collapse}}
    th,td{{border-bottom:1px solid #e5e7eb;padding:8px;text-align:left;vertical-align:top}}
    .row{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
    .muted{{color:#6b7280;font-size:14px}}
  </style>
</head>
<body>
{body}
</body>
</html>"""

            def _login_page(self, error: str = "") -> str:
                err = (
                    f"<p style='color:#b91c1c'>{html.escape(error)}</p>"
                    if error
                    else "<p class='muted'>请输入你的机器人 Token 登录后台。</p>"
                )
                return self._layout(
                    "机器人管理后台",
                    f"""
<h1>🤖 机器人管理后台</h1>
{err}
<div class="card">
  <form method="post" action="/admin/login">
    <label>机器人 Token</label>
    <input name="token" type="password" placeholder="123456:ABC..." required />
    <button type="submit">登录</button>
  </form>
</div>
                    """,
                )

            def _dashboard_page(self, tenant_id: int) -> str:
                tenant = outer.db.get_tenant(tenant_id)
                if not tenant:
                    self._clear_session()
                    return self._login_page("机器人不存在或已被删除，请重新登录。")
                welcome_text = outer.db.get_setting(tenant_id, SK_WELCOME_TEXT, "") or ""
                antiflood = outer.db.get_bool_setting(tenant_id, SK_ANTIFLOOD, True)
                alphabet = outer.db.get_bool_setting(tenant_id, SK_ALPHABET_LATIN, False)
                auto_replies = outer.db.get_auto_replies(tenant_id)
                filters_rows = outer.db.get_filters(tenant_id)
                ar_rows = "".join(
                    f"""<tr>
<td>{r["id"]}</td>
<td>{html.escape(r["keyword"] or "")}</td>
<td>{html.escape(r["reply"] or "")}</td>
<td>{html.escape(r["match_type"] or "contains")}</td>
<td>{"是" if _to_bool(str(r["stop"])) else "否"}</td>
<td>
  <form method="post" action="/admin/auto_replies/delete">
    <input type="hidden" name="id" value="{r["id"]}" />
    <button type="submit">删除</button>
  </form>
</td>
</tr>"""
                    for r in auto_replies
                ) or "<tr><td colspan='6' class='muted'>暂无自动回复</td></tr>"
                filter_rows = "".join(
                    f"""<tr>
<td>{r["id"]}</td>
<td>{html.escape(r["keyword"] or "")}</td>
<td>
  <form method="post" action="/admin/filters/delete">
    <input type="hidden" name="id" value="{r["id"]}" />
    <button type="submit">删除</button>
  </form>
</td>
</tr>"""
                    for r in filters_rows
                ) or "<tr><td colspan='3' class='muted'>暂无过滤词</td></tr>"
                title = html.escape(tenant["bot_name"] or "未命名机器人")
                uname = html.escape(tenant["bot_username"] or "unknown")
                return self._layout(
                    "机器人管理后台",
                    f"""
<h1>⚙️ 机器人管理后台</h1>
<p class="muted">当前机器人：<b>{title}</b> (@{uname}) · ID #{tenant_id}
  · <a href="/admin/logout">退出登录</a></p>

<div class="card">
  <h2>基础设置</h2>
  <form method="post" action="/admin/settings">
    <label>启动语文本</label>
    <textarea name="welcome_text" rows="4"
      placeholder="用户 /start 时显示的欢迎文案">{html.escape(welcome_text)}</textarea>
    <label><input type="checkbox" name="antiflood" {"checked" if antiflood else ""} />
      启用防刷屏过滤</label><br />
    <label><input type="checkbox" name="alphabet_latin" {"checked" if alphabet else ""} />
      拦截拉丁字母（英文）消息</label><br /><br />
    <button type="submit">保存设置</button>
  </form>
</div>

<div class="card">
  <h2>自动回复</h2>
  <form method="post" action="/admin/auto_replies/add">
    <div class="row">
      <div>
        <label>关键词</label>
        <input name="keyword" required />
      </div>
      <div>
        <label>匹配方式</label>
        <select name="match_type">
          <option value="contains">包含</option>
          <option value="regex">正则</option>
        </select>
      </div>
    </div>
    <label>回复内容</label>
    <textarea name="reply" rows="3" required></textarea>
    <label><input type="checkbox" name="stop" /> 命中后拦截，不再转发给管理员</label><br /><br />
    <button type="submit">新增自动回复</button>
  </form>
  <table>
    <thead><tr><th>ID</th><th>关键词</th><th>回复</th><th>匹配</th><th>拦截</th><th>操作</th></tr></thead>
    <tbody>{ar_rows}</tbody>
  </table>
</div>

<div class="card">
  <h2>关键词过滤</h2>
  <form method="post" action="/admin/filters/add">
    <label>过滤词</label>
    <input name="keyword" required />
    <button type="submit">新增过滤词</button>
  </form>
  <table>
    <thead><tr><th>ID</th><th>关键词</th><th>操作</th></tr></thead>
    <tbody>{filter_rows}</tbody>
  </table>
</div>
                    """,
                )

        return Handler
