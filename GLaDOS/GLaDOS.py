# -*- coding: utf-8 -*-
"""
name: GLaDOS 自动签到
description: 多账号探测登录域名、完成 challenge 签到并查询积分与剩余天数
cron: 0 8 * * *
env:
  - GLADOS_COOKIES (必填): 账号 JSON 数组，兼容 Cookie 用 |||、& 或换行分割
  - GLADOS_DOMAINS (选填): 候选 HTTPS 域名，用 ||| 分割，默认探测内置域名
  - GLADOS_EXCHANGE_PLAN (选填): 自动兑换计划，默认关闭
  - GLADOS_USER_AGENT (选填): 登录浏览器完整 User-Agent，默认 Windows Chrome
  - QL_RANDOM_DELAY_ENABLED (选填): 是否启用任务启动随机延迟，默认 true
  - QL_RANDOM_DELAY_MIN_SECONDS (选填): 最小延迟秒数，默认 0
  - QL_RANDOM_DELAY_MAX_SECONDS (选填): 最大延迟秒数，默认 300
  - QL_LOG_LEVEL (选填): 日志级别，默认 INFO，可设 DEBUG/INFO/WARNING/ERROR
version: 1.4.0
updated: 2026-11-15
disclaimer: 仅供学习交流，禁止用于商业用途，风险自负
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from notification_adapter import send_payload  # noqa: E402
from runtime_control import (  # noqa: E402
    RandomDelayConfigurationError,
    configure_logging,
    wait_for_random_delay,
)


LOGGER = logging.getLogger("glados")
COOKIE_ENV_NAME = "GLADOS_COOKIES"
DOMAIN_ENV_NAME = "GLADOS_DOMAINS"
EXCHANGE_ENV_NAME = "GLADOS_EXCHANGE_PLAN"
USER_AGENT_ENV_NAME = "GLADOS_USER_AGENT"
ACCOUNT_SEPARATOR = "|||"
DEFAULT_DOMAINS = (
    "glados.cloud",
    "railgun.info",
    "glados.network",
    "glados.rocks",
    "glados.one",
    "glados.space",
    "glados.vip",
    "glados-facility.com",
)
KNOWN_DOMAINS = frozenset(DEFAULT_DOMAINS)
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
# 与上游网页协议一致：nonce 获取后至少等待 2.5 秒再提交 proof。
CHALLENGE_SUFFIX = "glados-observe-v1"
CHALLENGE_DELAY_SECONDS = 2.5
MAX_LEFT_DAYS = 36_500  # 超过约 100 年的剩余天数视为异常数据。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
PLATFORM_USER_AGENTS = {
    "Windows": DEFAULT_USER_AGENT,
    "macOS": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/156.0.0.0 Safari/537.36"
    ),
    "Linux": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "iPhone": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Android": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
}
PLATFORM_USER_AGENTS["iOS"] = PLATFORM_USER_AGENTS["iPhone"]
AUTH_FAIL_KEYWORDS = (
    "没有权限",
    "权限不足",
    "未登录",
    "登录已失效",
    "unauthorized",
    "forbidden",
    "invalid token",
)
DEVICE_CHECK_KEYWORDS = (
    "automated check-in detected",
    "device-mismatch",
)
SESSION_KEY_PATTERN = re.compile(
    r"^(?P<prefix>[A-Za-z0-9_.-]+):sess(?P<signature>\.sig)?$"
)
COOKIE_FORMAT_HINT = (
    "期望 Cookie 格式（前缀任意，sess 与 sess.sig 必须成对出现）；"
    "请从 GLaDOS 浏览器 Cookie 中复制完整值"
)


class CheckinCode(IntEnum):
    """GLaDOS 签到接口的已知业务状态码。"""

    PERMISSION_DENIED = -2
    SUCCESS = 0
    ALREADY_CHECKED_IN = 1
    DEVICE_REJECTED = 4  # 设备校验失败，reason 区分是否为平台不匹配。


class ResultStatus(str, Enum):
    """仓库标准通知状态。"""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class ConfigurationError(ValueError):
    """环境变量配置不合法。"""


class ServiceError(RuntimeError):
    """GLaDOS 服务请求或响应不合法。"""


class AuthenticationError(ServiceError):
    """服务端明确拒绝当前登录凭证。"""


@dataclass(frozen=True)
class AccountSettings:
    """单账号配置；凭证不进入对象的调试表示。"""

    cookie: str = field(repr=False)
    name: str = ""
    origin: str = ""
    user_agent: str = ""


@dataclass(frozen=True)
class Settings:
    """经过校验的脚本配置。"""

    accounts: tuple[AccountSettings, ...]
    domains: tuple[str, ...]
    exchange_plan: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        """从项目专用环境变量读取配置。"""
        accounts = parse_accounts(os.environ.get(COOKIE_ENV_NAME, ""))

        raw_domains = os.environ.get(
            DOMAIN_ENV_NAME, ACCOUNT_SEPARATOR.join(DEFAULT_DOMAINS)
        )
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
            accounts=accounts,
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


def parse_accounts(raw: str) -> tuple[AccountSettings, ...]:
    """兼容上游账号对象数组和已有的 Cookie 分隔符配置，并去重。"""
    text = raw.lstrip("\ufeff").strip()
    if not text:
        return ()
    entries: list[AccountSettings] = []
    if text.startswith(("[", "{")):
        try:
            items = json.loads(text)
        except ValueError as exc:
            raise ConfigurationError(
                f"{COOKIE_ENV_NAME} 不是合法 JSON 数组"
            ) from exc
        if not isinstance(items, list) or not items:
            raise ConfigurationError(
                f"{COOKIE_ENV_NAME} 必须是非空账号对象数组"
            )
        allowed_fields = {"cookie", "name", "origin", "user-agent"}
        for index, item in enumerate(items, start=1):
            if (
                not isinstance(item, dict)
                or set(item) - allowed_fields
                or any(not isinstance(value, str) for value in item.values())
                or not item.get("cookie", "").strip()
            ):
                raise ConfigurationError(
                    f"第 {index} 项账号格式无效；只支持字符串字段 "
                    "cookie、name、origin、user-agent，且 cookie 必填"
                )
            origin = item.get("origin", "").strip()
            entries.append(
                AccountSettings(
                    cookie=normalize_cookie(item["cookie"]),
                    name=" ".join(item.get("name", "").split()),
                    origin=normalize_domain(origin) if origin else "",
                    user_agent=" ".join(item.get("user-agent", "").split()),
                )
            )
    else:
        entries = [
            AccountSettings(cookie=normalize_cookie(item))
            for item in re.split(r"\|\|\||[&\n]", text)
            if item.strip()
        ]

    unique: list[AccountSettings] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.cookie in seen:
            LOGGER.warning("检测到重复 Cookie，已跳过重复账号")
            continue
        seen.add(entry.cookie)
        unique.append(entry)
    return tuple(unique)


def normalize_cookie(raw_cookie: str) -> str:
    """清理复制 Cookie 时混入的引号、空白和 ``Cookie:`` 头名。

    不改写会话前缀。GLaDOS 当前可能使用 ``gld:``，旧账号仍可能
    使用 ``koa:``，改写前缀会使服务端无法识别会话。
    """
    cookie = (raw_cookie or "").strip()
    while len(cookie) >= 2 and cookie[0] == cookie[-1] and cookie[0] in "\"'":
        cookie = cookie[1:-1].strip()
    if cookie[:7].lower() == "cookie:":
        cookie = cookie[7:].strip()
        while (
            len(cookie) >= 2
            and cookie[0] == cookie[-1]
            and cookie[0] in "\"'"
        ):
            cookie = cookie[1:-1].strip()
    return cookie


def parse_session_prefixes(cookie: str) -> dict[str, dict[str, bool]]:
    """解析任意前缀的 ``<prefix>:sess`` 会话字段。"""
    found: dict[str, dict[str, bool]] = {}
    for part in cookie.split(";"):
        key, separator, value = part.strip().partition("=")
        if not separator or not value.strip():
            continue
        match = SESSION_KEY_PATTERN.fullmatch(key.strip())
        if not match:
            continue
        prefix = match.group("prefix")
        field = "sig" if match.group("signature") else "sess"
        found.setdefault(prefix, {})[field] = True
    return found


def normalize_domain(raw_domain: str) -> str:
    """规范并校验自定义 HTTPS 主机名。"""
    domain = raw_domain.strip().strip("\"'").lower()
    if domain.startswith("http://"):
        raise ConfigurationError("自定义域名必须使用 HTTPS")
    domain = re.sub(r"^https://", "", domain)
    if any(character in domain for character in ("/", "@", ":", "?", "#")):
        raise ConfigurationError("域名格式无效；只允许 HTTPS 纯主机名")
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise ConfigurationError("域名格式无效；只允许 HTTPS 纯主机名")
    return domain


def validate_cookie(cookie: str) -> tuple[bool, str]:
    """校验会话字段是否成对，兼容 GLaDOS 变更过的任意前缀。"""
    cookie = normalize_cookie(cookie)
    if not cookie:
        return False, f"Cookie 为空；{COOKIE_FORMAT_HINT}"
    if any(character in cookie for character in ("\r", "\n", "\0")):
        return False, "Cookie 包含非法控制字符，请重新复制完整请求头"

    groups = parse_session_prefixes(cookie)
    complete = [
        prefix
        for prefix, fields in groups.items()
        if fields.get("sess") and fields.get("sig")
    ]
    if complete:
        return True, ""

    return False, (
        "Cookie 会话字段不成对或缺失；"
        f"{COOKIE_FORMAT_HINT}"
    )


def classify_checkin(
    code: Any,
    message: str,
    *,
    repeated: Any = None,
    checked_in: Any = None,
    reason: Any = None,
) -> CheckinCode | None:
    """按上游网页判定顺序处理拒绝、repeated、code 和 checkedIn。"""
    parsed_code = parse_api_code(code)
    if "please checkin via" in message.lower():
        return None
    if (
        parsed_code == CheckinCode.DEVICE_REJECTED
        and reason == "device-mismatch"
    ):
        return None
    if isinstance(repeated, bool):
        if repeated:
            return CheckinCode.ALREADY_CHECKED_IN
        return (
            CheckinCode.SUCCESS
            if parsed_code == CheckinCode.SUCCESS
            else None
        )
    if parsed_code == CheckinCode.SUCCESS:
        return CheckinCode.SUCCESS
    if parsed_code == CheckinCode.ALREADY_CHECKED_IN:
        return CheckinCode.ALREADY_CHECKED_IN
    if checked_in is True:
        return CheckinCode.ALREADY_CHECKED_IN
    return None


def compact_message(value: Any, fallback: str = "未知错误") -> str:
    """压缩服务消息，避免日志或通知出现超长响应。"""
    message = " ".join(str(value or fallback).split())
    message = re.sub(
        r"([A-Za-z0-9_.-]+:sess(?:\.sig)?\s*=\s*)[^;\s]+",
        r"\1[REDACTED]",
        message,
    )
    message = re.sub(
        r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+=*",
        r"\1[REDACTED]",
        message,
    )
    return message[:MAX_SERVICE_MESSAGE_LENGTH]


def parse_integer(value: Any) -> int | None:
    """防御性解析接口中的整数值。"""
    if isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def parse_api_code(value: Any) -> int | None:
    """业务状态码必须为整数，不能将小数截断成成功状态。"""
    parsed = parse_integer(value)
    if parsed is None:
        return None
    if isinstance(value, str):
        return parsed if re.fullmatch(r"[+-]?\d+", value.strip()) else None
    return parsed if value == parsed else None


def parse_earned_points(message: str) -> int:
    """从中英文签到提示中提取本次积分。"""
    match = re.search(
        r"(?:got\s+|获得\s*)(\d+)\s*(?:points?|点|积分)?",
        message,
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match else 0


def earned_points(payload: dict[str, Any], message: str) -> int:
    """优先读取 points / list[0].change，兼容旧版消息中的积分。"""
    points = parse_integer(payload.get("points"))
    if points is not None:
        return points
    records = payload.get("list")
    if isinstance(records, list) and records and isinstance(records[0], dict):
        change = parse_integer(records[0].get("change"))
        if change is not None:
            return change
    return parse_earned_points(message)


class GLaDOSClient:
    """封装单账号的 GLaDOS API 调用。"""

    def __init__(
        self,
        domain: str,
        cookie: str,
        user_agent: str | None = None,
    ) -> None:
        self.domain = domain
        self.session = requests.Session()
        self.configured_user_agent = (
            user_agent
            or os.environ.get(USER_AGENT_ENV_NAME, "").strip()
        )
        selected_user_agent = (
            " ".join(self.configured_user_agent.split()) or DEFAULT_USER_AGENT
        )
        self.headers = {
            "cookie": cookie,
            "origin": f"https://{domain}",
            "referer": f"https://{domain}/console/checkin",
            "user-agent": selected_user_agent,
            "accept": "application/json, text/plain, */*",
        }

    def __enter__(self) -> "GLaDOSClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.session.close()

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        retryable: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """请求 JSON 接口，对可重试错误、429 和 5xx 有限重试。

        积分兑换是会消耗余额的非幂等 POST，调用方可关闭重试，
        避免首次请求已成功但响应丢失时重复扣分。
        """
        url = f"https://{self.domain}{path}"
        last_error: Exception | None = None

        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=self.headers,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    allow_redirects=False,
                    **kwargs,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise ServiceError(
                        f"服务暂不可用: HTTP {response.status_code}"
                    )
                if 300 <= response.status_code < 400:
                    raise ServiceError("服务返回重定向，请检查登录域名")
                if response.status_code in {401, 403}:
                    raise AuthenticationError("当前域名未登录或拒绝访问")
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
                should_retry = retryable and isinstance(
                    exc, requests.RequestException
                )
                response = getattr(exc, "response", None)
                if (
                    isinstance(exc, requests.HTTPError)
                    and response is not None
                ):
                    status_code = response.status_code
                    should_retry = retryable and (
                        status_code == 429 or status_code >= 500
                    )
                if isinstance(exc, ServiceError):
                    should_retry = retryable and (
                        "HTTP 429" in str(exc)
                        or "HTTP 5" in str(exc)
                        or "非 JSON" in str(exc)
                    )

                if not should_retry or attempt == MAX_REQUEST_ATTEMPTS:
                    break
                wait_seconds = 2 ** (attempt - 1) + random.uniform(0, 0.5)
                LOGGER.warning(
                    "请求失败，第 %d/%d 次，%.1f 秒后重试",
                    attempt,
                    MAX_REQUEST_ATTEMPTS,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        if isinstance(last_error, AuthenticationError):
            raise last_error
        error_name = (
            type(last_error).__name__ if last_error else "UnknownError"
        )
        raise ServiceError(f"请求失败: {error_name}") from last_error

    def _checkin_attempt(self) -> dict[str, Any]:
        """先获取 challenge；不可用时按上游行为回退表单请求。"""
        body = {"token": self.domain}
        try:
            challenge = self._request_json(
                "GET", "/api/user/checkin/challenge"
            )
        except ServiceError:
            challenge = {}
        nonce = challenge.get("nonce")
        has_challenge = (
            parse_api_code(challenge.get("code")) == CheckinCode.SUCCESS
            and isinstance(nonce, str)
            and bool(nonce.strip())
        )
        if has_challenge:
            # 上游协议将 nonce 与固定观察版本号用点连接，作为摘要原文。
            proof_input = f"{nonce}.{CHALLENGE_SUFFIX}"
            # 网页端使用 UTF-8 编码后计算 SHA-256，无需账号私钥或签名密钥。
            proof_bytes = proof_input.encode("utf-8")
            # 服务端接收小写十六进制摘要，和原始 nonce 一起验证。
            proof = hashlib.sha256(proof_bytes).hexdigest()
            # nonce 到手后等待网页规定的观察时间，再提交同一会话的证明。
            time.sleep(CHALLENGE_DELAY_SECONDS)
            body.update({"nonce": nonce, "proof": proof})
            request_body = {"json": body}
        else:
            LOGGER.warning("未取得签到 challenge，按旧协议提交，积分可能降低")
            request_body = {"data": body}
        # nonce 可能只能使用一次；响应丢失时留给下一轮重新获取，禁止重放。
        return self._request_json(
            "POST",
            "/api/user/checkin",
            retryable=False,
            **request_body,
        )

    def checkin(self) -> tuple[CheckinCode | None, str, int]:
        """执行签到；未显式配置 UA 时按服务端登录平台重试一次。"""
        payload = self._checkin_attempt()
        device_mismatch = (
            parse_api_code(payload.get("code")) == CheckinCode.DEVICE_REJECTED
            and payload.get("reason") == "device-mismatch"
        )
        device = payload.get("loginDevice")
        if (
            device_mismatch
            and not self.configured_user_agent
            and isinstance(device, str)
            and device in PLATFORM_USER_AGENTS
        ):
            LOGGER.warning("登录设备平台不匹配，按 %s 平台重新获取 challenge", device)
            self.headers["user-agent"] = PLATFORM_USER_AGENTS[device]
            payload = self._checkin_attempt()

        # 不在日志或推送中回显服务端可能返回的完整 Cookie。
        raw_message = str(payload.get("message") or "未知错误")
        raw_message = raw_message.replace(self.headers["cookie"], "[REDACTED]")
        message = compact_message(raw_message)
        reason = payload.get("reason")
        code = classify_checkin(
            payload.get("code"),
            raw_message,
            repeated=payload.get("repeated"),
            checked_in=payload.get("checkedIn"),
            reason=reason,
        )
        if (
            parse_api_code(payload.get("code")) == CheckinCode.DEVICE_REJECTED
            and reason == "device-mismatch"
        ):
            message = "device-mismatch: 登录设备与 User-Agent 不匹配"
        elif (
            code is None
            and parse_api_code(payload.get("code"))
            == CheckinCode.PERMISSION_DENIED
        ):
            message = "没有权限，请重新获取 Cookie"
        points = (
            earned_points(payload, raw_message)
            if code == CheckinCode.SUCCESS
            else 0
        )
        return code, message, points

    def probe_login(self) -> bool:
        """只读探测登录状态；有响应但未登录时不重试。"""
        try:
            payload = self._request_json(
                "GET", "/api/user/status", retryable=False
            )
        except AuthenticationError:
            return False
        return (
            parse_api_code(payload.get("code")) == CheckinCode.SUCCESS
            and isinstance(payload.get("data"), dict)
        )

    def query_remaining_days(self) -> str:
        """查询会员剩余天数，字段缺失时返回未知。"""
        payload = self._request_json("GET", "/api/user/status")
        data = payload.get("data")
        if not isinstance(data, dict):
            return "未知"
        days = parse_integer(data.get("leftDays"))
        if days is None or abs(days) > MAX_LEFT_DAYS:
            return "未知"
        return f"{days} 天"

    def query_total_points(self) -> tuple[str, int | None]:
        """查询账号总积分，兼容两种常见响应结构。"""
        payload = self._request_json(
            "GET", "/api/user/points", retryable=False
        )
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
            retryable=False,
            data={"planType": plan},
        )
        code = parse_api_code(payload.get("code"))
        if code == CheckinCode.SUCCESS:
            return True, f"自动兑换 {plan} 成功"
        raw_message = str(payload.get("message") or "未知错误")
        message = compact_message(
            raw_message.replace(self.headers["cookie"], "[REDACTED]")
        )
        return False, f"自动兑换 {plan} 失败: {message}"


def execute_account(
    index: int,
    domain: str,
    cookie: str,
    exchange_plan: str | None,
    *,
    name: str = "",
    user_agent: str = "",
) -> AccountResult:
    """执行单账号任务；查询附加信息失败不会覆盖签到结果。"""
    account_name = f"{name or f'账号 {index}'} @ {domain}"
    valid, reason = validate_cookie(cookie)
    if not valid:
        return AccountResult(account_name, ResultStatus.FAILED, reason)

    LOGGER.info("开始处理账号 %d，域名 %s", index, domain)
    try:
        with GLaDOSClient(domain, cookie, user_agent=user_agent) as client:
            code, message, earned = client.checkin()
            if code not in {
                CheckinCode.SUCCESS,
                CheckinCode.ALREADY_CHECKED_IN,
            }:
                message_lower = message.lower()
                if any(
                    keyword in message_lower
                    for keyword in DEVICE_CHECK_KEYWORDS
                ):
                    failure_detail = (
                        "设备校验失败: 请设置与登录浏览器一致的 "
                        f"{USER_AGENT_ENV_NAME}"
                    )
                elif any(
                    keyword in message_lower
                    for keyword in AUTH_FAIL_KEYWORDS
                ):
                    failure_detail = (
                        f"鉴权失败: {message}，请重新获取 Cookie"
                    )
                elif "please checkin via" in message_lower:
                    failure_detail = "签到域名被拒，请确认 Cookie 来源域名"
                else:
                    failure_detail = f"签到失败: {message}"
                return AccountResult(
                    account_name,
                    ResultStatus.FAILED,
                    failure_detail,
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
                LOGGER.warning(
                    "账号 %d 积分查询失败: %s",
                    index,
                    type(exc).__name__,
                )
                detail_items.append("总积分未知")

            try:
                detail_items.append(
                    f"剩余时间 {client.query_remaining_days()}"
                )
            except ServiceError as exc:
                LOGGER.warning(
                    "账号 %d 剩余时间查询失败: %s",
                    index,
                    type(exc).__name__,
                )
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
                        LOGGER.warning(
                            "账号 %d 自动兑换失败: %s",
                            index,
                            type(exc).__name__,
                        )
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
            type(exc).__name__,
        )
        return AccountResult(
            account_name,
            ResultStatus.FAILED,
            f"执行异常: {type(exc).__name__}",
        )


def execute_configured_account(
    index: int,
    account: AccountSettings,
    settings: Settings,
) -> AccountResult:
    """每个账号仅在首个命中登录状态的候选域名签到一次。"""
    account_name = account.name or f"账号 {index}"
    valid, reason = validate_cookie(account.cookie)
    if not valid:
        return AccountResult(account_name, ResultStatus.FAILED, reason)
    domains = tuple(
        dict.fromkeys(
            ((account.origin,) if account.origin else ()) + settings.domains
        )
    )
    network_failures = 0
    for domain in domains:
        try:
            with GLaDOSClient(
                domain, account.cookie, account.user_agent
            ) as client:
                logged_in = client.probe_login()
        except ServiceError:
            network_failures += 1
            LOGGER.warning("账号 %d 在 %s 的登录探测请求失败", index, domain)
            continue
        if logged_in:
            LOGGER.info("账号 %d 命中登录域名 %s", index, domain)
            return execute_account(
                index,
                domain,
                account.cookie,
                settings.exchange_plan,
                name=account.name,
                user_agent=account.user_agent,
            )
    detail = (
        "候选域名存在网络或响应异常，未能确认登录状态，请稍后重试"
        if network_failures
        else "候选域名均未登录，请确认 Cookie 来源域名或重新获取 Cookie"
    )
    return AccountResult(account_name, ResultStatus.FAILED, detail)


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
        LOGGER.error(
            "通知调用失败: %s",
            type(exc).__name__,
            exc_info=LOGGER.isEnabledFor(logging.DEBUG),
        )
        return False


def run() -> int:
    """加载配置并依次处理全部账号，局部失败不终止任务。"""
    try:
        settings = Settings.from_environment()
    except ConfigurationError as exc:
        LOGGER.error("配置检查失败: %s", str(exc))
        results = [
            AccountResult("配置检查", ResultStatus.FAILED, str(exc))
        ]
        notify_results(results)
        return 1

    if not settings.accounts:
        LOGGER.error("配置检查失败: 缺少环境变量 %s", COOKIE_ENV_NAME)
        results = [
            AccountResult(
                "配置检查",
                ResultStatus.FAILED,
                f"缺少必填环境变量 {COOKIE_ENV_NAME}",
            )
        ]
        notify_results(results)
        return 1

    try:
        wait_for_random_delay(LOGGER)
    except RandomDelayConfigurationError as exc:
        LOGGER.error("随机延迟配置失败: %s", str(exc))
        results = [AccountResult("随机延迟配置", ResultStatus.FAILED, str(exc))]
        notify_results(results)
        return 1

    results = []
    for index, account in enumerate(settings.accounts, start=1):
        try:
            result = execute_configured_account(index, account, settings)
            results.append(result)
            LOGGER.info(
                "%s 处理完成，状态=%s",
                result.name,
                result.status.value,
            )
        except Exception as exc:
            LOGGER.error(
                "账号 %d 出现未预期异常: %s",
                index,
                type(exc).__name__,
            )
            results.append(
                AccountResult(
                    account.name or f"账号 {index}",
                    ResultStatus.FAILED,
                    f"未预期异常: {type(exc).__name__}",
                )
            )
        if index < len(settings.accounts):
            time.sleep(random.uniform(*ACCOUNT_DELAY_RANGE_SECONDS))

    success_count = sum(
        result.status == ResultStatus.SUCCESS for result in results
    )
    LOGGER.info(
        "任务完成，账号任务=%d，成功=%d，失败=%d",
        len(results),
        success_count,
        len(results) - success_count,
    )
    notification_ok = notify_results(results)
    all_succeeded = calculate_global_status(results) == ResultStatus.SUCCESS
    return 0 if all_succeeded and notification_ok else 1


def main() -> int:
    """配置日志并运行青龙入口。"""
    configure_logging(LOGGER)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
