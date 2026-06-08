"""双向私聊中转测试：相册聚合、话题去重、话题模式回复提示。"""

import asyncio
import types

import pytest

from modules.private_chat_module import PrivateChatModule
from tests.conftest import FakeBot, FakeMessage, make_ctx


def make_module(db, manage_group=None, admin_id=99):
    mod = PrivateChatModule.__new__(PrivateChatModule)
    mod.db = db
    mod.tenant_id = 1
    mod.admin_id = admin_id
    mod.received = ""
    mod.sent_ack = "✅ 已发送成功，管理员会尽快回复你。"
    mod._ack_delete_delay = 0
    mod._albums = {}
    mod._album_delay = 0.05
    mod._topic_locks = {}
    mod._manage_group = lambda: manage_group
    return mod


USER = types.SimpleNamespace(id=42, full_name="Alice", username="a")


@pytest.mark.asyncio
async def test_user_album_to_dm_single_album(db):
    mod = make_module(db, manage_group=None)
    ctx = make_ctx(FakeBot())
    for i in range(3):
        mod._buffer_album(ctx, USER, FakeMessage(10 + i, media_group_id="G1"))
    await asyncio.sleep(0.2)
    cm = ctx.bot.of("copy_messages")
    assert len(cm) == 1
    assert cm[0]["message_ids"] == [10, 11, 12]
    # 一条 DM 头部
    assert len(ctx.bot.of("send_message")) == 1


@pytest.mark.asyncio
async def test_album_topics_no_duplicate_topic(db):
    mod = make_module(db, manage_group=-100)
    ctx = make_ctx(FakeBot())
    for i in range(3):
        mod._buffer_album(ctx, USER, FakeMessage(20 + i, media_group_id="G2"))
    # 相册 flush 与普通消息并发，争用话题创建
    await asyncio.gather(
        mod._flush_album_later(ctx, "G2"),
        mod._forward_to_topic(ctx, -100, USER, FakeMessage(30)),
    )
    assert len(ctx.bot.of("create_forum_topic")) == 1
    assert db.get_user_topic(1, USER.id) is not None


@pytest.mark.asyncio
async def test_admin_album_to_user(db):
    mod = make_module(db, manage_group=-100)
    mod._ack = staticmethod(lambda m: asyncio.sleep(0))
    ctx = make_ctx(FakeBot())
    for i in range(2):
        mod._buffer_admin_album(ctx, 42, FakeMessage(40 + i, media_group_id="G3"))
    await asyncio.sleep(0.2)
    cm = ctx.bot.of("copy_messages")
    assert len(cm) == 1
    assert cm[0]["chat_id"] == 42
    assert cm[0]["message_ids"] == [40, 41]


@pytest.mark.asyncio
async def test_topic_reply_hint_sent(db):
    mod = make_module(db, manage_group=-100)
    ctx = make_ctx(FakeBot())
    replied = FakeMessage(5, text="这是用户回复的原消息内容")
    msg = FakeMessage(50, text="我的回复", reply_to_message=replied)
    await mod._forward_to_topic(ctx, -100, USER, msg)
    hints = [c for c in ctx.bot.of("send_message")
             if "用户回复了" in c.get("text", "")]
    assert len(hints) == 1
    assert "原消息内容" in hints[0]["text"]


@pytest.mark.asyncio
async def test_no_reply_hint_when_not_reply(db):
    mod = make_module(db, manage_group=-100)
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(51, text="普通消息")
    await mod._forward_to_topic(ctx, -100, USER, msg)
    hints = [c for c in ctx.bot.of("send_message")
             if "用户回复了" in c.get("text", "")]
    assert hints == []


def test_reply_snippet_truncates(db):
    mod = make_module(db)
    long = "x" * 200
    msg = FakeMessage(2, text="reply", reply_to_message=FakeMessage(1, text=long))
    snippet = mod._reply_snippet(msg)
    assert snippet is not None and len(snippet) <= 80 and snippet.endswith("…")


@pytest.mark.asyncio
async def test_incoming_user_acks_and_autodeletes(db):
    mod = make_module(db, manage_group=None)
    ctx = make_ctx(FakeBot())
    msg = FakeMessage(60, text="你好")
    update = types.SimpleNamespace(message=msg, effective_user=USER)
    await mod._incoming_user(update, ctx)
    # 用户收到「已发送成功」轻提示
    assert any("已发送成功" in r for r in msg.replies)
    # 提示在延时（测试中为 0）后被自动删除
    await asyncio.sleep(0.05)
    assert ctx.bot.of("delete_message"), "应安排删除已送达提示"
