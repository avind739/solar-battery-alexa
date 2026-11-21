# ADR 0003: Termux Auto-Start and PID-Locked Watchdog Supervision

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
Cloning the repository on Android/Termux previously did not auto-start the bridge, and `scripts/watchdog.sh` had several Termux incompatibilities:
- Used `#!/bin/bash`, which does not exist in Termux (`$PREFIX/bin/bash` is used instead).
- Was not committed with executable (`+x`) permissions.
- Did not acquire `termux-wake-lock`, so Android Doze could suspend the process.
- Had no single-instance lock, so launching from multiple Termux sessions or boot hooks could spawn duplicate bridges.
- Did not distinguish intentional stops, clean scheduled recycles, and unexpected crashes.

## Decision
1. **Standardize all shell scripts on `#!/usr/bin/env bash`** with executable (`+x`) git permissions and shell validation (`bash -n` / `shellcheck`).
2. **Upgrade `scripts/watchdog.sh`** to:
   - Enforce a single running instance using `logs/watchdog.pid` (with stale-PID cleanup).
   - Automatically call `termux-wake-lock` when available on Termux (and release on clean exit).
   - Resolve Python automatically (`.venv/bin/python` -> `python3` -> `python`).
   - Honor the exit-code contract (`0` = stop, `42` = 5s recycle restart, other = backoff restart) and log to `logs/watchdog.log`.
3. **Provide an idempotent `scripts/setup_termux.sh`** that installs runtime dependencies, initializes/preserves `~/.config/solar-battery-alexa/.env`, installs `~/.termux/boot/start-solar-bridge.sh` (for `Termux:Boot`), adds an idempotent auto-start guard to `~/.bashrc`, and starts the watchdog immediately.
4. **Provide `scripts/stop.sh`** to stop the watchdog and bridge cleanly.

## Consequences
- **Pros:** One command after `git clone` configures boot startup, Termux launch startup, credentials, and background supervision; zero duplicate processes; survives screen-off on Android.
- **Cons:** Reboot auto-start requires installing the `Termux:Boot` add-on app (from F-Droid) and disabling Android battery optimization for both Termux and Termux:Boot.
