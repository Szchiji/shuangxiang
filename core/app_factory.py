"""统一构建 telegram Application 的工厂。

集中应用以下升级，平台机器人与所有租户机器人共用：
  • concurrent_updates(True)：单机器人内多用户消息并行处理；
  • AIORateLimiter（若已安装 rate-limiter 额外依赖）：自动处理 429 / flood control 重试；
  • 全局错误处理器。
"""

import logging

from telegram.ext import Application, ApplicationBuilder

from core.errors import register_error_handler

logger = logging.getLogger("shuangxiang.app")

try:  # rate-limiter 为可选额外依赖（python-telegram-bot[rate-limiter]）
    from telegram.ext import AIORateLimiter
except Exception:  # pragma: no cover - 取决于运行环境是否安装
    AIORateLimiter = None

_RATE_LIMITER_WARNED = False


def build_application(token: str) -> Application:
    """按平台统一策略构建并返回一个 Application（未 initialize）。"""
    global _RATE_LIMITER_WARNED
    builder: ApplicationBuilder = ApplicationBuilder().token(token)
    builder = builder.concurrent_updates(True)
    if AIORateLimiter is not None:
        try:
            builder = builder.rate_limiter(AIORateLimiter())
        except Exception as e:  # pragma: no cover - 防御性
            if not _RATE_LIMITER_WARNED:
                logger.warning("启用限流器失败，已跳过: %s", e)
                _RATE_LIMITER_WARNED = True
    elif not _RATE_LIMITER_WARNED:
        logger.info(
            "未安装限流器额外依赖（python-telegram-bot[rate-limiter]），"
            "将不启用内置限流。")
        _RATE_LIMITER_WARNED = True

    app = builder.build()
    register_error_handler(app)
    return app
