# V2EX 每日签到

该项目使用用户本人账号 Cookie 访问 V2EX 每日任务页面，领取每日登录奖励并查询
账户余额。支持多账号、重复执行幂等成功、有限重试和统一通知。

V2EX API 2.0 当前未提供每日任务接口，因此脚本使用官方网页流程。脚本不会模拟
账号密码登录，也不会尝试绕过验证码、Cloudflare 或其他访问控制。

## 文件说明

```text
V2EX/
├── V2EX.py            # 青龙定时任务入口
├── README.md          # 配置与运行说明
└── requirements.txt   # Python 依赖
```

## 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `V2EX_COOKIES` | 是 | V2EX 登录 Cookie，多账号用 `|||` 分隔 |

单账号格式：

```text
PB3_SESSION=<会话值>; A2=<认证值>
```

多账号格式：

```text
PB3_SESSION=<账号1会话>; A2=<账号1认证>|||PB3_SESSION=<账号2会话>; A2=<账号2认证>
```

Cookie 字段可能随 V2EX 调整，脚本会完整使用环境变量中提供的 Cookie，不限定字段
名称。不要在 README、Issue、任务命令或日志中填写真实值。

通知渠道使用根目录青龙官方 `notify.py` 的全局变量，例如 Telegram 的
`TG_BOT_TOKEN` 和 `TG_USER_ID`。项目脚本不会读取、重定义或覆盖通知变量。

## 获取 Cookie

1. 在可信浏览器中登录 `https://www.v2ex.com`。
2. 打开开发者工具的 **Network** 面板，访问 `/mission/daily`。
3. 在该请求的 **Request Headers** 中找到 `Cookie`，仅将其值配置到青龙环境变量
   `V2EX_COOKIES`。

Cookie 等同于登录凭证，应只保存在受控的青龙实例中。失效后重新登录并更新，
不要通过聊天、Issue 或日志分享。

## 青龙配置

1. 在青龙 **环境变量** 中创建 `V2EX_COOKIES`。
2. 确认 **依赖管理** 中已安装 Python3 依赖 `requests`。
3. 运行仓库订阅，让青龙自动创建任务。

手动任务命令：

```text
task <订阅唯一值>/V2EX/V2EX.py
```

脚本头部 Cron 为 `20 9 * * *`，即每天 09:20 执行。V2EX 的每日奖励按 UTC
日期计算，北京时间 08:00 后才进入新的一天，因此默认时间留出了缓冲。

## 本地验证

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r V2EX/requirements.txt
V2EX_COOKIES='PB3_SESSION=<会话值>; A2=<认证值>' \
  python3 V2EX/V2EX.py
```

## 执行行为

- 每个账号先读取每日任务页面，已领取时不会再次提交领取请求。
- 只读页面遇到网络错误、HTTP 429 或 5xx 时最多尝试 3 次，单次超时 10 秒。
- 领取请求不做盲目网络重试；响应不确定时重新读取每日任务页面确认状态。
- V2EX 明确要求再次点击时，脚本最多执行一次额外领取请求。
- 单账号失败不会中止后续账号，最终可能返回 `PARTIAL_SUCCESS`。
- 日志与通知仅使用账号序号，不输出 Cookie 内容。

## 常见问题

### 提示登录状态无效

在浏览器重新登录 V2EX，并更新 `V2EX_COOKIES`。确认复制的是完整 Cookie 值，
且多账号之间使用 `|||` 分隔。

### 无法获取领取链接

V2EX 页面结构可能发生变化，或者当前语言页面未返回预期内容。请先在浏览器确认
`/mission/daily` 页面可以正常打开；本项目不提供验证码或访问控制绕过方案。

### 任务执行成功但没有通知

检查根 README 中的通用通知变量，并在青龙环境变量中至少配置一个通知渠道。

## 相关链接

- [V2EX 每日登录奖励说明](https://www.v2ex.com/t/67463)
- [V2EX API 2.0](https://www.v2ex.com/help/api)
