from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from core.base_module import BaseModule


class MenuModule(BaseModule):
    """交互式菜单模块"""

    def setup(self, app: Application) -> None:
        app.add_handler(CommandHandler("menu", self.cmd_menu))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CallbackQueryHandler(self.on_callback, pattern=r"^menu:"))

    def _main_kb(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🏪 商店",   callback_data="menu:shop"),
             InlineKeyboardButton("📋 表单",   callback_data="menu:forms")],
            [InlineKeyboardButton("🎖️ 我的权限", callback_data="menu:role"),
             InlineKeyboardButton("ℹ️ 关于",   callback_data="menu:about")],
        ])

    async def cmd_menu(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        name = self.config["bot"].get("name", "机器人")
        await update.message.reply_text(
            f"📋 *{name} 主菜单*\n\n请选择功能：",
            reply_markup=self._main_kb(),
            parse_mode="Markdown",
        )

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "📖 *帮助*\n\n"
            "/start   — 欢迎消息\n"
            "/menu    — 主菜单\n"
            "/shop    — 数字商店\n"
            "/cart    — 购物车\n"
            "/orders  — 我的订单\n"
            "/forms   — 可用表单列表\n"
            "/myrole  — 查看我的权限\n"
            "/help    — 本帮助",
            parse_mode="Markdown",
        )

    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q    = update.callback_query
        data = q.data
        await q.answer()

        if data == "menu:shop":
            await q.edit_message_text(
                "🏪 前往商店，发送 /shop 开始购物！",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ 返回", callback_data="menu:back")]]))
        elif data == "menu:forms":
            await q.edit_message_text(
                "📋 发送 /forms 查看所有可用表单",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ 返回", callback_data="menu:back")]]))
        elif data == "menu:role":
            await q.edit_message_text(
                "🎖️ 发送 /myrole 查看您的权限等级",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ 返回", callback_data="menu:back")]]))
        elif data == "menu:about":
            ver     = self.config["bot"].get("version", "1.0.0")
            website = self.config["bot"].get("website", "")
            await q.edit_message_text(
                f"ℹ️ *关于*\n\n版本：{ver}\n{website}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ 返回", callback_data="menu:back")]]),
                parse_mode="Markdown",
            )
        elif data == "menu:back":
            name = self.config["bot"].get("name", "机器人")
            await q.edit_message_text(
                f"📋 *{name} 主菜单*\n\n请选择功能：",
                reply_markup=self._main_kb(),
                parse_mode="Markdown",
            )
