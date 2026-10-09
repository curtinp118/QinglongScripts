# -*- coding: utf-8 -*-
"""
name: 成都地铁积分签到
description: 使用成都地铁 App 每日积分签到
cron: 10 9 * * *
env:
  - CDRAIL_HEADERS_JSON (必填): 抓包导出的请求头 JSON，多账号用 ||| 分割
version: 1.0.0
updated: 2026-10-09
disclaimer: 仅供学习交流，禁止用于商业用途，风险自负
"""

from __future__ import annotations

import json
import logging
import os
import random
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


LOGGER = logging.getLogger("cdrail")
HEADERS_ENV_NAME = "CDRAIL_HEADERS_JSON"
ACCOUNT_SEPARATOR = "|||"
SIGN_IN_URL = (
    "https://app.cdmetro.chengdurail.cn/"
    "platform/users/user/sign-in-integral"
)
REQUEST_TIMEOUT_SECONDS = 10
ACCOUNT_DELAY_RANGE_SECONDS = (0.5, 1.5)
MAX_MESSAGE_LENGTH = 160

DEFAULT_HEADERS = {
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh-Hans;q=0.9",
    "Host": "app.cdmetro.chengdurail.cn",
    "User-Agent": "CDMetro",
    "system-version": "",
    "system": "",
    "app-version": "",
    "appVersion": "",
    "device-id": "",
    "deviceId": "",
    "source": "",
    "vendor": "",
    "language": "",
    "user": "",
    "token": "",
    "app-token": "",
    "Cookie": "",
}


class ResultStatus(str, Enum):
    """仓库标准通知状态。"""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class CheckinCode(str, Enum):
    """成都地铁签到接口的业务状态码。"""

    SUCCESS = "0"
    ALREADY_CHECKED_IN = "1102"


class ConfigurationError(ValueError):
    """环境变量配置不合法。"""


class ServiceError(RuntimeError):
    """成都地铁请求或响应不合法。"""


@dataclass(frozen=True)
class AccountResult:
    """单账号签到结果。"""

    name: str
    status: ResultStatus
    detail: str

    def as_payload(self) -> dict[str, str]:
        """转换为统一通知账号结构。"""
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
        }


def compact_message(value: Any, fallback: str = "未知返回") -> str:
    """压缩服务端消息，避免通知和日志出现巨型内容。"""
    message = " ".join(str(value or fallback).split())
    return message[:MAX_MESSAGE_LENGTH]


def normalize_header_value(value: Any) -> str:
    """仅接受可安全转换为请求头文本的标量值。"""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    raise ConfigurationError("请求头值必须是字符串或基本标量")


