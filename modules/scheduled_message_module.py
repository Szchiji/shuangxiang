"""定时消息模块：定时发送消息到群组或频道。

支持：
  • 一次性 / 重复发送（按分钟间隔）；
  • 发送前自动删除上一条已发送的消息（``delete_previous``）；
  • 文本 / 图片 / 视频 / 文件，均可附带内联按钮。

后台每个租户机器人各自运行一个轻量轮询循环（默认 30 秒一次），
从数据库读取到期的定时消息并调用 Bot API 发送，随后据 ``repeat``
计算下一次 ``next_run_at`` 或（一次性任务）自动禁用。
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application

from core.base_module import BaseModule
from core.database import Database
from modules.customize_module import rows_to_keyboard

logger = logging.getLogger("shuangxiang.scheduled_message")

# 到期检查的轮询间隔（秒）。定时消息以“分钟”为最小粒度，无需更频繁地检查。
_POLL_INTERVAL = 30
# 首次检查前的延迟，确保 Application 已完成 initialize()/start()。
_STARTUP_DELAY = 5


def build_markup(buttons_raw: str) -> InlineKeyboardMarkup | None:
    """把存储的按钮 JSON 转换为 InlineKeyboardMarkup（无按钮时返回 None）。"""
    if not buttons_raw:
        return None
    try:
        rows = json.loads(buttons_raw)
    except (TypeError, ValueError):
        return None
    keyboard = rows_to_keyboard(rows)
    return InlineKeyboardMarkup(keyboard) if keyboard else None


class ScheduledMessageModule(BaseModule):

    def setup(self, app: Application) -> None:
        self.db = Database()
        self.tenant_id = self.config.get("tenant_id")
        if self.tenant_id is None:
            logger.warning("缺少 tenant_id，定时消息模块未启动")
            return
        app.create_task(
            self._loop(app), name=f"scheduled-message-loop-{self.tenant_id}")

    async def _loop(self, app: Application) -> None:
        await asyncio.sleep(_STARTUP_DELAY)
        while True:
            try:
                await self._tick(app)
            except Exception:
                logger.exception("[租户#%s] 定时消息轮询异常", self.tenant_id)
            await asyncio.sleep(_POLL_INTERVAL)

    async def _tick(self, app: Application) -> None:
        due = self.db.get_due_scheduled_messages(self.tenant_id)
        for row in due:
            await self._send_one(app, row)

    async def _send_one(self, app: Application, row) -> None:
        chat_id = row["target_chat_id"]
        if row["delete_previous"] and row["last_message_id"]:
            try:
                await app.bot.delete_message(
                    chat_id=chat_id, message_id=row["last_message_id"])
            except TelegramError as e:
                logger.info(
                    "[租户#%s] 删除上一条定时消息(#%s)失败: %s",
                    self.tenant_id, row["id"], e)

        markup = build_markup(row["buttons"])
        sent = None
        try:
            sent = await self._dispatch(app, chat_id, row, markup)
        except TelegramError as e:
            logger.warning(
                "[租户#%s] 发送定时消息(#%s)失败: %s", self.tenant_id, row["id"], e)

        with_repeat = bool(row["repeat"])
        self.db.mark_scheduled_message_sent(
            self.tenant_id, row["id"],
            message_id=sent.message_id if sent else row["last_message_id"],
            next_run_at=self._compute_next_run(row) if with_repeat else None,
            disable_if_once=not with_repeat,
        )

    @staticmethod
    def _compute_next_run(row) -> str:
        """按 ``interval_minutes`` 计算下一次发送时间（UTC，与 SQLite ``datetime('now')`` 对齐）。"""
        interval = max(1, int(row["interval_minutes"] or 60))
        next_dt = datetime.now(timezone.utc) + timedelta(minutes=interval)
        return next_dt.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    async def _dispatch(app: Application, chat_id, row, markup):
        msg_type = row["msg_type"] or "text"
        content = row["content"] or ""
        media_id = row["media_id"] or ""
        if msg_type == "photo" and media_id:
            return await app.bot.send_photo(
                chat_id=chat_id, photo=media_id,
                caption=content or None, reply_markup=markup)
        if msg_type == "video" and media_id:
            return await app.bot.send_video(
                chat_id=chat_id, video=media_id,
                caption=content or None, reply_markup=markup)
        if msg_type == "document" and media_id:
            return await app.bot.send_document(
                chat_id=chat_id, document=media_id,
                caption=content or None, reply_markup=markup)
        return await app.bot.send_message(
            chat_id=chat_id, text=content, reply_markup=markup)
