"""租户机器人交互式自定义模块（每个租户机器人各运行一份）。

通过「按钮 + 引导式输入」让拥有者无需记忆指令即可：
  • 自定义启动语（/start 欢迎消息）并附带内联按钮（链接按钮）。
  • 新增带内联按钮的自动回复。
  • 配置「强制订阅频道」：未加入指定频道的用户消息会被拦截，并提示加入。
  • 群发广播：把一条消息一次性发送给全部用户。

所有编辑流程都以会话状态 ``ctx.user_data["cz"]`` 驱动，由 group=-3 的处理器
优先捕获拥有者的下一条输入；强制订阅的拦截器注册在 group=-1，先于双向转发执行。
"""

import asyncio
import json
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.base_module import BaseModule
from core.database import Database

logger = logging.getLogger("shuangxiang.customize")

# 设置键（存于 tenant_kv）
SK_WELCOME_TEXT = "welcome_text"      # 自定义启动语文本
SK_WELCOME_BTNS = "welcome_buttons"   # 启动语内联按钮（JSON）
SK_FORCE_SUB    = "force_sub"          # 强制订阅频道列表（JSON）
SK_FORCE_SUB_ON = "force_sub_on"       # 强制订阅总开关

_JOINED_STATUSES = ("member", "administrator", "creator", "owner")


# ── 按钮序列化 / 解析（供其它模块复用）──────────────────────

