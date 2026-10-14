#!/bin/bash
# Day-trading test: 5-min (60 days) + 1-hour (2 years) setups vs random, with 0DTE / 1-week option returns. Read-only, ~2-3 min.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
python3 -u intraday.py 2>&1 | grep -v "NotOpenSSL\|warnings.warn\|Warning"
echo; echo "Done — tell Claude."
