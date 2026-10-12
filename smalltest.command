#!/bin/bash
# Tests narrow SPY/QQQ credit spreads sized for a $2,500 account. Read-only, ~1 min.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
source ../.webull_paper
if [ -f bt_bars.json ]; then C=--cached; else C=; fi
python3 -u backtest.py $C --small 2500 2>&1 | grep -v "client_initializer INFO\|NotOpenSSL\|warnings.warn"
echo; echo "Done — tell Claude."
