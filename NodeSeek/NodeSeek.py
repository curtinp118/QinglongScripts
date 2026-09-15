# -*- coding: utf-8 -*-
"""
name: NodeSeek 每日签到
description: 使用浏览器 Cookie 执行 NodeSeek 多账号签到及可选评论
cron: 10 9 * * *
env:
  - NODESEEK_COOKIES (必填): NodeSeek Cookie，多账号用 ||| 分割
  - NODESEEK_RANDOM (选填): 是否优先选择“试试手气”，默认 true
  - NODESEEK_HEADLESS (选填): 是否使用无头浏览器，默认 true
  - NODESEEK_COMMENT (选填): 是否执行评论，默认 true
  - NODESEEK_COMMENT_URL (选填): 评论区域 HTTPS 地址，默认交易区
  - NODESEEK_DELAY_MIN (选填): 任务开始前最短延迟分钟数，默认 0
  - NODESEEK_DELAY_MAX (选填): 任务开始前最长延迟分钟数，默认 10
  - NODESEEK_CHROME_BIN (选填): Chrome 可执行文件路径
version: 2.0.0
updated: 2026-09-15
disclaimer: 仅供学习交流，禁止用于商业用途，风险自负
"""

from __future__ import annotations

import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# 青龙订阅会把公共依赖复制到入口脚本目录；
# 本地直接运行时则从仓库根目录加载。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from notification_adapter import send_payload  # noqa: E402


LOGGER = logging.getLogger("nodeseek")

COOKIE_ENV_NAME = "NODESEEK_COOKIES"
RANDOM_ENV_NAME = "NODESEEK_RANDOM"
HEADLESS_ENV_NAME = "NODESEEK_HEADLESS"
COMMENT_ENV_NAME = "NODESEEK_COMMENT"
COMMENT_URL_ENV_NAME = "NODESEEK_COMMENT_URL"
DELAY_MIN_ENV_NAME = "NODESEEK_DELAY_MIN"
DELAY_MAX_ENV_NAME = "NODESEEK_DELAY_MAX"
CHROME_BIN_ENV_NAME = "NODESEEK_CHROME_BIN"
CHROME_EXECUTABLE_NAMES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)

ACCOUNT_SEPARATOR = "|||"
SITE_ORIGIN = "https://www.nodeseek.com"
BOARD_URL = f"{SITE_ORIGIN}/board"
DEFAULT_COMMENT_URL = f"{SITE_ORIGIN}/categories/trade"
COOKIE_DOMAIN = ".nodeseek.com"

PAGE_LOAD_TIMEOUT_SECONDS = 10
ELEMENT_WAIT_TIMEOUT_SECONDS = 10
CLOUDFLARE_WAIT_SECONDS = 30
MAX_COMMENT_FAILURES = 2
MAX_SERVICE_MESSAGE_LENGTH = 160
ACCOUNT_DELAY_RANGE_SECONDS = (0.5, 1.5)
COMMENT_DELAY_RANGE_SECONDS = (60, 120)
COMMENT_COUNT_RANGE = (3, 5)
COOKIE_SEPARATOR_PATTERN = re.compile(
    rf"{re.escape(ACCOUNT_SEPARATOR)}|(?<!\|)\|(?!\|)"
)

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})
CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "checking your browser",
)
LOGIN_MARKERS = ("登录", "sign in", "log in")
ALREADY_SIGNED_MARKERS = (
    "今日已签到",
    "今日签到获得",
    "已完成签到",
    "已经签到",
    "已签到",
    "当前排名",
)
SIGN_SUCCESS_MARKERS = ("签到成功", "本次获得", "今日签到获得")
REWARD_PATTERNS = (
    re.compile(r"获得\s*(\d+)\s*鸡腿"),
    re.compile(r"鸡腿\s*(\d+)\s*个"),
    re.compile(r"踩到鸡腿\s*(\d+)\s*个"),
    re.compile(r"得鸡腿\s*(\d+)\s*个"),
    re.compile(r"(\d+)\s*(?:个?\s*鸡腿|鸡腿)"),
)
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(?P<key>cookie|session|pjwt|token|authorization)"
    r"\s*[:=]\s*(?P<value>[^;\s,]+)"
)

