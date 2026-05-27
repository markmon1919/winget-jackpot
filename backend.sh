#!/usr/bin/env bash

set -uo pipefail

PYTHON=".venv/bin/python"

# Start Redis
redis-server ./redis.conf > redis.log 2>&1 &
PID_REDIS=$!

sleep 2

# Start workers
$PYTHON api_data.py > api.log 2>&1 &
PID_API=$!

$PYTHON hs_data.py > hs.log 2>&1 &
PID_HS=$!

$PYTHON rtp_data.py > rtp.log 2>&1 &
PID_RTP=$!

$PYTHON winners_data.py > winners.log 2>&1 &
PID_WIN=$!

echo "📊 Backend started."
echo "redis=$PID_REDIS api=$PID_API hs=$PID_HS rtp=$PID_RTP winners=$PID_WIN"

wait
