"""双向私聊机器人核心模块（每个租户机器人各运行一份）。

工作方式：
  • 普通用户私聊机器人 → 机器人把消息（任意类型）转发给该机器人的拥有者（管理员）；
  • 管理员「回复」某条转发过来的消息 → 机器人把回复（任意类型）发还给对应用户。

所有用户、封禁状态与消息映射均按 tenant_id 隔离，
因此同一套数据库可同时承载多个用户各自创建的机器人。
"""

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from core.base_module import BaseModule
from core.database import Database


class PrivateChatModule(BaseModule):
    """双向私聊（客服/反馈）机器人。"""

    def setup(self, app: Application) -> None:
        self.db        = Database()
        self.tenant_id = int(self.config.get("tenant_id", 0))
        self.admin_id  = int(self.config["bot"]["admin_id"])
        msgs           = self.config.get("messages", {})
        self.welcome   = msgs.get(
            "welcome",
            "👋 你好！直接发送消息即可联系管理员，我们会尽快回复你。",
        )
        self.admin_welcome = msgs.get(
            "admin_welcome",
            "👋 管理员你好！用户的消息会转发到这里，"
            "直接「回复」某条消息即可回复对应用户。",
        )
        self.received = msgs.get("received", "")          # 给用户的收到提示（留空则不发）
        self.banned   = msgs.get("banned", "⛔ 你已被封禁，无法发送消息。")

        # 指令
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_start))
        app.add_handler(CommandHandler("ban", self.cmd_ban))
        app.add_handler(CommandHandler("unban", self.cmd_unban))
        app.add_handler(CommandHandler("info", self.cmd_info))
        app.add_handler(CommandHandler("stats", self.cmd_stats))

        # 其余所有私聊消息（排除指令）走双向中转
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND, self.relay))

    # ── 辅助 ────────────────────────────────────────────────

    def _is_admin(self, uid: int) -> bool:
        return uid == self.admin_id

    def _user_label(self, user) -> str:
        uname = f"@{user.username}" if user.username else "无用户名"
        return f"👤 {user.full_name} ({uname})\n🆔 ID: `{user.id}`"

    def _resolve_target(self, update: Update):
        """从被回复的消息解析目标用户 ID。"""
        reply = update.message.reply_to_message
        if not reply:
            return None
        return self.db.get_mapped_user(self.tenant_id, reply.message_id)

    def _target_from_args(self, update: Update, ctx) -> int | None:
        target = self._resolve_target(update)
        if target is None and ctx.args:
            try:
                target = int(ctx.args[0])
            except ValueError:
                target = None
        return target

    # ── 指令 ────────────────────────────────────────────────

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if self._is_admin(user.id):
            await update.message.reply_text(self.admin_welcome)
        else:
            self.db.upsert_tenant_user(self.tenant_id, user.id,
                                       user.username or "", user.full_name)
            await update.message.reply_text(self.welcome)

    async def cmd_ban(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            return
        target = self._target_from_args(update, ctx)
        if target is None:
            await update.message.reply_text("⚠️ 请「回复」某位用户的消息，或使用 /ban <用户ID>。")
            return
        self.db.ban_user(self.tenant_id, target)
        await update.message.reply_text(f"⛔ 已封禁用户 `{target}`", parse_mode="Markdown")

    async def cmd_unban(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            return
        target = self._target_from_args(update, ctx)
        if target is None:
            await update.message.reply_text("⚠️ 请「回复」某位用户的消息，或使用 /unban <用户ID>。")
            return
        self.db.unban_user(self.tenant_id, target)
        await update.message.reply_text(f"✅ 已解封用户 `{target}`", parse_mode="Markdown")

    async def cmd_info(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            return
        target = self._resolve_target(update)
        if target is None:
            await update.message.reply_text("⚠️ 请「回复」某位用户的消息以查看其资料。")
            return
        u = self.db.get_tenant_user(self.tenant_id, target)
        if not u:
            await update.message.reply_text(f"未找到用户 `{target}`", parse_mode="Markdown")
            return
        status = "⛔ 已封禁" if u["is_banned"] else "✅ 正常"
        await update.message.reply_text(
            f"👤 {u['full_name']}\n"
            f"🔗 @{u['username'] or '无'}\n"
            f"🆔 `{u['id']}`\n".replace("u['id']", str(u['user_id']))
            if False else
            f"👤 {u['full_name']}\n"
            f"🔗 @{u['username'] or '无'}\n"
            f"🆔 `{u['user_id']}`\n"
            f"📊 状态：{status}\n"
            f"🕐 首次：{u['joined_at']}\n"
            f"🕐 最近：{u['last_seen']}",
            parse_mode="Markdown",
        )

    async def cmd_stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            return
        s = self.db.get_tenant_user_count(self.tenant_id)
        await update.message.reply_text(
            f"📊 *统计*\n\n"
            f"总用户：{s['total']}\n"
            f"正常：{s['active']}\n"
            f"封禁：{s['banned']}",
            parse_mode="Markdown",
        )

    # ── 双向中转 ─────────────────────────────────────────────

    async def relay(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg  = update.message
        user = update.effective_user
        if msg is None or user is None:
            return

        # 管理员：回复转发消息 → 发还给对应用户
        if self._is_admin(user.id):
            await self._admin_reply(update, ctx)
            return

        # 普通用户：消息 → 转发给管理员
        await self._user_to_admin(update, ctx)

    async def _user_to_admin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg  = update.message
        user = update.effective_user
        self.db.upsert_tenant_user(self.tenant_id, user.id,
                                   user.username or "", user.full_name)

        if self.db.is_banned(self.tenant_id, user.id):
            await msg.reply_text(self.banned)
            return

        try:
            # 先发送一条用户信息抬头，便于管理员识别
            header = await ctx.bot.send_message(
                chat_id=self.admin_id,
                text=f"📩 *新消息*\n\n{self._user_label(user)}\n\n_回复本消息即可回复该用户_",
                parse_mode="Markdown",
            )
            self.db.save_message_map(self.tenant_id, header.message_id,
                                     user.id, msg.message_id)

            # 再原样复制用户消息（支持图片/语音/文件/贴纸等所有类型）
            copied = await ctx.bot.copy_message(
                chat_id=self.admin_id,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id,
            )
            self.db.save_message_map(self.tenant_id, copied.message_id,
                                     user.id, msg.message_id)
        except TelegramError as e:
            print(f"[私聊] 转发给管理员失败: {e}")
            return

        if self.received:
            await msg.reply_text(self.received)

    async def _admin_reply(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg    = update.message
        target = self._resolve_target(update)

        if target is None:
            await msg.reply_text(
                "⚠️ 请「回复」某条用户消息来回复对应用户。\n"
                "可用指令：/ban /unban /info /stats")
            return

        try:
            await ctx.bot.copy_message(
                chat_id=target,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id,
            )
        except TelegramError as e:
            await msg.reply_text(f"❌ 发送失败：{e}\n（用户可能已停用或拉黑机器人）")
            return

        # 轻量回执：优先用表情反应，失败则忽略（不打扰管理员）
        try:
            await msg.set_reaction("👍")
        except (TelegramError, AttributeError):
            pass
