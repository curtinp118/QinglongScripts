# 开发规范

[返回首页](README.md) · [订阅规则](docs/subscription.md) · [全局配置](docs/configuration.md)

## 目录与职责

每个服务沿用 `<Service>/<Service>.py`、`README.md`、`requirements.txt` 的结构。
服务目录使用稳定的 ASCII 名称，路径区分大小写。入口文件名与目录名保持一致；
已有路径不随格式整理改名，避免青龙将其视为旧任务删除、新任务新增。

服务代码留在对应目录；跨服务共用能力放在根目录公共模块，使用小写下划线文件名。
公共模块不写青龙任务元数据。新增公共模块时，必须同步更新订阅的依赖文件表达式。
服务内新增辅助模块时也要明确加入依赖文件表达式；精确入口白名单不会自动复制辅助模块。
文档放入 `docs/`，各服务 README 负责本服务账号配置和接口行为，避免重复维护订阅教程。

仓库保留官方 `notify.py` 副本供本地运行，推荐订阅使用面板自带版本。
该文件作为上游代码维护，不参与本仓库的格式检查；更新时记录上游版本或提交来源，
检查可用渠道和运行依赖，不混入业务逻辑。

本地抓包、账号配置、运行日志和临时检查放在 Git 忽略的目录中。
`tests/`、`test/`、`.tmp/`、`.venv/` 等已有忽略规则；不要为了发布验证脚本而随意移除。

本地请求记录统一放入根目录 `captures/`，HAR、SAZ、PCAP 等抓包文件也已忽略；
个人配置使用 `*.local.json`、`*.local.yaml`、`*.local.toml` 等命名，或放入 `.local/`。
临时下载和实验分别放入根目录 `downloads/`、`scratch/`。运行缓存、覆盖率报告、
本地 SQLite 状态、编辑器历史和备份文件不提交。
脱敏的 `.env.example`、`.env.<名称>.example`、`.env.sample` 可以提交，
依赖锁文件、正常 JSON / YAML 配置和文档资源也保持可跟踪。
`.env` 示例仅供配置参考，脚本不会自动加载它们。

新增忽略规则时用 `git check-ignore -v --no-index <路径>` 核实命中来源，避免误屏蔽源码。
`.gitignore` 不会停止跟踪已提交文件；误提交凭证时需要另行移出跟踪并更新凭证，
仅添加忽略规则无法消除已提交内容。

## Python 风格

- 自有代码以 Python 3.10+ 为语法基线；UTF-8、LF 换行、四空格缩进，Ruff 统一格式，行宽 88。
- 模块 / 函数 / 变量使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`。
- 导入按标准库、第三方库、仓库模块分组；公共函数和数据结构尽量提供类型标注与中文说明。
- 各入口通过 `Path(__file__).resolve().parents[1]` 找到仓库根目录，添加到 `sys.path`
  后导入公共模块。此处保留 `# noqa: E402`；不依赖调用时工作目录。
- `main()` 配置日志后调用 `run()`；模块导入时不发起请求、等待或发送通知。
  使用 `if __name__ == "__main__": raise SystemExit(main())` 保护入口。

## 任务元数据

入口顶部采用统一文档字符串，至少包含以下字段，`name:`、`cron:` 各占一行：

```python
# -*- coding: utf-8 -*-
"""
name: 示例服务每日任务
description: 使用环境变量提供的本人账号凭证执行每日任务
cron: 0 9 * * *
env:
  - EXAMPLE_COOKIES (必填): Cookie，多账号使用 ||| 分隔
version: 1.0.0
updated: YYYY-MM-DD
disclaimer: 仅供学习交流，禁止用于商业用途，风险自负
"""
```

不要在其他注释中重复带 `name:` / `cron:` 的配置示例，避免青龙按首个匹配值误读。
Cron 使用常见五段格式，并在服务 README 说明面板时区和服务日期边界。
修改实际行为时同步版本、日期、变量表和行为说明；仅格式调整无需提升业务版本。

## 配置、请求与结果

账号变量使用服务专属大写前缀，多账号通常使用 `|||`，复杂配置优先使用 JSON，
兼容格式需在项目文档明确。先校验配置再等待随机延迟、发起业务请求。
禁止硬编码真实凭证；含凭证的数据类字段应设置 `repr=False`，不要打印完整请求或响应。

日志与随机延迟统一使用 `runtime_control.configure_logging` 和 `wait_for_random_delay`。
日志保留阶段、账号序号、受控的账号名称、域名和状态；网络异常优先记录错误类型，
不要将可能包含认证 URL / 请求头的底层异常直接推送给用户。
预期错误不输出 traceback；未预期异常可仅在 `QL_LOG_LEVEL=DEBUG` 时附加 traceback。

请求必须设置超时。只读操作可以有限重试并处理限流；会改变状态的签到、兑换等请求
按服务的幂等机制处理，避免在响应不确定时盲目重放。单账号失败应继续处理后续账号。

各项目保留服务自己的结果结构，统一转换成以下 Payload 后调用
`notification_adapter.send_payload`，业务入口不实现独立推送渠道：

```json
{
  "title": "示例服务每日任务",
  "status": "SUCCESS",
  "accounts": [
    {"name": "账号 1", "status": "SUCCESS", "detail": "今日已完成"}
  ],
  "summary": "共执行 1 个账号，成功 1 个，失败 0 个。",
  "timestamp": "2026-11-16 09:00:00"
}
```

全局状态使用 `SUCCESS`、`PARTIAL_SUCCESS`、`FAILED`；账号状态使用 `SUCCESS` 或
`FAILED`。结果数组不得为空；配置失败以一条“配置检查”结果表示。
服务端返回的文本进入日志或通知前，应限制长度并清理可能包含的凭证。
退出码和通知送达限制见[全局配置](docs/configuration.md#执行结果与通知送达)。

## 本地开发环境

建议创建独立虚拟环境，运行依赖和开发工具分开声明。
根目录 `requirements.txt` 汇总全部服务运行依赖；每个服务保留自己的依赖清单，
更新依赖时同步两个位置。开发工具只放入 `requirements-dev.txt`。

Windows PowerShell，在仓库根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Linux / macOS：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

主动修复导入与格式时运行 `python -m ruff check --fix .`、`python -m ruff format .`，
其中 `python` 指上方虚拟环境解释器。官方 `notify.py`、临时目录和虚拟环境会被排除。
本地执行入口仍会发起真实请求、签到和通知；只有使用本人凭证进行联调时才运行。
本仓库不自动读取 `.env` 文件，需要由运行环境注入变量。

## 提交前检查

1. 运行 Ruff 静态检查和格式检查，确认修改范围内语法有效。
2. 修改业务解析或状态判断时，使用脱敏响应或 mock 验证成功、已完成、凭证失效、
   网络错误和多账号隔离；本地验证不使用生产凭证或真实推送。
3. 新增入口时验证订阅正则仅选中预期任务，所有公共 / 辅助模块能按原目录导入。
4. 检查首页、项目 README、依赖声明和通知 Payload 是否同步，运行 `git diff --check`。
5. 区分本地模拟验证和真实青龙联调，提交说明写清实际执行过的检查与未验证的限制。
