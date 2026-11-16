# 青龙订阅与拉取

[返回首页](../README.md) · [全局配置](configuration.md) · [开发规范](../CONTRIBUTING.md)

本文对照青龙 `v2.24.0` 的默认 Shell 订阅实现与官方用法说明编写。
首次使用请先完成 [首页的四步配置](../README.md#在青龙中使用)。

## 三个不同的操作

| 操作 | 作用 | 是否定期执行 |
| --- | --- | --- |
| 在订阅管理中创建并保存订阅 | 保存仓库、筛选条件和更新计划 | 到订阅规则指定的时间执行拉取 |
| 在订阅管理中点击运行 | 立即拉取该订阅、复制文件、对比并增删任务 | 本次立即执行 |
| 在青龙容器中执行 `ql repo ...` | 按位置参数立即拉取仓库、同步文件与任务 | 命令本身不保存订阅更新计划 |

`git clone` 仅用于本地开发，不会注册青龙定时任务。
`ql update` 用于更新青龙面板，与更新本仓库订阅是两个操作。

## 筛选与文件复制规则

青龙先按“文件后缀”查找文件，再用白名单包含、黑名单排除，得到业务脚本清单。
开启自动添加任务后，清单中的新文件会进入定时任务。

- 匹配对象是去掉 `./` 的仓库相对路径，如 `V2EX/V2EX.py`，路径分隔符为 `/`。
- 白名单、黑名单和依赖文件使用 `grep -E` 风格的 POSIX 扩展正则。多个候选用 `|`。
- 不要使用 Python / JavaScript 专有的 `\d`、`(?:...)`、前后向断言等表达式。
- 文件后缀填写 `py`，不带 `.`；多个后缀按表单提示用空格分隔。
- 依赖文件从相同后缀的文件中单独匹配，绕过白名单和黑名单，按原相对目录复制。
  它们不会因为出现在依赖字段中就成为任务；如果同时命中业务清单，仍然会建任务。
- 依赖字段不安装 `requests`，也不会自动读取 `requirements.txt`。

| 字段 | 表达式 |
| --- | --- |
| 白名单：全部三个入口 | `^(GLaDOS/GLaDOS\|V2EX/V2EX\|CDRail/CDRail)\.py$` |
| 白名单：仅 GLaDOS | `^GLaDOS/GLaDOS\.py$` |
| 白名单：仅 V2EX | `^V2EX/V2EX\.py$` |
| 白名单：仅成都地铁 | `^CDRail/CDRail\.py$` |
| 黑名单：公共模块 | `(^\|/)(notify\|notification_adapter\|runtime_control)\.py$` |
| 依赖文件：推荐 | `^(notification_adapter\|runtime_control)\.py$` |

精确到入口文件的白名单可以避免将今后新增的辅助 `.py` 文件误建成任务。
新增服务时，需要将新入口加入白名单；只想保留部分项目时也只需修改白名单。

## notify.py 的来源

青龙在订阅目标目录先复制面板脚本根目录的 `notify.py` / `sendNotify.js`，
随后复制仓库依赖文件，最后复制业务脚本。因此推荐依赖字段只填写：

```text
^(notification_adapter|runtime_control)\.py$
```

这样适配器使用随面板维护的官方通知模块。仓库根目录仍保留 `notify.py`，
用于本地 Python 运行。若确实需要在订阅中使用仓库副本，可将依赖文件改为：

```text
^(notify|notification_adapter|runtime_control)\.py$
```

仓库副本会覆盖本次拉取时青龙放入订阅目录的同名文件，通知渠道能力和变量以该副本为准。
更改选择后需要重新运行订阅。面板的自定义依赖目录也可能覆盖同名文件，
排查导入问题时应检查最终脚本目录中的实际文件。

## 在容器终端立即拉取

推荐优先使用订阅管理，终端方式适合排查或手动维护。以下命令在安装了青龙的
容器内运行；普通 Windows PowerShell 和本地开发虚拟环境不提供面板内置 `ql`。

Docker 部署可先进入容器（`qinglong` 替换为实际容器名）：

```bash
docker exec -it qinglong bash
```

在容器中执行与首页一致的命令：

```bash
ql repo "https://github.com/curtinp118/QinglongScripts.git" "^(GLaDOS/GLaDOS|V2EX/V2EX|CDRail/CDRail)\.py$" "(^|/)(notify|notification_adapter|runtime_control)\.py$" "^(notification_adapter|runtime_control)\.py$" "main" "py"
```

位置参数顺序不能调整；中间不用的值必须保留空字符串 `""`：

```text
ql repo <仓库链接> <白名单> <黑名单> <依赖文件> <分支> <文件后缀>
```

上述六参数命令的任务增删开关遵循面板的全局 `AutoAddCron` / `AutoDelCron` 配置。
订阅管理运行时使用该订阅自己的开关。需要长期更新时，请创建订阅记录并设置定时规则。
青龙另有用于远程管理的 `@whyour/qinglong-cli`，其 npm `ql` 与面板内置 `ql`
用途不同，不要为了执行本命令在本机安装同名 npm CLI。

## 拉取结果与任务路径

默认 Docker 数据目录下，仓库检出与可执行脚本分开放置：

```text
/ql/data/repo/<订阅唯一值>/       # 仓库检出目录
/ql/data/scripts/<订阅唯一值>/    # 筛选后复制的业务脚本与公共模块
```

其他安装方式或自定义数据目录以面板实际路径为准。不要直接修改 `repo` 检出目录，
重新拉取会重新生成它；`scripts` 中的订阅文件也会被覆盖。本地修改应在开发仓库中完成。

使用本仓库地址和 `main` 分支时，通常生成唯一值 `curtinp118_QinglongScripts_main`。
不要仅凭订阅名称猜目录；查看自动生成的任务命令或脚本管理中的实际目录。

以 V2EX 为例，面板中的任务命令通常是：

```text
task curtinp118_QinglongScripts_main/V2EX/V2EX.py
```

在容器终端中需要实时检查日志时，可执行：

```bash
task curtinp118_QinglongScripts_main/V2EX/V2EX.py now
```

`now` 跳过青龙执行器的随机延迟；本仓库的 `QL_RANDOM_DELAY_*` 是独立控制，
需要即时发起业务请求时，在面板环境变量中设置 `QL_RANDOM_DELAY_ENABLED=false`。
凭证仍通过环境变量提供，不要拼入命令。

## 更新与任务同步

订阅运行会比较当前脚本清单与已有任务：

- 自动添加任务：为新增路径创建任务，优先读取脚本中的任务元数据。
- 自动删除任务：清理不再命中清单的任务及对应脚本，修改白名单也会触发。
- 已有同路径任务：更新脚本内容，不会根据新 `cron:` 重写已有任务时间。
- `name:` / `cron:` 使用英文小写并各占一行，见 [开发规范](../CONTRIBUTING.md)。

自动删除并非只删除远端已经移除的文件。缩小白名单前先确认要保留哪些任务；
重新拉取后检查新增和失效任务清单。没有自动删除的历史错误任务需要手动清理。
切换仓库地址、分支或唯一值后，应核对旧目录对应的任务，避免两套任务重复执行。

## 常见问题

### 拉取失败

先看订阅日志：网络超时、DNS、TLS、GitHub 连通性、分支不存在和认证失败处理方式不同。
本仓库为公开仓库，HTTPS 地址无需 GitHub Token。代理按面板订阅的“代理”字段配置。
依赖安装失败不等同于 Git 拉取失败，应分别查看依赖日志和订阅日志。

### 拉取成功但没有生成任务

核对精确白名单、`py` 后缀和自动添加开关。空白名单可能将所有同后缀公共模块也纳入任务，
不要通过清空全部筛选条件排查。使用首页配置重新拉取并查看新增 / 失效清单。
已存在的任务不会再次新增，应同时检查禁用任务和任务搜索条件。

### 公共模块被自动添加为任务

按首页精确白名单、公共模块黑名单及依赖字段修正，开启自动删除后重新运行订阅。
若历史错误任务仍存在，检查命令路径是否属于旧唯一值，并手动删除对应任务。
不要删除脚本目录内仍被业务入口导入的公共模块。

### 提示 ModuleNotFoundError

| 模块 | 处理方法 |
| --- | --- |
| `requests` | 在依赖管理 → Python3 安装首页指定的版本范围，确认任务使用同一 Python 环境 |
| `notification_adapter` / `runtime_control` | 恢复依赖文件表达式，重新拉取；确认模块位于订阅根目录而非业务子目录 |
| `notify` | 确认面板自带通知模块存在并重新拉取；按需使用仓库副本方案 |

不要只通过 `ql raw` 拉取单个业务入口：它依赖本仓库公共模块，推荐完整仓库订阅。

### 任务执行成功但没有推送

查看 [通知配置](configuration.md)，确认账号变量和通知渠道变量均已启用。
官方 `notify.send` 不提供统一的逐渠道送达回执；业务日志成功不代表通知已送达，
还需查看通知模块的输出以及实际接收端。

## 官方依据

核实时间：2026-11-16。稳定版 `v2.24.0` 对应提交
`f2c2f5e4f8254a8682269c21ee1411ac2189e17e`。以下源码链接固定到该提交：

- [官方基本说明](https://qinglong.online/guide/user-guide/basic-explanation)：`task`、`ql repo` 的用法。
- [shell/update.sh](https://github.com/whyour/qinglong/blob/f2c2f5e4f8254a8682269c21ee1411ac2189e17e/shell/update.sh)：
  `gen_list_repo` 筛选与复制，`diff_scripts` / `add_cron` / `del_cron` 任务同步。
- [shell/share.sh](https://github.com/whyour/qinglong/blob/f2c2f5e4f8254a8682269c21ee1411ac2189e17e/shell/share.sh)：
  数据目录、通知模块位置与全局后缀默认值。
- [订阅表单](https://github.com/whyour/qinglong/blob/f2c2f5e4f8254a8682269c21ee1411ac2189e17e/src/pages/subscription/modal.tsx)：
  字段、命令导入、唯一值与自动任务开关。
- [订阅命令生成](https://github.com/whyour/qinglong/blob/f2c2f5e4f8254a8682269c21ee1411ac2189e17e/back/config/subscription.ts)：
  表单值到 `ql repo` 位置参数的映射。

官方网页会持续更新，其他版本及可选执行器应结合对应版本的帮助与源码确认。
