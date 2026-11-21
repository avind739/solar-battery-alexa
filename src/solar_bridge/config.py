"""Typed configuration loading with zero import-time side effects."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_CONFIG_ENV_PATH = Path.home() / ".config" / "solar-battery-alexa" / ".env"


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


def hash_solarman_password(password: str) -> str:
    """Return the SHA-256 hex digest expected by the Solarman API."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def resolve_env_file(
    env_file: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    default_config_path: Path | None = None,
    fallback_path: Path | None = None,
) -> Path | None:
    """Resolve the .env path in priority order.

    1. Explicit ``env_file`` argument
    2. ``SOLAR_BRIDGE_ENV`` environment variable
    3. ``~/.config/solar-battery-alexa/.env`` (if it exists)
    4. ``./.env`` in the current working directory (if it exists)
    """
    env_map = os.environ if environ is None else environ

    if env_file is not None:
        return Path(env_file).expanduser()

    env_override = env_map.get("SOLAR_BRIDGE_ENV", "").strip()
    if env_override:
        return Path(env_override).expanduser()

    primary = DEFAULT_CONFIG_ENV_PATH if default_config_path is None else default_config_path
    if primary.is_file():
        return primary

    fallback = Path.cwd() / ".env" if fallback_path is None else fallback_path
    if fallback.is_file():
        return fallback

    return None


def _get_value(values: Mapping[str, str], name: str) -> str | None:
    raw = values.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped if stripped else None


def _require(values: Mapping[str, str], name: str) -> str:
    val = _get_value(values, name)
    if val is None:
        raise ConfigError(f"Missing required environment variable: {name}")
    return val


def _parse_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = _get_value(values, name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ConfigError(f"Invalid integer for {name}: {raw!r}") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be > 0, got {parsed}")
    return parsed


def _parse_float(values: Mapping[str, str], name: str, default: float) -> float:
    raw = _get_value(values, name)
    if raw is None:
        return default
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ConfigError(f"Invalid number for {name}: {raw!r}") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be > 0, got {parsed}")
    return parsed


def _parse_optional_path(values: Mapping[str, str], name: str) -> Path | None:
    raw = _get_value(values, name)
    if raw is None:
        return None
    return Path(raw).expanduser()


@dataclass(frozen=True)
class BridgeConfig:
    """Validated runtime configuration for the Solar Battery Alexa Bridge."""

    sinric_app_key: str
    sinric_app_secret: str
    sinric_device_id: str
    solarman_app_id: str
    solarman_app_secret: str
    solarman_email: str
    solarman_password_hash: str
    inverter_sn: str
    healthchecks_url: str | None = None
    poll_interval_seconds: int = 300
    heartbeat_interval_seconds: int = 1800
    health_check_interval_seconds: int = 30
    keepalive_interval_seconds: int = 60
    max_offline_seconds: int = 120
    recycle_interval_hours: float = 12.0
    token_refresh_hours: float = 12.0
    startup_timeout_seconds: float = 20.0
    shutdown_timeout_seconds: float = 5.0
    log_file: Path | None = None
    status_file: Path | None = None
    env_source: Path | None = None

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        default_config_path: Path | None = None,
        fallback_path: Path | None = None,
    ) -> BridgeConfig:
        """Load and validate configuration from an env file and environment mapping."""
        env_map = os.environ if environ is None else environ
        resolved = resolve_env_file(
            env_file=env_file,
            environ=env_map,
            default_config_path=default_config_path,
            fallback_path=fallback_path,
        )

        if env_file is not None and (resolved is None or not resolved.is_file()):
            raise ConfigError(f"Specified env file not found: {env_file}")

        merged: dict[str, str] = {}
        if resolved is not None and resolved.is_file():
            for key, val in dotenv_values(resolved).items():
                if val is not None:
                    merged[key] = val

        for key, val in env_map.items():
            merged[key] = val

        password_hash = _get_value(merged, "SOLARMAN_PASSWORD_HASH")
        if password_hash is None:
            plaintext = _get_value(merged, "SOLARMAN_PASSWORD")
            if plaintext is None:
                raise ConfigError(
                    "Missing required environment variable: "
                    "SOLARMAN_PASSWORD_HASH (or SOLARMAN_PASSWORD)"
                )
            password_hash = hash_solarman_password(plaintext)

        return cls(
            sinric_app_key=_require(merged, "SINRIC_APP_KEY"),
            sinric_app_secret=_require(merged, "SINRIC_APP_SECRET"),
            sinric_device_id=_require(merged, "SINRIC_DEVICE_ID"),
            solarman_app_id=_require(merged, "SOLARMAN_APP_ID"),
            solarman_app_secret=_require(merged, "SOLARMAN_APP_SECRET"),
            solarman_email=_require(merged, "SOLARMAN_EMAIL"),
            solarman_password_hash=password_hash,
            inverter_sn=_require(merged, "INVERTER_SN"),
            healthchecks_url=_get_value(merged, "HEALTHCHECKS_URL"),
            poll_interval_seconds=_parse_int(merged, "POLL_INTERVAL_SECONDS", 300),
            heartbeat_interval_seconds=_parse_int(merged, "HEARTBEAT_INTERVAL_SECONDS", 1800),
            health_check_interval_seconds=_parse_int(
                merged, "HEALTH_CHECK_INTERVAL_SECONDS", 30
            ),
            keepalive_interval_seconds=_parse_int(merged, "KEEPALIVE_INTERVAL_SECONDS", 60),
            max_offline_seconds=_parse_int(merged, "MAX_OFFLINE_SECONDS", 120),
            recycle_interval_hours=_parse_float(merged, "RECYCLE_INTERVAL_HOURS", 12.0),
            token_refresh_hours=_parse_float(merged, "TOKEN_REFRESH_HOURS", 12.0),
            startup_timeout_seconds=_parse_float(merged, "STARTUP_TIMEOUT_SECONDS", 20.0),
            shutdown_timeout_seconds=_parse_float(merged, "SHUTDOWN_TIMEOUT_SECONDS", 5.0),
            log_file=_parse_optional_path(merged, "LOG_FILE"),
            status_file=_parse_optional_path(merged, "STATUS_FILE"),
            env_source=resolved,
        )
