"""平台主机器人模块（机器人工厂）。

让任意用户通过指令用自己的 BotFather token 创建一个属于自己的双向私聊机器人：
  • /newbot <token>  —— 校验 token、登记并立即上线（也支持无参数引导态）
  • /mybots          —— 查看自己创建的机器人
  • /delbot <编号>   —— 停用并删除自己的机器人
新建的机器人会自动加载平台配置中的 tenant_modules（私聊 / 自动回复 / 菜单 / 表单 / 商店等）。

为了降低上手门槛并促进传播，本模块提供：
  • 内联按钮引导（如何创建 / 我的机器人 / 常见问题）；
  • 无参数引导态：发送 /newbot 后直接粘贴 Token 即可；
  • 创建成功后的新手引导与「分享我的机器人」按钮。
"""

import json
import re
from urllib.parse import quote

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
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
from modules.customize_module import load_button_rows, parse_buttons

TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")

# 平台级设置统一存于 tenant_kv 的 tenant_id=0 行（租户机器人共享同一数据库）。
PLATFORM_TID = 0
SK_PLATFORM_START_TEXT = "platform_start_text"          # 平台机器人自定义启动语
SK_PLATFORM_START_BTNS = "platform_start_buttons"       # 平台机器人启动语附加按钮(JSON)
SK_PLATFORM_BOT_USERNAME = "platform_bot_username"      # 超级管理员自定义的平台用户名
SK_PLATFORM_BOT_USERNAME_AUTO = "platform_bot_username_auto"  # 启动时自动探测的平台用户名


def platform_footer_username(db: Database) -> str:
    """返回要展示在租户启动信息底部的平台机器人用户名（去掉 @，可能为空）。

    优先使用超级管理员自定义值，其次回退到启动时自动探测到的真实用户名。
    """
    name = (db.get_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME, "")
            or db.get_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME_AUTO, "")
            or "")
    return name.lstrip("@").strip()

START_TEXT = (
    "🤖 *双向私聊机器人 · 工厂*\n\n"
    "用你自己的机器人 Token，几秒钟创建一个属于你的双向私聊机器人，"
    "支持 Topics 管理、自动回复与过滤、菜单、表单、数字商店等。\n\n"
    "点击下方按钮开始，或直接发送 `/newbot <你的Token>`。"
)

HELP_CREATE_TEXT = (
    "📖 *如何创建你的机器人*\n\n"
    "1️⃣ 打开 @BotFather，发送 /newbot 创建机器人，复制它给你的 *Token*\n"
    "（形如 `123456:ABC-DEF1234ghIkl...`）\n"
    "2️⃣ 回到这里发送：`/newbot <你的Token>`\n"
    "   也可以先发送 /newbot，再把 Token 直接粘贴发过来。\n"
    "3️⃣ 创建成功后打开你的机器人，给它发 /start 即可开始使用。"
)

FAQ_TEXT = (
    "❓ *常见问题*\n\n"
    "• *Token 在哪拿？* 找 @BotFather 创建机器人后会发给你。\n"
    "• *提示 Token 已被使用？* 同一个 Token 只能创建一个机器人，"
    "请到 @BotFather 用 /token 重置或换一个机器人。\n"
    "• *启动失败？* 多为 Token 失效或网络波动，稍后重试或更换 Token。\n"
    "• *如何多管理员协作？* 在你的机器人里使用 /setgroup 启用 Topics 模式。\n"
    "• *如何删除机器人？* 发送 /mybots 查看编号，再 /delbot <编号>。"
)


def _botfather_button() -> InlineKeyboardButton:
    return InlineKeyboardButton("➡️ 打开 @BotFather", url="https://t.me/BotFather")


