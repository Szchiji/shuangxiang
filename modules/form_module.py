"""引导式表单 / 信息收集（每个租户机器人各运行一份）。

拥有者定义表单与若干步骤（问题）；用户用 /forms 选择表单后，
机器人逐步提问、收集回答，完成后保存并通知拥有者。

进行中的填写状态存于 ctx.user_data["form_state"]，
填写期间的消息由 group=-2 的处理器优先捕获，不再转发给管理员。
"""

import json

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ApplicationHandlerStop,
)

from core.base_module import BaseModule
from core.database import Database


class FormModule(BaseModule):

    def setup(self, app: Application) -> None:
        self.db        = Database()
        self.tenant_id = int(self.config.get("tenant_id", 0))
        self.admin_id  = int(self.config["bot"]["admin_id"])

        app.add_handler(CommandHandler("forms", self.cmd_forms))
        app.add_handler(CommandHandler("form_new", self.form_new))
        app.add_handler(CommandHandler("form_step", self.form_step))
        app.add_handler(CommandHandler("form_list", self.form_list))
        app.add_handler(CommandHandler("form_del", self.form_del))
        app.add_handler(CommandHandler("cancel", self.cancel))
        app.add_handler(CallbackQueryHandler(self.start_form, pattern=r"^form:"))
        # 填写中的回答优先捕获
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            self.on_answer), group=-2)

    def _admin(self, update: Update) -> bool:
        return update.effective_user.id == self.admin_id

    # ── 拥有者定义 ──────────────────────────────────────────

    async def form_new(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        title = update.message.text.partition(" ")[2].strip()
        if not title:
            await update.message.reply_text("用法：/form_new <表单标题>")
            return
        fid = self.db.add_form(self.tenant_id, title)
        await update.message.reply_text(
            f"✅ 已创建表单 #{fid}：{title}\n用 /form_step {fid} | 问题 添加步骤。")

    async def form_step(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        raw = update.message.text.partition(" ")[2]
        if "|" not in raw:
            await update.message.reply_text("用法：/form_step <表单编号> | <问题>")
            return
        fid_s, prompt = (p.strip() for p in raw.split("|", 1))
        if not fid_s.isdigit() or not prompt:
            await update.message.reply_text("⚠️ 表单编号或问题无效。")
            return
        form = self.db.get_form(self.tenant_id, int(fid_s))
        if not form:
            await update.message.reply_text(f"⚠️ 表单 #{fid_s} 不存在。")
            return
        n = self.db.add_form_step(int(fid_s), prompt)
        await update.message.reply_text(f"✅ 已为表单 #{fid_s} 添加第 {n} 步。")

    async def form_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        forms = self.db.get_forms(self.tenant_id)
        if not forms:
            await update.message.reply_text("暂无表单。用 /form_new 创建。")
            return
        out = []
        for f in forms:
            out.append(f"📋 #{f['id']} {f['title']}")
            for s in self.db.get_form_steps(f["id"]):
                out.append(f"　{s['step_number']}. {s['prompt']}")
        await update.message.reply_text("\n".join(out))

    async def form_del(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        if not ctx.args or not ctx.args[0].isdigit():
            await update.message.reply_text("用法：/form_del <表单编号>")
            return
        self.db.delete_form(self.tenant_id, int(ctx.args[0]))
        await update.message.reply_text("✅ 已删除。")

    # ── 用户填写 ────────────────────────────────────────────

    async def cmd_forms(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type != "private" or self._admin(update):
            return
        forms = self.db.get_forms(self.tenant_id)
        if not forms:
            await update.message.reply_text("暂无可填写的表单。")
            return
        rows = [[InlineKeyboardButton(f["title"], callback_data=f"form:{f['id']}")]
                for f in forms]
        await update.message.reply_text(
            "请选择要填写的表单：", reply_markup=InlineKeyboardMarkup(rows))

    async def start_form(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        await q.answer()
        fid   = int(q.data.split(":", 1)[1])
        steps = self.db.get_form_steps(fid)
        if not steps:
            await q.edit_message_text("该表单暂无问题。")
            return
        ctx.user_data["form_state"] = {"form_id": fid, "i": 0, "answers": []}
        await q.edit_message_text(
            f"开始填写。共 {len(steps)} 步，随时可发送 /cancel 取消。\n\n"
            f"1. {steps[0]['prompt']}")

    async def on_answer(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        state = ctx.user_data.get("form_state")
        if not state:
            return  # 未在填写中 → 交给后续处理器（转发等）
        steps = self.db.get_form_steps(state["form_id"])
        state["answers"].append(update.message.text)
        state["i"] += 1

        if state["i"] < len(steps):
            nxt = steps[state["i"]]
            await update.message.reply_text(f"{state['i'] + 1}. {nxt['prompt']}")
            raise ApplicationHandlerStop

        # 完成
        form    = self.db.get_form(self.tenant_id, state["form_id"])
        answers = state["answers"]
        pairs   = [{"q": steps[i]["prompt"], "a": answers[i]} for i in range(len(steps))]
        self.db.save_form_response(
            state["form_id"], self.tenant_id, update.effective_user.id, json.dumps(
                pairs, ensure_ascii=False))
        ctx.user_data.pop("form_state", None)
        await update.message.reply_text("✅ 感谢填写，已提交！")

        u       = update.effective_user
        summary = "\n".join(f"• {p['q']}：{p['a']}" for p in pairs)
        try:
            await ctx.bot.send_message(
                chat_id=self.admin_id,
                text=(f"🗂 *新表单提交*\n表单：{form['title'] if form else state['form_id']}\n"
                      f"用户：{u.full_name} (`{u.id}`)\n\n{summary}"),
                parse_mode="Markdown")
        except Exception as e:
            print(f"[表单] 通知拥有者失败: {e}")
        raise ApplicationHandlerStop

    async def cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if ctx.user_data.pop("form_state", None):
            await update.message.reply_text("已取消填写。")
