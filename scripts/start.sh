#!/usr/bin/env bash
# Start the Solar Battery Alexa Bridge watchdog in the background.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
PID_FILE="$LOG_DIR/watchdog.pid"

mkdir -p "$LOG_DIR"

if [ -f "$PID_FILE" ]; then
    EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "Solar Battery Alexa Bridge is already running (watchdog PID $EXISTING_PID)."
        exit 0
    fi
fi

nohup "$PROJECT_ROOT/scripts/watchdog.sh" "$@" >/dev/null 2>&1 &
sleep 1

if [ -f "$PID_FILE" ]; then
    NEW_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$NEW_PID" ] && kill -0 "$NEW_PID" 2>/dev/null; then
        echo "Solar Battery Alexa Bridge started (watchdog PID $NEW_PID)."
        echo "Logs: tail -f $LOG_DIR/watchdog.log"
        exit 0
    fi
fi

echo "Watchdog launched; check $LOG_DIR/watchdog.log for status."
