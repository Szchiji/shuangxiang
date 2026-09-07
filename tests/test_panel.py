"""控制面板与用户导航按钮（UI 升级）测试。"""

import types

import pytest

from modules.auto_reply_module import SK_ALPHABET_LATIN, SK_ANTIFLOOD
from modules.private_chat_module import PrivateChatModule


def make_module(db, manage_group=None, admin_id=99):
    mod = PrivateChatModule.__new__(PrivateChatModule)
    mod.db = db
    mod.tenant_id = 1
    mod.admin_id = admin_id
    mod._manage_group = lambda: manage_group
    return mod


def _button_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


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


def make_cbk_update(query):
    return types.SimpleNamespace(callback_query=query)


# ── 控制面板按钮反映开关状态 ─────────────────────────────────

def test_panel_markup_default_states(db):
    mod = make_module(db)
    texts = _button_texts(mod._panel_markup())
    assert any("防刷屏：✅ 开" in t for t in texts)      # 默认开启
    assert any("拦截英文：⛔ 关" in t for t in texts)     # 默认关闭
    assert any("Topics 模式：未启用" in t for t in texts)


def test_panel_markup_reflects_topics_enabled(db):
    mod = make_module(db, manage_group=-100)
    texts = _button_texts(mod._panel_markup())
    assert any("Topics 模式：✅ 已启用" in t for t in texts)


def test_panel_surfaces_autoreply_and_customize_shortcuts(db):
    """面板应直达自动回复等常用自定义功能（人性化升级）。"""
    mod = make_module(db)
    cbs = _callbacks(mod._panel_markup())
    assert "cz:ar" in cbs       # 💬 自动回复
    assert "cz:welcome" in cbs  # ✏️ 启动语
    assert "cz:bc" in cbs       # 📣 群发广播
    assert "pc:stats" in cbs    # 📊 数据统计


# ── 按钮切换防刷屏 / 英文拦截 ─────────────────────────────────

@pytest.mark.asyncio
async def test_toggle_antiflood_via_button(db):
    mod = make_module(db)
    assert db.get_bool_setting(1, SK_ANTIFLOOD, True) is True
    q = FakeQuery(99, "pc:toggle:antiflood")
    await mod.on_panel(make_cbk_update(q), None)
    assert db.get_bool_setting(1, SK_ANTIFLOOD, True) is False
    # 再点一次切回开启
    q2 = FakeQuery(99, "pc:toggle:antiflood")
    await mod.on_panel(make_cbk_update(q2), None)
    assert db.get_bool_setting(1, SK_ANTIFLOOD, True) is True


@pytest.mark.asyncio
async def test_toggle_alphabet_via_button(db):
    mod = make_module(db)
    q = FakeQuery(99, "pc:toggle:alphabet")
    await mod.on_panel(make_cbk_update(q), None)
    assert db.get_bool_setting(1, SK_ALPHABET_LATIN, False) is True


@pytest.mark.asyncio
async def test_non_admin_cannot_use_panel(db):
    mod = make_module(db)
    q = FakeQuery(1234, "pc:toggle:antiflood")
    await mod.on_panel(make_cbk_update(q), None)
    # 设置未被改动，且收到拒绝提示
    assert db.get_bool_setting(1, SK_ANTIFLOOD, True) is True
    assert q.answers and q.answers[0][1].get("show_alert") is True


# ── 用户导航按钮：仅在配置了自定义启动按钮时出现 ────────────

def test_user_home_markup_empty_when_no_content(db):
    mod = make_module(db)
    assert mod._user_home_markup() is None


def test_user_home_markup_shows_custom_buttons(db):
    import json

    from modules.customize_module import SK_WELCOME_BTNS
    mod = make_module(db)
    db.set_setting(1, SK_WELCOME_BTNS,
                   json.dumps([[{"text": "频道", "url": "https://t.me/x"}]]))
    cbs = _button_texts(mod._user_home_markup())
    assert "频道" in cbs


# ── 封禁管理面板 ─────────────────────────────────────────────

