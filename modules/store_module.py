import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from core.base_module import BaseModule
from core.database import Database


class StoreModule(BaseModule):
    """数字商店模块：分类浏览 / 购物车 / 结账"""

    def setup(self, app: Application) -> None:
        self.db        = Database()
        self.tenant_id = self.config.get("tenant_id")
        app.add_handler(CommandHandler("shop",   self.cmd_shop))
        app.add_handler(CommandHandler("cart",   self.cmd_cart))
        app.add_handler(CommandHandler("orders", self.cmd_orders))
        app.add_handler(CallbackQueryHandler(self.on_callback, pattern=r"^shop:"))

    # ── 主入口 ────────────────────────────────────────────────

    async def cmd_shop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        cats = self.db.get_categories(self.tenant_id)
        if not cats:
            await update.message.reply_text("🏪 商店暂无商品，敬请期待！")
            return
        kb = [[InlineKeyboardButton(f"{c['emoji']} {c['name']}",
               callback_data=f"shop:cat:{c['id']}:1")] for c in cats]
        await update.message.reply_text(
            "🏪 *欢迎来到商店*\n\n请选择分类：",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown")

    # ── 购物车 ────────────────────────────────────────────────

    async def cmd_cart(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid   = update.effective_user.id
        items = self.db.get_cart_items(uid, self.tenant_id)
        await update.message.reply_text(
            *self._cart_text_kb(items), parse_mode="Markdown")

    def _cart_text_kb(self, items):
        if not items:
            return "🛒 购物车为空", None
        total = sum(i["price"] * i["quantity"] for i in items)
        lines = ["🛒 *您的购物车*\n"]
        for i in items:
            lines.append(f"• {i['name']} x{i['quantity']} — ¥{i['price'] * i['quantity']:.2f}")
        lines.append(f"\n💰 合计：¥{total:.2f}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ 结账", callback_data="shop:checkout"),
             InlineKeyboardButton("🗑 清空", callback_data="shop:clearcart")],
        ])
        return "\n".join(lines), kb

    # ── 订单 ─────────────────────────────────────────────────

    async def cmd_orders(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid    = update.effective_user.id
        orders = self.db.get_orders(user_id=uid, tenant_id=self.tenant_id, limit=10)
        if not orders:
            await update.message.reply_text("📦 您还没有订单")
            return
        lines = ["📦 *您的订单（最近 10 条）*\n"]
        for o in orders:
            status_map = {"pending": "⏳", "paid": "✅", "cancelled": "❌", "shipped": "🚚"}
            icon = status_map.get(o["status"], "❓")
            lines.append(f"`#{o['id']}` {icon} ¥{o['total']:.2f} — {o['created_at'][:10]}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # ── Callback 分发 ─────────────────────────────────────────

    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q    = update.callback_query
        data = q.data
        await q.answer()
        parts = data.split(":")
        action = parts[1]

        if action == "cat":
            await self._show_products(q, int(parts[2]), int(parts[3]))
        elif action == "product":
            await self._show_product(q, int(parts[2]))
        elif action == "addcart":
            await self._add_to_cart(q, int(parts[2]))
        elif action == "checkout":
            await self._checkout(q)
        elif action == "clearcart":
            self.db.clear_cart(q.from_user.id, self.tenant_id)
            await q.edit_message_text("🗑 购物车已清空")
        elif action == "back_cats":
            await self.cmd_shop.__wrapped__(self, update, ctx) if hasattr(self.cmd_shop, '__wrapped__') else await self._back_to_cats(q)

    async def _show_products(self, q, cat_id, page):
        cat   = self.db.get_category(cat_id)
        rows, total = self.db.get_products(cat_id, self.tenant_id, page)
        if not rows:
            await q.edit_message_text("📭 该分类暂无商品")
            return
        per_page = 5
        pages    = (total + per_page - 1) // per_page
        kb_rows  = [[InlineKeyboardButton(
            f"{p['name']} — ¥{p['price']:.2f}",
            callback_data=f"shop:product:{p['id']}")] for p in rows]
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"shop:cat:{cat_id}:{page-1}"))
        if page < pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"shop:cat:{cat_id}:{page+1}"))
        if nav:
            kb_rows.append(nav)
        kb_rows.append([InlineKeyboardButton("⬅️ 返回分类", callback_data="shop:back_cats")])
        await q.edit_message_text(
            f"{cat['emoji']} *{cat['name']}*\n共 {total} 件商品（第 {page}/{pages} 页）",
            reply_markup=InlineKeyboardMarkup(kb_rows),
            parse_mode="Markdown")

    async def _show_product(self, q, pid):
        p = self.db.get_product(pid)
        if not p:
            await q.edit_message_text("❌ 商品不存在")
            return
        stock_txt = "有货" if p["stock"] == -1 else (f"库存 {p['stock']}" if p["stock"] > 0 else "售罄")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🛒 加入购物车", callback_data=f"shop:addcart:{pid}"),
            InlineKeyboardButton("⬅️ 返回",     callback_data=f"shop:cat:{p['category_id']}:1"),
        ]])
        await q.edit_message_text(
            f"📦 *{p['name']}*\n\n{p['description'] or ''}\n\n"
            f"💰 价格：¥{p['price']:.2f}\n📊 {stock_txt}",
            reply_markup=kb, parse_mode="Markdown")

    async def _add_to_cart(self, q, pid):
        uid = q.from_user.id
        p   = self.db.get_product(pid)
        if not p:
            await q.answer("❌ 商品不存在", show_alert=True)
            return
        if p["stock"] == 0:
            await q.answer("❌ 商品已售罄", show_alert=True)
            return
        self.db.add_to_cart(uid, pid, self.tenant_id)
        await q.answer(f"✅ {p['name']} 已加入购物车")

    async def _checkout(self, q):
        uid   = q.from_user.id
        items = self.db.get_cart_items(uid, self.tenant_id)
        if not items:
            await q.answer("购物车为空", show_alert=True)
            return
        order_items = [{"product_id": i["product_id"],
                        "quantity":   i["quantity"],
                        "price":      i["price"]} for i in items]
        oid = self.db.create_order(uid, self.tenant_id, order_items)
        self.db.clear_cart(uid, self.tenant_id)
        total = sum(i["price"] * i["quantity"] for i in items)
        await q.edit_message_text(
            f"✅ *订单已提交！*\n\n"
            f"🆔 订单号：`#{oid}`\n💰 总计：¥{total:.2f}\n\n"
            f"感谢您的购买！管理员会尽快处理。",
            parse_mode="Markdown")

    async def _back_to_cats(self, q):
        cats = self.db.get_categories(self.tenant_id)
        kb   = [[InlineKeyboardButton(f"{c['emoji']} {c['name']}",
                 callback_data=f"shop:cat:{c['id']}:1")] for c in cats]
        await q.edit_message_text(
            "🏪 *欢迎来到商店*\n\n请选择分类：",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown")
