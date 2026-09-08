# QinglongScripts

面向青龙面板的自动化脚本仓库。项目按服务独立组织，统一使用环境变量管理
账号配置，并通过青龙官方通知模块发送结构化执行结果。

> 脚本仅供学习交流。使用前请阅读对应项目文档并自行评估账号、接口和自动化
> 操作风险，禁止用于商业用途或违反目标服务条款的场景。

## 特性

- 支持青龙面板订阅、自动更新和定时任务发现；
- 多账号使用 `|||` 分隔，单账号失败不会中断后续账号；
- Cookie、Token 等敏感信息仅通过环境变量注入；
- 日志自动避免输出完整凭证；
- 通知统一调用青龙官方 `notify.py`；
- 每个项目独立维护入口脚本、依赖声明和配置文档。

## 快速开始

### 添加仓库订阅

进入青龙面板的 **订阅管理**，选择 **创建订阅**，按下表填写：

| 字段 | 推荐值 |
| --- | --- |
| 名称 | `QinglongScripts` |
| 类型 | `公开仓库` |
| 链接 | `https://github.com/curtinp118/QinglongScripts.git` |
| 分支 | `main` |
| 定时类型 | `crontab` |
| 定时规则 | `0 3 * * *` |
| 白名单 | `GLaDOS|NodeSeek` |
| 黑名单 | 留空 |
| 依赖文件 | `notification_adapter|notify` |
| 文件后缀 | `py` |
| 自动添加任务 | 开启 |
| 自动删除任务 | 开启 |

也可以将以下命令完整粘贴到创建订阅窗口，青龙会自动解析仓库参数；定时规则
仍需在表单中填写：

```bash
ql repo "https://github.com/curtinp118/QinglongScripts.git" "GLaDOS|NodeSeek" "" "notification_adapter|notify" "main" "py"
```

白名单决定哪些入口脚本参与自动建任务；依赖文件只负责复制公共模块，不会创建
定时任务。后续订阅多个项目时，在白名单中使用 `|` 分隔项目目录名。白名单、
黑名单和依赖文件均支持关键词或正则表达式。

创建完成后手动运行一次订阅，确认日志显示仓库拉取成功。后续由订阅定时规则
自动获取更新。

### 安装 Python 依赖

本仓库当前统一依赖 `requests`。青龙通常已包含该库；若任务提示缺少模块，进入
**依赖管理**，创建类型为 `Python3`、名称为 `requests` 的依赖。

使用独立 Python 环境时，可执行：

```bash
python3 -m pip install -r requirements.txt
```

### 配置项目变量

进入青龙面板的 **环境变量** 页面，按照项目文档创建变量。不要把 Cookie、
Token 或 Secret 直接写入脚本或定时任务命令。

| 项目 | 配置文档 |
| --- | --- |
| GLaDOS | [`GLaDOS/README.md`](./GLaDOS/README.md) |
| NodeSeek | [`NodeSeek/README.md`](./NodeSeek/README.md) |

### 运行任务

订阅成功后，青龙会读取入口脚本顶部小写的 `name:` 和 `cron:`，自动生成任务
名称与定时规则。若当前版本未自动创建，可在 **定时任务** 中手动添加：

```text
task <订阅唯一值>/GLaDOS/GLaDOS.py
task <订阅唯一值>/NodeSeek/NodeSeek.py
```

`<订阅唯一值>` 以订阅管理页面实际显示的值为准。首次运行建议先查看完整日志，
确认环境变量、目标域名和通知渠道配置正确。

## 项目索引

| 项目 | 入口脚本 | 配置文档 | 说明 |
| --- | --- | --- | --- |
| GLaDOS | [`GLaDOS/GLaDOS.py`](./GLaDOS/GLaDOS.py) | [`GLaDOS/README.md`](./GLaDOS/README.md) | 多账号签到、积分查询与可选兑换 |
| NodeSeek | [`NodeSeek/NodeSeek.py`](./NodeSeek/NodeSeek.py) | [`NodeSeek/README.md`](./NodeSeek/README.md) | 多账号每日签到 |

## 公共文件索引

| 文件 | 说明 |
| --- | --- |
| [`requirements.txt`](./requirements.txt) | 全部 Python 脚本的依赖汇总 |
| [`notify.py`](./notify.py) | 青龙面板官方 Python 通知模块 |
| [`notification_adapter.py`](./notification_adapter.py) | 标准 Payload 到官方通知接口的适配器 |

## 通用变量

以下变量由根目录青龙官方 `notify.py` 统一读取，属于全局保留变量。各项目脚本
不得重定义、覆盖或改用项目专属前缀。未使用的通知渠道无需配置。

### 全局控制

| 变量 | 说明 |
| --- | --- |
| `HITOKOTO` | 是否在通知末尾附加一言，设置为 `false` 可关闭 |
| `CONSOLE` | 是否启用控制台通知输出 |
| `SKIP_PUSH_TITLE` | 按通知标题跳过推送，多个标题使用换行分隔 |

### 通知渠道

