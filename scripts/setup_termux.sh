#!/usr/bin/env bash
# Idempotent one-command Termux installer for Solar Battery Alexa Bridge.
# - Installs Python runtime dependencies
# - Preserves or creates ~/.config/solar-battery-alexa/.env (chmod 600)
# - Configures Termux:Boot (~/.termux/boot/start-solar-bridge.sh)
# - Configures idempotent ~/.bashrc auto-start guard
# - Launches watchdog.sh in the background

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_DIR="${HOME}/.config/solar-battery-alexa"
ENV_FILE="${CONFIG_DIR}/.env"
BOOT_DIR="${HOME}/.termux/boot"
BOOT_SCRIPT="${BOOT_DIR}/start-solar-bridge.sh"
BASHRC="${HOME}/.bashrc"

echo "=== Solar Battery Alexa Bridge: Termux Setup ==="
echo "Project directory: $PROJECT_ROOT"

# 1. Ensure scripts are executable
chmod +x "$PROJECT_ROOT/scripts/watchdog.sh" "$PROJECT_ROOT/scripts/stop.sh" "$PROJECT_ROOT/scripts/setup_termux.sh"

# 2. Resolve Python & install pure-Python runtime dependencies
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
else
    echo "ERROR: Python is not installed. Run: pkg install python" >&2
    exit 1
fi

echo "Installing runtime dependencies..."
"$PYTHON_BIN" -m pip install --upgrade -r "$PROJECT_ROOT/requirements.txt"

# 3. Set up credentials outside the git repo (~/.config/solar-battery-alexa/.env)
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

if [ -f "$ENV_FILE" ]; then
    echo "Found existing credentials at $ENV_FILE (leaving untouched)."
    chmod 600 "$ENV_FILE"
elif [ -f "$PROJECT_ROOT/.env" ]; then
    echo "Copying existing repo .env to $ENV_FILE..."
    cp "$PROJECT_ROOT/.env" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "Tip: You can now remove $PROJECT_ROOT/.env so credentials live only in $ENV_FILE."
else
    echo ""
    echo "No credentials found at $ENV_FILE. Let's configure them now."
    echo "(Your Solarman password will be SHA-256 hashed and never stored in plaintext.)"
    echo ""

    read -r -p "SINRIC_APP_KEY: " SINRIC_APP_KEY
    read -r -s -p "SINRIC_APP_SECRET (hidden): " SINRIC_APP_SECRET
    echo ""
    read -r -p "SINRIC_DEVICE_ID: " SINRIC_DEVICE_ID
    read -r -p "SOLARMAN_APP_ID: " SOLARMAN_APP_ID
    read -r -s -p "SOLARMAN_APP_SECRET (hidden): " SOLARMAN_APP_SECRET
    echo ""
    read -r -p "SOLARMAN_EMAIL: " SOLARMAN_EMAIL
    read -r -s -p "SOLARMAN_PASSWORD (hidden, will be SHA-256 hashed): " SOLARMAN_PASSWORD_RAW
    echo ""
    read -r -p "INVERTER_SN: " INVERTER_SN
    read -r -p "HEALTHCHECKS_URL (optional, press Enter to skip): " HEALTHCHECKS_URL

    SOLARMAN_PASSWORD_HASH="$(
        SOLARMAN_PASSWORD_RAW="$SOLARMAN_PASSWORD_RAW" "$PYTHON_BIN" -c \
            'import hashlib, os; print(hashlib.sha256(os.environ["SOLARMAN_PASSWORD_RAW"].encode("utf-8")).hexdigest())'
    )"
    unset SOLARMAN_PASSWORD_RAW

    umask 077
    cat > "$ENV_FILE" <<EOF
SINRIC_APP_KEY=${SINRIC_APP_KEY}
SINRIC_APP_SECRET=${SINRIC_APP_SECRET}
SINRIC_DEVICE_ID=${SINRIC_DEVICE_ID}
SOLARMAN_APP_ID=${SOLARMAN_APP_ID}
SOLARMAN_APP_SECRET=${SOLARMAN_APP_SECRET}
SOLARMAN_EMAIL=${SOLARMAN_EMAIL}
SOLARMAN_PASSWORD_HASH=${SOLARMAN_PASSWORD_HASH}
INVERTER_SN=${INVERTER_SN}
HEALTHCHECKS_URL=${HEALTHCHECKS_URL}
LOG_FILE=${PROJECT_ROOT}/logs/bridge.log
STATUS_FILE=${PROJECT_ROOT}/status.json
EOF
    chmod 600 "$ENV_FILE"
    echo "Saved credentials securely to $ENV_FILE (chmod 600)."
fi

# 4. Validate configuration offline
echo "Validating configuration..."
PYTHONPATH="$PROJECT_ROOT/src" "$PYTHON_BIN" -m solar_bridge --env-file "$ENV_FILE" --check-config

# 5. Configure Termux:Boot auto-start (on phone reboot)
mkdir -p "$BOOT_DIR"
cat > "$BOOT_SCRIPT" <<EOF
#!/usr/bin/env bash
termux-wake-lock >/dev/null 2>&1 || true
nohup "${PROJECT_ROOT}/scripts/watchdog.sh" >/dev/null 2>&1 &
EOF
chmod +x "$BOOT_SCRIPT"
echo "Installed Termux:Boot script at $BOOT_SCRIPT"

# 6. Configure idempotent ~/.bashrc auto-start (when opening Termux)
touch "$BASHRC"
MARKER_START="# >>> solar-battery-alexa >>>"
MARKER_END="# <<< solar-battery-alexa <<<"

if grep -qF "$MARKER_START" "$BASHRC"; then
    # Remove old managed block before writing updated path
    awk -v s="$MARKER_START" -v e="$MARKER_END" '
        $0 == s { skip = 1; next }
        $0 == e { skip = 0; next }
        !skip { print }
    ' "$BASHRC" > "${BASHRC}.tmp" && mv "${BASHRC}.tmp" "$BASHRC"
fi

cat >> "$BASHRC" <<EOF
${MARKER_START}
if [ -x "${PROJECT_ROOT}/scripts/watchdog.sh" ]; then
    nohup "${PROJECT_ROOT}/scripts/watchdog.sh" >/dev/null 2>&1 &
fi
${MARKER_END}
EOF
echo "Configured auto-start hook in $BASHRC"

# 7. Launch watchdog immediately
echo "Starting Solar Battery Alexa Bridge in background..."
nohup "$PROJECT_ROOT/scripts/watchdog.sh" >/dev/null 2>&1 &
sleep 1

echo ""
echo "=== Setup Complete ==="
echo "Logs:   tail -f ${PROJECT_ROOT}/logs/watchdog.log ${PROJECT_ROOT}/logs/bridge.log"
echo "Status: cat ${PROJECT_ROOT}/status.json"
echo "Stop:   ${PROJECT_ROOT}/scripts/stop.sh"
echo ""
echo "Android checklist for reliable 24/7 operation:"
echo "  1. Install the 'Termux:Boot' app from F-Droid and open it once."
echo "  2. In Android Settings -> Battery, set both 'Termux' and 'Termux:Boot' to Unrestricted."
echo "  3. Note: If your phone has a lock screen PIN, Android requires one unlock after a reboot"
echo "     before Termux:Boot can read ~/.config/solar-battery-alexa/.env."
