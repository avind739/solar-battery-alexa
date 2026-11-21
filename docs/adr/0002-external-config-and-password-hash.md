# ADR 0002: External Credential Storage and Hashed Solarman Password

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
Storing `.env` inside the cloned git repository on an Android phone causes two issues:
1. Deleting and re-cloning the repository wipes `.env`, forcing manual re-entry of 9 credentials on a mobile keyboard.
2. Keeping secrets inside the working tree increases the risk of accidental exposure when sharing archives or running coding agents.

Additionally, the Solarman API only accepts the SHA-256 hex digest of the user's password, meaning storing the plaintext `SOLARMAN_PASSWORD` on the phone is unnecessary.

## Decision
1. **Resolve `.env` outside the repository by default on Termux:**
   - Priority 1: Explicit `--env-file` CLI flag or `SOLAR_BRIDGE_ENV` environment variable.
   - Priority 2: `~/.config/solar-battery-alexa/.env` (inside Termux's private Android app sandbox, `chmod 700` dir / `chmod 600` file).
   - Priority 3: `./.env` in the current working directory (convenient fallback for local development).
2. **Support `SOLARMAN_PASSWORD_HASH`** (SHA-256 hex digest) as the preferred credential, while keeping `SOLARMAN_PASSWORD` supported for backwards compatibility. Provide `python -m solar_bridge --hash-password` and hash automatically in `scripts/setup_termux.sh`.
3. **Never store credentials in Android shared storage** (`/sdcard/` or `~/storage/shared/`), which is accessible to other apps.

## Consequences
- **Pros:** Re-cloning or resetting the repository never loses credentials; plaintext Solarman passwords never need to exist on the phone; `.env` stays isolated inside Termux's private UID sandbox.
- **Cons:** Users transferring `.env` from a computer should copy it to `~/.config/solar-battery-alexa/.env` (e.g., via `scp` over Termux SSH) or run `scripts/setup_termux.sh`.
- **Android caveat:** When a screen lock PIN is configured, Android File-Based Encryption prevents `Termux:Boot` from reading `$HOME` until the device is unlocked once after a reboot.
