"""交互式自定义模块（启动语/按钮/强制订阅/广播）测试。"""

import json
import types

import pytest

from modules.customize_module import (
    SK_FORCE_SUB,
    SK_FORCE_SUB_ON,
    SK_WELCOME_BTNS,
    SK_WELCOME_TEXT,
    CustomizeModule,
    load_button_rows,
    parse_buttons,
    rows_to_keyboard,
)
from modules.private_chat_module import PrivateChatModule

# ── 假对象 ───────────────────────────────────────────────────

class FakeBot:
    def __init__(self, member_status=None, fail=False):
        self.member_status = member_status
        self.fail = fail
        self.copies = []

    async def get_chat_member(self, chat, user_id):
        if self.fail:
            from telegram.error import TelegramError
            raise TelegramError("not admin")
        return types.SimpleNamespace(status=self.member_status)

    async def copy_message(self, **k):
        self.copies.append(k)
        return types.SimpleNamespace(message_id=1)


class FakeMessage:
    def __init__(self, text=None, caption=None, chat_id=7, message_id=1):
        self.text = text
        self.caption = caption
        self.chat_id = chat_id
        self.message_id = message_id
        self.replies = []
        self.media_replies = []

    async def reply_text(self, text, **k):
        self.replies.append((text, k))

    async def reply_photo(self, file_id, **k):
        self.media_replies.append(("photo", file_id, k))

    async def reply_video(self, file_id, **k):
        self.media_replies.append(("video", file_id, k))


def make_cz(db, admin_id=99):
    mod = CustomizeModule.__new__(CustomizeModule)
    mod.db = db
    mod.tenant_id = 1
    mod.admin_id = admin_id
    return mod


def make_ctx(bot=None):
    return types.SimpleNamespace(bot=bot, user_data={})


def make_update(user_id, message, chat_type="private"):
    return types.SimpleNamespace(
        message=message,
        effective_user=types.SimpleNamespace(
            id=user_id, username="u", full_name="User"),
        effective_chat=types.SimpleNamespace(type=chat_type, id=user_id),
    )


# ── 按钮解析 ─────────────────────────────────────────────────

def test_parse_buttons_valid_and_invalid():
    rows = parse_buttons(
        "官方频道 - https://t.me/a\n"
        "客服 | https://t.me/b\n"
        "无效行没有链接\n"
        "坏链接 - ftp://x")
    flat = [b for row in rows for b in row]
    assert [b["text"] for b in flat] == ["官方频道", "客服"]
    assert flat[0]["url"] == "https://t.me/a"


def test_parse_buttons_multiple_per_row():
    rows = parse_buttons(
        "频道 - https://t.me/a && 客服 - https://t.me/b\n"
        "单独 - https://t.me/c")
    assert [[b["text"] for b in row] for row in rows] == [["频道", "客服"], ["单独"]]
    assert rows[0][1]["url"] == "https://t.me/b"


def test_parse_buttons_skips_invalid_cells_in_row():
    rows = parse_buttons("好 - https://t.me/a && 坏 - ftp://x && 也好 - https://t.me/b")
    assert [[b["text"] for b in row] for row in rows] == [["好", "也好"]]


def test_rows_to_keyboard_skips_incomplete():
    kb = rows_to_keyboard([[{"text": "a", "url": "https://t.me/a"}],
                           [{"text": "", "url": "https://t.me/b"}]])
    assert len(kb) == 1
    assert kb[0][0].url == "https://t.me/a"


def test_load_button_rows_handles_bad_json(db):
    db.set_setting(1, SK_WELCOME_BTNS, "{not json")
    assert load_button_rows(db, 1, SK_WELCOME_BTNS) == []


# ── 启动语自定义渲染 ─────────────────────────────────────────

def _make_pc(db, admin_id=99):
    mod = PrivateChatModule.__new__(PrivateChatModule)
    mod.db = db
    mod.tenant_id = 1
    mod.admin_id = admin_id
    mod.welcome = "默认欢迎"
    mod.brand = ""
    mod._manage_group = lambda: None
    return mod


