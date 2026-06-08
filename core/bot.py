import asyncio
from telegram.ext import Application
from core.loader import ModuleLoader


class ModularBot:

    def __init__(self, config: dict):
        self.config = config
        self.token  = config["bot"]["token"]
        self.app    = Application.builder().token(self.token).build()
        self.loader = ModuleLoader(self.config)
        self._setup()

    def _setup(self) -> None:
        print("🤖 正在加载模块...")
        self.loader.load_all(self.app)
        print(f"✅ 已加载 {len(self.loader.list_modules())} 个模块")

    def run(self) -> None:
        self.app.run_polling()

    async def run_async(self) -> None:
        async with self.app:
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling()
            print("🤖 Telegram Bot 已启动")
            await asyncio.Event().wait()
