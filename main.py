from core.config_loader import load_config
from core.database import Database
from core.bot import ModularBot


def main():
    # 1. 加载配置（优先读取环境变量）
    config = load_config("config.yaml")

    # 2. 初始化数据库
    Database(db_path=config["db_path"])

    # 3. 创建并运行双向私聊机器人
    bot = ModularBot(config=config)
    print(f"🗃️  数据库路径：{config['db_path']}")
    print("�� 双向私聊机器人已启动")
    bot.run()


if __name__ == "__main__":
    main()
