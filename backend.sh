#!/usr/bin/env bash


set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$BASE_DIR/.venv/bin/python"
PIDFILE="$BASE_DIR/backend.pid"

# Prevent multiple instances
if [[ -f "$PIDFILE" ]]; then
    oldpid=$(cat "$PIDFILE")
    if kill -0 "$oldpid" 2>/dev/null; then
        echo "Backend already running (PID $oldpid)"
        exit 1
    fi
fi

echo $$ > "$PIDFILE"

CLEANED_UP=0

cleanup() {
    (( CLEANED_UP )) && return
    CLEANED_UP=1

    echo -e "\n\n\t🛑  Stopping services..."

    rm -f "$PIDFILE"

    # Ask children to exit cleanly
    kill \
        "$PID_API" \
        "$PID_HS" \
        "$PID_RTP" \
        "$PID_WIN" \
        "$PID_WIN2" \
        2>/dev/null || true

    # Give them up to 5 seconds
    for _ in {1..50}; do
        alive=0

        for pid in \
            "$PID_API" \
            "$PID_HS" \
            "$PID_RTP" \
            "$PID_WIN" \
            "$PID_WIN2"
        do
            if kill -0 "$pid" 2>/dev/null; then
                alive=1
                break
            fi
        done

        (( alive == 0 )) && break
        sleep 0.1
    done

    # Force kill any remaining
    kill -9 \
        "$PID_API" \
        "$PID_HS" \
        "$PID_RTP" \
        "$PID_WIN" \
        "$PID_WIN2" \
        2>/dev/null || true

    wait 2>/dev/null || true

    echo -e "\n\n\t✅  Backend stopped."
}

trap cleanup EXIT INT TERM

"$PYTHON" "$BASE_DIR/api_data.py" >api.log 2>&1 &
PID_API=$!

"$PYTHON" "$BASE_DIR/hs_data.py" >hs.log 2>&1 &
PID_HS=$!

"$PYTHON" "$BASE_DIR/rtp_data.py" >rtp.log 2>&1 &
PID_RTP=$!

"$PYTHON" "$BASE_DIR/winners_data.py" >winners.log 2>&1 &
PID_WIN=$!

"$PYTHON" "$BASE_DIR/winners_data_2.py" >winners2.log 2>&1 &
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

# echo -e "\n\n\tA child process exited."

exit "$status"
