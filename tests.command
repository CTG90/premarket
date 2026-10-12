#!/bin/bash
# 1) Preview a SPY credit spread order (places NOTHING)  2) Run backtest v2. Read-only. ~3-5 min.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
source ../.webull_paper
echo "=== 1/2 Spread order preview (no order placed) ==="
python3 mmt_bot.py --test-spread 2>&1 | grep -v "client_initializer INFO\|NotOpenSSL\|warnings.warn" | tee spread_output.txt
echo; echo "=== 2/2 Backtest v2 (older-half vs newer-half check) ==="
rm -f bt_bars.json
python3 -u backtest.py 2>&1 | grep -v "client_initializer INFO\|NotOpenSSL\|warnings.warn" | grep -v "configs " | tee backtest_run.txt | grep "^bars\|BACKTEST\|Picked"
echo; echo "Done — tell Claude."