def parse_buttons(text: str) -> list[list[dict]]:
    """把多行文本解析为按钮行。每行一个链接按钮，格式：``文字 - 链接``。

    分隔符支持 ``-``、``|``、``：``、``:``。仅接受 http(s):// 或 tg:// 链接。
    返回形如 ``[[{"text":..,"url":..}], ...]`` 的按钮行列表。
    """
    rows: list[list[dict]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        label, sep, url = _split_button_line(line)
        url = url.strip()
        if not sep or not label.strip() or not _valid_url(url):
            continue
        rows.append([{"text": label.strip(), "url": url}])
    return rows


def _split_button_line(line: str):
    for sep in (" - ", " | ", "|", "：", ":"):
        if sep in line:
            label, _, url = line.partition(sep)
            return label, sep, url
    return line, "", ""


def _valid_url(url: str) -> bool:
    return url.startswith(("http://", "https://", "tg://"))


def rows_to_keyboard(rows) -> list[list[InlineKeyboardButton]]:
    """把存储的按钮行（list[list[dict]]）转换为 InlineKeyboardButton 行。"""
    keyboard: list[list[InlineKeyboardButton]] = []
    for row in rows or []:
        buttons = [InlineKeyboardButton(b["text"], url=b["url"])
                   for b in row if b.get("text") and b.get("url")]
        if buttons:
            keyboard.append(buttons)
    return keyboard


def load_button_rows(db: Database, tenant_id: int, key: str):
    """从设置中读取按钮行并转换为 InlineKeyboardButton 行（失败返回空）。"""
    raw = db.get_setting(tenant_id, key, "")
    if not raw:
        return []
    try:
        return rows_to_keyboard(json.loads(raw))
    except (ValueError, TypeError, KeyError):
        return []


class CustomizeModule(BaseModule):

    def setup(self, app: Application) -> None:
        self.db        = Database()
        self.tenant_id = int(self.config.get("tenant_id", 0))
        self.admin_id  = int(self.config["bot"]["admin_id"])

        app.add_handler(CommandHandler("settings", self.cmd_settings))
        app.add_handler(CommandHandler("broadcast", self.cmd_broadcast))
        app.add_handler(CommandHandler("cancel", self.cmd_cancel), group=-3)
        app.add_handler(CallbackQueryHandler(self.on_cb, pattern=r"^cz:"))
        # 拥有者引导式输入：最高优先级，先于表单(-2)与转发(5)。
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND, self.on_wizard), group=-3)
        # 强制订阅拦截：先于双向转发(5)。放在 group=-1。
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND, self.on_guard), group=-1)

    def _admin(self, uid: int) -> bool:
        return uid == self.admin_id

    # ── 设置面板 ────────────────────────────────────────────

    def _settings_markup(self) -> InlineKeyboardMarkup:
        fsub_on = self.db.get_bool_setting(self.tenant_id, SK_FORCE_SUB_ON, False)
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ 启动语", callback_data="cz:welcome")],
            [InlineKeyboardButton("💬 自动回复（带按钮）", callback_data="cz:ar")],
            [InlineKeyboardButton(
                f"📢 强制订阅：{'✅ 开' if fsub_on else '⛔ 关'}",
                callback_data="cz:fsub")],
            [InlineKeyboardButton("📣 群发广播", callback_data="cz:bc")],
            [InlineKeyboardButton("🏠 控制面板", callback_data="pc:home")],
        ])

    @staticmethod
    def _settings_text() -> str:
        return ("🎛 *高级设置*\n\n"
                "点击下方按钮即可自定义机器人，全程按提示操作，无需记忆指令。")

    async def cmd_settings(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update.effective_user.id):
            return
        if update.effective_chat.type != "private":
            return
        await update.effective_message.reply_text(
            self._settings_text(), parse_mode="Markdown",
            reply_markup=self._settings_markup())

    async def cmd_broadcast(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update.effective_user.id):
            return
        if update.effective_chat.type != "private":
            return
        ctx.user_data["cz"] = {"flow": "bc"}
        await update.effective_message.reply_text(
            "📣 *群发广播*\n\n请发送要广播的内容（文字 / 图片 / 视频均可）。\n\n"
            "发送后会先让你确认。发送 /cancel 取消。",
            parse_mode="Markdown")

    async def cmd_cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if ctx.user_data.pop("cz", None) is not None:
            await update.effective_message.reply_text("已取消当前操作。")

    # ── 回调分发 ────────────────────────────────────────────

    async def on_cb(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        action = q.data.split(":", 1)[1]

        # 公开：用户「我已订阅」复核
        if action == "checksub":
            await self._on_checksub(q, ctx)
            return

        if not self._admin(q.from_user.id):
            await q.answer("仅机器人拥有者可用。", show_alert=True)
            return

        handler = {
            "home":        self._show_home,
            "welcome":     self._show_welcome,
            "welcome:text": self._start_welcome,
            "wbtns":       self._show_welcome,
            "wbtns:edit":  self._start_wbtns,
            "wbtns:clear": self._clear_wbtns,
            "ar":          self._show_ar,
            "ar:add":      self._start_ar,
            "fsub":        self._show_fsub,
            "fsub:toggle": self._toggle_fsub,
            "fsub:add":    self._start_fsub,
            "bc":          self._start_bc,
            "bc:send":     self._send_bc,
            "bc:cancel":   self._cancel_bc,
            "cancel":      self._cancel_wizard,
        }.get(action)
        if handler is not None:
            await handler(q, ctx)
            return
        if action.startswith("ar:mt:"):
            await self._pick_ar_match(q, ctx, action.rsplit(":", 1)[1])
        elif action.startswith("ar:del:"):
            await self._del_ar(q, ctx, int(action.rsplit(":", 1)[1]))
        elif action.startswith("fsub:del:"):
            await self._del_fsub(q, ctx, int(action.rsplit(":", 1)[1]))
        else:
            await q.answer()

    def _back_markup(self):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ 返回设置", callback_data="cz:home")],
            [InlineKeyboardButton("🏠 控制面板", callback_data="pc:home")],
        ])

    def _welcome_back_markup(self):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ 启动语设置", callback_data="cz:welcome")],
            [InlineKeyboardButton("🏠 控制面板", callback_data="pc:home")],
        ])

    async def _show_home(self, q, ctx) -> None:
        ctx.user_data.pop("cz", None)
        await q.answer()
        await q.edit_message_text(
            self._settings_text(), parse_mode="Markdown",
            reply_markup=self._settings_markup())

    # ── 启动语（文本 + 按钮，统一管理）──────────────────────

    async def _show_welcome(self, q, ctx) -> None:
        ctx.user_data.pop("cz", None)
        await q.answer()
        cur = self.db.get_setting(self.tenant_id, SK_WELCOME_TEXT, "") or "（未设置，使用默认）"
        rows = load_button_rows(self.db, self.tenant_id, SK_WELCOME_BTNS)
        btns = "、".join(b.text for row in rows for b in row) or "（无）"
        await q.edit_message_text(
            "✏️ *启动语*\n\n启动语文本与启动按钮在此统一设置，"
            "它们会一起显示在用户的 /start 启动信息中。\n\n"
            f"当前启动语：\n{cur}\n\n当前按钮：{btns}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ 编辑启动语", callback_data="cz:welcome:text")],
                [InlineKeyboardButton("🔘 编辑按钮", callback_data="cz:wbtns:edit"),
                 InlineKeyboardButton("🗑 清空按钮", callback_data="cz:wbtns:clear")],
                [InlineKeyboardButton("⬅️ 返回设置", callback_data="cz:home")],
                [InlineKeyboardButton("🏠 控制面板", callback_data="pc:home")],
            ]))

    async def _start_welcome(self, q, ctx) -> None:
        ctx.user_data["cz"] = {"flow": "welcome"}
        cur = self.db.get_setting(self.tenant_id, SK_WELCOME_TEXT, "") or "（未设置，使用默认）"
        await q.answer()
        await q.edit_message_text(
            "✏️ *自定义启动语*\n\n请发送新的欢迎语文本。\n\n"
            f"当前：\n{cur}\n\n发送 /cancel 取消。",
            parse_mode="Markdown")

    async def _start_wbtns(self, q, ctx) -> None:
        ctx.user_data["cz"] = {"flow": "wbtns"}
        await q.answer()
        await q.edit_message_text(
            "🔘 *设置启动按钮*\n\n每行一个按钮，格式：\n`按钮文字 - 链接`\n\n"
            "例如：\n`官方频道 - https://t.me/yourchannel`\n`联系客服 - https://t.me/yourname`\n\n"
            "发送 /cancel 取消。",
            parse_mode="Markdown")

    async def _clear_wbtns(self, q, ctx) -> None:
        self.db.set_setting(self.tenant_id, SK_WELCOME_BTNS, "")
        await q.answer("已清空启动按钮")
        await self._show_welcome(q, ctx)

    # ── 自动回复（带按钮）──────────────────────────────────

    async def _show_ar(self, q, ctx) -> None:
        await q.answer()
        rows = self.db.get_auto_replies(self.tenant_id)
        lines, kb = [], []
        for r in rows:
            tag = " [拦截]" if r["stop"] else ""
            mt = (r["match_type"] if "match_type" in r.keys() else "") or "contains"
            mt_tag = " [正则]" if mt == "regex" else ""
            has_btn = " 🔘" if (r["buttons"] or "") else ""
            lines.append(f"#{r['id']} 「{r['keyword']}」{mt_tag}{tag}{has_btn}")
            kb.append([InlineKeyboardButton(
                f"🗑 删除 #{r['id']}", callback_data=f"cz:ar:del:{r['id']}")])
        kb.append([InlineKeyboardButton("➕ 新增自动回复", callback_data="cz:ar:add")])
        kb.append([InlineKeyboardButton("⬅️ 返回设置", callback_data="cz:home"),
                   InlineKeyboardButton("🏠 控制面板", callback_data="pc:home")])
        await q.edit_message_text(
            "💬 *自动回复*\n\n" + ("\n".join(lines) if lines else "（暂无）"),
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    async def _start_ar(self, q, ctx) -> None:
        ctx.user_data["cz"] = {"flow": "ar", "step": "keyword", "buf": {}}
        await q.answer()
        await q.edit_message_text(
            "➕ *新增自动回复*（第 1/4 步）\n\n请发送要匹配的*关键词*。\n\n发送 /cancel 取消。",
            parse_mode="Markdown")

    async def _pick_ar_match(self, q, ctx, match_type: str) -> None:
        """向导第 2/4 步：选择匹配方式（包含 / 正则）。"""
        state = ctx.user_data.get("cz")
        if not state or state.get("flow") != "ar" or state.get("step") != "match":
            await q.answer()
            return
        buf = state.setdefault("buf", {})
        if match_type == "regex":
            try:
                re.compile(buf.get("keyword", ""))
            except re.error:
                await q.answer(
                    "⚠️ 该关键词不是合法的正则表达式，请改用包含匹配或发送 /cancel 重来。",
                    show_alert=True)
                return
        buf["match_type"] = match_type
        state["step"] = "reply"
        await q.answer()
        label = "正则匹配" if match_type == "regex" else "包含匹配"
        await q.edit_message_text(
            f"匹配方式：*{label}*\n\n（第 3/4 步）请发送命中后要*自动回复的文本*。",
            parse_mode="Markdown")

    async def _del_ar(self, q, ctx, rid: int) -> None:
        self.db.delete_auto_reply(self.tenant_id, rid)
        await q.answer("已删除")
        await self._show_ar(q, ctx)

    # ── 强制订阅 ────────────────────────────────────────────

    def _load_fsub(self):
        raw = self.db.get_setting(self.tenant_id, SK_FORCE_SUB, "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except ValueError:
            return []

    def _save_fsub(self, channels) -> None:
        self.db.set_setting(self.tenant_id, SK_FORCE_SUB,
                            json.dumps(channels, ensure_ascii=False))

    async def _show_fsub(self, q, ctx) -> None:
        await q.answer()
        on = self.db.get_bool_setting(self.tenant_id, SK_FORCE_SUB_ON, False)
        channels = self._load_fsub()
        kb = []
        for i, ch in enumerate(channels):
            kb.append([InlineKeyboardButton(
                f"🗑 {ch.get('title') or ch.get('chat')}",
                callback_data=f"cz:fsub:del:{i}")])
        kb.append([InlineKeyboardButton(
            f"{'⛔ 关闭' if on else '✅ 开启'}强制订阅", callback_data="cz:fsub:toggle")])
        kb.append([InlineKeyboardButton("➕ 添加频道", callback_data="cz:fsub:add")])
        kb.append([InlineKeyboardButton("⬅️ 返回设置", callback_data="cz:home"),
                   InlineKeyboardButton("🏠 控制面板", callback_data="pc:home")])
        await q.edit_message_text(
            "📢 *强制订阅*\n\n"
            f"状态：{'✅ 已开启' if on else '⛔ 已关闭'}\n"
            f"频道数：{len(channels)}\n\n"
            "开启后，未加入下列频道的用户消息会被拦截并提示加入。\n"
            "⚠️ 需先把本机器人设为各频道的管理员，否则无法校验。",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    async def _toggle_fsub(self, q, ctx) -> None:
        cur = self.db.get_bool_setting(self.tenant_id, SK_FORCE_SUB_ON, False)
        self.db.set_setting(self.tenant_id, SK_FORCE_SUB_ON, "0" if cur else "1")
        await q.answer("已" + ("关闭" if cur else "开启"))
        await self._show_fsub(q, ctx)

    async def _start_fsub(self, q, ctx) -> None:
        ctx.user_data["cz"] = {"flow": "fsub"}
        await q.answer()
        await q.edit_message_text(
            "➕ *添加强制订阅频道*\n\n请按以下格式发送（每行一个频道）：\n"
            "`名称 | @频道用户名 | 加入链接`\n\n"
            "公开频道示例：\n`官方频道 | @mychannel | https://t.me/mychannel`\n\n"
            "私有频道可用 `-100` 开头的数字 ID 代替 @用户名，并填写邀请链接。\n\n"
            "发送 /cancel 取消。",
            parse_mode="Markdown")

    async def _del_fsub(self, q, ctx, idx: int) -> None:
        channels = self._load_fsub()
        if 0 <= idx < len(channels):
            channels.pop(idx)
            self._save_fsub(channels)
        await q.answer("已删除")
        await self._show_fsub(q, ctx)

    # ── 群发广播 ────────────────────────────────────────────

    async def _start_bc(self, q, ctx) -> None:
        ctx.user_data["cz"] = {"flow": "bc"}
        await q.answer()
        await q.edit_message_text(
            "📣 *群发广播*\n\n请发送要广播的内容（文字 / 图片 / 视频均可）。\n\n"
            "发送后会先让你确认。发送 /cancel 取消。",
            parse_mode="Markdown")

    async def _send_bc(self, q, ctx) -> None:
        st = ctx.user_data.get("cz") or {}
        src = st.get("bc")
        ctx.user_data.pop("cz", None)
        await q.answer()
        if not src:
            await q.edit_message_text("⚠️ 没有待发送的内容。", reply_markup=self._back_markup())
            return
        await q.edit_message_text("📣 正在群发，请稍候…")
        sent, failed = await self._broadcast(ctx, src["chat_id"], src["message_id"])
        await q.message.reply_text(
            f"✅ 群发完成。\n成功：{sent}　失败：{failed}",
            reply_markup=self._back_markup())

    async def _cancel_bc(self, q, ctx) -> None:
        ctx.user_data.pop("cz", None)
        await q.answer("已取消")
        await self._show_home(q, ctx)

    async def _broadcast(self, ctx, from_chat_id: int, message_id: int):
        sent = failed = 0
        for uid in self.db.get_tenant_user_ids(self.tenant_id, only_active=True):
            try:
                await ctx.bot.copy_message(
                    chat_id=uid, from_chat_id=from_chat_id, message_id=message_id)
                sent += 1
            except TelegramError:
                failed += 1
            await asyncio.sleep(0.05)  # 轻微限速，降低触发 Telegram 限制的概率
        return sent, failed

    async def _cancel_wizard(self, q, ctx) -> None:
        ctx.user_data.pop("cz", None)
        await q.answer("已取消")
        await self._show_home(q, ctx)

    # ── 引导式输入捕获 ──────────────────────────────────────

    async def on_wizard(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if msg is None or not self._admin(update.effective_user.id):
            return
        state = ctx.user_data.get("cz")
        if not state or "flow" not in state:
            return  # 未处于编辑流程 → 交给后续处理器
        flow = state["flow"]
        if flow == "welcome":
            await self._wizard_welcome(msg, ctx)
        elif flow == "wbtns":
            await self._wizard_wbtns(msg, ctx)
        elif flow == "ar":
            await self._wizard_ar(msg, ctx, state)
        elif flow == "fsub":
            await self._wizard_fsub(msg, ctx)
        elif flow == "bc":
            await self._wizard_bc(msg, ctx)
        else:
            return
        raise ApplicationHandlerStop

    async def _wizard_welcome(self, msg, ctx) -> None:
        text = (msg.text or "").strip()
        ctx.user_data.pop("cz", None)
        if not text:
            await msg.reply_text("⚠️ 启动语不能为空，已取消。")
            return
        self.db.set_setting(self.tenant_id, SK_WELCOME_TEXT, text)
        await msg.reply_text("✅ 启动语已更新。", reply_markup=self._welcome_back_markup())

    async def _wizard_wbtns(self, msg, ctx) -> None:
        rows = parse_buttons(msg.text or "")
        ctx.user_data.pop("cz", None)
        if not rows:
            await msg.reply_text(
                "⚠️ 未识别到有效按钮（格式：文字 - 链接，链接需以 http/https 开头），已取消。")
            return
        self.db.set_setting(self.tenant_id, SK_WELCOME_BTNS,
                            json.dumps(rows, ensure_ascii=False))
        await msg.reply_text(
            f"✅ 已设置 {sum(len(r) for r in rows)} 个启动按钮。",
            reply_markup=self._welcome_back_markup())

    async def _wizard_ar(self, msg, ctx, state) -> None:
        step = state.get("step")
        buf  = state.setdefault("buf", {})
        text = (msg.text or "").strip()
        if step == "keyword":
            if not text:
                await msg.reply_text("⚠️ 关键词不能为空，请重新发送。")
                return
            buf["keyword"] = text
            state["step"] = "match"
            await msg.reply_text(
                "（第 2/4 步）请选择*匹配方式*：\n\n"
                "• 包含匹配：消息中*包含*该关键词即命中（推荐）。\n"
                "• 正则匹配：把关键词当作*正则表达式*匹配（高级）。",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔡 包含匹配（推荐）",
                                          callback_data="cz:ar:mt:contains")],
                    [InlineKeyboardButton("🧩 正则匹配",
                                          callback_data="cz:ar:mt:regex")],
                ]))
        elif step == "match":
            await msg.reply_text("请点击上方按钮选择匹配方式（或发送 /cancel 取消）。")
        elif step == "reply":
            if not text:
                await msg.reply_text("⚠️ 回复内容不能为空，请重新发送。")
                return
            buf["reply"] = text
            state["step"] = "buttons"
            await msg.reply_text(
                "（第 4/4 步）请发送随回复附带的*内联按钮*，每行一个：\n"
                "`文字 - 链接`\n\n若不需要按钮，发送「跳过」。",
                parse_mode="Markdown")
        elif step == "buttons":
            buttons_json = ""
            if text not in ("跳过", "skip", "无", "-"):
                rows = parse_buttons(msg.text or "")
                if rows:
                    buttons_json = json.dumps(rows, ensure_ascii=False)
            rid = self.db.add_auto_reply(
                self.tenant_id, buf["keyword"], buf["reply"],
                buf.get("match_type", "contains"), 0, buttons_json)
            ctx.user_data.pop("cz", None)
            mt_note = "（正则）" if buf.get("match_type") == "regex" else ""
            await msg.reply_text(
                f"✅ 已添加自动回复 #{rid}：「{buf['keyword']}」{mt_note}"
                f"{'（含按钮）' if buttons_json else ''}",
                reply_markup=self._back_markup())

    async def _wizard_fsub(self, msg, ctx) -> None:
        channels = self._load_fsub()
        added = 0
        for line in (msg.text or "").splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            title, chat = parts[0], parts[1]
            url = parts[2] if len(parts) > 2 else _default_join_url(chat)
            if not chat or not url:
                continue
            channels.append({"title": title, "chat": chat, "url": url})
            added += 1
        ctx.user_data.pop("cz", None)
        if not added:
            await msg.reply_text(
                "⚠️ 未识别到有效频道（格式：名称 | @用户名 | 链接），已取消。")
            return
        self._save_fsub(channels)
        self.db.set_setting(self.tenant_id, SK_FORCE_SUB_ON, "1")
        await msg.reply_text(
            f"✅ 已添加 {added} 个频道，强制订阅已开启。",
            reply_markup=self._back_markup())

    async def _wizard_bc(self, msg, ctx) -> None:
        ctx.user_data["cz"] = {
            "flow": "bc",
            "bc": {"chat_id": msg.chat_id, "message_id": msg.message_id},
        }
        total = len(self.db.get_tenant_user_ids(self.tenant_id, only_active=True))
        await msg.reply_text(
            f"📣 即将把这条消息群发给 {total} 位用户，确认发送？",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ 发送", callback_data="cz:bc:send"),
                InlineKeyboardButton("❌ 取消", callback_data="cz:bc:cancel"),
            ]]))

    # ── 强制订阅拦截 ────────────────────────────────────────

    async def on_guard(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg, user = update.message, update.effective_user
        if msg is None or user is None or self._admin(user.id):
            return
        if not self.db.get_bool_setting(self.tenant_id, SK_FORCE_SUB_ON, False):
            return
        channels = self._load_fsub()
        if not channels:
            return
        missing = await self._missing_subscriptions(ctx, user.id, channels)
        if not missing:
            return
        await msg.reply_text(
            "🔒 请先加入以下频道后再继续：",
            reply_markup=self._join_markup(missing))
        raise ApplicationHandlerStop

    async def _missing_subscriptions(self, ctx, user_id: int, channels):
        missing = []
        for ch in channels:
            chat = _normalize_chat(ch.get("chat", ""))
            if chat is None:
                continue
            try:
                member = await ctx.bot.get_chat_member(chat, user_id)
                if member.status not in _JOINED_STATUSES:
                    missing.append(ch)
            except TelegramError as e:
                # 无法校验（如机器人不是该频道管理员）→ 放行，避免误锁用户。
                logger.warning("强制订阅校验失败 chat=%s: %s", chat, e)
        return missing

    def _join_markup(self, channels) -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton(
            f"➕ {ch.get('title') or ch.get('chat')}", url=ch["url"])]
            for ch in channels if ch.get("url")]
        rows.append([InlineKeyboardButton("✅ 我已订阅", callback_data="cz:checksub")])
        return InlineKeyboardMarkup(rows)

    async def _on_checksub(self, q, ctx) -> None:
        if not self.db.get_bool_setting(self.tenant_id, SK_FORCE_SUB_ON, False):
            await q.answer()
            try:
                await q.edit_message_text("✅ 你已可以正常使用本机器人。")
            except TelegramError:
                pass
            return
        channels = self._load_fsub()
        missing = await self._missing_subscriptions(ctx, q.from_user.id, channels)
        if missing:
            await q.answer("仍有频道未加入，请先加入后再点。", show_alert=True)
            return
        await q.answer("订阅校验通过！")
        try:
            await q.edit_message_text("✅ 感谢订阅，现在可以正常发送消息了。")
        except TelegramError:
            pass


def _normalize_chat(chat: str):
    chat = (chat or "").strip()
    if not chat:
        return None
    if chat.lstrip("-").isdigit():
        try:
            return int(chat)
        except ValueError:
            return None
    return chat if chat.startswith("@") else "@" + chat


def _default_join_url(chat: str) -> str:
    chat = (chat or "").strip()
    if chat.startswith("@"):
        return "https://t.me/" + chat[1:]
    return ""
