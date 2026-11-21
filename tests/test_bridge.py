from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from solar_bridge.bridge import EXIT_ERROR, EXIT_OK, EXIT_RECYCLE, SolarBridge
from solar_bridge.config import BridgeConfig


class FakeSolarman:
    def __init__(self, readings: list[float | None]) -> None:
        self._readings = list(readings)
        self.call_count = 0

    def get_battery_soc(self) -> float | None:
        self.call_count += 1
        if self._readings:
            return self._readings.pop(0)
        return None


class FakeSinricGateway:
    def __init__(
        self,
        *,
        connected_sequence: list[bool] | None = None,
        connect_error: Exception | None = None,
        connect_delay: float = 0.0,
        stop_delay: float = 0.0,
        push_results: list[bool] | None = None,
    ) -> None:
        self._connected_sequence = (
            list(connected_sequence) if connected_sequence is not None else []
        )
        self._connected = True
        self._connect_error = connect_error
        self._connect_delay = connect_delay
        self._stop_delay = stop_delay
        self._push_results = list(push_results) if push_results is not None else []
        self.connect_calls = 0
        self.stop_calls = 0
        self.ping_calls = 0
        self.pushed_values: list[float] = []

    async def connect(self) -> None:
        self.connect_calls += 1
        if self._connect_delay > 0:
            await asyncio.sleep(self._connect_delay)
        if self._connect_error is not None:
            raise self._connect_error

    def is_connected(self) -> bool:
        if self._connected_sequence:
            self._connected = self._connected_sequence.pop(0)
        return self._connected

    async def send_temperature(self, value: float) -> bool:
        self.pushed_values.append(value)
        if self._push_results:
            return self._push_results.pop(0)
        return True

    async def ping(self) -> bool:
        self.ping_calls += 1
        return self._connected

    async def stop(self) -> None:
        self.stop_calls += 1
        if self._stop_delay > 0:
            await asyncio.sleep(self._stop_delay)


def _make_config(
    *,
    status_file: Path | None = None,
    healthchecks_url: str | None = None,
    poll_interval_seconds: int = 300,
    heartbeat_interval_seconds: int = 1800,
    health_check_interval_seconds: int = 30,
    keepalive_interval_seconds: int = 60,
    max_offline_seconds: int = 120,
    recycle_interval_hours: float = 12.0,
    startup_timeout_seconds: float = 0.2,
    shutdown_timeout_seconds: float = 0.2,
) -> BridgeConfig:
    return BridgeConfig(
        sinric_app_key="11111111-2222-3333-4444-555555555555",
        sinric_app_secret="s" * 32,
        sinric_device_id="0123456789abcdef01234567",
        solarman_app_id="app-id",
        solarman_app_secret="app-secret",
        solarman_email="owner@example.com",
        solarman_password_hash="a" * 64,
        inverter_sn="INV-001",
        healthchecks_url=healthchecks_url,
        poll_interval_seconds=poll_interval_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        health_check_interval_seconds=health_check_interval_seconds,
        keepalive_interval_seconds=keepalive_interval_seconds,
        max_offline_seconds=max_offline_seconds,
        recycle_interval_hours=recycle_interval_hours,
        startup_timeout_seconds=startup_timeout_seconds,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
        status_file=status_file,
    )


async def test_pushes_on_first_reading_skips_unchanged_and_pushes_on_change() -> None:
    current_time = [datetime(2026, 11, 21, 10, 0, 0)]
    solarman = FakeSolarman([80.0, 80.0, 79.0])
    sinric = FakeSinricGateway()
    bridge = SolarBridge(
        _make_config(),
        solarman=solarman,
        sinric=sinric,
        now_fn=lambda: current_time[0],
    )

    await bridge.poll_once()
    assert sinric.pushed_values == [80.0]

    # 5 minutes later, same SoC -> should skip push
    current_time[0] += timedelta(minutes=5)
    await bridge.poll_once()
    assert sinric.pushed_values == [80.0]

    # 5 minutes later, SoC changed -> should push
    current_time[0] += timedelta(minutes=5)
    await bridge.poll_once()
    assert sinric.pushed_values == [80.0, 79.0]


async def test_pushes_heartbeat_after_heartbeat_interval_when_soc_unchanged() -> None:
    current_time = [datetime(2026, 11, 21, 10, 0, 0)]
    solarman = FakeSolarman([80.0, 80.0])
    sinric = FakeSinricGateway()
    bridge = SolarBridge(
        _make_config(heartbeat_interval_seconds=1800),
        solarman=solarman,
        sinric=sinric,
        now_fn=lambda: current_time[0],
    )

    await bridge.poll_once()
    assert sinric.pushed_values == [80.0]

    # 30 minutes later, unchanged SoC -> heartbeat forces a push
    current_time[0] += timedelta(seconds=1800)
    await bridge.poll_once()
    assert sinric.pushed_values == [80.0, 80.0]


async def test_pings_healthchecks_on_push_and_ignores_healthcheck_failure() -> None:
    pinged_urls: list[str] = []

    def flaky_healthcheck(url: str) -> None:
        pinged_urls.append(url)
        if len(pinged_urls) == 2:
            raise RuntimeError("healthchecks unreachable")

    solarman = FakeSolarman([80.0, 75.0])
    sinric = FakeSinricGateway()
    bridge = SolarBridge(
        _make_config(healthchecks_url="https://hc-ping.com/test"),
        solarman=solarman,
        sinric=sinric,
        healthcheck_fn=flaky_healthcheck,
    )

    assert await bridge.poll_once() is True
    assert await bridge.poll_once() is True
    assert pinged_urls == ["https://hc-ping.com/test", "https://hc-ping.com/test"]


