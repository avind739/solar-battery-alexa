# Solar Battery Alexa Bridge (Deye / Solarman)

A 100% free, lightweight Python bridge that polls the real-time State of Charge (SoC) of your Deye/Sunsynk solar battery from the **Solarman Global API** and pushes it to **Amazon Alexa** via a **SinricPro** virtual Thermostat device.

Designed to run 24/7 on an old Android phone via **Termux** (or any Raspberry Pi / Linux server).

---

## Features
- **Zero Cost:** No monthly subscriptions (uses SinricPro free tier + Alexa Routines).
- **Voice Enabled:** Ask *"Alexa, what is my solar battery?"*
- **Resilient Long-Running Operation:**
  - Automatically refreshes expired Solarman tokens (handles HTTP 401/403, HTTP 200 `success: false`, and proactive TTL refresh).
  - Runs HTTP calls off the `asyncio` event loop (`asyncio.to_thread`) so SinricPro WebSocket heartbeats never stall.
  - Detects silent Wi-Fi/NAT disconnects quickly, exits cleanly for watchdog recovery, and performs a scheduled clean recycle every 12 hours (`exit 42`).
- **One-Command Termux Auto-Start:** Configures `Termux:Boot` (phone reboot), `~/.bashrc` (Termux open), `termux-wake-lock`, and single-instance PID locking.
- **Safe Credential Isolation:** Stores credentials outside the git repo at `~/.config/solar-battery-alexa/.env` (`chmod 600`) and supports `SOLARMAN_PASSWORD_HASH` (no plaintext inverter password on the phone).
- **Observability:** Rotating logs (`logs/bridge.log`, `logs/watchdog.log`), atomic `status.json`, and optional Healthchecks.io dead-man's-switch pings.

---

## Project Structure

```text
solar-battery-alexa/
├── .github/workflows/ci.yml        # CI: ruff, pyright, pytest, shellcheck
├── docs/
│   ├── system-design.md            # High-level architecture, data flow, failure matrix
│   └── adr/                        # Architecture Decision Records
├── scripts/
│   ├── setup_termux.sh             # One-command Termux installer & auto-start setup
│   ├── start.sh                    # Starts watchdog & bridge in the background
│   ├── watchdog.sh                 # PID-locked supervisor with wakelock & backoff
│   └── stop.sh                     # Cleanly stops watchdog & bridge
├── src/
│   ├── solar_bridge/               # Modular core package (config, solarman, bridge, cli)
│   ├── battery_soc.py              # Backwards-compatible entrypoint shim
│   └── battery_test.py             # Interactive Alexa simulator
├── tests/                          # 100% offline automated unit tests
├── AGENTS.md                       # AI coding agent instructions & TDD workflow
├── Makefile                        # Single-command lint, typecheck, test, shellcheck
├── pyproject.toml                  # Packaging, runtime/dev deps, tool config
└── requirements.txt                # Pure-Python runtime deps for Termux
```

See [docs/system-design.md](docs/system-design.md) and [docs/adr/README.md](docs/adr/README.md) for architectural details.

---

## Prerequisites

1. **Solarman API Account:** Email `service@solarmanpv.com` to request your `App ID` and `App Secret` (include your inverter serial number).
2. **SinricPro Account:** Create a free account at [sinric.pro](https://sinric.pro) and add a **Thermostat** device named `Solar Battery`.
3. **Android Phone with Termux:** Install [Termux](https://f-droid.org/en/packages/com.termux/) and [Termux:Boot](https://f-droid.org/en/packages/com.termux.boot/) from **F-Droid** (not Google Play).
4. **Monitoring (Optional):** Create a free check at [Healthchecks.io](https://healthchecks.io) to receive alerts if the phone goes offline.

---

## Quick Start on Android (Termux)

```bash
pkg update && pkg install -y git python
git clone https://github.com/yourusername/solar-battery-alexa.git
cd solar-battery-alexa
./scripts/setup_termux.sh
```

`setup_termux.sh` is idempotent and will:
1. Install lightweight pure-Python runtime dependencies from `requirements.txt`.
2. Preserve `~/.config/solar-battery-alexa/.env` if it already exists, or interactively prompt for your keys (automatically SHA-256 hashing your Solarman password into `SOLARMAN_PASSWORD_HASH` and setting `chmod 600`).
3. Install a **Termux:Boot** hook at `~/.termux/boot/start-solar-bridge.sh` (auto-starts on phone reboot).
4. Add an idempotent auto-start block to `~/.bashrc` (auto-starts when opening Termux without spawning duplicates).
5. Start `scripts/watchdog.sh` immediately in the background with `termux-wake-lock`.

### Android Settings Checklist
- Open **Termux:Boot** once after installing it so Android registers its boot receiver.
- In **Android Settings -> Battery**, set both **Termux** and **Termux:Boot** to **Unrestricted** (disable battery optimization).
- **Direct Boot note:** If the phone has a screen lock PIN, Android encrypts Termux's home directory until the first unlock after a reboot.

---

## Managing Credentials Safely

The bridge resolves `.env` in this priority order:
1. `--env-file /path/to/.env` (or `SOLAR_BRIDGE_ENV` env var)
2. `~/.config/solar-battery-alexa/.env` *(recommended on Termux — survives re-clones and stays inside Termux's private sandbox)*
3. `./.env` *(convenient fallback for local development)*

### Transferring `.env` from Mac/PC via Termux SSH (No Phone Typing)
On the phone (Termux):
```bash
pkg install -y openssh
sshd
```
From your Mac/PC on the same Wi-Fi:
```bash
ssh -p 8022 <termux-user>@<phone-ip> 'mkdir -p ~/.config/solar-battery-alexa && chmod 700 ~/.config/solar-battery-alexa'
scp -P 8022 .env <termux-user>@<phone-ip>:~/.config/solar-battery-alexa/.env
ssh -p 8022 <termux-user>@<phone-ip> 'chmod 600 ~/.config/solar-battery-alexa/.env'
```

### Generating `SOLARMAN_PASSWORD_HASH`
Solarman only needs the SHA-256 digest of your password. Generate it locally so your plaintext password never sits on the phone:
```bash
PYTHONPATH=src python -m solar_bridge --hash-password
```

---

## CLI Usage & Operations

```bash
# Validate configuration without hitting external APIs
PYTHONPATH=src python -m solar_bridge --check-config

# Fetch SoC from Solarman once without connecting/pushing to SinricPro
PYTHONPATH=src python -m solar_bridge --dry-run

# Run a single live poll/push cycle and exit cleanly
PYTHONPATH=src python -m solar_bridge --once

# Interactive Alexa simulator
python src/battery_test.py

# Backwards-compatible entrypoint
python src/battery_soc.py

# Monitor logs & status on the phone
tail -f logs/watchdog.log logs/bridge.log
cat status.json

# Start / stop / restart cleanly in the background
./scripts/start.sh
./scripts/stop.sh
./scripts/stop.sh && ./scripts/start.sh
```

---

## Alexa Voice Configuration
Because SinricPro uses a virtual Thermostat to represent the battery, Alexa natively says *"The Solar Battery is 85 degrees."* Create a **Routine** in the Alexa App:
1. **New Routine:** Name it `Solar SoC`.
2. **When this happens:** Voice -> *"Alexa, what is my solar battery?"*
3. **Add Action:** Alexa Says -> Customized -> *"The battery is currently at [Solar Battery] temperature percent."*

---

## Local Development & Verification

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Run full verification suite (ruff + pyright + pytest + shell syntax)
make check
```
