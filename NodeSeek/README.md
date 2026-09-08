# NodeSeek 每日签到

该项目使用用户本人账号 Cookie 调用 NodeSeek 签到接口，支持多账号、重复签到
幂等成功、有限重试和统一通知。

脚本不使用 Selenium、Chrome 或反检测工具，也不会尝试绕过 Cloudflare。若服务
拒绝青龙服务器的请求，脚本会返回明确失败结果，用户需在浏览器重新登录并更新
合法会话，或停止使用该自动化任务。

## 文件说明

```text
NodeSeek/
├── NodeSeek.py        # 青龙定时任务入口
├── README.md          # 配置与运行说明
└── requirements.txt   # Python 依赖
```

## 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `NODESEEK_COOKIES` | 是 | NodeSeek 登录 Cookie，多账号用 `|||` 分隔 |

单账号格式：

```text
session=<会话值>; pjwt=<令牌值>
```

多账号格式：

```text
session=<账号1>; pjwt=<账号1令牌>|||session=<账号2>; pjwt=<账号2令牌>
```

Cookie 字段可能随 NodeSeek 调整，以登录浏览器实际请求携带的 Cookie 为准。
不要在 README、Issue、任务命令或日志中填写真实值。

通知渠道使用根目录青龙官方 `notify.py` 的全局变量，例如 Telegram 的
`TG_BOT_TOKEN` 和 `TG_USER_ID`。项目脚本不会读取、重定义或覆盖通知变量。

## 青龙配置

1. 在青龙 **环境变量** 中创建 `NODESEEK_COOKIES`。
2. 确认 **依赖管理** 中已安装 Python3 依赖 `requests`。
3. 运行仓库订阅，让青龙自动创建任务。

手动任务命令：

```text
task <订阅唯一值>/NodeSeek/NodeSeek.py
```

脚本头部 Cron 为 `10 9 * * *`，即每天 09:10 执行。

## 本地验证

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r NodeSeek/requirements.txt
NODESEEK_COOKIES='session=<会话值>; pjwt=<令牌值>' \
  python3 NodeSeek/NodeSeek.py
```

## 执行行为

- 每个账号仅调用一次签到接口，重复签到视为成功。
- 网络错误、HTTP 429 和 5xx 最多尝试 3 次，单次超时 10 秒。
- HTTP 403 不重试，也不尝试规避 Cloudflare 防护。
- 单账号失败不会中止后续账号，最终可能返回 `PARTIAL_SUCCESS`。
- 日志与通知仅使用账号序号，不输出 Cookie 内容。

## 常见问题

### HTTP 403 或 Cloudflare 拒绝访问

重新登录 NodeSeek 并更新 Cookie。若 NodeSeek 不允许青龙服务器直接访问签到
接口，请停止任务；本项目不提供挑战绕过或浏览器反检测方案。

### 任务执行成功但没有通知

检查根 README 中的通用通知变量，并在青龙环境变量中至少配置一个通知渠道。
