#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$BASE_DIR/.venv/bin/python"

# redis-server "$BASE_DIR/redis.conf" > redis.log 2>&1 &
# PID_REDIS=$!

# sleep 2

$PYTHON "$BASE_DIR/api_data.py" > api.log 2>&1 &
PID_API=$!

$PYTHON "$BASE_DIR/hs_data.py" > hs.log 2>&1 &
PID_HS=$!

$PYTHON "$BASE_DIR/rtp_data.py" > rtp.log 2>&1 &
PID_RTP=$!

$PYTHON "$BASE_DIR/winners_data.py" > winners.log 2>&1 &
PID_WIN=$!

$PYTHON "$BASE_DIR/winners_data_2.py" > winners2.log 2>&1 &
PID_WIN2=$!

echo "📊 Backend started."
# echo "redis=$PID_REDIS api=$PID_API hs=$PID_HS rtp=$PID_RTP winners=$PID_WIN"
echo "api=$PID_API hs=$PID_HS rtp=$PID_RTP winners=$PID_WIN winners2=$PID_WIN2"

wait
