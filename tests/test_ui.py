"""共享 UI 设计系统（core.ui）的单元测试。"""

from core import ui


def test_header_markdown_with_emoji():
    out = ui.header("控制面板", emoji="⚙️")
    assert out == f"*⚙️ 控制面板*\n{ui.DIVIDER}"


def test_header_html_with_emoji():
    out = ui.header("我的机器人", emoji="🤖", html=True)
    assert out == f"<b>🤖 我的机器人</b>\n{ui.DIVIDER}"


def test_header_without_emoji_has_no_leading_space():
    assert ui.header("标题") == f"*标题*\n{ui.DIVIDER}"
    assert ui.header("标题", html=True) == f"<b>标题</b>\n{ui.DIVIDER}"


def test_section_appends_body_after_blank_line():
    out = ui.section("统计", "正文内容", emoji="📊")
    assert out == f"*📊 统计*\n{ui.DIVIDER}\n\n正文内容"


def test_section_without_body_equals_header():
    assert ui.section("统计", emoji="📊") == ui.header("统计", emoji="📊")
