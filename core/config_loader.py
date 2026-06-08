import os
import yaml


def load_config(path: str = "config.yaml") -> dict:
    """
    加载配置：优先读取环境变量，其次读取 config.yaml。
    生产环境（如 Railway）只需设置环境变量。
    """
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if os.getenv("BOT_TOKEN"):
        config.setdefault("bot", {})["token"] = os.getenv("BOT_TOKEN")
    if os.getenv("ADMIN_ID"):
        config.setdefault("bot", {})["admin_id"] = int(os.getenv("ADMIN_ID"))

    config["db_path"] = os.getenv("DB_PATH", "bot.db")

    return config