def parse_headers(raw_headers: str) -> dict[str, str]:
    """解析单账号 JSON 请求头，并按原脚本规则补齐字段。"""
    try:
        payload = json.loads(raw_headers)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("请求头不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError("请求头 JSON 顶层必须是对象")

    casefolded = {
        str(key).casefold(): value for key, value in payload.items()
    }
    selected: dict[str, str] = {}
    for name, default in DEFAULT_HEADERS.items():
        value = casefolded.get(name.casefold())
        if value is None and name in {"device-id", "deviceId"}:
            alternate = "deviceid" if name == "device-id" else "device-id"
            value = casefolded.get(alternate.casefold())
        selected[name] = (
            normalize_header_value(value) if value is not None else default
        )

    if not selected["Cookie"].strip() and not selected["token"].strip():
        raise ConfigurationError("请求头至少需要 Cookie 或 token")
    return selected


def load_headers() -> tuple[dict[str, str], ...]:
    """从环境变量读取一个或多个账号的请求头 JSON。"""
    raw = os.environ.get(HEADERS_ENV_NAME, "")
    if not raw.strip():
        return ()
    headers: list[dict[str, str]] = []
    for index, item in enumerate(raw.split(ACCOUNT_SEPARATOR), start=1):
        if not item.strip():
            continue
        try:
            headers.append(parse_headers(item.strip()))
        except ConfigurationError as exc:
            raise ConfigurationError(f"第 {index} 个账号: {exc}") from exc
    return tuple(headers)


def parse_response(payload_text: str) -> dict[str, Any]:
    """安全解析接口 JSON 响应。"""
    try:
        payload = json.loads(payload_text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ServiceError("服务返回非 JSON 数据") from exc
    if not isinstance(payload, dict):
        raise ServiceError("服务返回的 JSON 顶层不是对象")
    return payload


class CDRailClient:
    """封装成都地铁签到请求。"""

    def __init__(self, headers: dict[str, str]) -> None:
        self.session = requests.Session()
        self.headers = headers

    def __enter__(self) -> "CDRailClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.session.close()

    def checkin(self) -> tuple[CheckinCode | None, str, str | None]:
        """执行一次签到，返回业务码、消息和新增积分。"""
        try:
            response = self.session.get(
                SIGN_IN_URL,
                headers=self.headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise ServiceError(f"网络请求失败: {type(exc).__name__}") from exc

        if response.status_code in {401, 403}:
            raise ServiceError(f"登录失效: HTTP {response.status_code}")
        if not 200 <= response.status_code < 300:
            raise ServiceError(f"接口异常: HTTP {response.status_code}")

        payload = parse_response(response.text)
        raw_message = payload.get("message") or payload.get("msg") or ""
        message = compact_message(raw_message)
        raw_code = (
            payload["code"]
            if "code" in payload
            else payload.get("status", "")
        )
        code = CheckinCode(str(raw_code)) if str(raw_code) in {
            item.value for item in CheckinCode
        } else None
        increment: str | None = None
        data = payload.get("data")
        if isinstance(data, dict) and data.get("integralIncrement") is not None:
            increment = compact_message(data["integralIncrement"])
        return code, message, increment


def execute_account(index: int, headers: dict[str, str]) -> AccountResult:
    """执行单账号签到，失败不影响其他账号。"""
    account_name = f"账号 {index}"
    LOGGER.info("开始处理账号 %d", index)
    try:
        with CDRailClient(headers) as client:
            code, message, increment = client.checkin()
    except ServiceError as exc:
        LOGGER.error("账号 %d 执行失败: %s", index, exc, exc_info=True)
        return AccountResult(account_name, ResultStatus.FAILED, compact_message(exc))
    except Exception as exc:
        LOGGER.error(
            "账号 %d 出现未预期异常: %s",
            index,
            type(exc).__name__,
            exc_info=True,
        )
        return AccountResult(
            account_name,
            ResultStatus.FAILED,
            f"执行异常: {type(exc).__name__}",
        )

    if code == CheckinCode.SUCCESS and message in {"", "SUCCESS"}:
        detail = "签到成功"
        if increment:
            detail += f"，获得 {increment} 积分"
        return AccountResult(account_name, ResultStatus.SUCCESS, detail)
    if code == CheckinCode.ALREADY_CHECKED_IN:
        return AccountResult(
            account_name,
            ResultStatus.SUCCESS,
            message or "今日已签到",
        )
    return AccountResult(
        account_name,
        ResultStatus.FAILED,
        message or "签到失败，返回异常",
    )


def calculate_global_status(results: list[AccountResult]) -> ResultStatus:
    """根据账号结果计算全局状态。"""
    success_count = sum(
        result.status == ResultStatus.SUCCESS for result in results
    )
    if success_count == len(results):
        return ResultStatus.SUCCESS
    return (
        ResultStatus.FAILED
        if success_count == 0
        else ResultStatus.PARTIAL_SUCCESS
    )


def build_payload(results: list[AccountResult]) -> dict[str, Any]:
    """构建仓库统一通知 Payload。"""
    success_count = sum(
        result.status == ResultStatus.SUCCESS for result in results
    )
    failed_count = len(results) - success_count
    return {
        "title": "成都地铁积分签到",
        "status": calculate_global_status(results).value,
        "accounts": [result.as_payload() for result in results],
        "summary": (
            f"共执行 {len(results)} 个账号，成功 {success_count} 个，"
            f"失败 {failed_count} 个。"
        ),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def notify_results(results: list[AccountResult]) -> bool:
    """调用全局通知适配器，并隔离通知异常。"""
    try:
        send_payload(build_payload(results))
        return True
    except Exception as exc:
        LOGGER.error("通知调用失败: %s", exc, exc_info=True)
        return False


def run() -> int:
    """读取配置并依次执行所有账号。"""
    try:
        headers_list = load_headers()
    except ConfigurationError as exc:
        results = [AccountResult("配置检查", ResultStatus.FAILED, str(exc))]
        notify_results(results)
        return 1

    if not headers_list:
        results = [
            AccountResult(
                "配置检查",
                ResultStatus.FAILED,
                f"缺少必填环境变量 {HEADERS_ENV_NAME}",
            )
        ]
        notify_results(results)
        return 1

    results: list[AccountResult] = []
    for offset, headers in enumerate(headers_list):
        results.append(execute_account(offset + 1, headers))
        if offset < len(headers_list) - 1:
            time.sleep(random.uniform(*ACCOUNT_DELAY_RANGE_SECONDS))

    notification_ok = notify_results(results)
    return (
        0
        if calculate_global_status(results) == ResultStatus.SUCCESS
        and notification_ok
        else 1
    )


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
