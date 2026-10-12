#!/bin/bash
# Runs the historical strategy test (read-only, no orders). Takes 1–3 minutes.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
source ../.webull_paper
python3 -u backtest.py 2>&1 | grep -v "client_initializer INFO\|NotOpenSSL\|warnings.warn" | tee backtest_run.txt
echo; echo "Done — tell Claude."
