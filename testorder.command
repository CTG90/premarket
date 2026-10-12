#!/bin/bash
# Previews one SPY option order to confirm the order format. Places NOTHING.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
source ../.webull_paper
python3 mmt_bot.py --test-order 2>&1 | grep -v "client_initializer INFO" | tee testorder_output.txt
echo; echo "Done — tell Claude."
