from __future__ import annotations

import logging
from typing import Any

import pytest
import requests

from solar_bridge.config import BridgeConfig
from solar_bridge.solarman import SolarmanClient


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: dict[str, Any] | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self._json_error = json_error

    def json(self) -> dict[str, Any]:
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.calls.append(
            {"url": url, "headers": headers or {}, "json": json or {}, "timeout": timeout}
        )
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _make_config(token_refresh_hours: float = 12.0) -> BridgeConfig:
    return BridgeConfig(
        sinric_app_key="11111111-2222-3333-4444-555555555555",
        sinric_app_secret="s" * 32,
        sinric_device_id="0123456789abcdef01234567",
        solarman_app_id="app-id-123",
        solarman_app_secret="TOP_SECRET_SOLARMAN_APP_SECRET",
        solarman_email="owner@example.com",
        solarman_password_hash="TOP_SECRET_PASSWORD_HASH_0123456789",
        inverter_sn="INV-998877",
        token_refresh_hours=token_refresh_hours,
    )


def test_get_battery_soc_authenticates_and_returns_soc() -> None:
    session = FakeSession(
        [
            FakeResponse(200, {"success": True, "access_token": "tok-1"}),
            FakeResponse(
                200,
                {
                    "success": True,
                    "dataList": [
                        {"key": "OTHER_METRIC", "value": "10"},
                        {"key": "B_left_cap1", "value": "85.5"},
                    ],
                },
            ),
        ]
    )
    client = SolarmanClient(_make_config(), session=session, clock=lambda: 1000.0)

    soc = client.get_battery_soc()

    assert soc == 85.5
    assert len(session.calls) == 2
    assert "/account/v1.0/token" in session.calls[0]["url"]
    assert session.calls[0]["json"]["password"] == "TOP_SECRET_PASSWORD_HASH_0123456789"
    assert session.calls[1]["headers"]["Authorization"] == "bearer tok-1"
    assert session.calls[1]["json"]["deviceSn"] == "INV-998877"


@pytest.mark.parametrize("status_code", [401, 403])
def test_refreshes_token_on_http_auth_error_and_retries(status_code: int) -> None:
    session = FakeSession(
        [
            FakeResponse(200, {"success": True, "access_token": "tok-old"}),
            FakeResponse(status_code, {"success": False, "msg": "unauthorized"}),
            FakeResponse(200, {"success": True, "access_token": "tok-new"}),
            FakeResponse(
                200,
                {"success": True, "dataList": [{"key": "B_left_cap1", "value": "72"}]},
            ),
        ]
    )
    client = SolarmanClient(_make_config(), session=session, clock=lambda: 1000.0)

    soc = client.get_battery_soc()

    assert soc == 72.0
    assert len(session.calls) == 4
    assert session.calls[1]["headers"]["Authorization"] == "bearer tok-old"
    assert session.calls[3]["headers"]["Authorization"] == "bearer tok-new"


def test_refreshes_token_on_http_200_success_false_and_retries() -> None:
    session = FakeSession(
        [
            FakeResponse(200, {"success": True, "access_token": "tok-stale"}),
            FakeResponse(
                200,
                {"success": False, "code": "2101018", "msg": "auth invalid token"},
            ),
            FakeResponse(200, {"success": True, "access_token": "tok-fresh"}),
            FakeResponse(
                200,
                {"success": True, "dataList": [{"key": "B_left_cap1", "value": "64.0"}]},
            ),
        ]
    )
    client = SolarmanClient(_make_config(), session=session, clock=lambda: 1000.0)

    soc = client.get_battery_soc()

    assert soc == 64.0
    assert len(session.calls) == 4
    assert session.calls[1]["headers"]["Authorization"] == "bearer tok-stale"
    assert session.calls[3]["headers"]["Authorization"] == "bearer tok-fresh"


def test_proactively_refreshes_token_when_ttl_exceeded() -> None:
    now = [1000.0]
    session = FakeSession(
        [
            FakeResponse(200, {"success": True, "access_token": "tok-1"}),
            FakeResponse(
                200,
                {"success": True, "dataList": [{"key": "B_left_cap1", "value": "90"}]},
            ),
            # Still within TTL -> should reuse tok-1 without calling /token
            FakeResponse(
                200,
                {"success": True, "dataList": [{"key": "B_left_cap1", "value": "89"}]},
            ),
            # Past TTL -> should proactively call /token before currentData
            FakeResponse(200, {"success": True, "access_token": "tok-2"}),
            FakeResponse(
                200,
                {"success": True, "dataList": [{"key": "B_left_cap1", "value": "88"}]},
            ),
        ]
    )
    client = SolarmanClient(
        _make_config(token_refresh_hours=2.0),
        session=session,
        clock=lambda: now[0],
    )

    assert client.get_battery_soc() == 90.0

    now[0] += 3600.0  # 1 hour later (< 2h TTL)
    assert client.get_battery_soc() == 89.0
    assert session.calls[-1]["headers"]["Authorization"] == "bearer tok-1"

    now[0] += 3700.0  # > 2h since tok-1 acquired
    assert client.get_battery_soc() == 88.0
    assert session.calls[-1]["headers"]["Authorization"] == "bearer tok-2"


def test_handles_network_timeout_and_invalid_json_gracefully() -> None:
    timeout_session = FakeSession(
        [
            FakeResponse(200, {"success": True, "access_token": "tok-1"}),
            requests.exceptions.Timeout("read timed out"),
        ]
    )
    client_timeout = SolarmanClient(_make_config(), session=timeout_session)
    assert client_timeout.get_battery_soc() is None

    bad_json_session = FakeSession(
        [
            FakeResponse(200, {"success": True, "access_token": "tok-1"}),
            FakeResponse(200, json_error=ValueError("invalid json")),
        ]
    )
    client_bad_json = SolarmanClient(_make_config(), session=bad_json_session)
    assert client_bad_json.get_battery_soc() is None


def test_never_logs_secrets_or_tokens_on_auth_or_api_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = FakeSession(
        [
            FakeResponse(200, {"success": True, "access_token": "SUPER_SECRET_BEARER_TOKEN"}),
            FakeResponse(200, {"success": False, "code": "2101018", "msg": "auth invalid token"}),
            FakeResponse(200, {"success": False, "msg": "bad credentials"}),
        ]
    )
    client = SolarmanClient(_make_config(), session=session)

    with caplog.at_level(logging.DEBUG):
        soc = client.get_battery_soc()

    assert soc is None
    combined_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "TOP_SECRET_SOLARMAN_APP_SECRET" not in combined_logs
    assert "TOP_SECRET_PASSWORD_HASH_0123456789" not in combined_logs
    assert "SUPER_SECRET_BEARER_TOKEN" not in combined_logs
