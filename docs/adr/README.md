# Architecture Decision Records (ADRs)

This folder records significant architectural decisions for `solar-battery-alexa`, including the context, chosen approach, and consequences.

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-persistent-websocket-with-recycle.md) | Persistent SinricPro WebSocket with Periodic Clean Recycle | Accepted |
| [0002](0002-external-config-and-password-hash.md) | External Credential Storage and Hashed Solarman Password | Accepted |
| [0003](0003-termux-autostart-and-watchdog.md) | Termux Auto-Start and PID-Locked Watchdog Supervision | Accepted |
| [0004](0004-modular-agent-friendly-architecture.md) | Modular Package Layout and Offline Agent-Friendly Tooling | Accepted |

## Adding a New ADR
Create `docs/adr/NNNN-short-title.md` with:
- **Status** (`Proposed` / `Accepted` / `Superseded`)
- **Context** (what problem or constraint drove the decision)
- **Decision** (what we chose to do)
- **Consequences** (benefits, tradeoffs, and operational notes)
