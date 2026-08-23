"""防刷屏与字母表（拉丁）过滤器测试。"""

import types

import pytest
from telegram.ext import ApplicationHandlerStop

from modules.auto_reply_module import (
    SK_ALPHABET_LATIN,
    SK_ANTIFLOOD,
    SK_BLOCK_VIA_BOT,
    SK_FILTER_AUTO_BAN,
    SK_FLOOD_MAX_MSGS,
    SK_FLOOD_WINDOW,
    AutoReplyModule,
    clamp_flood_limit,
)
from tests.conftest import FakeBot, FakeMessage, make_ctx


def make_module(db, admin_id=99):
    mod = AutoReplyModule.__new__(AutoReplyModule)
    mod.db = db
    mod.tenant_id = 1
    mod.admin_id = admin_id
    mod._flood = {}
    mod._flood_last_cleanup = 0.0
    mod._flood_group_cache = {}
    return mod


def make_update(user_id, msg):
    return types.SimpleNamespace(
        message=msg,
        effective_user=types.SimpleNamespace(id=user_id))


def make_ctx_with_args(*args):
    ctx = make_ctx(FakeBot())
    ctx.args = list(args)
    return ctx



def test_antiflood_blocks_after_threshold(db):
    mod = make_module(db)
    t = 100.0
    # 阈值为 5 条/5 秒；第 6 条应被判定为刷屏
    results = [mod._is_flooding(1, now=t + i * 0.1) for i in range(6)]
    assert results[:5] == [False] * 5
    assert results[5] is True


def test_antiflood_window_resets(db):
    mod = make_module(db)
    for i in range(5):
        mod._is_flooding(1, now=100.0 + i * 0.1)
    # 远超窗口后，旧时间戳被清除，不再刷屏
    assert mod._is_flooding(1, now=200.0) is False


@pytest.mark.asyncio
async def test_on_message_antiflood_stop(db):
    mod = make_module(db)
    ctx = make_ctx(FakeBot())
    # 默认开启；连续发送触发拦截
    msg = FakeMessage(1, text="hi")
    upd = make_update(7, msg)
    with pytest.raises(ApplicationHandlerStop):
        for _ in range(6):
            await mod.on_message(upd, ctx)


def test_antiflood_album_counts_as_one_message(db):
    mod = make_module(db)
    t = 100.0
    # 相册（同一 media_group_id）拆成 8 条 Update 逐一到达，
    # 但应作为一条消息计数，不应因条数多而被误判为刷屏。
    results = [mod._is_flooding(1, media_group_id="G1", now=t + i * 0.1)
               for i in range(8)]
    assert results == [False] * 8


@pytest.mark.asyncio
async def test_on_message_album_not_blocked_by_antiflood(db):
    mod = make_module(db)
    ctx = make_ctx(FakeBot())
    # 同一相册的 8 张图片应全部通过，不被防刷屏拦截（不抛出异常）。
    for i in range(8):
        msg = FakeMessage(i, caption=None, media_group_id="G1")
        await mod.on_message(make_update(7, msg), ctx)


def test_clamp_flood_limit_bounds():
    assert clamp_flood_limit(0, 0) == (1, 1)
    assert clamp_flood_limit(999, 999) == (50, 60)
    assert clamp_flood_limit(10, 20) == (10, 20)


def test_custom_flood_limit_applies_to_is_flooding(db):
    mod = make_module(db)
    db.set_setting(1, SK_FLOOD_MAX_MSGS, 3)
    db.set_setting(1, SK_FLOOD_WINDOW, 5)
    t = 100.0
    # 自定义阈值为 3 条/5 秒；第 4 条应被判定为刷屏
    results = [mod._is_flooding(1, now=t + i * 0.1) for i in range(4)]
    assert results == [False, False, False, True]


@pytest.mark.asyncio
async def test_cmd_flood_limit_shows_current_value(db):
    mod = make_module(db)
    ctx = make_ctx_with_args()
    msg = FakeMessage(1)
    await mod.cmd_flood_limit(make_update(99, msg), ctx)
    assert msg.replies and "5" in msg.replies[0]


@pytest.mark.asyncio
async def test_cmd_flood_limit_sets_and_clamps(db):
    mod = make_module(db)
    ctx = make_ctx_with_args("999", "999")
    msg = FakeMessage(1)
    await mod.cmd_flood_limit(make_update(99, msg), ctx)
    assert db.get_int_setting(1, SK_FLOOD_MAX_MSGS, 0) == 50
    assert db.get_int_setting(1, SK_FLOOD_WINDOW, 0) == 60


@pytest.mark.asyncio
async def test_cmd_flood_limit_rejects_invalid_args(db):
    mod = make_module(db)
    ctx = make_ctx_with_args("abc", "5")
    msg = FakeMessage(1)
    await mod.cmd_flood_limit(make_update(99, msg), ctx)
    assert db.get_setting(1, SK_FLOOD_MAX_MSGS) is None
    assert msg.replies