def _default_start_buttons() -> list:
    return [
        [InlineKeyboardButton("🪄 创建我的机器人", callback_data="pf:newbot")],
        [InlineKeyboardButton("📖 如何创建", callback_data="pf:create")],
        [InlineKeyboardButton("🤖 我的机器人", callback_data="pf:mybots")],
        [InlineKeyboardButton("❓ 常见问题", callback_data="pf:faq")],
    ]


def _help_create_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_botfather_button()],
        [InlineKeyboardButton("🪄 我已拿到 Token，去创建", callback_data="pf:newbot")],
        [InlineKeyboardButton("⬅️ 返回", callback_data="pf:home")],
    ])


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ 返回", callback_data="pf:home")],
    ])


def _await_token_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_botfather_button()],
        [InlineKeyboardButton("⬅️ 返回", callback_data="pf:home")],
    ])


def _share_keyboard(username: str) -> InlineKeyboardMarkup:
    """生成「分享我的机器人」按钮（Telegram 转发卡片深链）。"""
    bot_url = f"https://t.me/{username}"
    text = quote(f"快来用我的机器人 @{username} 联系我吧！")
    share_url = f"https://t.me/share/url?url={quote(bot_url)}&text={text}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 打开机器人", url=bot_url)],
        [InlineKeyboardButton("📣 分享我的机器人", url=share_url)],
    ])