def test_panel_surfaces_ban_management(db):
    mod = make_module(db)
    cbs = _callbacks(mod._panel_markup())
    assert "pc:bans" in cbs


@pytest.mark.asyncio
async def test_bans_view_empty(db):
    mod = make_module(db)
    q = FakeQuery(99, "pc:bans")
    await mod.on_panel(make_cbk_update(q), None)
    text, kwargs = q.edits[0]
    assert "没有被封禁" in text
    # 仅返回按钮，无解封按钮
    cbs = _callbacks(kwargs["reply_markup"])
    assert cbs == ["pc:home"]


@pytest.mark.asyncio
async def test_bans_view_lists_and_unbans(db):
    mod = make_module(db)
    db.upsert_tenant_user(1, 42, "alice", "Alice")
    db.ban_user(1, 42)
    # 列表中出现解封按钮
    q = FakeQuery(99, "pc:bans")
    await mod.on_panel(make_cbk_update(q), None)
    cbs = _callbacks(q.edits[0][1]["reply_markup"])
    assert "pc:unban:42" in cbs
    # 点击解封按钮后用户被解封
    q2 = FakeQuery(99, "pc:unban:42")
    await mod.on_panel(make_cbk_update(q2), None)
    assert db.is_banned(1, 42) is False
    # 解封后列表为空
    assert "没有被封禁" in q2.edits[0][0]


@pytest.mark.asyncio
async def test_non_admin_cannot_unban(db):
    mod = make_module(db)
    db.upsert_tenant_user(1, 42, "alice", "Alice")
    db.ban_user(1, 42)
    q = FakeQuery(1234, "pc:unban:42")
    await mod.on_panel(make_cbk_update(q), None)
    assert db.is_banned(1, 42) is True


# ── 过滤词管理：面板添加 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_filters_view_lists_keywords_and_actions(db):
    """过滤词列表应在正文展示已添加的词，并提供编辑/删除按钮。"""
    mod = make_module(db)
    fid = db.add_filter(1, "自定义违禁词")
    q = FakeQuery(99, "pc:filters")
    await mod.on_panel(make_cbk_update(q), None)
    text, kwargs = q.edits[0]
    assert "自定义违禁词" in text
    assert "共" in text
    cbs = _callbacks(kwargs["reply_markup"])
    assert "pc:filter_add" in cbs
    assert f"pc:filter_edit:{fid}" in cbs
    assert any(c.startswith(f"pc:filter_del:{fid}") for c in cbs)


@pytest.mark.asyncio
async def test_filters_view_has_add_button(db):
    mod = make_module(db)
    q = FakeQuery(99, "pc:filters")
    await mod.on_panel(make_cbk_update(q), None)
    cbs = _callbacks(q.edits[0][1]["reply_markup"])
    assert "pc:filter_add" in cbs


@pytest.mark.asyncio
async def test_filter_edit_via_panel_wizard(db):
    from telegram.ext import ApplicationHandlerStop

    from modules.private_chat_module import _SK_FILTER_ADD
    from tests.conftest import FakeMessage, make_ctx

    mod = make_module(db)
    fid = db.add_filter(1, "旧词")
    ctx = make_ctx(None)
    ctx.user_data = {}

    q = FakeQuery(99, f"pc:filter_edit:{fid}")
    await mod.on_panel(make_cbk_update(q), ctx)
    assert ctx.user_data.get(_SK_FILTER_ADD, {}).get("edit_id") == fid

    msg = FakeMessage(1, text="新词")
    upd = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=99),
        effective_message=msg,
        message=msg,
    )
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_filter_add_wizard(upd, ctx)
    assert _SK_FILTER_ADD not in ctx.user_data
    row = db.get_filter(1, fid)
    assert row is not None and row["keyword"] == "新词"
    assert any("已更新" in r for r in msg.replies)