@pytest.mark.asyncio
async def test_cmd_flood_limit_admin_only(db):
    mod = make_module(db)
    ctx = make_ctx_with_args("3", "5")
    msg = FakeMessage(1)
    await mod.cmd_flood_limit(make_update(7, msg), ctx)  # 非管理员
    assert not msg.replies
    assert db.get_setting(1, SK_FLOOD_MAX_MSGS) is None


@pytest.mark.asyncio
async def test_on_message_antiflood_can_be_disabled(db):
    mod = make_module(db)
    db.set_setting(1, SK_ANTIFLOOD, "0")
    ctx = make_ctx(FakeBot())
    # 关闭后即使大量消息也不应抛出刷屏拦截
    for i in range(20):
        await mod.on_message(make_update(7, FakeMessage(i, text="你好")), ctx)


@pytest.mark.asyncio
async def test_alphabet_latin_blocks_when_enabled(db):
    mod = make_module(db)
    db.set_setting(1, SK_ANTIFLOOD, "0")
    db.set_setting(1, SK_ALPHABET_LATIN, "1")
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="hello world")
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_message(make_update(7, msg), ctx)
    assert msg.replies, "应提示用户被拦截"


@pytest.mark.asyncio
async def test_alphabet_latin_allows_non_latin(db):
    mod = make_module(db)
    db.set_setting(1, SK_ANTIFLOOD, "0")
    db.set_setting(1, SK_ALPHABET_LATIN, "1")
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="你好，世界")
    # 不含拉丁字母 → 不拦截
    await mod.on_message(make_update(7, msg), ctx)
    assert not msg.replies


@pytest.mark.asyncio
async def test_alphabet_latin_off_by_default(db):
    mod = make_module(db)
    db.set_setting(1, SK_ANTIFLOOD, "0")
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="hello")
    # 默认关闭 → 英文消息放行
    await mod.on_message(make_update(7, msg), ctx)
    assert not msg.replies


# ── 自动回复匹配（包含 / 正则）───────────────────────────────

@pytest.mark.asyncio
async def test_auto_reply_contains_match(db):
    mod = make_module(db)
    db.add_auto_reply(1, "价格", "见官网")  # 默认 contains
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="请问价格多少")
    # 命中自动回复后应拦截：不再转发关键词消息给管理员。
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_message(make_update(7, msg), ctx)
    assert msg.replies and msg.replies[0] == "见官网"


@pytest.mark.asyncio
async def test_auto_reply_regex_match(db):
    mod = make_module(db)
    db.add_auto_reply(1, r"价格|报价", "见官网", "regex", 0)
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="报价")  # 整条消息完全匹配该正则
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_message(make_update(7, msg), ctx)
    assert msg.replies and msg.replies[0] == "见官网"


@pytest.mark.asyncio
async def test_auto_reply_regex_requires_full_match(db):
    """正则模式下，仅*包含*关键词的消息不应命中（整条消息需完全匹配）。"""
    mod = make_module(db)
    db.add_auto_reply(1, r"价格|报价", "见官网", "regex", 0)
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="请问报价多少")  # 仅包含，非完全匹配
    await mod.on_message(make_update(7, msg), ctx)
    assert not msg.replies


@pytest.mark.asyncio
async def test_auto_reply_regex_no_false_match(db):
    mod = make_module(db)
    db.add_auto_reply(1, r"^价格$", "见官网", "regex", 0)
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="请问价格多少")  # 非完全匹配
    await mod.on_message(make_update(7, msg), ctx)
    assert not msg.replies


@pytest.mark.asyncio
async def test_auto_reply_invalid_regex_does_not_crash(db):
    mod = make_module(db)
    db.add_auto_reply(1, "(", "x", "regex", 0)  # 非法正则
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="任意内容")
    await mod.on_message(make_update(7, msg), ctx)
    assert not msg.replies


@pytest.mark.asyncio
async def test_auto_reply_sends_media_when_configured(db):
    mod = make_module(db)
    db.add_auto_reply(1, "图", "看图", "contains", 0, "", "photo", "PIC1")
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="发个图")
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_message(make_update(7, msg), ctx)
    # 命中后以媒体形式回复（图说为回复文本），不走纯文本路径
    assert not msg.replies
    assert msg.media_replies and msg.media_replies[0][0] == "photo"
    assert msg.media_replies[0][1] == "PIC1"
    assert msg.media_replies[0][2]["caption"] == "看图"


# ── 过滤词：正则匹配 / 自动封禁 / 第三方机器人拦截 ─────────────

@pytest.mark.asyncio
async def test_filter_regex_match_blocks_message(db):
    mod = make_module(db)
    db.add_filter(1, r"PC\d+", "regex")
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="注册就送 PC28 大礼包")
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_message(make_update(7, msg), ctx)
    assert msg.replies


