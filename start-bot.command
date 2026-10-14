#!/bin/bash
# Make Me Trade — start the Mac bot (Webull PAPER). Leave this window open.
# Auto-reloads when the bot code is updated, and restarts itself if it ever crashes.
cd "$(dirname "$0")/relay" || exit 1
source .venv/bin/activate
source ../.webull_paper
echo "=== Make Me Trade bot (paper) ==="
echo "Keeps your Mac awake while running. Close this window or press Ctrl+C to stop."
echo
(
  while true; do
    caffeinate -dims python3 -u mmt_bot.py 2>&1
    code=$?
    if [ "$code" -eq 75 ]; then echo "🔄 Reloading updated bot…"; continue; fi
    if [ "$code" -eq 0 ] || [ "$code" -eq 130 ]; then break; fi
    echo "Bot stopped unexpectedly (code $code). Restarting in 60 seconds — Ctrl+C to stop."
    sleep 60
  done
) 2>&1 | tee -a bot.log &
PID=$!
trap 'kill $PID 2>/dev/null; pkill -f mmt_bot.py 2>/dev/null; pkill -f "caffeinate -dims python3" 2>/dev/null; echo; echo Stopped.; exit 0' INT TERM
for i in $(seq 1 30); do [ -f status.html ] && break; sleep 2; done
[ -f status.html ] && open status.html
wait $PID
