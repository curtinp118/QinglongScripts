# -*- coding: utf-8 -*-
"""提供青龙入口脚本共用的运行时控制能力。"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass

RANDOM_DELAY_ENABLED_ENV_NAME = "QL_RANDOM_DELAY_ENABLED"
RANDOM_DELAY_MIN_ENV_NAME = "QL_RANDOM_DELAY_MIN_SECONDS"
RANDOM_DELAY_MAX_ENV_NAME = "QL_RANDOM_DELAY_MAX_SECONDS"
LOG_LEVEL_ENV_NAME = "QL_LOG_LEVEL"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_RANDOM_DELAY_ENABLED = True
DEFAULT_RANDOM_DELAY_MIN_SECONDS = 0
DEFAULT_RANDOM_DELAY_MAX_SECONDS = 300
MAX_RANDOM_DELAY_SECONDS = 86_400
TRUE_VALUES = frozenset({"1", "true", "yes", "on", "enable", "enabled"})
FALSE_VALUES = frozenset({"0", "false", "no", "off", "disable", "disabled"})
SUPPORTED_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class RandomDelayConfigurationError(ValueError):
    """随机延迟环境变量配置不合法。"""


def configure_logging(logger: logging.Logger) -> None:
    """按全局环境变量初始化统一日志格式和级别。"""
    raw_level = os.environ.get(LOG_LEVEL_ENV_NAME, DEFAULT_LOG_LEVEL)
    level_name = raw_level.strip().upper() or DEFAULT_LOG_LEVEL
    if level_name not in SUPPORTED_LOG_LEVELS:
        level_name = DEFAULT_LOG_LEVEL

    logging.basicConfig(
        level=getattr(logging, level_name),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.setLevel(getattr(logging, level_name))
    if raw_level.strip() and raw_level.strip().upper() not in SUPPORTED_LOG_LEVELS:
        logger.warning(
            "%s=%s 无效，已使用默认级别 %s",
            LOG_LEVEL_ENV_NAME,
            raw_level.strip(),
            DEFAULT_LOG_LEVEL,
        )


@dataclass(frozen=True)
class RandomDelaySettings:
    """经过校验的任务启动随机延迟配置。"""

    enabled: bool = DEFAULT_RANDOM_DELAY_ENABLED
    minimum_seconds: int = DEFAULT_RANDOM_DELAY_MIN_SECONDS
    maximum_seconds: int = DEFAULT_RANDOM_DELAY_MAX_SECONDS

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "RandomDelaySettings":
        """读取全局环境变量，未设置的字段使用默认值。"""
        source = os.environ if environ is None else environ
        enabled = _parse_enabled(source.get(RANDOM_DELAY_ENABLED_ENV_NAME))
        minimum = _parse_seconds(
            source.get(RANDOM_DELAY_MIN_ENV_NAME),
            RANDOM_DELAY_MIN_ENV_NAME,
            DEFAULT_RANDOM_DELAY_MIN_SECONDS,
        )
        maximum = _parse_seconds(
            source.get(RANDOM_DELAY_MAX_ENV_NAME),
            RANDOM_DELAY_MAX_ENV_NAME,
            DEFAULT_RANDOM_DELAY_MAX_SECONDS,
        )
        if minimum > maximum:
            raise RandomDelayConfigurationError(
                f"{RANDOM_DELAY_MIN_ENV_NAME} 不能大于 {RANDOM_DELAY_MAX_ENV_NAME}"
            )
        return cls(enabled, minimum, maximum)


def _parse_enabled(raw_value: str | None) -> bool:
    """解析随机延迟开关，空值使用默认设置。"""
    if raw_value is None or not raw_value.strip():
        return DEFAULT_RANDOM_DELAY_ENABLED
    normalized = raw_value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise RandomDelayConfigurationError(
        f"{RANDOM_DELAY_ENABLED_ENV_NAME} 仅支持 true/false、1/0、yes/no 或 on/off"
    )


def _parse_seconds(
    raw_value: str | None,
    variable_name: str,
    default_value: int,
) -> int:
    """解析非负整数秒数，并限制单次最长延迟为一天。"""
    if raw_value is None or not raw_value.strip():
        return default_value
    try:
        value = int(raw_value.strip())
    except ValueError as exc:
        raise RandomDelayConfigurationError(f"{variable_name} 必须是整数秒数") from exc
    if not 0 <= value <= MAX_RANDOM_DELAY_SECONDS:
        raise RandomDelayConfigurationError(
            f"{variable_name} 必须在 0 到 {MAX_RANDOM_DELAY_SECONDS} 之间"
        )
    return value


def wait_for_random_delay(logger: logging.Logger) -> int:
    """按全局配置在业务执行前随机等待，并返回实际秒数。"""
    settings = RandomDelaySettings.from_environment()
    if not settings.enabled:
        logger.info("任务启动随机延迟已关闭")
        return 0

    delay_seconds = random.randint(
        settings.minimum_seconds,
        settings.maximum_seconds,
    )
    logger.info(
        "任务将在 %d 秒后开始执行（配置范围 %d-%d 秒）",
        delay_seconds,
        settings.minimum_seconds,
        settings.maximum_seconds,
    )
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    return delay_seconds
