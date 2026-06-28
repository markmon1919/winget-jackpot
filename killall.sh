#!/usr/bin/env bash


set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$BASE_DIR/backend.pid"

if [[ -f "$PIDFILE" ]]; then
    pid=$(cat "$PIDFILE")

    if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping backend supervisor ($pid)..."
        kill -TERM "$pid"
        exit 0
    fi
fi

echo "Backend is not running."