COMMENT_TEXTS = (
    "bd",
    "绑定",
    "帮顶",
    "吃瓜吃瓜",
    "好价",
    "过来看一下",
    "喝杯奶茶压压惊",
    "咕噜咕噜",
    "前排",
    "恭喜发财",
    "好基",
    "公道公道",
    "楼主不错 绑定",
    "还可以",
    "再看看吧",
    "楼下要了",
    "挺不错的 bdbd",
    "好价 好价",
    "给楼下点个",
    "祝早出",
    "观望一下 早出",
    "让给楼下",
    "还要啥自行车",
    "卷起来",
    "这是什么东西",
    "收了吧楼下",
    "bd一下",
)


class ResultStatus(str, Enum):
    """仓库标准通知状态。"""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class SignInStatus(str, Enum):
    """签到流程内部状态。"""

    SUCCESS = "success"
    ALREADY = "already"
    FAILED = "failed"


class ConfigurationError(ValueError):
    """环境变量配置不合法。"""


class NodeSeekError(RuntimeError):
    """NodeSeek 浏览器或页面处理错误。"""


@dataclass(frozen=True)
class Settings:
    """经过规范化的脚本配置。"""

    cookies: tuple[str, ...]
    random_signin: bool
    headless: bool
    enable_comments: bool
    comment_url: str
    delay_min_minutes: int
    delay_max_minutes: int
    chrome_binary: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        """读取并校验 NodeSeek 专用环境变量。"""
        raw_cookies = os.environ.get(COOKIE_ENV_NAME, "")
        cookies = tuple(
            dict.fromkeys(
                normalize_cookie(item)
                for item in COOKIE_SEPARATOR_PATTERN.split(raw_cookies)
                if item.strip()
            )
        )

        comment_url = normalize_comment_url(
            os.environ.get(COMMENT_URL_ENV_NAME, DEFAULT_COMMENT_URL)
        )
        delay_min = parse_non_negative_int(
            os.environ.get(DELAY_MIN_ENV_NAME), DELAY_MIN_ENV_NAME, 0
        )
        delay_max = parse_non_negative_int(
            os.environ.get(DELAY_MAX_ENV_NAME), DELAY_MAX_ENV_NAME, 10
        )
        if delay_min > delay_max:
            delay_min, delay_max = delay_max, delay_min

        chrome_binary = os.environ.get(CHROME_BIN_ENV_NAME, "").strip() or None
        return cls(
            cookies=cookies,
            random_signin=parse_bool(
                os.environ.get(RANDOM_ENV_NAME), RANDOM_ENV_NAME, default=True
            ),
            headless=parse_bool(
                os.environ.get(HEADLESS_ENV_NAME), HEADLESS_ENV_NAME,
                default=True,
            ),
            enable_comments=parse_bool(
                os.environ.get(COMMENT_ENV_NAME), COMMENT_ENV_NAME,
                default=True,
            ),
            comment_url=comment_url,
            delay_min_minutes=delay_min,
            delay_max_minutes=delay_max,
            chrome_binary=chrome_binary,
        )

    def get_random_delay_seconds(self) -> int:
        """获取任务开始前的随机延迟秒数。"""
        if self.delay_max_minutes <= 0:
            return 0
        return random.randint(
            self.delay_min_minutes,
            self.delay_max_minutes,
        ) * 60


@dataclass(frozen=True)
class AccountResult:
    """单账号签到及可选评论结果。"""

    name: str
    status: ResultStatus
    detail: str

    def as_payload(self) -> dict[str, str]:
        """转换为统一通知 Payload 的账号详情。"""
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
        }


def parse_bool(
    raw_value: str | None,
    variable_name: str,
    default: bool,
) -> bool:
    """解析常见布尔环境变量值。"""
    if raw_value is None or not raw_value.strip():
        return default
    value = raw_value.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ConfigurationError(f"{variable_name} 仅支持 true/false")