class PlatformModule(BaseModule):

    def setup(self, app: Application) -> None:
        self.db = Database()
        self.super_admin = int(self.config["bot"]["admin_id"])
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_start))
        app.add_handler(CommandHandler("newbot", self.cmd_newbot))
        app.add_handler(CommandHandler("mybots", self.cmd_mybots))
        app.add_handler(CommandHandler("delbot", self.cmd_delbot))
        app.add_handler(CommandHandler("cancel", self.cmd_cancel))
        app.add_handler(CallbackQueryHandler(self.on_callback, pattern=r"^pf:"))
        # 无参数引导态：用户发送 /newbot 后，直接粘贴的 Token 文本由此捕获。
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            self.on_text), group=9)

    def _is_super_admin(self, uid: int) -> bool:
        return uid == self.super_admin

    async def cmd_cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        cleared = ctx.user_data.pop("pf_admin_flow", None) is not None
        if ctx.chat_data.pop("awaiting_token", None):
            cleared = True
        if cleared:
            await update.effective_message.reply_text("已取消当前操作。")

    def _start_text(self) -> str:
        return self.db.get_setting(
            PLATFORM_TID, SK_PLATFORM_START_TEXT, "") or START_TEXT

    def _home_markup(self, user_id: int | None = None) -> InlineKeyboardMarkup:
        """平台启动面板：内置按钮 + 超级管理员自定义的附加按钮（及管理入口）。"""
        rows = _default_start_buttons()
        rows += load_button_rows(self.db, PLATFORM_TID, SK_PLATFORM_START_BTNS)
        if user_id is not None and self._is_super_admin(user_id):
            rows.append([InlineKeyboardButton(
                "⚙️ 平台设置", callback_data="pf:admin")])
        return InlineKeyboardMarkup(rows)

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        self.db.upsert_user(u.id, u.username or "", u.full_name)
        await update.message.reply_text(
            self._start_text(), parse_mode="Markdown",
            reply_markup=self._home_markup(u.id))

    # ── 内联按钮回调 ────────────────────────────────────────

    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        action = q.data.split(":", 1)[1]
        if action == "home":
            await q.answer()
            ctx.chat_data["awaiting_token"] = False
            ctx.user_data.pop("pf_admin_flow", None)
            await q.edit_message_text(
                self._start_text(), parse_mode="Markdown",
                reply_markup=self._home_markup(q.from_user.id))
        elif action == "create":
            await q.answer()
            await q.edit_message_text(
                HELP_CREATE_TEXT, parse_mode="Markdown",
                reply_markup=_help_create_keyboard())
        elif action == "faq":
            await q.answer()
            await q.edit_message_text(
                FAQ_TEXT, parse_mode="Markdown", reply_markup=_back_keyboard())
        elif action == "mybots":
            await q.answer()
            text, markup = self._mybots_view(q.from_user.id)
            await q.edit_message_text(
                text, parse_mode="Markdown", reply_markup=markup)
        elif action == "newbot":
            await q.answer()
            ctx.chat_data["awaiting_token"] = True
            await q.edit_message_text(
                "🪄 请把从 @BotFather 拿到的 *Token* 直接发给我即可。\n"
                "（形如 `123456:ABC-DEF1234ghIkl...`）",
                parse_mode="Markdown", reply_markup=_await_token_keyboard())
        elif action.startswith("admin"):
            await self._on_admin(q, ctx, action)
        else:
            await q.answer()

    # ── 平台设置（仅超级管理员）─────────────────────────────

    def _admin_markup(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ 自定义启动信息", callback_data="pf:admin:text")],
            [InlineKeyboardButton("🔘 启动信息按钮", callback_data="pf:admin:btns")],
            [InlineKeyboardButton("🏷 平台用户名（租户底部署名）",
                                  callback_data="pf:admin:uname")],
            [InlineKeyboardButton("⬅️ 返回", callback_data="pf:home")],
        ])

    def _admin_text(self) -> str:
        btn_rows = load_button_rows(self.db, PLATFORM_TID, SK_PLATFORM_START_BTNS)
        btns = "、".join(b.text for row in btn_rows for b in row) or "（无）"
        custom = self.db.get_setting(PLATFORM_TID, SK_PLATFORM_START_TEXT, "")
        uname = platform_footer_username(self.db)
        uname_line = f"@{escape_markdown(uname, version=1)}" if uname else "（未设置）"
        return (
            "⚙️ *平台设置*\n\n"
            f"启动信息：{'已自定义' if custom else '默认'}\n"
            f"启动按钮：{escape_markdown(btns, version=1)}\n"
            f"平台用户名：{uname_line}")

    async def _on_admin(self, q, ctx, action: str) -> None:
        if not self._is_super_admin(q.from_user.id):
            await q.answer("仅平台超级管理员可用。", show_alert=True)
            return
        if action == "admin":
            ctx.user_data.pop("pf_admin_flow", None)
            await q.answer()
            await q.edit_message_text(
                self._admin_text(), parse_mode="Markdown",
                reply_markup=self._admin_markup())
        elif action == "admin:text":
            ctx.user_data["pf_admin_flow"] = "text"
            await q.answer()
            cur = self.db.get_setting(
                PLATFORM_TID, SK_PLATFORM_START_TEXT, "") or "（未设置，使用默认）"
            await q.edit_message_text(
                "✏️ *自定义启动信息*\n\n请发送新的启动信息文本。\n\n"
                f"当前：\n{escape_markdown(cur, version=1)}\n\n发送 /cancel 取消。",
                parse_mode="Markdown")
        elif action == "admin:btns":
            ctx.user_data["pf_admin_flow"] = "btns"
            await q.answer()
            await q.edit_message_text(
                "🔘 *设置启动信息按钮*\n\n每行一行按钮，格式：\n`按钮文字 - 链接`\n\n"
                "例如：\n`官方频道 - https://t.me/yourchannel`\n\n"
                "💡 用 `&&` 可在一行放多个按钮：\n`频道 - https://t.me/a && 客服 - https://t.me/b`\n\n"
                "发送「清空」可移除全部自定义按钮，发送 /cancel 取消。",
                parse_mode="Markdown")
        elif action == "admin:uname":
            ctx.user_data["pf_admin_flow"] = "uname"
            await q.answer()
            await q.edit_message_text(
                "🏷 *平台用户名*\n\n该用户名会显示在每个租户机器人启动信息的最下方。\n"
                "请发送平台机器人的用户名（可带或不带 @）。\n\n"
                "发送「清空」可恢复为自动探测的真实用户名，发送 /cancel 取消。",
                parse_mode="Markdown")
        else:
            await q.answer()

    # ── 无参数引导态：粘贴 Token ─────────────────────────────

    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        flow = ctx.user_data.get("pf_admin_flow")
        if flow and self._is_super_admin(update.effective_user.id):
            await self._handle_admin_input(update, ctx, flow)
            return
        if not ctx.chat_data.get("awaiting_token"):
            return
        token = (update.message.text or "").strip()
        if not TOKEN_RE.match(token):
            return  # 非 Token 文本，忽略，等待用户重新发送或使用按钮
        ctx.chat_data["awaiting_token"] = False
        await self._create_bot(update, ctx, token)

    async def _handle_admin_input(self, update: Update,
                                  ctx: ContextTypes.DEFAULT_TYPE, flow: str) -> None:
        ctx.user_data.pop("pf_admin_flow", None)
        text = (update.message.text or "").strip()
        back = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ 返回平台设置", callback_data="pf:admin")]])
        if flow == "text":
            if not text:
                await update.message.reply_text(
                    "⚠️ 启动信息不能为空，已取消。", reply_markup=back)
                return
            self.db.set_setting(PLATFORM_TID, SK_PLATFORM_START_TEXT, text)
            await update.message.reply_text("✅ 启动信息已更新。", reply_markup=back)
        elif flow == "btns":
            if text == "清空":
                self.db.set_setting(PLATFORM_TID, SK_PLATFORM_START_BTNS, "")
                await update.message.reply_text(
                    "✅ 已清空启动信息按钮。", reply_markup=back)
                return
            rows = parse_buttons(text)
            if not rows:
                await update.message.reply_text(
                    "⚠️ 未识别到有效按钮（格式：文字 - 链接，链接需以 http/https 开头），已取消。",
                    reply_markup=back)
                return
            self.db.set_setting(PLATFORM_TID, SK_PLATFORM_START_BTNS,
                                json.dumps(rows, ensure_ascii=False))
            await update.message.reply_text(
                f"✅ 已设置 {sum(len(r) for r in rows)} 个启动信息按钮。",
                reply_markup=back)
        elif flow == "uname":
            if text == "清空":
                self.db.set_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME, "")
                await update.message.reply_text(
                    "✅ 已恢复为自动探测的平台用户名。", reply_markup=back)
                return
            uname = text.lstrip("@").strip()
            if not uname:
                await update.message.reply_text(
                    "⚠️ 用户名不能为空，已取消。", reply_markup=back)
                return
            self.db.set_setting(PLATFORM_TID, SK_PLATFORM_BOT_USERNAME, uname)
            await update.message.reply_text(
                f"✅ 平台用户名已设置为 @{uname}。", reply_markup=back)

    # ── 创建机器人 ──────────────────────────────────────────

    async def cmd_newbot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        self.db.upsert_user(u.id, u.username or "", u.full_name)

        token = (ctx.args[0].strip() if ctx.args else "")
        if not token:
            # 无参数 → 进入引导态，等待用户粘贴 Token
            ctx.chat_data["awaiting_token"] = True
            await update.message.reply_text(
                "🪄 请把从 @BotFather 拿到的 *Token* 直接发给我即可。\n"
                "（形如 `123456:ABC-DEF1234ghIkl...`）",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[_botfather_button()]]))
            return
        await self._create_bot(update, ctx, token)

    async def _create_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                          token: str) -> None:
        u = update.effective_user
        if not TOKEN_RE.match(token):
            await update.message.reply_text(
                "⚠️ Token 格式不正确。它应形如 `123456:ABC-DEF...`，"
                "请从 @BotFather 复制完整 Token 后重试。",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[_botfather_button()]]))
            return
        if self.db.get_tenant_by_token(token):
            await update.message.reply_text(
                "⚠️ 该 Token 已被使用。每个 Token 只能创建一个机器人，"
                "请到 @BotFather 用 /token 重置，或换一个机器人后重试。",
                reply_markup=InlineKeyboardMarkup([[_botfather_button()]]))
            return

        tm = ctx.application.bot_data.get("tenant_manager")
        await update.message.reply_text("⏳ 正在校验 Token 并启动你的机器人...")
        try:
            me = await tm.validate_token(token)
        except Exception:
            await update.message.reply_text(
                "❌ Token 无效或无法连接 Telegram。\n"
                "请检查：① Token 是否完整复制；② 该机器人是否未被删除；"
                "③ 稍后重试。",
                reply_markup=InlineKeyboardMarkup([[_botfather_button()]]))
            return

        tid = self.db.add_tenant(
            token, u.id, bot_id=me.id,
            bot_username=me.username or "", bot_name=me.full_name or "")
        tenant = self.db.get_tenant(tid)
        ok = await tm.start_tenant(tenant)
        if ok:
            await update.message.reply_text(
                f"✅ *创建成功！* 你的机器人：@{me.username}\n\n"
                "🚀 *接下来三步上手：*\n"
                f"1️⃣ 打开 t.me/{me.username} 给它发送 /start 测试收发\n"
                "2️⃣ 设置自动回复：`/ar_add 你好 | 您好，请问有什么可以帮您？`\n"
                "3️⃣ 搭建菜单：`/menu_add 0 | 关于我们 | 这里是简介`\n\n"
                "💡 进阶：/setgroup 启用 Topics 多人协作、/form_new 收集表单、"
                "/shop_addcat 开数字商店。\n"
                "把机器人分享给朋友，让更多人来联系你 👇",
                parse_mode="Markdown",
                reply_markup=_share_keyboard(me.username or ""))
        else:
            self.db.deactivate_tenant(tid)
            await update.message.reply_text(
                "❌ 机器人启动失败，请稍后重试或更换 Token。",
                reply_markup=InlineKeyboardMarkup([[_botfather_button()]]))

    # ── 我的机器人 ──────────────────────────────────────────

    def _mybots_view(self, user_id: int):
        rows = self.db.get_user_tenants(user_id)
        active = [r for r in rows if r["is_active"]]
        if not active:
            return (
                "你还没有机器人。点击下方按钮，几秒钟创建你的第一个机器人 👇",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ 创建我的机器人", callback_data="pf:newbot")],
                    [InlineKeyboardButton("📖 如何创建", callback_data="pf:create")],
                ]),
            )
        lines = [f"#{r['id']} @{r['bot_username']}（{r['bot_name']}）" for r in active]
        buttons = [
            [InlineKeyboardButton(f"📣 分享 @{r['bot_username']}",
                                  url=f"https://t.me/{r['bot_username']}")]
            for r in active if r["bot_username"]
        ]
        buttons.append(
            [InlineKeyboardButton("➕ 再创建一个", callback_data="pf:newbot")])
        return (
            "🤖 *我的机器人：*\n" + "\n".join(lines) + "\n\n删除：/delbot <编号>",
            InlineKeyboardMarkup(buttons),
        )

    async def cmd_mybots(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        text, markup = self._mybots_view(update.effective_user.id)
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=markup)

    async def cmd_delbot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args or not ctx.args[0].isdigit():
            await update.message.reply_text("用法：/delbot <编号>（编号见 /mybots）")
            return
        tid    = int(ctx.args[0])
        tenant = self.db.get_tenant(tid)
        if not tenant or tenant["owner_user_id"] != update.effective_user.id:
            await update.message.reply_text("⚠️ 未找到该机器人，或它不属于你。")
            return
        tm = ctx.application.bot_data.get("tenant_manager")
        if tm:
            await tm.stop_tenant(tid)
        self.db.delete_tenant(tid)
        await update.message.reply_text(f"✅ 已删除机器人 #{tid}。")
