"""共享测试夹具：内存数据库与假 Bot / 消息对象。"""

import types

import pytest

from core.database import Database


@pytest.fixture
def db(tmp_path):
    """每个测试使用独立的临时 SQLite 文件，并重置 Database 单例。"""
    Database._instance = None
    database = Database(db_path=str(tmp_path / "test.db"))
    yield database
    Database._instance = None


class FakeMsgId:
    def __init__(self, mid):
        self.message_id = mid


class FakeBot:
    """记录调用的假 Bot，覆盖中转所需的方法。"""

    def __init__(self):
        self.calls = []
        self._mid = 1000
        self._topic_id = 500

    async def send_message(self, **k):
        self.calls.append(("send_message", k))
        self._mid += 1
        return FakeMsgId(self._mid)

    async def copy_message(self, **k):
        self.calls.append(("copy_message", k))
        self._mid += 1
        return FakeMsgId(self._mid)

    async def forward_message(self, **k):
        self.calls.append(("forward_message", k))
        self._mid += 1
        return FakeMsgId(self._mid)

    async def delete_message(self, **k):
        self.calls.append(("delete_message", k))
        return True

    async def copy_messages(self, **k):
        self.calls.append(("copy_messages", k))
        return [FakeMsgId(self._mid + i) for i, _ in enumerate(k["message_ids"])]

    async def forward_messages(self, **k):
        self.calls.append(("forward_messages", k))
        return [FakeMsgId(self._mid + i) for i, _ in enumerate(k["message_ids"])]

    async def create_forum_topic(self, **k):
        self.calls.append(("create_forum_topic", k))
        self._topic_id += 1
        return types.SimpleNamespace(message_thread_id=self._topic_id)

    def kinds(self):
        return [c[0] for c in self.calls]

    def of(self, kind):
        return [c[1] for c in self.calls if c[0] == kind]


class FakeMessage:
    def __init__(self, message_id, text=None, caption=None, media_group_id=None,
                 chat_id=7, reply_to_message=None, forward_origin=None):
        self.message_id = message_id
        self.text = text
        self.caption = caption
        self.media_group_id = media_group_id
        self.chat_id = chat_id
        self.reply_to_message = reply_to_message
        self.forward_origin = forward_origin
        self.replies = []
        self.media_replies = []

    async def reply_text(self, *a, **k):
        self.replies.append(a[0] if a else "")
        return types.SimpleNamespace(
            message_id=self.message_id + 10000, chat_id=self.chat_id)

    async def reply_photo(self, file_id, **k):
        self.media_replies.append(("photo", file_id, k))
        return types.SimpleNamespace(
            message_id=self.message_id + 10000, chat_id=self.chat_id)

    async def reply_video(self, file_id, **k):
        self.media_replies.append(("video", file_id, k))
        return types.SimpleNamespace(
            message_id=self.message_id + 10000, chat_id=self.chat_id)

    async def set_reaction(self, *a, **k):
        pass


def make_ctx(bot):
    return types.SimpleNamespace(bot=bot)
