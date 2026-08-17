import hashlib
import logging
import os
import secrets

import yaml

logger = logging.getLogger("shuangxiang.config")


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

    admin_web_enabled = os.getenv("ADMIN_WEB_ENABLED", "0").lower() in ("1", "true", "on", "yes")
    public_base_url = os.getenv("ADMIN_WEB_PUBLIC_BASE_URL", "").strip()
    auto_secret = os.getenv("ADMIN_WEB_AUTOLOGIN_SECRET", "").strip()
    if admin_web_enabled and not auto_secret:
        bot_token = str(config.get("bot", {}).get("token", "") or "").strip()
        auto_secret = (
            hashlib.sha256(f"shuangxiang-admin:{bot_token}".encode("utf-8")).hexdigest()
            if bot_token
            else secrets.token_urlsafe(32)
        )
        if not bot_token:
            logger.warning(
                "未设置 ADMIN_WEB_AUTOLOGIN_SECRET 且未检测到 bot token，"
                "已使用临时随机密钥；服务重启后旧的一键登录链接将失效。"
            )

    config["db_path"] = os.getenv("DB_PATH", "bot.db")
    config["admin_web"] = {
        "enabled": admin_web_enabled,
        "host": os.getenv("ADMIN_WEB_HOST", "127.0.0.1"),
        "port": int(os.getenv("ADMIN_WEB_PORT", "8080")),
        "session_ttl": int(os.getenv("ADMIN_WEB_SESSION_TTL", "3600")),
        "public_base_url": public_base_url,
        "autologin_secret": auto_secret,
        "autologin_ttl": int(os.getenv("ADMIN_WEB_AUTOLOGIN_TTL", "180")),
        "secure_cookies": os.getenv("ADMIN_WEB_SECURE_COOKIES", "").lower()
        in ("1", "true", "on", "yes")
        or public_base_url.lower().startswith("https://"),
    }

    return config
