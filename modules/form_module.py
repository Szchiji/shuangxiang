import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from core.base_module import BaseModule
from core.database import Database

_STATE_KEY = "form_state"


class FormModule(BaseModule):
    """多步骤表单收集模块"""

    def setup(self, app: Application) -> None:
        self.db        = Database()
        self.tenant_id = self.config.get("tenant_id")
        app.add_handler(CommandHandler("forms",   self.cmd_list_forms))
        app.add_handler(CommandHandler("form",    self.cmd_start_form))
        app.add_handler(CommandHandler("cancel",  self.cmd_cancel))
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self.handle_answer))

    async def cmd_list_forms(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        forms = self.db.get_forms(self.tenant_id)
        if not forms:
            await update.message.reply_text("📋 暂无可用表单")
            return
        lines = ["📋 *可用表单*\n"]
        for f in forms:
            lines.append(f"`/form {f['slug']}` — {f['title']}")
            if f["description"]:
                lines.append(f"  _{f['description']}_")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def cmd_start_form(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：`/form <表单slug>`", parse_mode="Markdown")
            return
        slug = ctx.args[0]
        form = self.db.get_form_by_slug(slug, self.tenant_id)
        if not form:
            await update.message.reply_text(f"❌ 找不到表单 `{slug}`", parse_mode="Markdown")
            return
        steps = self.db.get_form_steps(form["id"])
        if not steps:
            await update.message.reply_text("❌ 该表单没有任何步骤")
            return
        ctx.user_data[_STATE_KEY] = {
            "form_id":  form["id"],
            "form_name": form["title"],
            "steps":    [dict(s) for s in steps],
            "current":  0,
            "answers":  {},
        }
        await update.message.reply_text(
            f"📋 *{form['title']}*\n"
            f"{form['description'] or ''}\n\n"
            f"发送 /cancel 可随时取消。",
            parse_mode="Markdown")
        await self._ask_step(update, ctx)

    async def _ask_step(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        state = ctx.user_data.get(_STATE_KEY)
        if not state:
            return
        idx   = state["current"]
        steps = state["steps"]
        if idx >= len(steps):
            await self._finish(update, ctx)
            return
        step    = steps[idx]
        total   = len(steps)
        choices = ""
        if step["choices"]:
            try:
                opts    = json.loads(step["choices"])
                choices = "\n\n选项：" + "、".join(opts)
            except Exception:
                pass
        req = "（必填）" if step["is_required"] else "（选填，发送 - 跳过）"
        await update.message.reply_text(
            f"📝 [{idx+1}/{total}] *{step['prompt']}* {req}{choices}",
            parse_mode="Markdown")

    async def handle_answer(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        state = ctx.user_data.get(_STATE_KEY)
        if not state:
            return
        text  = update.message.text
        idx   = state["current"]
        step  = state["steps"][idx]
        if text == "-" and not step["is_required"]:
            text = None
        state["answers"][step["field_name"]] = text
        state["current"] += 1
        if state["current"] >= len(state["steps"]):
            await self._finish(update, ctx)
        else:
            await self._ask_step(update, ctx)

    async def _finish(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        state = ctx.user_data.pop(_STATE_KEY, {})
        if not state:
            return
        uid       = update.effective_user.id
        responses = json.dumps(state["answers"], ensure_ascii=False)
        self.db.save_form_response(state["form_id"], uid, self.tenant_id, responses)
        lines = [f"✅ *{state['form_name']} — 提交成功！*\n\n您的回答："]
        for k, v in state["answers"].items():
            lines.append(f"• {k}：{v or '（跳过）'}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        # 通知管理员
        admin_id = self.config["bot"]["admin_id"]
        try:
            u     = update.effective_user
            uname = f"@{u.username}" if u.username else u.full_name
            await ctx.bot.send_message(
                chat_id=admin_id,
                text=f"📋 *新表单提交*\n\n表单：{state['form_name']}\n用户：{uname} (`{uid}`)\n\n"
                     + "\n".join(f"• {k}：{v}" for k, v in state["answers"].items()),
                parse_mode="Markdown")
        except Exception:
            pass

    async def cmd_cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if ctx.user_data.pop(_STATE_KEY, None):
            await update.message.reply_text("❌ 表单已取消")
        else:
            await update.message.reply_text("ℹ️ 没有进行中的表单")
