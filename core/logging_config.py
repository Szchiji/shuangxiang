"""统一日志配置与敏感信息脱敏。

用 `logging` 替代散落的 `print`，便于在 Railway 等平台按级别/时间排查问题。
"""

import logging
import os
import re

# 形如 123456789:AAH...（Telegram Bot Token）的脱敏匹配
_TOKEN_RE = re.compile(r"\b(\d{6,})(:)([A-Za-z0-9_-]{10,})\b")


def redact_token(text: str) -> str:
    """将文本中的 Bot Token 脱敏，仅保留 bot_id 与尾部少量字符。"""
    if not text:
        return text

    def _mask(m: "re.Match") -> str:
        secret = m.group(3)
        tail = secret[-4:] if len(secret) > 4 else ""
        return f"{m.group(1)}{m.group(2)}***{tail}"

    return _TOKEN_RE.sub(_mask, str(text))


class _RedactTokenFilter(logging.Filter):
    """日志过滤器：对最终输出的消息做 Token 脱敏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if _TOKEN_RE.search(msg):
            record.msg = redact_token(msg)
            record.args = ()
        return True


_CONFIGURED = False


def setup_logging() -> None:
    """初始化根日志器。可通过环境变量 LOG_LEVEL 调整级别（默认 INFO）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    handler.addFilter(_RedactTokenFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))

    # 降低第三方库噪声
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    _CONFIGURED = True

