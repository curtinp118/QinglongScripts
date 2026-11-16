# 通知与运行配置

[返回首页](../README.md) · [订阅说明](subscription.md)

运行控制变量由 `runtime_control.py` 读取，通知渠道变量由实际导入的青龙官方
`notify.py` 读取。各项目使用服务专属前缀管理账号配置，不覆盖公共变量。
推荐订阅使用面板提供的通知模块；下表渠道以仓库副本为参考，不同版本以实际模块为准。

## 全局控制

| 变量 | 说明 |
| --- | --- |
| `QL_RANDOM_DELAY_ENABLED` | 是否在业务请求前随机延迟，默认 `true`；支持 `true/false`、`1/0`、`yes/no`、`on/off` |
| `QL_RANDOM_DELAY_MIN_SECONDS` | 随机延迟下限，默认 `0` 秒，支持 `0` 至 `86400` 的整数 |
| `QL_RANDOM_DELAY_MAX_SECONDS` | 随机延迟上限，默认 `300` 秒，支持 `0` 至 `86400` 的整数且不得小于下限 |
| `QL_LOG_LEVEL` | 日志级别，默认 `INFO`；支持 `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` |
| `HITOKOTO` | 是否在通知末尾附加一言，设置为 `false` 可关闭 |
| `CONSOLE` | 是否启用控制台通知输出 |
| `SKIP_PUSH_TITLE` | 按通知标题跳过推送，多个标题使用换行分隔 |

业务脚本日志只输出任务阶段、账号序号/域名、状态和错误类型，不输出 Cookie、Token
或完整响应。预期的网络和账号失败不会打印 traceback；需要排查未预期异常时，将青龙
变量 `QL_LOG_LEVEL` 设为 `DEBUG`；部分异常处理分支会附加 traceback。
该级别只用于业务日志，`requests` / `urllib3` 保持 `WARNING`，避免其请求调试日志
输出包含通知 Token、接收人和正文的完整 URL。DEBUG traceback 仍可能带有异常上下文，
对外分享前应检查并脱敏。

## 通知渠道

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
| WxPusher | `WXPUSHER_APP_TOKEN`，并填写 `WXPUSHER_TOPIC_IDS` / `WXPUSHER_UIDS` 至少一项 | - |
| WxPusher SPT | `WXPUSHER_SPT_LIST` | - |
| OpeniLink | `OPENILINK_APP_TOKEN` | `OPENILINK_HUB_URL`, `OPENILINK_CONTEXT_TOKEN` |

通知凭证必须通过青龙环境变量注入，禁止写入脚本、README、日志或提交记录。

## 通知状态

| 状态 | 说明 |
| --- | --- |
| `SUCCESS` | 全部账号任务执行成功 |
| `PARTIAL_SUCCESS` | 部分账号成功、部分账号失败 |
| `FAILED` | 所有账号失败或配置检查未通过 |

通知正文包含执行时间、账号结果和汇总信息。账号显示名称可以明文展示，
账号凭证不得主动加入通知 Payload；接口返回消息也应先脱敏。
排查问题时不要分享含凭证的响应。

## 执行结果与通知送达

业务入口在全部账号成功且通知调用未抛出异常时返回 `0`，配置失败、部分账号失败、
全部账号失败或通知调用抛出异常时返回 `1`。青龙默认 Shell 包装器可能不透传脚本退出码，
排查时应结合任务日志与通知中的状态，不能只看面板的运行完成提示。

官方 `notify.send` 不返回统一的渠道送达结果，部分推送失败会在内部处理并输出日志，
因此通知调用未抛出异常不等于接收端已经收到消息。

只在控制台查看汇总时设置 `CONSOLE=true`。设置 `HITOKOTO=false` 可以关闭通知末尾的
一言附加内容及相应外部请求。`SKIP_PUSH_TITLE` 按完整通知标题匹配，本仓库的标题包含
适配器添加的 `🔔 ` 前缀，例如 `🔔 V2EX 每日签到`。

## 凭证管理

- 在可信面板的环境变量中保存账号及通知凭证，确认变量已启用。
- 不要在 README、Issue、日志截图或 Git 提交中填写真实值。
- Cookie / Token 失效后按对应项目文档更新，不要通过任务命令传递凭证。
- 配置自定义服务域名前确认其归属，因为该地址会收到对应账号凭证。