def parse_non_negative_int(
    raw_value: str | None,
    variable_name: str,
    default: int,
) -> int:
    """解析非负整数配置。"""
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value.strip())
    except ValueError as exc:
        raise ConfigurationError(
            f"{variable_name} 必须是非负整数"
        ) from exc
    if value < 0:
        raise ConfigurationError(f"{variable_name} 必须是非负整数")
    return value


def normalize_comment_url(raw_url: str) -> str:
    """校验评论地址，避免 Cookie 被导航到外部域名。"""
    comment_url = (raw_url or DEFAULT_COMMENT_URL).strip()
    parsed = urlparse(comment_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.nodeseek.com", "nodeseek.com"}
    ):
        raise ConfigurationError(
            f"{COMMENT_URL_ENV_NAME} 必须是 NodeSeek HTTPS 地址"
        )
    return comment_url


def normalize_cookie(raw_cookie: str) -> str:
    """清理 Cookie 两端引号并合并抓包工具产生的换行。"""
    cookie = raw_cookie.strip().strip("\"'")
    return re.sub(r"[\r\n]+", "; ", cookie)


def validate_cookie(cookie: str) -> tuple[bool, str]:
    """验证 Cookie 至少包含一个合法名称和值，不记录字段值。"""
    valid_pairs = 0
    for chunk in cookie.split(";"):
        name, separator, value = chunk.strip().partition("=")
        if separator and name.strip() and value.strip():
            valid_pairs += 1
    if valid_pairs == 0:
        return False, "Cookie 格式无效，应为 name=value"
    return True, ""


def cookie_pairs(cookie: str) -> list[tuple[str, str]]:
    """提取可交给浏览器的 Cookie 键值对。"""
    pairs = []
    for chunk in cookie.split(";"):
        name, separator, value = chunk.strip().partition("=")
        if separator and name.strip() and value.strip():
            pairs.append((name.strip(), value.strip()))
    return pairs


def compact_message(value: Any, fallback: str = "未知错误") -> str:
    """压缩并脱敏服务消息，避免日志或通知输出冗长内容。"""
    message = " ".join(str(value or fallback).split())
    message = SENSITIVE_VALUE_PATTERN.sub(
        lambda match: f"{match.group('key')}=***",
        message,
    )
    return message[:MAX_SERVICE_MESSAGE_LENGTH]


def parse_reward_from_text(text: str) -> str:
    """从页面文本中解析鸡腿数量。"""
    normalized_text = " ".join(text.split())
    for pattern in REWARD_PATTERNS:
        match = pattern.search(normalized_text)
        if match:
            return match.group(1)
    return "未知"


def parse_page(driver: Any) -> BeautifulSoup:
    """使用 BeautifulSoup 解析当前页面源代码。"""
    try:
        return BeautifulSoup(driver.page_source, "html.parser")
    except Exception as exc:
        raise NodeSeekError("页面 HTML 解析失败") from exc


def page_text(soup: BeautifulSoup) -> str:
    """提取压缩后的可见文本，不输出完整 HTML。"""
    return " ".join(soup.get_text(" ", strip=True).split())


def contains_any(text: str, markers: tuple[str, ...]) -> bool:
    """检查文本是否包含任一标记。"""
    lowered_text = text.lower()
    return any(marker.lower() in lowered_text for marker in markers)


def is_challenge_page(driver: Any) -> bool:
    """识别 Cloudflare 页面标题。"""
    title = str(getattr(driver, "title", "") or "").lower()
    return any(marker in title for marker in CHALLENGE_MARKERS)


def wait_for_cloudflare(driver: Any) -> None:
    """等待 Cloudflare 验证完成，不记录页面源码。"""
    deadline = time.monotonic() + CLOUDFLARE_WAIT_SECONDS
    while is_challenge_page(driver) and time.monotonic() < deadline:
        LOGGER.info("等待 Cloudflare 验证完成")
        time.sleep(3)
    if is_challenge_page(driver):
        raise NodeSeekError("Cloudflare 验证超时")


