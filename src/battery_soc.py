"""
Solar Battery Alexa Bridge (Production Version 1.2)
Description: Polls Solarman (Deye) API for Battery SoC and pushes to SinricPro.
Enhancements: 
    - WebSocket Health Monitor: Exits after 10 failed cycles to trigger Watchdog reboot.
    - Improved Error Handling for DNS/Network failures.

Features: 
    - Throttling (updates only on change or 30-min heartbeat)
    - Connection pooling via requests.Session
    - Environment-based configuration
    - Graceful shutdown handling
"""

import asyncio
import hashlib
import logging
import os
import sys
import time
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv
from sinricpro import SinricPro, SinricProConfig, SinricProThermostat

# --- 1. Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# --- 2. Configuration & Validation ---
load_dotenv()

def get_env_var(name: str, required: bool = True) -> Optional[str]:
    value = os.getenv(name)
    if required and not value:
        logger.critical(f"Missing required environment variable: {name}")
        sys.exit(1)
    return value

# SinricPro Settings
APP_KEY = get_env_var("SINRIC_APP_KEY")
APP_SECRET = get_env_var("SINRIC_APP_SECRET")
DEVICE_ID = get_env_var("SINRIC_DEVICE_ID")

# Solarman Settings
SOLARMAN_APP_ID = get_env_var("SOLARMAN_APP_ID")
SOLARMAN_APP_SECRET = get_env_var("SOLARMAN_APP_SECRET")
SOLARMAN_EMAIL = get_env_var("SOLARMAN_EMAIL")
SOLARMAN_PASS = get_env_var("SOLARMAN_PASSWORD")
INVERTER_SN = get_env_var("INVERTER_SN")

# Monitoring/Health Settings
HEALTH_URL = get_env_var("HEALTHCHECKS_URL", required=False)
POLL_INTERVAL = 300  # 5 minutes
FORCE_UPDATE_INTERVAL = 1800  # 30 minutes heartbeat
MAX_OFFLINE_CYCLES = 10  # Exit after 50 minutes of disconnection


class SolarmanClient:
    """Client to interact with the Solarman Global API."""

    def __init__(self):
        self.token: Optional[str] = None
        self.base_url = "https://globalapi.solarmanpv.com"
        self.session = requests.Session()

    def _get_token(self) -> bool:
        """Authenticates with Solarman and retrieves an access token."""
        logger.info("Requesting new Solarman access token...")
        pass_hash = hashlib.sha256(SOLARMAN_PASS.encode()).hexdigest()
        url = f"{self.base_url}/account/v1.0/token?appId={SOLARMAN_APP_ID}&language=en"
        
        payload = {
            "appSecret": SOLARMAN_APP_SECRET,
            "email": SOLARMAN_EMAIL,
            "password": pass_hash
        }

        try:
            response = self.session.post(url, json=payload, timeout=20)
            data = response.json()
            if data.get("success"):
                self.token = data.get("access_token")
                logger.info("Solarman authentication successful.")
                return True
            logger.error(f"Solarman Auth Failed: {data.get('msg')}")
        except Exception as e:
            logger.error(f"Network error during Solarman auth: {e}")
        return False

    def get_battery_soc(self) -> Optional[float]:
        """Fetches the current State of Charge from the inverter."""
        if not self.token and not self._get_token():
            return None

        url = f"{self.base_url}/device/v1.0/currentData"
        headers = {"Authorization": f"bearer {self.token}"}
        payload = {"deviceSn": INVERTER_SN}

        try:
            response = self.session.post(url, headers=headers, json=payload, timeout=20)

            if response.status_code == 401:
                if self._get_token():
                    headers["Authorization"] = f"bearer {self.token}"
                    response = self.session.post(url, headers=headers, json=payload, timeout=20)
                else:
                    return None

            data = response.json()
            for item in data.get("dataList", []):
                if item.get("key") == "B_left_cap1":
                    return float(item.get("value"))
            
            logger.warning("SoC key 'B_left_cap1' not found in API response.")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Solarman API connection issue: {e}")
        except Exception as e:
            logger.error(f"Unexpected error parsing Solarman data: {e}")
        return None


async def main():
    """Main execution loop."""
    solarman = SolarmanClient()
    
    # Initialize SinricPro
    sinric = SinricPro.get_instance()
    battery_device = SinricProThermostat(DEVICE_ID)
    sinric.add(battery_device)
    config = SinricProConfig(app_key=APP_KEY, app_secret=APP_SECRET)

    # Background task for WebSocket connection
    sinric_task = asyncio.create_task(sinric.begin(config))
    # Allow time for SinricPro handshake
    logger.info("Initializing SinricPro connection...")
    await asyncio.sleep(5)

    # State tracking variables
    last_sent_soc: float = -1.0
    last_update_time = datetime.min
    offline_cycles = 0  # Counter for consecutive connection failures
    
    logger.info(f"Solar Bridge Operational. Polling: {POLL_INTERVAL}s")

    try:
        while True:
            # 1. Check SinricPro Connection Health
            if not sinric.is_connected():
                offline_cycles += 1
                logger.warning(f"SinricPro is OFFLINE. Attempting to recover... ({offline_cycles}/{MAX_OFFLINE_CYCLES})")
                
                if offline_cycles >= MAX_OFFLINE_CYCLES:
                    logger.critical("Maximum offline cycles reached. Forcing exit for Watchdog reboot.")
                    break # Exit loop to trigger cleanup and script restart
            else:
                if offline_cycles > 0:
                    logger.info("SinricPro connection restored.")
                offline_cycles = 0 # Reset counter on successful connection

            # 2. Fetch data from Solarman
            current_soc = solarman.get_battery_soc()
            now = datetime.now()

            if current_soc is not None:
                # 3. Decision Logic: Push if changed OR heartbeat interval reached
                seconds_since_last = (now - last_update_time).total_seconds()
                needs_update = (current_soc != last_sent_soc) or (seconds_since_last >= FORCE_UPDATE_INTERVAL)

                if needs_update:
                    # Skip push if we know we are offline (saves API credits and prevents hanging)
                    if not sinric.is_connected():
                        logger.debug("Skipping push: WebSocket is currently disconnected.")
                    else:
                        reason = "Change" if current_soc != last_sent_soc else "Heartbeat"
                        logger.info(f"Pushing SoC {current_soc}% to Alexa ({reason})")
                        
                        success = await battery_device.send_temperature_event(current_soc, current_soc)
                        
                        if success:
                            last_sent_soc = current_soc
                            last_update_time = now
                            
                            if HEALTH_URL:
                                try: requests.get(HEALTH_URL, timeout=5)
                                except Exception: pass
                        else:
                            logger.warning("SinricPro server rejected the push event.")
                else:
                    logger.debug(f"SoC {current_soc}% unchanged. Skipping push.")
            else:
                logger.error("Failed to retrieve SoC from Solarman API.")

            await asyncio.sleep(POLL_INTERVAL)

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutdown signal received.")
    except Exception as e:
        logger.critical(f"Unrecoverable error in main loop: {e}")
    finally:
        logger.info("Cleaning up resources...")
        sinric_task.cancel()
        try:
            # Wait for clean close of the WebSocket
            await asyncio.gather(sinric_task, return_exceptions=True)
        except Exception:
            pass
        logger.info("Bridge stopped cleanly.")
        # Final exit to ensure Watchdog picks up the failure
        sys.exit(1 if offline_cycles >= MAX_OFFLINE_CYCLES else 0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)