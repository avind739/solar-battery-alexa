"""Interactive Solar Battery simulator for verifying SinricPro -> Alexa integration."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import dotenv_values
from sinricpro import SinricPro, SinricProConfig, SinricProThermostat

_SRC_DIR = str(Path(__file__).resolve().parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from solar_bridge.config import resolve_env_file  # noqa: E402

logger = logging.getLogger(__name__)


def _load_sinric_credentials(env_file: Path | None) -> tuple[str, str, str]:
    resolved = resolve_env_file(env_file=env_file)
    values: dict[str, str] = {}
    if resolved is not None and resolved.is_file():
        for key, val in dotenv_values(resolved).items():
            if val is not None:
                values[key] = val
    for key, val in os.environ.items():
        values[key] = val

    app_key = values.get("SINRIC_APP_KEY", "").strip()
    app_secret = values.get("SINRIC_APP_SECRET", "").strip()
    device_id = values.get("SINRIC_DEVICE_ID", "").strip()
    if not all([app_key, app_secret, device_id]):
        raise ValueError("Missing SINRIC_APP_KEY, SINRIC_APP_SECRET, or SINRIC_DEVICE_ID.")
    return app_key, app_secret, device_id


async def send_update(device: SinricProThermostat, value: float) -> bool:
    """Send a simulated temperature/SoC event to the SinricPro cloud."""
    try:
        return bool(await device.send_temperature_event(value, value))
    except Exception as exc:
        logger.error("Failed to communicate with SinricPro: %s", exc)
        return False


async def run_simulator(app_key: str, app_secret: str, device_id: str) -> None:
    """Run the interactive CLI simulator loop."""
    sinric = SinricPro.get_instance()
    battery_device = SinricProThermostat(device_id)
    sinric.add(battery_device)
    config = SinricProConfig(app_key=app_key, app_secret=app_secret)

    await asyncio.wait_for(sinric.begin(config), timeout=20.0)

    print("\n" + "=" * 40)
    print("   SOLAR BATTERY SIMULATOR (CLI)")
    print("=" * 40)
    print("Commands:")
    print(" - Enter 0-100 to update SoC")
    print(" - Type 'exit' to shut down safely")
    print("-" * 40 + "\n")

    try:
        while True:
            user_input = await asyncio.to_thread(input, "Enter SoC Value: ")
            clean_input = user_input.strip().lower()

            if clean_input == "exit":
                logger.info("Initiating graceful shutdown...")
                break

            try:
                soc_val = float(clean_input)
                if 0.0 <= soc_val <= 100.0:
                    logger.info("Sending SoC %s%% to Alexa...", soc_val)
                    success = await send_update(battery_device, soc_val)
                    if success:
                        logger.info("Successfully updated Alexa state to %s%%", soc_val)
                    else:
                        logger.warning("Update rejected by SinricPro server.")
                else:
                    print("[!] Please enter a value between 0 and 100.")
            except ValueError:
                print("[!] Invalid input. Please enter a numerical SoC value.")
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        try:
            await asyncio.wait_for(sinric.stop(), timeout=5.0)
        except Exception:
            pass
        logger.info("Simulation service closed cleanly.")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the manual Alexa simulator."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Interactive SinricPro Solar Battery Simulator")
    parser.add_argument("--env-file", type=Path, default=None, help="Optional path to .env file")
    args = parser.parse_args(argv)

    try:
        app_key, app_secret, device_id = _load_sinric_credentials(args.env_file)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    try:
        asyncio.run(run_simulator(app_key, app_secret, device_id))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
