#!/bin/bash
# Edge scanner: pulls NFLX/GOOGL/TSLA/AMD/AVGO/PLTR history, tests ~23 signals, options, growth sim. Read-only, ~2-5 min.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
source ../.webull_paper
python3 -u edges.py 2>&1 | grep -v "client_initializer INFO\|NotOpenSSL\|warnings.warn"
echo; echo "Done — tell Claude."
