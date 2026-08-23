"""自动回复 + 关键词过滤（每个租户机器人各运行一份）。

拥有者可配置：
  • 自动回复：命中关键词时机器人自动回复，并拦截该消息（不再转发给管理员、不发送任何提示）。
  • 关键词过滤：用户消息含违禁词时拦截并提示；新租户默认预置一份常见博彩/广告过滤词
    （见 core.database.DEFAULT_FILTER_KEYWORDS），支持正则（/filter_add regex:<正则>）。
  • 防刷屏过滤器：限制单用户短时间内的消息频率（默认开启，可关闭）。
  • 字母表过滤器：可屏蔽包含特定文字（如拉丁字母 / 英文）的消息（默认关闭）。
  • 第三方机器人转发拦截：可选择拦截「经由其他机器人（如群发器）转发」的全部消息，
    从源头阻断借道群发机器人批量投放广告（默认关闭，见 SK_BLOCK_VIA_BOT）。
  • 命中过滤词自动封禁：命中违禁词时可选择自动封禁该用户及其借助的群发器机器人，
    无需管理员手动 /ban（默认关闭，见 SK_FILTER_AUTO_BAN）。

该模块的消息处理器注册在 group=0：在强制订阅拦截(group=-1)之后、
双向中转(group=5)之前执行；命中拦截时通过 ApplicationHandlerStop 阻止后续转发。

⚠️ 每个 group 最多只会执行一个处理器（python-telegram-bot 的语义），
因此本模块必须使用与 customize 模块的强制订阅拦截器(group=-1)*不同*的 group，
否则二者会互相抢占、导致自动回复 / 过滤 / 防刷屏从未运行。
"""

import json
import logging
import re
import time

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.base_module import BaseModule
from core.database import Database
from modules.customize_module import reply_with_optional_media, rows_to_keyboard

logger = logging.getLogger("shuangxiang.auto_reply")

# 设置键
SK_ANTIFLOOD        = "antiflood"        # 防刷屏开关，默认开启
SK_ALPHABET_LATIN   = "alphabet_latin"   # 屏蔽拉丁字母，默认关闭
SK_FLOOD_MAX_MSGS   = "flood_max_msgs"   # 防刷屏：窗口内最多消息数，可自定义
SK_FLOOD_WINDOW     = "flood_window"     # 防刷屏：窗口秒数，可自定义
SK_FILTER_AUTO_BAN  = "filter_auto_ban"  # 命中过滤词自动封禁用户（及来源机器人），默认关闭
SK_BLOCK_VIA_BOT    = "block_via_bot"    # 拦截「经由第三方机器人转发」的消息，默认关闭

# 防刷屏阈值默认值（管理员可在后台自定义，见 SK_FLOOD_MAX_MSGS / SK_FLOOD_WINDOW）
_FLOOD_WINDOW_DEFAULT   = 5.0   # 秒
_FLOOD_MAX_MSGS_DEFAULT = 5     # 窗口内最多消息数

# 自定义阈值的合法范围，防止管理员误配置导致过滤器失效或过于灵敏
_FLOOD_WINDOW_MIN, _FLOOD_WINDOW_MAX     = 1, 60
_FLOOD_MAX_MSGS_MIN, _FLOOD_MAX_MSGS_MAX = 1, 50

# 拉丁字母（英语等使用的基本/扩展拉丁字母）
_LATIN_RE = re.compile(r"[A-Za-z\u00C0-\u024F]")


def match_type_of(row) -> str:
    """从自动回复记录中读取匹配方式（sqlite3.Row 无 .get，需手动判断）。"""
    return (row["match_type"] if "match_type" in row.keys() else "") or "contains"


def clamp_flood_limit(max_msgs: int, window: int) -> tuple[int, int]:
    """将自定义的刷屏阈值限制在合法范围内，避免误配置。"""
    max_msgs = max(_FLOOD_MAX_MSGS_MIN, min(_FLOOD_MAX_MSGS_MAX, max_msgs))
    window = max(_FLOOD_WINDOW_MIN, min(_FLOOD_WINDOW_MAX, window))
    return max_msgs, window


