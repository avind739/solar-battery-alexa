#!/usr/bin/env bash
# Termux-safe supervisor for Solar Battery Alexa Bridge.
# Exit code contract:
#   0  = intentional stop (exit watchdog)
#   42 = scheduled clean recycle (fast 5s restart)
#   *  = error / extended disconnect (exponential backoff restart)

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
WATCHDOG_LOG="$LOG_DIR/watchdog.log"
PID_FILE="$LOG_DIR/watchdog.pid"
BRIDGE_PID_FILE="$LOG_DIR/bridge.pid"

mkdir -p "$LOG_DIR"

log() {
    printf '%s [watchdog] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$WATCHDOG_LOG"
}

# Single-instance guard
if [ -f "$PID_FILE" ]; then
    EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$EXISTING_PID" ] && [ "$EXISTING_PID" != "$$" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        log "Watchdog already running (PID $EXISTING_PID). Exiting duplicate instance."
        exit 0
    fi
fi

echo "$$" > "$PID_FILE"

WAKELOCK_ACQUIRED=0
if command -v termux-wake-lock >/dev/null 2>&1; then
    if termux-wake-lock >/dev/null 2>&1; then
        WAKELOCK_ACQUIRED=1
        log "Acquired Termux wakelock."
    fi
fi

CHILD_PID=""

cleanup() {
    if [ -n "$CHILD_PID" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
        log "Stopping bridge process (PID $CHILD_PID)..."
        kill -TERM "$CHILD_PID" 2>/dev/null || true
        wait "$CHILD_PID" 2>/dev/null || true
    fi
    rm -f "$BRIDGE_PID_FILE"
    if [ -f "$PID_FILE" ] && [ "$(cat "$PID_FILE" 2>/dev/null || true)" = "$$" ]; then
        rm -f "$PID_FILE"
    fi
    if [ "$WAKELOCK_ACQUIRED" -eq 1 ] && command -v termux-wake-unlock >/dev/null 2>&1; then
        termux-wake-unlock >/dev/null 2>&1 || true
        log "Released Termux wakelock."
    fi
}

handle_signal() {
    log "Received stop signal. Shutting down watchdog..."
    exit 0
}

trap cleanup EXIT
trap handle_signal INT TERM

# Resolve Python interpreter
if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
else
    log "ERROR: Python interpreter not found."
    exit 1
fi

cd "$PROJECT_ROOT" || exit 1
log "Watchdog started (PID $$, python=$PYTHON_BIN)."

BACKOFF=30
MAX_BACKOFF=300

while true; do
    if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        START_TS="$(date +%s)"
        log "Internet OK. Starting Solar Bridge..."

        PYTHONPATH="$PROJECT_ROOT/src" "$PYTHON_BIN" -m solar_bridge "$@" >> "$WATCHDOG_LOG" 2>&1 &
        CHILD_PID=$!
        echo "$CHILD_PID" > "$BRIDGE_PID_FILE"

        wait "$CHILD_PID"
        EXIT_CODE=$?
        CHILD_PID=""
        rm -f "$BRIDGE_PID_FILE"

        END_TS="$(date +%s)"
        UPTIME=$((END_TS - START_TS))

        if [ "$EXIT_CODE" -eq 0 ]; then
            log "Bridge exited cleanly (code 0). Stopping watchdog."
            break
        elif [ "$EXIT_CODE" -eq 42 ]; then
            log "Scheduled clean recycle (code 42, uptime=${UPTIME}s). Restarting in 5s..."
            BACKOFF=30
            sleep 5
        else
            if [ "$UPTIME" -ge 120 ]; then
                BACKOFF=30
            fi
            log "Bridge exited with code $EXIT_CODE (uptime=${UPTIME}s). Restarting in ${BACKOFF}s..."
            sleep "$BACKOFF"
            BACKOFF=$((BACKOFF * 2))
            if [ "$BACKOFF" -gt "$MAX_BACKOFF" ]; then
                BACKOFF=$MAX_BACKOFF
            fi
        fi
    else
        log "No internet connectivity. Retrying in 60s..."
        sleep 60
    fi
done
