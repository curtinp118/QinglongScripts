# -*- coding: utf-8 -*-
"""GLaDOS 新版协议与多账号流程的离线回归测试。"""

import hashlib
import json
import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import requests

from GLaDOS import GLaDOS as gl
from notification_adapter import render_payload


# 仅用于本地模拟协议，不是可登录的会话。
COOKIE = "gld:sess=sample-session; gld:sess.sig=sample-signature"


def response(payload: Any, status: int = 200) -> MagicMock:
    """构造 requests 响应替身，不触发真实网络请求。"""
    result = MagicMock(status_code=status)
    result.json.return_value = payload
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(
            response=result
        )
    return result


class ConfigurationTest(unittest.TestCase):
    """验证新旧配置兼容、去重与凭证保护。"""

    def test_json_accounts_and_global_defaults(self) -> None:
        raw = json.dumps(
            [
                {
                    "name": "主号",
                    "cookie": COOKIE,
                    "origin": "https://railgun.info",
                    "user-agent": "custom browser",
                }
            ]
        )
        with patch.dict(os.environ, {gl.COOKIE_ENV_NAME: raw}, clear=True):
            settings = gl.Settings.from_environment()
        account = settings.accounts[0]
        self.assertEqual(account.origin, "railgun.info")
        self.assertEqual(account.name, "主号")
        self.assertEqual(account.user_agent, "custom browser")
        self.assertEqual(settings.domains, gl.DEFAULT_DOMAINS)
        self.assertIsNone(settings.exchange_plan)
        self.assertNotIn(COOKIE, repr(settings))

    def test_legacy_separators_and_duplicate_accounts(self) -> None:
        other_cookie = COOKIE.replace("gld:", "koa:")
        for separator in ("|||", "&", "\n"):
            with self.subTest(separator=separator):
                accounts = gl.parse_accounts(
                    separator.join((COOKIE, other_cookie, COOKIE))
                )
                self.assertEqual(len(accounts), 2)
                self.assertEqual(accounts[1].cookie, other_cookie)

    def test_bad_json_and_fields_never_echo_credentials(self) -> None:
        inputs = (
            '[{"cookie":"' + COOKIE,
            json.dumps({"cookie": COOKIE}),
            json.dumps([COOKIE]),
            json.dumps([{"cookie": COOKIE, COOKIE: "unknown field"}]),
            json.dumps([{"cookie": []}]),
            "[]",
        )
        for raw in inputs:
            with self.subTest(raw=raw):
                with self.assertRaises(gl.ConfigurationError) as caught:
                    gl.parse_accounts(raw)
                self.assertNotIn(COOKIE, str(caught.exception))

    def test_cookie_normalization_and_pair_validation(self) -> None:
        self.assertEqual(gl.normalize_cookie(f'Cookie: "{COOKIE}"'), COOKIE)
        for prefix in ("gld", "koa", "custom"):
            cookie = COOKIE.replace("gld", prefix)
            self.assertEqual(gl.validate_cookie(cookie), (True, ""))
        for cookie in (
            "gld:sess=value", COOKIE + "\rmalformed",
            "gld:sess=; gld:sess.sig=", "gld:sess; gld:sess.sig",
        ):
            self.assertFalse(gl.validate_cookie(cookie)[0])

    def test_explicit_domain_list_is_respected(self) -> None:
        with patch.dict(
            os.environ,
            {gl.DOMAIN_ENV_NAME: "railgun.info|||glados.cloud|||railgun.info"},
            clear=True,
        ):
            self.assertEqual(
                gl.Settings.from_environment().domains,
                ("railgun.info", "glados.cloud"),
            )
        for domain in ("http://glados.cloud", "glados.cloud/path"):
            with self.assertRaises(gl.ConfigurationError):
                gl.normalize_domain(domain)


