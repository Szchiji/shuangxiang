"""双向私聊机器人核心模块（每个租户机器人各运行一份）。

两种管理模式：
  1) DM 模式（默认）：用户消息转发到机器人拥有者的私聊；拥有者「回复」即可回复用户。
  2) Topics 模式：拥有者把机器人加入一个开启「话题」的论坛超级群并运行 /setgroup，
     之后每位用户的对话会进入该群内独立的「话题(Topic)」，拥有者在话题内回复即可。

所有用户、封禁状态与消息映射均按 tenant_id 隔离。
"""

import asyncio

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
        # 相册（媒体组）缓冲：media_group_id -> {"user", "messages", "task"}。
        # 同一相册的多张媒体以多个独立消息到达，需聚合后整体转发。
        self._albums       = {}
        self._album_delay  = 1.0
        # 每用户话题创建锁，避免并发首条消息为同一用户重复建话题。
        self._topic_locks  = {}
        msgs           = self.config.get("messages", {})
        self.welcome   = msgs.get(
            "welcome",
            "👋 你好！直接发送消息即可联系管理员，我们会尽快回复你。")
        self.admin_welcome = msgs.get(
            "admin_welcome",
            "👋 管理员你好！用户的消息会转发到这里，"
            "直接「回复」某条消息即可回复对应用户。\n\n"
            "💡 把我加入一个开启「话题」的群并运行 /setgroup 可启用 Topics 管理模式。")
        self.received = msgs.get("received", "")
        self.banned   = msgs.get("banned", "⛔ 你已被封禁，无法发送消息。")
        # 可配置品牌署名页脚（默认关闭，尊重租户；设置后追加到用户欢迎语末尾）
        self.brand    = (msgs.get("brand") or "").strip()
        # 拥有者首次进入时的「下一步」上手清单
        self.admin_onboarding = (
            "\n\n🚀 *新手上手清单：*\n"
            "1️⃣ 自动回复：`/ar_add 你好 | 您好，有什么可以帮您？`\n"
            "2️⃣ 关键词过滤：`/filter_add 广告`\n"
            "3️⃣ 搭建菜单：`/menu_add 0 | 关于我们 | 这里是简介`\n"
            "4️⃣ 收集表单：`/form_new 报名`\n"
            "5️⃣ 数字商店：`/shop_addcat 会员`\n"
            "6️⃣ 多人协作：把我加入论坛群并运行 /setgroup\n"
            "查看用户统计：/stats")

        # 指令
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_start))
        app.add_handler(CommandHandler("ban", self.cmd_ban))
        app.add_handler(CommandHandler("unban", self.cmd_unban))
        app.add_handler(CommandHandler("info", self.cmd_info))
        app.add_handler(CommandHandler("stats", self.cmd_stats))
        app.add_handler(CommandHandler("setgroup", self.cmd_setgroup))
        app.add_handler(CommandHandler("unsetgroup", self.cmd_unsetgroup))

        # 私聊消息（用户 ↔ DM 模式拥有者）—— 放在较低优先级 group，
        # 让自动回复/过滤模块（group=-1）有机会先拦截。
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND, self.on_private), group=5)
        # 群内话题消息（Topics 模式拥有者回复用户）
        app.add_handler(MessageHandler(
            filters.ChatType.GROUPS & ~filters.COMMAND, self.on_group), group=5)

    # ── 辅助 ────────────────────────────────────────────────

    def _is_admin(self, uid: int) -> bool:
        return uid == self.admin_id

    def _manage_group(self):
        return self.db.get_manage_group(self.tenant_id)

    def _user_label(self, user) -> str:
        uname = f"@{user.username}" if user.username else "无用户名"
        return f"👤 {user.full_name} ({uname})\n🆔 ID: `{user.id}`"

    def _resolve_target(self, update: Update):
        reply = update.message.reply_to_message
        if not reply:
            return None
        return self.db.get_mapped_user(self.tenant_id, reply.message_id)

    def _target_from_args(self, update: Update, ctx):
        target = self._resolve_target(update)
        if target is None and ctx.args:
            try:
                target = int(ctx.args[0])
            except ValueError:
                target = None
        return target

    # ── 指令 ────────────────────────────────────────────────

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type != "private":
            return
        user = update.effective_user
        if self._is_admin(user.id):
            await update.message.reply_text(
                self.admin_welcome + self.admin_onboarding, parse_mode="Markdown")
        else:
            self.db.upsert_tenant_user(self.tenant_id, user.id,
                                       user.username or "", user.full_name)
            text = self.welcome + (f"\n\n{self.brand}" if self.brand else "")
            await update.message.reply_text(text)

    async def cmd_setgroup(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            return
        chat = update.effective_chat
        if chat.type not in ("group", "supergroup"):
            await update.message.reply_text("⚠️ 请在目标群里发送 /setgroup。")
            return
        if not getattr(chat, "is_forum", False):
            await update.message.reply_text(
                "⚠️ 该群未开启「话题(Topics)」功能。请在群设置中开启后再试。")
            return
        self.db.set_manage_group(self.tenant_id, chat.id)
        await update.message.reply_text(
            "✅ 已绑定本群为管理群。用户的每段对话会进入独立话题，"
            "在话题内直接回复即可回复用户。")

    async def cmd_unsetgroup(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            return
        self.db.set_manage_group(self.tenant_id, None)
        await update.effective_message.reply_text("✅ 已解绑管理群，恢复为私聊(DM)模式。")

    async def cmd_ban(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            return
        target = self._target_from_args(update, ctx) or self._topic_target(update)
        if target is None:
            await update.message.reply_text("⚠️ 请「回复」某位用户的消息（或在其话题内），或使用 /ban <用户ID>。")
            return
        self.db.ban_user(self.tenant_id, target)
        await update.message.reply_text(f"⛔ 已封禁用户 `{target}`", parse_mode="Markdown")

    async def cmd_unban(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            return
        target = self._target_from_args(update, ctx) or self._topic_target(update)
        if target is None:
            await update.message.reply_text("⚠️ 请「回复」某位用户的消息（或在其话题内），或使用 /unban <用户ID>。")
            return
        self.db.unban_user(self.tenant_id, target)
        await update.message.reply_text(f"✅ 已解封用户 `{target}`", parse_mode="Markdown")

    async def cmd_info(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            return
        target = self._resolve_target(update) or self._topic_target(update)
        if target is None:
            await update.message.reply_text("⚠️ 请「回复」某位用户的消息（或在其话题内）查看资料。")
            return
        u = self.db.get_tenant_user(self.tenant_id, target)
        if not u:
            await update.message.reply_text(f"未找到用户 `{target}`", parse_mode="Markdown")
            return
        status = "⛔ 已封禁" if u["is_banned"] else "✅ 正常"
        await update.message.reply_text(
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
        if s["total"] == 0:
            await update.effective_message.reply_text(
                "📊 *统计*\n\n还没有用户来联系你。\n"
                "把你的机器人分享出去，并用 /ar_add 设置自动回复来留住第一批用户吧！",
                parse_mode="Markdown")
            return
        await update.effective_message.reply_text(
            "📊 *统计*\n\n"
            f"总用户：{s['total']}\n"
            f"正常：{s['active']}\n"
            f"封禁：{s['banned']}\n"
            f"近 7 天活跃：{s['active_7d']}\n"
            f"近 7 天新增：{s['new_7d']}",
            parse_mode="Markdown",
        )

    def _topic_target(self, update: Update):
        """Topics 模式下，从当前话题解析对应用户。"""
        thread_id = getattr(update.effective_message, "message_thread_id", None)
        if thread_id is None:
            return None
        return self.db.get_topic_user(self.tenant_id, thread_id)

    # ── 私聊消息 ─────────────────────────────────────────────

    async def on_private(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg, user = update.message, update.effective_user
        if msg is None or user is None:
            return

        # DM 模式下，拥有者在私聊里「回复」转发消息 → 回复用户
        if self._is_admin(user.id) and self._manage_group() is None:
            await self._admin_reply_dm(update, ctx)
            return
        if self._is_admin(user.id):
            # 已启用 Topics 模式：拥有者请到管理群的话题里回复
            return

        await self._incoming_user(update, ctx)

    async def _incoming_user(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg, user = update.message, update.effective_user
        self.db.upsert_tenant_user(self.tenant_id, user.id,
                                   user.username or "", user.full_name)
        if self.db.is_banned(self.tenant_id, user.id):
            await msg.reply_text(self.banned)
            return

        # 相册（媒体组）：聚合后整体转发，避免逐张拆散。
        if getattr(msg, "media_group_id", None):
            self._buffer_album(ctx, user, msg)
            return

        group = self._manage_group()
        try:
            if group is not None:
                await self._forward_to_topic(ctx, group, user, msg)
            else:
                await self._forward_to_dm(ctx, user, msg)
        except TelegramError as e:
            print(f"[私聊] 转发失败: {e}")
            return

        if self.received:
            await msg.reply_text(self.received)

    # ── 相册（媒体组）聚合 ───────────────────────────────────

    def _buffer_album(self, ctx, user, msg) -> None:
        mgid = msg.media_group_id
        buf = self._albums.get(mgid)
        if buf is None:
            buf = {"user": user, "messages": [], "task": None}
            self._albums[mgid] = buf
        buf["messages"].append(msg)
        if buf["task"] is not None:
            buf["task"].cancel()
        buf["task"] = asyncio.create_task(self._flush_album_later(ctx, mgid))

    async def _flush_album_later(self, ctx, mgid) -> None:
        try:
            await asyncio.sleep(self._album_delay)
        except asyncio.CancelledError:
            return
        buf = self._albums.pop(mgid, None)
        if not buf or not buf["messages"]:
            return
        user = buf["user"]
        messages = sorted(buf["messages"], key=lambda m: m.message_id)
        group = self._manage_group()
        try:
            if group is not None:
                await self._forward_album_to_topic(ctx, group, user, messages)
            else:
                await self._forward_album_to_dm(ctx, user, messages)
        except TelegramError as e:
            print(f"[私聊] 相册转发失败: {e}")
            return
        if self.received:
            await messages[-1].reply_text(self.received)

    async def _forward_to_dm(self, ctx, user, msg) -> None:
        header = await ctx.bot.send_message(
            chat_id=self.admin_id,
            text=f"📩 *新消息*\n\n{self._user_label(user)}\n\n_回复本消息即可回复该用户_",
            parse_mode="Markdown",
        )
        self.db.save_message_map(self.tenant_id, header.message_id, user.id, msg.message_id)
        copied = await ctx.bot.copy_message(
            chat_id=self.admin_id, from_chat_id=msg.chat_id, message_id=msg.message_id)
        self.db.save_message_map(self.tenant_id, copied.message_id, user.id, msg.message_id)

    async def _forward_album_to_dm(self, ctx, user, messages) -> None:
        first = messages[0]
        header = await ctx.bot.send_message(
            chat_id=self.admin_id,
            text=f"📩 *新消息*\n\n{self._user_label(user)}\n\n_回复本消息即可回复该用户_",
            parse_mode="Markdown",
        )
        self.db.save_message_map(self.tenant_id, header.message_id, user.id, first.message_id)
        copied = await ctx.bot.copy_messages(
            chat_id=self.admin_id, from_chat_id=first.chat_id,
            message_ids=[m.message_id for m in messages])
        for mid in copied:
            self.db.save_message_map(self.tenant_id, mid.message_id, user.id, first.message_id)

    def _topic_lock(self, user_id: int) -> asyncio.Lock:
        lock = self._topic_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._topic_locks[user_id] = lock
        return lock

    async def _ensure_topic(self, ctx, group, user):
        """获取用户对应话题，没有则创建。加锁避免并发重复创建。"""
        async with self._topic_lock(user.id):
            thread_id = self.db.get_user_topic(self.tenant_id, user.id)
            if thread_id is None:
                topic = await ctx.bot.create_forum_topic(
                    chat_id=group, name=f"{user.full_name} · {user.id}")
                thread_id = topic.message_thread_id
                self.db.set_topic(self.tenant_id, thread_id, user.id)
                await ctx.bot.send_message(
                    chat_id=group, message_thread_id=thread_id,
                    text=f"🆕 新会话\n\n{self._user_label(user)}", parse_mode="Markdown")
            return thread_id

    async def _forward_to_topic(self, ctx, group, user, msg) -> None:
        thread_id = await self._ensure_topic(ctx, group, user)
        await ctx.bot.copy_message(
            chat_id=group, message_thread_id=thread_id,
            from_chat_id=msg.chat_id, message_id=msg.message_id)

    async def _forward_album_to_topic(self, ctx, group, user, messages) -> None:
        thread_id = await self._ensure_topic(ctx, group, user)
        first = messages[0]
        await ctx.bot.copy_messages(
            chat_id=group, message_thread_id=thread_id,
            from_chat_id=first.chat_id,
            message_ids=[m.message_id for m in messages])

    async def _admin_reply_dm(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg    = update.message
        target = self._resolve_target(update)
        if target is None:
            await msg.reply_text(
                "⚠️ 请「回复」某条用户消息来回复对应用户。\n可用指令：/ban /unban /info /stats")
            return
        try:
            await ctx.bot.copy_message(
                chat_id=target, from_chat_id=msg.chat_id, message_id=msg.message_id)
        except TelegramError as e:
            await msg.reply_text(f"❌ 发送失败：{e}\n（用户可能已停用或拉黑机器人）")
            return
        await self._ack(msg)

    # ── 群内话题消息（Topics 模式拥有者回复）────────────────

    async def on_group(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if msg is None or update.effective_user is None:
            return
        group = self._manage_group()
        if group is None or update.effective_chat.id != group:
            return
        if update.effective_user.is_bot:
            return
        thread_id = getattr(msg, "message_thread_id", None)
        if thread_id is None:
            return
        target = self.db.get_topic_user(self.tenant_id, thread_id)
        if target is None:
            return
        if self.db.is_banned(self.tenant_id, target):
            await msg.reply_text("⛔ 该用户已被封禁。")
            return

        # 拥有者发来的相册（媒体组）：聚合后整体回传给用户。
        if getattr(msg, "media_group_id", None):
            self._buffer_admin_album(ctx, target, msg)
            return

        try:
            await ctx.bot.copy_message(
                chat_id=target, from_chat_id=msg.chat_id, message_id=msg.message_id)
        except TelegramError as e:
            await msg.reply_text(f"❌ 发送失败：{e}")
            return
        await self._ack(msg)

    def _buffer_admin_album(self, ctx, target, msg) -> None:
        mgid = msg.media_group_id
        buf = self._albums.get(mgid)
        if buf is None:
            buf = {"target": target, "messages": [], "task": None}
            self._albums[mgid] = buf
        buf["messages"].append(msg)
        if buf["task"] is not None:
            buf["task"].cancel()
        buf["task"] = asyncio.create_task(self._flush_admin_album_later(ctx, mgid))

    async def _flush_admin_album_later(self, ctx, mgid) -> None:
        try:
            await asyncio.sleep(self._album_delay)
        except asyncio.CancelledError:
            return
        buf = self._albums.pop(mgid, None)
        if not buf or not buf["messages"]:
            return
        target = buf["target"]
        messages = sorted(buf["messages"], key=lambda m: m.message_id)
        first = messages[0]
        try:
            await ctx.bot.copy_messages(
                chat_id=target, from_chat_id=first.chat_id,
                message_ids=[m.message_id for m in messages])
        except TelegramError as e:
            await first.reply_text(f"❌ 发送失败：{e}")
            return
        await self._ack(messages[-1])

    @staticmethod
    async def _ack(msg) -> None:
        try:
            await msg.set_reaction("��")
        except (TelegramError, AttributeError):
            pass
