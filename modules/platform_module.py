"""平台主机器人模块（机器人工厂）。

让任意用户通过指令用自己的 BotFather token 创建一个属于自己的双向私聊机器人：
  • /newbot <token>  —— 校验 token、登记并立即上线
  • /mybots          —— 查看自己创建的机器人
  • /delbot <编号>   —— 停用并删除自己的机器人
新建的机器人会自动加载平台配置中的 tenant_modules（私聊 / 自动回复 / 菜单 / 表单 / 商店等）。
"""

import re

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.base_module import BaseModule
from core.database import Database

TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")


class PlatformModule(BaseModule):

    def setup(self, app: Application) -> None:
        self.db = Database()
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_start))
        app.add_handler(CommandHandler("newbot", self.cmd_newbot))
        app.add_handler(CommandHandler("mybots", self.cmd_mybots))
        app.add_handler(CommandHandler("delbot", self.cmd_delbot))

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        self.db.upsert_user(u.id, u.username or "", u.full_name)
        await update.message.reply_text(
            "🤖 *双向私聊机器人 · 工厂*\n\n"
            "用你自己的机器人 Token，几秒钟创建一个属于你的双向私聊机器人，"
            "支持 Topics 管理、自动回复与过滤、菜单、表单、数字商店等。\n\n"
            "*如何创建：*\n"
            "1️⃣ 找 @BotFather 创建机器人，复制它给你的 Token\n"
            "2️⃣ 发送：`/newbot <你的Token>`\n\n"
            "*其他指令：*\n"
            "/mybots —— 查看我的机器人\n"
            "/delbot <编号> —— 删除我的机器人",
            parse_mode="Markdown",
        )

    async def cmd_newbot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        self.db.upsert_user(u.id, u.username or "", u.full_name)

        token = (ctx.args[0].strip() if ctx.args else "")
        if not token:
            await update.message.reply_text(
                "用法：/newbot <机器人Token>\nToken 形如 `123456:ABC-DEF...`，从 @BotFather 获取。",
                parse_mode="Markdown")
            return
        if not TOKEN_RE.match(token):
            await update.message.reply_text("⚠️ Token 格式不正确，请检查后重试。")
            return
        if self.db.get_tenant_by_token(token):
            await update.message.reply_text("⚠️ 该 Token 已被使用。")
            return

        tm = ctx.application.bot_data.get("tenant_manager")
        await update.message.reply_text("⏳ 正在校验 Token 并启动你的机器人...")
        try:
            me = await tm.validate_token(token)
        except Exception:
            await update.message.reply_text("❌ Token 无效或无法连接 Telegram，请确认后重试。")
            return

        tid = self.db.add_tenant(
            token, u.id, bot_id=me.id,
            bot_username=me.username or "", bot_name=me.full_name or "")
        tenant = self.db.get_tenant(tid)
        ok = await tm.start_tenant(tenant)
        if ok:
            await update.message.reply_text(
                f"✅ 创建成功！你的机器人：@{me.username}\n"
                f"现在打开 t.me/{me.username} 给它发送 /start 试试。\n\n"
                f"在你的机器人里可用：/setgroup（Topics 管理）、/ar_add（自动回复）、"
                f"/menu_add（菜单）、/form_new（表单）、/shop_addcat（商店）等。")
        else:
            self.db.deactivate_tenant(tid)
            await update.message.reply_text(
                "❌ 机器人启动失败，请稍后重试或更换 Token。")

    async def cmd_mybots(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        rows = self.db.get_user_tenants(update.effective_user.id)
        active = [r for r in rows if r["is_active"]]
        if not active:
            await update.message.reply_text("你还没有机器人。发送 /newbot <Token> 创建一个。")
            return
        lines = [f"#{r['id']} @{r['bot_username']}（{r['bot_name']}）" for r in active]
        await update.message.reply_text(
            "🤖 我的机器人：\n" + "\n".join(lines) + "\n\n删除：/delbot <编号>")

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
