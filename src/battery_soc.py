"""
Solar Battery Alexa Bridge (Production Version)
Description: Polls Solarman (Deye) API for Battery SoC and pushes to SinricPro.
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


class SolarmanClient:
    """Client to interact with the Solarman Global API."""

    def __init__(self):
        self.token: Optional[str] = None
        self.base_url = "https://globalapi.solarmanpv.com"
        self.session = requests.Session()  # Use session for connection pooling

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

            # Handle expired token
            if response.status_code == 401:
                if self._get_token():
                    headers["Authorization"] = f"bearer {self.token}"
                    response = self.session.post(url, headers=headers, json=payload, timeout=20)
                else:
                    return None

            data = response.json()
            for item in data.get("dataList", []):
                # Key specific to Deye/Solarman SoC
                if item.get("key") == "B_left_cap1":
                    return float(item.get("value"))
            
            logger.warning(f"SoC key 'B_left_cap1' not found in API response.")
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
    
    logger.info(f"Solar Bridge Operational. Polling: {POLL_INTERVAL}s")

    try:
        while True:
            current_soc = solarman.get_battery_soc()
            now = datetime.now()

            if current_soc is not None:
                # Update logic: Only push if value changed OR heartbeat interval reached
                seconds_since_last = (now - last_update_time).total_seconds()
                needs_update = (current_soc != last_sent_soc) or (seconds_since_last >= FORCE_UPDATE_INTERVAL)

                if needs_update:
                    reason = "Change" if current_soc != last_sent_soc else "Heartbeat"
                    logger.info(f"Pushing SoC {current_soc}% to Alexa ({reason})")
                    
                    # Push to SinricPro (Using SoC for both Temp/Humidity for UI visibility)
                    success = await battery_device.send_temperature_event(current_soc, current_soc)
                    
                    if success:
                        last_sent_soc = current_soc
                        last_update_time = now
                        
                        # Ping Healthchecks.io if configured
                        if HEALTH_URL:
                            try:
                                requests.get(HEALTH_URL, timeout=5)
                            except Exception as e:
                                logger.debug(f"Healthcheck ping failed: {e}")
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
            await asyncio.gather(sinric_task, return_exceptions=True)
        except Exception:
            pass
        logger.info("Bridge stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
