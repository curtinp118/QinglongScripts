# -*- coding: utf-8 -*-
"""
name: NodeSeek 每日签到
description: 使用账号 Cookie 执行 NodeSeek 多账号每日签到
cron: 10 9 * * *
env:
  - NODESEEK_COOKIES (必填): NodeSeek Cookie，多账号用 ||| 分割
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
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from notification_adapter import send_payload  # noqa: E402


LOGGER = logging.getLogger("nodeseek")
COOKIE_ENV_NAME = "NODESEEK_COOKIES"
ACCOUNT_SEPARATOR = "|||"
CHECKIN_URL = "https://www.nodeseek.com/api/attendance"
SITE_ORIGIN = "https://www.nodeseek.com"
REQUEST_TIMEOUT_SECONDS = 10
MAX_REQUEST_ATTEMPTS = 3
MAX_MESSAGE_LENGTH = 160
ACCOUNT_DELAY_RANGE_SECONDS = (0.5, 1.5)
REPEAT_MARKERS = ("已完成签到", "请勿重复", "已经签到", "already")


class ResultStatus(str, Enum):
    """仓库标准通知状态。"""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class NodeSeekError(RuntimeError):
    """NodeSeek 请求或响应错误。"""


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
    """验证 Cookie 至少包含一个合法的名称和值。"""
    pairs = []
    for chunk in cookie.split(";"):
        name, separator, value = chunk.strip().partition("=")
        if separator and name.strip() and value.strip():
            pairs.append((name.strip(), value.strip()))
    if not pairs:
        return False, "Cookie 格式无效，应为 name=value"
    return True, ""


def compact_message(value: Any, fallback: str = "未知错误") -> str:
    """压缩服务消息，避免输出冗长响应。"""
    message = " ".join(str(value or fallback).split())
    return message[:MAX_MESSAGE_LENGTH]


def format_metric(value: Any) -> str | None:
    """安全格式化积分字段。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str) and len(value.strip()) <= 32:
        return value.strip() or None
    return None


class NodeSeekClient:
    """封装 NodeSeek 签到请求。"""

    def __init__(self, cookie: str) -> None:
        self.session = requests.Session()
        self.headers = {
            "accept": "application/json, text/plain, */*",
            "cookie": cookie,
            "origin": SITE_ORIGIN,
            "referer": f"{SITE_ORIGIN}/board",
            "user-agent": (
                "QingLongScripts-NodeSeek/1.0 "
                "(+https://github.com/curtinp118/QinglongScripts)"
            ),
        }

    def __enter__(self) -> "NodeSeekClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.session.close()

    def request_checkin(self) -> dict[str, Any]:
        """请求签到接口，对网络错误、429 和 5xx 有限重试。"""
        last_error: Exception | None = None
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                response = self.session.post(
                    CHECKIN_URL,
                    params={"random": "true"},
                    headers=self.headers,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                if response.status_code == 403:
                    raise NodeSeekError(
                        "HTTP 403，访问被拒绝，请重新登录并更新 Cookie"
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = NodeSeekError(
                        f"服务暂不可用: HTTP {response.status_code}"
                    )
                elif 400 <= response.status_code < 500:
                    raise NodeSeekError(
                        f"HTTP {response.status_code}，请检查 Cookie 是否有效"
                    )
                else:
                    response.raise_for_status()
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise NodeSeekError("服务返回非 JSON 数据") from exc
                    if not isinstance(payload, dict):
                        raise NodeSeekError("服务返回的 JSON 顶层不是对象")
                    return payload
            except NodeSeekError:
                raise
            except requests.RequestException as exc:
                last_error = exc

            if attempt < MAX_REQUEST_ATTEMPTS:
                wait_seconds = 2 ** (attempt - 1) + random.uniform(0, 0.5)
                LOGGER.warning(
                    "请求失败，第 %d/%d 次，%.1f 秒后重试",
                    attempt,
                    MAX_REQUEST_ATTEMPTS,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        message = compact_message(last_error, "未知请求错误")
        raise NodeSeekError(f"请求失败: {message}") from last_error


def parse_checkin_result(
    account_name: str,
    payload: dict[str, Any],
) -> AccountResult:
    """将 NodeSeek 响应转换为标准账号结果。"""
    message = compact_message(payload.get("message"), "签到接口未返回说明")
    if payload.get("success") is True:
        details = ["签到成功"]
        gain = format_metric(payload.get("gain"))
        current = format_metric(payload.get("current"))
        if gain is not None:
            details.append(f"获得 {gain} 鸡腿")
        if current is not None:
            details.append(f"当前共 {current} 鸡腿")
        return AccountResult(
            account_name,
            ResultStatus.SUCCESS,
            "，".join(details),
        )

    if any(marker.lower() in message.lower() for marker in REPEAT_MARKERS):
        return AccountResult(
            account_name,
            ResultStatus.SUCCESS,
            f"今日已签到: {message}",
        )

    return AccountResult(
        account_name,
        ResultStatus.FAILED,
        f"签到失败: {message}",
    )


def execute_account(index: int, cookie: str) -> AccountResult:
    """执行单账号签到，不让失败影响后续账号。"""
    account_name = f"账号 {index}"
    valid, reason = validate_cookie(cookie)
    if not valid:
        return AccountResult(account_name, ResultStatus.FAILED, reason)

    LOGGER.info("开始处理账号 %d", index)
    try:
        with NodeSeekClient(cookie) as client:
            payload = client.request_checkin()
        return parse_checkin_result(account_name, payload)
    except (NodeSeekError, requests.RequestException) as exc:
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
        "title": "NodeSeek 每日签到",
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
