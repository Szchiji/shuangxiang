# 双向私聊机器人 (Two-way Private Chat Bot)

一个基于 [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) 的
**双向私聊（客服 / 反馈）机器人**：

- 普通用户私聊机器人 → 机器人把消息转发给管理员；
- 管理员**回复**某条转发过来的消息 → 机器人把回复发还给对应用户。

支持文本、图片、视频、语音、文件、贴纸等**所有消息类型**的双向中转。

## 功能

- 🔁 双向消息中转（用户 ↔ 管理员）
- 🖼️ 支持所有消息类型（图片 / 语音 / 文件 / 贴纸 …）
- 🧷 基于数据库的消息映射，回复任意历史消息都能精准送达
- ⛔ 封禁 / 解封用户
- 👤 查看用户资料、统计

## 管理员指令

> 在管理员私聊里使用，部分指令需「回复」某条用户消息。

| 指令 | 说明 |
| --- | --- |
| `/start`、`/help` | 显示帮助 |
| `/ban`（回复）或 `/ban <用户ID>` | 封禁用户 |
| `/unban`（回复）或 `/unban <用户ID>` | 解封用户 |
| `/info`（回复） | 查看该用户资料 |
| `/stats` | 用户统计 |

## 快速开始

1. 向 [@BotFather](https://t.me/BotFather) 创建机器人，获取 `BOT_TOKEN`。
2. 获取你自己的 Telegram 用户 ID（可用 [@userinfobot](https://t.me/userinfobot)）作为 `ADMIN_ID`。
3. 配置 `config.yaml` 或设置环境变量（环境变量优先）。

```bash
pip install -r requirements.txt
python main.py
```

### 环境变量

| 变量 | 说明 |
| --- | --- |
| `BOT_TOKEN` | 机器人 Token |
| `ADMIN_ID` | 管理员用户 ID |
| `DB_PATH` | SQLite 数据库路径（默认 `bot.db`） |

## 部署（Railway / Docker）

仓库已内置 `Dockerfile` 与 `railway.toml`，在平台上设置 `BOT_TOKEN`、`ADMIN_ID`
（以及挂载卷对应的 `DB_PATH`）即可一键部署。

## 配置文件 `config.yaml`

```yaml
bot:
  token:    "YOUR_BOT_TOKEN"
  admin_id: 123456789
modules:
  - modules.private_chat_module
messages:
  welcome:       "👋 你好！直接发送消息即可联系管理员。"
  admin_welcome: "👋 管理员你好！回复某条消息即可回复对应用户。"
  received:      ""
  banned:        "⛔ 你已被封禁，无法发送消息。"
```
