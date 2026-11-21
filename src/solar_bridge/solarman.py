"""Solarman Global REST API client with robust token refresh."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

import requests

from solar_bridge.config import BridgeConfig

logger = logging.getLogger(__name__)

SOLARMAN_BASE_URL = "https://globalapi.solarmanpv.com"
SOC_DATA_KEY = "B_left_cap1"


class HttpResponse(Protocol):
    """Minimal response interface used by SolarmanClient."""

    status_code: int

    def json(self) -> Any: ...


class HttpSession(Protocol):
    """Minimal HTTP session interface used by SolarmanClient."""

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse: ...


class SolarmanClient:
    """Client to authenticate with and fetch battery SoC from Solarman Global API."""

    def __init__(
        self,
        config: BridgeConfig,
        *,
        session: HttpSession | None = None,
        clock: Callable[[], float] | None = None,
        base_url: str = SOLARMAN_BASE_URL,
        request_timeout: float = 20.0,
    ) -> None:
        self._config = config
        self._session: HttpSession = session if session is not None else requests.Session()
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._base_url = base_url.rstrip("/")
        self._request_timeout = request_timeout
        self._token: str | None = None
        self._token_acquired_at: float | None = None

    def _is_token_stale(self) -> bool:
        if not self._token or self._token_acquired_at is None:
            return True
        max_age_seconds = self._config.token_refresh_hours * 3600.0
        return (self._clock() - self._token_acquired_at) >= max_age_seconds

    def _get_token(self) -> bool:
        """Authenticate with Solarman and store a fresh access token."""
        logger.info("Requesting new Solarman access token...")
        url = (
            f"{self._base_url}/account/v1.0/token"
            f"?appId={self._config.solarman_app_id}&language=en"
        )
        payload = {
            "appSecret": self._config.solarman_app_secret,
            "email": self._config.solarman_email,
            "password": self._config.solarman_password_hash,
        }

        try:
            response = self._session.post(url, json=payload, timeout=self._request_timeout)
            data = response.json()
        except requests.exceptions.RequestException as exc:
            logger.error("Network error during Solarman auth: %s", exc.__class__.__name__)
            return False
        except (ValueError, TypeError) as exc:
            logger.error("Invalid JSON during Solarman auth: %s", exc.__class__.__name__)
            return False

        if isinstance(data, dict) and data.get("success") and data.get("access_token"):
            self._token = str(data["access_token"])
            self._token_acquired_at = self._clock()
            logger.info("Solarman authentication successful.")
            return True

        code = data.get("code") if isinstance(data, dict) else None
        msg = data.get("msg") if isinstance(data, dict) else "unexpected response"
        logger.error("Solarman auth failed (code=%s, msg=%s).", code, msg)
        self._token = None
        self._token_acquired_at = None
        return False

    def _fetch_current_data(self) -> tuple[int, dict[str, Any] | None]:
        url = f"{self._base_url}/device/v1.0/currentData"
        headers = {"Authorization": f"bearer {self._token}"}
        payload = {"deviceSn": self._config.inverter_sn}

        response = self._session.post(
            url,
            headers=headers,
            json=payload,
            timeout=self._request_timeout,
        )
        status_code = response.status_code
        if status_code in (401, 403):
            return status_code, None

        parsed = response.json()
        if not isinstance(parsed, dict):
            raise ValueError("Solarman response JSON is not an object")
        return status_code, parsed

    def get_battery_soc(self) -> float | None:
        """Fetch current battery State of Charge (%) from the inverter."""
        if self._is_token_stale() and not self._get_token():
            return None

        try:
            status_code, data = self._fetch_current_data()

            needs_refresh = status_code in (401, 403) or (
                data is not None and data.get("success") is False
            )
            if needs_refresh:
                logger.warning(
                    "Solarman token rejected or expired (status=%s); refreshing and retrying.",
                    status_code,
                )
                if not self._get_token():
                    return None
                status_code, data = self._fetch_current_data()

            if status_code != 200 or data is None:
                logger.warning("Solarman currentData returned HTTP %s.", status_code)
                return None

            if data.get("success") is False:
                logger.warning(
                    "Solarman currentData unsuccessful after retry (code=%s, msg=%s).",
                    data.get("code"),
                    data.get("msg"),
                )
                return None

            data_list = data.get("dataList")
            if not isinstance(data_list, list):
                logger.warning("Solarman response missing 'dataList'.")
                return None

            for item in data_list:
                if isinstance(item, dict) and item.get("key") == SOC_DATA_KEY:
                    raw_value = item.get("value")
                    if raw_value is not None:
                        return float(raw_value)

            logger.warning("SoC key '%s' not found in Solarman API response.", SOC_DATA_KEY)
        except requests.exceptions.RequestException as exc:
            logger.warning("Solarman API connection issue: %s", exc.__class__.__name__)
        except (ValueError, TypeError) as exc:
            logger.error("Unexpected error parsing Solarman data: %s", exc.__class__.__name__)
        return None
