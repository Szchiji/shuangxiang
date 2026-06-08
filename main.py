import asyncio
import logging

from core.bot import ModularBot
from core.config_loader import load_config
from core.database import Database
from core.logging_config import setup_logging
from core.tenant_manager import TenantManager

logger = logging.getLogger("shuangxiang.main")


async def _clear_platform_commands(bot) -> None:
    """清空平台主机器人左下角「/」命令栏，改用内联按钮面板交互。"""
    try:
        await bot.delete_my_commands()
    except Exception as e:
        logger.warning("清除平台命令菜单失败: %s", e)


async def main():
    # 0. 初始化日志（含 Token 脱敏）
    setup_logging()

    # 1. 加载配置（优先读取环境变量）
    config = load_config("config.yaml")

    # 2. 初始化数据库
    Database(db_path=config["db_path"])

    # 3. 平台主机器人（机器人工厂）
    bot = ModularBot(config=config)

    # 4. 多租户管理器（运行所有用户创建的机器人）
    tm = TenantManager(config)
    bot.app.bot_data["tenant_manager"] = tm

    logger.info("数据库路径：%s", config["db_path"])

    # 5. 启动平台主机器人 + 所有已有租户机器人
    async with bot.app:
        await bot.app.initialize()
        await bot.app.start()
        await bot.app.updater.start_polling(drop_pending_updates=True)
        logger.info("平台主机器人已启动")

        await _clear_platform_commands(bot.app.bot)

        await tm.load_all()

        try:
            await asyncio.Event().wait()
        finally:
            await tm.stop_all()
            await bot.app.updater.stop()
            await bot.app.stop()


if __name__ == "__main__":
    asyncio.run(main())