| 渠道 | 主要变量 | 可选变量 |
| --- | --- | --- |
| Bark | `BARK_PUSH` | `BARK_ARCHIVE`, `BARK_GROUP`, `BARK_SOUND`, `BARK_ICON`, `BARK_LEVEL`, `BARK_URL` |
| 钉钉机器人 | `DD_BOT_TOKEN` | `DD_BOT_SECRET` |
| 飞书机器人 | `FSKEY` | `FSSECRET` |
| go-cqhttp | `GOBOT_URL`, `GOBOT_QQ` | `GOBOT_TOKEN` |
| Gotify | `GOTIFY_URL`, `GOTIFY_TOKEN` | `GOTIFY_PRIORITY` |
| iGot | `IGOT_PUSH_KEY` | - |
| Server 酱 | `PUSH_KEY` | - |
| PushDeer | `DEER_KEY` | `DEER_URL` |
| Synology Chat | `CHAT_URL`, `CHAT_TOKEN` | - |
| PushPlus | `PUSH_PLUS_TOKEN` | `PUSH_PLUS_USER`, `PUSH_PLUS_TEMPLATE`, `PUSH_PLUS_CHANNEL`, `PUSH_PLUS_WEBHOOK`, `PUSH_PLUS_CALLBACKURL`, `PUSH_PLUS_TO` |
| 微加机器人 | `WE_PLUS_BOT_TOKEN`, `WE_PLUS_BOT_RECEIVER` | `WE_PLUS_BOT_VERSION` |
| Qmsg 酱 | `QMSG_KEY`, `QMSG_TYPE` | - |
| 企业微信应用 | `QYWX_AM` | `QYWX_ORIGIN` |
| 企业微信机器人 | `QYWX_KEY` | - |
| Telegram | `TG_BOT_TOKEN`, `TG_USER_ID` | `TG_API_HOST`, `TG_PROXY_AUTH`, `TG_PROXY_HOST`, `TG_PROXY_PORT` |
| 智能微秘书 | `AIBOTK_KEY`, `AIBOTK_TYPE`, `AIBOTK_NAME` | - |
| SMTP 邮件 | `SMTP_SERVER`, `SMTP_EMAIL`, `SMTP_PASSWORD`, `SMTP_NAME` | `SMTP_SSL`, `SMTP_EMAIL_TO` |
| PushMe | `PUSHME_KEY` | `PUSHME_URL` |
| Chronocat | `CHRONOCAT_URL`, `CHRONOCAT_QQ`, `CHRONOCAT_TOKEN` | - |
| 自定义 Webhook | `WEBHOOK_URL`, `WEBHOOK_METHOD` | `WEBHOOK_BODY`, `WEBHOOK_HEADERS`, `WEBHOOK_CONTENT_TYPE` |
| ntfy | `NTFY_TOPIC` | `NTFY_URL`, `NTFY_PRIORITY`, `NTFY_TOKEN`, `NTFY_USERNAME`, `NTFY_PASSWORD`, `NTFY_ACTIONS` |
| WxPusher | `WXPUSHER_APP_TOKEN` | `WXPUSHER_TOPIC_IDS`, `WXPUSHER_UIDS` |
| WxPusher SPT | `WXPUSHER_SPT_LIST` | - |
| OpeniLink | `OPENILINK_APP_TOKEN` | `OPENILINK_HUB_URL`, `OPENILINK_CONTEXT_TOKEN` |

通知凭证必须通过青龙环境变量注入，禁止写入脚本、README、日志或提交记录。

## 通知状态

| 状态 | 说明 |
| --- | --- |
| `SUCCESS` | 全部账号任务执行成功 |
| `PARTIAL_SUCCESS` | 部分账号成功、部分账号失败 |
| `FAILED` | 所有账号失败或配置检查未通过 |

通知正文包含执行时间、账号结果和汇总信息。账号显示名称可以明文展示，Cookie、
Token、签名等认证数据不会进入通知 Payload。

## 常见问题

### 订阅成功但没有生成任务

确认订阅中的“自动添加任务”已开启，并检查订阅日志是否拉取了 `py` 文件。
仍未生成时，可按上文示例手动创建定时任务。

### 提示 `ModuleNotFoundError: requests`

在青龙 **依赖管理** 中安装 Python3 依赖 `requests`，安装完成后重新运行任务。

### 日志提示“无推送渠道”

至少配置一种本页列出的官方通知渠道变量。仅需在日志中查看通知时，可设置
`CONSOLE=true`；不需要一言内容时，可设置 `HITOKOTO=false`。

### 更新后任务路径发生变化

检查订阅的“唯一值”和分支是否被修改。手动任务命令必须使用当前订阅唯一值，
推荐开启自动添加、自动删除任务，让青龙随订阅同步任务路径。

## 安全说明

- 仅在可信青龙实例中保存账号凭证，并限制面板公网访问；
- 定期轮换 Cookie、Token 和通知密钥；
- 不要在 Issue、日志截图或聊天记录中提交完整环境变量；
- 自定义服务域名会接收对应账号 Cookie，配置前必须确认其归属与可信性；
- 建议使用青龙最新稳定版本，并在升级后先检查订阅与任务日志。

## 相关链接

- [青龙面板](https://github.com/whyour/qinglong)
- [青龙官方文档](https://qinglong.online)
- [青龙官方 notify.py](https://github.com/whyour/qinglong/blob/develop/sample/notify.py)