class CheckinClassificationTest(unittest.TestCase):
    """用上游网页判定规则覆盖旧实现中的误判场景。"""

    def test_web_response_precedence(self) -> None:
        success = gl.CheckinCode.SUCCESS
        repeat = gl.CheckinCode.ALREADY_CHECKED_IN
        cases = [
            ({"code": 0}, success),
            ({"code": "1"}, repeat),
            ({"code": 0, "repeated": True}, repeat),
            ({"code": 0, "repeated": False}, success),
            ({"code": 1, "repeated": False}, None),
            ({"code": -2, "checked_in": True}, repeat),
            ({"code": -2, "checked_in": True, "repeated": False}, None),
            (
                {
                    "code": 0,
                    "message": "please checkin via https://railgun.info",
                },
                None,
            ),
            ({"code": 4, "repeated": True, "reason": "device-mismatch"}, None),
            ({"code": None, "message": "got 20 points"}, None),
            ({"code": -2, "message": "already rejected"}, None),
            ({"code": False}, None),
            ({"code": 0.5}, None),
            ({"code": "0.5"}, None),
        ]
        for case, expected in cases:
            with self.subTest(case=case):
                arguments = {"message": "签到结果", **case}
                self.assertEqual(gl.classify_checkin(**arguments), expected)

    def test_points_prefer_structured_fields(self) -> None:
        self.assertEqual(gl.earned_points({"points": "20"}, "got 1 point"), 20)
        self.assertEqual(
            gl.earned_points({"list": [{"change": "15"}]}, "签到成功"), 15
        )
        self.assertEqual(gl.earned_points({}, "获得 8 积分"), 8)
        for value in (None, True, False, "NaN", "inf", "-inf", {}, []):
            with self.subTest(value=value):
                self.assertIsNone(gl.parse_integer(value))


