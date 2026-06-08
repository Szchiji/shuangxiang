"""多租户管理器：并发运行所有用户创建的机器人。

每个租户对应一个独立的 telegram Application，加载 config["tenant_modules"]
指定的功能模块（双向私聊、自动回复、菜单、表单、商店等），
并以 tenant 的拥有者作为该机器人的管理员。
"""

import asyncio

from telegram import Bot
from telegram.error import TelegramError
from telegram.ext import Application

from core.database import Database
from core.loader import ModuleLoader


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
        app = Application.builder().token(tenant["token"]).build()
        ModuleLoader(cfg).load_all(app)
        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
        except TelegramError as e:
            print(f"[租户#{tid}] 启动失败: {e}")
            return False
        self.bots[tid] = app
        print(f"[租户#{tid}] ✅ 机器人已启动 (@{tenant['bot_username']})")
        return True

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
            print(f"[租户#{tid}] 停止时出错: {e}")

    async def load_all(self) -> None:
        tenants = self.db.get_active_tenants()
        print(f"🚀 正在启动 {len(tenants)} 个已有租户机器人...")
        for t in tenants:
            await self.start_tenant(t)
            await asyncio.sleep(0.2)

    async def stop_all(self) -> None:
        for tid in list(self.bots.keys()):
            await self.stop_tenant(tid)
