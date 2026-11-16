# QinglongScripts

面向 [青龙面板](https://github.com/whyour/qinglong) 的 Python 自动化脚本。
每个服务独立维护入口、配置文档和依赖声明，共用日志、随机延迟和通知适配器。

> 仅供学习交流。使用前请阅读对应服务文档并评估账号和自动化操作风险，
> 禁止用于商业用途或违反目标服务条款的场景。Cookie、Token 等凭证仅通过环境变量配置。

## 脚本索引

| 项目 | 入口 | 配置文档 | 默认执行时间¹ | 功能 |
| --- | --- | --- | --- | --- |
| GLaDOS | [GLaDOS.py](GLaDOS/GLaDOS.py) | [配置说明](GLaDOS/README.md) | 每天 08:00 | 多账号签到、积分查询、可选兑换 |
| V2EX | [V2EX.py](V2EX/V2EX.py) | [配置说明](V2EX/README.md) | 每天 09:20 | 每日登录奖励、账户余额查询 |
| 成都地铁 | [CDRail.py](CDRail/CDRail.py) | [配置说明](CDRail/README.md) | 每天 09:10 | App 积分签到 |

¹ 时间按面板时区解释；业务请求前默认还会随机等待 0～300 秒。面板使用北京时间时，
请确认时区为 `Asia/Shanghai`。V2EX 的默认时间按北京时间安排。

## 在青龙中使用

### 1. 添加仓库订阅

进入 **订阅管理 → 创建订阅**，填写以下配置。正则表达式应复制为单行，
保留其中的 `|`、括号、反斜杠和 `$`；表单中的值不需要外层引号。

| 字段 | 推荐值 |
| --- | --- |
| 名称 | `QinglongScripts` |
| 类型 | 公开仓库 |
| 链接 | `https://github.com/curtinp118/QinglongScripts.git` |
| 分支 | `main` |
| 定时类型 | `crontab` |
| 定时规则 | `0 3 * * *`（每天 03:00 拉取更新） |
| 白名单 | `^(GLaDOS/GLaDOS\|V2EX/V2EX\|CDRail/CDRail)\.py$` |
| 黑名单 | `(^\|/)(notify\|notification_adapter\|runtime_control)\.py$` |
| 依赖文件 | `^(notification_adapter\|runtime_control)\.py$` |
| 文件后缀 | `py`（不带点） |
| 自动添加任务 | 开启 |
| 自动删除任务 | 开启；修改筛选条件时会清理被移出的任务 |
| 执行前 / 执行后 / 代理 | 按需配置，无需时留空 |

白名单只选中三个业务入口。依赖文件会另外复制两个公共模块，且不会将它们建成任务。
青龙自带的 `notify.py` 会放入订阅脚本目录供适配器使用，推荐配置无需再次拉取仓库副本。
“依赖文件”指仓库内的文件，Python 包需要在下一步单独安装。

支持命令粘贴导入的面板版本，可复制以下**完整单行**命令到创建订阅窗口：

```bash
ql repo "https://github.com/curtinp118/QinglongScripts.git" "^(GLaDOS/GLaDOS|V2EX/V2EX|CDRail/CDRail)\.py$" "(^|/)(notify|notification_adapter|runtime_control)\.py$" "^(notification_adapter|runtime_control)\.py$" "main" "py"
```

导入后核对表单，并补全名称、定时规则和自动添加 / 删除开关；命令不包含这些表单设置。
未自动填充的版本请使用上表手动填写。在青龙容器终端中运行此命令只会立即拉取，
不会替你创建订阅管理记录或后续的更新计划。

只订阅一个项目时，修改白名单，例如 V2EX 为 `^V2EX/V2EX\.py$`，依赖文件保持不变。
详细参数、终端拉取、更新与故障处理见 [订阅与拉取说明](docs/subscription.md)。

### 2. 安装 Python 依赖

进入 **依赖管理 → 新建依赖 → Python3**，名称填写：

```text
requests>=2.28.0,<3.0.0
```

等待安装完成，检查依赖日志。当前全部业务脚本共用该依赖；已有兼容版本可直接使用。
订阅拉取不会自动执行 `pip install`，也无需为本仓库安装 Node.js 依赖。

### 3. 配置账号与通知

进入 **环境变量**，按对应项目文档填写并启用变量：

| 项目 | 必填变量 | 多账号格式 |
| --- | --- | --- |
| GLaDOS | `GLADOS_COOKIES` | 推荐账号 JSON 数组，详见 [项目文档](GLaDOS/README.md) |
| V2EX | `V2EX_COOKIES` | Cookie 使用 `\|\|\|` 分隔 |
| 成都地铁 | `CDRAIL_HEADERS_JSON` | 请求头 JSON 对象使用 `\|\|\|` 分隔 |

只配置需要运行的项目。不使用的任务请在定时任务中禁用，或调整订阅白名单。
凭证不要写入任务命令、脚本和 Git 提交。

通知使用青龙官方 `notify.py` 的环境变量。配置 Telegram 时填写 `TG_BOT_TOKEN`、
`TG_USER_ID`；其他渠道及完整变量表见 [通知与运行配置](docs/configuration.md)。
只查看控制台结果可设置 `CONSOLE=true`、`HITOKOTO=false`。

### 4. 拉取订阅并检查任务

1. 保存订阅，在 **订阅管理** 中选中该订阅，点击 **运行**，等待完成并查看订阅日志。
2. 确认仓库拉取成功，且新增任务对应上方三个业务入口；缩小白名单后，任务数量相应减少。
3. 在 **脚本管理** 中确认订阅目录包含业务入口、根目录的
   `notification_adapter.py`、`runtime_control.py` 和青龙提供的 `notify.py`。
4. 在 **定时任务** 中手动运行已配置账号的任务，检查任务日志中的账号结果与通知。

订阅定时规则控制**何时更新代码**；每个脚本头部的 `cron:` 控制**新增任务的执行时间**。
修改脚本头部 Cron 不会自动覆盖面板中已有任务的时间；已有任务请在面板中调整。

未自动创建时，可手动添加以下命令，并分别填写 `0 8 * * *`、`20 9 * * *`、
`10 9 * * *` 作为定时规则：

```text
task <订阅唯一值>/GLaDOS/GLaDOS.py
task <订阅唯一值>/V2EX/V2EX.py
task <订阅唯一值>/CDRail/CDRail.py
```

`<订阅唯一值>` 是占位符，需要整体替换。上述 URL 和 `main` 分支通常生成
`curtinp118_QinglongScripts_main`，以面板实际生成的目录和任务命令为准。
