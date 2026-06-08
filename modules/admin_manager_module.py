from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from core.base_module import BaseModule
from core.database import Database
from core.permissions import Role, require_role, get_role_from_config_or_db


class AdminManagerModule(BaseModule):

    _ROLE_ALIAS = {
        "mod":       Role.MODERATOR,
        "moderator": Role.MODERATOR,
        "群管":      Role.MODERATOR,
        "admin":     Role.ADMIN,
        "管理员":    Role.ADMIN,
    }

    def setup(self, app: Application) -> None:
        self.db = Database()
        for cmd, handler in [
            ("addadmin",    self.cmd_add_admin),
            ("removeadmin", self.cmd_remove_admin),
            ("promote",     self.cmd_promote),
            ("demote",      self.cmd_demote),
            ("admins",      self.cmd_list_admins),
            ("myrole",      self.cmd_my_role),
        ]:
            app.add_handler(CommandHandler(cmd, handler))

    @require_role(Role.SUPER_ADMIN)
    async def cmd_add_admin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text(
                "用法：`/addadmin <用户ID> [mod|admin] [备注]`",
                parse_mode="Markdown")
            return
        uid  = int(ctx.args[0])
        role = self._ROLE_ALIAS.get(ctx.args[1].lower(), Role.MODERATOR) if len(ctx.args) > 1 else Role.MODERATOR
        note = " ".join(ctx.args[2:]) if len(ctx.args) > 2 else ""
        if uid == self.config["bot"]["admin_id"]:
            await update.message.reply_text("⚠️ 超级管理员由配置文件控制，无需添加。")
            return
        self.db.add_admin(uid, int(role), update.effective_user.id, note)
        await update.message.reply_text(
            f"✅ *管理员添加成功*\n\n🆔 用户 ID：`{uid}`\n🎖️ 权限：{role.label}\n📝 备注：{note or '无'}",
            parse_mode="Markdown")

    @require_role(Role.SUPER_ADMIN)
    async def cmd_remove_admin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：`/removeadmin <用户ID>`", parse_mode="Markdown")
            return
        uid = int(ctx.args[0])
        if uid == self.config["bot"]["admin_id"]:
            await update.message.reply_text("⚠️ 无法移除超级管理员。")
            return
        self.db.remove_admin(uid)
        await update.message.reply_text(f"✅ 用户 `{uid}` 的管理员权限已撤销。", parse_mode="Markdown")

    @require_role(Role.SUPER_ADMIN)
    async def cmd_promote(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：`/promote <用户ID>`", parse_mode="Markdown")
            return
        uid       = int(ctx.args[0])
        curr_role = Role(self.db.get_admin_role(uid))
        if curr_role >= Role.ADMIN:
            await update.message.reply_text(f"⚠️ 该用户已经是 {curr_role.label}，无法继续升级。")
            return
        if curr_role == Role.USER:
            await update.message.reply_text("⚠️ 该用户还不是管理员，请先用 /addadmin 添加。")
            return
        new_role = Role(int(curr_role) + 1)
        self.db.update_admin_role(uid, int(new_role))
        await update.message.reply_text(
            f"⬆️ 用户 `{uid}` 权限已升级：\n{curr_role.label} → {new_role.label}",
            parse_mode="Markdown")

    @require_role(Role.SUPER_ADMIN)
    async def cmd_demote(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("用法：`/demote <用户ID>`", parse_mode="Markdown")
            return
        uid       = int(ctx.args[0])
        curr_role = Role(self.db.get_admin_role(uid))
        if curr_role <= Role.USER:
            await update.message.reply_text("⚠️ 该用户没有管理员权限。")
            return
        if curr_role == Role.MODERATOR:
            await update.message.reply_text("⚠️ 已是最低管理等级，如需撤权请用 /removeadmin。")
            return
        new_role = Role(int(curr_role) - 1)
        self.db.update_admin_role(uid, int(new_role))
        await update.message.reply_text(
            f"⬇️ 用户 `{uid}` 权限已降级：\n{curr_role.label} → {new_role.label}",
            parse_mode="Markdown")

    @require_role(Role.ADMIN)
    async def cmd_list_admins(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        super_admin_id = self.config["bot"]["admin_id"]
        rows           = self.db.get_all_admins()
        lines = ["👑 *管理员列表*\n", f"🔴 `{super_admin_id}` — *超级管理员*（配置文件）"]
        for r in rows:
            role  = Role(r["role"])
            name  = r["full_name"] or "未知"
            uname = f"@{r['username']}" if r["username"] else "N/A"
            note  = f"  _{r['note']}_" if r["note"] else ""
            lines.append(f"{role.label} `{r['id']}` {name} ({uname}){note}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def cmd_my_role(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid  = update.effective_user.id
        role = get_role_from_config_or_db(uid, self.config["bot"]["admin_id"])
        perms = {
            Role.SUPER_ADMIN: "✅ 全部权限，含管理其他管理员",
            Role.ADMIN:       "✅ 用户管理 / 广播 / 历史记录 / 定时任务",
            Role.MODERATOR:   "✅ 群内踢人 / 禁言 / 警告",
            Role.USER:        "✅ 发送消息 / 查看菜单",
        }
        await update.message.reply_text(
            f"🎖️ *您的权限信息*\n\n等级：{role.label}\n权限：{perms[role]}",
            parse_mode="Markdown")
