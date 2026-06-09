"""共享 UI 设计系统。

统一全项目用户界面的视觉语言：现代「卡片式」标题——一行加粗标题（可带表情图标），
下方紧跟一条细分隔线，再接正文。这样每个面板都有清晰的视觉层级，整体更美观一致。

同时支持 Telegram 两种 parse_mode：
  • Markdown（`*标题*`）—— 多数面板使用；
  • HTML（`<b>标题</b>`）—— 含用户名/转义内容的面板使用。

用法::

    from core import ui

    ui.header("控制面板", emoji="⚙️")               # Markdown
    ui.header("我的机器人", emoji="🤖", html=True)   # HTML
    ui.section("控制面板", "正文……", emoji="⚙️")     # 标题 + 分隔线 + 正文
"""

# 细分隔线：现代 Telegram 机器人常用的「卡片」分割样式，比粗线更克制、耐看。
DIVIDER = "──────────────"


def header(title: str, *, emoji: str = "", html: bool = False) -> str:
    """返回带分隔线的卡片式标题（不含正文）。

    Args:
        title: 标题文本。
        emoji: 可选的标题前置表情图标。
        html: 为 True 时输出 HTML（``<b>``），否则输出 Markdown（``*``）。
    """
    label = f"{emoji} {title}".strip()
    head = f"<b>{label}</b>" if html else f"*{label}*"
    return f"{head}\n{DIVIDER}"


def section(title: str, body: str = "", *, emoji: str = "", html: bool = False) -> str:
    """返回完整的卡片式区块：标题 + 分隔线 +（可选）正文。"""
    text = header(title, emoji=emoji, html=html)
    if body:
        text += f"\n\n{body}"
    return text
