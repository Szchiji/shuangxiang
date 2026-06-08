"""自动回复 + 关键词过滤（每个租户机器人各运行一份）。

拥有者可配置：
  • 自动回复：命中关键词时机器人自动回复，可选「拦截」（不再转发给管理员）。
  • 关键词过滤：用户消息含违禁词时拦截并提示。
  • 防刷屏过滤器：限制单用户短时间内的消息频率（默认开启，可关闭）。
  • 字母表过滤器：可屏蔽包含特定文字（如拉丁字母 / 英文）的消息（默认关闭）。

该模块的消息处理器注册在 group=-1，先于双向中转(group=5)执行，
命中拦截时通过 ApplicationHandlerStop 阻止后续转发。
"""

import logging
import re
import time

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.base_module import BaseModule
from core.database import Database

logger = logging.getLogger("shuangxiang.auto_reply")

# 设置键
SK_ANTIFLOOD      = "antiflood"        # 防刷屏开关，默认开启
SK_ALPHABET_LATIN = "alphabet_latin"   # 屏蔽拉丁字母，默认关闭

# 防刷屏阈值：窗口内消息条数上限
_FLOOD_WINDOW   = 5.0   # 秒
_FLOOD_MAX_MSGS = 5     # 窗口内最多消息数

# 拉丁字母（英语等使用的基本/扩展拉丁字母）
_LATIN_RE = re.compile(r"[A-Za-z\u00C0-\u024F]")