def check_login_status(driver: Any) -> bool:
    """使用 BeautifulSoup 检查登录后的页面元素。"""
    try:
        wait_for_cloudflare(driver)
        soup = parse_page(driver)
        text = page_text(soup)
        login_elements = soup.select("a, button, span")
        login_present = any(
            contains_any(element.get_text(" ", strip=True), LOGIN_MARKERS)
            for element in login_elements
        )
        login_present = login_present or bool(
            soup.select("a[href*='login'], a[href*='signin']")
        )
        personal_present = bool(
            soup.select(
                ".avatar, .nsk-user-avatar, [class*='avatar'], "
                ".user-avatar, .user-info, a[href*='/user/']"
            )
        ) or contains_any(text, ("个人中心", "消息"))
        if personal_present and not login_present:
            LOGGER.info("登录状态有效")
            return True
        LOGGER.warning("Cookie 已过期或页面未检测到登录状态")
        return False
    except NodeSeekError:
        raise
    except Exception as exc:
        raise NodeSeekError("登录状态检测失败") from exc


def choose_sign_button(driver: Any, settings: Settings) -> Any | None:
    """按随机签到设置选择按钮。

    找不到偏好按钮时使用首个按钮。
    """
    buttons = driver.find_elements(By.CSS_SELECTOR, ".board-intro button")
    if not buttons:
        buttons = driver.find_elements(
            By.XPATH,
            "//button[contains(., '手气') or contains(., '鸡腿')]",
        )
    if not buttons:
        return None

    preferred = []
    for button in buttons:
        label = str(getattr(button, "text", "") or "")
        if settings.random_signin and "手气" in label:
            preferred.append(button)
        elif not settings.random_signin and (
            "鸡腿" in label or re.search(r"x\s*5", label, re.I)
        ):
            preferred.append(button)
    return preferred[0] if preferred else buttons[0]


def click_sign_icon(
    driver: Any,
    settings: Settings,
) -> tuple[SignInStatus, str]:
    """执行签到面板点击，并在页面结构变化时使用备用选择器。"""
    try:
        driver.get(BOARD_URL)
        time.sleep(3)
        wait_for_cloudflare(driver)
        current_url = str(getattr(driver, "current_url", "") or "")
        soup = parse_page(driver)
        text = page_text(soup)
        if contains_any(text, LOGIN_MARKERS) and not soup.select(
            ".avatar, .nsk-user-avatar, [class*='avatar'], .user-avatar"
        ):
            return SignInStatus.FAILED, "Cookie 已过期或未登录"

        intro = soup.select_one(".board-intro")
        intro_text = intro.get_text(" ", strip=True) if intro else ""
        if contains_any(intro_text or text, ALREADY_SIGNED_MARKERS):
            return SignInStatus.ALREADY, parse_reward_from_text(intro_text or text)

        target_button = choose_sign_button(driver, settings)
        if target_button is None:
            if "/board" not in current_url and "nodeseek.com" in current_url:
                return SignInStatus.FAILED, "无法找到签到按钮"
            if "还未签到" in (intro_text or text):
                return SignInStatus.FAILED, "页面提示未签到但未找到按钮"
            return SignInStatus.FAILED, "无法确认签到状态"

        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});",
            target_button,
        )
        time.sleep(0.5)
        try:
            target_button.click()
        except WebDriverException:
            driver.execute_script("arguments[0].click();", target_button)
        time.sleep(3)
        wait_for_cloudflare(driver)

        result_soup = parse_page(driver)
        result_scope = result_soup.select_one(".board-intro") or result_soup
        result_text = page_text(result_scope)
        reward = parse_reward_from_text(result_text)
        if reward != "未知" or contains_any(result_text, SIGN_SUCCESS_MARKERS):
            return SignInStatus.SUCCESS, reward
        if contains_any(result_text, ALREADY_SIGNED_MARKERS):
            return SignInStatus.ALREADY, reward
        return SignInStatus.FAILED, "签到结果无法确认"
    except NodeSeekError:
        raise
    except TimeoutException as exc:
        raise NodeSeekError("签到页面加载超时") from exc
    except WebDriverException as exc:
        raise NodeSeekError("签到浏览器操作失败") from exc
    except Exception as exc:
        raise NodeSeekError("签到过程中发生异常") from exc


