#!/usr/bin/env python3
"""Read-only check: does Webull paper OpenAPI serve stock quotes, daily bars and option data?
Writes datacheck_output.txt. Places no orders."""
import datetime as dt, json, logging, os, sys, traceback
from pathlib import Path
logging.disable(logging.CRITICAL)
OUT = Path(__file__).with_name("datacheck_output.txt")
lines = []
def log(s): print(s); lines.append(s)
def show(res, n=900):
    try:
        body = res.json()
    except Exception:
        body = getattr(res, "text", str(res))
    return f"HTTP {getattr(res,'status_code','?')} " + json.dumps(body, default=str)[:n]
def step(name, fn):
    try:
        log(f"\n## {name}\n" + fn())
    except Exception as e:
        log(f"\n## {name}\nERROR {type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}")

try:
    from webull.core.client import ApiClient
    from webull.data.data_client import DataClient
    from webull.data.common.category import Category
    from webull.data.common.timespan import Timespan
except Exception as e:
    log("SDK import failed: " + repr(e)); OUT.write_text("\n".join(lines)); sys.exit(1)
try:
    import webull; log("SDK version: " + str(getattr(webull, "__version__", "?")))
except Exception: pass

key, sec = os.environ["WEBULL_APP_KEY"], os.environ["WEBULL_APP_SECRET"]
host = os.environ.get("WEBULL_HOST", "api.sandbox.webull.com")
log(f"Host: {host}   Time: {dt.datetime.now().isoformat(timespec='seconds')}")
api = ApiClient(key, sec, "us"); api.add_endpoint("us", host)
try:
    dc = DataClient(api)
except Exception as e:
    log("DataClient init failed: " + str(e).splitlines()[0]); OUT.write_text("\n".join(lines)); sys.exit(1)
logging.disable(logging.CRITICAL)

step("Stock snapshot SPY,AAPL", lambda: show(dc.market_data.get_snapshot("SPY,AAPL", Category.US_STOCK.name, extend_hour_required=True)))
step("Stock quote (bid/ask) AAPL", lambda: show(dc.market_data.get_quotes("AAPL", Category.US_STOCK.name, depth=1)))
def bars():
    md = dc.market_data
    if hasattr(md, "get_batch_history_bar"):
        return show(md.get_batch_history_bar(["SPY"], Category.US_STOCK.name, Timespan.D.name, 5))
    return show(md.get_history_bar("SPY", Category.US_STOCK.name, Timespan.D.name, count="5"))
step("Daily bars SPY (5)", bars)

state = {}
def contracts():
    ins = dc.instrument
    today = dt.date.today()
    start = (today + dt.timedelta(days=14)).isoformat(); end = (today + dt.timedelta(days=35)).isoformat()
    fn = getattr(ins, "list_option_contracts", None) or getattr(ins, "get_option_contracts")
    kw = dict(underlying_symbols="SPY", option_type="CALL", page_size=20)
    try:
        res = fn(**kw, end_date=start)  # lower bound on expiry in get_option_contracts
    except TypeError:
        res = fn(**kw)
    try:
        data = res.json()
        items = data if isinstance(data, list) else (data.get("data") or data.get("list") or data.get("items") or [])
        for it in items:
            sym = it.get("symbol") or it.get("option_symbol")
            if sym: state["opt"] = sym; break
    except Exception:
        pass
    return show(res, 1500) + f"\n(picked: {state.get('opt')})"
step("Option contracts SPY calls (2-5 wks out)", contracts)
def osnap():
    sym = state.get("opt")
    if not sym:
        # fall back to a constructed near-ATM monthly contract
        d = dt.date.today() + dt.timedelta(days=21)
        while d.weekday() != 4: d += dt.timedelta(days=1)
        sym = "SPY" + d.strftime("%y%m%d") + "C00" + "650000"
        sym = sym[:-8] + "00650000"
    return f"symbol {sym}\n" + show(dc.option_market_data.get_option_snapshot(sym, Category.US_OPTION.name), 1500)
step("Option snapshot (bid/ask/IV/greeks?)", osnap)

OUT.write_text("\n".join(lines) + "\n")
log("\nSaved to relay/datacheck_output.txt")
