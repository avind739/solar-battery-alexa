from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from solar_bridge.config import (
    BridgeConfig,
    ConfigError,
    hash_solarman_password,
    resolve_env_file,
)


def _write_env(path: Path, values: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={val}" for key, val in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _base_env_values() -> dict[str, str]:
    return {
        "SINRIC_APP_KEY": "11111111-2222-3333-4444-555555555555",
        "SINRIC_APP_SECRET": "a" * 32,
        "SINRIC_DEVICE_ID": "0123456789abcdef01234567",
        "SOLARMAN_APP_ID": "test-app-id",
        "SOLARMAN_APP_SECRET": "test-app-secret",
        "SOLARMAN_EMAIL": "user@example.com",
        "SOLARMAN_PASSWORD_HASH": hashlib.sha256(b"super-secret").hexdigest(),
        "INVERTER_SN": "SN1234567890",
    }


def test_env_file_priority_explicit_over_config_and_fallback(tmp_path: Path) -> None:
    explicit = _write_env(tmp_path / "explicit.env", _base_env_values())
    env_var_file = _write_env(tmp_path / "from_var.env", _base_env_values())
    default_cfg = _write_env(tmp_path / "config" / ".env", _base_env_values())
    fallback = _write_env(tmp_path / "repo" / ".env", _base_env_values())

    resolved = resolve_env_file(
        env_file=explicit,
        environ={"SOLAR_BRIDGE_ENV": str(env_var_file)},
        default_config_path=default_cfg,
        fallback_path=fallback,
    )
    assert resolved == explicit


def test_env_file_priority_env_var_over_config_and_fallback(tmp_path: Path) -> None:
    env_var_file = _write_env(tmp_path / "from_var.env", _base_env_values())
    default_cfg = _write_env(tmp_path / "config" / ".env", _base_env_values())
    fallback = _write_env(tmp_path / "repo" / ".env", _base_env_values())

    resolved = resolve_env_file(
        env_file=None,
        environ={"SOLAR_BRIDGE_ENV": str(env_var_file)},
        default_config_path=default_cfg,
        fallback_path=fallback,
    )
    assert resolved == env_var_file


def test_env_file_priority_default_config_over_repo_fallback(tmp_path: Path) -> None:
    default_cfg = _write_env(tmp_path / "config" / ".env", _base_env_values())
    fallback = _write_env(tmp_path / "repo" / ".env", _base_env_values())

    resolved = resolve_env_file(
        env_file=None,
        environ={},
        default_config_path=default_cfg,
        fallback_path=fallback,
    )
    assert resolved == default_cfg


def test_env_file_priority_falls_back_to_repo_env(tmp_path: Path) -> None:
    missing_default = tmp_path / "config" / ".env"
    fallback = _write_env(tmp_path / "repo" / ".env", _base_env_values())

    resolved = resolve_env_file(
        env_file=None,
        environ={},
        default_config_path=missing_default,
        fallback_path=fallback,
    )
    assert resolved == fallback


def test_supports_solarman_password_hash_without_plaintext(tmp_path: Path) -> None:
    values = _base_env_values()
    expected_hash = values["SOLARMAN_PASSWORD_HASH"]
    env_path = _write_env(tmp_path / ".env", values)

    cfg = BridgeConfig.from_env(env_file=env_path, environ={})

    assert cfg.solarman_password_hash == expected_hash
    assert cfg.inverter_sn == "SN1234567890"


def test_supports_plaintext_solarman_password_and_hashes_it(tmp_path: Path) -> None:
    values = _base_env_values()
    del values["SOLARMAN_PASSWORD_HASH"]
    values["SOLARMAN_PASSWORD"] = "my-plaintext-pass"
    env_path = _write_env(tmp_path / ".env", values)

    cfg = BridgeConfig.from_env(env_file=env_path, environ={})

    assert cfg.solarman_password_hash == hash_solarman_password("my-plaintext-pass")
    assert cfg.solarman_password_hash == hashlib.sha256(b"my-plaintext-pass").hexdigest()


def test_missing_required_variable_raises_config_error(tmp_path: Path) -> None:
    values = _base_env_values()
    del values["INVERTER_SN"]
    env_path = _write_env(tmp_path / ".env", values)

    with pytest.raises(ConfigError, match="INVERTER_SN"):
        BridgeConfig.from_env(env_file=env_path, environ={})


def test_missing_both_password_and_password_hash_raises_config_error(tmp_path: Path) -> None:
    values = _base_env_values()
    del values["SOLARMAN_PASSWORD_HASH"]
    env_path = _write_env(tmp_path / ".env", values)

    with pytest.raises(ConfigError, match="SOLARMAN_PASSWORD"):
        BridgeConfig.from_env(env_file=env_path, environ={})


def test_default_intervals_and_optional_overrides(tmp_path: Path) -> None:
    base_env = _write_env(tmp_path / "base.env", _base_env_values())
    default_cfg = BridgeConfig.from_env(env_file=base_env, environ={})

    assert default_cfg.poll_interval_seconds == 300
    assert default_cfg.heartbeat_interval_seconds == 1800
    assert default_cfg.health_check_interval_seconds == 30
    assert default_cfg.keepalive_interval_seconds == 60
    assert default_cfg.max_offline_seconds == 120
    assert default_cfg.recycle_interval_hours == 12.0
    assert default_cfg.token_refresh_hours == 12.0
    assert default_cfg.healthchecks_url is None

    custom_values = _base_env_values() | {
        "HEALTHCHECKS_URL": "https://hc-ping.com/example-id",
        "POLL_INTERVAL_SECONDS": "120",
        "HEARTBEAT_INTERVAL_SECONDS": "900",
        "HEALTH_CHECK_INTERVAL_SECONDS": "15",
        "KEEPALIVE_INTERVAL_SECONDS": "45",
        "MAX_OFFLINE_SECONDS": "90",
        "RECYCLE_INTERVAL_HOURS": "6",
        "TOKEN_REFRESH_HOURS": "8",
        "LOG_FILE": str(tmp_path / "logs" / "bridge.log"),
        "STATUS_FILE": str(tmp_path / "status.json"),
    }
    custom_env = _write_env(tmp_path / "custom.env", custom_values)
    custom_cfg = BridgeConfig.from_env(env_file=custom_env, environ={})

    assert custom_cfg.healthchecks_url == "https://hc-ping.com/example-id"
    assert custom_cfg.poll_interval_seconds == 120
    assert custom_cfg.heartbeat_interval_seconds == 900
    assert custom_cfg.health_check_interval_seconds == 15
    assert custom_cfg.keepalive_interval_seconds == 45
    assert custom_cfg.max_offline_seconds == 90
    assert custom_cfg.recycle_interval_hours == 6.0
    assert custom_cfg.token_refresh_hours == 8.0
    assert custom_cfg.log_file == tmp_path / "logs" / "bridge.log"
    assert custom_cfg.status_file == tmp_path / "status.json"
