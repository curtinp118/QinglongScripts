# GLaDOS 自动签到

该集成用于在青龙面板中执行 GLaDOS 多账号签到，并查询账号总积分和会员
剩余天数。脚本对单账号异常独立降级，最终构建仓库标准 Payload，通过根目录
`notification_adapter.py` 调用青龙官方 `notify.py`。

本次协议对照来源为
[Devilstore/Glados-Railgun-checkin](https://github.com/Devilstore/Glados-Railgun-checkin)
的 `4d3e1e5baea76086c43d7c02c2401b5639d2d715`（2026-11-11，北京时间）：
适配 challenge 流程与网页签到结果判定，同时保留本仓库已有的青龙配置、统一通知
和兑换防重复限制。

## 文件说明

```text
GLaDOS/
├── GLaDOS.py          # 青龙定时任务入口
├── README.md          # 配置与运行说明
└── requirements.txt   # Python 依赖
```

## 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `GLADOS_COOKIES` | 是 | 推荐账号 JSON 数组；兼容 Cookie 用 `|||`、`&` 或换行分隔 |
| `GLADOS_DOMAINS` | 否 | 候选服务域名，用 `|||` 分隔；未设置时按下方顺序探测内置域名 |
| `GLADOS_EXCHANGE_PLAN` | 否 | `plan100`、`plan200` 或 `plan500`，默认关闭 |
| `GLADOS_USER_AGENT` | 否 | 所有账号的默认 User-Agent；账号 JSON 的 `user-agent` 优先 |
| `QL_RANDOM_DELAY_ENABLED` | 否 | 是否启用任务启动随机延迟，默认 `true` |
| `QL_RANDOM_DELAY_MIN_SECONDS` | 否 | 最小延迟秒数，默认 `0` |
| `QL_RANDOM_DELAY_MAX_SECONDS` | 否 | 最大延迟秒数，默认 `300` |
| `QL_LOG_LEVEL` | 否 | 日志级别，默认 `INFO`；支持 `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` |

推荐将 `GLADOS_COOKIES` 配置为账号对象数组：

```json
[
  {
    "name": "主号",
    "origin": "glados.cloud",
    "cookie": "gld:sess=<会话值>; gld:sess.sig=<签名值>",
    "user-agent": "复制获取 Cookie 时浏览器的完整 User-Agent"
  },
  {
    "name": "小号",
    "origin": "railgun.info",
    "cookie": "koa:sess=<会话值>; koa:sess.sig=<签名值>"
  }
]
```

只有 `cookie` 必填，`name`、`origin` 和 `user-agent` 可省略；所有字段必须是字符串，
不接受未知字段。`origin` 只接受纯主机名或 `https://` 加纯主机名。
相同的 Cookie 会去重，避免重复签到。

未设置 `GLADOS_DOMAINS` 时，探测顺序为 `glados.cloud` → `railgun.info` →
`glados.network` → `glados.rocks` → `glados.one` → `glados.space` →
`glados.vip` → `glados-facility.com`。设置后仅使用指定的候选列表。
每个账号优先探测自己的 `origin`，然后回退候选列表；命中登录状态后停止探测，
只在该域名签到，最终每个账号只生成一条结果。

`GLADOS_DOMAINS` 也支持显式配置的自定义 HTTPS 域名。
自定义值只允许纯主机名，不接受路径、端口、用户信息或 HTTP；
配置 `GLADOS_DOMAINS` 或账号的 `origin` 前须确认该域名可信，因为脚本会将
GLaDOS Cookie 发送给它。请求不会自动跟随重定向。

Cookie 必须包含同一前缀成对的 `:sess` 和 `:sess.sig` 字段。GLaDOS 当前常见的
前缀是 `gld:`，旧版账号可能仍是 `koa:`；脚本不会改写前缀：

```text
gld:sess=<账号1>; gld:sess.sig=<签名1>|||koa:sess=<账号2>; koa:sess.sig=<签名2>
```

也可以直接粘贴带 `Cookie:` 头名或首尾引号的整行，脚本会自动清理这些复制痕迹。
脚本不会输出 Cookie，只在日志中显示账号序号、备注名和已校验的服务域名。通知渠道使用
青龙官方 `notify.py` 的环境变量，例如 Telegram 的 `TG_BOT_TOKEN` 和
`TG_USER_ID`；业务脚本不会重定义或覆盖这些全局变量。

## 青龙配置

定时任务命令：

```text
task <仓库目录>/GLaDOS/GLaDOS.py
```

默认 Cron 表达式为 `0 8 * * *`。

安装依赖：

```text
requests
```

青龙通常已包含该依赖；如使用独立 Python 环境，可运行：

```bash
python3 -m pip install -r GLaDOS/requirements.txt
```

## 行为说明

- 每次签到前先请求 `/api/user/checkin/challenge`，获取 `nonce`，等待 2.5 秒后，
  用 JSON 提交 `token`、`nonce` 和 `proof`。proof 按上游协议计算为
  `SHA256(nonce + ".glados-observe-v1")`。challenge 与签到使用同一会话和 UA。
- challenge 不可用时，回退为只包含 `token` 的旧版表单请求；服务端可能降低积分，
  是否接受该请求由服务端决定。
- 签到判定对齐网页：先排除域名拒绝和设备不匹配，再优先处理布尔字段
  `repeated`，然后处理 `code`，最后兼容 `checkedIn=true`。
  `repeated=true` 或正常的“今日已签到”视为幂等成功，本次获得积分记为 0。
  `code=0` 但消息为 `please checkin via ...` 时仍然判定失败。
  不再仅凭消息包含“got points”或“already”等片段判定成功。
- 本次积分优先读取 `points`，其次读取 `list[0].change`，最后兼容旧版消息中的积分。
- 未指定 UA 时使用 Windows Chrome 默认值；服务端明确返回
  `code=4`、`reason=device-mismatch` 时，按 `loginDevice` 切换对应平台 UA，
  重新获取 challenge 并只重试一次。显式配置的 UA 不会自动改写。
- 设备校验仍失败时，在获取 Cookie 的浏览器中复制完整 User-Agent，
  设置到账号 JSON 的 `user-agent` 或全局 `GLADOS_USER_AGENT`。
  `Automated check-in detected` 也可能与网络、设备等服务端规则有关，
  challenge 流程不保证获得特定积分。
- 单次请求超时为 10 秒；challenge 和剩余天数查询遇到网络错误、
  HTTP 429、5xx 或非 JSON 响应时最多尝试 3 次。
- 登录域名探测和积分查询每次只请求一次；签到提交不自动重放，
  避免响应丢失后复用已经消费的 nonce；网络异常可在下一轮重新获取 challenge。
- 业务请求前默认随机等待 0 至 300 秒；可通过全局随机延迟变量关闭或调整范围。
- 单账号失败不会中止后续账号，最终状态可能为 `PARTIAL_SUCCESS`。
- 自动兑换默认关闭；启用后仅在本次新签到成功时尝试兑换。
- 兑换以表单提交 `planType`，请求不重试，避免响应丢失导致重复扣分。
- 重跑返回“今日已签到”时会跳过兑换，避免同一天重复兑换。
- 积分不足时跳过兑换；兑换接口失败会在账号结果中标记失败。
- 不在集成内实现任何通知渠道，所有推送统一交给官方 `notify.py`。

## 离线验证

安装本集成依赖后，在仓库根目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_glados.py' -v
```

测试通过模拟 HTTP 响应覆盖 challenge、旧协议降级、设备重试、网页状态判定、
域名选择、积分兑换与多账号通知，不请求真实账号或发送通知。
