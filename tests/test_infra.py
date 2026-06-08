"""日志脱敏与应用工厂测试。"""

from core.app_factory import build_application
from core.logging_config import redact_token


def test_redact_token_masks_secret():
    out = redact_token("启动 token 123456789:AAHkjsdfsdfsdf1234 完成")
    assert "AAHkjsdfsdfsdf1234" not in out
    assert "123456789:" in out
    assert "***" in out


def test_redact_token_noop_on_plain_text():
    assert redact_token("no token here") == "no token here"


def test_build_application_sets_concurrency_and_error_handler():
    app = build_application("123456:ABCdummy")
    # concurrent_updates 为正整数（启用并发）
    assert int(app.concurrent_updates) > 0
    assert app.error_handlers, "应注册全局错误处理器"
