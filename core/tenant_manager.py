import asyncio
from core.database import Database
from core.loader import ModuleLoader


class TenantManager:
    """管理所有租户机器人的完整生命周期"""

    def __init__(self, base_config: dict):
        self.base_config = base_config
        self.db          = Database()
        self._running: dict[int, dict] = {}

    @property
    def tenant_modules(self) -> list:
        return self.base_config.get("tenant_modules", [
            "modules.store_module",
            "modules.form_module",
            "modules.forward_module",
            "modules.auto_reply_module",
            "modules.admin_module",
            "modules.menu_module",
        ])

    async def load_all_tenants(self) -> None:
        tenants = self.db.get_active_tenants()
        if not tenants:
            print("[TenantManager] 暂无租户机器人")
            return
        results = await asyncio.gather(
            *[self.start_tenant(t["id"], t["token"], t["admin_id"]) for t in tenants],
            return_exceptions=True,
        )
        ok = sum(1 for r in results if not isinstance(r, Exception))
        print(f"[TenantManager] ✅ 已启动 {ok}/{len(tenants)} 个租户机器人")

    async def start_tenant(self, tenant_id: int, token: str, admin_id: int) -> None:
        from telegram.ext import Application
        if tenant_id in self._running:
            return
        tenant_config = {
            **self.base_config,
            "bot":       {**self.base_config["bot"], "admin_id": admin_id},
            "modules":   self.tenant_modules,
            "tenant_id": tenant_id,
        }
        try:
            app    = Application.builder().token(token).build()
            loader = ModuleLoader(tenant_config)
            loader.load_all(app)
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
            task = asyncio.create_task(self._watch(tenant_id))
            self._running[tenant_id] = {"app": app, "task": task}
            print(f"[Tenant #{tenant_id}] ✅ 已启动")
        except Exception as e:
            print(f"[Tenant #{tenant_id}] ❌ 启动失败：{e}")
            raise

    async def _watch(self, tenant_id: int) -> None:
        try:
            while tenant_id in self._running:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    async def stop_tenant(self, tenant_id: int) -> None:
        if tenant_id not in self._running:
            return
        entry = self._running.pop(tenant_id)
        entry["task"].cancel()
        app = entry["app"]
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception as e:
            print(f"[Tenant #{tenant_id}] 停止异常：{e}")
        self.db.deactivate_tenant(tenant_id)
        print(f"[Tenant #{tenant_id}] ⏹ 已停止")

    async def launch_tenant_from_data(
        self, token: str, bot_username: str, bot_name: str,
        owner_user_id: int, admin_id: int,
    ) -> dict:
        tenant_id = self.db.add_tenant(
            token=token, bot_username=bot_username, bot_name=bot_name,
            owner_user_id=owner_user_id, admin_id=admin_id,
        )
        await self.start_tenant(tenant_id, token, admin_id)
        return {"id": tenant_id, "bot_username": bot_username, "bot_name": bot_name}

    def is_running(self, tenant_id: int) -> bool:
        return tenant_id in self._running

    def running_count(self) -> int:
        return len(self._running)
