import os
import secrets

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
    config["admin_web"] = {
        "enabled": os.getenv("ADMIN_WEB_ENABLED", "0").lower()
        in ("1", "true", "on", "yes"),
        "host": os.getenv("ADMIN_WEB_HOST", "127.0.0.1"),
        "port": int(os.getenv("ADMIN_WEB_PORT", "8080")),
        "session_ttl": int(os.getenv("ADMIN_WEB_SESSION_TTL", "3600")),
        "public_base_url": os.getenv("ADMIN_WEB_PUBLIC_BASE_URL", "").strip(),
        "autologin_secret": os.getenv("ADMIN_WEB_AUTOLOGIN_SECRET", "")
        or secrets.token_urlsafe(32),
        "autologin_ttl": int(os.getenv("ADMIN_WEB_AUTOLOGIN_TTL", "180")),
    }

    return config