@pytest.mark.asyncio
async def test_filter_delete_via_panel_refreshes_list(db):
    mod = make_module(db)
    fid = db.add_filter(1, "待删词")
    q = FakeQuery(99, f"pc:filter_del:{fid}:0")
    await mod.on_panel(make_cbk_update(q), None)
    assert db.get_filter(1, fid) is None
    text = q.edits[0][0]
    assert "待删词" not in text


@pytest.mark.asyncio
async def test_filter_add_via_panel_wizard(db):
    from telegram.ext import ApplicationHandlerStop

    from modules.private_chat_module import _SK_FILTER_ADD
    from tests.conftest import FakeMessage, make_ctx

    mod = make_module(db)
    ctx = make_ctx(None)
    ctx.user_data = {}

    q = FakeQuery(99, "pc:filter_add")
    await mod.on_panel(make_cbk_update(q), ctx)
    assert ctx.user_data.get(_SK_FILTER_ADD)

    msg = FakeMessage(1, text="广告词\nregex:PC\\d+")
    upd = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=99),
        effective_message=msg,
        message=msg,
    )
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_filter_add_wizard(upd, ctx)
    assert _SK_FILTER_ADD not in ctx.user_data
    keywords = {r["keyword"] for r in db.get_filters(1)}
    assert "广告词" in keywords
    assert r"PC\d+" in keywords
    assert any("已添加" in r for r in msg.replies)


@pytest.mark.asyncio
async def test_filter_add_wizard_cancel(db):
    from telegram.ext import ApplicationHandlerStop

    from modules.private_chat_module import _SK_FILTER_ADD
    from tests.conftest import FakeMessage, make_ctx

    mod = make_module(db)
    ctx = make_ctx(None)
    ctx.user_data = {_SK_FILTER_ADD: {"step": "keyword"}}
    msg = FakeMessage(1, text="/cancel")
    upd = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=99),
        effective_message=msg,
        message=msg,
    )
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_filter_add_wizard(upd, ctx)
    assert _SK_FILTER_ADD not in ctx.user_data
    assert any("取消" in r for r in msg.replies)


@pytest.mark.asyncio
async def test_filter_add_wizard_inactive_does_not_stop(db):
    """无会话时向导应直接 return，让其它 group 的处理器继续工作。"""
    from modules.private_chat_module import _SK_FILTER_ADD
    from tests.conftest import FakeMessage, make_ctx

    mod = make_module(db)
    ctx = make_ctx(None)
    ctx.user_data = {}
    msg = FakeMessage(1, text="普通消息")
    upd = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=99),
        effective_message=msg,
        message=msg,
    )
    # 不应抛 ApplicationHandlerStop，也不应写入过滤词
    await mod.on_filter_add_wizard(upd, ctx)
    assert _SK_FILTER_ADD not in ctx.user_data
    assert not any(r["keyword"] == "普通消息" for r in db.get_filters(1))


@pytest.mark.asyncio
async def test_cmd_cancel_clears_filter_add_state(db):
    """ /cancel 应同时清掉控制面板添加过滤词会话。"""
    from modules.customize_module import CustomizeModule
    from modules.private_chat_module import _SK_FILTER_ADD
    from tests.conftest import FakeMessage, make_ctx

    mod = CustomizeModule.__new__(CustomizeModule)
    mod.db = db
    mod.tenant_id = 1
    mod.admin_id = 99
    ctx = make_ctx(None)
    ctx.user_data = {_SK_FILTER_ADD: {"step": "keyword"}}
    msg = FakeMessage(1, text="/cancel")
    upd = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=99),
        effective_message=msg,
        message=msg,
    )
    await mod.cmd_cancel(upd, ctx)
    assert _SK_FILTER_ADD not in ctx.user_data
    assert any("取消" in r for r in msg.replies)


# ── 统计文案 ─────────────────────────────────────────────────

def test_stats_text_empty_and_nonempty(db):
    mod = make_module(db)
    assert "还没有用户" in mod._stats_text()
    db.upsert_tenant_user(1, 42, "a", "Alice")
    text = mod._stats_text()
    assert "总用户" in text
    assert "1" in text
