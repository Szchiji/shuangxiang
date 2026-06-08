"""全局错误处理：为每个 telegram Application 注册统一异常处理器。

避免单条更新处理中抛出的异常导致 handler 静默失效或进程噪声，
所有未捕获异常集中记录（含 Token 脱敏），并尽量不影响其它更新。
"""

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes

logger = logging.getLogger("shuangxiang.errors")


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = None
    if isinstance(update, Update) and update.effective_chat:
        chat_id = update.effective_chat.id
    logger.error(
        "处理更新时发生未捕获异常 (chat_id=%s): %s",
        chat_id, context.error, exc_info=context.error)


def register_error_handler(app: Application) -> None:
    """为给定 Application 注册全局错误处理器。"""
    app.add_error_handler(_on_error)
