#!/usr/bin/env bash


set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$BASE_DIR/backend.pid"

if [[ -f "$PIDFILE" ]]; then
    pid=$(cat "$PIDFILE")

    if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping backend supervisor ($pid)..."

        kill -TERM "$pid"

        # Wait up to 5 seconds
        for _ in {1..50}; do
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 0.1
        done

        # Still alive? Force kill.
        if kill -0 "$pid" 2>/dev/null; then
            echo "Force killing supervisor..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi

    rm -f "$PIDFILE"
fi

# Cleanup leftover ports
for port in 6666 7777 8080 8888; do
    pids=$(lsof -ti :"$port" 2>/dev/null || true)

    if [[ -n "$pids" ]]; then
        echo "Force killing port $port: $pids"
        kill -9 $pids 2>/dev/null || true
    fi
done

# Cleanup orphan backend scripts
pkill -f "api_data.py" 2>/dev/null || true
pkill -f "hs_data.py" 2>/dev/null || true
pkill -f "rtp_data.py" 2>/dev/null || true
pkill -f "winners_data.py" 2>/dev/null || true
pkill -f "winners_data_2.py" 2>/dev/null || true

echo "✅ Backend stopped."
