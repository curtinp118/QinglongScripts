# -*- coding: utf-8 -*-
"""将仓库标准 Payload 转换为青龙官方通知模块的调用参数。"""

from collections.abc import Mapping, Sequence
from typing import Any

from notify import send


GLOBAL_STATUS_LINES = {
    "SUCCESS": "🟢 状态: 成功",
    "PARTIAL_SUCCESS": "🟡 状态: 部分成功",
    "FAILED": "🔴 状态: 失败",
}
ACCOUNT_STATUS_LABELS = {
    "SUCCESS": "✅ 成功",
    "FAILED": "❌ 失败",
}
SEPARATOR = "───────────────────"


def _require_text(payload: Mapping[str, Any], field: str) -> str:
    """读取必填文本字段，并拒绝空值。"""
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"通知字段 {field!r} 必须是非空字符串")
    return value.strip()


def _render_account(index: int, account: Mapping[str, Any]) -> str:
    """渲染单个账号的执行结果。"""
    name = _require_text(account, "name")
    status = _require_text(account, "status")
    detail = _require_text(account, "detail")
    status_label = ACCOUNT_STATUS_LABELS.get(status)
    if status_label is None:
        raise ValueError(f"账号状态不受支持: {status}")

    return "\n".join(
        (
            f"👤 账号 {index}: {name}",
            f"├─ 状态: {status_label}",
            f"└─ 详情: {detail}",
        )
    )


def render_payload(payload: Mapping[str, Any]) -> tuple[str, str]:
    """校验标准 Payload，并转换为官方 send 所需的标题和正文。"""
    title = _require_text(payload, "title")
    status = _require_text(payload, "status")
    timestamp = _require_text(payload, "timestamp")
    summary = _require_text(payload, "summary")
    status_line = GLOBAL_STATUS_LINES.get(status)
    if status_line is None:
        raise ValueError(f"全局状态不受支持: {status}")

    accounts = payload.get("accounts")
    if (
        not isinstance(accounts, Sequence)
        or isinstance(accounts, (str, bytes))
        or not accounts
    ):
        raise ValueError("通知字段 'accounts' 必须是非空数组")

    account_sections = []
    for index, account in enumerate(accounts, start=1):
        if not isinstance(account, Mapping):
            raise ValueError("账号执行详情必须是对象")
        account_sections.append(_render_account(index, account))

    content = "\n".join(
        (
            SEPARATOR,
            status_line,
            f"⏰ 时间: {timestamp}",
            SEPARATOR,
            "\n\n".join(account_sections),
            SEPARATOR,
            f"📌 总结: {summary}",
        )
    )
    return f"🔔 {title}", content


def send_payload(payload: Mapping[str, Any]) -> None:
    """通过青龙官方 notify.send(title, content) 发送标准 Payload。"""
    title, content = render_payload(payload)
    send(title, content)
