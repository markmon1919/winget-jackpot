#!/usr/bin/env bash


set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$BASE_DIR/.venv/bin/python"
PIDFILE="$BASE_DIR/backend.pid"

echo $$ > "$PIDFILE"

cleanup() {
    echo "🛑 Stopping services..."

    rm -f "$PIDFILE"

    kill \
        "$PID_API" \
        "$PID_HS" \
        "$PID_RTP" \
        "$PID_WIN" \
        "$PID_WIN2" \
        2>/dev/null || true

    wait 2>/dev/null || true

    echo "✅ Backend stopped."
}

trap cleanup EXIT INT TERM

"$PYTHON" "$BASE_DIR/api_data.py" > api.log 2>&1 &
PID_API=$!

"$PYTHON" "$BASE_DIR/hs_data.py" > hs.log 2>&1 &
PID_HS=$!

"$PYTHON" "$BASE_DIR/rtp_data.py" > rtp.log 2>&1 &
PID_RTP=$!

"$PYTHON" "$BASE_DIR/winners_data.py" > winners.log 2>&1 &
PID_WIN=$!

"$PYTHON" "$BASE_DIR/winners_data_2.py" > winners2.log 2>&1 &
PID_WIN2=$!

echo "📊 Backend started."
echo "Supervisor: $$"
echo "api=$PID_API"
echo "hs=$PID_HS"
echo "rtp=$PID_RTP"
echo "winners=$PID_WIN"
echo "winners2=$PID_WIN2"

set +e
wait -n
status=$?
set -e

echo "A child process exited."

exit "$status"
