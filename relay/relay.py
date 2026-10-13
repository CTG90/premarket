#!/usr/bin/env python3
"""
Premarket Pro -> Webull relay (v0, SANDBOX FIRST).

Reads a paper-trading export from the app (Bot tab -> Export) and sends the
open positions' opening orders to Webull's OpenAPI.

Safety defaults:
  * DRY RUN unless --send is given (prints the exact payloads, sends nothing)
  * SANDBOX host unless --live is given AND env WEBULL_ALLOW_LIVE=1
  * LIMIT + DAY orders only, never market orders
  * hard caps: contracts per order, $ per order, orders per day
  * each app trade id is sent at most once (tracked in sent.json)

Usage:
  pip3 install --upgrade webull-openapi-python-sdk
  export WEBULL_APP_KEY=...  WEBULL_APP_SECRET=...
  python3 relay.py accounts
  python3 relay.py place premarket-paper-2026-10-12.json            # dry run
  python3 relay.py place premarket-paper-2026-10-12.json --send     # sandbox
"""
import argparse
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path

import keyfile  # noqa: F401  (loads ../.webull_paper into env if not sourced)

SANDBOX_HOST = "api.sandbox.webull.com"        # current docs (paper/sandbox)
OLD_UAT_HOST = "us-openapi-alb.uat.webullbroker.com"
LIVE_HOST = "api.webull.com"
REGION = "us"

# Hard caps. Edit deliberately; the relay refuses anything above these.
MAX_CONTRACTS_PER_ORDER = 1          # start at 1 contract, always
MAX_DOLLARS_PER_ORDER = 750
MAX_ORDERS_PER_DAY = 5
UNSUPPORTED = {"SPX", "SPXW"}        # Webull OpenAPI: no index options

STATE = Path(__file__).with_name("sent.json")


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"sent": {}, "days": {}}


def save_state(s):
    STATE.write_text(json.dumps(s, indent=2))


def client(live, key=None, secret=None, host=None):
    try:
        from webull.core.client import ApiClient
        from webull.trade.trade_client import TradeClient
    except ImportError:
        sys.exit("Install the SDK first: pip3 install --upgrade webull-openapi-python-sdk")
    key = key or os.environ.get("WEBULL_APP_KEY")
    secret = secret or os.environ.get("WEBULL_APP_SECRET")
    if not key or not secret:
        sys.exit("Set WEBULL_APP_KEY and WEBULL_APP_SECRET.")
    host = host or os.environ.get("WEBULL_HOST") or (LIVE_HOST if live else SANDBOX_HOST)
    api = ApiClient(key, secret, REGION)
    api.add_endpoint(REGION, host)
    return TradeClient(api), host


def to_webull(order):
    """App order (bot.js makeOrder) -> Webull single-leg option order."""
    side = "BUY" if order["side"].startswith("BUY") else "SELL"
    qty = str(int(order["qty"]))
    return {
        "client_order_id": uuid.uuid4().hex,
        "combo_type": "NORMAL",
        "order_type": "LIMIT",
        "quantity": qty,
        "limit_price": f'{float(order["limit"]):.2f}',
        "option_strategy": "SINGLE",
        "side": side,
        "time_in_force": "DAY",
        "entrust_type": "QTY",
        "legs": [{
            "side": side,
            "quantity": qty,
            "symbol": order["symbol"],
            "strike_price": str(order["strike"]),
            # Docs show option_expire_date in the Python sample and
            # init_exp_date in the JSON sample. Verify against the SDK version.
            "option_expire_date": order["exp"],
            "instrument_type": "OPTION",
            "option_type": "CALL" if order["dir"] == "C" else "PUT",
            "market": "US",
        }],
    }


def check(order, state, today):
    if order["symbol"] in UNSUPPORTED:
        return "index options not supported by Webull OpenAPI"
    if order.get("type") != "LIMIT":
        return "only LIMIT orders allowed"
    if int(order["qty"]) > MAX_CONTRACTS_PER_ORDER:
        return f'qty {order["qty"]} > cap {MAX_CONTRACTS_PER_ORDER} (will be clipped)'
    if float(order["limit"]) * 100 * int(order["qty"]) > MAX_DOLLARS_PER_ORDER:
        return f"cost > ${MAX_DOLLARS_PER_ORDER} cap"
    if state["days"].get(today, 0) >= MAX_ORDERS_PER_DAY:
        return f"daily cap of {MAX_ORDERS_PER_DAY} orders reached"
    return None


