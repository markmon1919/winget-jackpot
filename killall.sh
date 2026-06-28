#!/usr/bin/env bash

set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$BASE_DIR/backend.pid"

# Stop the supervisor first (this should clean up its children)
if [[ -f "$PIDFILE" ]]; then
    pid=$(cat "$PIDFILE")

    if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping backend supervisor ($pid)..."
        kill -TERM "$pid"

        # Give it a moment to run its cleanup trap
        sleep 2
    fi

    rm -f "$PIDFILE"
fi

# Force-kill anything still listening on backend ports
for port in 6666 7777 8080 8888; do
    pids=$(lsof -ti :"$port" 2>/dev/null || true)

    if [[ -n "$pids" ]]; then
        echo "Force killing port $port: $pids"
        kill -9 $pids 2>/dev/null || true
    fi
done

# Last-resort cleanup of backend scripts only
pkill -f "api_data.py" 2>/dev/null || true
pkill -f "hs_data.py" 2>/dev/null || true
pkill -f "rtp_data.py" 2>/dev/null || true
pkill -f "winners_data.py" 2>/dev/null || true
pkill -f "winners_data_2.py" 2>/dev/null || true

echo "✅ Backend stopped."