@pytest.mark.asyncio
async def test_cmd_start_uses_custom_welcome_and_buttons(db):
    pc = _make_pc(db)
    db.set_setting(1, SK_WELCOME_TEXT, "自定义欢迎语")
    db.set_setting(1, SK_WELCOME_BTNS,
                   json.dumps([[{"text": "频道", "url": "https://t.me/x"}]]))
    msg = FakeMessage()
    await pc.cmd_start(make_update(7, msg), None)
    text, kwargs = msg.replies[0]
    assert "自定义欢迎语" in text
    kb = kwargs["reply_markup"].inline_keyboard
    assert kb[0][0].text == "频道" and kb[0][0].url == "https://t.me/x"


@pytest.mark.asyncio
async def test_cmd_start_falls_back_to_default_welcome(db):
    pc = _make_pc(db)
    msg = FakeMessage()
    await pc.cmd_start(make_update(7, msg), None)
    text, _ = msg.replies[0]
    assert "默认欢迎" in text


@pytest.mark.asyncio
async def test_cmd_start_sends_welcome_media(db):
    from modules.customize_module import SK_WELCOME_MEDIA_ID, SK_WELCOME_MEDIA_TYPE
    pc = _make_pc(db)
    db.set_setting(1, SK_WELCOME_TEXT, "带图欢迎")
    db.set_setting(1, SK_WELCOME_MEDIA_TYPE, "photo")
    db.set_setting(1, SK_WELCOME_MEDIA_ID, "WPIC")
    msg = FakeMessage()
    await pc.cmd_start(make_update(7, msg), None)
    assert not msg.replies  # 不走纯文本路径
    assert msg.media_replies and msg.media_replies[0][0] == "photo"
    assert msg.media_replies[0][1] == "WPIC"
    assert "带图欢迎" in msg.media_replies[0][2]["caption"]


# ── 自动回复按钮渲染 ─────────────────────────────────────────

def test_auto_reply_markup_from_buttons(db):
    from modules.auto_reply_module import AutoReplyModule
    db.add_auto_reply(1, "价格", "见官网", "contains", 0,
                      json.dumps([[{"text": "官网", "url": "https://e.com"}]]))
    row = db.get_auto_replies(1)[0]
    markup = AutoReplyModule._reply_markup(row)
    assert markup.inline_keyboard[0][0].url == "https://e.com"


def test_auto_reply_markup_none_when_no_buttons(db):
    from modules.auto_reply_module import AutoReplyModule
    db.add_auto_reply(1, "价格", "见官网")
    row = db.get_auto_replies(1)[0]
    assert AutoReplyModule._reply_markup(row) is None


def test_auto_reply_markup_multi_button_row(db):
    from modules.auto_reply_module import AutoReplyModule
    rows = parse_buttons("频道 - https://t.me/a && 客服 - https://t.me/b")
    db.add_auto_reply(1, "价格", "见官网", "contains", 0,
                      json.dumps(rows, ensure_ascii=False))
    row = db.get_auto_replies(1)[0]
    markup = AutoReplyModule._reply_markup(row)
    assert len(markup.inline_keyboard) == 1
    assert [b.text for b in markup.inline_keyboard[0]] == ["频道", "客服"]
    assert markup.inline_keyboard[0][1].url == "https://t.me/b"


# ── 引导式向导：启动语 ───────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_welcome_saves(db):
    cz = make_cz(db)
    ctx = make_ctx()
    ctx.user_data["cz"] = {"flow": "welcome"}
    msg = FakeMessage(text="新的欢迎语")
    await cz._wizard_welcome(msg, ctx)
    assert db.get_setting(1, SK_WELCOME_TEXT) == "新的欢迎语"
    assert "cz" not in ctx.user_data


# ── 启动语：文本与按钮统一管理（合并为一个功能）────────────

class _CbQuery:
    def __init__(self, user_id, data):
        self.from_user = types.SimpleNamespace(id=user_id)
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, *a, **k):
        self.answers.append((a, k))

    async def edit_message_text(self, text, **k):
        self.edits.append((text, k))


