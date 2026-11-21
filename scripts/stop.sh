#!/usr/bin/env bash
# Cleanly stop the Solar Battery Alexa Bridge watchdog and child process.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
PID_FILE="$LOG_DIR/watchdog.pid"
BRIDGE_PID_FILE="$LOG_DIR/bridge.pid"

stop_pid_file() {
    local file="$1"
    local label="$2"

    if [ ! -f "$file" ]; then
        return 0
    fi

    local pid
    pid="$(cat "$file" 2>/dev/null || true)"
    if [ -z "$pid" ]; then
        rm -f "$file"
        return 0
    fi

    if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping $label (PID $pid)..."
        kill -TERM "$pid" 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "$label did not stop gracefully; sending SIGKILL..."
            kill -KILL "$pid" 2>/dev/null || true
        fi
    fi

    rm -f "$file"
}

if [ ! -f "$PID_FILE" ] && [ ! -f "$BRIDGE_PID_FILE" ]; then
    echo "Solar Battery Alexa Bridge does not appear to be running."
    exit 0
fi

stop_pid_file "$PID_FILE" "watchdog"
stop_pid_file "$BRIDGE_PID_FILE" "bridge"

if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock >/dev/null 2>&1 || true
fi

echo "Solar Battery Alexa Bridge stopped."
