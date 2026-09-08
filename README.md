# QingLong 自动化脚本索引

本仓库用于组织青龙面板可调度的 Python、JavaScript 和 Shell 自动化脚本。
项目专属配置请查看对应子目录的 `README.md`。

## 项目索引

| 项目 | 入口脚本 | 配置文档 | 说明 |
| --- | --- | --- | --- |
| GLaDOS | [`GLaDOS/GLaDOS.py`](./GLaDOS/GLaDOS.py) | [`GLaDOS/README.md`](./GLaDOS/README.md) | 多账号签到、积分查询与可选兑换 |

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
