#!/bin/bash
# Get the directory where the script is located (scripts/ folder)
SCRIPT_DIR=$(dirname "$0")
# Go one level up to the project root
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

cd "$PROJECT_ROOT"

while true; do
    echo "Starting Solar Battery SOC monitor script..."
    python src/battery_soc.py
    echo "Script crashed with exit code $?. Restarting in 2 minutes..."
    sleep 120
done