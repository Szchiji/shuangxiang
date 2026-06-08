"""回归测试：确保各模块的私聊消息处理器不会因 group 冲突而互相抢占。

python-telegram-bot 每个 group 最多只执行一个处理器。若自动回复模块的
``on_message`` 与强制订阅拦截器 ``on_guard`` 处于同一 group，自动回复 /
过滤 / 防刷屏将永远不会被触发（历史 bug：二者都在 group=-1）。
"""

from telegram.ext import MessageHandler

from modules.auto_reply_module import AutoReplyModule
from modules.customize_module import CustomizeModule
from modules.private_chat_module import PrivateChatModule


class FakeApp:
    """记录 add_handler(handler, group) 调用的假 Application。"""

    def __init__(self):
        self.handlers = []  # list[(handler, group)]

    def add_handler(self, handler, group=0):
        self.handlers.append((handler, group))


def _config():
    return {"bot": {"admin_id": 99}, "tenant_id": 1, "messages": {}}


def _group_of(app, callback_name):
    """返回某 MessageHandler（按回调方法名定位）所在的 group。"""
    for handler, group in app.handlers:
        if (isinstance(handler, MessageHandler)
                and getattr(handler.callback, "__name__", "") == callback_name):
            return group
    raise AssertionError(f"未找到回调为 {callback_name} 的 MessageHandler")


def test_autoreply_and_guard_in_distinct_groups(db):
    app = FakeApp()
    # 与 config.yaml 中 tenant_modules 相同的加载顺序
    PrivateChatModule(_config()).setup(app)
    CustomizeModule(_config()).setup(app)
    AutoReplyModule(_config()).setup(app)

    guard_group     = _group_of(app, "on_guard")       # 强制订阅拦截
    autoreply_group = _group_of(app, "on_message")     # 自动回复 / 过滤 / 防刷屏
    forward_group   = _group_of(app, "on_private")     # 双向转发

    # 三者必须分属不同 group，否则每组只会执行一个处理器。
    assert len({guard_group, autoreply_group, forward_group}) == 3, (
        f"处理器 group 必须互不相同，实际："
        f"guard={guard_group} autoreply={autoreply_group} forward={forward_group}")
    # 顺序：强制订阅(先) → 自动回复 → 双向转发(后)
    assert guard_group < autoreply_group < forward_group
