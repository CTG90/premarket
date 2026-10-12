#!/bin/bash
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
source ../.webull_paper
python3 relay.py probe 2>/dev/null
echo; echo "Done — tell Claude."
