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


# ── config_loader: WEBAPP_URL 自动启用 webapp ─────────────────────────────────

def test_load_config_webapp_url_env_sets_enabled(tmp_path, monkeypatch):
    """WEBAPP_URL 环境变量设置时应自动将 webapp.enabled 置为 True。"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "bot:\n  token: 'X'\n  admin_id: 1\n"
        "webapp:\n  enabled: false\n  url: ''\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBAPP_URL", "https://example.com")
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_ID", raising=False)

    from core.config_loader import load_config
    config = load_config(str(cfg_file))

    assert config["webapp"]["url"] == "https://example.com"
    assert config["webapp"]["enabled"] is True


def test_load_config_no_webapp_url_env_leaves_enabled_false(tmp_path, monkeypatch):
    """未设置 WEBAPP_URL 时，webapp.enabled 保持原始值 False。"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "bot:\n  token: 'X'\n  admin_id: 1\n"
        "webapp:\n  enabled: false\n  url: ''\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WEBAPP_URL", raising=False)
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_ID", raising=False)

    from core.config_loader import load_config
    config = load_config(str(cfg_file))

    assert config["webapp"]["enabled"] is False
    assert config["webapp"]["url"] == ""


def test_load_config_webapp_url_env_does_not_downgrade_existing_enabled(tmp_path, monkeypatch):
    """WEBAPP_URL 环境变量不会将已经显式设为 True 的 enabled 覆盖为其他值。"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "bot:\n  token: 'X'\n  admin_id: 1\n"
        "webapp:\n  enabled: true\n  url: ''\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBAPP_URL", "https://example.com")
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_ID", raising=False)

    from core.config_loader import load_config
    config = load_config(str(cfg_file))

    assert config["webapp"]["enabled"] is True
    assert config["webapp"]["url"] == "https://example.com"
