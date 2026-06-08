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
- 🔁 **双向私聊**：用户 ↔ 管理员消息中转，支持所有消息类型（含**相册/媒体组**，会聚合后整体转发，不再拆散）。
  - **DM 模式**：消息直接转发到管理员私聊，回复任意历史消息精准送达。
  - **Topics 模式**：把机器人加入一个开启「主题」的超级群，每个用户对应一个独立主题，便于多管理员协作。
- 🤖 **自动回复 + 关键词过滤**：按关键词自动回复；命中过滤词的消息可拦截、不转发。
- 🧭 **菜单 / 子菜单**：用内联按钮逐层搭建机器人菜单树。
- 📝 **引导式表单**：分步骤收集用户信息并保存。
- 🛒 **数字商店**：分类 / 商品 / 购物车 / 下单。
- ⛔ 封禁 / 解封、用户资料、统计。
- 🎛️ **一站式控制面板**：拥有者 `/panel`（或 `/start`）即可直达自动回复、启动语、群发、安全过滤与 Topics 协作等常用功能，全程点按钮、无需记忆指令；用户 `/start` 自动显示功能导航按钮，少打字、好上手。

## 使用方式

### 1. 平台主机器人指令

| 指令 | 说明 |
| --- | --- |
| `/start`、`/help` | 显示图文引导（内联按钮：如何创建 / 我的机器人 / 常见问题） |
| `/newbot <token>` | 用 @BotFather 给的 Token 创建你自己的机器人（立即上线）；也可只发 `/newbot`，再直接粘贴 Token |
| `/mybots` | 查看你创建的机器人列表，并可一键分享 |
| `/delbot <id>` | 删除某个机器人 |

> 💡 平台主机器人与每个租户机器人启动时都会通过 `set_my_commands` 注册「/」命令菜单，
> 在输入框旁即可看到可用命令；租户机器人会为拥有者额外展示管理命令。
> 创建成功后会给出「三步上手」引导与「分享我的机器人」按钮，便于传播。

### 2. 租户机器人 —— 管理员（机器人拥有者）指令

> 在你创建的机器人里使用。回复类指令需「回复」对应的用户消息。

> 💡 **推荐**：在你的机器人里发送 `/panel`（或 `/start`），即可打开**控制面板**，
> 用按钮直达自动回复、启动语、群发、强制订阅，并一键开关防刷屏 / 英文拦截、查看
> Topics 状态与指令速查，无需记忆命令。

**双向私聊**

| 指令 | 说明 |
| --- | --- |
| `/start`、`/help` | 帮助，并显示 **⚙️ 控制面板** 按钮 |
| `/panel` | 打开一站式控制面板（自动回复 / 启动语 / 群发 / 一键开关 / Topics 状态 / 指令速查） |
| `/ban`、`/unban`（回复或带用户ID） | 封禁 / 解封用户 |
| `/info`（回复） | 查看用户资料 |
| `/stats` | 用户统计 |
| `/setgroup` | 在开启主题的超级群内运行，切换到 Topics 模式 |
| `/unsetgroup` | 取消 Topics 模式，回到 DM 模式 |

**自动回复 / 过滤**

| 指令 | 说明 |
| --- | --- |
| `/ar_add <关键词> \| <回复内容>` | 添加自动回复（回复内容前加 `!` 表示命中后不再转发） |
| `/ar_list`、`/ar_del <id>` | 列出 / 删除自动回复 |
| `/filter_add <关键词>` | 添加过滤词（命中则拦截） |
| `/filter_list`、`/filter_del <id>` | 列出 / 删除过滤词 |
| `/antiflood on｜off` | 防刷屏过滤器开关（默认开启） |
| `/alphabet_latin on｜off` | 屏蔽含拉丁字母（英文）的消息（默认关闭） |

**菜单**

| 指令 | 说明 |
| --- | --- |
| `/menu_add <父ID> \| <按钮文字> \| <内容(可选)>` | 添加菜单项（父ID 为 0 表示顶级） |
| `/menu_list`、`/menu_del <id>` | 列出 / 删除菜单项 |

**表单**

| 指令 | 说明 |
| --- | --- |
| `/form_new <表单名>` | 新建表单 |
| `/form_step <表单ID> \| <提问>` | 给表单添加一步提问 |
| `/form_list`、`/form_del <id>` | 列出 / 删除表单 |

**数字商店**

| 指令 | 说明 |
| --- | --- |
| `/shop_addcat <名称>` | 添加商品分类 |
| `/shop_addproduct <分类ID> \| <名称> \| <价格> \| <描述(可选)>` | 添加商品 |
| `/shop_list` | 列出分类与商品 |
| `/shop_delcat <id>`、`/shop_delproduct <id>` | 删除分类 / 商品 |

### 3. 租户机器人 —— 普通用户指令

> 💡 用户发送 `/start` 后，会根据机器人已配置的内容自动显示
> **📋 浏览菜单 / 📝 填写表单 / 🛒 进入商店** 等导航按钮，点击即可，无需记忆命令。

| 指令 | 说明 |
| --- | --- |
| `/start` | 开始私聊（消息转发给管理员），并显示可用功能导航按钮 |
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
| `LOG_LEVEL` | 日志级别（`DEBUG`/`INFO`/`WARNING`/`ERROR`，默认 `INFO`） |
| `TENANT_STARTUP_CONCURRENCY` | 启动时并发拉起租户机器人的上限（默认 `10`） |

## 稳定性与性能

平台对每个机器人（平台主机器人与所有租户机器人）统一应用以下策略，由
`core/app_factory.py` 集中构建：

- **并发处理**：启用 `concurrent_updates`，单机器人内多用户消息并行处理。
- **内置限流**：若安装了 `python-telegram-bot[rate-limiter]`（已写入 `requirements.txt`），
  自动启用 `AIORateLimiter` 处理 429 / flood control 重试，降低触发 Telegram 限制的风险；
  未安装时自动跳过、不影响运行。
- **全局错误处理**：统一捕获并记录各机器人未捕获的异常，避免单条更新崩溃。
- **SQLite 加固**：开启 WAL、`busy_timeout` 与外键约束，缓解多租户并发下的 `database is locked`。
- **结构化日志**：使用 `logging`（含 Bot Token 自动脱敏），便于平台侧排查。
- **批量启动**：`TenantManager.load_all` 以信号量受控并发启动已有租户机器人。

> 💡 **高级表情（Premium Emoji）**：双向中转使用 `copy_message`/`copy_messages`，
> 会原样保留自定义表情、相册与清单等富内容；前提是机器人拥有者账号已开通 Telegram Premium。

## 开发与测试

```bash
pip install -r requirements.txt ruff pytest pytest-asyncio
ruff check .      # 代码风格检查
pytest -q         # 运行单元测试（中转 / 过滤器 / 数据库 / 工厂）
```

CI 工作流见 `.github/workflows/ci.yml`，会在 push / PR 时自动运行 ruff 与 pytest。

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

# 租户机器人提示文案（可选 brand 为品牌署名页脚，留空表示关闭）
messages:
  welcome: "👋 你好！直接发送消息即可联系管理员，我们会尽快回复你。"
  brand:   ""
```