def _cz_callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_welcome_screen_combines_text_and_buttons(db):
    cz = make_cz(db)
    q = _CbQuery(99, "cz:welcome")
    await cz._show_welcome(q, types.SimpleNamespace(user_data={}))
    cbs = _cz_callbacks(q.edits[0][1]["reply_markup"])
    # 同一界面同时提供编辑文本、编辑按钮、清空按钮，以及返回控制面板
    assert "cz:welcome:text" in cbs
    assert "cz:wbtns:edit" in cbs
    assert "cz:wbtns:clear" in cbs
    assert "pc:home" in cbs


def test_settings_markup_has_single_welcome_entry_and_panel_return(db):
    cz = make_cz(db)
    cbs = _cz_callbacks(cz._settings_markup())
    assert "cz:welcome" in cbs
    assert "cz:wbtns" not in cbs       # 启动按钮已并入启动语
    assert "pc:home" in cbs            # 返回控制面板


def test_back_markup_returns_to_control_panel(db):
    cz = make_cz(db)
    assert "pc:home" in _cz_callbacks(cz._back_markup())



# ── 引导式向导：自动回复（含按钮）───────────────────────────

@pytest.mark.asyncio
async def test_wizard_ar_full_flow(db):
    cz = make_cz(db)
    ctx = make_ctx()
    state = {"flow": "ar", "step": "keyword", "buf": {}}
    ctx.user_data["cz"] = state
    await cz._wizard_ar(FakeMessage(text="价格"), ctx, state)
    assert state["step"] == "match"
    # 第 2 步：选择匹配方式（包含）
    await cz._pick_ar_match(_CbQuery(99, "cz:ar:mt:contains"), ctx, "contains")
    assert state["step"] == "reply"
    await cz._wizard_ar(FakeMessage(text="见官网"), ctx, state)
    await cz._wizard_ar(
        FakeMessage(text="官网 - https://e.com"), ctx, state)
    rows = db.get_auto_replies(1)
    assert len(rows) == 1
    assert rows[0]["keyword"] == "价格"
    assert rows[0]["match_type"] == "contains"
    btns = json.loads(rows[0]["buttons"])
    assert btns[0][0]["url"] == "https://e.com"


@pytest.mark.asyncio
async def test_wizard_ar_regex_flow(db):
    cz = make_cz(db)
    ctx = make_ctx()
    state = {"flow": "ar", "step": "keyword", "buf": {}}
    ctx.user_data["cz"] = state
    await cz._wizard_ar(FakeMessage(text=r"价格|报价"), ctx, state)
    await cz._pick_ar_match(_CbQuery(99, "cz:ar:mt:regex"), ctx, "regex")
    assert state["step"] == "reply"
    await cz._wizard_ar(FakeMessage(text="见官网"), ctx, state)
    await cz._wizard_ar(FakeMessage(text="跳过"), ctx, state)
    rows = db.get_auto_replies(1)
    assert rows[0]["match_type"] == "regex"


@pytest.mark.asyncio
async def test_wizard_ar_regex_rejects_invalid_pattern(db):
    cz = make_cz(db)
    ctx = make_ctx()
    state = {"flow": "ar", "step": "keyword", "buf": {}}
    ctx.user_data["cz"] = state
    await cz._wizard_ar(FakeMessage(text="("), ctx, state)  # 非法正则
    q = _CbQuery(99, "cz:ar:mt:regex")
    await cz._pick_ar_match(q, ctx, "regex")
    # 仍停留在 match 步，并弹出告警
    assert state["step"] == "match"
    assert q.answers and q.answers[-1][1].get("show_alert") is True
    assert db.get_auto_replies(1) == []


@pytest.mark.asyncio
async def test_wizard_ar_skip_buttons(db):
    cz = make_cz(db)
    ctx = make_ctx()
    state = {"flow": "ar", "step": "buttons", "buf": {"keyword": "k", "reply": "r"}}
    ctx.user_data["cz"] = state
    await cz._wizard_ar(FakeMessage(text="跳过"), ctx, state)
    assert db.get_auto_replies(1)[0]["buttons"] == ""


# ── 引导式向导：自动回复编辑 / 多媒体 ────────────────────────

