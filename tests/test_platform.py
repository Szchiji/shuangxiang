"""平台机器人启动信息自定义 + 租户启动信息底部平台署名测试。"""

import json
import types

import pytest

from modules.platform_module import (
    MENU_ADMIN,
    MENU_CREATE,
    MENU_MYBOTS,
    MENU_NEWBOT,
    PLATFORM_TID,
    SK_PLATFORM_BOT_USERNAME,
    SK_PLATFORM_BOT_USERNAME_AUTO,
    SK_PLATFORM_START_BTNS,
    SK_PLATFORM_START_TEXT,
    PlatformModule,
    _reply_keyboard,
    platform_footer_username,
)
from modules.private_chat_module import PrivateChatModule

# ── 假对象 ───────────────────────────────────────────────────

class FakeQuery:
    def __init__(self, user_id, data):
        self.from_user = types.SimpleNamespace(id=user_id)
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, *a, **k):
        self.answers.append((a, k))

    async def edit_message_text(self, text, **k):
        self.edits.append((text, k))


class FakeMessage:
    def __init__(self, text=None):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **k):
        self.replies.append((text, k))


def make_pf(db, super_admin=99):
    mod = PlatformModule.__new__(PlatformModule)
    mod.db = db
    mod.super_admin = super_admin
    return mod


def make_cbk_update(query):
    return types.SimpleNamespace(callback_query=query)


def make_text_update(user_id, message):
    return types.SimpleNamespace(
        message=message,
        effective_user=types.SimpleNamespace(id=user_id),
        effective_message=message,
    )


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# ── 启动面板：管理入口仅对超级管理员可见 ─────────────────────

def test_home_markup_admin_only_settings_button(db):
    pf = make_pf(db)
    assert "pf:admin" in _callbacks(pf._home_markup(99))      # 超级管理员
    assert "pf:admin" not in _callbacks(pf._home_markup(1234))  # 普通用户


def test_home_markup_includes_custom_buttons(db):
    pf = make_pf(db)
    db.set_setting(PLATFORM_TID, SK_PLATFORM_START_BTNS,
                   json.dumps([[{"text": "频道", "url": "https://t.me/x"}]]))
    markup = pf._home_markup(1234)
    urls = [b.url for row in markup.inline_keyboard for b in row if b.url]
    assert "https://t.me/x" in urls


# ── 启动信息文本：自定义优先，否则默认 ──────────────────────

def test_start_text_custom_overrides_default(db):
    pf = make_pf(db)
    assert "工厂" in pf._start_text()  # 默认
    db.set_setting(PLATFORM_TID, SK_PLATFORM_START_TEXT, "自定义启动信息")
    assert pf._start_text() == "自定义启动信息"


# ── 仅超级管理员可进入平台设置 ──────────────────────────────

@pytest.mark.asyncio
async def test_non_admin_cannot_open_admin(db):
    pf = make_pf(db)
    q = FakeQuery(1234, "pf:admin")
    await pf.on_callback(make_cbk_update(q), types.SimpleNamespace(
        chat_data={}, user_data={}))
    assert q.answers and q.answers[0][1].get("show_alert") is True
    assert not q.edits


@pytest.mark.asyncio
async def test_admin_can_open_admin_panel(db):
    pf = make_pf(db)
    q = FakeQuery(99, "pf:admin")
    await pf.on_callback(make_cbk_update(q), types.SimpleNamespace(
        chat_data={}, user_data={}))
    assert q.edits
    cbs = _callbacks(q.edits[0][1]["reply_markup"])
    assert "pf:admin:text" in cbs and "pf:admin:uname" in cbs


def test_admin_text_escapes_username_underscores(db):
    """平台用户名含下划线时，平台设置面板文本须转义，避免 Markdown 解析失败。

    复现「超级管理员点击平台设置按钮无反应」：自动探测到的平台机器人用户名
    （常以 _bot 结尾）含奇数个下划线，未转义会导致 edit_message_text 报错。
    """
    pf = make_pf(db)
    db.set_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME, "my_factory_bot")
    text = pf._admin_text()
    assert "@my\\_factory\\_bot" in text
    assert "my_factory_bot" not in text


# ── 管理员输入：保存启动信息 / 按钮 / 平台用户名 ─────────────

