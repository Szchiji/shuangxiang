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


# ── 用户导航按钮：仅在有内容时出现 ──────────────────────────

def test_user_home_markup_empty_when_no_content(db):
    mod = make_module(db)
    assert mod._user_home_markup() is None


def test_user_home_markup_shows_available_features(db):
    mod = make_module(db)
    db.add_menu_item(1, 0, "关于我们", "简介")
    db.add_form(1, "报名")
    db.add_category(1, "会员")
    cbs = _callbacks(mod._user_home_markup())
    assert "menu:0" in cbs
    assert "pc:forms" in cbs
    assert "shop:cats" in cbs


# ── 用户「填写表单」按钮：非拥有者也可用 ────────────────────

@pytest.mark.asyncio
async def test_forms_callback_public_for_users(db):
    mod = make_module(db)
    db.add_form(1, "报名")
    q = FakeQuery(1234, "pc:forms")  # 普通用户
    await mod.on_panel(make_cbk_update(q), None)
    assert q.edits  # 正常渲染表单列表，未被拒绝
    text, kwargs = q.edits[0]
    cbs = _callbacks(kwargs["reply_markup"])
    assert any(c.startswith("form:") for c in cbs)


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


# ── 统计文案 ─────────────────────────────────────────────────

def test_stats_text_empty_and_nonempty(db):
    mod = make_module(db)
    assert "还没有用户" in mod._stats_text()
    db.upsert_tenant_user(1, 42, "a", "Alice")
    assert "总用户：1" in mod._stats_text()


# ── 内容功能进入控制面板（菜单 / 表单 / 商店）────────────────

def test_panel_surfaces_content_features(db):
    mod = make_module(db)
    cbs = _callbacks(mod._panel_markup())
    assert "pc:menu" in cbs    # 📋 菜单
    assert "pc:form" in cbs    # 📝 表单
    assert "pc:store" in cbs   # 🛒 商店


@pytest.mark.asyncio
async def test_panel_content_views_render(db):
    mod = make_module(db)
    db.add_menu_item(1, 0, "关于我们", "简介")
    db.add_form(1, "报名")
    cid = db.add_category(1, "会员")
    db.add_product(1, cid, "月卡", "", 9.9)
    cases = [
        ("pc:menu", "菜单管理", "关于我们"),
        ("pc:form", "表单管理", "报名"),
        ("pc:store", "商店管理", "月卡"),
    ]
    for action, title, item in cases:
        q = FakeQuery(99, action)
        await mod.on_panel(make_cbk_update(q), None)
        text = q.edits[0][0]
        assert title in text and item in text
        # 提供返回面板按钮
        assert "pc:home" in _callbacks(q.edits[0][1]["reply_markup"])


@pytest.mark.asyncio
async def test_panel_content_views_admin_only(db):
    mod = make_module(db)
    q = FakeQuery(1234, "pc:menu")
    await mod.on_panel(make_cbk_update(q), None)
    assert not q.edits
    assert q.answers and q.answers[0][1].get("show_alert") is True