class AutoReplyModule(BaseModule):

    # 每隔多少秒清理一次过期的防刷屏条目（与窗口量级相同即可，取默认窗口的 10 倍）
    _FLOOD_CLEANUP_INTERVAL = _FLOOD_WINDOW_DEFAULT * 10

    def setup(self, app: Application) -> None:
        self.db        = Database()
        self.tenant_id = int(self.config.get("tenant_id", 0))
        self.admin_id  = int(self.config["bot"]["admin_id"])
        # 防刷屏：内存中按用户记录最近消息时间戳
        self._flood: dict[int, list[float]] = {}
        # 上次清理过期条目的时间（单调时钟），用于定期触发 _cleanup_flood
        self._flood_last_cleanup: float = 0.0
        # 相册（媒体组）去重缓存：user_id -> (media_group_id, 判定结果, 时间戳)，
        # 避免同一相册的多条消息被逐条计入刷屏计数
        self._flood_group_cache: dict[int, tuple[str, bool, float]] = {}

        app.add_handler(CommandHandler("ar_add", self.ar_add))
        app.add_handler(CommandHandler("ar_list", self.ar_list))
        app.add_handler(CommandHandler("ar_del", self.ar_del))
        app.add_handler(CommandHandler("filter_add", self.filter_add))
        app.add_handler(CommandHandler("filter_list", self.filter_list))
        app.add_handler(CommandHandler("filter_del", self.filter_del))
        app.add_handler(CommandHandler("antiflood", self.cmd_antiflood))
        app.add_handler(CommandHandler("flood_limit", self.cmd_flood_limit))
        app.add_handler(CommandHandler("alphabet_latin", self.cmd_alphabet_latin))
        app.add_handler(CommandHandler("filter_auto_ban", self.cmd_filter_auto_ban))
        app.add_handler(CommandHandler("block_via_bot", self.cmd_block_via_bot))

        # 在强制订阅拦截(group=-1)之后、双向转发(group=5)之前执行。
        # 必须与 customize 的 on_guard(group=-1) 处于*不同* group，否则会被其抢占。
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND, self.on_message), group=0)

    def _admin(self, update: Update) -> bool:
        return update.effective_user.id == self.admin_id

    # ── 拥有者配置 ──────────────────────────────────────────

    async def ar_add(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        raw = update.message.text.partition(" ")[2]
        if "|" not in raw:
            await update.message.reply_text(
                "用法：/ar_add 关键词 | 回复内容\n（在回复内容前加 ! 表示命中后不再转发，例如：/ar_add 价格 | !见官网）")
            return
        keyword, reply = (p.strip() for p in raw.split("|", 1))
        stop = 0
        if reply.startswith("!"):
            stop, reply = 1, reply[1:].strip()
        if not keyword or not reply:
            await update.message.reply_text("⚠️ 关键词和回复都不能为空。")
            return
        self.db.add_auto_reply(self.tenant_id, keyword, reply, "contains", stop)
        await update.message.reply_text(
            f"✅ 已添加自动回复：「{keyword}」{'（拦截）' if stop else ''}")

    async def ar_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        rows = self.db.get_auto_replies(self.tenant_id)
        if not rows:
            await update.message.reply_text("暂无自动回复。用 /ar_add 添加。")
            return
        lines = [f"{i}. 「{r['keyword']}」{self._type_tag(r)}→ {r['reply']}"
                 f"{' [拦截]' if r['stop'] else ''}"
                 for i, r in enumerate(rows, 1)]
        await update.message.reply_text(
            "📝 自动回复：\n" + "\n".join(lines)
            + "\n\n删除：/ar_del 序号")

    async def ar_del(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        if not ctx.args or not ctx.args[0].isdigit():
            await update.message.reply_text("用法：/ar_del <序号>")
            return
        rows = self.db.get_auto_replies(self.tenant_id)
        idx = int(ctx.args[0])
        if not 1 <= idx <= len(rows):
            await update.message.reply_text("⚠️ 序号不存在，请用 /ar_list 查看。")
            return
        self.db.delete_auto_reply(self.tenant_id, rows[idx - 1]["id"])
        await update.message.reply_text("✅ 已删除。")

    async def filter_add(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        word = update.message.text.partition(" ")[2].strip()
        if not word:
            await update.message.reply_text(
                "用法：/filter_add <违禁词>\n"
                "支持正则：/filter_add regex:<正则表达式>（覆盖变体广告文案时使用）")
            return
        match_type = "contains"
        if word.lower().startswith("regex:"):
            word = word[len("regex:"):].strip()
            match_type = "regex"
            if not word:
                await update.message.reply_text("⚠️ 正则表达式不能为空。")
                return
            try:
                re.compile(word)
            except re.error as e:
                await update.message.reply_text(f"⚠️ 正则表达式无效：{e}")
                return
        self.db.add_filter(self.tenant_id, word, match_type)
        await update.message.reply_text(f"✅ 已添加过滤词：{word}")

    async def filter_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        rows = self.db.get_filters(self.tenant_id)
        if not rows:
            await update.message.reply_text("暂无过滤词。用 /filter_add 添加。")
            return
        await update.message.reply_text(
            "🚫 过滤词：\n"
            + "\n".join(
                f"{i}. {'[正则] ' if match_type_of(r) == 'regex' else ''}{r['keyword']}"
                for i, r in enumerate(rows, 1))
            + "\n\n删除：/filter_del 序号")

    async def filter_del(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        if not ctx.args or not ctx.args[0].isdigit():
            await update.message.reply_text("用法：/filter_del <序号>")
            return
        rows = self.db.get_filters(self.tenant_id)
        idx = int(ctx.args[0])
        if not 1 <= idx <= len(rows):
            await update.message.reply_text("⚠️ 序号不存在，请用 /filter_list 查看。")
            return
        self.db.delete_filter(self.tenant_id, rows[idx - 1]["id"])
        await update.message.reply_text("✅ 已删除。")

    # ── 防刷屏 / 字母表 开关 ────────────────────────────────

    async def cmd_antiflood(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        arg = (ctx.args[0].lower() if ctx.args else "")
        if arg in ("on", "off"):
            self.db.set_setting(self.tenant_id, SK_ANTIFLOOD, "1" if arg == "on" else "0")
            await update.message.reply_text(
                f"✅ 防刷屏过滤器已{'开启' if arg == 'on' else '关闭'}。")
            return
        cur = self.db.get_bool_setting(self.tenant_id, SK_ANTIFLOOD, True)
        await update.message.reply_text(
            f"防刷屏过滤器当前：{'开启' if cur else '关闭'}。\n用法：/antiflood on｜off")

    async def cmd_flood_limit(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """查看或设置防刷屏阈值：多少秒内最多允许多少条消息。"""
        if not self._admin(update):
            return
        cur_n = self.db.get_int_setting(
            self.tenant_id, SK_FLOOD_MAX_MSGS, _FLOOD_MAX_MSGS_DEFAULT)
        cur_w = self.db.get_int_setting(
            self.tenant_id, SK_FLOOD_WINDOW, int(_FLOOD_WINDOW_DEFAULT))
        if not ctx.args:
            await update.message.reply_text(
                f"当前防刷屏阈值：{cur_w} 秒内最多 {cur_n} 条消息。\n"
                f"用法：/flood_limit <条数> <秒数>，例如：/flood_limit 5 5\n"
                f"（条数范围 {_FLOOD_MAX_MSGS_MIN}-{_FLOOD_MAX_MSGS_MAX}，"
                f"秒数范围 {_FLOOD_WINDOW_MIN}-{_FLOOD_WINDOW_MAX}）")
            return
        if len(ctx.args) != 2:
            await update.message.reply_text("用法：/flood_limit <条数> <秒数>，例如：/flood_limit 5 5")
            return
        try:
            n, w = clamp_flood_limit(int(ctx.args[0]), int(ctx.args[1]))
        except ValueError:
            await update.message.reply_text("用法：/flood_limit <条数> <秒数>，例如：/flood_limit 5 5")
            return
        self.db.set_setting(self.tenant_id, SK_FLOOD_MAX_MSGS, n)
        self.db.set_setting(self.tenant_id, SK_FLOOD_WINDOW, w)
        await update.message.reply_text(f"✅ 已设置防刷屏阈值：{w} 秒内最多 {n} 条消息。")

    async def cmd_alphabet_latin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._admin(update):
            return
        arg = (ctx.args[0].lower() if ctx.args else "")
        if arg in ("on", "off"):
            self.db.set_setting(self.tenant_id, SK_ALPHABET_LATIN,
                                "1" if arg == "on" else "0")
            await update.message.reply_text(
                f"✅ 拉丁字母（英文）屏蔽已{'开启' if arg == 'on' else '关闭'}。")
            return
        cur = self.db.get_bool_setting(self.tenant_id, SK_ALPHABET_LATIN, False)
        await update.message.reply_text(
            f"拉丁字母屏蔽当前：{'开启' if cur else '关闭'}。\n用法：/alphabet_latin on｜off")

    async def cmd_filter_auto_ban(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """命中过滤词是否自动封禁该用户（及其借助的群发器机器人）。默认关闭。"""
        if not self._admin(update):
            return
        arg = (ctx.args[0].lower() if ctx.args else "")
        if arg in ("on", "off"):
            self.db.set_setting(self.tenant_id, SK_FILTER_AUTO_BAN,
                                "1" if arg == "on" else "0")
            await update.message.reply_text(
                f"✅ 命中过滤词自动封禁已{'开启' if arg == 'on' else '关闭'}。")
            return
        cur = self.db.get_bool_setting(self.tenant_id, SK_FILTER_AUTO_BAN, False)
        await update.message.reply_text(
            f"命中过滤词自动封禁当前：{'开启' if cur else '关闭'}。\n"
            f"用法：/filter_auto_ban on｜off")

    async def cmd_block_via_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """是否拦截「经由第三方机器人（如群发器）转发」的全部消息。默认关闭。"""
        if not self._admin(update):
            return
        arg = (ctx.args[0].lower() if ctx.args else "")
        if arg in ("on", "off"):
            self.db.set_setting(self.tenant_id, SK_BLOCK_VIA_BOT,
                                "1" if arg == "on" else "0")
            await update.message.reply_text(
                f"✅ 第三方机器人转发消息拦截已{'开启' if arg == 'on' else '关闭'}。")
            return
        cur = self.db.get_bool_setting(self.tenant_id, SK_BLOCK_VIA_BOT, False)
        await update.message.reply_text(
            f"第三方机器人转发消息拦截当前：{'开启' if cur else '关闭'}。\n"
            f"用法：/block_via_bot on｜off\n"
            f"开启后，任何「通过其他机器人」转发来的消息将被直接拦截，不再送达管理员。")

    # ── 防刷屏检测 ──────────────────────────────────────────

    def _flood_limit(self) -> tuple[int, float]:
        """读取该租户当前生效的防刷屏阈值（可在后台自定义，否则用默认值）。"""
        n = self.db.get_int_setting(
            self.tenant_id, SK_FLOOD_MAX_MSGS, _FLOOD_MAX_MSGS_DEFAULT)
        w = self.db.get_int_setting(
            self.tenant_id, SK_FLOOD_WINDOW, int(_FLOOD_WINDOW_DEFAULT))
        return clamp_flood_limit(n, w)

    def _is_flooding(self, user_id: int, media_group_id: str | None = None,
                      now: float | None = None) -> bool:
        """记录一次消息，并判断是否超过窗口内的频率阈值。

        过期用户条目在窗口结束后即时清除，避免长时间运行后内存无限增长。

        同一相册（媒体组）会拆分成多条 Update 逐一到达，若逐条计数，
        发送稍大的相册就会导致后面的图片/视频被误判为刷屏而拦截
        （例如管理员总是只收到前 5 张）。因此同一 media_group_id 只按
        一条消息计数，并复用首条消息的判定结果。
        """
        now = time.monotonic() if now is None else now
        max_msgs, window = self._flood_limit()
        group_cache = self._flood_group_cache
        if media_group_id is not None:
            cached = group_cache.get(user_id)
            if (cached is not None and cached[0] == media_group_id
                    and now - cached[2] < window):
                return cached[1]
        bucket = [t for t in self._flood.get(user_id, []) if now - t < window]
        bucket.append(now)
        self._flood[user_id] = bucket
        flooding = len(bucket) > max_msgs
        if media_group_id is not None:
            group_cache[user_id] = (media_group_id, flooding, now)
        return flooding

    def _cleanup_flood(self, now: float) -> None:
        """删除 _flood 中所有时间戳均已过期的用户条目，释放内存。"""
        _, window = self._flood_limit()
        stale = [uid for uid, ts in self._flood.items()
                 if not any(now - t < window for t in ts)]
        for uid in stale:
            del self._flood[uid]

    # ── 用户消息拦截 ────────────────────────────────────────

    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if msg is None or self._admin(update):
            return

        text = msg.text or msg.caption or ""

        # 0) 防刷屏（默认开启，可关闭）
        if self.db.get_bool_setting(self.tenant_id, SK_ANTIFLOOD, True):
            now = time.monotonic()
            # 定期清理过期条目，防止内存无限增长
            if now - self._flood_last_cleanup >= self._FLOOD_CLEANUP_INTERVAL:
                self._cleanup_flood(now)
                self._flood_last_cleanup = now
            mgid = getattr(msg, "media_group_id", None)
            if self._is_flooding(update.effective_user.id, mgid, now):
                self._log_intercept(update, "antiflood", text=text)
                raise ApplicationHandlerStop

        # 0.5) 拦截「经由第三方机器人（如群发器）转发」的消息（默认关闭，可开启）。
        # 用于从源头阻止借助群发/推广机器人批量投放广告，无需等待管理员逐个 /ban。
        via_bot = getattr(msg, "via_bot", None)
        if via_bot is not None and self.db.get_bool_setting(
                self.tenant_id, SK_BLOCK_VIA_BOT, False):
            self._log_intercept(update, "block_via_bot", text=text, via_bot=via_bot)
            raise ApplicationHandlerStop

        if not text:
            return

        # 1) 字母表过滤：屏蔽含拉丁字母（英文等）的消息（默认关闭）
        if self.db.get_bool_setting(self.tenant_id, SK_ALPHABET_LATIN, False):
            if _LATIN_RE.search(text):
                self._log_intercept(update, "alphabet_latin", text=text, via_bot=via_bot)
                await msg.reply_text("⚠️ 不支持包含英文/拉丁字母的消息。")
                raise ApplicationHandlerStop

        # 2) 过滤违禁词 → 拦截（支持大小写不敏感子串匹配 / 正则）
        text_lower = text.lower()
        for f in self.db.get_filters(self.tenant_id):
            if self._filter_matches(f, text, text_lower):
                # 命中过滤词自动封禁（默认关闭）：同时封禁其借助的群发器机器人。
                auto_banned = self.db.get_bool_setting(
                    self.tenant_id, SK_FILTER_AUTO_BAN, False)
                if auto_banned:
                    self.db.ban_user(self.tenant_id, update.effective_user.id)
                    if via_bot is not None:
                        self.db.ban_bot(
                            self.tenant_id, via_bot.id, via_bot.username or "")
                self._log_intercept(
                    update, "filter", rule=f["keyword"], text=text,
                    via_bot=via_bot, auto_banned=auto_banned)
                await msg.reply_text("⚠️ 您的消息包含不被允许的内容，未发送。")
                raise ApplicationHandlerStop

        # 3) 自动回复
        for r in self.db.get_auto_replies(self.tenant_id):
            if self._matches(r, text):
                markup = self._reply_markup(r)
                media_type, media_id = self._media_of(r)
                await reply_with_optional_media(
                    msg, r["reply"], media_type, media_id, reply_markup=markup)
                # 自动回复命中即视为已处理：不再把关键词消息转发给租户机器人（管理员），
                # 也不向其发送任何提示。
                raise ApplicationHandlerStop

    # 拦截日志中消息摘要的最大长度，避免超长内容占用过多存储。
    _LOG_SUMMARY_MAX_LEN = 200

    def _log_intercept(self, update: Update, reason: str, *, rule: str = "",
                       text: str = "", via_bot=None, auto_banned: bool = False) -> None:
        """写入一条拦截日志，供管理员在 Web 后台排查、判断词库是否需要调整。"""
        user = update.effective_user
        try:
            self.db.add_intercept_log(
                self.tenant_id, reason,
                user_id=getattr(user, "id", None),
                username=getattr(user, "username", "") or "",
                full_name=getattr(user, "full_name", "") or "",
                rule=rule,
                message_summary=text[: self._LOG_SUMMARY_MAX_LEN],
                via_bot_id=getattr(via_bot, "id", None) if via_bot else None,
                via_bot_username=getattr(via_bot, "username", "") or "" if via_bot else "",
                auto_banned=auto_banned,
            )
        except Exception:
            # 日志写入失败不应影响正常的拦截流程。
            logger.exception("写入拦截日志失败")

    @staticmethod
    def _filter_matches(row, text: str, text_lower: str) -> bool:
        """判断一条过滤词是否命中。

        match_type='regex' → 把 keyword 当作正则（不区分大小写），命中消息中任意位置即可；
        其它（默认 'contains'）→ 大小写不敏感子串包含匹配。无效正则视为不命中。
        """
        keyword = row["keyword"]
        match_type = match_type_of(row)
        if match_type == "regex":
            try:
                return re.search(keyword, text, re.IGNORECASE) is not None
            except re.error:
                return False
        return keyword.lower() in text_lower

    @staticmethod
    def _matches(row, text: str) -> bool:
        """判断一条自动回复是否命中。

        match_type='regex'      → 把 keyword 当作正则（不区分大小写），整条消息完全匹配；
        match_type='ci_contains'→ 大小写不敏感子串包含匹配；
        其它（默认 'contains'） → 区分大小写子串包含匹配。无效正则视为不命中。
        """
        keyword = row["keyword"]
        match_type = match_type_of(row)
        if match_type == "regex":
            try:
                return re.fullmatch(keyword, text, re.IGNORECASE) is not None
            except re.error:
                return False
        if match_type == "ci_contains":
            return keyword.lower() in text.lower()
        return keyword in text

    @staticmethod
    def _type_tag(row) -> str:
        """命中方式标签，用于列表展示。"""
        mt = match_type_of(row)
        if mt == "regex":
            return "[正则] "
        if mt == "ci_contains":
            return "[忽略大小写] "
        return ""

    @staticmethod
    def _media_of(row):
        """读取一条自动回复的媒体 (media_type, media_id)（兼容旧库无该列）。"""
        keys = row.keys()
        mtype = (row["media_type"] if "media_type" in keys else "") or ""
        mid = (row["media_id"] if "media_id" in keys else "") or ""
        return mtype, mid

    @staticmethod
    def _reply_markup(row):
        """若该自动回复配置了内联按钮（JSON），构建 InlineKeyboardMarkup。"""
        raw = row["buttons"] or ""
        if not raw:
            return None
        try:
            keyboard = rows_to_keyboard(json.loads(raw))
        except (ValueError, TypeError, KeyError):
            return None
        return InlineKeyboardMarkup(keyboard) if keyboard else None