@pytest.mark.asyncio
async def test_admin_input_saves_start_text(db):
    pf = make_pf(db)
    ctx = types.SimpleNamespace(chat_data={}, user_data={"pf_admin_flow": "text"})
    msg = FakeMessage(text="新的启动信息")
    await pf.on_text(make_text_update(99, msg), ctx)
    assert db.get_setting(PLATFORM_TID, SK_PLATFORM_START_TEXT) == "新的启动信息"
    assert "pf_admin_flow" not in ctx.user_data


@pytest.mark.asyncio
async def test_admin_input_saves_buttons(db):
    pf = make_pf(db)
    ctx = types.SimpleNamespace(chat_data={}, user_data={"pf_admin_flow": "btns"})
    msg = FakeMessage(text="频道 - https://t.me/x")
    await pf.on_text(make_text_update(99, msg), ctx)
    rows = json.loads(db.get_setting(PLATFORM_TID, SK_PLATFORM_START_BTNS))
    assert rows[0][0]["url"] == "https://t.me/x"


@pytest.mark.asyncio
async def test_admin_input_saves_username_strips_at(db):
    pf = make_pf(db)
    ctx = types.SimpleNamespace(chat_data={}, user_data={"pf_admin_flow": "uname"})
    msg = FakeMessage(text="@MyPlatformBot")
    await pf.on_text(make_text_update(99, msg), ctx)
    assert db.get_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME) == "MyPlatformBot"


@pytest.mark.asyncio
async def test_admin_input_clear_username(db):
    pf = make_pf(db)
    db.set_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME, "Old")
    ctx = types.SimpleNamespace(chat_data={}, user_data={"pf_admin_flow": "uname"})
    await pf.on_text(make_text_update(99, FakeMessage(text="清空")), ctx)
    assert db.get_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME) == ""


@pytest.mark.asyncio
async def test_non_admin_text_not_treated_as_admin_flow(db):
    """普通用户即便残留 flow 也不应触发管理员保存。"""
    pf = make_pf(db)
    ctx = types.SimpleNamespace(
        chat_data={}, user_data={"pf_admin_flow": "text"})
    await pf.on_text(make_text_update(1234, FakeMessage(text="x")), ctx)
    assert db.get_setting(PLATFORM_TID, SK_PLATFORM_START_TEXT) is None


# ── 底部键盘菜单 ────────────────────────────────────────────

def _reply_labels(markup):
    return [b.text for row in markup.keyboard for b in row]


def test_reply_keyboard_admin_shows_settings():
    assert MENU_ADMIN in _reply_labels(_reply_keyboard(is_super_admin=True))
    assert MENU_ADMIN not in _reply_labels(_reply_keyboard(is_super_admin=False))


@pytest.mark.asyncio
async def test_menu_button_newbot_enters_token_flow(db):
    pf = make_pf(db)
    ctx = types.SimpleNamespace(chat_data={}, user_data={})
    await pf.on_text(make_text_update(1234, FakeMessage(text=MENU_NEWBOT)), ctx)
    assert ctx.chat_data.get("awaiting_token") is True


@pytest.mark.asyncio
async def test_menu_button_mybots_shows_view(db):
    pf = make_pf(db)
    ctx = types.SimpleNamespace(chat_data={}, user_data={})
    msg = FakeMessage(text=MENU_MYBOTS)
    await pf.on_text(make_text_update(1234, msg), ctx)
    assert msg.replies  # 渲染了「我的机器人」视图


@pytest.mark.asyncio
async def test_menu_admin_for_non_admin_falls_back_home(db):
    pf = make_pf(db)
    db.set_setting(PLATFORM_TID, SK_PLATFORM_START_TEXT, "主页文本")
    ctx = types.SimpleNamespace(chat_data={}, user_data={})
    msg = FakeMessage(text=MENU_ADMIN)
    await pf.on_text(make_text_update(1234, msg), ctx)
    assert msg.replies[0][0] == "主页文本"  # 普通用户回退到主菜单


@pytest.mark.asyncio
async def test_menu_admin_for_admin_opens_settings(db):
    pf = make_pf(db)
    ctx = types.SimpleNamespace(chat_data={}, user_data={})
    msg = FakeMessage(text=MENU_ADMIN)
    await pf.on_text(make_text_update(99, msg), ctx)
    cbs = _callbacks(msg.replies[0][1]["reply_markup"])
    assert "pf:admin:text" in cbs


