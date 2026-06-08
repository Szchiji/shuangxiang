"""多租户管理器：并发运行所有用户创建的机器人。

每个租户对应一个独立的 telegram Application，加载 config["tenant_modules"]
指定的功能模块（双向私聊、交互式自定义、自动回复等），
并以 tenant 的拥有者作为该机器人的管理员。
"""

import asyncio
import logging
import os

from telegram import Bot, BotCommandScopeChat
from telegram.error import InvalidToken, TelegramError
from telegram.ext import Application

from core.app_factory import build_application
from core.database import Database
from core.loader import ModuleLoader

logger = logging.getLogger("shuangxiang.tenant")


class TenantManager:
    def __init__(self, config: dict):
        self.config = config
        self.db     = Database()
        self.bots: dict[int, Application] = {}

    def _tenant_config(self, tenant) -> dict:
        cfg = dict(self.config)
        cfg["bot"] = {
            "token":    tenant["token"],
            "admin_id": tenant["owner_user_id"],
            "name":     tenant["bot_name"] or "双向私聊机器人",
        }
        cfg["tenant_id"] = tenant["id"]
        cfg["modules"]   = self.config.get(
            "tenant_modules", ["modules.private_chat_module"])
        return cfg

    @staticmethod
    async def validate_token(token: str):
        """校验 token，返回 bot 信息或抛出异常。"""
        bot = Bot(token)
        try:
            me = await bot.get_me()
            return me
        finally:
            try:
                await bot.shutdown()
            except Exception:
                pass

    async def start_tenant(self, tenant) -> bool:
        tid = tenant["id"]
        if tid in self.bots:
            return True
        cfg = self._tenant_config(tenant)
        app = build_application(tenant["token"])
        ModuleLoader(cfg).load_all(app)
        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
        except TelegramError as e:
            logger.error("[租户#%s] 启动失败: %s", tid, e)
            return False
        self.bots[tid] = app
        logger.info("[租户#%s] 机器人已启动 (@%s)", tid, tenant["bot_username"])
        self._supervise_polling(tid)
        await self._clear_tenant_commands(app.bot, tenant["owner_user_id"])
        return True

    def _supervise_polling(self, tid: int) -> None:
        """监控租户轮询任务：Token 在运行期间失效（如被 BotFather 撤销）时，
        polling 循环会带 InvalidToken 异常退出。为其挂载完成回调，
        避免异常被静默丢弃，并自动停用该租户、清理资源。"""
        app = self.bots.get(tid)
        updater = getattr(app, "updater", None) if app else None
        # __polling_task 为 Updater 的私有属性（名称改写后为 _Updater__polling_task），
        # 在 start_polling 之后创建；不同 PTB 版本若缺失则静默跳过监控。
        task = getattr(updater, "_Updater__polling_task", None)
        if task is None:
            return

        def _on_done(t) -> None:
            if t.cancelled():
                return
            try:
                exc = t.exception()
            except asyncio.CancelledError:
                return
            if exc is None:
                return
            asyncio.create_task(self._on_polling_failure(tid, exc))

        task.add_done_callback(_on_done)

    async def _on_polling_failure(self, tid: int, exc: BaseException) -> None:
        """轮询任务异常退出后的处理：Token 失效则停用租户，其它异常仅记录。"""
        if isinstance(exc, InvalidToken):
            logger.warning(
                "[租户#%s] Token 已失效（可能被 BotFather 撤销），已停用该机器人。", tid)
            try:
                self.db.deactivate_tenant(tid)
            except Exception as e:
                logger.warning("[租户#%s] 停用失败: %s", tid, e)
            await self.stop_tenant(tid)
        else:
            logger.error(
                "[租户#%s] 轮询循环异常退出: %s", tid, exc, exc_info=exc)

    @staticmethod
    async def _clear_tenant_commands(bot, owner_user_id: int) -> None:
        """清空租户机器人左下角「/」命令栏（默认与拥有者作用域），改用控制面板按钮交互。"""
        try:
            await bot.delete_my_commands()
            await bot.delete_my_commands(
                scope=BotCommandScopeChat(chat_id=owner_user_id))
        except Exception as e:
            logger.warning("清除租户命令菜单失败: %s", e)

    async def stop_tenant(self, tid: int) -> None:
        app = self.bots.pop(tid, None)
        if not app:
            return
        try:
            if app.updater and app.updater.running:
                await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception as e:
            logger.warning("[租户#%s] 停止时出错: %s", tid, e)

    async def load_all(self) -> None:
        tenants = self.db.get_active_tenants()
        logger.info("正在启动 %d 个已有租户机器人...", len(tenants))
        # 受控并发批量启动：相比逐个 sleep(0.2) 串行启动，租户多时显著更快，
        # 同时用信号量限制并发，避免一次性建立过多连接触发 Telegram 限制。
        # 并发上限可经环境变量 TENANT_STARTUP_CONCURRENCY 调整（默认 10）。
        try:
            limit = max(1, int(os.getenv("TENANT_STARTUP_CONCURRENCY", "10")))
        except ValueError:
            limit = 10
        sem = asyncio.Semaphore(limit)

        async def _start(t):
            async with sem:
                await self.start_tenant(t)

        await asyncio.gather(*(_start(t) for t in tenants), return_exceptions=True)

    async def stop_all(self) -> None:
        await asyncio.gather(
            *(self.stop_tenant(tid) for tid in list(self.bots.keys())),
            return_exceptions=True)
