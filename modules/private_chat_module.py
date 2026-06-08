"""双向私聊机器人核心模块（每个租户机器人各运行一份）。

两种管理模式：
  1) DM 模式（默认）：用户消息转发到机器人拥有者的私聊；拥有者「回复」即可回复用户。
  2) Topics 模式：拥有者把机器人加入一个开启「话题」的论坛超级群并运行 /setgroup，
     之后每位用户的对话会进入该群内独立的「话题(Topic)」，拥有者在话题内回复即可。

所有用户、封禁状态与消息映射均按 tenant_id 隔离。
"""

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown

from core.base_module import BaseModule
from core.database import Database
from modules.auto_reply_module import SK_ALPHABET_LATIN, SK_ANTIFLOOD
from modules.customize_module import (
    SK_WELCOME_BTNS,
    SK_WELCOME_MEDIA_ID,
    SK_WELCOME_MEDIA_TYPE,
    SK_WELCOME_TEXT,
    load_button_rows,
    reply_with_optional_media,
)
from modules.platform_module import platform_footer_username

logger = logging.getLogger("shuangxiang.private_chat")


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
        # 用户消息成功转发后给用户的「已发送」轻提示，默认 5 秒后自动删除。
        self.sent_ack = (msgs.get("sent_ack")
                         or "✅ 已发送成功，管理员会尽快回复你。")
        self._ack_delete_delay = 5.0
        self.banned   = msgs.get("banned", "⛔ 你已被封禁，无法发送消息。")
        # 可配置品牌署名页脚（默认关闭，尊重租户；设置后追加到用户欢迎语末尾）
        self.brand    = (msgs.get("brand") or "").strip()
        # 拥有者首次进入时的「下一步」上手清单
        self.admin_onboarding = (
            "\n\n🚀 *第一次使用？*\n"
            "点下方 *⚙️ 控制面板*，用按钮即可设置自动回复、启动语、安全过滤等，"
            "全程无需记忆指令。")

        # 指令
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_start))
        app.add_handler(CommandHandler("ban", self.cmd_ban))
        app.add_handler(CommandHandler("unban", self.cmd_unban))
        app.add_handler(CommandHandler("info", self.cmd_info))
        app.add_handler(CommandHandler("stats", self.cmd_stats))
        app.add_handler(CommandHandler("setgroup", self.cmd_setgroup))
        app.add_handler(CommandHandler("unsetgroup", self.cmd_unsetgroup))
        app.add_handler(CommandHandler("panel", self.cmd_panel))
        app.add_handler(CallbackQueryHandler(self.on_panel, pattern=r"^pc:"))

        # 私聊消息（用户 ↔ DM 模式拥有者）—— 放在较低优先级 group，
        # 让自动回复/过滤模块（group=0）有机会先拦截。
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

    def _platform_footer(self) -> str:
        """租户启动信息底部展示平台机器人用户名（由超级管理员配置，未配置则为空）。"""
        uname = platform_footer_username(self.db)
        return f"\n\n🏭 由 @{uname} 创建" if uname else ""

    def _user_label(self, user) -> str:
        name = escape_markdown(user.full_name or "", version=1)
        uname = (
            f"@{escape_markdown(user.username, version=1)}"
            if user.username else "无用户名"
        )
        return f"👤 {name} ({uname})\n🆔 ID: `{user.id}`"

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
                self.admin_welcome + self.admin_onboarding, parse_mode="Markdown",
                reply_markup=self._panel_markup())
        else:
            self.db.upsert_tenant_user(self.tenant_id, user.id,
                                       user.username or "", user.full_name)
            welcome = self.db.get_setting(
                self.tenant_id, SK_WELCOME_TEXT, "") or self.welcome
            text = welcome + (f"\n\n{self.brand}" if self.brand else "")
            text += self._platform_footer()
            media_type = self.db.get_setting(
                self.tenant_id, SK_WELCOME_MEDIA_TYPE, "") or ""
            media_id = self.db.get_setting(
                self.tenant_id, SK_WELCOME_MEDIA_ID, "") or ""
            await reply_with_optional_media(
                update.message, text, media_type, media_id,
                reply_markup=self._user_home_markup())

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
        await update.effective_message.reply_text(
            self._stats_text(), parse_mode="Markdown")

    def _stats_text(self) -> str:
        s = self.db.get_tenant_user_count(self.tenant_id)
        if s["total"] == 0:
            return (
                "📊 *统计*\n\n还没有用户来联系你。\n"
                "把你的机器人分享出去，并设置自动回复来留住第一批用户吧！")
        return (
            "📊 *统计*\n\n"
            f"总用户：{s['total']}\n"
            f"正常：{s['active']}\n"
            f"封禁：{s['banned']}\n"
            f"近 7 天活跃：{s['active_7d']}\n"
            f"近 7 天新增：{s['new_7d']}")

    # ── 控制面板（拥有者，按钮式管理）────────────────────────

    def _panel_markup(self) -> InlineKeyboardMarkup:
        """拥有者控制面板：一个入口聚合最常用的管理动作，按钮即点即用。"""
        antiflood = self.db.get_bool_setting(self.tenant_id, SK_ANTIFLOOD, True)
        latin     = self.db.get_bool_setting(self.tenant_id, SK_ALPHABET_LATIN, False)
        topics    = self._manage_group() is not None
        return InlineKeyboardMarkup([
            # 常用功能（直达交互式自定义，无需记忆指令）
            [InlineKeyboardButton("💬 自动回复", callback_data="cz:ar"),
             InlineKeyboardButton("📢 强制订阅", callback_data="cz:fsub")],
            [InlineKeyboardButton("✏️ 启动语", callback_data="cz:welcome"),
             InlineKeyboardButton("📊 数据统计", callback_data="pc:stats")],
            [InlineKeyboardButton("📣 群发广播", callback_data="cz:bc")],
            # 安全开关（点一下即切换）
            [InlineKeyboardButton(
                f"🛡 防刷屏：{'✅ 开' if antiflood else '⛔ 关'}",
                callback_data="pc:toggle:antiflood")],
            [InlineKeyboardButton(
                f"🔤 拦截英文：{'✅ 开' if latin else '⛔ 关'}",
                callback_data="pc:toggle:alphabet")],
            [InlineKeyboardButton(
                f"💬 Topics 模式：{'✅ 已启用' if topics else '未启用'}",
                callback_data="pc:topics")],
            [InlineKeyboardButton("⛔ 封禁管理", callback_data="pc:bans"),
             InlineKeyboardButton("📖 指令速查", callback_data="pc:help")],
        ])

    def _panel_text(self) -> str:
        return (
            "⚙️ *控制面板*\n\n"
            "一站式管理你的机器人，点按钮即可、无需记忆指令：\n"
            "• 自定义自动回复、启动语、群发等常用功能\n"
            "• 一键开关安全过滤与 Topics 协作模式")

    def _bans_view(self):
        """封禁管理视图：列出已封禁用户，并提供一键解封按钮。"""
        users = self.db.get_banned_tenant_users(self.tenant_id)
        if not users:
            text = (
                "⛔ *封禁管理*\n\n"
                "当前没有被封禁的用户。\n"
                "「回复」某位用户的消息（或在其话题内）发送 /ban 即可封禁。")
            kb = [[InlineKeyboardButton("⬅️ 返回面板", callback_data="pc:home")]]
            return text, InlineKeyboardMarkup(kb)
        text = (
            "⛔ *封禁管理*\n\n"
            "以下为已封禁用户，点按钮即可解封：")
        kb = []
        for u in users:
            label = u["full_name"] or (f"@{u['username']}" if u["username"] else "")
            label = (label or str(u["user_id"]))[:24]
            kb.append([InlineKeyboardButton(
                f"✅ 解封 {label}", callback_data=f"pc:unban:{u['user_id']}")])
        kb.append([InlineKeyboardButton("⬅️ 返回面板", callback_data="pc:home")])
        return text, InlineKeyboardMarkup(kb)

    # ── 内容功能管理视图 ────────────────────────────────────

    async def cmd_panel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            return
        await update.effective_message.reply_text(
            self._panel_text(), parse_mode="Markdown",
            reply_markup=self._panel_markup())

    async def on_panel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        action = q.data.split(":", 1)[1]

        # 控制面板操作均限拥有者
        if not self._is_admin(q.from_user.id):
            await q.answer("仅机器人拥有者可用。", show_alert=True)
            return
        back = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ 返回面板", callback_data="pc:home")]])

        if action == "home":
            await q.answer()
            await q.edit_message_text(
                self._panel_text(), parse_mode="Markdown",
                reply_markup=self._panel_markup())
        elif action == "stats":
            await q.answer()
            await q.edit_message_text(
                self._stats_text(), parse_mode="Markdown", reply_markup=back)
        elif action == "topics":
            await q.answer()
            text = (
                "💬 *Topics 模式*\n\n"
                "把我加入一个开启「话题」的论坛群，在群里发送 /setgroup 即可启用；"
                "之后每位用户的对话会进入独立话题，方便多人协作。\n"
                "发送 /unsetgroup 可恢复为私聊(DM)模式。")
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back)
        elif action == "help":
            await q.answer()
            text = (
                "📖 *指令速查*\n\n"
                "*自动回复*：/ar_add 关键词 | 回复　/ar_list　/ar_del\n"
                "*关键词过滤*：/filter_add 词　/filter_list　/filter_del\n"
                "*用户*：回复消息后 /ban /unban /info")
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back)
        elif action == "bans":
            await q.answer()
            text, markup = self._bans_view()
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        elif action.startswith("unban:"):
            try:
                target = int(action.split(":", 1)[1])
            except ValueError:
                await q.answer("⚠️ 无效的用户 ID")
                return
            self.db.unban_user(self.tenant_id, target)
            await q.answer("已解封")
            text, markup = self._bans_view()
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        elif action == "toggle:antiflood":
            cur = self.db.get_bool_setting(self.tenant_id, SK_ANTIFLOOD, True)
            self.db.set_setting(self.tenant_id, SK_ANTIFLOOD, "0" if cur else "1")
            await q.answer("防刷屏已" + ("关闭" if cur else "开启"))
            await q.edit_message_text(
                self._panel_text(), parse_mode="Markdown",
                reply_markup=self._panel_markup())
        elif action == "toggle:alphabet":
            cur = self.db.get_bool_setting(self.tenant_id, SK_ALPHABET_LATIN, False)
            self.db.set_setting(self.tenant_id, SK_ALPHABET_LATIN, "0" if cur else "1")
            await q.answer("英文拦截已" + ("关闭" if cur else "开启"))
            await q.edit_message_text(
                self._panel_text(), parse_mode="Markdown",
                reply_markup=self._panel_markup())
        else:
            await q.answer()

    # ── 用户主页导航（按钮代替命令）──────────────────────────

    def _user_home_markup(self):
        """根据已配置的自定义启动按钮，为用户生成导航按钮。"""
        rows = list(load_button_rows(self.db, self.tenant_id, SK_WELCOME_BTNS))
        return InlineKeyboardMarkup(rows) if rows else None

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
            logger.warning("转发失败: %s", e)
            return
        await self._notify_sent(ctx, msg)

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
            logger.warning("相册转发失败: %s", e)
            return
        await self._notify_sent(ctx, messages[-1])

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

    @staticmethod
    def _reply_snippet(msg) -> str | None:
        """从用户消息中提取「被回复消息」的简短摘要（话题模式提示用）。"""
        reply = getattr(msg, "reply_to_message", None)
        if reply is None:
            return None
        text = (reply.text or reply.caption or "").strip()
        if not text:
            # 无文本（如纯媒体）时给出占位说明
            return "（某条消息）"
        text = " ".join(text.split())
        return text if len(text) <= 80 else text[:79] + "…"

    async def _maybe_topic_reply_hint(self, ctx, group, thread_id, msg) -> None:
        """话题模式下，若用户发送的是「回复消息」，向管理员展示其回复上下文。"""
        snippet = self._reply_snippet(msg)
        if snippet is None:
            return
        try:
            await ctx.bot.send_message(
                chat_id=group, message_thread_id=thread_id,
                text=f"↩️ 用户回复了：{snippet}")
        except TelegramError as e:
            logger.warning("发送回复提示失败: %s", e)

    async def _forward_to_topic(self, ctx, group, user, msg) -> None:
        thread_id = await self._ensure_topic(ctx, group, user)
        await self._maybe_topic_reply_hint(ctx, group, thread_id, msg)
        await ctx.bot.copy_message(
            chat_id=group, message_thread_id=thread_id,
            from_chat_id=msg.chat_id, message_id=msg.message_id)

    async def _forward_album_to_topic(self, ctx, group, user, messages) -> None:
        thread_id = await self._ensure_topic(ctx, group, user)
        first = messages[0]
        await self._maybe_topic_reply_hint(ctx, group, thread_id, first)
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
            await msg.set_reaction("👍")
        except (TelegramError, AttributeError):
            pass

    async def _notify_sent(self, ctx, msg) -> None:
        """用户消息成功转发后给出回执。

        • 若租户自定义了 ``received`` 文案：保持原行为（持久提示，不自动删除）。
        • 否则发送默认「已发送成功」轻提示，并在 ``_ack_delete_delay`` 秒后自动删除，
          保持用户对话整洁。
        """
        if self.received:
            try:
                await msg.reply_text(self.received)
            except TelegramError as e:
                logger.warning("发送回执失败: %s", e)
            return
        if not self.sent_ack:
            return
        try:
            sent = await msg.reply_text(self.sent_ack)
        except TelegramError as e:
            logger.warning("发送已送达提示失败: %s", e)
            return
        if sent is None or self._ack_delete_delay is None:
            return
        chat_id = getattr(sent, "chat_id", None)
        message_id = getattr(sent, "message_id", None)
        if chat_id is None or message_id is None:
            return
        # 保留任务引用，避免被垃圾回收而中断延时删除。
        tasks = self.__dict__.setdefault("_bg_tasks", set())
        task = asyncio.create_task(
            self._delete_later(ctx, chat_id, message_id, self._ack_delete_delay))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @staticmethod
    async def _delete_later(ctx, chat_id, message_id, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await ctx.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (TelegramError, asyncio.CancelledError):
            pass
        except Exception as e:  # noqa: BLE001 — 删除失败不应影响主流程
            logger.debug("删除已送达提示失败: %s", e)
