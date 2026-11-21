"""Command-line interface for the Solar Battery Alexa Bridge."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import signal
import sys
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler
from pathlib import Path

from solar_bridge.bridge import EXIT_ERROR, EXIT_OK, SinricProGateway, SolarBridge
from solar_bridge.config import BridgeConfig, ConfigError, hash_solarman_password
from solar_bridge.solarman import SolarmanClient


def configure_logging(*, debug: bool = False, log_file: Path | None = None) -> None:
    """Configure console logging and optional rotating file logging."""
    level = logging.DEBUG if debug else logging.INFO
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="solar-bridge",
        description="Solarman-to-SinricPro Alexa Battery SoC Bridge",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to .env file (defaults to ~/.config/solar-battery-alexa/.env then ./.env)",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate configuration and exit without connecting to external APIs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch battery SoC once from Solarman without connecting or pushing to SinricPro",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Connect, run a single poll/push cycle, and exit cleanly",
    )
    parser.add_argument(
        "--hash-password",
        action="store_true",
        help="Interactively compute SOLARMAN_PASSWORD_HASH (SHA-256) and exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


async def _run_with_signals(
    bridge: SolarBridge,
    *,
    once: bool,
    dry_run: bool,
) -> int:
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()

    def _cancel() -> None:
        if task is not None and not task.done():
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _cancel)
        except (NotImplementedError, RuntimeError):
            pass

    return await bridge.run(once=once, dry_run=dry_run)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint returning an OS exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.hash_password:
        password = getpass.getpass("Enter Solarman password: ")
        if not password:
            print("Error: password cannot be empty.", file=sys.stderr)
            return EXIT_ERROR
        print(f"SOLARMAN_PASSWORD_HASH={hash_solarman_password(password)}")
        return EXIT_OK

    try:
        config = BridgeConfig.from_env(env_file=args.env_file)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    configure_logging(debug=args.debug, log_file=config.log_file)
    logger = logging.getLogger(__name__)

    if args.check_config:
        source = str(config.env_source) if config.env_source else "environment"
        logger.info("Configuration OK (source=%s, inverter=%s).", source, config.inverter_sn)
        return EXIT_OK

    solarman = SolarmanClient(config)
    sinric = SinricProGateway(config, debug=args.debug)
    bridge = SolarBridge(config, solarman=solarman, sinric=sinric)

    try:
        return asyncio.run(
            _run_with_signals(bridge, once=args.once, dry_run=args.dry_run)
        )
    except KeyboardInterrupt:
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
