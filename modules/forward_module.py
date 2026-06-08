from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from core.base_module import BaseModule
from core.database import Database
from core.permissions import Role, get_role_from_config_or_db


class ForwardModule(BaseModule):
    """将普通用户消息转发给管理员，管理员回复时反向转发给用户"""

    def setup(self, app: Application) -> None:
        self.db = Database()
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u    = update.effective_user
        text = update.message.text
        self.db.upsert_user(u.id, u.username or "", u.full_name)

        if self.db.is_banned(u.id):
            await update.message.reply_text("⛔ 您已被封禁，无法发送消息。")
            return

        role           = get_role_from_config_or_db(u.id, self.config["bot"]["admin_id"])
        super_admin_id = self.config["bot"]["admin_id"]

        # 管理员回复转发给用户
        if role >= Role.ADMIN and update.message.reply_to_message:
            reply_text = update.message.reply_to_message.text or ""
            # 从转发消息中解析原始用户 ID
            for line in reply_text.split("\n"):
                if "ID:" in line:
                    try:
                        target_uid = int(line.split("ID:")[-1].strip().strip("`"))
                        self.db.log_message(u.id, "out", text)
                        await ctx.bot.send_message(
                            chat_id=target_uid,
                            text=f"📨 *管理员回复：*\n{text}",
                            parse_mode="Markdown",
                        )
                        await update.message.reply_text("✅ 已回复给用户")
                        return
                    except (ValueError, Exception):
                        pass

        # 普通用户消息 → 转发给管理员
        if role == Role.USER:
            self.db.log_message(u.id, "in", text)
            name  = u.full_name
            uname = f"@{u.username}" if u.username else "N/A"
            await ctx.bot.send_message(
                chat_id=super_admin_id,
                text=(
                    f"📩 *新消息*\n\n"
                    f"👤 {name} ({uname})\n"
                    f"🆔 ID: `{u.id}`\n\n"
                    f"💬 {text}\n\n"
                    f"_回复此消息可直接回复给用户_"
                ),
                parse_mode="Markdown",
            )
