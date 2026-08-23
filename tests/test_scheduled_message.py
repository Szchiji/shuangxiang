"""定时消息模块（modules/scheduled_message_module.py）单元测试。"""

import types

import pytest

from modules.scheduled_message_module import ScheduledMessageModule, build_markup


class _FakeBot:
    def __init__(self):
        self.sent = []
        self.deleted = []
        self._mid = 100

    async def send_message(self, **kw):
        self.sent.append(("text", kw))
        self._mid += 1
        return types.SimpleNamespace(message_id=self._mid)

    async def send_photo(self, **kw):
        self.sent.append(("photo", kw))
        self._mid += 1
        return types.SimpleNamespace(message_id=self._mid)

    async def delete_message(self, **kw):
        self.deleted.append(kw)


def _make_module(config):
    mod = ScheduledMessageModule(config)
    mod.tenant_id = config.get("tenant_id")
    return mod


def test_build_markup_empty():
    assert build_markup("") is None
    assert build_markup("not-json") is None


def test_build_markup_valid():
    markup = build_markup('[[{"text": "官网", "url": "https://example.com"}]]')
    assert markup is not None
    assert markup.inline_keyboard[0][0].text == "官网"


@pytest.mark.asyncio
async def test_tick_sends_due_text_message_and_reschedules(db):
    tenant_id = db.add_tenant(
        token="test_token:XYZ", owner_user_id=1, bot_id=1,
        bot_username="testbot", bot_name="Test Bot")
    sid = db.add_scheduled_message(
        tenant_id, target_type="group", target_chat_id=-100123,
        content="hello", interval_minutes=15, repeat=1)

    mod = _make_module({"tenant_id": tenant_id})
    mod.db = db
    bot = _FakeBot()
    app = types.SimpleNamespace(bot=bot)

    await mod._tick(app)

    assert len(bot.sent) == 1
    kind, kw = bot.sent[0]
    assert kind == "text"
    assert kw["chat_id"] == "-100123"
    assert kw["text"] == "hello"

    row = db.get_scheduled_message(tenant_id, sid)
    assert row["enabled"] == 1
    assert row["last_message_id"] == 101
    assert row["next_run_at"] is not None

    # Not due again immediately since next_run_at is in the future.
    bot.sent.clear()
    await mod._tick(app)
    assert bot.sent == []


@pytest.mark.asyncio
async def test_tick_disables_once_only_message_after_send(db):
    tenant_id = db.add_tenant(
        token="test_token2:XYZ", owner_user_id=2, bot_id=2,
        bot_username="testbot2", bot_name="Test Bot 2")
    sid = db.add_scheduled_message(
        tenant_id, target_type="channel", target_chat_id="@mychannel",
        content="once", interval_minutes=10, repeat=0)

    mod = _make_module({"tenant_id": tenant_id})
    mod.db = db
    bot = _FakeBot()
    app = types.SimpleNamespace(bot=bot)

    await mod._tick(app)

    assert len(bot.sent) == 1
    row = db.get_scheduled_message(tenant_id, sid)
    assert row["enabled"] == 0
    assert row["next_run_at"] is None


@pytest.mark.asyncio
async def test_tick_deletes_previous_message_when_configured(db):
    tenant_id = db.add_tenant(
        token="test_token3:XYZ", owner_user_id=3, bot_id=3,
        bot_username="testbot3", bot_name="Test Bot 3")
    sid = db.add_scheduled_message(
        tenant_id, target_type="group", target_chat_id=-1,
        content="msg", interval_minutes=10, repeat=1, delete_previous=1)
    db.mark_scheduled_message_sent(tenant_id, sid, message_id=555, next_run_at=None)

    mod = _make_module({"tenant_id": tenant_id})
    mod.db = db
    bot = _FakeBot()
    app = types.SimpleNamespace(bot=bot)

    await mod._tick(app)

    assert bot.deleted == [{"chat_id": "-1", "message_id": 555}]
    assert len(bot.sent) == 1