def build_driver(settings: Settings) -> Any:
    """按原脚本方式初始化 undetected-chromedriver。"""
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--lang=zh-CN,zh")
    chrome_options.add_argument("--window-size=1920,1080")

    if settings.chrome_binary:
        chrome_options.binary_location = settings.chrome_binary

    chrome_binary = settings.chrome_binary
    if chrome_binary:
        chrome_binary = os.path.expanduser(chrome_binary)
        if not os.path.isfile(chrome_binary) or not os.access(
            chrome_binary, os.X_OK
        ):
            raise NodeSeekError(
                f"{CHROME_BIN_ENV_NAME} 指向的浏览器不可执行: {chrome_binary}"
            )
    else:
        for executable in CHROME_EXECUTABLE_NAMES:
            chrome_binary = shutil.which(executable)
            if chrome_binary:
                break
    if not chrome_binary:
        raise NodeSeekError(
            "未找到 Chrome/Chromium，请安装浏览器或设置 "
            f"{CHROME_BIN_ENV_NAME}"
        )
    chrome_major_version: int | None = None
    if chrome_binary:
        try:
            result = subprocess.run(
                [chrome_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                version = result.stdout.strip().split()[-1]
                chrome_major_version = int(version.split(".")[0])
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            LOGGER.warning("Chrome 版本检测失败: %s", compact_message(exc))

    kwargs: dict[str, Any] = {
        "options": chrome_options,
        "headless": settings.headless,
        "use_subprocess": True,
        "version_main": chrome_major_version,
    }
    if chrome_binary:
        kwargs["browser_executable_path"] = chrome_binary

    try:
        driver = uc.Chrome(**kwargs)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
        driver.set_script_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
        driver.set_window_size(1920, 1080)
        return driver
    except Exception as exc:
        detail = compact_message(exc)
        LOGGER.error("Chrome 启动失败 (%s): %s", type(exc).__name__, detail)
        raise NodeSeekError(f"Chrome 浏览器启动失败: {detail}") from exc


def close_driver(driver: Any) -> None:
    """安全关闭浏览器，避免清理异常覆盖账号结果。"""
    try:
        driver.quit()
    except Exception as exc:
        LOGGER.warning("浏览器关闭失败: %s", type(exc).__name__)


def setup_driver_and_cookies(settings: Settings, cookie: str) -> Any:
    """初始化浏览器、设置 Cookie 并等待 Cloudflare 验证。"""
    driver = build_driver(settings)
    try:
        driver.get(SITE_ORIGIN)
        time.sleep(5)
        added_count = 0
        for name, value in cookie_pairs(cookie):
            try:
                driver.add_cookie(
                    {
                        "name": name,
                        "value": value,
                        "domain": COOKIE_DOMAIN,
                        "path": "/",
                    }
                )
                added_count += 1
            except WebDriverException as exc:
                LOGGER.warning("Cookie 字段设置失败: %s", type(exc).__name__)
        if added_count == 0:
            raise NodeSeekError("没有可设置的 Cookie 字段")
        driver.refresh()
        time.sleep(3)
        wait_for_cloudflare(driver)
        time.sleep(3)
        return driver
    except NodeSeekError:
        close_driver(driver)
        raise
    except (TimeoutException, WebDriverException) as exc:
        close_driver(driver)
        raise NodeSeekError("浏览器页面初始化失败") from exc
    except Exception as exc:
        close_driver(driver)
        raise NodeSeekError("浏览器 Cookie 初始化失败") from exc


def collect_comment_urls(driver: Any, settings: Settings) -> list[str]:
    """用 BeautifulSoup 从评论区域提取非置顶帖子地址。"""
    driver.get(settings.comment_url)
    WebDriverWait(driver, ELEMENT_WAIT_TIMEOUT_SECONDS).until(
        lambda browser: browser.find_elements(By.CSS_SELECTOR, ".post-list-item")
    )
    soup = parse_page(driver)
    urls: list[str] = []
    for post in soup.select(".post-list-item"):
        post_classes = set(post.get("class", []))
        if (
            post_classes.intersection({"pined", "pinned"})
            or post.select_one(".pined, .pinned")
        ):
            continue
        link = post.select_one(".post-title a[href]")
        if not link:
            continue
        post_url = urljoin(settings.comment_url, link.get("href", ""))
        parsed = urlparse(post_url)
        if parsed.scheme == "https" and parsed.hostname in {
            "www.nodeseek.com",
            "nodeseek.com",
        }:
            urls.append(post_url)
    return list(dict.fromkeys(urls))


def perform_comments(driver: Any, settings: Settings) -> tuple[int, str]:
    """按原脚本流程执行有限数量的随机评论。"""
    try:
        urls = collect_comment_urls(driver, settings)
    except TimeoutException:
        return 0, "评论区域加载超时"
    except (NodeSeekError, WebDriverException) as exc:
        return 0, f"评论区域读取失败: {type(exc).__name__}"

    if not urls:
        return 0, "评论区域没有可用帖子"

    post_count = random.randint(*COMMENT_COUNT_RANGE)
    selected_urls = random.sample(urls, min(post_count, len(urls)))
    comment_count = 0
    consecutive_failures = 0
    for index, post_url in enumerate(selected_urls):
        if consecutive_failures >= MAX_COMMENT_FAILURES:
            break
        try:
            driver.get(post_url)
            editor = WebDriverWait(
                driver,
                ELEMENT_WAIT_TIMEOUT_SECONDS,
            ).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".CodeMirror"))
            )
            input_text = random.choice(COMMENT_TEXTS)
            driver.execute_script("arguments[0].click();", editor)
            js_ok = driver.execute_script(
                """
                var cm = arguments[0].CodeMirror;
                if (!cm) { return false; }
                cm.setValue(arguments[1]);
                if (cm.save) { cm.save(); }
                return true;
                """,
                editor,
                input_text,
            )
            if not js_ok:
                ActionChains(driver).move_to_element(editor).click().send_keys(
                    input_text
                ).perform()
            submit_button = WebDriverWait(
                driver,
                ELEMENT_WAIT_TIMEOUT_SECONDS,
            ).until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        "//button[contains(@class, 'submit') and "
                        "contains(@class, 'btn') and "
                        "contains(text(), '发布评论')]",
                    )
                )
            )
            driver.execute_script("arguments[0].click();", submit_button)
            comment_count += 1
            consecutive_failures = 0
            if index < len(selected_urls) - 1:
                time.sleep(random.uniform(*COMMENT_DELAY_RANGE_SECONDS))
        except (TimeoutException, WebDriverException) as exc:
            consecutive_failures += 1
            LOGGER.warning(
                "评论帖子处理失败 (%d/%d): %s",
                consecutive_failures,
                MAX_COMMENT_FAILURES,
                type(exc).__name__,
            )
            try:
                driver.get(SITE_ORIGIN)
                time.sleep(2)
            except WebDriverException:
                break

    if comment_count:
        return comment_count, f"评论 {comment_count} 条"
    return 0, "评论任务未完成"


