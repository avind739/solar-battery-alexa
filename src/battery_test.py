"""
Solar Battery Simulator for Alexa (via SinricPro)
Version: 1.1.0
Description: Simulates battery SoC updates to verify Alexa integration.
"""

import asyncio
import logging
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from sinricpro import SinricPro, SinricProConfig, SinricProThermostat

# --- 1. Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# --- 2. Load Environment Variables ---
load_dotenv()

APP_KEY = os.getenv("SINRIC_APP_KEY")
APP_SECRET = os.getenv("SINRIC_APP_SECRET")
DEVICE_ID = os.getenv("SINRIC_DEVICE_ID")

# Validate credentials
if not all([APP_KEY, APP_SECRET, DEVICE_ID]):
    logger.error("Missing SinricPro credentials in .env file. Exiting.")
    sys.exit(1)


async def send_update(device: SinricProThermostat, value: float) -> bool:
    """Sends a temperature event to the SinricPro cloud."""
    try:
        # We send SoC value as both temperature and humidity for display consistency
        success = await device.send_temperature_event(value, value)
        return success
    except Exception as e:
        logger.error(f"Failed to communicate with SinricPro: {e}")
        return False


async def main() -> None:
    """Main application loop."""
    # Initialize SinricPro
    sinric = SinricPro.get_instance()
    battery_device = SinricProThermostat(DEVICE_ID)
    sinric.add(battery_device)
    config = SinricProConfig(app_key=APP_KEY, app_secret=APP_SECRET)

    # Start the background WebSocket connection
    sinric_task = asyncio.create_task(sinric.begin(config))

    print("\n" + "=" * 40)
    print("   SOLAR BATTERY SIMULATOR (CLI)")
    print("=" * 40)
    print("Commands:")
    print(" - Enter 0-100 to update SoC")
    print(" - Type 'exit' to shut down safely")
    print("-" * 40 + "\n")

    try:
        while True:
            # Run input in an executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            user_input = await loop.run_in_executor(None, input, "Enter SoC Value: ")

            clean_input = user_input.strip().lower()

            if clean_input == "exit":
                logger.info("Initiating graceful shutdown...")
                break

            try:
                soc_val = float(clean_input)
                if 0 <= soc_val <= 100:
                    logger.info(f"Sending SoC {soc_val}% to Alexa...")
                    success = await send_update(battery_device, soc_val)
                    if success:
                        logger.info(f"Successfully updated Alexa state to {soc_val}%")
                    else:
                        logger.warning("Update rejected by SinricPro server.")
                else:
                    print("[!] Please enter a value between 0 and 100.")

            except ValueError:
                print("[!] Invalid input. Please enter a numerical SoC value.")

    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        # Clean up resources
        sinric_task.cancel()
        try:
            await sinric_task
        except asyncio.CancelledError:
            pass
        logger.info("Simulation service closed cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