def cmd_accounts(args):
    tc, host = client(args.live)
    res = tc.account_v2.get_account_list()
    print(f"[{host}] status {res.status_code}")
    print(json.dumps(res.json(), indent=2))


def cmd_probe(args):
    """Try key/host combinations; read-only (account list). Writes probe_output.txt."""
    import logging
    logging.disable(logging.CRITICAL)
    key, secret = os.environ.get("WEBULL_APP_KEY", ""), os.environ.get("WEBULL_APP_SECRET", "")
    keys = [key] + ([key.split(".", 1)[1]] if key.lower().startswith("us.") else [])
    lines = []
    for k in keys:
        for h in (SANDBOX_HOST, OLD_UAT_HOST, LIVE_HOST):
            label = f'key={"as-is" if k == key else "without us."}  host={h}'
            try:
                tc, _ = client(False, k, secret, h)
                res = tc.account_v2.get_account_list()
                body = res.json() if res.status_code == 200 else res.text[:200]
                ok = res.status_code == 200
                lines.append(("OK   " if ok else "FAIL ") + label + "  ->  " + (json.dumps(body)[:1500] if ok else str(body)))
            except Exception as e:
                lines.append("FAIL " + label + "  ->  " + str(e).splitlines()[0][:200])
    out = "\n".join(lines)
    print(out)
    Path(__file__).with_name("probe_output.txt").write_text(out + "\n")


def cmd_place(args):
    if args.live and os.environ.get("WEBULL_ALLOW_LIVE") != "1":
        sys.exit("Refusing --live without WEBULL_ALLOW_LIVE=1. Finish the graduation checks first.")
    data = json.loads(Path(args.export).read_text())
    state, today = load_state(), dt.date.today().isoformat()
    open_trades = [t for t in data.get("trades", []) if not t.get("exit") and t.get("order")]
    if not open_trades:
        print("No open paper trades with orders in this export.")
        return
    tc = host = None
    args.account = args.account or os.environ.get("WEBULL_ACCOUNT_ID")
    if args.send:
        tc, host = client(args.live)
        if not args.account:
            sys.exit("Pass --account <account_id> or set WEBULL_ACCOUNT_ID (run: relay.py accounts).")
        if host == LIVE_HOST and os.environ.get("WEBULL_ALLOW_LIVE") != "1":
            sys.exit("WEBULL_HOST points at the live server. Refusing without WEBULL_ALLOW_LIVE=1.")
    for t in open_trades:
        o = dict(t["order"])
        label = f'{o["symbol"]} {o["exp"]} {o["strike"]}{o["dir"]} x{o["qty"]} @ {float(o["limit"]):.2f}'
        if t["id"] in state["sent"]:
            print(f"skip  {label}  (already sent)")
            continue
        if int(o["qty"]) > MAX_CONTRACTS_PER_ORDER:
            o["qty"] = MAX_CONTRACTS_PER_ORDER
        why = check(o, state, today)
        if why:
            print(f"BLOCK {label}  ({why})")
            continue
        payload = to_webull(o)
        if not args.send:
            print(f"DRY   {label}")
            print(json.dumps(payload, indent=2))
            continue
        res = tc.order_v2.place_option(args.account, [payload])
        ok = res.status_code == 200
        print(f'{"SENT " if ok else "FAIL "} {label}  [{host}] {res.status_code} {res.text[:300]}')
        if ok:
            state["sent"][t["id"]] = {"client_order_id": payload["client_order_id"], "host": host, "at": dt.datetime.now().isoformat()}
            state["days"][today] = state["days"].get(today, 0) + 1
            save_state(state)


def main():
    p = argparse.ArgumentParser(description="Premarket Pro -> Webull relay (sandbox first)")
    p.add_argument("--live", action="store_true", help="use production host (also needs WEBULL_ALLOW_LIVE=1)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("accounts", help="list accounts to get account_id")
    sub.add_parser("probe", help="find which key format + host your keys work with (read-only)")
    pl = sub.add_parser("place", help="send open paper trades from an app export")
    pl.add_argument("export", help="JSON file from Bot tab -> Export")
    pl.add_argument("--account", help="Webull account_id")
    pl.add_argument("--send", action="store_true", help="actually send (default is dry run)")
    args = p.parse_args()
    {"accounts": cmd_accounts, "place": cmd_place, "probe": cmd_probe}[args.cmd](args)


if __name__ == "__main__":
    main()
