#!/bin/bash
# Micro-futures trend-following backtest (ETF proxies). Read-only, ~1-2 min.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
source ../.webull_paper
python3 -u futures.py 2>&1 | grep -v "NotOpenSSL\|warnings.warn"
echo; echo "Done — tell Claude."
