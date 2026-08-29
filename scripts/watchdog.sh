#!/bin/bash
while true; do
    echo "Starting Solar Battery SOC monitor script..."
    python battery_soc.py
    echo "Script crashed with exit code $?. Restarting in 2 minutes..."
    sleep 120
done