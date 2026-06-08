import asyncio
import uvicorn
from core.config_loader import load_config
from core.database import Database
from core.bot import ModularBot
from core.tenant_manager import TenantManager
from web.app import create_app


async def main():
    # 1. 加载配置（优先读取环境变量）
    config = load_config("config.yaml")

    # 2. 初始化数据库
    Database(db_path=config["db_path"])

    # 3. 创建主平台 Bot
    bot = ModularBot(config=config)

    # 4. 多租户管理器
    tm = TenantManager(config)
    bot.app.bot_data["tenant_manager"] = tm

    # 5. FastAPI Web 面板
    web = create_app(config=config, bot_app=bot.app, tenant_manager=tm)

    # 6. 启动所有已有租户机器人
    await tm.load_all_tenants()

    # 7. 配置 uvicorn
    port   = config["web_port"]
    server = uvicorn.Server(uvicorn.Config(
        web,
        host      = "0.0.0.0",
        port      = port,
        log_level = "info",
    ))

    print(f"🌐 Web 管理面板：http://0.0.0.0:{port}")
    print(f"📖 API  文  档：http://0.0.0.0:{port}/api/docs")
    print(f"🗃️  数据库路径：{config['db_path']}")

    # 8. 并行运行 Bot + Web
    await asyncio.gather(
        bot.run_async(),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
