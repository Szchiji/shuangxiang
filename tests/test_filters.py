"""防刷屏与字母表（拉丁）过滤器测试。"""

import pytest
from telegram.ext import ApplicationHandlerStop

from modules.auto_reply_module import SK_ALPHABET_LATIN, SK_ANTIFLOOD, AutoReplyModule
from tests.conftest import FakeBot, FakeMessage, make_ctx


def make_module(db, admin_id=99):
    mod = AutoReplyModule.__new__(AutoReplyModule)
    mod.db = db
    mod.tenant_id = 1
    mod.admin_id = admin_id
    mod._flood = {}
    return mod


def make_update(user_id, msg):
    import types
    return types.SimpleNamespace(
        message=msg,
        effective_user=types.SimpleNamespace(id=user_id))


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