@pytest.mark.asyncio
async def test_menu_button_clears_pending_admin_flow(db):
    """超级管理员处于输入流程时点击底部菜单，应取消流程而非保存输入。"""
    pf = make_pf(db)
    ctx = types.SimpleNamespace(
        chat_data={}, user_data={"pf_admin_flow": "text"})
    await pf.on_text(make_text_update(99, FakeMessage(text=MENU_CREATE)), ctx)
    assert "pf_admin_flow" not in ctx.user_data
    assert db.get_setting(PLATFORM_TID, SK_PLATFORM_START_TEXT) is None


# ── 我的机器人：转义 + 删除按钮 ──────────────────────────────

def test_mybots_view_escapes_username_and_has_delete_button(db):
    """机器人用户名常以 _bot 结尾，未转义会导致「我的机器人」点击无反应。"""
    pf = make_pf(db)
    tid = db.add_tenant("123:tok", owner_user_id=1234,
                        bot_username="my_feedback_bot", bot_name="反馈_机器人")
    text, markup = pf._mybots_view(1234)
    assert "@my\\_feedback\\_bot" in text
    assert "反馈\\_机器人" in text
    assert f"pf:delask:{tid}" in _callbacks(markup)


def test_mybots_view_empty_offers_create(db):
    pf = make_pf(db)
    text, markup = pf._mybots_view(1234)
    assert "pf:newbot" in _callbacks(markup)


@pytest.mark.asyncio
async def test_delete_ask_then_confirm_removes_tenant(db):
    pf = make_pf(db)
    tid = db.add_tenant("123:tok", owner_user_id=1234,
                        bot_username="b_bot", bot_name="B")
    ctx = types.SimpleNamespace(
        chat_data={}, user_data={},
        application=types.SimpleNamespace(bot_data={}))
    # 第一步：请求删除 → 显示确认按钮
    q = FakeQuery(1234, f"pf:delask:{tid}")
    await pf.on_callback(make_cbk_update(q), ctx)
    assert f"pf:delyes:{tid}" in _callbacks(q.edits[0][1]["reply_markup"])
    # 第二步：确认删除 → 租户被移除
    q2 = FakeQuery(1234, f"pf:delyes:{tid}")
    await pf.on_callback(make_cbk_update(q2), ctx)
    assert db.get_tenant(tid) is None


@pytest.mark.asyncio
async def test_delete_rejects_non_owner(db):
    pf = make_pf(db)
    tid = db.add_tenant("123:tok", owner_user_id=1234,
                        bot_username="b_bot", bot_name="B")
    ctx = types.SimpleNamespace(
        chat_data={}, user_data={},
        application=types.SimpleNamespace(bot_data={}))
    q = FakeQuery(5678, f"pf:delyes:{tid}")
    await pf.on_callback(make_cbk_update(q), ctx)
    assert q.answers and q.answers[0][1].get("show_alert") is True
    assert db.get_tenant(tid) is not None


# ── 平台署名：自定义优先，回退自动探测 ──────────────────────
def test_platform_footer_username_prefers_custom(db):
    assert platform_footer_username(db) == ""
    db.set_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME_AUTO, "AutoBot")
    assert platform_footer_username(db) == "AutoBot"
    db.set_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME, "@CustomBot")
    assert platform_footer_username(db) == "CustomBot"


# ── 租户启动信息底部展示平台用户名 ──────────────────────────

def _make_pc(db, admin_id=99):
    mod = PrivateChatModule.__new__(PrivateChatModule)
    mod.db = db
    mod.tenant_id = 1
    mod.admin_id = admin_id
    mod.welcome = "默认欢迎"
    mod.brand = ""
    mod._manage_group = lambda: None
    return mod


class _Msg:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **k):
        self.replies.append((text, k))


def _user_update(uid=7):
    return types.SimpleNamespace(
        effective_chat=types.SimpleNamespace(type="private"),
        effective_user=types.SimpleNamespace(
            id=uid, username="u", full_name="User"),
        message=_Msg(),
    )


@pytest.mark.asyncio
async def test_tenant_start_shows_platform_username(db):
    pc = _make_pc(db)
    db.set_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME, "FactoryBot")
    upd = _user_update()
    await pc.cmd_start(upd, None)
    text, _ = upd.message.replies[0]
    assert "@FactoryBot" in text


@pytest.mark.asyncio
async def test_tenant_start_no_footer_when_unset(db):
    pc = _make_pc(db)
    upd = _user_update()
    await pc.cmd_start(upd, None)
    text, _ = upd.message.replies[0]
    assert "由 @" not in text
