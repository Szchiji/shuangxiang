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

from core.base_module import BaseModule
from core.database import Database

TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")

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


def _start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🪄 创建我的机器人", callback_data="pf:newbot")],
        [InlineKeyboardButton("📖 如何创建", callback_data="pf:create")],
        [InlineKeyboardButton("🤖 我的机器人", callback_data="pf:mybots")],
        [InlineKeyboardButton("❓ 常见问题", callback_data="pf:faq")],
    ])


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
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_start))
        app.add_handler(CommandHandler("newbot", self.cmd_newbot))
        app.add_handler(CommandHandler("mybots", self.cmd_mybots))
        app.add_handler(CommandHandler("delbot", self.cmd_delbot))
        app.add_handler(CallbackQueryHandler(self.on_callback, pattern=r"^pf:"))
        # 无参数引导态：用户发送 /newbot 后，直接粘贴的 Token 文本由此捕获。
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            self.on_text), group=9)

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        self.db.upsert_user(u.id, u.username or "", u.full_name)
        await update.message.reply_text(
            START_TEXT, parse_mode="Markdown", reply_markup=_start_keyboard())

    # ── 内联按钮回调 ────────────────────────────────────────

    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        await q.answer()
        action = q.data.split(":", 1)[1]
        if action == "home":
            ctx.chat_data["awaiting_token"] = False
            await q.edit_message_text(
                START_TEXT, parse_mode="Markdown", reply_markup=_start_keyboard())
        elif action == "create":
            await q.edit_message_text(
                HELP_CREATE_TEXT, parse_mode="Markdown",
                reply_markup=_help_create_keyboard())
        elif action == "faq":
            await q.edit_message_text(
                FAQ_TEXT, parse_mode="Markdown", reply_markup=_back_keyboard())
        elif action == "mybots":
            text, markup = self._mybots_view(q.from_user.id)
            await q.edit_message_text(
                text, parse_mode="Markdown", reply_markup=markup)
        elif action == "newbot":
            ctx.chat_data["awaiting_token"] = True
            await q.edit_message_text(
                "🪄 请把从 @BotFather 拿到的 *Token* 直接发给我即可。\n"
                "（形如 `123456:ABC-DEF1234ghIkl...`）",
                parse_mode="Markdown", reply_markup=_await_token_keyboard())

    # ── 无参数引导态：粘贴 Token ─────────────────────────────

    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.chat_data.get("awaiting_token"):
            return
        token = (update.message.text or "").strip()
        if not TOKEN_RE.match(token):
            return  # 非 Token 文本，忽略，等待用户重新发送或使用按钮
        ctx.chat_data["awaiting_token"] = False
        await self._create_bot(update, ctx, token)

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
