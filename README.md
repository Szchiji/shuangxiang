# 双向私聊机器人工厂 (Bot Factory Platform)

一个基于 [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) 的
**多租户机器人平台**，灵感来自 [@ModularBot](https://t.me/ModularBot)。

任何用户都可以向**平台主机器人**发送自己的 Bot Token，一键创建属于自己的
**双向私聊机器人**，并使用主题（Topics）管理私聊、配置自动回复 / 过滤、搭建菜单、
收集表单、开设数字商店等功能。

- 平台主机器人 = 「机器人工厂」：用户用 `/newbot <token>` 创建自己的机器人；
- 每个被创建的机器人（租户）独立运行，数据按 `tenant_id` 隔离，但共用同一套代码与数据库。

## 功能总览

- 🏭 **机器人工厂**：用户通过命令创建 / 管理 / 删除自己的机器人，创建后立即上线运行。
- 🔁 **双向私聊**：用户 ↔ 管理员消息中转，支持所有消息类型。
  - **DM 模式**：消息直接转发到管理员私聊，回复任意历史消息精准送达。
  - **Topics 模式**：把机器人加入一个开启「主题」的超级群，每个用户对应一个独立主题，便于多管理员协作。
- 🤖 **自动回复 + 关键词过滤**：按关键词自动回复；命中过滤词的消息可拦截、不转发。
- 🧭 **菜单 / 子菜单**：用内联按钮逐层搭建机器人菜单树。
- 📝 **引导式表单**：分步骤收集用户信息并保存。
- 🛒 **数字商店**：分类 / 商品 / 购物车 / 下单。
- ⛔ 封禁 / 解封、用户资料、统计。

## 使用方式

### 1. 平台主机器人指令

| 指令 | 说明 |
| --- | --- |
| `/start`、`/help` | 显示帮助 |
| `/newbot <token>` | 用 @BotFather 给的 Token 创建你自己的机器人（立即上线） |
| `/mybots` | 查看你创建的机器人列表 |
| `/delbot <id>` | 删除某个机器人 |

### 2. 租户机器人 —— 管理员（机器人拥有者）指令

> 在你创建的机器人里使用。回复类指令需「回复」对应的用户消息。

**双向私聊**

| 指令 | 说明 |
| --- | --- |
| `/start`、`/help` | 帮助 |
| `/ban`、`/unban`（回复或带用户ID） | 封禁 / 解封用户 |
| `/info`（回复） | 查看用户资料 |
| `/stats` | 用户统计 |
| `/setgroup` | 在开启主题的超级群内运行，切换到 Topics 模式 |
| `/unsetgroup` | 取消 Topics 模式，回到 DM 模式 |

**自动回复 / 过滤**

| 指令 | 说明 |
| --- | --- |
| `/ar_add <关键词> <回复内容>` | 添加自动回复 |
| `/ar_list`、`/ar_del <id>` | 列出 / 删除自动回复 |
| `/filter_add <关键词>` | 添加过滤词（命中则拦截） |
| `/filter_list`、`/filter_del <id>` | 列出 / 删除过滤词 |

**菜单**

| 指令 | 说明 |
| --- | --- |
| `/menu_add <父ID> <标题> [内容]` | 添加菜单项（父ID 为 0 表示顶级） |
| `/menu_list`、`/menu_del <id>` | 列出 / 删除菜单项 |

**表单**

| 指令 | 说明 |
| --- | --- |
| `/form_new <表单名>` | 新建表单 |
| `/form_step <表单ID> <提问>` | 给表单添加一步提问 |
| `/form_list`、`/form_del <id>` | 列出 / 删除表单 |

**数字商店**

| 指令 | 说明 |
| --- | --- |
| `/shop_addcat <名称>` | 添加商品分类 |
| `/shop_addproduct <分类ID> <名称> <价格> [描述]` | 添加商品 |
| `/shop_list` | 列出分类与商品 |
| `/shop_delcat <id>`、`/shop_delproduct <id>` | 删除分类 / 商品 |

### 3. 租户机器人 —— 普通用户指令

| 指令 | 说明 |
| --- | --- |
| `/start` | 开始私聊，消息会转发给管理员 |
| `/menu` | 浏览机器人菜单 |
| `/forms` | 填写表单 / `/cancel` 取消 |
| `/shop`、`/cart` | 浏览商店 / 查看购物车 |

## 快速开始

1. 向 [@BotFather](https://t.me/BotFather) 创建**平台主机器人**，获取 `BOT_TOKEN`。
2. 获取你自己的 Telegram 用户 ID（可用 [@userinfobot](https://t.me/userinfobot)）作为 `ADMIN_ID`（平台拥有者）。
3. 配置 `config.yaml` 或设置环境变量（环境变量优先）。

```bash
pip install -r requirements.txt
python main.py
```

启动后，任何用户都能私聊平台主机器人，用 `/newbot <token>` 创建自己的机器人。

### 环境变量

| 变量 | 说明 |
| --- | --- |
| `BOT_TOKEN` | 平台主机器人 Token |
| `ADMIN_ID` | 平台拥有者用户 ID |
| `DB_PATH` | SQLite 数据库路径（默认 `bot.db`） |

## 部署（Railway / Docker）

仓库已内置 `Dockerfile` 与 `railway.toml`，在平台上设置 `BOT_TOKEN`、`ADMIN_ID`
（以及挂载卷对应的 `DB_PATH`）即可一键部署。

## 架构

- `main.py` — 异步入口：启动平台主机器人，再由 `TenantManager` 并发拉起所有已创建的租户机器人。
- `core/tenant_manager.py` — 租户运行时：校验 Token、为每个租户构建独立 `Application` 并加载 `tenant_modules`。
- `modules/platform_module.py` — 机器人工厂命令（`/newbot` 等）。
- `modules/private_chat_module.py` — 双向私聊（DM / Topics）。
- `modules/auto_reply_module.py`、`menu_module.py`、`form_module.py`、`store_module.py` — 各功能模块。
- `core/database.py` — 多租户 SQLite 数据层，所有数据按 `tenant_id` 隔离。

## 配置文件 `config.yaml`

```yaml
bot:
  token:    "YOUR_PLATFORM_BOT_TOKEN"
  admin_id: 123456789
  name:     "双向私聊机器人工厂"

# 平台主机器人加载的模块
modules:
  - modules.platform_module

# 每个用户创建的机器人自动加载的功能模块
tenant_modules:
  - modules.private_chat_module
  - modules.auto_reply_module
  - modules.menu_module
  - modules.form_module
  - modules.store_module
```
