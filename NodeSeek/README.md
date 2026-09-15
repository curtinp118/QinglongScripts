# NodeSeek 每日签到

该项目使用用户本人账号 Cookie 驱动 NodeSeek 页面完成多账号签到，使用
BeautifulSoup 解析登录状态、签到奖励和评论帖子，并通过统一通知模块发送结果。

脚本通过无头浏览器完成登录、签到和页面交互，并使用 BeautifulSoup 解析页面内容；
Cloudflare 验证超时后会返回明确的失败结果，不记录页面源码或 Cookie。

## 文件说明

```text
NodeSeek/
├── NodeSeek.py        # 青龙定时任务入口
├── README.md          # 配置与运行说明
└── requirements.txt   # Python 依赖
```

脚本按“配置读取 → 浏览器初始化 → BeautifulSoup 页面解析 → 单账号结果 → 统一通知”
的边界组织。入口只从 `NODESEEK_COOKIES` 读取凭证，账号执行失败会记录为该账号
结果并继续处理后续账号。
通知载荷由根目录 `notification_adapter.py` 统一渲染，再交给青龙官方 `notify.py`。

## 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `NODESEEK_COOKIES` | 是 | NodeSeek 登录 Cookie，多账号用 `|||` 分隔 |
| `NODESEEK_RANDOM` | 否 | 是否优先选择“试试手气”，默认 `true` |
| `NODESEEK_HEADLESS` | 否 | 是否使用无头浏览器，默认 `true` |
| `NODESEEK_COMMENT` | 否 | 是否执行随机评论，默认 `true`；设置 `false` 关闭 |
| `NODESEEK_COMMENT_URL` | 否 | NodeSeek 评论区域 HTTPS 地址，默认交易区 |
| `NODESEEK_DELAY_MIN` | 否 | 任务开始前最短随机延迟（分钟），默认 `0` |
| `NODESEEK_DELAY_MAX` | 否 | 任务开始前最长随机延迟（分钟），默认 `10` |
| `NODESEEK_CHROME_BIN` | 否 | Chrome/Chromium 可执行文件路径，未设置时自动查找 |

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
2. 确认 **依赖管理** 中已安装 NodeSeek 的 Python3 依赖：`beautifulsoup4`、
   `requests`、`selenium`、`setuptools` 和 `undetected-chromedriver`。
3. 运行仓库订阅，让青龙自动创建任务。

青龙的 Python 依赖管理只能安装 Python 包，不能安装操作系统级浏览器。任务运行环境
必须另行安装 Chrome/Chromium；容器中建议使用无头模式（保持
`NODESEEK_HEADLESS=true`）。

如果日志先出现 `patching driver executable`，随后出现 `Chrome 浏览器启动失败`，
说明驱动文件已经准备，但浏览器程序没有安装、路径不可执行，或当前容器架构不匹配。

### Docker 安装 Chromium（推荐）

青龙官方镜像的 `latest` 版本基于 Alpine；需要额外系统依赖时，建议改用
`whyour/qinglong:debian`，再构建一个带 Chromium 的镜像。新建 `Dockerfile`：

```dockerfile
FROM whyour/qinglong:debian

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

USER qinglong
```

在 `Dockerfile` 所在目录执行：

```bash
docker build -t qinglong-nodeseek:debian .
```

然后用这个镜像重新创建青龙容器。请沿用原容器的 `/ql/data` 挂载、端口、名称和其他
环境变量，例如：

```bash
docker stop qinglong
docker rm qinglong
docker run -d \
  --name qinglong \
  --restart unless-stopped \
  -v /你的路径/ql/data:/ql/data \
  -p 5700:5700 \
  qinglong-nodeseek:debian
```

如果当前容器本身就是 Debian，也可以临时安装（重新创建或更新容器后需要重装）：

```bash
docker exec -u 0 -it qinglong sh
apt-get update && apt-get install -y --no-install-recommends chromium fonts-noto-cjk
exit
```

如果执行 `apt-get` 提示命令不存在，说明当前是 Alpine 镜像；可以临时执行
`apk add --no-cache chromium nss freetype harfbuzz ttf-freefont font-noto-cjk`，但长期使用
建议按上面的 Debian 方案重建容器。

安装完成后，在青龙 **环境变量** 中设置：

```text
NODESEEK_HEADLESS=true
NODESEEK_CHROME_BIN=/usr/bin/chromium
```

如果使用 Google Chrome，将 `NODESEEK_CHROME_BIN` 改为实际路径，例如
`/usr/bin/google-chrome`。用下面的命令确认青龙任务用户可以启动浏览器：

```bash
docker exec -u qinglong qinglong sh -lc \
  '/usr/bin/chromium --headless --no-sandbox --disable-dev-shm-usage \
   --dump-dom data:,ok >/dev/null && echo browser-ok'
```

`undetected-chromedriver` 首次运行会准备匹配的驱动文件，任务用户需要能写入
`/home/qinglong/.local/share/undetected_chromedriver`。如果日志仍显示浏览器启动失败，
先在容器内执行 `chromium --version`，再检查 `NODESEEK_CHROME_BIN` 路径和容器架构。

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

- 每个账号执行一次浏览器签到流程，重复签到视为成功。
- `NODESEEK_RANDOM=true` 时优先选择“试试手气”，否则优先选择鸡腿按钮。
- `NODESEEK_COMMENT=true` 且本次签到成功时随机选择 3-5 个非置顶帖子评论，并在连续失败 2 次后停止评论；重复运行若已签到则跳过评论。
- 浏览器页面加载和脚本执行超时为 10 秒；Cloudflare 页面最多等待 30 秒。
- 脚本不依赖青龙任务的当前工作目录，也不会在仓库中生成截图或临时文件。
- 重复的 Cookie 配置会自动去重，格式无效的 Cookie 只影响对应账号。
- 单账号失败不会中止后续账号，最终可能返回 `PARTIAL_SUCCESS`。
- 日志与通知仅使用账号序号，不输出 Cookie 内容；错误消息中的凭证字段会脱敏。

## 常见问题

### HTTP 403 或 Cloudflare 拒绝访问

确认 Chrome/Chromium 和 `undetected-chromedriver` 已安装并可由青龙任务访问，
且运行用户能写入驱动缓存目录。
如果 Cloudflare 验证仍然超时，请在浏览器中确认账号状态和网络条件，不要把 Cookie
写入任务命令或日志。

### 任务执行成功但没有通知

检查根 README 中的通用通知变量，并在青龙环境变量中至少配置一个通知渠道。

### 浏览器无法启动

在青龙环境中安装 Chrome/Chromium，并将其路径配置到 `NODESEEK_CHROME_BIN`；
同时确认 `undetected-chromedriver` 与当前 Chrome 主版本兼容。

如果设置了 `NODESEEK_HEADLESS=false`，还需要为青龙容器提供可用的 Xvfb 显示环境；
无桌面环境时请保持默认的无头模式。
