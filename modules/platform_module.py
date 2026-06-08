from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from core.base_module import BaseModule
from core.database import Database
from core.permissions import Role, require_role


class PlatformModule(BaseModule):
    """平台主Bot：管理多租户机器人的注册与控制"""

    def setup(self, app: Application) -> None:
        self.db = Database()
        app.add_handler(CommandHandler("addbot",    self.cmd_add_bot))
        app.add_handler(CommandHandler("mybots",    self.cmd_my_bots))
        app.add_handler(CommandHandler("stopbot",   self.cmd_stop_bot))
        app.add_handler(CommandHandler("startbot",  self.cmd_start_bot))
        app.add_handler(CommandHandler("platform",  self.cmd_platform))

    @require_role(Role.SUPER_ADMIN)
    async def cmd_platform(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tm     = ctx.application.bot_data.get("tenant_manager")
        count  = tm.running_count() if tm else 0
        tenants = self.db.get_all_tenants()
        await update.message.reply_text(
            f"🏢 *平台状态*\n\n"
            f"🤖 运行中的租户Bot：{count}\n"
            f"📊 总租户数：{len(tenants)}",
            parse_mode="Markdown")

    async def cmd_add_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text(
                "用法：`/addbot <Bot Token>`\n\n"
                "从 @BotFather 获取 Token 后粘贴此命令。",
                parse_mode="Markdown")
            return
        token = ctx.args[0].strip()
        uid   = update.effective_user.id
        tm    = ctx.application.bot_data.get("tenant_manager")
        if not tm:
            await update.message.reply_text("❌ 平台未初始化，请联系超级管理员")
            return
        await update.message.reply_text("⏳ 正在启动机器人，请稍候...")
        try:
            from telegram import Bot as TGBot
            async with TGBot(token=token) as tg:
                me = await tg.get_me()
            result = await tm.launch_tenant_from_data(
                token=token, bot_username=me.username, bot_name=me.full_name,
                owner_user_id=uid, admin_id=uid)
            await update.message.reply_text(
                f"✅ *机器人已添加并启动！*\n\n"
                f"🤖 名称：{result['bot_name']}\n"
                f"📎 用户名：@{result['bot_username']}\n"
                f"🆔 租户ID：`{result['id']}`",
                parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ 启动失败：{e}")

    async def cmd_my_bots(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid     = update.effective_user.id
        tm      = ctx.application.bot_data.get("tenant_manager")
        tenants = self.db.get_user_tenants(uid)
        if not tenants:
            await update.message.reply_text("📭 您还没有添加任何机器人。\n\n使用 /addbot <token> 添加。")
            return
        lines = ["🤖 *您的机器人列表*\n"]
        for t in tenants:
            running = "🟢 运行中" if (tm and tm.is_running(t["id"])) else "🔴 已停止"
            lines.append(f"`#{t['id']}` @{t['bot_username']} — {running}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def cmd_stop_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：`/stopbot <租户ID>`", parse_mode="Markdown")
            return
        tid = int(ctx.args[0])
        t   = self.db.get_tenant(tid)
        uid = update.effective_user.id
        if not t:
            await update.message.reply_text("❌ 找不到该机器人")
            return
        if t["owner_user_id"] != uid and uid != self.config["bot"]["admin_id"]:
            await update.message.reply_text("⛔ 您没有权限操作此机器人")
            return
        tm = ctx.application.bot_data.get("tenant_manager")
        if tm:
            await tm.stop_tenant(tid)
        await update.message.reply_text(f"⏹ 机器人 `#{tid}` 已停止", parse_mode="Markdown")

    async def cmd_start_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：`/startbot <租户ID>`", parse_mode="Markdown")
            return
        tid = int(ctx.args[0])
        t   = self.db.get_tenant(tid)
        uid = update.effective_user.id
        if not t:
            await update.message.reply_text("❌ 找不到该机器人")
            return
        if t["owner_user_id"] != uid and uid != self.config["bot"]["admin_id"]:
            await update.message.reply_text("⛔ 您没有权限操作此机器人")
            return
        tm = ctx.application.bot_data.get("tenant_manager")
        if tm:
            await tm.start_tenant(tid, t["token"], t["admin_id"])
            self.db.activate_tenant(tid)
        await update.message.reply_text(f"▶️ 机器人 `#{tid}` 已启动", parse_mode="Markdown")
