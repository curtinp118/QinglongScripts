# -*- coding: utf-8 -*-
"""公共运行控制模块测试。"""

import logging
import os
import unittest
from unittest.mock import patch

from runtime_control import (
    RandomDelayConfigurationError,
    RandomDelaySettings,
    wait_for_random_delay,
)


class RandomDelaySettingsTest(unittest.TestCase):
    """验证环境变量默认值与边界校验。"""

    def test_defaults_are_used_when_environment_is_empty(self) -> None:
        settings = RandomDelaySettings.from_environment({})

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.minimum_seconds, 0)
        self.assertEqual(settings.maximum_seconds, 300)

    def test_environment_can_disable_and_override_range(self) -> None:
        settings = RandomDelaySettings.from_environment(
            {
                "QL_RANDOM_DELAY_ENABLED": "off",
                "QL_RANDOM_DELAY_MIN_SECONDS": "15",
                "QL_RANDOM_DELAY_MAX_SECONDS": "45",
            }
        )

        self.assertFalse(settings.enabled)
        self.assertEqual(settings.minimum_seconds, 15)
        self.assertEqual(settings.maximum_seconds, 45)

    def test_invalid_boolean_is_rejected(self) -> None:
        with self.assertRaises(RandomDelayConfigurationError):
            RandomDelaySettings.from_environment(
                {"QL_RANDOM_DELAY_ENABLED": "sometimes"}
            )

    def test_inverted_range_is_rejected(self) -> None:
        with self.assertRaises(RandomDelayConfigurationError):
            RandomDelaySettings.from_environment(
                {
                    "QL_RANDOM_DELAY_MIN_SECONDS": "20",
                    "QL_RANDOM_DELAY_MAX_SECONDS": "10",
                }
            )


class WaitForRandomDelayTest(unittest.TestCase):
    """验证等待执行和关闭开关行为。"""

    @patch("runtime_control.time.sleep")
    @patch("runtime_control.random.randint", return_value=12)
    def test_waits_for_selected_delay(self, randint_mock, sleep_mock) -> None:
        environ = {
            "QL_RANDOM_DELAY_ENABLED": "true",
            "QL_RANDOM_DELAY_MIN_SECONDS": "10",
            "QL_RANDOM_DELAY_MAX_SECONDS": "20",
        }
        with patch.dict(os.environ, environ, clear=True):
            delay = wait_for_random_delay(logging.getLogger("test"))

        self.assertEqual(delay, 12)
        randint_mock.assert_called_once_with(10, 20)
        sleep_mock.assert_called_once_with(12)

    @patch("runtime_control.time.sleep")
    @patch("runtime_control.random.randint")
    def test_disabled_delay_does_not_draw_or_sleep(
        self,
        randint_mock,
        sleep_mock,
    ) -> None:
        with patch.dict(
            os.environ,
            {"QL_RANDOM_DELAY_ENABLED": "false"},
            clear=True,
        ):
            delay = wait_for_random_delay(logging.getLogger("test"))

        self.assertEqual(delay, 0)
        randint_mock.assert_not_called()
        sleep_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
