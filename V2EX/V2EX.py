# -*- coding: utf-8 -*-
"""
name: V2EX 每日签到
description: 使用账号 Cookie 领取 V2EX 每日登录奖励并查询账户余额
cron: 20 9 * * *
env:
  - V2EX_COOKIES (必填): V2EX Cookie，多账号用 ||| 分割
version: 1.0.0
updated: 2026-09-08
disclaimer: 仅供学习交流，禁止用于商业用途，风险自负
"""

from __future__ import annotations

import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from notification_adapter import send_payload  # noqa: E402


LOGGER = logging.getLogger("v2ex")
COOKIE_ENV_NAME = "V2EX_COOKIES"
ACCOUNT_SEPARATOR = "|||"
BASE_URL = "https://www.v2ex.com"
DAILY_PATH = "/mission/daily"
BALANCE_PATH = "/balance"
REQUEST_TIMEOUT_SECONDS = 10
MAX_READ_ATTEMPTS = 3
MAX_MESSAGE_LENGTH = 160
ACCOUNT_DELAY_RANGE_SECONDS = (0.5, 1.5)
REDEEM_PATH_PATTERN = re.compile(
    r"(/mission/daily/redeem\?once=[A-Za-z0-9_-]+)"
)
LOGIN_MARKERS = (
    "你要查看的页面需要先登录",
    "you need to sign in first",
)
CLAIMED_MARKERS = (
    "每日登录奖励已领取",
    "今日的登录奖励已领取",
    "daily login reward has been claimed",
)
CLAIM_SUCCESS_MARKERS = (
    "已成功领取每日登录奖励",
    "每日登录奖励已领取",
)
RECLICK_MARKERS = ("请重新点击一次以领取每日登录奖励",)
STREAK_PATTERN = re.compile(r"已连续登录\s*(\d+)\s*天")
REWARD_PATTERNS = (
    re.compile(r"已成功领取每日登录奖励\s*(\d+(?:\.\d+)?)\s*铜币"),
    re.compile(r"\d{8}\s*的每日登录奖励\s*(\d+(?:\.\d+)?)\s*铜币"),
)


class ResultStatus(str, Enum):
    """仓库标准通知状态。"""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class V2EXError(RuntimeError):
    """V2EX 请求或页面解析错误。"""


@dataclass(frozen=True)
class AccountResult:
    """单账号签到结果。"""

    name: str
    status: ResultStatus
    detail: str

    def as_payload(self) -> dict[str, str]:
        """转换为通知账号结构。"""
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DailyState:
    """每日任务页面的解析结果。"""

    requires_login: bool
    already_claimed: bool
    redeem_path: str | None
    streak_days: str | None
    text: str