async def test_startup_connection_failure_exits_fast_with_error_code() -> None:
    solarman = FakeSolarman([80.0])
    sinric = FakeSinricGateway(connect_error=RuntimeError("dns failure"))
    bridge = SolarBridge(_make_config(), solarman=solarman, sinric=sinric)

    code = await bridge.run()

    assert code == EXIT_ERROR
    assert solarman.call_count == 0
    assert sinric.stop_calls == 1


async def test_startup_timeout_exits_fast_with_error_code() -> None:
    solarman = FakeSolarman([80.0])
    sinric = FakeSinricGateway(connect_delay=5.0)
    bridge = SolarBridge(
        _make_config(startup_timeout_seconds=0.05),
        solarman=solarman,
        sinric=sinric,
    )

    code = await bridge.run()

    assert code == EXIT_ERROR
    assert solarman.call_count == 0


async def test_extended_disconnect_exits_with_error_code() -> None:
    mono = [0.0]

    async def fake_sleep(seconds: float) -> None:
        mono[0] += seconds

    solarman = FakeSolarman([80.0, 80.0, 80.0])
    # Always disconnected after initial connect
    sinric = FakeSinricGateway(connected_sequence=[False, False, False, False, False, False])
    bridge = SolarBridge(
        _make_config(
            health_check_interval_seconds=30,
            max_offline_seconds=120,
            poll_interval_seconds=300,
        ),
        solarman=solarman,
        sinric=sinric,
        clock=lambda: mono[0],
        sleep_fn=fake_sleep,
    )

    code = await bridge.run()

    assert code == EXIT_ERROR
    assert mono[0] >= 120.0
    assert sinric.stop_calls == 1


async def test_brief_disconnect_that_recovers_does_not_exit_for_offline() -> None:
    mono = [0.0]

    async def fake_sleep(seconds: float) -> None:
        mono[0] += seconds

    # Disconnect for 2 ticks (60s < 120s max_offline), then recover until scheduled recycle (1h)
    connected_seq = [False, False, True, True]
    solarman = FakeSolarman([85.0])
    sinric = FakeSinricGateway(connected_sequence=connected_seq)
    bridge = SolarBridge(
        _make_config(
            health_check_interval_seconds=30,
            max_offline_seconds=120,
            recycle_interval_hours=0.05,  # 180 seconds
            poll_interval_seconds=300,
        ),
        solarman=solarman,
        sinric=sinric,
        clock=lambda: mono[0],
        sleep_fn=fake_sleep,
    )

    code = await bridge.run()

    assert code == EXIT_RECYCLE
    assert sinric.stop_calls == 1


async def test_periodic_clean_recycle_exits_with_recycle_code() -> None:
    mono = [0.0]

    async def fake_sleep(seconds: float) -> None:
        mono[0] += seconds

    solarman = FakeSolarman([82.0])
    sinric = FakeSinricGateway()
    bridge = SolarBridge(
        _make_config(
            health_check_interval_seconds=30,
            recycle_interval_hours=0.025,  # 90 seconds
            poll_interval_seconds=300,
        ),
        solarman=solarman,
        sinric=sinric,
        clock=lambda: mono[0],
        sleep_fn=fake_sleep,
    )

    code = await bridge.run()

    assert code == EXIT_RECYCLE
    assert mono[0] >= 90.0
    assert sinric.stop_calls == 1


async def test_shutdown_timeout_prevents_hanging_on_dead_socket() -> None:
    solarman = FakeSolarman([85.0])
    sinric = FakeSinricGateway(stop_delay=10.0)
    bridge = SolarBridge(
        _make_config(shutdown_timeout_seconds=0.05),
        solarman=solarman,
        sinric=sinric,
    )

    code = await asyncio.wait_for(bridge.run(once=True), timeout=1.0)

    assert code == EXIT_OK
    assert sinric.stop_calls == 1


async def test_writes_status_json_on_successful_push(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    fixed_now = datetime(2026, 11, 21, 12, 30, 0)
    solarman = FakeSolarman([91.5])
    sinric = FakeSinricGateway()
    bridge = SolarBridge(
        _make_config(status_file=status_path),
        solarman=solarman,
        sinric=sinric,
        now_fn=lambda: fixed_now,
    )

    code = await bridge.run(once=True)

    assert code == EXIT_OK
    assert status_path.exists()
    data: dict[str, Any] = json.loads(status_path.read_text(encoding="utf-8"))
    assert data["last_soc"] == 91.5
    assert data["connected"] is True
    assert data["last_error"] is None
    assert data["last_push_at"] == fixed_now.isoformat()
    assert data["last_poll_at"] == fixed_now.isoformat()
    assert data["started_at"] == fixed_now.isoformat()


async def test_dry_run_fetches_soc_without_pushing_to_sinric() -> None:
    solarman = FakeSolarman([77.0])
    sinric = FakeSinricGateway()
    bridge = SolarBridge(_make_config(), solarman=solarman, sinric=sinric)

    code = await bridge.run(once=True, dry_run=True)

    assert code == EXIT_OK
    assert solarman.call_count == 1
    assert sinric.connect_calls == 0
    assert sinric.pushed_values == []
