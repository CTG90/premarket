#!/bin/bash
# Swing strategy lab + 12-month growth simulator. Read-only, ~1-3 min.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
python3 -u swings.py 2>&1 | grep -v "client_initializer INFO\|NotOpenSSL\|warnings.warn\|swing configs"
echo; echo "Done — tell Claude."
