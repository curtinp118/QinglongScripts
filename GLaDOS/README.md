# GLaDOS 自动签到

该集成用于在青龙面板中执行 GLaDOS 多账号签到，并查询账号总积分和会员
剩余天数。脚本对单账号异常独立降级，最终构建仓库标准 Payload，通过根目录
`notification_adapter.py` 调用青龙官方 `notify.py`。

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
| `GLADOS_COOKIES` | 是 | GLaDOS Cookie，多账号用 `|||` 分隔 |
| `GLADOS_DOMAINS` | 否 | 服务域名，多域名用 `|||` 分隔，默认 `glados.cloud` |
| `GLADOS_EXCHANGE_PLAN` | 否 | `plan100`、`plan200` 或 `plan500`，默认关闭 |

`GLADOS_DOMAINS` 支持 `glados.cloud`、`railgun.info` 和显式配置的自定义
HTTPS 域名。自定义值只允许纯主机名，不接受路径、端口、用户信息或 HTTP；
配置前须确认该域名可信，因为脚本会将 GLaDOS Cookie 发送给它。

Cookie 必须包含 `koa:sess` 和 `koa:sess.sig`：

```text
koa:sess=<账号1>; koa:sess.sig=<签名1>|||koa:sess=<账号2>; koa:sess.sig=<签名2>
```

脚本不会输出 Cookie，只在日志中显示账号序号和已校验的服务域名。通知渠道使用
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

- 签到接口识别“签到成功”和“今日已签到”，两者均视为幂等成功。
- 单次请求超时为 10 秒；网络错误、HTTP 429 和 5xx 最多尝试 3 次。
- 单账号失败不会中止后续账号，最终状态可能为 `PARTIAL_SUCCESS`。
- 自动兑换默认关闭；启用后仅在本次新签到成功时尝试兑换。
- 重跑返回“今日已签到”时会跳过兑换，避免同一天重复兑换。
- 积分不足时跳过兑换；兑换接口失败会在账号结果中标记失败。
- 不在集成内实现任何通知渠道，所有推送统一交给官方 `notify.py`。