@pytest.mark.asyncio
async def test_wizard_ar_edit_updates_existing(db):
    cz = make_cz(db)
    ctx = make_ctx()
    rid = db.add_auto_reply(1, "旧词", "旧回复", "contains", 0)
    # 进入编辑：复用向导，预置 edit_id
    q = _CbQuery(99, f"cz:ar:edit:{rid}")
    await cz._start_ar_edit(q, ctx, rid)
    state = ctx.user_data["cz"]
    assert state["buf"]["edit_id"] == rid
    await cz._wizard_ar(FakeMessage(text="新词"), ctx, state)
    await cz._pick_ar_match(_CbQuery(99, "cz:ar:mt:contains"), ctx, "contains")
    await cz._wizard_ar(FakeMessage(text="新回复"), ctx, state)
    await cz._wizard_ar(FakeMessage(text="跳过"), ctx, state)
    rows = db.get_auto_replies(1)
    # 仍是同一条记录（未新增），内容已更新
    assert len(rows) == 1
    assert rows[0]["id"] == rid
    assert rows[0]["keyword"] == "新词"
    assert rows[0]["reply"] == "新回复"


@pytest.mark.asyncio
async def test_wizard_ar_reply_accepts_media(db):
    import types as _t
    cz = make_cz(db)
    ctx = make_ctx()
    state = {"flow": "ar", "step": "reply", "buf": {"keyword": "k"}}
    ctx.user_data["cz"] = state
    msg = FakeMessage(caption="看图")
    msg.photo = [_t.SimpleNamespace(file_id="PHOTO123")]
    await cz._wizard_ar(msg, ctx, state)
    await cz._wizard_ar(FakeMessage(text="跳过"), ctx, state)
    row = db.get_auto_replies(1)[0]
    assert row["reply"] == "看图"
    assert row["media_type"] == "photo"
    assert row["media_id"] == "PHOTO123"


@pytest.mark.asyncio
async def test_wizard_welcome_saves_media(db):
    import types as _t

    from modules.customize_module import (
        SK_WELCOME_MEDIA_ID,
        SK_WELCOME_MEDIA_TYPE,
    )
    cz = make_cz(db)
    ctx = make_ctx()
    ctx.user_data["cz"] = {"flow": "welcome"}
    msg = FakeMessage(caption="封面欢迎")
    msg.video = _t.SimpleNamespace(file_id="VID9")
    await cz._wizard_welcome(msg, ctx)
    assert db.get_setting(1, SK_WELCOME_TEXT) == "封面欢迎"
    assert db.get_setting(1, SK_WELCOME_MEDIA_TYPE) == "video"
    assert db.get_setting(1, SK_WELCOME_MEDIA_ID) == "VID9"


def test_show_ar_lists_edit_buttons(db):
    cz = make_cz(db)
    rid = db.add_auto_reply(1, "价格", "见官网")

    import asyncio
    q = _CbQuery(99, "cz:ar")
    asyncio.run(cz._show_ar(q, types.SimpleNamespace(user_data={})))
    cbs = _cz_callbacks(q.edits[0][1]["reply_markup"])
    assert f"cz:ar:edit:{rid}" in cbs
    assert f"cz:ar:del:{rid}" in cbs


# ── 引导式向导：强制订阅 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_fsub_adds_and_enables(db):
    cz = make_cz(db)
    ctx = make_ctx()
    ctx.user_data["cz"] = {"flow": "fsub"}
    msg = FakeMessage(text="官方 | @chan | https://t.me/chan")
    await cz._wizard_fsub(msg, ctx)
    channels = json.loads(db.get_setting(1, SK_FORCE_SUB))
    assert channels[0]["chat"] == "@chan"
    assert db.get_bool_setting(1, SK_FORCE_SUB_ON, False) is True


