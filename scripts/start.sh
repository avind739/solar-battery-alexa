#!/usr/bin/env bash
# Start the Solar Battery Alexa Bridge watchdog in the background.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
WATCHDOG_LOG="$LOG_DIR/watchdog.log"
PID_FILE="$LOG_DIR/watchdog.pid"

mkdir -p "$LOG_DIR"

if [ -f "$PID_FILE" ]; then
    EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "Solar Battery Alexa Bridge is already running (watchdog PID $EXISTING_PID)."
        exit 0
    fi
fi

# Launch via explicit bash with stdin closed (SSH-safe) and capture any startup errors in watchdog.log
nohup bash "$PROJECT_ROOT/scripts/watchdog.sh" "$@" </dev/null >> "$WATCHDOG_LOG" 2>&1 &
LAUNCHER_PID=$!
disown "$LAUNCHER_PID" 2>/dev/null || true

for _ in 1 2 3 4 5 6; do
    if [ -f "$PID_FILE" ]; then
        NEW_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
        if [ -n "$NEW_PID" ] && kill -0 "$NEW_PID" 2>/dev/null; then
            echo "Solar Battery Alexa Bridge started (watchdog PID $NEW_PID)."
            echo "Logs: tail -f $WATCHDOG_LOG $LOG_DIR/bridge.log"
            exit 0
        fi
    fi
    sleep 0.5
done

echo "WARNING: Watchdog did not stay running. Recent log output:" >&2
tail -n 20 "$WATCHDOG_LOG" 2>/dev/null || echo "(no log file created at $WATCHDOG_LOG)" >&2
exit 1
