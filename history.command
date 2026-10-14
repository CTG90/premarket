#!/bin/bash
# 20+ year crash test: replays the bot's strategies through every bear market since 2000. Read-only, ~2-4 min.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
python3 -u history.py 2>&1 | grep -v "NotOpenSSL\|warnings.warn\|DeprecationWarning\|utcfromtimestamp"
echo; echo "Done — tell Claude."