# ── 强制订阅拦截 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guard_blocks_unsubscribed(db):
    cz = make_cz(db)
    db.set_setting(1, SK_FORCE_SUB_ON, "1")
    db.set_setting(1, SK_FORCE_SUB,
                   json.dumps([{"title": "f", "chat": "@c", "url": "https://t.me/c"}]))
    ctx = make_ctx(FakeBot(member_status="left"))
    msg = FakeMessage(text="hi")
    from telegram.ext import ApplicationHandlerStop
    with pytest.raises(ApplicationHandlerStop):
        await cz.on_guard(make_update(7, msg), ctx)
    assert msg.replies  # 收到加入提示


@pytest.mark.asyncio
async def test_guard_allows_subscribed(db):
    cz = make_cz(db)
    db.set_setting(1, SK_FORCE_SUB_ON, "1")
    db.set_setting(1, SK_FORCE_SUB,
                   json.dumps([{"title": "f", "chat": "@c", "url": "https://t.me/c"}]))
    ctx = make_ctx(FakeBot(member_status="member"))
    msg = FakeMessage(text="hi")
    await cz.on_guard(make_update(7, msg), ctx)  # 不抛出
    assert not msg.replies


@pytest.mark.asyncio
async def test_guard_fail_open_on_error(db):
    cz = make_cz(db)
    db.set_setting(1, SK_FORCE_SUB_ON, "1")
    db.set_setting(1, SK_FORCE_SUB,
                   json.dumps([{"title": "f", "chat": "@c", "url": "https://t.me/c"}]))
    ctx = make_ctx(FakeBot(fail=True))
    msg = FakeMessage(text="hi")
    await cz.on_guard(make_update(7, msg), ctx)  # 校验失败时放行
    assert not msg.replies


@pytest.mark.asyncio
async def test_guard_ignores_admin(db):
    cz = make_cz(db)
    db.set_setting(1, SK_FORCE_SUB_ON, "1")
    db.set_setting(1, SK_FORCE_SUB,
                   json.dumps([{"title": "f", "chat": "@c", "url": "https://t.me/c"}]))
    ctx = make_ctx(FakeBot(member_status="left"))
    msg = FakeMessage(text="hi")
    await cz.on_guard(make_update(99, msg), ctx)  # 管理员不受限
    assert not msg.replies


# ── 广播 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broadcast_sends_to_active_users(db):
    cz = make_cz(db)
    db.upsert_tenant_user(1, 11, "a", "A")
    db.upsert_tenant_user(1, 22, "b", "B")
    db.upsert_tenant_user(1, 33, "c", "C")
    db.ban_user(1, 33)  # 封禁用户不应收到
    bot = FakeBot()
    ctx = make_ctx(bot)
    sent, failed = await cz._broadcast(ctx, from_chat_id=99, message_id=5)
    assert sent == 2 and failed == 0
    assert {c["chat_id"] for c in bot.copies} == {11, 22}


# ── 我已订阅复核 ─────────────────────────────────────────────

class FakeQuery:
    def __init__(self, user_id):
        self.from_user = types.SimpleNamespace(id=user_id)
        self.answers = []
        self.edits = []

    async def answer(self, *a, **k):
        self.answers.append((a, k))

    async def edit_message_text(self, text, **k):
        self.edits.append(text)


@pytest.mark.asyncio
async def test_checksub_still_missing(db):
    cz = make_cz(db)
    db.set_setting(1, SK_FORCE_SUB_ON, "1")
    db.set_setting(1, SK_FORCE_SUB,
                   json.dumps([{"title": "f", "chat": "@c", "url": "https://t.me/c"}]))
    ctx = make_ctx(FakeBot(member_status="left"))
    q = FakeQuery(7)
    await cz._on_checksub(q, ctx)
    assert q.answers and q.answers[0][1].get("show_alert") is True


@pytest.mark.asyncio
async def test_checksub_passes(db):
    cz = make_cz(db)
    db.set_setting(1, SK_FORCE_SUB_ON, "1")
    db.set_setting(1, SK_FORCE_SUB,
                   json.dumps([{"title": "f", "chat": "@c", "url": "https://t.me/c"}]))
    ctx = make_ctx(FakeBot(member_status="member"))
    q = FakeQuery(7)
    await cz._on_checksub(q, ctx)
    assert q.edits and "感谢订阅" in q.edits[0]
