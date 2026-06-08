"""自动回复 + 关键词过滤（每个租户机器人各运行一份）。

拥有者可配置：
  • 自动回复：命中关键词时机器人自动回复，可选「拦截」（不再转发给管理员）。
  • 关键词过滤：用户消息含违禁词时拦截并提示。

该模块的消息处理器注册在 group=-1，先于双向中转(group=5)执行，
命中拦截时通过 ApplicationHandlerStop 阻止后续转发。
"""

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ApplicationHandlerStop,
)

from core.base_module import BaseModule
from core.database import Database


class AutoReplyModule(BaseModule):

    def setup(self, app: Application) -> None:
        self.db        = Database()
        self.tenant_id = int(self.config.get("tenant_id", 0))
        self.admin_id  = int(self.config["bot"]["admin_id"])

        app.add_handler(CommandHandler("ar_add", self.ar_add))
        app.add_handler(CommandHandler("ar_list", self.ar_list))
        app.add_handler(CommandHandler("ar_del", self.ar_del))
        app.add_handler(CommandHandler("filter_add", self.filter_add))
        app.add_handler(CommandHandler("filter_list", self.filter_list))
        app.add_handler(CommandHandler("filter_del", self.filter_del))

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

    # ── 用户消息拦截 ────────────────────────────────────────

    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if msg is None or self._admin(update):
            return
        text = msg.text or msg.caption or ""
        if not text:
            return

        # 1) 过滤违禁词 → 拦截
        for f in self.db.get_filters(self.tenant_id):
            if f["keyword"] in text:
                await msg.reply_text("⚠️ 您的消息包含不被允许的内容，未发送。")
                raise ApplicationHandlerStop

        # 2) 自动回复
        for r in self.db.get_auto_replies(self.tenant_id):
            if r["keyword"] in text:
                await msg.reply_text(r["reply"])
                if r["stop"]:
                    raise ApplicationHandlerStop
                return