def execute_account(
    index: int,
    cookie: str,
    settings: Settings,
) -> AccountResult:
    """执行单账号浏览器签到；失败不会影响后续账号。"""
    account_name = f"账号 {index}"
    valid, reason = validate_cookie(cookie)
    if not valid:
        return AccountResult(account_name, ResultStatus.FAILED, reason)

    driver = None
    try:
        LOGGER.info("开始处理账号 %d", index)
        driver = setup_driver_and_cookies(settings, cookie)
        if not check_login_status(driver):
            return AccountResult(
                account_name,
                ResultStatus.FAILED,
                "Cookie 已过期或未登录",
            )

        sign_status, reward = click_sign_icon(driver, settings)
        details = []
        if sign_status is SignInStatus.SUCCESS:
            details.append("签到成功")
            details.append(f"奖励 {reward} 鸡腿")
        elif sign_status is SignInStatus.ALREADY:
            details.append("今日已签到")
            details.append(f"奖励 {reward} 鸡腿")
        else:
            details.append(f"签到失败: {reward}")

        if sign_status is SignInStatus.SUCCESS and settings.enable_comments:
            _, comment_detail = perform_comments(driver, settings)
            details.append(comment_detail)
        elif sign_status is SignInStatus.ALREADY and settings.enable_comments:
            details.append("已签到，跳过重复评论")
        elif not settings.enable_comments:
            details.append("评论已关闭")

        result_status = (
            ResultStatus.FAILED
            if sign_status is SignInStatus.FAILED
            else ResultStatus.SUCCESS
        )
        return AccountResult(account_name, result_status, "，".join(details))
    except (NodeSeekError, WebDriverException) as exc:
        LOGGER.error(
            "账号 %d 执行失败: %s",
            index,
            type(exc).__name__,
        )
        return AccountResult(
            account_name,
            ResultStatus.FAILED,
            compact_message(exc) if isinstance(exc, NodeSeekError)
            else "浏览器操作失败",
        )
    finally:
        if driver is not None:
            close_driver(driver)