class ClientProtocolTest(unittest.TestCase):
    """在 HTTP 边界验证请求体、会话、重试与设备切换。"""

    def setUp(self) -> None:
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = gl.GLaDOSClient("glados.cloud", COOKIE)
        self.addCleanup(self.client.session.close)
        self.request = MagicMock()
        self.client.session.request = self.request
        self.sleep = patch.object(gl.time, "sleep").start()
        self.addCleanup(patch.stopall)

    def test_challenge_and_checkin_use_same_session_and_json(self) -> None:
        self.request.side_effect = [
            response({"code": 0, "nonce": "sample-nonce"}),
            response({"code": 0, "points": 20, "repeated": False}),
        ]
        self.assertEqual(
            self.client.checkin(), (gl.CheckinCode.SUCCESS, "未知错误", 20)
        )
        first, second = self.request.call_args_list
        self.assertEqual(first.args, (
            "GET", "https://glados.cloud/api/user/checkin/challenge"
        ))
        self.assertEqual(second.kwargs["json"], {
            "token": "glados.cloud",
            "nonce": "sample-nonce",
            "proof": hashlib.sha256(
                b"sample-nonce.glados-observe-v1"
            ).hexdigest(),
        })
        self.sleep.assert_called_once_with(2.5)
        for call in (first, second):
            self.assertEqual(call.kwargs["timeout"], 10)
            self.assertEqual(call.kwargs["headers"]["cookie"], COOKIE)
            self.assertFalse(call.kwargs["allow_redirects"])

    def test_unavailable_challenge_uses_legacy_form(self) -> None:
        for challenge in (
            response({"code": -2}),
            response({"code": 0}),
            response({"code": 0, "nonce": []}),
            response([]),
            response({}, 404),
        ):
            with self.subTest(challenge=challenge):
                self.request.reset_mock()
                self.request.side_effect = [
                    challenge, response({"code": 0, "points": 1})
                ]
                self.client.checkin()
                self.assertEqual(
                    self.request.call_args.kwargs["data"],
                    {"token": "glados.cloud"},
                )
                self.assertNotIn("json", self.request.call_args.kwargs)
        self.sleep.assert_not_called()

    def test_challenge_json_error_recovers_after_bounded_retries(self) -> None:
        malformed = response(None)
        malformed.json.side_effect = ValueError("invalid JSON")
        self.request.side_effect = [
            malformed, malformed, malformed, response({"code": 1})
        ]
        self.assertEqual(
            self.client.checkin()[0], gl.CheckinCode.ALREADY_CHECKED_IN
        )
        self.assertEqual(self.request.call_count, 4)
        self.assertIn("data", self.request.call_args.kwargs)

    def test_consumed_nonce_is_never_replayed(self) -> None:
        for error in (
            requests.Timeout("response lost"),
            response({}, 503),
        ):
            with self.subTest(error=error):
                self.request.reset_mock()
                self.request.side_effect = [
                    response({"code": 0, "nonce": "sample-nonce"}), error
                ]
                with self.assertRaises(gl.ServiceError):
                    self.client.checkin()
                self.assertEqual(self.request.call_count, 2)

    def test_device_retry_gets_new_challenge(self) -> None:
        headers: list[dict[str, str]] = []
        replies = iter([
            response({"code": 0, "nonce": "first-nonce"}),
            response({
                "code": 4, "reason": "device-mismatch", "loginDevice": "macOS"
            }),
            response({"code": 0, "nonce": "second-nonce"}),
            response({"code": 0, "points": 20}),
        ])

        def request(*args: Any, **kwargs: Any) -> MagicMock:
            headers.append(dict(kwargs["headers"]))
            return next(replies)

        self.request.side_effect = request
        self.assertEqual(self.client.checkin()[0], gl.CheckinCode.SUCCESS)
        self.assertEqual(headers[0]["user-agent"], gl.DEFAULT_USER_AGENT)
        self.assertEqual(
            headers[2]["user-agent"], gl.PLATFORM_USER_AGENTS["macOS"]
        )
        self.assertEqual(
            self.request.call_args_list[3].kwargs["json"]["nonce"],
            "second-nonce",
        )

    def test_explicit_user_agent_is_never_overridden(self) -> None:
        for source in ("account", "global"):
            with self.subTest(source=source):
                with patch.dict(
                    os.environ,
                    {gl.USER_AGENT_ENV_NAME: "global browser"},
                    clear=True,
                ):
                    with gl.GLaDOSClient(
                        "glados.cloud", COOKIE,
                        "account browser" if source == "account" else "",
                    ) as client:
                        client._checkin_attempt = MagicMock(return_value={
                            "code": 4, "reason": "device-mismatch",
                            "loginDevice": "macOS",
                        })
                        code, message, _ = client.checkin()
                        self.assertIsNone(code)
                        self.assertIn("device-mismatch", message)
                        client._checkin_attempt.assert_called_once()
                        self.assertEqual(
                            client.headers["user-agent"], f"{source} browser"
                        )

    def test_repeated_checkin_never_reports_historical_points(self) -> None:
        with patch.object(
            self.client, "_checkin_attempt",
            return_value={"code": 0, "repeated": True, "points": 20},
        ):
            code, _, points = self.client.checkin()
        self.assertEqual(code, gl.CheckinCode.ALREADY_CHECKED_IN)
        self.assertEqual(points, 0)

    def test_exchange_is_form_and_never_retried(self) -> None:
        self.request.return_value = response({"code": 0})
        self.assertTrue(self.client.exchange_points("plan100")[0])
        self.assertEqual(
            self.request.call_args.kwargs["data"], {"planType": "plan100"}
        )
        self.request.reset_mock()
        self.request.side_effect = requests.Timeout("response lost")
        with self.assertRaises(gl.ServiceError):
            self.client.exchange_points("plan100")
        self.request.assert_called_once()

    def test_read_retry_and_authorization_rejection(self) -> None:
        self.request.side_effect = [
            response({}, 503), response({"data": {"leftDays": "12.8"}})
        ]
        self.assertEqual(self.client.query_remaining_days(), "12 天")
        self.request.reset_mock()
        self.request.side_effect = [response({}, 401)]
        self.assertFalse(self.client.probe_login())
        self.request.assert_called_once()

    def test_redirect_never_forwards_credentials(self) -> None:
        self.request.return_value = response({}, 302)
        with self.assertRaises(gl.ServiceError):
            self.client._request_json("GET", "/api/user/status")
        self.request.assert_called_once()

    def test_service_message_is_redacted(self) -> None:
        with patch.object(
            self.client, "_checkin_attempt",
            return_value={"code": -3, "message": f"invalid {COOKIE}"},
        ):
            _, message, _ = self.client.checkin()
        self.assertNotIn("sample-session", message)
        self.assertNotIn("sample-signature", message)


