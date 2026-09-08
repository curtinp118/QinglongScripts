# -*- coding: utf-8 -*-
"""
脚本名称: GLaDOS 自动签到脚本
功能描述: 多账号执行 GLaDOS 签到，并查询积分与剩余天数
Cron: 0 8 * * *
环境变量:
  - GLADOS_COOKIES (必填): GLaDOS Cookie，多账号用 ||| 分割
  - GLADOS_DOMAINS (选填): HTTPS 服务域名，多域名用 ||| 分割
  - GLADOS_EXCHANGE_PLAN (选填): 自动兑换计划，默认关闭
更新时间: 2026-09-08
声明: 仅供学习交流，禁止用于商业用途，风险自负
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
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from notification_adapter import send_payload  # noqa: E402


LOGGER = logging.getLogger("glados")
COOKIE_ENV_NAME = "GLADOS_COOKIES"
DOMAIN_ENV_NAME = "GLADOS_DOMAINS"
EXCHANGE_ENV_NAME = "GLADOS_EXCHANGE_PLAN"
ACCOUNT_SEPARATOR = "|||"
DEFAULT_DOMAIN = "glados.cloud"
KNOWN_DOMAINS = frozenset({"glados.cloud", "railgun.info"})
REQUIRED_COOKIE_KEYS = frozenset({"koa:sess", "koa:sess.sig"})
EXCHANGE_PLANS = {"plan100": 100, "plan200": 200, "plan500": 500}
DISABLED_VALUES = frozenset(
    {"", "0", "false", "off", "none", "disable", "disabled"}
)
DOMAIN_PATTERN = re.compile(
    r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}"
)
REQUEST_TIMEOUT_SECONDS = 10
MAX_REQUEST_ATTEMPTS = 3
MAX_SERVICE_MESSAGE_LENGTH = 120
ACCOUNT_DELAY_RANGE_SECONDS = (0.5, 1.5)


class CheckinCode(IntEnum):
    """GLaDOS 签到接口的已知业务状态码。"""

    SUCCESS = 0
    ALREADY_CHECKED_IN = 1


class ResultStatus(str, Enum):
    """仓库标准通知状态。"""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class ConfigurationError(ValueError):
    """环境变量配置不合法。"""


class ServiceError(RuntimeError):
    """GLaDOS 服务请求或响应不合法。"""


@dataclass(frozen=True)
class Settings:
    """经过校验的脚本配置。"""

    cookies: tuple[str, ...]
    domains: tuple[str, ...]
    exchange_plan: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        """从项目专用环境变量读取配置。"""
        raw_cookies = os.environ.get(COOKIE_ENV_NAME, "")
        cookies = tuple(
            normalize_cookie(item)
            for item in raw_cookies.split(ACCOUNT_SEPARATOR)
            if item.strip()
        )

        raw_domains = os.environ.get(DOMAIN_ENV_NAME, DEFAULT_DOMAIN)
        domain_items = (
            normalize_domain(item)
            for item in raw_domains.split(ACCOUNT_SEPARATOR)
        )
        domains = tuple(dict.fromkeys(item for item in domain_items if item))
        if not domains:
            raise ConfigurationError(f"{DOMAIN_ENV_NAME} 未包含有效域名")

        custom_domains = sorted(set(domains) - KNOWN_DOMAINS)
        if custom_domains:
            joined = ", ".join(custom_domains)
            LOGGER.warning(
                "将向显式配置的自定义域名发送 Cookie: %s",
                joined,
            )

        raw_plan = os.environ.get(EXCHANGE_ENV_NAME, "").strip().lower()
        exchange_plan = None if raw_plan in DISABLED_VALUES else raw_plan
        if exchange_plan is not None and exchange_plan not in EXCHANGE_PLANS:
            raise ConfigurationError(
                f"{EXCHANGE_ENV_NAME} 仅支持: "
                f"{', '.join(EXCHANGE_PLANS)}"
            )
        return cls(
            cookies=cookies,
            domains=domains,
            exchange_plan=exchange_plan,
        )


@dataclass(frozen=True)
class AccountResult:
    """单账号在单个域名上的执行结果。"""

    name: str
    status: ResultStatus
    detail: str

    def as_payload(self) -> dict[str, str]:
        """转换为通知 Payload 的账号详情。"""
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
        }


def normalize_cookie(raw_cookie: str) -> str:
    """规范抓包工具可能产生的 Cookie 展示格式。"""
    cookie = raw_cookie.strip().strip("\"'")
    cookie = re.sub(r"[\r\n]+", "; ", cookie)
    cookie = re.sub(r"koa:sess\.sig(?!=)", "koa:sess.sig=", cookie)
    cookie = re.sub(r"koa:sess(?!\.sig)(?!=)", "koa:sess=", cookie)
    return cookie


def normalize_domain(raw_domain: str) -> str:
    """规范并校验自定义 HTTPS 主机名。"""
    domain = raw_domain.strip().strip("\"'").lower()
    if domain.startswith("http://"):
        raise ConfigurationError("自定义域名必须使用 HTTPS")
    domain = re.sub(r"^https://", "", domain)
    if any(character in domain for character in ("/", "@", ":", "?", "#")):
        raise ConfigurationError(f"域名格式无效: {domain}")
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise ConfigurationError(f"域名格式无效: {domain}")
    return domain


def validate_cookie(cookie: str) -> tuple[bool, str]:
    """检查签到接口要求的 Cookie 字段，不记录字段值。"""
    keys = {
        part.split("=", maxsplit=1)[0].strip()
        for part in cookie.split(";")
        if "=" in part
    }
    missing = sorted(REQUIRED_COOKIE_KEYS - keys)
    if missing:
        return False, f"Cookie 缺少必要字段: {', '.join(missing)}"
    return True, ""


def compact_message(value: Any, fallback: str = "未知错误") -> str:
    """压缩服务消息，避免日志或通知出现超长响应。"""
    message = " ".join(str(value or fallback).split())
    return message[:MAX_SERVICE_MESSAGE_LENGTH]


def parse_integer(value: Any) -> int | None:
    """防御性解析接口中的整数值。"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_earned_points(message: str) -> int:
    """从中英文签到提示中提取本次积分。"""
    match = re.search(
        r"(?:got\s+|获得\s*)(\d+)\s*(?:points?|点|积分)?",
        message,
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match else 0


class GLaDOSClient:
    """封装单账号的 GLaDOS API 调用。"""

    def __init__(self, domain: str, cookie: str) -> None:
        self.domain = domain
        self.session = requests.Session()
        self.headers = {
            "cookie": cookie,
            "origin": f"https://{domain}",
            "referer": f"https://{domain}/console/checkin",
            "user-agent": "QingLong-GLaDOS/1.0",
        }

    def __enter__(self) -> "GLaDOSClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.session.close()

    def _request_json(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """请求 JSON 接口，对网络错误、429 和 5xx 有限重试。"""
        url = f"https://{self.domain}{path}"
        last_error: Exception | None = None

        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=self.headers,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    **kwargs,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise ServiceError(
                        f"服务暂不可用: HTTP {response.status_code}"
                    )
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise ServiceError("服务返回非 JSON 数据") from exc
                if not isinstance(payload, dict):
                    raise ServiceError("服务返回的 JSON 顶层不是对象")
                return payload
            except (requests.RequestException, ServiceError) as exc:
                last_error = exc
                retryable = isinstance(exc, requests.RequestException)
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    status_code = exc.response.status_code
                    retryable = status_code == 429 or status_code >= 500
                if isinstance(exc, ServiceError):
                    retryable = "HTTP 429" in str(exc) or "HTTP 5" in str(exc)

                if not retryable or attempt == MAX_REQUEST_ATTEMPTS:
                    break
                wait_seconds = 2 ** (attempt - 1) + random.uniform(0, 0.5)
                LOGGER.warning(
                    "请求失败，第 %d/%d 次，%.1f 秒后重试",
                    attempt,
                    MAX_REQUEST_ATTEMPTS,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        error_name = type(last_error).__name__ if last_error else "UnknownError"
        raise ServiceError(f"请求失败: {error_name}") from last_error

    def checkin(self) -> tuple[CheckinCode | None, str, int]:
        """执行一次幂等签到并返回状态、消息和本次积分。"""
        payload = self._request_json(
            "POST",
            "/api/user/checkin",
            json={"token": self.domain},
        )
        code_value = parse_integer(payload.get("code"))
        message = compact_message(payload.get("message"))
        try:
            code = CheckinCode(code_value) if code_value is not None else None
        except ValueError:
            code = None
        return code, message, parse_earned_points(message)

    def query_remaining_days(self) -> str:
        """查询会员剩余天数，字段缺失时返回未知。"""
        payload = self._request_json("GET", "/api/user/status")
        data = payload.get("data")
        if not isinstance(data, dict):
            return "未知"
        days = parse_integer(data.get("leftDays"))
        return f"{days} 天" if days is not None else "未知"

    def query_total_points(self) -> tuple[str, int | None]:
        """查询账号总积分，兼容两种常见响应结构。"""
        payload = self._request_json("GET", "/api/user/points")
        value = payload.get("points")
        if value is None and isinstance(payload.get("data"), dict):
            value = payload["data"].get("points")
        points = parse_integer(value)
        label = f"{points} 积分" if points is not None else "未知"
        return label, points

    def exchange_points(self, plan: str) -> tuple[bool, str]:
        """执行一次积分兑换，并返回是否成功及简短结果。"""
        payload = self._request_json(
            "POST",
            "/api/user/exchange",
            data={"planType": plan},
        )
        code = parse_integer(payload.get("code"))
        if code == CheckinCode.SUCCESS:
            return True, f"自动兑换 {plan} 成功"
        message = compact_message(payload.get("message"))
        return False, f"自动兑换 {plan} 失败: {message}"


def execute_account(
    index: int,
    domain: str,
    cookie: str,
    exchange_plan: str | None,
) -> AccountResult:
    """执行单账号任务；查询附加信息失败不会覆盖签到结果。"""
    account_name = f"账号 {index} @ {domain}"
    valid, reason = validate_cookie(cookie)
    if not valid:
        return AccountResult(account_name, ResultStatus.FAILED, reason)

    LOGGER.info("开始处理账号 %d，域名 %s", index, domain)
    try:
        with GLaDOSClient(domain, cookie) as client:
            code, message, earned = client.checkin()
            if code not in {
                CheckinCode.SUCCESS,
                CheckinCode.ALREADY_CHECKED_IN,
            }:
                return AccountResult(
                    account_name,
                    ResultStatus.FAILED,
                    f"签到失败: {message}",
                )

            detail_items = []
            if code == CheckinCode.SUCCESS:
                detail_items.append(f"签到成功，获得 {earned} 积分")
            else:
                detail_items.append("今日已签到")

            total_points = None
            try:
                points_label, total_points = client.query_total_points()
                detail_items.append(f"总积分 {points_label}")
            except ServiceError as exc:
                LOGGER.warning("账号 %d 积分查询失败: %s", index, exc)
                detail_items.append("总积分未知")

            try:
                detail_items.append(
                    f"剩余时间 {client.query_remaining_days()}"
                )
            except ServiceError as exc:
                LOGGER.warning("账号 %d剩余时间查询失败: %s", index, exc)
                detail_items.append("剩余时间未知")

            exchange_failed = False
            if exchange_plan and code == CheckinCode.ALREADY_CHECKED_IN:
                detail_items.append("自动兑换跳过（本次非新签到）")
            elif exchange_plan and total_points is None:
                exchange_failed = True
                detail_items.append("自动兑换失败（无法确认当前积分）")
            elif exchange_plan:
                required_points = EXCHANGE_PLANS[exchange_plan]
                if total_points < required_points:
                    detail_items.append(
                        "自动兑换跳过"
                        f"（积分 {total_points}/{required_points}）"
                    )
                else:
                    try:
                        exchange_ok, exchange_detail = client.exchange_points(
                            exchange_plan
                        )
                        exchange_failed = not exchange_ok
                        detail_items.append(exchange_detail)
                    except ServiceError as exc:
                        exchange_failed = True
                        LOGGER.warning("账号 %d 自动兑换失败: %s", index, exc)
                        detail_items.append("自动兑换异常")

            return AccountResult(
                account_name,
                (
                    ResultStatus.FAILED
                    if exchange_failed
                    else ResultStatus.SUCCESS
                ),
                "，".join(detail_items),
            )
    except (requests.RequestException, ServiceError) as exc:
        LOGGER.error(
            "账号 %d 在 %s 执行失败: %s",
            index,
            domain,
            exc,
            exc_info=True,
        )
        return AccountResult(
            account_name,
            ResultStatus.FAILED,
            f"执行异常: {type(exc).__name__}",
        )


def calculate_global_status(results: list[AccountResult]) -> ResultStatus:
    """根据各账号结果计算全局状态。"""
    success_count = sum(
        result.status == ResultStatus.SUCCESS for result in results
    )
    if success_count == len(results):
        return ResultStatus.SUCCESS
    if success_count == 0:
        return ResultStatus.FAILED
    return ResultStatus.PARTIAL_SUCCESS


def build_payload(results: list[AccountResult]) -> dict[str, Any]:
    """构建仓库统一的通知 Payload。"""
    success_count = sum(
        result.status == ResultStatus.SUCCESS for result in results
    )
    failed_count = len(results) - success_count
    return {
        "title": "GLaDOS 自动签到",
        "status": calculate_global_status(results).value,
        "accounts": [result.as_payload() for result in results],
        "summary": (
            f"共执行 {len(results)} 个账号任务，成功 {success_count} 个，"
            f"失败 {failed_count} 个。"
        ),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def notify_results(results: list[AccountResult]) -> bool:
    """调用全局适配器，并捕获通知入口异常。"""
    try:
        send_payload(build_payload(results))
        return True
    except Exception as exc:
        LOGGER.error("通知调用失败: %s", exc, exc_info=True)
        return False


def run() -> int:
    """加载配置并依次处理全部账号，局部失败不终止任务。"""
    try:
        settings = Settings.from_environment()
    except ConfigurationError as exc:
        results = [
            AccountResult("配置检查", ResultStatus.FAILED, str(exc))
        ]
        notify_results(results)
        return 1

    if not settings.cookies:
        results = [
            AccountResult(
                "配置检查",
                ResultStatus.FAILED,
                f"缺少必填环境变量 {COOKIE_ENV_NAME}",
            )
        ]
        notify_results(results)
        return 1

    tasks = [
        (index, domain, cookie)
        for index, cookie in enumerate(settings.cookies, start=1)
        for domain in settings.domains
    ]
    results = []
    for task_index, (index, domain, cookie) in enumerate(tasks):
        try:
            results.append(
                execute_account(
                    index,
                    domain,
                    cookie,
                    settings.exchange_plan,
                )
            )
        except Exception as exc:
            LOGGER.error(
                "账号 %d 在 %s 出现未预期异常: %s",
                index,
                domain,
                exc,
                exc_info=True,
            )
            results.append(
                AccountResult(
                    f"账号 {index} @ {domain}",
                    ResultStatus.FAILED,
                    f"未预期异常: {type(exc).__name__}",
                )
            )
        if task_index < len(tasks) - 1:
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
