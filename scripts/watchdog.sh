#!/bin/bash
# Get the directory where the script is located (scripts/ folder)
SCRIPT_DIR=$(dirname "$0")
# Go one level up to the project root
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

cd "$PROJECT_ROOT"

while true; do
    # Check if we can reach Google DNS (8.8.8.8)
    if ping -c 1 8.8.8.8 > /dev/null 2>&1; then
        echo "$(date): Internet OK. Starting Solar Bridge..."
        python src/battery_soc.py
        echo "$(date): Script exited with code $?. Restarting in 60s..."
        sleep 60
    else
        echo "$(date): No Internet. Waiting 5 minutes to retry..."
        sleep 300
    fi
done
