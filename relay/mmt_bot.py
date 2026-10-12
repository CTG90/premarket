#!/usr/bin/env python3
"""
Make Me Trade — Mac bot (Webull PAPER).

Runs the same playbook as the browser app, but:
  * stock quotes, daily bars and option bid/ask/IV/greeks come from Webull
  * orders are real Webull paper orders (limit, DAY), not simulated fills
  * runs in the background — no browser tab needed

Files (all in this folder):
  bot_config.json  rules (created with defaults on first run — edit freely)
  bot_state.json   trades, pending orders, log (the bot's memory)
  status.html      live dashboard — open it in a browser, refreshes itself
  ../STOP          create this file to pause NEW entries (exits still managed)

Usage:
  python3 mmt_bot.py               # run forever (Ctrl+C to stop)
  python3 mmt_bot.py --once        # one cycle, then exit
  python3 mmt_bot.py --dry         # decide + preview orders, never place
  python3 mmt_bot.py --test-order  # preview one order to validate format, places nothing
"""
import argparse
import datetime as dt
import json
import logging
import math
import os
import sys
import time
import traceback
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
CFG_F, STATE_F, BARS_F, HTML_F = BASE / "bot_config.json", BASE / "bot_state.json", BASE / "bars_cache.json", BASE / "status.html"
STOP_F = ROOT / "STOP"
ET = ZoneInfo("America/New_York")

WATCH = ["SPY", "QQQ", "NVDA", "AAPL", "AMZN", "MSFT", "META", "TSLA", "AMD", "PLTR"]
NAMES = {"SPY": "S&P 500 ETF", "QQQ": "Nasdaq ETF", "NVDA": "Nvidia", "AAPL": "Apple", "AMZN": "Amazon",
         "MSFT": "Microsoft", "META": "Meta", "TSLA": "Tesla", "AMD": "AMD", "PLTR": "Palantir"}

DEFAULTS = {
    "contracts": 1,            # contracts per trade (hard cap below)
    "max_per_trade": 750,      # $ per trade
    "max_open": 5,
    "take_profit_pct": 20,
    "stop_loss_pct": 35,
    "min_score": 60,
    "min_dte": 21,
    "time_stop_dte": 7,
    "otm_pct": 2,
    "max_spread_pct": 12,      # skip contracts whose bid/ask spread is wider than this % of mid
    "min_open_interest": 50,
    "max_orders_per_day": 5,   # new entries per day
    "daily_loss_limit": 1500,  # stop new entries for the day after this much realized loss
    "pause_calls_risk_off": True,
    "learn": True,
}
HARD_MAX_CONTRACTS = 1
LIVE_HOST = "api.webull.com"

log_lines = []


def now_et():
    return dt.datetime.now(ET)


def say(msg, st=None):
    line = now_et().strftime("%m-%d %H:%M") + "  " + msg
    print(line, flush=True)
    if st is not None:
        st["log"].append({"at": time.time(), "m": msg})
        st["log"] = st["log"][-400:]