class AutoReplyModule(BaseModule):

    def setup(self, app: Application) -> None:
        self.db        = Database()
        self.tenant_id = int(self.config.get("tenant_id", 0))
        self.admin_id  = int(self.config["bot"]["admin_id"])
        # 防刷屏：内存中按用户记录最近消息时间戳
        self._flood: dict[int, list[float]] = {}

        app.add_handler(CommandHandler("ar_add", self.ar_add))
        app.add_handler(CommandHandler("ar_list", self.ar_list))
        app.add_handler(CommandHandler("ar_del", self.ar_del))
        app.add_handler(CommandHandler("filter_add", self.filter_add))
        app.add_handler(CommandHandler("filter_list", self.filter_list))
        app.add_handler(CommandHandler("filter_del", self.filter_del))
        app.add_handler(CommandHandler("antiflood", self.cmd_antiflood))
        app.add_handler(CommandHandler("alphabet_latin", self.cmd_alphabet_latin))

        # 先于转发执行
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND, self.on_message), group=-1)

    def _admin(self, update: Update) -> bool:
        return update.effective_user.id == self.admin_id

    # ── 拥有者配置 ──────────────────────────────────────────

    async def ar_add(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        raw = update.message.text.partition(" ")[2]
        if "|" not in raw:
            await update.message.reply_text(
                "用法：/ar_add 关键词 | 回复内容\n（在回复内容前加 ! 表示命中后不再转发，例如：/ar_add 价格 | !见官网）")
            return
        keyword, reply = (p.strip() for p in raw.split("|", 1))
        stop = 0
        if reply.startswith("!"):
            stop, reply = 1, reply[1:].strip()
        if not keyword or not reply:
            await update.message.reply_text("⚠️ 关键词和回复都不能为空。")
            return
        rid = self.db.add_auto_reply(self.tenant_id, keyword, reply, "contains", stop)
        await update.message.reply_text(
            f"✅ 已添加自动回复 #{rid}：「{keyword}」{'（拦截）' if stop else ''}")

    async def ar_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        rows = self.db.get_auto_replies(self.tenant_id)
        if not rows:
            await update.message.reply_text("暂无自动回复。用 /ar_add 添加。")
            return
        lines = [f"#{r['id']} 「{r['keyword']}」→ {r['reply']}"
                 f"{' [拦截]' if r['stop'] else ''}" for r in rows]
        await update.message.reply_text("📝 自动回复：\n" + "\n".join(lines))

    async def ar_del(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        if not ctx.args or not ctx.args[0].isdigit():
            await update.message.reply_text("用法：/ar_del <编号>")
            return
        self.db.delete_auto_reply(self.tenant_id, int(ctx.args[0]))
        await update.message.reply_text("✅ 已删除。")

    async def filter_add(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        word = update.message.text.partition(" ")[2].strip()
        if not word:
            await update.message.reply_text("用法：/filter_add <违禁词>")
            return
        fid = self.db.add_filter(self.tenant_id, word)
        await update.message.reply_text(f"✅ 已添加过滤词 #{fid}：{word}")

    async def filter_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        rows = self.db.get_filters(self.tenant_id)
        if not rows:
            await update.message.reply_text("暂无过滤词。用 /filter_add 添加。")
            return
        await update.message.reply_text(
            "🚫 过滤词：\n" + "\n".join(f"#{r['id']} {r['keyword']}" for r in rows))

    async def filter_del(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        if not ctx.args or not ctx.args[0].isdigit():
            await update.message.reply_text("用法：/filter_del <编号>")
            return
        self.db.delete_filter(self.tenant_id, int(ctx.args[0]))
        await update.message.reply_text("✅ 已删除。")

    # ── 防刷屏 / 字母表 开关 ────────────────────────────────

    async def cmd_antiflood(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        arg = (ctx.args[0].lower() if ctx.args else "")
        if arg in ("on", "off"):
            self.db.set_setting(self.tenant_id, SK_ANTIFLOOD, "1" if arg == "on" else "0")
            await update.message.reply_text(
                f"✅ 防刷屏过滤器已{'开启' if arg == 'on' else '关闭'}。")
            return
        cur = self.db.get_bool_setting(self.tenant_id, SK_ANTIFLOOD, True)
        await update.message.reply_text(
            f"防刷屏过滤器当前：{'开启' if cur else '关闭'}。\n用法：/antiflood on｜off")

    async def cmd_alphabet_latin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        arg = (ctx.args[0].lower() if ctx.args else "")
        if arg in ("on", "off"):
            self.db.set_setting(self.tenant_id, SK_ALPHABET_LATIN,
                                "1" if arg == "on" else "0")
            await update.message.reply_text(
                f"✅ 拉丁字母（英文）屏蔽已{'开启' if arg == 'on' else '关闭'}。")
            return
        cur = self.db.get_bool_setting(self.tenant_id, SK_ALPHABET_LATIN, False)
        await update.message.reply_text(
            f"拉丁字母屏蔽当前：{'开启' if cur else '关闭'}。\n用法：/alphabet_latin on｜off")

    # ── 防刷屏检测 ──────────────────────────────────────────

    def _is_flooding(self, user_id: int, now: float | None = None) -> bool:
        """记录一次消息，并判断是否超过窗口内的频率阈值。"""
        now = time.monotonic() if now is None else now
        bucket = [t for t in self._flood.get(user_id, []) if now - t < _FLOOD_WINDOW]
        bucket.append(now)
        self._flood[user_id] = bucket
        return len(bucket) > _FLOOD_MAX_MSGS

    # ── 用户消息拦截 ────────────────────────────────────────

    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if msg is None or self._admin(update):
            return

        # 0) 防刷屏（默认开启，可关闭）
        if self.db.get_bool_setting(self.tenant_id, SK_ANTIFLOOD, True):
            if self._is_flooding(update.effective_user.id):
                raise ApplicationHandlerStop

        text = msg.text or msg.caption or ""
        if not text:
            return

        # 1) 字母表过滤：屏蔽含拉丁字母（英文等）的消息（默认关闭）
        if self.db.get_bool_setting(self.tenant_id, SK_ALPHABET_LATIN, False):
            if _LATIN_RE.search(text):
                await msg.reply_text("⚠️ 不支持包含英文/拉丁字母的消息。")
                raise ApplicationHandlerStop

        # 2) 过滤违禁词 → 拦截
        for f in self.db.get_filters(self.tenant_id):
            if f["keyword"] in text:
                await msg.reply_text("⚠️ 您的消息包含不被允许的内容，未发送。")
                raise ApplicationHandlerStop

        # 3) 自动回复
        for r in self.db.get_auto_replies(self.tenant_id):
            if r["keyword"] in text:
                await msg.reply_text(r["reply"])
                if r["stop"]:
                    raise ApplicationHandlerStop
                return
