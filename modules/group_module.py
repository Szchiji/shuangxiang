from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, ChatMemberHandler, filters, ContextTypes
from core.base_module import BaseModule
from core.database import Database


class GroupModule(BaseModule):
    """群组管理：欢迎消息 + 违禁词过滤 + 警告系统"""

    def setup(self, app: Application) -> None:
        self.db          = Database()
        self.cfg         = self.config.get("group", {})
        self.max_warns   = self.cfg.get("max_warns", 3)
        self.banned_kw   = self.cfg.get("banned_keywords", [])
        self.welcome_msg = self.cfg.get("welcome_message", "👋 欢迎 {name} 加入！")
        self._warns: dict[int, int] = {}

        app.add_handler(ChatMemberHandler(self.on_member_join, ChatMemberHandler.CHAT_MEMBER))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.filter_message))

    async def on_member_join(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        result = update.chat_member
        if result.new_chat_member.status not in ("member", "restricted"):
            return
        user = result.new_chat_member.user
        msg  = self.welcome_msg.format(
            name=user.full_name, username=f"@{user.username}" if user.username else user.full_name)
        try:
            await ctx.bot.send_message(chat_id=result.chat.id, text=msg)
        except Exception:
            pass

    async def filter_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type == "private":
            return
        text = (update.message.text or "").lower()
        for kw in self.banned_kw:
            if kw.lower() in text:
                uid  = update.effective_user.id
                self._warns[uid] = self._warns.get(uid, 0) + 1
                warns = self._warns[uid]
                try:
                    await update.message.delete()
                except Exception:
                    pass
                if warns >= self.max_warns:
                    try:
                        await ctx.bot.ban_chat_member(
                            chat_id=update.effective_chat.id, user_id=uid)
                        await update.effective_chat.send_message(
                            f"⛔ 用户 {update.effective_user.full_name} 因多次违规已被封禁。")
                        self._warns.pop(uid, None)
                    except Exception as e:
                        print(f"[GroupModule] 封禁失败：{e}")
                else:
                    await update.effective_chat.send_message(
                        f"⚠️ {update.effective_user.full_name}，检测到违禁词！\n"
                        f"警告 {warns}/{self.max_warns}，达到上限将被封禁。")
                return
