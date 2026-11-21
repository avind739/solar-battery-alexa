"""Async Solarman-to-SinricPro bridge runtime with health checks and clean recycle."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import requests
from sinricpro import SinricPro, SinricProConfig, SinricProThermostat

from solar_bridge.config import BridgeConfig

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_RECYCLE = 42


class SolarmanProvider(Protocol):
    """Protocol for fetching battery SoC readings."""

    def get_battery_soc(self) -> float | None: ...


class SinricGateway(Protocol):
    """Protocol abstracting the SinricPro WebSocket SDK for testability."""

    async def connect(self) -> None: ...

    def is_connected(self) -> bool: ...

    async def send_temperature(self, value: float) -> bool: ...

    async def ping(self) -> bool: ...

    async def stop(self) -> None: ...


class SinricProGateway:
    """Production SinricPro adapter wrapping the official sinricpro SDK."""

    def __init__(self, config: BridgeConfig, *, debug: bool = False) -> None:
        self._config = config
        self._debug = debug
        self._sinric = SinricPro.get_instance()
        self._device = SinricProThermostat(config.sinric_device_id)
        self._sinric.add(self._device)

    async def connect(self) -> None:
        sdk_config = SinricProConfig(
            app_key=self._config.sinric_app_key,
            app_secret=self._config.sinric_app_secret,
            debug=self._debug,
        )
        await self._sinric.begin(sdk_config)

    def is_connected(self) -> bool:
        return bool(self._sinric.is_connected())

    async def send_temperature(self, value: float) -> bool:
        return bool(await self._device.send_temperature_event(value, value))

    async def ping(self) -> bool:
        ws_client = self._sinric.websocket
        if ws_client is None or not ws_client.is_connected() or ws_client.ws is None:
            return False
        try:
            pong_waiter = await ws_client.ws.ping()
            await asyncio.wait_for(pong_waiter, timeout=10.0)
            return True
        except Exception as exc:
            logger.warning("Active WebSocket keepalive ping failed: %s", exc.__class__.__name__)
            try:
                await asyncio.wait_for(ws_client.ws.close(), timeout=3.0)
            except Exception:
                pass
            return False

    async def stop(self) -> None:
        await self._sinric.stop()


def _default_healthcheck(url: str) -> None:
    requests.get(url, timeout=5)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


class SolarBridge:
    """Coordinates Solarman polling, SinricPro WebSocket health, and clean recycles."""

    def __init__(
        self,
        config: BridgeConfig,
        *,
        solarman: SolarmanProvider,
        sinric: SinricGateway,
        healthcheck_fn: Callable[[str], None] | None = None,
        clock: Callable[[], float] | None = None,
        now_fn: Callable[[], datetime] | None = None,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._solarman = solarman
        self._sinric = sinric
        self._healthcheck_fn = (
            healthcheck_fn if healthcheck_fn is not None else _default_healthcheck
        )
        self._clock = clock if clock is not None else time.monotonic
        self._now_fn = now_fn if now_fn is not None else datetime.now
        self._sleep_fn = sleep_fn if sleep_fn is not None else asyncio.sleep

        self._last_sent_soc: float | None = None
        self._last_soc: float | None = None
        self._last_push_time: datetime | None = None
        self._last_poll_time: datetime | None = None
        self._started_at: datetime | None = None
        self._last_error: str | None = None

    def should_push(self, current_soc: float, now: datetime) -> tuple[bool, str]:
        """Return whether a new SoC value should be pushed and the reason."""
        if self._last_sent_soc is None or current_soc != self._last_sent_soc:
            return True, "Change"
        if self._last_push_time is None:
            return True, "Heartbeat"
        elapsed = (now - self._last_push_time).total_seconds()
        if elapsed >= self._config.heartbeat_interval_seconds:
            return True, "Heartbeat"
        return False, "Unchanged"

    def _write_status(self, *, connected: bool) -> None:
        status_file = self._config.status_file
        if status_file is None:
            return
        payload: dict[str, Any] = {
            "connected": connected,
            "last_soc": self._last_soc,
            "last_poll_at": self._last_poll_time.isoformat() if self._last_poll_time else None,
            "last_push_at": self._last_push_time.isoformat() if self._last_push_time else None,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "last_error": self._last_error,
        }
        try:
            _atomic_write_json(status_file, payload)
        except OSError as exc:
            logger.warning("Failed to write status file: %s", exc)

    async def poll_once(self, *, dry_run: bool = False) -> bool:
        """Fetch SoC from Solarman in a worker thread and push to SinricPro if due."""
        current_soc = await asyncio.to_thread(self._solarman.get_battery_soc)
        now = self._now_fn()
        self._last_poll_time = now

        if current_soc is None:
            self._last_error = "Failed to retrieve SoC from Solarman API"
            logger.error("%s.", self._last_error)
            self._write_status(connected=False if dry_run else self._sinric.is_connected())
            return False

        self._last_soc = current_soc

        if dry_run:
            self._last_error = None
            logger.info("Dry-run Solarman SoC reading: %s%%", current_soc)
            self._write_status(connected=False)
            return True

        needs_update, reason = self.should_push(current_soc, now)
        if not needs_update:
            self._last_error = None
            logger.debug("SoC %s%% unchanged. Skipping push.", current_soc)
            self._write_status(connected=self._sinric.is_connected())
            return True

        if not self._sinric.is_connected():
            self._last_error = "Skipped push because SinricPro is disconnected"
            logger.debug("%s.", self._last_error)
            self._write_status(connected=False)
            return False

        logger.info("Pushing SoC %s%% to Alexa (%s).", current_soc, reason)
        success = await self._sinric.send_temperature(current_soc)
        if not success:
            self._last_error = "SinricPro rejected the temperature event"
            logger.warning("%s.", self._last_error)
            self._write_status(connected=self._sinric.is_connected())
            return False

        self._last_sent_soc = current_soc
        self._last_push_time = now
        self._last_error = None

        if self._config.healthchecks_url:
            try:
                await asyncio.to_thread(self._healthcheck_fn, self._config.healthchecks_url)
            except Exception as exc:
                logger.warning("Healthchecks ping failed: %s", exc.__class__.__name__)

        self._write_status(connected=True)
        return True

    async def _safe_stop(self) -> None:
        logger.info("Stopping SinricPro connection...")
        try:
            await asyncio.wait_for(
                self._sinric.stop(),
                timeout=self._config.shutdown_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "SinricPro stop() timed out after %.1fs; continuing exit.",
                self._config.shutdown_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("Error while stopping SinricPro: %s", exc.__class__.__name__)

    async def run(self, *, once: bool = False, dry_run: bool = False) -> int:
        """Run the bridge loop and return a watchdog-compatible exit code."""
        started_mono = self._clock()
        self._started_at = self._now_fn()

        if dry_run:
            ok = await self.poll_once(dry_run=True)
            return EXIT_OK if ok else EXIT_ERROR

        try:
            try:
                logger.info("Connecting to SinricPro...")
                await asyncio.wait_for(
                    self._sinric.connect(),
                    timeout=self._config.startup_timeout_seconds,
                )
            except (asyncio.TimeoutError, Exception) as exc:
                self._last_error = f"SinricPro startup failed: {exc.__class__.__name__}"
                logger.critical("SinricPro startup connection failed: %s", exc)
                self._write_status(connected=False)
                return EXIT_ERROR

            if once:
                await self.poll_once()
                return EXIT_OK

            recycle_after_seconds = self._config.recycle_interval_hours * 3600.0
            last_poll_mono: float | None = None
            last_ping_mono = started_mono
            offline_since: float | None = None

            logger.info(
                "Solar Bridge operational (poll=%ss, health=%ss, recycle=%.1fh).",
                self._config.poll_interval_seconds,
                self._config.health_check_interval_seconds,
                self._config.recycle_interval_hours,
            )

            while True:
                now_mono = self._clock()

                if (now_mono - started_mono) >= recycle_after_seconds:
                    logger.info(
                        "Scheduled clean recycle reached (%.1fh). Exiting with code %s.",
                        self._config.recycle_interval_hours,
                        EXIT_RECYCLE,
                    )
                    return EXIT_RECYCLE

                connected = self._sinric.is_connected()
                if not connected:
                    if offline_since is None:
                        offline_since = now_mono
                    offline_for = now_mono - offline_since
                    self._last_error = "SinricPro WebSocket disconnected"
                    logger.warning(
                        "SinricPro is OFFLINE (%.0fs/%ss).",
                        offline_for,
                        self._config.max_offline_seconds,
                    )
                    self._write_status(connected=False)
                    if offline_for >= self._config.max_offline_seconds:
                        logger.critical(
                            "Max offline duration (%ss) reached. Exiting for watchdog restart.",
                            self._config.max_offline_seconds,
                        )
                        return EXIT_ERROR
                else:
                    if offline_since is not None:
                        logger.info("SinricPro connection restored.")
                        offline_since = None

                    if (now_mono - last_ping_mono) >= self._config.keepalive_interval_seconds:
                        last_ping_mono = now_mono
                        await self._sinric.ping()

                poll_due = (
                    last_poll_mono is None
                    or (now_mono - last_poll_mono) >= self._config.poll_interval_seconds
                )
                if poll_due and connected:
                    last_poll_mono = now_mono
                    await self.poll_once()

                await self._sleep_fn(self._config.health_check_interval_seconds)

        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Shutdown signal received.")
            return EXIT_OK
        except Exception as exc:
            self._last_error = f"Unhandled bridge error: {exc.__class__.__name__}"
            logger.critical("Unrecoverable error in bridge loop: %s", exc)
            self._write_status(connected=False)
            return EXIT_ERROR
        finally:
            await self._safe_stop()
