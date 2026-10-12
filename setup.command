#!/bin/bash
# Make Me Trade — one-time Webull paper setup. Double-click to run.
cd "$(dirname "$0")"
KEYFILE="$(pwd)/.webull_paper"
clear
echo "=== Make Me Trade · Webull paper setup ==="
echo
if [ ! -s "$KEYFILE" ]; then
  echo "Paste your Webull PAPER App Key, then press Enter:"
  read -r KEY
  echo "Paste your Webull PAPER App Secret, then press Enter (it stays hidden):"
  read -rs SECRET; echo
  KEY="$(echo "$KEY" | tr -d '[:space:]')"; SECRET="$(echo "$SECRET" | tr -d '[:space:]')"
  if [ -z "$KEY" ] || [ -z "$SECRET" ]; then echo "Key or secret was empty. Run this again."; read -r -p "Press Enter to close"; exit 1; fi
  printf "export WEBULL_APP_KEY='%s'\nexport WEBULL_APP_SECRET='%s'\n" "$KEY" "$SECRET" > "$KEYFILE"
  chmod 600 "$KEYFILE"
  echo "✅ Keys saved to MakeMeTrade/.webull_paper (only your user can read it)."
else
  echo "✅ Keys already saved in MakeMeTrade/.webull_paper"
  echo "   (to re-enter them: delete that file and run this again)"
fi
echo
if ! /usr/bin/xcrun --find python3 >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  echo "Python isn't installed. A macOS window will offer Command Line Tools — click Install,"
  echo "wait for it to finish, then double-click setup.command again."
  xcode-select --install 2>/dev/null
  read -r -p "Press Enter to close"; exit 1
fi
cd relay || exit 1
echo "Setting up Python (first run takes a minute)…"
[ -d .venv ] || python3 -m venv .venv || { echo "Couldn't create Python env."; read -r -p "Press Enter to close"; exit 1; }
source .venv/bin/activate
pip install -q --upgrade pip >/dev/null 2>&1
pip install -q --upgrade webull-openapi-python-sdk 2>/dev/null || pip install -q "git+https://github.com/webull-inc/webull-openapi-python-sdk"
source "$KEYFILE"
echo
echo "=== Your Webull paper accounts ==="
python3 relay.py accounts 2>&1 | tee accounts_output.txt
echo
echo "Done. Result saved to relay/accounts_output.txt — tell Claude it's finished."
read -r -p "Press Enter to close"
