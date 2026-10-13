#!/bin/bash
# Tests pullback calls as call debit spreads (what the bot now trades). Read-only, ~1 min.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
python3 -u swings.py --debit 2>&1 | grep -v "NotOpenSSL\|warnings.warn"
echo; echo "Done — tell Claude."
