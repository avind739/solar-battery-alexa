# ADR 0001: Persistent SinricPro WebSocket with Periodic Clean Recycle

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
Over long-running sessions on an Android/Termux phone, the original bridge experienced SinricPro WebSocket timeouts, expired Solarman tokens, and stalled recovery. Moving to a pure scheduled one-shot job (cron: connect -> push SoC -> exit) was considered so every run would start with fresh tokens and sockets.

However:
1. **Alexa + SinricPro requires an active WebSocket.** When a device disconnects from SinricPro, SinricPro marks it offline and Alexa voice queries commonly fail with *"device is not responding"*.
2. **The `sinricpro` Python SDK (`5.3.1`) has reconnection limitations:**
   - Its built-in ping runs only every 5 minutes (3 missed pongs = 15 minutes to notice a dead socket).
   - Its `_reconnect()` method attempts to reconnect only **once** after 5 seconds; if Wi-Fi is still down, it gives up permanently.
3. **Solarman API token expiry** often returns HTTP `200` with `{"success": false}` rather than HTTP `401`, which the previous client missed.
4. **Blocking `requests` calls** on the `asyncio` event loop could freeze event loop heartbeats longer than the 10-second pong timeout.

## Decision
1. **Maintain a persistent SinricPro WebSocket** so Alexa voice queries work on demand.
2. **Offload all blocking HTTP calls** (`SolarmanClient`, Healthchecks.io) to worker threads via `asyncio.to_thread(...)`.
3. **Actively monitor connection health** on a short tick (`30s` default) with periodic keepalive pings (`60s` default) and fail fast (`MAX_OFFLINE_SECONDS=120`) via a timeout-bounded `sinric.stop()`.
4. **Refresh Solarman tokens properly** on HTTP `401`/`403`, JSON `success: false`, and proactively after `TOKEN_REFRESH_HOURS` (`12h` default).
5. **Perform a scheduled clean recycle** every `RECYCLE_INTERVAL_HOURS` (`12h` default), exiting with code `42` so `watchdog.sh` starts a fresh Python process, WebSocket, and Solarman token after a 5-second pause.

## Consequences
- **Pros:** Alexa sees the device online >99.9% of the time; silent NAT/Wi-Fi drops recover within ~2 minutes instead of >1 hour; periodic recycling prevents long-lived session drift while avoiding cron offline gaps.
- **Cons:** Brief (~5–10s) reconnect window every 12 hours; requires `watchdog.sh` to supervise the process and honor exit code `42`.
