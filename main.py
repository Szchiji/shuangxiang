import asyncio
import logging

from telegram.error import InvalidToken

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


async def _store_platform_username(bot) -> None:
    """记录平台主机器人的真实用户名，供租户机器人启动信息底部署名使用。"""
    from modules.platform_module import (
        PLATFORM_TID,
        SK_PLATFORM_BOT_USERNAME_AUTO,
    )
    try:
        me = await bot.get_me()
        if me.username:
            Database().set_setting(
                PLATFORM_TID, SK_PLATFORM_BOT_USERNAME_AUTO, me.username)
    except Exception as e:
        logger.warning("记录平台用户名失败: %s", e)


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
    try:
        async with bot.app:
            await bot.app.initialize()
            await bot.app.start()
            await bot.app.updater.start_polling(drop_pending_updates=True)
            logger.info("平台主机器人已启动")

            await _clear_platform_commands(bot.app.bot)

            await _store_platform_username(bot.app.bot)

            await tm.load_all()

            try:
                await asyncio.Event().wait()
            finally:
                await tm.stop_all()
                await bot.app.updater.stop()
                await bot.app.stop()
    except InvalidToken:
        logger.error(
            "平台主机器人 Token 无效（Unauthorized）。请检查环境变量 BOT_TOKEN "
            "或 config.yaml 中的 bot.token 是否正确、是否已被 BotFather 撤销。")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