class AccountFlowTest(unittest.TestCase):
    """验证域名选择、附加查询降级、幂等兑换和最终统一通知。"""

    @patch.object(gl, "send_payload")
    @patch.object(gl, "wait_for_random_delay")
    @patch.object(gl.time, "sleep")
    @patch.object(gl.requests, "Session")
    def test_complete_multi_account_protocol(
        self, session_factory: MagicMock, sleep: MagicMock,
        delay: MagicMock, send: MagicMock,
    ) -> None:
        sessions: list[MagicMock] = []
        exchanges: list[str] = []
        checkins: list[str] = []
        other_cookie = COOKIE.replace("gld:", "koa:")
        accounts = [
            {"name": "主号", "cookie": COOKIE, "origin": "glados.cloud"},
            {
                "name": "小号", "cookie": other_cookie,
                "origin": "railgun.info", "user-agent": "custom browser",
            },
        ]

        def new_session() -> MagicMock:
            session = MagicMock()
            nonce = f"session-nonce-{len(sessions)}"
            challenged = False

            def request(
                method: str, url: str, **kwargs: Any,
            ) -> MagicMock:
                nonlocal challenged
                cookie = kwargs["headers"]["cookie"]
                if url.endswith("/status"):
                    return response({"code": 0, "data": {"leftDays": "12.5"}})
                if url.endswith("/challenge"):
                    challenged = True
                    return response({"code": 0, "nonce": nonce})
                if url.endswith("/checkin"):
                    self.assertTrue(challenged)
                    self.assertEqual(kwargs["json"]["nonce"], nonce)
                    self.assertEqual(kwargs["json"]["proof"], hashlib.sha256(
                        f"{nonce}.glados-observe-v1".encode()
                    ).hexdigest())
                    if cookie == other_cookie:
                        self.assertIn("railgun.info", url)
                        self.assertEqual(
                            kwargs["headers"]["user-agent"], "custom browser"
                        )
                    checkins.append(cookie)
                    return response({
                        "code": 0, "points": 20,
                        "repeated": cookie == other_cookie,
                    })
                if url.endswith("/points"):
                    return response({"code": 0, "points": 500})
                if url.endswith("/exchange"):
                    self.assertEqual(kwargs["data"], {"planType": "plan100"})
                    exchanges.append(cookie)
                    return response({"code": 0})
                self.fail(f"出现未预期请求: {method} {url}")

            session.request.side_effect = request
            sessions.append(session)
            return session

        session_factory.side_effect = new_session
        with patch.dict(os.environ, {
            gl.COOKIE_ENV_NAME: json.dumps(accounts),
            gl.EXCHANGE_ENV_NAME: "plan100",
        }, clear=True):
            self.assertEqual(gl.run(), 0)
        self.assertEqual(checkins, [COOKIE, other_cookie])
        self.assertEqual(exchanges, [COOKIE])
        payload = send.call_args.args[0]
        self.assertEqual(payload["status"], "SUCCESS")
        self.assertIn("获得 20 积分", payload["accounts"][0]["detail"])
        self.assertIn("今日已签到", payload["accounts"][1]["detail"])
        self.assertIn("自动兑换跳过", payload["accounts"][1]["detail"])
        self.assertEqual(len(payload["accounts"]), 2)
        for session in sessions:
            session.close.assert_called_once()

    @patch.object(gl, "execute_account")
    @patch.object(gl.GLaDOSClient, "probe_login")
    def test_origin_first_and_stop_after_first_login(
        self, probe: MagicMock, execute: MagicMock,
    ) -> None:
        account = gl.AccountSettings(COOKIE, name="主号", origin="railgun.info")
        settings = gl.Settings((account,), gl.DEFAULT_DOMAINS, None)
        probe.side_effect = [False, True]
        gl.execute_configured_account(1, account, settings)
        self.assertEqual(probe.call_count, 2)
        execute.assert_called_once_with(
            1, "glados.cloud", COOKIE, None, name="主号", user_agent=""
        )

    @patch.object(gl.GLaDOSClient, "probe_login")
    def test_network_failure_does_not_abort_domain_fallback(
        self, probe: MagicMock,
    ) -> None:
        account = gl.AccountSettings(COOKIE)
        settings = gl.Settings(
            (account,), ("glados.cloud", "railgun.info"), None
        )
        probe.side_effect = [gl.ServiceError("network"), False]
        result = gl.execute_configured_account(1, account, settings)
        self.assertEqual(result.status, gl.ResultStatus.FAILED)
        self.assertIn("网络或响应异常", result.detail)

    @patch.object(gl, "GLaDOSClient")
    def test_auxiliary_query_failure_keeps_checkin_success(
        self, client_class: MagicMock,
    ) -> None:
        client = client_class.return_value.__enter__.return_value
        client.checkin.return_value = (gl.CheckinCode.SUCCESS, "ok", 20)
        client.query_total_points.side_effect = gl.ServiceError("network")
        client.query_remaining_days.side_effect = gl.ServiceError("network")
        result = gl.execute_account(1, "glados.cloud", COOKIE, None)
        self.assertEqual(result.status, gl.ResultStatus.SUCCESS)
        self.assertIn("获得 20 积分", result.detail)
        self.assertIn("总积分未知", result.detail)
        self.assertIn("剩余时间未知", result.detail)

    @patch.object(gl, "GLaDOSClient")
    def test_exchange_only_after_new_checkin_with_sufficient_balance(
        self, client_class: MagicMock,
    ) -> None:
        client = client_class.return_value.__enter__.return_value
        client.query_remaining_days.return_value = "20 天"
        client.exchange_points.return_value = (True, "兑换成功")
        for code, balance, expected in (
            (gl.CheckinCode.ALREADY_CHECKED_IN, 500, False),
            (gl.CheckinCode.SUCCESS, 99, False),
            (gl.CheckinCode.SUCCESS, 100, True),
        ):
            with self.subTest(code=code, balance=balance):
                client.exchange_points.reset_mock()
                client.checkin.return_value = (code, "ok", 20)
                client.query_total_points.return_value = (
                    str(balance), balance
                )
                gl.execute_account(1, "glados.cloud", COOKIE, "plan100")
                self.assertEqual(client.exchange_points.called, expected)

    @patch.object(gl, "send_payload")
    @patch.object(gl, "wait_for_random_delay")
    @patch.object(gl.time, "sleep")
    @patch.object(gl, "execute_configured_account")
    def test_account_exception_preserves_following_account_and_notification(
        self, execute: MagicMock, sleep: MagicMock,
        delay: MagicMock, send: MagicMock,
    ) -> None:
        execute.side_effect = [
            RuntimeError("unexpected"),
            gl.AccountResult("账号 2", gl.ResultStatus.SUCCESS, "今日已签到"),
        ]
        other_cookie = COOKIE.replace("gld:", "koa:")
        with patch.dict(
            os.environ,
            {gl.COOKIE_ENV_NAME: f"{COOKIE}|||{other_cookie}"},
            clear=True,
        ):
            self.assertEqual(gl.run(), 1)
        self.assertEqual(execute.call_count, 2)
        payload = send.call_args.args[0]
        self.assertEqual(payload["status"], "PARTIAL_SUCCESS")
        self.assertEqual(len(payload["accounts"]), 2)
        title, content = render_payload(payload)
        self.assertIn("GLaDOS 自动签到", title)
        self.assertIn("今日已签到", content)
        self.assertNotIn(COOKIE, content)


if __name__ == "__main__":
    unittest.main()
