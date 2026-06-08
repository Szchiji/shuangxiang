"""数字商店（每个租户机器人各运行一份）。

拥有者用指令维护分类与商品；用户用 /shop 浏览、加入购物车、/cart 结算下单，
下单后通知拥有者。所有数据按 tenant_id 隔离。
"""

import logging

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

logger = logging.getLogger("shuangxiang.store")


class StoreModule(BaseModule):

    def setup(self, app: Application) -> None:
        self.db        = Database()
        self.tenant_id = int(self.config.get("tenant_id", 0))
        self.admin_id  = int(self.config["bot"]["admin_id"])

        # 用户
        app.add_handler(CommandHandler("shop", self.cmd_shop))
        app.add_handler(CommandHandler("cart", self.cmd_cart))
        app.add_handler(CallbackQueryHandler(self.on_click, pattern=r"^shop:"))
        # 拥有者
        app.add_handler(CommandHandler("shop_addcat", self.add_cat))
        app.add_handler(CommandHandler("shop_delcat", self.del_cat))
        app.add_handler(CommandHandler("shop_addproduct", self.add_product))
        app.add_handler(CommandHandler("shop_delproduct", self.del_product))
        app.add_handler(CommandHandler("shop_list", self.shop_list))

    def _admin(self, update: Update) -> bool:
        return update.effective_user.id == self.admin_id

    # ── 拥有者维护 ──────────────────────────────────────────

    async def add_cat(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        name = update.message.text.partition(" ")[2].strip()
        if not name:
            await update.message.reply_text("用法：/shop_addcat <分类名>")
            return
        cid = self.db.add_category(self.tenant_id, name)
        await update.message.reply_text(f"✅ 已添加分类 #{cid}：{name}")

    async def del_cat(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        if not ctx.args or not ctx.args[0].isdigit():
            await update.message.reply_text("用法：/shop_delcat <分类编号>")
            return
        self.db.delete_category(self.tenant_id, int(ctx.args[0]))
        await update.message.reply_text("✅ 已删除分类及其商品。")

    async def add_product(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        raw   = update.message.text.partition(" ")[2]
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 3 or not parts[0].isdigit():
            await update.message.reply_text(
                "用法：/shop_addproduct <分类编号> | <名称> | <价格> | <描述(可选)>")
            return
        cid, name, price_s = int(parts[0]), parts[1], parts[2]
        desc = parts[3] if len(parts) > 3 else ""
        try:
            price = float(price_s)
        except ValueError:
            await update.message.reply_text("⚠️ 价格必须是数字。")
            return
        if not self.db.get_category(self.tenant_id, cid):
            await update.message.reply_text(f"⚠️ 分类 #{cid} 不存在。")
            return
        pid = self.db.add_product(self.tenant_id, cid, name, desc, price)
        await update.message.reply_text(f"✅ 已添加商品 #{pid}：{name} ￥{price:g}")

    async def del_product(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        if not ctx.args or not ctx.args[0].isdigit():
            await update.message.reply_text("用法：/shop_delproduct <商品编号>")
            return
        self.db.delete_product(self.tenant_id, int(ctx.args[0]))
        await update.message.reply_text("✅ 已删除。")

    async def shop_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        cats = self.db.get_categories(self.tenant_id)
        if not cats:
            await update.message.reply_text("暂无分类。用 /shop_addcat 添加。")
            return
        out = []
        for cat in cats:
            out.append(f"{cat['emoji']} #{cat['id']} {cat['name']}")
            for p in self.db.get_products(self.tenant_id, cat["id"]):
                out.append(f"　#{p['id']} {p['name']} ￥{p['price']:g}")
        await update.message.reply_text("\n".join(out))

    # ── 用户浏览 / 购物 ─────────────────────────────────────

    async def cmd_shop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type != "private":
            return
        await update.message.reply_text(*self._cats_view())

    def _cats_view(self):
        cats = self.db.get_categories(self.tenant_id)
        if not cats:
            return ("🛒 商店暂未上架商品。", None)
        rows = [[InlineKeyboardButton(f"{c['emoji']} {c['name']}",
                                      callback_data=f"shop:cat:{c['id']}")] for c in cats]
        return ("🛒 *商店* — 请选择分类：", InlineKeyboardMarkup(rows))

    async def on_click(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        await q.answer()
        parts  = q.data.split(":")
        action = parts[1]

        if action == "cats":
            text, markup = self._cats_view()
            await q.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")

        elif action == "cat":
            cid      = int(parts[2])
            products = self.db.get_products(self.tenant_id, cid)
            if not products:
                await q.edit_message_text(
                    "该分类暂无商品。",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("⬅️ 返回", callback_data="shop:cats")]]))
                return
            rows = [[InlineKeyboardButton(f"{p['name']} ￥{p['price']:g}",
                                          callback_data=f"shop:prod:{p['id']}")]
                    for p in products]
            rows.append([InlineKeyboardButton("⬅️ 返回", callback_data="shop:cats")])
            await q.edit_message_text("请选择商品：", reply_markup=InlineKeyboardMarkup(rows))

        elif action == "prod":
            pid = int(parts[2])
            p   = self.db.get_product(self.tenant_id, pid)
            if not p:
                await q.edit_message_text("商品不存在。")
                return
            rows = [
                [InlineKeyboardButton("➕ 加入购物车", callback_data=f"shop:add:{pid}")],
                [InlineKeyboardButton("⬅️ 返回", callback_data=f"shop:cat:{p['category_id']}")],
            ]
            await q.edit_message_text(
                f"*{p['name']}*\n价格：￥{p['price']:g}\n\n{p['description'] or ''}",
                reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

        elif action == "add":
            pid = int(parts[2])
            if self.db.get_product(self.tenant_id, pid):
                self.db.add_to_cart(self.tenant_id, q.from_user.id, pid)
                await q.answer("已加入购物车 ✅", show_alert=False)

        elif action == "clear":
            self.db.clear_cart(self.tenant_id, q.from_user.id)
            await q.edit_message_text("🗑 购物车已清空。")

        elif action == "checkout":
            await self._checkout(q, ctx)

    async def cmd_cart(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type != "private":
            return
        text, markup = self._cart_view(update.effective_user.id)
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

    def _cart_view(self, user_id: int):
        items = self.db.get_cart(self.tenant_id, user_id)
        if not items:
            return ("🛒 购物车是空的。用 /shop 选购吧。", None)
        lines = [f"• {i['name']} ×{i['quantity']} = ￥{i['price'] * i['quantity']:g}"
                 for i in items]
        total = sum(i["price"] * i["quantity"] for i in items)
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ 结算下单", callback_data="shop:checkout")],
            [InlineKeyboardButton("🗑 清空", callback_data="shop:clear")],
        ])
        return ("🛒 *购物车*\n\n" + "\n".join(lines) + f"\n\n合计：￥{total:g}", markup)

    async def _checkout(self, q, ctx) -> None:
        user_id = q.from_user.id
        items   = self.db.get_cart(self.tenant_id, user_id)
        if not items:
            await q.edit_message_text("🛒 购物车是空的。")
            return
        oid   = self.db.create_order(self.tenant_id, user_id, items)
        order = self.db.get_order(self.tenant_id, oid)
        self.db.clear_cart(self.tenant_id, user_id)
        await q.edit_message_text(
            f"✅ 下单成功！订单号 #{oid}，合计 ￥{order['total']:g}。\n管理员会尽快与您联系。")
        try:
            lines = "\n".join(
                f"• {i['name']} ×{i['quantity']}" for i in items)
            await ctx.bot.send_message(
                chat_id=self.admin_id,
                text=(f"🧾 *新订单* #{oid}\n用户：{q.from_user.full_name} (`{user_id}`)\n"
                      f"合计：￥{order['total']:g}\n\n{lines}"),
                parse_mode="Markdown")
        except TelegramError as e:
            logger.warning("通知拥有者失败: %s", e)
