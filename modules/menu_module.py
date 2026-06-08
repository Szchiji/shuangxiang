"""菜单 / 子菜单构建器（每个租户机器人各运行一份）。

拥有者用指令逐步搭建多级菜单；用户用 /menu 浏览（内联按钮，可进入子菜单）。

菜单项存于 menu_items：parent_id=0 表示根菜单项，其余指向父项 id。
点击有子项的菜单 → 展开子菜单；点击无子项的菜单 → 显示其内容。
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from core.base_module import BaseModule
from core.database import Database


class MenuModule(BaseModule):

    def setup(self, app: Application) -> None:
        self.db        = Database()
        self.tenant_id = int(self.config.get("tenant_id", 0))
        self.admin_id  = int(self.config["bot"]["admin_id"])

        app.add_handler(CommandHandler("menu", self.cmd_menu))
        app.add_handler(CommandHandler("menu_add", self.menu_add))
        app.add_handler(CommandHandler("menu_list", self.menu_list))
        app.add_handler(CommandHandler("menu_del", self.menu_del))
        app.add_handler(CallbackQueryHandler(self.on_click, pattern=r"^menu:"))

    def _admin(self, update: Update) -> bool:
        return update.effective_user.id == self.admin_id

    # ── 用户浏览 ────────────────────────────────────────────

    async def cmd_menu(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type != "private":
            return
        text, markup = self._render(0)
        await update.message.reply_text(text, reply_markup=markup)

    async def on_click(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        await q.answer()
        item_id = int(q.data.split(":", 1)[1])
        text, markup = self._render(item_id)
        try:
            await q.edit_message_text(text, reply_markup=markup)
        except TelegramError:
            await q.message.reply_text(text, reply_markup=markup)

    def _render(self, item_id: int):
        """返回 (文本, 内联键盘)。item_id=0 表示根菜单。"""
        children = self.db.get_menu_children(self.tenant_id, item_id)
        if item_id == 0:
            title = "📋 菜单"
        else:
            node  = self.db.get_menu_item(self.tenant_id, item_id)
            title = (node["content"] or node["label"]) if node else "菜单"

        rows = [[InlineKeyboardButton(ch["label"], callback_data=f"menu:{ch['id']}")]
                for ch in children]
        if item_id != 0:
            node = self.db.get_menu_item(self.tenant_id, item_id)
            parent = node["parent_id"] if node else 0
            rows.append([InlineKeyboardButton("⬅️ 返回", callback_data=f"menu:{parent}")])
        markup = InlineKeyboardMarkup(rows) if rows else None
        if not children and item_id == 0:
            title = "📋 菜单为空。拥有者可用 /menu_add 添加。"
        return title, markup

    # ── 拥有者构建 ──────────────────────────────────────────

    async def menu_add(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        raw   = update.message.text.partition(" ")[2]
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 2 or not parts[0].lstrip("-").isdigit():
            await update.message.reply_text(
                "用法：/menu_add <父项编号> | <按钮文字> | <内容(可选)>\n"
                "父项编号 0 表示根菜单。例如：/menu_add 0 | 关于我们 | 我们成立于 2020 年。")
            return
        parent_id = int(parts[0])
        label     = parts[1]
        content   = parts[2] if len(parts) > 2 else ""
        if not label:
            await update.message.reply_text("⚠️ 按钮文字不能为空。")
            return
        if parent_id != 0 and not self.db.get_menu_item(self.tenant_id, parent_id):
            await update.message.reply_text(f"⚠️ 父项 #{parent_id} 不存在。")
            return
        mid = self.db.add_menu_item(self.tenant_id, parent_id, label, content)
        await update.message.reply_text(f"✅ 已添加菜单项 #{mid}：{label}")

    async def menu_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        lines: list[str] = []
        self._walk(0, 0, lines)
        await update.message.reply_text(
            "🌳 菜单结构：\n" + ("\n".join(lines) if lines else "（空）"))

    def _walk(self, parent_id: int, depth: int, out: list[str]) -> None:
        for ch in self.db.get_menu_children(self.tenant_id, parent_id):
            out.append(f"{'　' * depth}#{ch['id']} {ch['label']}")
            self._walk(ch["id"], depth + 1, out)

    async def menu_del(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        if not ctx.args or not ctx.args[0].isdigit():
            await update.message.reply_text("用法：/menu_del <编号>")
            return
        self.db.delete_menu_item(self.tenant_id, int(ctx.args[0]))
        await update.message.reply_text("✅ 已删除（其子项仍保留，可单独删除）。")