def calculate_global_status(results: list[AccountResult]) -> ResultStatus:
    """根据账号结果计算全局状态。"""
    if not results:
        return ResultStatus.FAILED
    success_count = sum(
        result.status == ResultStatus.SUCCESS for result in results
    )
    if success_count == len(results):
        return ResultStatus.SUCCESS
    if success_count == 0:
        return ResultStatus.FAILED
    return ResultStatus.PARTIAL_SUCCESS


def build_payload(results: list[AccountResult]) -> dict[str, Any]:
    """构建仓库统一通知 Payload。"""
    safe_results = results or [
        AccountResult("配置检查", ResultStatus.FAILED, "没有可执行的账号")
    ]
    success_count = sum(
        result.status == ResultStatus.SUCCESS for result in safe_results
    )
    failed_count = len(safe_results) - success_count
    return {
        "title": "NodeSeek 每日签到",
        "status": calculate_global_status(safe_results).value,
        "accounts": [result.as_payload() for result in safe_results],
        "summary": (
            f"共执行 {len(safe_results)} 个账号，成功 {success_count} 个，"
            f"失败 {failed_count} 个。"
        ),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def notify_results(results: list[AccountResult]) -> bool:
    """通过公共通知适配器发送结果，并隔离通知异常。"""
    try:
        send_payload(build_payload(results))
        return True
    except Exception as exc:
        LOGGER.error("通知调用失败: %s", type(exc).__name__)
        return False


def run() -> int:
    """加载配置并依次处理全部账号，最后发送一次汇总通知。"""
    try:
        settings = Settings.from_environment()
    except ConfigurationError as exc:
        notify_results(
            [AccountResult("配置检查", ResultStatus.FAILED, str(exc))]
        )
        return 1

    if not settings.cookies:
        notify_results(
            [
                AccountResult(
                    "配置检查",
                    ResultStatus.FAILED,
                    f"缺少必填环境变量 {COOKIE_ENV_NAME}",
                )
            ]
        )
        return 1

    initial_delay = settings.get_random_delay_seconds()
    if initial_delay:
        LOGGER.info("任务开始前随机等待 %d 分钟", initial_delay // 60)
        time.sleep(initial_delay)

    results: list[AccountResult] = []
    for offset, cookie in enumerate(settings.cookies):
        index = offset + 1
        try:
            results.append(execute_account(index, cookie, settings))
        except Exception as exc:
            LOGGER.error(
                "账号 %d 出现未预期异常: %s",
                index,
                type(exc).__name__,
            )
            results.append(
                AccountResult(
                    f"账号 {index}",
                    ResultStatus.FAILED,
                    f"未预期异常: {type(exc).__name__}",
                )
            )
        if offset < len(settings.cookies) - 1:
            time.sleep(random.uniform(*ACCOUNT_DELAY_RANGE_SECONDS))

    notification_ok = notify_results(results)
    all_succeeded = calculate_global_status(results) == ResultStatus.SUCCESS
    return 0 if all_succeeded and notification_ok else 1


def main() -> int:
    """配置日志并运行青龙入口。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
