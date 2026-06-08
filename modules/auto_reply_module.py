from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from core.base_module import BaseModule
from core.database import Database


class AutoReplyModule(BaseModule):
    """关键词自动回复"""

    def setup(self, app: Application) -> None:
        self.db    = Database()
        self.rules = self.config.get("auto_reply", {})
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self.handle))

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        text = update.message.text or ""
        for keyword, reply in self.rules.items():
            if keyword in text:
                await update.message.reply_text(reply)
                return
