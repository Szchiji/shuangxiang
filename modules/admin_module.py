from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from core.base_module import BaseModule
from core.database import Database
from core.permissions import Role, require_role


class AdminModule(BaseModule):

    def setup(self, app: Application) -> None:
        self.db = Database()
        for cmd, handler in [
            ("start",     self.cmd_start),
            ("status",    self.cmd_status),
            ("users",     self.cmd_users),
            ("ban",       self.cmd_ban),
            ("unban",     self.cmd_unban),
            ("broadcast", self.cmd_broadcast),
            ("history",   self.cmd_history),
        ]:
            app.add_handler(CommandHandler(cmd, handler))

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        self.db.upsert_user(u.id, u.username or "", u.full_name)
        await update.message.reply_text(
            "👋 你好！我是模块化机器人。\n直接发消息给我，我会转达给管理员。\n\n"
            "发送 /menu 打开功能菜单，/myrole 查看您的权限。"
        )

    @require_role(Role.ADMIN)
    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        s = self.db.get_user_count()
        a = len(self.db.get_all_admins())
        await update.message.reply_text(
            f"📊 *机器人状态*\n\n"
            f"👥 总用户：{s['total']}\n"
            f"✅ 活跃：{s['active']}\n"
            f"⛔ 封禁：{s['banned']}\n"
            f"🎖️ 管理员：{a + 1}",
            parse_mode="Markdown"
        )

    @require_role(Role.ADMIN)
    async def cmd_users(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        users = self.db.get_all_users(include_banned=True)
        if not users:
            await update.message.reply_text("📭 暂无用户")
            return
        lines = ["👥 *用户列表（最近 20 位）*\n"]
        for u in users[:20]:
            flag = "⛔" if u["is_banned"] else "✅"
            lines.append(f"{flag} `{u['id']}` {u['full_name']} (@{u['username'] or 'N/A'})")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    @require_role(Role.ADMIN)
    async def cmd_ban(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：/ban <用户ID>")
            return
        uid = int(ctx.args[0])
        self.db.ban_user(uid)
        await update.message.reply_text(f"⛔ 用户 `{uid}` 已封禁", parse_mode="Markdown")

    @require_role(Role.ADMIN)
    async def cmd_unban(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：/unban <用户ID>")
            return
        uid = int(ctx.args[0])
        self.db.unban_user(uid)
        await update.message.reply_text(f"✅ 用户 `{uid}` 已解封", parse_mode="Markdown")

    @require_role(Role.ADMIN)
    async def cmd_broadcast(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：/broadcast <消息内容>")
            return
        text  = " ".join(ctx.args)
        users = self.db.get_all_users()
        ok    = 0
        for u in users:
            try:
                await ctx.bot.send_message(chat_id=u["id"], text=f"📢 广播消息：\n{text}")
                ok += 1
            except Exception:
                pass
        self.db.log_broadcast(text, ok)
        await update.message.reply_text(f"✅ 广播完成：{ok}/{len(users)} 成功")

    @require_role(Role.ADMIN)
    async def cmd_history(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：/history <用户ID>")
            return
        uid  = int(ctx.args[0])
        msgs = self.db.get_user_messages(uid)
        if not msgs:
            await update.message.reply_text("📭 无记录")
            return
        lines = [f"📜 *用户 `{uid}` 最近消息*\n"]
        for m in reversed(msgs):
            arrow = "▶" if m["direction"] == "in" else "◀"
            lines.append(f"`{m['sent_at']}` {arrow} {m['content'][:50]}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
