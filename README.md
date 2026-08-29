# Solar Battery Alexa Bridge (Deye/Solarman)

A 100% free, lightweight Python bridge that enables you to ask Alexa for the real-time State of Charge (SoC) of your Deye/Sunsynk solar battery. 

This project is designed to run on low-power, always-on hardware like an old Android phone (via Termux), a Raspberry Pi, or any home server.

## 🚀 Features
- **Zero Cost:** No monthly subscriptions (No Nabu Casa or IFTTT Pro required).
- **Voice Enabled:** Ask "Alexa, what is the battery level of Solar Battery?"
- **Low Power:** Optimized for Android/Termux; uses minimal CPU and data.
- **Self-Healing:** includes a watchdog shell script to auto-restart the bridge if it crashes.
- **Downtime Alerts:** Integrated with Healthchecks.io to notify you if your home "server" goes offline.

## 📁 Project Structure
```text
solar-battery-alexa/
├── .env                  # Your private credentials (Hidden)
├── .env.example          # Template for credentials
├── .gitignore            # Git exclusion rules
├── README.md             # Project documentation
├── requirements.txt      # Python dependencies
├── scripts/
│   └── watchdog.sh       # Auto-restart wrapper
└── src/
    ├── battery_soc.py    # Main production bridge
    └── battery_test.py   # Simulation/Testing tool
```

## 🛠 Prerequisites

1.  **Solarman API Account:** Email `service@solarmanpv.com` to request your `App ID` and `App Secret`. (Include your inverter serial number in the email).
2.  **SinricPro Account:** Create a free account at [sinric.pro](https://sinric.pro). Add a **Thermostat** device named "Solar Battery".
3.  **Hardware:** An Android phone with [Termux](https://f-droid.org/en/packages/com.termux/) or a Linux server (Raspberry Pi, etc.).
4.  **Monitoring (Optional):** Create a free check at [Healthchecks.io](https://healthchecks.io) to receive email alerts if the script stops.

## 📥 Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/solar-battery-alexa.git
    cd solar-battery-alexa
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment:**
    Copy the example configuration and fill in your specific keys:
    ```bash
    cp .env.example .env
    nano .env
    ```

## ⚙️ Configuration (.env)
Edit your `.env` file with the following keys:
- `SINRIC_APP_KEY`: From SinricPro Credentials tab.
- `SINRIC_APP_SECRET`: From SinricPro Credentials tab.
- `SINRIC_DEVICE_ID`: The ID of your "Solar Battery" device.
- `SOLARMAN_APP_ID`: Your Solarman API ID.
- `SOLARMAN_APP_SECRET`: Your Solarman API Secret.
- `SOLARMAN_EMAIL`: Your Solarman login email.
- `SOLARMAN_PASSWORD`: Your Solarman login password.
- `INVERTER_SN`: Your Inverter Serial Number.
- `HEALTHCHECKS_URL`: (Optional) Your unique ping URL from Healthchecks.io.

## 🚀 Usage

### 1. Verification
Test the connection to Alexa by running the simulation tool:
```bash
python src/battery_test.py
```
Type a number (0-100) and check if your Alexa App updates the "Solar Battery" temperature.

### 2. Production
Run the bridge with the **Watchdog** script. This ensures that if the Python script crashes due to a network error, it will automatically restart within 10 seconds.
```bash
chmod +x scripts/watchdog.sh
./scripts/watchdog.sh
```

## 🗣 Alexa Voice Configuration
Because SinricPro uses a virtual Thermostat to represent the battery, Alexa will natively say "The Solar Battery is 85 degrees." To fix this, create a **Routine** in the Alexa App:

1.  **New Routine:** Name it "Solar SoC".
2.  **When this happens:** Voice -> "Alexa, what is my solar battery?"
3.  **Add Action:** Alexa Says -> Customized -> "The battery is currently at [Solar Battery] temperature percent."

## 🛡 Security & Maintenance
- **File Permissions:** Run `chmod 600 .env` to ensure other users on your device cannot read your API keys.
- **Git Safety:** The `.gitignore` file is configured to prevent your `.env` from ever being uploaded to a public repository.
- **Android Tip:** In Termux, pull down the notification bar and select **"Acquire Wakelock"** to prevent Android from killing the script when the screen is off.

## 🤝 Contributing
Contributions are welcome! If you have a different inverter brand (Sunsynk, Victron, etc.), feel free to submit a Pull Request with the corresponding data key mappings.
