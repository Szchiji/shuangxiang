from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from core.base_module import BaseModule
from core.database import Database
from core.permissions import Role, require_role


class SchedulerModule(BaseModule):
    """定时广播任务模块"""

    def setup(self, app: Application) -> None:
        self.db = Database()
        app.add_handler(CommandHandler("addschedule",    self.cmd_add))
        app.add_handler(CommandHandler("listschedules",  self.cmd_list))
        app.add_handler(CommandHandler("delschedule",    self.cmd_del))

        # 恢复已有任务
        for sched in self.db.get_active_schedules():
            self._register_job(app, sched["id"], sched["content"], sched["interval_s"])

    def _register_job(self, app, sid, content, interval_s):
        try:
            app.job_queue.run_repeating(
                callback=self._make_job(content),
                interval=interval_s,
                first=interval_s,
                name=f"sched_{sid}",
            )
        except Exception as e:
            print(f"[Scheduler] 任务 #{sid} 注册失败：{e}")

    def _make_job(self, content):
        async def job(ctx):
            users = self.db.get_all_users()
            for u in users:
                try:
                    await ctx.bot.send_message(chat_id=u["id"], text=content)
                except Exception:
                    pass
        return job

    @require_role(Role.ADMIN)
    async def cmd_add(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if len(ctx.args) < 2:
            await update.message.reply_text(
                "用法：`/addschedule <间隔秒数> <消息内容>`\n\n"
                "例如：`/addschedule 3600 每小时提醒`",
                parse_mode="Markdown")
            return
        try:
            interval_s = int(ctx.args[0])
        except ValueError:
            await update.message.reply_text("❌ 间隔秒数必须是整数")
            return
        content = " ".join(ctx.args[1:])
        sid     = self.db.add_schedule(content, interval_s)
        self._register_job(ctx.application, sid, content, interval_s)
        await update.message.reply_text(
            f"✅ 定时任务 `#{sid}` 已添加\n\n"
            f"⏱ 间隔：每 {interval_s} 秒\n"
            f"💬 内容：{content}",
            parse_mode="Markdown")

    @require_role(Role.ADMIN)
    async def cmd_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        scheds = self.db.get_active_schedules()
        if not scheds:
            await update.message.reply_text("📭 暂无定时任务")
            return
        lines = ["⏱ *定时任务列表*\n"]
        for s in scheds:
            lines.append(f"`#{s['id']}` 每 {s['interval_s']}s — {s['content'][:40]}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    @require_role(Role.ADMIN)
    async def cmd_del(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：`/delschedule <任务ID>`", parse_mode="Markdown")
            return
        sid = int(ctx.args[0])
        self.db.delete_schedule(sid)
        # 移除 job_queue 中的任务
        jobs = ctx.application.job_queue.get_jobs_by_name(f"sched_{sid}")
        for job in jobs:
            job.schedule_removal()
        await update.message.reply_text(f"✅ 任务 `#{sid}` 已删除", parse_mode="Markdown")