class V2EXPageParser(HTMLParser):
    """提取每日任务链接、页面文本和余额区域。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.balance_parts: list[str] = []
        self.redeem_path: str | None = None
        self._balance_div_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """检查标签属性，并跟踪余额区域的 div 层级。"""
        attributes = dict(attrs)
        if tag == "div":
            if self._balance_div_depth:
                self._balance_div_depth += 1
            else:
                classes = set((attributes.get("class") or "").split())
                if {"balance_area", "bigger"}.issubset(classes):
                    self._balance_div_depth = 1

        if self.redeem_path is None:
            for value in attributes.values():
                match = REDEEM_PATH_PATTERN.search(value or "")
                if match:
                    self.redeem_path = match.group(1)
                    break

    def handle_endtag(self, tag: str) -> None:
        """结束余额区域的 div 层级跟踪。"""
        if tag == "div" and self._balance_div_depth:
            self._balance_div_depth -= 1

    def handle_data(self, data: str) -> None:
        """收集可见文本，不保留原始 HTML。"""
        text = " ".join(data.split())
        if not text:
            return
        self.text_parts.append(text)
        if self._balance_div_depth:
            self.balance_parts.append(text)


def normalize_cookie(raw_cookie: str) -> str:
    """清理 Cookie 两端引号并合并意外换行。"""
    cookie = raw_cookie.strip().strip("\"'")
    return re.sub(r"[\r\n]+", "; ", cookie)


def load_cookies() -> tuple[str, ...]:
    """从环境变量读取多账号 Cookie。"""
    raw_cookies = os.environ.get(COOKIE_ENV_NAME, "")
    return tuple(
        normalize_cookie(item)
        for item in raw_cookies.split(ACCOUNT_SEPARATOR)
        if item.strip()
    )


def validate_cookie(cookie: str) -> tuple[bool, str]:
    """验证 Cookie 至少包含一个合法名称和值。"""
    valid_pairs = 0
    for chunk in cookie.split(";"):
        name, separator, value = chunk.strip().partition("=")
        if separator and name.strip() and value.strip():
            valid_pairs += 1
    if valid_pairs == 0:
        return False, "Cookie 格式无效，应为 name=value"
    return True, ""


def compact_message(value: Any, fallback: str = "未知错误") -> str:
    """压缩服务消息，避免输出冗长页面内容。"""
    message = " ".join(str(value or fallback).split())
    return message[:MAX_MESSAGE_LENGTH]


def parse_page(content: str) -> V2EXPageParser:
    """使用容错 HTML 解析器处理页面。"""
    parser = V2EXPageParser()
    try:
        parser.feed(content)
        parser.close()
    except Exception as exc:
        raise V2EXError("页面 HTML 解析失败") from exc
    return parser


def inspect_daily_page(content: str, response_url: str) -> DailyState:
    """识别登录状态、领取状态、领取链接和连续登录天数。"""
    parser = parse_page(content)
    text = " ".join(parser.text_parts)
    lowered_text = text.lower()
    response_path = urlparse(response_url).path
    requires_login = response_path == "/signin" or any(
        marker in lowered_text for marker in LOGIN_MARKERS
    )
    already_claimed = any(
        marker in lowered_text for marker in CLAIMED_MARKERS
    )
    streak_match = STREAK_PATTERN.search(text)
    return DailyState(
        requires_login=requires_login,
        already_claimed=already_claimed,
        redeem_path=parser.redeem_path,
        streak_days=streak_match.group(1) if streak_match else None,
        text=text,
    )


def extract_reward(*page_texts: str) -> str | None:
    """从领取页或余额页提取当日铜币奖励。"""
    combined = " ".join(page_texts)
    for pattern in REWARD_PATTERNS:
        match = pattern.search(combined)
        if match:
            return match.group(1)
    return None


def extract_balance(content: str) -> str | None:
    """从余额区域提取金币、银币和铜币。"""
    values = parse_page(content).balance_parts
    if len(values) == 2:
        values = ["0", *values]
    if len(values) != 3:
        return None
    if any(len(value) > 32 for value in values):
        return None
    golden, silver, bronze = values
    return f"{golden} 金币，{silver} 银币，{bronze} 铜币"


class V2EXClient:
    """封装 V2EX 每日任务请求。"""

    def __init__(self, cookie: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "accept-language": "zh-CN,zh;q=0.9,en;q=0.7",
                "cookie": cookie,
                "user-agent": (
                    "QingLongScripts-V2EX/1.0 "
                    "(+https://github.com/curtinp118/QinglongScripts)"
                ),
            }
        )

    def __enter__(self) -> "V2EXClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.session.close()

    def _get(self, path: str, *, retry_read: bool) -> requests.Response:
        """执行受限 GET；仅只读页面允许网络与服务错误重试。"""
        attempts = MAX_READ_ATTEMPTS if retry_read else 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.get(
                    urljoin(BASE_URL, path),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                if response.status_code == 403:
                    raise V2EXError("HTTP 403，访问被拒绝")
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = V2EXError(
                        f"服务暂不可用: HTTP {response.status_code}"
                    )
                elif 400 <= response.status_code < 500:
                    raise V2EXError(f"请求失败: HTTP {response.status_code}")
                else:
                    response.raise_for_status()
                    return response
            except V2EXError:
                raise
            except requests.RequestException as exc:
                last_error = exc

            if attempt < attempts:
                wait_seconds = 2 ** (attempt - 1) + random.uniform(0, 0.5)
                LOGGER.warning(
                    "读取页面失败，第 %d/%d 次，%.1f 秒后重试",
                    attempt,
                    attempts,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        message = compact_message(last_error, "未知请求错误")
        raise V2EXError(f"请求失败: {message}") from last_error

    def get_daily(self) -> requests.Response:
        """读取每日任务页面。"""
        return self._get(DAILY_PATH, retry_read=True)

    def redeem(self, redeem_path: str) -> requests.Response:
        """领取每日奖励，不对有副作用的请求做网络重试。"""
        if not REDEEM_PATH_PATTERN.fullmatch(redeem_path):
            raise V2EXError("领取链接格式无效")
        return self._get(redeem_path, retry_read=False)

    def get_balance(self) -> requests.Response:
        """读取账户余额页面。"""
        return self._get(BALANCE_PATH, retry_read=True)


def build_success_detail(
    prefix: str,
    client: V2EXClient,
    *known_page_texts: str,
) -> str:
    """在不改变签到结果的前提下补充奖励和余额。"""
    details = [prefix]
    try:
        balance_response = client.get_balance()
        balance_parser = parse_page(balance_response.text)
        balance_text = " ".join(balance_parser.text_parts)
        reward = extract_reward(*known_page_texts, balance_text)
        balance = extract_balance(balance_response.text)
        if reward:
            details.append(f"今日奖励 {reward} 铜币")
        if balance:
            details.append(f"余额 {balance}")
        if not reward and not balance:
            details.append("未能解析奖励与余额")
    except V2EXError as exc:
        details.append(f"余额查询失败: {compact_message(exc)}")
    return "，".join(details)


def perform_checkin(client: V2EXClient) -> tuple[bool, str]:
    """执行一次幂等签到，并在响应不确定时重新读取状态。"""
    daily_response = client.get_daily()
    initial_state = inspect_daily_page(
        daily_response.text,
        daily_response.url,
    )
    if initial_state.requires_login:
        return False, "登录状态无效，请重新登录并更新 Cookie"
    if initial_state.already_claimed:
        prefix = "今日已签到"
        if initial_state.streak_days:
            prefix += f"，已连续登录 {initial_state.streak_days} 天"
        return True, build_success_detail(
            prefix,
            client,
            initial_state.text,
        )
    if not initial_state.redeem_path:
        return False, "无法获取领取链接，页面结构可能已变更"

    claim_texts: list[str] = []
    claim_error: V2EXError | None = None
    redeem_path = initial_state.redeem_path
    for claim_attempt in range(2):
        try:
            claim_response = client.redeem(redeem_path)
            claim_parser = parse_page(claim_response.text)
            claim_text = " ".join(claim_parser.text_parts)
            claim_texts.append(claim_text)
            if not any(marker in claim_text for marker in RECLICK_MARKERS):
                break
        except V2EXError as exc:
            claim_error = exc
            break

        if claim_attempt == 0:
            refreshed_response = client.get_daily()
            refreshed_state = inspect_daily_page(
                refreshed_response.text,
                refreshed_response.url,
            )
            if refreshed_state.already_claimed:
                break
            if not refreshed_state.redeem_path:
                break
            redeem_path = refreshed_state.redeem_path

    claim_confirmed = any(
        marker in text
        for text in claim_texts
        for marker in CLAIM_SUCCESS_MARKERS
    )
    try:
        verification_response = client.get_daily()
        verification_state = inspect_daily_page(
            verification_response.text,
            verification_response.url,
        )
        if verification_state.requires_login:
            return False, "签到后登录状态失效，请更新 Cookie"
        claim_confirmed = claim_confirmed or verification_state.already_claimed
    except V2EXError:
        if not claim_confirmed:
            if claim_error:
                raise claim_error
            raise
        verification_state = initial_state

    if not claim_confirmed:
        if claim_error:
            return False, f"领取请求失败: {compact_message(claim_error)}"
        return False, "签到结果无法确认，请检查 Cookie 或页面结构"

    prefix = "签到成功"
    if verification_state.streak_days:
        prefix += f"，已连续登录 {verification_state.streak_days} 天"
    return True, build_success_detail(prefix, client, *claim_texts)


def execute_account(index: int, cookie: str) -> AccountResult:
    """执行单账号签到，不让失败影响后续账号。"""
    account_name = f"账号 {index}"
    valid, reason = validate_cookie(cookie)
    if not valid:
        return AccountResult(account_name, ResultStatus.FAILED, reason)

    LOGGER.info("开始处理账号 %d", index)
    try:
        with V2EXClient(cookie) as client:
            succeeded, detail = perform_checkin(client)
        status = ResultStatus.SUCCESS if succeeded else ResultStatus.FAILED
        return AccountResult(account_name, status, detail)
    except (V2EXError, requests.RequestException) as exc:
        LOGGER.error("账号 %d 执行失败: %s", index, exc, exc_info=True)
        return AccountResult(
            account_name,
            ResultStatus.FAILED,
            compact_message(exc),
        )


def calculate_global_status(results: list[AccountResult]) -> ResultStatus:
    """根据账号结果计算全局状态。"""
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
    success_count = sum(
        result.status == ResultStatus.SUCCESS for result in results
    )
    failed_count = len(results) - success_count
    return {
        "title": "V2EX 每日签到",
        "status": calculate_global_status(results).value,
        "accounts": [result.as_payload() for result in results],
        "summary": (
            f"共执行 {len(results)} 个账号，成功 {success_count} 个，"
            f"失败 {failed_count} 个。"
        ),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def notify_results(results: list[AccountResult]) -> bool:
    """发送统一通知，并捕获通知入口异常。"""
    try:
        send_payload(build_payload(results))
        return True
    except Exception as exc:
        LOGGER.error("通知调用失败: %s", exc, exc_info=True)
        return False


def run() -> int:
    """依次处理全部账号并发送汇总通知。"""
    cookies = load_cookies()
    if not cookies:
        results = [
            AccountResult(
                "配置检查",
                ResultStatus.FAILED,
                f"缺少必填环境变量 {COOKIE_ENV_NAME}",
            )
        ]
        notify_results(results)
        return 1

    results = []
    for offset, cookie in enumerate(cookies):
        index = offset + 1
        try:
            results.append(execute_account(index, cookie))
        except Exception as exc:
            LOGGER.error(
                "账号 %d 出现未预期异常: %s",
                index,
                exc,
                exc_info=True,
            )
            results.append(
                AccountResult(
                    f"账号 {index}",
                    ResultStatus.FAILED,
                    f"未预期异常: {type(exc).__name__}",
                )
            )
        if offset < len(cookies) - 1:
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