@pytest.mark.asyncio
async def test_filter_regex_invalid_does_not_crash(db):
    mod = make_module(db)
    db.add_filter(1, "(", "regex")  # 非法正则
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="任意内容")
    await mod.on_message(make_update(7, msg), ctx)
    assert not msg.replies


@pytest.mark.asyncio
async def test_filter_contains_case_insensitive(db):
    mod = make_module(db)
    db.add_filter(1, "casino")
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="欢迎来到 CASINO 娱乐城")
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_message(make_update(7, msg), ctx)


@pytest.mark.asyncio
async def test_filter_auto_ban_off_by_default(db):
    mod = make_module(db)
    db.add_filter(1, "违禁词")
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="包含违禁词的消息")
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_message(make_update(7, msg), ctx)
    assert db.is_banned(1, 7) is False


@pytest.mark.asyncio
async def test_filter_auto_ban_when_enabled(db):
    mod = make_module(db)
    db.add_filter(1, "违禁词")
    db.set_setting(1, SK_FILTER_AUTO_BAN, "1")
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="包含违禁词的消息")
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_message(make_update(7, msg), ctx)
    assert db.is_banned(1, 7) is True


@pytest.mark.asyncio
async def test_filter_auto_ban_also_bans_via_bot(db):
    mod = make_module(db)
    db.add_filter(1, "违禁词")
    db.set_setting(1, SK_FILTER_AUTO_BAN, "1")
    ctx = make_ctx(FakeBot())
    via_bot = types.SimpleNamespace(id=555, username="PostBot")
    msg = FakeMessage(1, text="包含违禁词的消息", via_bot=via_bot)
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_message(make_update(7, msg), ctx)
    assert db.is_banned(1, 7) is True
    assert db.is_bot_banned(1, 555) is True


@pytest.mark.asyncio
async def test_block_via_bot_off_by_default(db):
    mod = make_module(db)
    ctx = make_ctx(FakeBot())
    via_bot = types.SimpleNamespace(id=555, username="PostBot")
    msg = FakeMessage(1, text="正常消息", via_bot=via_bot)
    # 默认关闭 → 不拦截，正常继续走后续流程（不抛异常）。
    await mod.on_message(make_update(7, msg), ctx)
    assert not msg.replies


@pytest.mark.asyncio
async def test_block_via_bot_when_enabled(db):
    mod = make_module(db)
    db.set_setting(1, SK_BLOCK_VIA_BOT, "1")
    ctx = make_ctx(FakeBot())
    via_bot = types.SimpleNamespace(id=555, username="PostBot")
    msg = FakeMessage(1, text="正常消息", via_bot=via_bot)
    with pytest.raises(ApplicationHandlerStop):
        await mod.on_message(make_update(7, msg), ctx)
    # 静默拦截，不提示用户，避免其得知被拦截。
    assert not msg.replies


@pytest.mark.asyncio
async def test_block_via_bot_does_not_affect_direct_messages(db):
    mod = make_module(db)
    db.set_setting(1, SK_BLOCK_VIA_BOT, "1")
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(1, text="正常消息")  # 非经由第三方机器人
    await mod.on_message(make_update(7, msg), ctx)
    assert not msg.replies


@pytest.mark.asyncio
async def test_cmd_filter_auto_ban_toggle(db):
    mod = make_module(db)
    ctx = make_ctx_with_args("on")
    msg = FakeMessage(1)
    await mod.cmd_filter_auto_ban(make_update(99, msg), ctx)
    assert db.get_bool_setting(1, SK_FILTER_AUTO_BAN, False) is True


@pytest.mark.asyncio
async def test_cmd_block_via_bot_toggle(db):
    mod = make_module(db)
    ctx = make_ctx_with_args("on")
    msg = FakeMessage(1)
    await mod.cmd_block_via_bot(make_update(99, msg), ctx)
    assert db.get_bool_setting(1, SK_BLOCK_VIA_BOT, False) is True


@pytest.mark.asyncio
async def test_filter_add_regex_command(db):
    mod = make_module(db)
    ctx = make_ctx_with_args()
    msg = FakeMessage(1, text="/filter_add regex:PC\\d+")
    await mod.filter_add(make_update(99, msg), ctx)
    rows = db.get_filters(1)
    assert rows and rows[0]["match_type"] == "regex" and rows[0]["keyword"] == "PC\\d+"


@pytest.mark.asyncio
async def test_filter_add_rejects_invalid_regex(db):
    mod = make_module(db)
    ctx = make_ctx_with_args()
    msg = FakeMessage(1, text="/filter_add regex:(")
    await mod.filter_add(make_update(99, msg), ctx)
    assert not db.get_filters(1)
    assert msg.replies