def load_json(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def save_json(p, obj):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    tmp.replace(p)


def load_cfg():
    cfg = dict(DEFAULTS)
    cfg.update(load_json(CFG_F, {}))
    save_json(CFG_F, cfg)
    cfg["contracts"] = max(1, min(int(cfg["contracts"]), HARD_MAX_CONTRACTS))
    return cfg


def f(x, d=None):
    try:
        if x in (None, ""):
            return d
        return float(x)
    except Exception:
        return d


# ── Webull clients ────────────────────────────────────────────────────
class WB:
    def __init__(self):
        from webull.core.client import ApiClient
        from webull.data.data_client import DataClient
        from webull.trade.trade_client import TradeClient
        from webull.data.common.category import Category
        from webull.data.common.timespan import Timespan
        key, sec = os.environ.get("WEBULL_APP_KEY"), os.environ.get("WEBULL_APP_SECRET")
        self.acct = os.environ.get("WEBULL_ACCOUNT_ID")
        self.host = os.environ.get("WEBULL_HOST", "api.sandbox.webull.com")
        if not (key and sec and self.acct):
            sys.exit("Missing WEBULL_APP_KEY / WEBULL_APP_SECRET / WEBULL_ACCOUNT_ID (source ../.webull_paper).")
        if self.host == LIVE_HOST and os.environ.get("WEBULL_ALLOW_LIVE") != "1":
            sys.exit("Refusing to run against the LIVE server. This bot is paper-only until graduation.")
        api = ApiClient(key, sec, "us")
        api.add_endpoint("us", self.host)
        self.dc = DataClient(api)
        self.tc = TradeClient(api)
        logging.disable(logging.CRITICAL)  # SDK logs are noisy; we log ourselves
        self.Cat, self.TS = Category, Timespan

    @staticmethod
    def body(res):
        try:
            return res.json()
        except Exception:
            return getattr(res, "text", None)

    def snapshot(self, syms):
        res = self.dc.market_data.get_snapshot(",".join(syms), self.Cat.US_STOCK.name)
        out = {}
        for q in (self.body(res) or []):
            if isinstance(q, dict) and q.get("symbol"):
                out[q["symbol"]] = q
        return out

    def daily_bars(self, syms, n=260):
        res = self.dc.market_data.get_batch_history_bar(syms, self.Cat.US_STOCK.name, self.TS.D.name, n)
        b = self.body(res) or {}
        out = {}
        for item in (b.get("result") or []):
            rows = list(reversed(item.get("result") or []))  # oldest → newest
            out[item.get("symbol")] = {
                "t": [r.get("time", "")[:10] for r in rows],
                "c": [f(r.get("close")) for r in rows], "h": [f(r.get("high")) for r in rows],
                "l": [f(r.get("low")) for r in rows], "v": [f(r.get("volume"), 0) for r in rows]}
        return out

    def option_snapshots(self, occs):
        out = {}
        for i in range(0, len(occs), 20):
            res = self.dc.option_market_data.get_option_snapshot(",".join(occs[i:i + 20]), self.Cat.US_OPTION.name)
            for q in (self.body(res) or []):
                if isinstance(q, dict) and q.get("symbol"):
                    out[q["symbol"]] = q
        return out

    def _call(self, fn, *a):
        """SDK raises on non-200; turn that into (status, message) so the bot can log and carry on."""
        try:
            res = fn(*a)
            return res.status_code, self.body(res)
        except Exception as e:
            msg = str(e).splitlines()[0] if str(e) else type(e).__name__
            code = getattr(e, "http_status", None) or getattr(e, "status", None) or 0
            return code, {"error": msg[:400], "type": type(e).__name__}

    def preview(self, order):
        return self._call(self.tc.order_v2.preview_option, self.acct, [order])

    def place(self, order):
        return self._call(self.tc.order_v2.place_option, self.acct, [order])

    def detail(self, coid):
        return self._call(self.tc.order_v2.get_order_detail, self.acct, coid)

    def cancel(self, coid):
        return self._call(self.tc.order_v2.cancel_option, self.acct, coid)


# ── indicators (same math as the browser app) ─────────────────────────
def sma(a, n):
    return sum(a[-n:]) / n if len(a) >= n else None


def rsi(c, n=14):
    if len(c) < n + 1:
        return None
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def atr(h, l, c, n=14):
    if len(c) < n + 1:
        return None
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def hv_at(c, end, n=20):
    if end < n:
        return None
    rs = [math.log(c[i] / c[i - 1]) for i in range(end - n + 1, end + 1)]
    m = sum(rs) / len(rs)
    v = sum((x - m) ** 2 for x in rs) / (len(rs) - 1)
    return math.sqrt(v * 252) * 100


def pivots(h, l, lookback=180, k=3):
    pts = []
    for i in range(max(k, len(h) - lookback), len(h) - k):
        if all(h[j] <= h[i] for j in range(i - k, i + k + 1)):
            pts.append(h[i])
        if all(l[j] >= l[i] for j in range(i - k, i + k + 1)):
            pts.append(l[i])
    pts.sort()
    cl = []
    for p in pts:
        if cl and abs(p - cl[-1][0]) / cl[-1][0] < 0.012:
            s, n = cl[-1][1] + p, cl[-1][2] + 1
            cl[-1] = [s / n, s, n]
        else:
            cl.append([p, p, 1])
    return [round(x[0], 2) for x in cl]


def indicators(B):
    c, h, l, v = B["c"], B["h"], B["l"], B["v"]
    if len(c) < 60:
        return None
    hvs = [x for x in (hv_at(c, i) for i in range(max(21, len(c) - 252), len(c))) if x is not None]
    hv = hvs[-1]
    rank = round((hv - min(hvs)) / (max(hvs) - min(hvs)) * 100) if max(hvs) > min(hvs) else 50
    vols = [x for x in v[-64:-1] if x]
    return {"sma20": sma(c, 20), "sma50": sma(c, 50), "sma200": sma(c, 200), "rsi": rsi(c), "atr": atr(h, l, c),
            "hv": hv, "vr": rank, "levels": pivots(h, l), "hi52": max(h[-252:]), "avg_vol": sum(vols) / len(vols) if vols else None}


def trend_of(ind, p):
    if not ind or not ind["sma50"]:
        return "n/a"
    if ind["sma200"]:
        if p > ind["sma50"] > ind["sma200"]:
            return "up"
        if p < ind["sma50"] < ind["sma200"]:
            return "down"
        return "mixed"
    return "up" if p > ind["sma50"] else "down"


def levels(ind, p):
    res = sorted([x for x in ind["levels"] if x > p * 1.003] + ([round(ind["hi52"], 2)] if ind["hi52"] > p * 1.003 else []))
    sup = sorted([x for x in ind["levels"] if x < p * 0.997], reverse=True)
    near_res, near_sup = (res[0] if res else None), (sup[0] if sup else None)
    return {"res": near_res, "sup": near_sup,
            "near_res": bool(near_res and (near_res - p) / p * 100 < 1.5),
            "near_sup": bool(near_sup and (p - near_sup) / p * 100 < 1.5)}


def session_frac():
    n = now_et()
    m = n.hour * 60 + n.minute - 570
    return min(1.0, max(0.15, m / 390.0))


def score(m, ind):
    s, sigs = 0, []
    pct = m["pct"]; gap = abs(pct); up = pct >= 0
    rv = (m["vol"] / (ind["avg_vol"] * session_frac())) if (ind and ind["avg_vol"] and m["vol"]) else 1.0
    if 4 <= gap <= 7: s += 25; sigs.append("move %.1f%% ideal" % gap)
    elif 7 < gap <= 12: s += 20; sigs.append("move %.1f%% strong" % gap)
    elif 12 < gap <= 20: s += 12; sigs.append("move %.1f%% reversal risk" % gap)
    elif gap > 20: s += 5; sigs.append("move %.1f%% extreme" % gap)
    elif gap >= 1: s += 8; sigs.append("move %.1f%% minor" % gap)
    else: s += 2; sigs.append("flat")
    if rv >= 3: s += 20
    elif rv >= 2: s += 15
    elif rv >= 1.5: s += 10
    else: s += 4
    sigs.append("rel vol %.1fx" % rv)
    s += 10  # core watchlist (all names are liquid)
    tr = trend_of(ind, m["price"])
    if tr in ("up", "down"):
        if (tr == "up") == up: s += 12; sigs.append("with %strend" % tr)
        else: s -= 6; sigs.append("against %strend" % tr)
    if ind and ind["rsi"] is not None:
        r = ind["rsi"]
        if up and r > 75: s -= 8; sigs.append("RSI %d overbought" % r)
        elif (not up) and r < 25: s -= 8; sigs.append("RSI %d oversold" % r)
    lv = levels(ind, m["price"]) if ind else None
    if lv:
        if lv["near_res"] and up: s -= 8; sigs.append("at resistance %.2f" % lv["res"])
        elif lv["near_sup"] and not up: s += 8; sigs.append("at support %.2f" % lv["sup"])
    vr = ind["vr"] if ind else None
    if vr is not None:
        if vr >= 80: s -= 5
        elif vr < 55: s += 5
        sigs.append("vol rank %d" % vr)
    s += 10 if up else 8
    s += 5
    s = max(0, min(100, round(s)))
    if lv and lv["near_res"] and up: play = "Resistance Put"
    elif s >= 55 and up and gap >= 2: play = "Gap & Go"
    elif s >= 40 and up: play = "Swing Calls"
    elif s >= 30 and not up: play = "Puts Setup"
    elif s >= 35: play = "Watch"
    else: play = "Skip"
    d = "C" if play in ("Gap & Go", "Swing Calls") else "P" if play in ("Puts Setup", "Resistance Put") else None
    return {"s": s, "play": play, "dir": d, "trend": tr, "rv": round(rv, 2), "vr": vr,
            "rsi": round(ind["rsi"]) if ind and ind["rsi"] is not None else None, "sigs": sigs}


# ── contracts ─────────────────────────────────────────────────────────
def round_strike(p):
    if p >= 1000: return round(p / 10) * 10
    if p >= 200: return round(p / 5) * 5
    if p >= 50: return round(p / 2.5) * 2.5
    if p >= 20: return float(round(p))
    return round(p * 2) / 2


def strike_step(p):
    return 10 if p >= 1000 else 5 if p >= 200 else 2.5 if p >= 50 else 1 if p >= 20 else 0.5


def friday_at_least(days):
    d = now_et().date() + dt.timedelta(days=days)
    while d.weekday() != 4:
        d += dt.timedelta(days=1)
    return d.isoformat()


def occ(sym, iso, d, k):
    return "%s%s%s%08d" % (sym, iso[2:].replace("-", ""), d, int(round(k * 1000)))


def dte(iso):
    exp = dt.datetime.fromisoformat(iso + "T16:00:00").replace(tzinfo=ET)
    return (exp - now_et()).total_seconds() / 86400


def opt_px(q):
    bid, ask = f(q.get("bid"), 0), f(q.get("ask"), 0)
    mid = (bid + ask) / 2 if bid and ask else f(q.get("price"), 0)
    return bid, ask, mid


def build_order(o, side, qty, limit, exp_field):
    leg = {"side": side, "quantity": str(qty), "symbol": o["ticker"], "strike_price": ("%g" % o["strike"]),
           exp_field: o["exp"], "instrument_type": "OPTION", "option_type": "CALL" if o["dir"] == "C" else "PUT", "market": "US"}
    return {"client_order_id": uuid.uuid4().hex, "combo_type": "NORMAL", "order_type": "LIMIT", "quantity": str(qty),
            "limit_price": "%.2f" % limit, "option_strategy": "SINGLE", "side": side, "time_in_force": "DAY",
            "entrust_type": "QTY", "legs": [leg]}


def deep(obj, keys):
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                return obj[k]
        for v in obj.values():
            r = deep(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = deep(v, keys)
            if r is not None:
                return r
    return None


# ── stats / learning / graduation ─────────────────────────────────────
def pnl(t):
    px = t["exit"]["px"] if t.get("exit") else (t.get("mark") or {}).get("px", t["entry"]["px"])
    return (px - t["entry"]["px"]) * 100 * t["qty"]


def pnl_pct(t):
    px = t["exit"]["px"] if t.get("exit") else (t.get("mark") or {}).get("px", t["entry"]["px"])
    return (px / t["entry"]["px"] - 1) * 100 if t["entry"]["px"] else 0


def stats(ts):
    n = len(ts); w = [t for t in ts if pnl(t) > 0]
    gw = sum(pnl(t) for t in w); gl = -sum(pnl(t) for t in ts if pnl(t) <= 0)
    return {"n": n, "wr": len(w) / n * 100 if n else 0, "exp": sum(pnl(t) for t in ts) / n if n else 0,
            "pf": gw / gl if gl else (99 if gw > 0 else 0), "sum": sum(pnl(t) for t in ts)}


def learned(st, cfg):
    closed = [t for t in st["trades"] if t["status"] == "closed"]
    out = {"blocked": [], "min_score": cfg["min_score"], "notes": []}
    if not cfg["learn"]:
        return out
    groups = {}
    for t in closed:
        groups.setdefault(t["play"], []).append(t)
    for k, ts in groups.items():
        s = stats(ts)
        if s["n"] >= 10 and s["exp"] < 0:
            out["blocked"].append(k); out["notes"].append("Blocked %s: %d trades, avg $%.0f" % (k, s["n"], s["exp"]))
    bands = {}
    for t in closed:
        bands.setdefault(int(t["score"] // 10 * 10), []).append(t)
    for b, ts in bands.items():
        s = stats(ts)
        if s["n"] >= 10 and s["exp"] < 0 and b + 10 > out["min_score"]:
            out["min_score"] = b + 10; out["notes"].append("Min score raised to %d" % (b + 10))
    if not out["notes"]:
        out["notes"].append("Need %d more closed trades before rules adapt." % max(0, 10 - len(closed)) if len(closed) < 10 else "No losing setup over 10+ trades yet.")
    return out


def graduation(st, start=10000.0):
    closed = sorted([t for t in st["trades"] if t["status"] == "closed"], key=lambda t: t["exit"]["at"])
    s = stats(closed)
    eq = pk = start; dd = 0
    for t in closed:
        eq += pnl(t); pk = max(pk, eq); dd = max(dd, (pk - eq) / pk * 100)
    span = (time.time() - min(t["entry"]["at"] for t in closed)) / 86400 if closed else 0
    return [("50+ closed trades", len(closed) >= 50, "%d/50" % len(closed)),
            ("6+ weeks of history", span >= 42, "%d/42 days" % span),
            ("Positive expectancy", s["n"] > 0 and s["exp"] > 0, "$%.0f/trade" % s["exp"]),
            ("Profit factor ≥ 1.3", s["pf"] >= 1.3, "%.2f" % s["pf"]),
            ("Max drawdown ≤ 20%", bool(closed) and dd <= 20, "%.1f%%" % dd)]


# ── the bot ───────────────────────────────────────────────────────────
class Bot:
    def __init__(self, dry=False):
        self.dry = dry
        self.wb = WB()
        self.cfg = load_cfg()
        self.st = load_json(STATE_F, None) or {"trades": [], "log": [], "exp_field": None, "created": time.time()}
        self.quotes, self.ind, self.sigs, self.regime = {}, {}, [], {"k": "unknown", "why": []}
        self.last_tick = None; self.err = None

    # data
    def refresh_bars(self):
        cache = load_json(BARS_F, {})
        today = now_et().date().isoformat()
        if cache.get("d") != today or set(cache.get("bars", {})) < set(WATCH):
            bars = self.wb.daily_bars(WATCH)
            if bars:
                cache = {"d": today, "bars": bars}
                save_json(BARS_F, cache)
        for t, B in (cache.get("bars") or {}).items():
            # drop today's partial bar so indicators use completed sessions
            if B["t"] and B["t"][-1] == today:
                B = {k: v[:-1] for k, v in B.items()}
            self.ind[t] = indicators(B)

    def refresh_quotes(self):
        raw = self.wb.snapshot(WATCH)
        q = {}
        for t, r in raw.items():
            p, pc = f(r.get("price")), f(r.get("pre_close"))
            if p and pc:
                q[t] = {"ticker": t, "price": p, "prev": pc, "pct": (p - pc) / pc * 100, "vol": f(r.get("volume"), 0),
                        "bid": f(r.get("bid")), "ask": f(r.get("ask")), "ts": (f(r.get("last_trade_time"), 0) or 0) / 1000}
        self.quotes = q

    def regime_of(self):
        spy, i = self.quotes.get("SPY"), self.ind.get("SPY")
        if not spy or not i:
            return {"k": "unknown", "why": ["waiting for SPY data"]}
        pts, why = 0, []
        if i["sma50"] and spy["price"] < i["sma50"]: pts += 1; why.append("SPY below 50-day")
        if i["sma200"] and spy["price"] < i["sma200"]: pts += 2; why.append("SPY below 200-day")
        if i["vr"] >= 80: pts += 1; why.append("SPY volatility near 1-year high")
        k = "off" if pts >= 3 else "caution" if pts >= 1 else "on"
        return {"k": k, "why": why or ["SPY above 50/200-day, volatility normal"]}

    # helpers
    def open_trades(self):
        return [t for t in self.st["trades"] if t["status"] in ("opening", "open", "closing")]

    def today_entries(self):
        d = now_et().date().isoformat()
        return [t for t in self.st["trades"] if dt.datetime.fromtimestamp(t["created"], ET).date().isoformat() == d and t["status"] != "rejected"]

    def realized_today(self):
        d = now_et().date().isoformat()
        return sum(pnl(t) for t in self.st["trades"] if t["status"] == "closed" and dt.datetime.fromtimestamp(t["exit"]["at"], ET).date().isoformat() == d)

    def send(self, order, label):
        """preview → place. Learns which expiry field name the API wants."""
        fields = [self.st["exp_field"]] if self.st.get("exp_field") else ["option_expire_date", "init_exp_date"]
        last = None
        for fld in fields:
            o = dict(order); o["legs"] = [dict(order["legs"][0])]
            if fld != "option_expire_date":
                o["legs"][0][fld] = o["legs"][0].pop("option_expire_date")
            code, body = self.wb.preview(o)
            last = (code, body)
            if code == 200:
                self.st["exp_field"] = fld
                if self.dry:
                    say("DRY preview ok: %s" % label, self.st)
                    return None, body
                code2, body2 = self.wb.place(o)
                if code2 == 200:
                    return o["client_order_id"], body2
                say("Place FAILED %s: %s %s" % (label, code2, str(body2)[:200]), self.st)
                return None, body2
        say("Preview FAILED %s: %s %s" % (label, last[0], str(last[1])[:200]), self.st)
        return None, last[1]

    def build(self, t, side, limit):
        o = build_order(t, side, t["qty"], limit, "option_expire_date")
        return o

    # pending orders
    def check_pending(self):
        for t in self.st["trades"]:
            for kind in ("open_order", "close_order"):
                po = t.get(kind)
                if not po or po.get("done"):
                    continue
                code, body = self.wb.detail(po["coid"])
                status = str(deep(body, ["status", "order_status"]) or "").upper()
                fpx = f(deep(body, ["filled_price", "avg_filled_price", "filled_avg_price", "avg_price", "fill_price"]))
                po["last_status"] = status
                age = time.time() - po["at"]
                if "FILL" in status and "PART" not in status:
                    po["done"] = True
                    px = fpx or po["limit"]
                    if kind == "open_order":
                        t["entry"]["px"] = px; t["status"] = "open"; t["peak"] = px
                        say("✅ FILLED open %s @ $%.2f" % (t["occ"], px), self.st)
                    else:
                        t["exit"] = {"px": px, "at": time.time(), "reason": po["reason"]}; t["status"] = "closed"
                        say("%s CLOSED %s @ $%.2f · %s · %+.0f$ (%+.0f%%)" % ("✅" if pnl(t) >= 0 else "❌", t["occ"], px, po["reason"], pnl(t), pnl_pct(t)), self.st)
                elif any(x in status for x in ("CANCEL", "REJECT", "FAIL", "EXPIRE")):
                    po["done"] = True
                    if kind == "open_order":
                        t["status"] = "cancelled"; say("Open order %s ended: %s" % (t["occ"], status), self.st)
                    else:
                        t["status"] = "open"; t.pop("close_order", None); say("Close order %s ended: %s — will retry" % (t["occ"], status), self.st)
                elif age > 7 * 60:
                    self.wb.cancel(po["coid"])
                    say("Cancel stale %s order %s (%s, %.0f min)" % ("open" if kind == "open_order" else "close", t["occ"], status or "?", age / 60), self.st)

    # exits
    def manage_exits(self, opts, trading):
        cfg = self.cfg
        for t in [x for x in self.st["trades"] if x["status"] == "open"]:
            q = opts.get(t["occ"])
            if q:
                bid, ask, mid = opt_px(q)
                t["mark"] = {"px": bid or mid, "mid": mid, "at": time.time(), "iv": f(q.get("imp_vol")), "delta": f(q.get("delta"))}
            if not trading:
                continue
            d = dte(t["exp"]); p = pnl_pct(t)
            reason = None
            if p >= cfg["take_profit_pct"]: reason = "Take profit +%d%%" % cfg["take_profit_pct"]
            elif p <= -cfg["stop_loss_pct"]: reason = "Stop -%d%%" % cfg["stop_loss_pct"]
            elif d <= cfg["time_stop_dte"]: reason = "Time stop (%d DTE)" % math.ceil(d)
            if not reason or not q:
                continue
            bid, ask, mid = opt_px(q)
            limit = max(0.01, round(mid - (ask - bid) * 0.25, 2)) if bid and ask else max(0.01, round(bid or mid, 2))
            coid, _ = self.send(self.build(t, "SELL", limit), "close " + t["occ"])
            if coid:
                t["close_order"] = {"coid": coid, "at": time.time(), "limit": limit, "reason": reason}
                t["status"] = "closing"
                say("📤 SELL %s x%d @ $%.2f · %s" % (t["occ"], t["qty"], limit, reason), self.st)

    # entries
    def find_contract(self, m, d):
        p = m["price"]; cfg = self.cfg
        iso = friday_at_least(cfg["min_dte"])
        k0 = round_strike(p * (1 + cfg["otm_pct"] / 100 if d == "C" else 1 - cfg["otm_pct"] / 100))
        step = strike_step(p)
        ks = [k0, k0 - step, k0 + step, k0 - 2 * step, k0 + 2 * step]
        occs = [occ(m["ticker"], iso, d, k) for k in ks]
        snaps = self.wb.option_snapshots(occs)
        why = "no listed contract near %g" % k0
        for k, o in zip(ks, occs):
            q = snaps.get(o)
            if not q:
                continue
            bid, ask, mid = opt_px(q)
            if not (bid and ask and mid):
                why = "no bid/ask"; continue
            spread = (ask - bid) / mid * 100
            oi = f(q.get("open_interest"), 0)
            if spread > cfg["max_spread_pct"]:
                why = "spread %.0f%%" % spread; continue
            if oi < cfg["min_open_interest"]:
                why = "open interest %d" % oi; continue
            if ask * 100 * cfg["contracts"] > cfg["max_per_trade"]:
                why = "$%.0f > $%d max" % (ask * 100, cfg["max_per_trade"]); continue
            return {"strike": k, "occ": o, "exp": iso, "bid": bid, "ask": ask, "mid": mid, "spread": spread, "oi": oi,
                    "iv": f(q.get("imp_vol")), "delta": f(q.get("delta"))}, None
        return None, why

    def status_of(self, m, sc, L):
        cfg = self.cfg; t = m["ticker"]
        if any(x["ticker"] == t for x in self.open_trades()): return "held", "In a position"
        if not sc["dir"]: return "none", "No setup"
        if sc["s"] < L["min_score"]: return "low", "Score < %d" % L["min_score"]
        if sc["play"] in L["blocked"]: return "blk", "Blocked by results"
        if cfg["pause_calls_risk_off"] and self.regime["k"] == "off" and sc["dir"] == "C": return "blk", "Calls paused · risk-off"
        if any(x["ticker"] == t for x in self.today_entries()): return "done", "Traded today"
        return "go", "Clears rules"

    def entries(self, trading_window):
        cfg = self.cfg; L = learned(self.st, cfg)
        rows = []
        for t in WATCH:
            m = self.quotes.get(t)
            if not m:
                continue
            sc = score(m, self.ind.get(t))
            k, label = self.status_of(m, sc, L)
            rows.append({"t": t, "m": m, "sc": sc, "k": k, "label": label})
        rows.sort(key=lambda r: (r["k"] != "go", -r["sc"]["s"]))
        self.sigs = rows
        if not trading_window:
            return
        if STOP_F.exists():
            return
        if self.realized_today() <= -cfg["daily_loss_limit"]:
            return
        for r in rows:
            if r["k"] != "go":
                continue
            if len(self.open_trades()) >= cfg["max_open"]:
                r["label"] = "Max positions"; break
            if len(self.today_entries()) >= cfg["max_orders_per_day"]:
                r["label"] = "Daily order cap"; break
            c, why = self.find_contract(r["m"], r["sc"]["dir"])
            if not c:
                r["label"] = "Skip: " + why; continue
            limit = round(c["mid"] + (c["ask"] - c["bid"]) * 0.25, 2)
            t = {"id": uuid.uuid4().hex[:10], "ticker": r["t"], "dir": r["sc"]["dir"], "strike": c["strike"], "exp": c["exp"],
                 "occ": c["occ"], "qty": cfg["contracts"], "play": r["sc"]["play"], "score": r["sc"]["s"],
                 "feat": {k: r["sc"][k] for k in ("trend", "rv", "vr", "rsi")}, "created": time.time(),
                 "entry": {"px": limit, "und": r["m"]["price"], "at": time.time(), "iv": c["iv"], "spread": c["spread"]},
                 "status": "opening"}
            coid, _ = self.send(self.build(t, "BUY", limit), "open " + c["occ"])
            if coid:
                t["open_order"] = {"coid": coid, "at": time.time(), "limit": limit}
                self.st["trades"].append(t)
                r["k"], r["label"] = "held", "Order sent"
                say("📥 BUY %s x%d @ $%.2f · %s · score %d · spread %.0f%% · IV %s" % (
                    c["occ"], t["qty"], limit, t["play"], t["score"], c["spread"], ("%.0f%%" % (c["iv"] * 100)) if c["iv"] else "?"), self.st)
            elif self.dry:
                r["label"] = "DRY: would buy %s @ $%.2f" % (c["occ"], limit)

    def tick(self):
        n = now_et(); mins = n.hour * 60 + n.minute; wd = n.weekday() < 5
        market = wd and 570 <= mins < 960
        window = wd and 585 <= mins <= 945
        self.cfg = load_cfg()
        try:
            self.refresh_bars()
            self.refresh_quotes()
            self.regime = self.regime_of()
            fresh = any(time.time() - q["ts"] < 20 * 60 for q in self.quotes.values()) if market else False
            if market and not fresh:
                say("Quotes look stale (holiday/halt?) — no trading this cycle", self.st)
            self.check_pending()
            opts = self.wb.option_snapshots([t["occ"] for t in self.st["trades"] if t["status"] in ("open", "closing")]) if self.open_trades() else {}
            self.manage_exits(opts, market and fresh)
            self.entries(window and fresh)
            self.err = None
        except Exception as e:
            self.err = "%s: %s" % (type(e).__name__, str(e).splitlines()[0][:200] if str(e) else "")
            say("ERROR " + self.err, self.st)
            traceback.print_exc()
        self.last_tick = time.time()
        save_json(STATE_F, self.st)
        write_html(self)

    def sleep_s(self):
        n = now_et(); mins = n.hour * 60 + n.minute; wd = n.weekday() < 5
        if wd and 565 <= mins < 965: return 180
        if wd and 240 <= mins < 565: return 600
        return 1800


# ── dashboard ─────────────────────────────────────────────────────────
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_html(bot):
    st, cfg = bot.st, bot.cfg
    closed = [t for t in st["trades"] if t["status"] == "closed"]
    opn = bot.open_trades()
    s = stats(closed)
    total = sum(pnl(t) for t in closed) + sum(pnl(t) for t in opn if t["status"] != "opening")
    n = now_et(); mins = n.hour * 60 + n.minute
    phase = "Weekend" if n.weekday() >= 5 else "Market open" if 570 <= mins < 960 else "Premarket" if 240 <= mins < 570 else "Closed"
    reg = bot.regime; regc = {"on": "#10b981", "caution": "#f59e0b", "off": "#ef4444"}.get(reg["k"], "#6b7280")
    L = learned(st, cfg)
    h = ["<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
         "<meta http-equiv=refresh content=60><title>Make Me Trade · Bot</title><style>",
         "body{font-family:-apple-system,system-ui,sans-serif;background:#060810;color:#e5e7eb;margin:0;padding:16px;max-width:820px;margin:auto}",
         ".c{background:#0d1420;border:1px solid #1a2540;border-radius:12px;padding:12px;margin:8px 0}.k{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}",
         ".k div{background:#060810;border:1px solid #1a2540;border-radius:8px;padding:8px;text-align:center}.l{font-size:10px;color:#5b6688;text-transform:uppercase}",
         ".v{font-size:17px;font-weight:700}.up{color:#10b981}.dn{color:#ef4444}h1{font-size:22px;margin:0}h2{font-size:12px;color:#818cf8;text-transform:uppercase;margin:16px 0 4px}",
         "table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:6px 4px;border-bottom:1px solid #1a2540;text-align:left}th{color:#5b6688;font-size:10px;text-transform:uppercase}",
         ".chip{font-size:11px;padding:2px 7px;border-radius:5px;background:#1a2540}.g{background:rgba(16,185,129,.15);color:#10b981}.r{background:rgba(239,68,68,.12);color:#f87171}",
         ".m{color:#5b6688;font-size:11px}</style></head><body>"]
    h.append("<h1>🤖 Make Me Trade · Mac bot</h1><div class=m>Webull PAPER · %s · %s ET · last cycle %s · page refreshes every 60s</div>" % (
        phase, n.strftime("%a %b %d %H:%M"), dt.datetime.fromtimestamp(bot.last_tick, ET).strftime("%H:%M:%S") if bot.last_tick else "--"))
    if STOP_F.exists():
        h.append("<div class='c' style='border-color:#ef4444;color:#f87171'>⏸ STOP file present — no new entries. Delete MakeMeTrade/STOP to resume.</div>")
    if bot.dry:
        h.append("<div class='c' style='border-color:#f59e0b;color:#fbbf24'>DRY RUN — previews only, no orders placed.</div>")
    if bot.err:
        h.append("<div class='c' style='border-color:#ef4444;color:#f87171'>Last error: %s</div>" % esc(bot.err))
    h.append("<div class='c k'><div><div class=l>Regime</div><div class=v style='color:%s'>%s</div></div>" % (regc, reg["k"].upper()))
    h.append("<div><div class=l>Total P&amp;L</div><div class='v %s'>%+.0f$</div></div>" % ("up" if total >= 0 else "dn", total))
    h.append("<div><div class=l>Win rate</div><div class=v>%s</div></div>" % ("%.0f%%" % s["wr"] if s["n"] else "--"))
    h.append("<div><div class=l>Closed / Open</div><div class=v>%d / %d</div></div></div>" % (s["n"], len(opn)))
    h.append("<div class=m>%s</div>" % esc(" · ".join(reg["why"])))
    h.append("<h2>Open positions</h2><div class=c>")
    if not opn:
        h.append("<div class=m>None.</div>")
    else:
        h.append("<table><tr><th>Contract</th><th>Status</th><th>Entry</th><th>Mark</th><th>P&amp;L</th></tr>")
        for t in opn:
            mk = (t.get("mark") or {}).get("px")
            h.append("<tr><td><b>%s</b><div class=m>%s · score %d · %d DTE</div></td><td>%s</td><td>$%.2f</td><td>%s</td><td class=%s>%+.0f%%<div class=m>%+.0f$</div></td></tr>" % (
                esc(t["occ"]), esc(t["play"]), t["score"], max(0, dte(t["exp"])), t["status"], t["entry"]["px"],
                "$%.2f" % mk if mk else "--", "up" if pnl(t) >= 0 else "dn", pnl_pct(t), pnl(t)))
        h.append("</table>")
    h.append("</div><h2>Signals</h2><div class=c><table><tr><th>Ticker</th><th>Price</th><th>Score</th><th>Play</th><th>Status</th></tr>")
    for r in bot.sigs:
        m = r["m"]
        h.append("<tr><td><b>%s</b></td><td>$%.2f <span class=%s>%+.2f%%</span></td><td>%d</td><td>%s<div class=m>%s</div></td><td><span class='chip %s'>%s</span></td></tr>" % (
            r["t"], m["price"], "up" if m["pct"] >= 0 else "dn", m["pct"], r["sc"]["s"], r["sc"]["play"], esc(", ".join(r["sc"]["sigs"][:4])),
            "g" if r["k"] in ("go", "held") else "r" if r["k"] == "blk" else "", esc(r["label"])))
    h.append("</table></div><h2>Ready for real money?</h2><div class=c><table>")
    for name, ok, v in graduation(st):
        h.append("<tr><td>%s %s</td><td>%s</td></tr>" % ("✅" if ok else "❌", name, v))
    h.append("</table><div class=m style='margin-top:6px'>%s</div></div>" % esc(" · ".join(L["notes"])))
    h.append("<h2>Closed trades</h2><div class=c>")
    if not closed:
        h.append("<div class=m>None yet.</div>")
    else:
        h.append("<table><tr><th>Contract</th><th>Exit</th><th>P&amp;L</th></tr>")
        for t in sorted(closed, key=lambda x: -x["exit"]["at"])[:40]:
            h.append("<tr><td>%s<div class=m>%s</div></td><td>%s</td><td class=%s>%+.0f%% <span class=m>%+.0f$</span></td></tr>" % (
                esc(t["occ"]), esc(t["play"]), esc(t["exit"]["reason"]), "up" if pnl(t) >= 0 else "dn", pnl_pct(t), pnl(t)))
        h.append("</table>")
    h.append("</div><h2>Activity</h2><div class=c>")
    for l in reversed(st["log"][-30:]):
        h.append("<div class=m style='padding:2px 0'>%s &nbsp; %s</div>" % (dt.datetime.fromtimestamp(l["at"], ET).strftime("%m-%d %H:%M"), esc(l["m"])))
    h.append("</div><div class=m>Rules: bot_config.json · Pause new entries: create a file named STOP in MakeMeTrade · Paper only.</div></body></html>")
    HTML_F.write_text("".join(h))


def test_order():
    bot = Bot(dry=True)
    bot.refresh_bars(); bot.refresh_quotes()
    m = bot.quotes.get("SPY")
    if not m:
        sys.exit("No SPY quote.")
    c, why = bot.find_contract(m, "C")
    if not c:
        bot.cfg["max_per_trade"] = 100000
        c, why = bot.find_contract(m, "C")
    if not c:
        sys.exit("No usable SPY contract: " + why)
    t = {"ticker": "SPY", "dir": "C", "strike": c["strike"], "exp": c["exp"], "qty": 1}
    print("Contract:", c["occ"], "bid", c["bid"], "ask", c["ask"], "spread %.1f%%" % c["spread"], "OI", c["oi"], "IV", c["iv"])
    base = build_order(t, "BUY", 1, max(0.05, round(c["bid"] * 0.5, 2)), "option_expire_date")
    for fld in ("option_expire_date", "init_exp_date"):
        o = json.loads(json.dumps(base)); leg = o["legs"][0]
        if fld != "option_expire_date":
            leg[fld] = leg.pop("option_expire_date")
        code, body = bot.wb.preview(o)
        print("Preview with %s -> %s %s" % (fld, code, json.dumps(body, default=str)[:600]))
        if code == 200:
            bot.st["exp_field"] = fld
            break
    print("Expiry field that worked:", bot.st.get("exp_field"))
    save_json(STATE_F, bot.st)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--test-order", action="store_true")
    a = ap.parse_args()
    if a.test_order:
        return test_order()
    bot = Bot(dry=a.dry)
    say("Make Me Trade bot started · host %s · %s" % (bot.wb.host, "DRY RUN" if a.dry else "paper orders"), bot.st)
    say("Dashboard: %s" % HTML_F)
    while True:
        bot.tick()
        if a.once:
            break
        s = bot.sleep_s()
        try:
            time.sleep(s)
        except KeyboardInterrupt:
            break
    save_json(STATE_F, bot.st)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
