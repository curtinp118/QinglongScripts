# 成都地铁积分签到

该集成使用成都地铁 App 的签到请求头调用积分签到接口，支持青龙多账号执行、
单账号失败隔离和统一通知。原 Quantumult X / Loon / Surge 脚本依赖代理持久化存储；
Python 版改用环境变量保存抓包后的请求头，不会在脚本中硬编码 Cookie 或 Token。

## 文件说明

```text
CDRail/
├── CDRail.py          # 青龙定时任务入口
├── README.md          # 配置与运行说明
└── requirements.txt   # Python 依赖
```

## 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `CDRAIL_HEADERS_JSON` | 是 | 抓包导出的完整请求头 JSON；多账号用 `|||` 分割 |

请求头至少需要 `Cookie` 或 `token` 字段。建议在成都地铁 App 中打开签到页面，
从请求 `https://app.cdmetro.chengdurail.cn/platform/users/user/sign-in-integral`
复制请求头，删除无关字段后保存为 JSON，再写入青龙环境变量。示例结构如下，
其中值必须替换为本人账号的实际凭证：

```json
{"Cookie":"替换为抓包得到的 Cookie","token":"替换为抓包得到的 token","device-id":"设备标识","app-version":"版本号"}
```

多账号示例：

```text
{"Cookie":"账号1 Cookie","token":"账号1 token"}|||{"Cookie":"账号2 Cookie","token":"账号2 token"}
```

不要把真实请求头写入 README、脚本、日志或 Git 提交。通知渠道继续使用根目录
`notify.py` 的全局变量，例如 `TG_BOT_TOKEN` 和 `TG_USER_ID`；本集成不会重定义这些变量。

## 青龙配置

定时任务命令：

```text
task <仓库目录>/CDRail/CDRail.py
```

默认 Cron 表达式为 `10 9 * * *`。依赖安装：

```bash
python3 -m pip install -r CDRail/requirements.txt
```

## 行为说明

- HTTP `401` / `403` 会标记为登录失效；其他非 2xx 状态标记为接口异常。
- 业务码 `0` 且消息为空或为 `SUCCESS` 视为签到成功；业务码 `1102` 视为今日已签到，
  两者均按幂等成功处理。
- 每次请求超时为 10 秒；单账号异常不会中断后续账号。
- 日志只显示账号序号和错误类型，不输出 Cookie、Token 或完整响应。
- 最终结果通过根目录 `notification_adapter.py` 生成标准 Payload 并交给青龙官方通知模块。
