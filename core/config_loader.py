import os
import yaml


def load_config(path: str = "config.yaml") -> dict:
    """
    加载配置：优先读取环境变量，其次读取 config.yaml。
    生产环境（Railway）只需设置环境变量。
    """
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if os.getenv("BOT_TOKEN"):
        config.setdefault("bot", {})["token"] = os.getenv("BOT_TOKEN")
    if os.getenv("ADMIN_ID"):
        config.setdefault("bot", {})["admin_id"] = int(os.getenv("ADMIN_ID"))
    if os.getenv("WEB_USERNAME"):
        config.setdefault("web", {})["username"] = os.getenv("WEB_USERNAME")
    if os.getenv("WEB_PASSWORD"):
        config.setdefault("web", {})["password"] = os.getenv("WEB_PASSWORD")
    if os.getenv("WEB_SECRET_KEY"):
        config.setdefault("web", {})["secret_key"] = os.getenv("WEB_SECRET_KEY")

    config["db_path"]  = os.getenv("DB_PATH", "bot.db")
    config["web_port"] = int(os.getenv("PORT", 8080))

    return config
