#!/usr/bin/env bash

set -euo pipefail

PYTHON=".venv/bin/python"

$PYTHON api_data.py   2>&1 &
PID_API=$!

$PYTHON hs_data.py    2>&1 &
PID_HS=$!

$PYTHON winners_data.py 2>&1 &
PID_WIN=$!

echo "📊 Backend started."
echo "PIDs: api=$PID_API hs=$PID_HS winners=$PID_WIN"

wait