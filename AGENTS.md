# AGENTS.md

Instructions for AI coding agents working in `solar-battery-alexa`.

## 1. Project Summary
A lightweight Python bridge that polls a Deye/Sunsynk solar inverter's battery State of Charge (SoC) from the **Solarman Global API** and pushes it to **Amazon Alexa** via a **SinricPro** virtual Thermostat device.

- **Primary target runtime:** Always-on Android phone running **Termux** (ARM Linux, no root, no `systemd`).
- **Secondary runtime:** macOS / standard Linux (development & testing).

Read [`docs/system-design.md`](docs/system-design.md) and [`docs/adr/README.md`](docs/adr/README.md) before making architectural changes.

---

## 2. Testing & Red-Green Workflow
- For new business logic, follow strict Red-Green-Refactor unless told otherwise.
- **Step 1 (RED):** Write tests first, run tests, and pause to show the failing output for user review. Do NOT write implementation code yet.
- **Step 2 (GREEN):** After user approval of the tests, implement the minimum clean code needed to pass tests. Never weaken or delete test assertions to make a test pass without asking first.
- **Step 3 (REFACTOR):** If code is in Python, clean up code, run `ruff check .` and `pyright`, and confirm `pytest` remains green. Do the same or equivalent for code in any other language (e.g., `bash -n scripts/*.sh` and `shellcheck scripts/*.sh` for shell scripts).

---

## 3. Repository Map
- `src/solar_bridge/config.py` — Typed config loader (`--env-file` -> `~/.config/solar-battery-alexa/.env` -> `./.env`).
- `src/solar_bridge/solarman.py` — Solarman REST API client & token refresh logic.
- `src/solar_bridge/bridge.py` — Async SinricPro WebSocket bridge, polling loop, keepalive, recycle, `status.json`.
- `src/solar_bridge/cli.py` — CLI flags, logging setup, exit code mapping.
- `src/battery_soc.py` — Backwards-compatible entrypoint shim (`python src/battery_soc.py`).
- `src/battery_test.py` — Manual interactive Alexa simulator.
- `scripts/watchdog.sh` — Termux-safe supervisor (PID lock, `termux-wake-lock`, backoff, logs).
- `scripts/setup_termux.sh` — Idempotent Termux installer (`Termux:Boot`, `~/.bashrc`, `~/.config/.../.env`).
- `scripts/stop.sh` — Stops running watchdog and bridge cleanly.
- `tests/` — Offline unit tests (`pytest` + `pytest-asyncio`).
- `docs/` — System design and Architecture Decision Records (ADRs).

---

## 4. Non-Negotiable Invariants

### SinricPro & Alexa
- **Do NOT convert the bridge into a pure cron / connect-push-exit job.** SinricPro marks disconnected devices as offline, causing Alexa to respond "device is not responding". Keep the persistent WebSocket and rely on periodic clean recycle (`RECYCLE_INTERVAL_HOURS`, exit code `42`). See `docs/adr/0001-persistent-websocket-with-recycle.md`.
- **Do NOT assume `sinricpro` will reconnect indefinitely.** The SDK's `_reconnect()` only retries once after 5s and then gives up. Health checks + fast exit on extended disconnect (`MAX_OFFLINE_SECONDS`) are required so `watchdog.sh` starts a clean process.
- **Always shut down with `await asyncio.wait_for(sinric.stop(), timeout=...)`.** Calling `cancel()` on `sinric.begin()` does not stop internal SDK tasks.

### Solarman API & Async Loop
- **Never block the `asyncio` event loop** with synchronous `requests` calls. Always offload HTTP calls (`SolarmanClient`, Healthchecks.io) via `asyncio.to_thread(...)`.
- **Handle HTTP 200 expired-token responses.** Solarman frequently returns HTTP `200` with `{"success": false, ...}` instead of HTTP `401` when a token expires. Refresh on HTTP `401`/`403`, JSON `success: false`, and token TTL (`TOKEN_REFRESH_HOURS`).

### Termux Portability
- **Never use `#!/bin/bash` in `scripts/*.sh`.** `/bin/bash` does not exist on Termux; always use `#!/usr/bin/env bash` and commit scripts with executable (`+x`) permissions.
- **Keep runtime dependencies pure Python** in `requirements.txt` and `[project.dependencies]` (`requests`, `python-dotenv`, `sinricpro`). Avoid runtime deps requiring C/Rust builds on Android ARM. Dev tools (`pytest`, `pytest-asyncio`, `ruff`, `pyright`) belong strictly in `[project.optional-dependencies] dev`.
- **Preserve the watchdog exit-code contract:**
  - `0` = intentional stop (do not restart)
  - `42` = scheduled clean recycle (fast 5s restart)
  - any other non-zero = error/disconnect (backoff restart)

### Module Purity
- **No import-time side effects.** Importing modules under `src/solar_bridge/` must never read `.env`, touch the network, configure global logging, or call `sys.exit()`.

---

## 5. Security & Credential Rules
- **Never read, print, log, or commit `.env`** or any real API keys, tokens, or passwords.
- Prefer `SOLARMAN_PASSWORD_HASH` (SHA-256 hex digest) over plaintext `SOLARMAN_PASSWORD` in docs and setup scripts.
- Ensure error logs and `status.json` never leak bearer tokens, app secrets, or passwords.
- All automated tests must run **100% offline** with mocked HTTP/WebSocket layers — never call live Solarman, SinricPro, or Healthchecks endpoints in tests.

---

## 6. Verification Commands

Run these before finishing any change:

```bash
# Full check (ruff + pyright + pytest + shell syntax)
make check

# Individual commands
make test        # Runs pytest
make lint        # Runs ruff check .
make typecheck   # Runs pyright
bash -n scripts/watchdog.sh scripts/setup_termux.sh scripts/stop.sh
```

If `shellcheck` is installed:
```bash
shellcheck scripts/*.sh
```

Safe offline CLI smoke checks (do not require live credentials when pointed at a mock/temp env):
```bash
PYTHONPATH=src .venv/bin/python -m solar_bridge --help
PYTHONPATH=src .venv/bin/python -m solar_bridge --env-file /tmp/mock.env --check-config
```

---

## 7. Contribution & Documentation Conventions
- Add or update offline tests under `tests/` for every bug fix or behavior change.
- Keep `requirements.txt` in sync with `pyproject.toml` `[project.dependencies]`.
- Keep `src/battery_soc.py` working as a backwards-compatible entrypoint.
- If you change an architectural invariant, exit-code contract, or runtime model, update `docs/system-design.md` and add a new numbered ADR under `docs/adr/`.
