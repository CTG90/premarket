#!/usr/bin/env python3
"""
Make Me Trade — 20+ year crash test.

Pulls free daily history from Yahoo (fallback: Stooq) back to ~1999 and replays the bot's strategies
through every bear market: dot-com, 2008, 2011, 2015-16, 2018, COVID, 2022, 2025.

  A  credit spreads on SPY/QQQ   (bot settings: 0.30 delta, 45 DTE, $2 wide, TP 75%, exit 7 DTE)
  B  dip-buy call debit spreads  (stock > 200-day, RSI2 < 5, ATM, 4% wide, TP 50%, 21-day hold)
  B+ same, but only when SPY is also above its 200-day (market filter)
  C  rip-sell put debit spreads  (stock < 200-day, RSI2 > 90, mirror of B)
  C+ same, but only when SPY is below its 200-day (true bear market)

Options are priced with Black-Scholes. IV = VIX for SPY, VXN for QQQ, 1.15x 20-day HV for stocks.
Split-adjusted prices drive the signals; option math uses the real (unsplit) price at entry.
Then it replays A+B as one account at the bot's sizing to show the worst drawdowns.

Usage: python3 history.py        (writes hist_bars.json once, history_report.txt each run)
"""
import datetime as dt
import json
import sys
import time
from pathlib import Path

import backtest as BT
import mmt_bot as M
import swings as SW

BASE = Path(__file__).resolve().parent
HIST_F = BASE / "hist_bars.json"
REPORT_F = BASE / "history_report.txt"
TICKERS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "NFLX", "META", "TSLA", "AMD", "AVGO", "PLTR"]
IVX = {"SPY": "^VIX", "QQQ": "^VXN"}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
CRASHES = [("Dot-com bust", "2000-03-24", "2002-10-09"), ("2008 crisis", "2007-10-09", "2009-03-09"),
           ("2011 debt scare", "2011-07-22", "2011-10-03"), ("2015-16 selloff", "2015-07-20", "2016-02-11"),
           ("2018 Q4 drop", "2018-09-20", "2018-12-24"), ("COVID crash", "2020-02-19", "2020-03-23"),
           ("2022 bear market", "2022-01-03", "2022-10-12"), ("2025 tariff drop", "2025-02-19", "2025-04-08")]


# ── data ─────────────────────────────────────────────────────────────────
def http_get(url):
    try:
        import requests
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        return r.text
    except ImportError:
        import urllib.request
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as f:
            return f.read().decode("utf-8", "ignore")


def from_yahoo(sym):
    q = sym.replace("^", "%5E")
    for host in ("query1", "query2"):
        try:
            j = json.loads(http_get("https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=0&period2=%d&interval=1d&events=split"
                                    % (host, q, int(time.time()) + 86400)))
            res = j["chart"]["result"][0]
            ts, qd = res["timestamp"], res["indicators"]["quote"][0]
            splits = [(dt.datetime.utcfromtimestamp(int(s["date"])).date().isoformat(), s["numerator"] / s["denominator"])
                      for s in (res.get("events", {}).get("splits") or {}).values() if s.get("denominator")]
            out = {"t": [], "c": [], "h": [], "l": [], "v": [], "splits": sorted(splits)}
            for k, t in enumerate(ts):
                c = qd["close"][k]
                if c is None:
                    continue
                out["t"].append(dt.datetime.utcfromtimestamp(t).date().isoformat())
                out["c"].append(float(c)); out["h"].append(float(qd["high"][k] or c)); out["l"].append(float(qd["low"][k] or c))
                out["v"].append(float(qd["volume"][k] or 0))
            if len(out["c"]) > 300:
                return out
        except Exception as e:
            print("  yahoo %s (%s): %s" % (sym, host, str(e)[:80]), flush=True)
    return None


def from_stooq(sym):
    s = sym.lower() if sym.startswith("^") else sym.lower() + ".us"
    try:
        rows = http_get("https://stooq.com/q/d/l/?s=%s&i=d" % s).strip().splitlines()
        out = {"t": [], "c": [], "h": [], "l": [], "v": [], "splits": []}
        for r in rows[1:]:
            p = r.split(",")
            if len(p) >= 5 and p[4] not in ("", "null"):
                out["t"].append(p[0]); out["c"].append(float(p[4])); out["h"].append(float(p[2])); out["l"].append(float(p[3]))
                out["v"].append(float(p[5]) if len(p) > 5 and p[5] else 0.0)
        return out if len(out["c"]) > 300 else None
    except Exception as e:
        print("  stooq %s: %s" % (sym, str(e)[:80]), flush=True)
        return None


def fetch():
    have = json.loads(HIST_F.read_text()) if HIST_F.exists() else {}
    for sym in TICKERS + list(IVX.values()):
        if sym in have and have[sym]["t"][-1] >= (dt.date.today() - dt.timedelta(days=7)).isoformat():
            continue
        b = from_yahoo(sym) or from_stooq(sym)
        if b:
            have[sym] = b
            print("bars %-6s %s → %s (%d days)" % (sym, b["t"][0], b["t"][-1], len(b["c"])), flush=True)
        else:
            print("bars %-6s FAILED" % sym, flush=True)
        time.sleep(0.6)
    HIST_F.write_text(json.dumps(have))
    return have


def build(raw):
    """Per ticker: adjusted series for signals + scale[i] = real price / adjusted price (undoes later splits)."""
    data = {}
    for t in TICKERS:
        B = raw.get(t)
        if not B:
            continue
        P = SW.enrich(BT.prep({k: B[k] for k in ("t", "c", "h", "l", "v")}))
        sc = []
        for d in P["t"]:
            f = 1.0
            for sd, ratio in B.get("splits", []):
                if d < sd:
                    f *= ratio
            sc.append(f)
        P["scale"] = sc
        P["idx"] = {d: k for k, d in enumerate(P["t"])}
        ivs = raw.get(IVX.get(t, ""), None)
        if ivs:
            m = dict(zip(ivs["t"], ivs["c"]))
            P["iv"] = [m.get(d) for d in P["t"]]
        data[t] = P
    return data


_hv_iv = BT.iv_at


def iv_at(P, i):  # VIX/VXN when we have it, else 1.15x HV
    iv = P.get("iv")
    if iv and iv[i]:
        return max(0.10, iv[i] / 100)
    return _hv_iv(P, i)


BT.iv_at = iv_at   # run_credit looks this up at call time


# ── strategies ───────────────────────────────────────────────────────────
def credit(data):
    sub = {t: data[t] for t in ("SPY", "QQQ") if t in data}
    cache = {t: {i: (BT.ind_at(P, i), None) for i in range(260, P["n"])} for t, P in sub.items()}
    p = dict(delta=0.30, dte=45, width_pct=0, width_usd=2, tp=75, stop_mult=0, exit_dte=7, both_sides=True,
             etf_only=True, max_rsi=70, ladder=2, spacing=5, max_risk=0, fee=0.26)
    out = []
    for x in BT.run_credit(sub, cache, p):
        P = sub[x["t"]]; i = P["idx"][x["d"]]
        out.append({"k": "A", "t": x["t"], "d": x["d"], "x": P["t"][min(P["n"] - 1, i + x["days"])],
                    "r": x["pnl"] / x["risk"] if x["risk"] else 0})
    return out


def spy_above(data):
    S = data["SPY"]
    return {d: (S["s200"][k] is not None and S["c"][k] > S["s200"][k]) for k, d in enumerate(S["t"])}


def debit(data, kind, mkt=None):
    """kind 'call': uptrend + RSI2<5 dip.  kind 'put': downtrend + RSI2>90 rip.  mkt: dict date→SPY above 200d (filter)."""
    call = kind == "call"; out = []
    for t, P in data.items():
        busy = -1
        for i in range(210, P["n"] - 2):
            if i <= busy or None in (P["s200"][i], P["r2"][i]):
                continue
            if call and not (P["c"][i] > P["s200"][i] and P["r2"][i] < 5):
                continue
            if not call and not (P["c"][i] < P["s200"][i] and P["r2"][i] > 90):
                continue
            if mkt is not None and mkt.get(P["t"][i]) is not (True if call else False):
                continue
            f = P["scale"][i]; S = P["c"][i] * f
            if S < 5:
                continue
            exp = BT.day_index_after(P, i, 45)
            k1 = BT.snap(S, S); w = max(M.strike_step(S), BT.snap(S * 0.04, S)); k2 = k1 + w if call else k1 - w

            def val(j):
                Tj = BT.T_years(P, j, exp); sj = iv_at(P, j); Sj = P["c"][j] * f
                return BT.bs(Sj, k1, Tj, sj, call) - BT.bs(Sj, k2, Tj, sj, call)
            mid = val(i)
            if mid <= 0.05 or mid > 0.7 * w:
                continue
            entry = mid + 0.04; j = i; v = None
            while j + 1 < P["n"]:
                j += 1
                v = max(0.0, val(j) - 0.04)
                if (v / entry - 1) * 100 >= 50 or (P["d"][j] - P["d"][i]).days >= 21 or (exp - P["d"][j]).days <= 7:
                    break
            else:
                break
            out.append({"k": "B" if call else "C", "t": t, "d": P["t"][i], "x": P["t"][j], "r": v / entry - 1})
            busy = j
    return out


# ── reporting ────────────────────────────────────────────────────────────
def st(tr):
    if not tr:
        return "%-26s" % "no trades"
    n = len(tr); w = sum(x["r"] > 0 for x in tr) / n * 100; a = sum(x["r"] for x in tr) / n * 100
    return "%3d tr · win %3.0f%% · avg %+6.1f%%" % (n, w, a)


def account(trades, risk, cap=30.0, max_debit_open=3, start=10000.0):
    """Replay trades in date order as one account: stake = risk% of equity at entry, P&L booked at exit."""
    ev = sorted([(x["d"], 1, k) for k, x in enumerate(trades)] + [(x["x"], 0, k) for k, x in enumerate(trades)])
    eq = start; open_ = {}; peak = eq; mdd = 0; mdd_at = ""; yr_start = {}; curve = {}
    for d, kind, k in ev:
        x = trades[k]
        yr_start.setdefault(d[:4], eq)
        if kind == 0:
            if k in open_:
                eq += open_.pop(k) * x["r"]
        else:
            stake = eq * risk[x["k"]] / 100
            at_risk = sum(open_.values())
            n_deb = sum(1 for kk in open_ if trades[kk]["k"] != "A")
            if at_risk + stake > eq * cap / 100 or (x["k"] != "A" and n_deb >= max_debit_open):
                continue
            open_[k] = stake
        peak = max(peak, eq)
        if (peak - eq) / peak * 100 > mdd:
            mdd = (peak - eq) / peak * 100; mdd_at = d
        curve[d[:4]] = eq
    years = sorted(curve)
    yret = {y: (curve[y] / yr_start[y] - 1) * 100 for y in years}
    n_years = max(1e-9, (dt.date.fromisoformat(ev[-1][0]) - dt.date.fromisoformat(ev[0][0])).days / 365)
    cagr = ((eq / start) ** (1 / n_years) - 1) * 100 if eq > 0 else -100
    return {"final": eq, "cagr": cagr, "mdd": mdd, "mdd_at": mdd_at, "yret": yret}


def main():
    raw = fetch()
    data = build(raw)
    if "SPY" not in data:
        sys.exit("Couldn't get SPY history — check the internet connection and run again.")
    mkt = spy_above(data)
    print("Running strategies…", flush=True)
    S = {"A": credit(data), "B": debit(data, "call"), "B+": debit(data, "call", mkt),
         "C": debit(data, "put"), "C+": debit(data, "put", mkt)}
    for k in ("B+", "C+"):
        for x in S[k]:
            x["k"] = k[0]
    names = {"A": "Credit spreads SPY/QQQ", "B": "Dip-buy call spreads", "B+": "Dip-buy calls + SPY filter",
             "C": "Rip-sell put spreads", "C+": "Put spreads, SPY bear only"}
    spy = data["SPY"]

    L = ["20+ YEAR CRASH TEST · %s → %s · %d tickers (%s)" % (spy["t"][0], spy["t"][-1], len(data), ",".join(data)),
         "IV: VIX for SPY, VXN for QQQ%s · stocks use 1.15x 20-day HV" % ("" if data["SPY"].get("iv") else " (VIX MISSING → HV)"),
         "avg = return on the money risked per trade (credit: credit kept vs max loss; debit: % gain on the debit)", "",
         "ALL YEARS"]
    for k in S:
        L.append("  %-28s %s" % (names[k], st(S[k])))

    L.append("\nCRASHES (trades entered during each drop)")
    L.append("  %-18s %8s | %-33s | %-33s | %-33s" % ("", "SPY", "A credit spreads", "B dip-buy calls", "C+ puts in bear"))
    for nm, a, b in CRASHES:
        if a < spy["t"][0]:
            continue
        ia, ib = spy["idx"].get(a), spy["idx"].get(b)
        if ia is None or ib is None:
            ia = next((k for k, d in enumerate(spy["t"]) if d >= a), None); ib = next((k for k, d in enumerate(spy["t"]) if d >= b), None)
        sp = (spy["c"][ib] / spy["c"][ia] - 1) * 100 if ia is not None and ib is not None else 0
        f = lambda tr: [x for x in tr if a <= x["d"] <= b]
        L.append("  %-18s %+7.0f%% | %-33s | %-33s | %-33s" % (nm, sp, st(f(S["A"])), st(f(S["B"])), st(f(S["C+"]))))

    L.append("\nBY YEAR")
    L.append("  %-5s %7s | %-31s | %-31s | %-31s" % ("year", "SPY", "A credit spreads", "B dip-buy calls", "C+ puts in bear"))
    ys = sorted({d[:4] for d in spy["t"]})
    for y in ys:
        ks = [k for k, d in enumerate(spy["t"]) if d[:4] == y]
        sp = (spy["c"][ks[-1]] / spy["c"][ks[0]] - 1) * 100
        f = lambda tr: [x for x in tr if x["d"][:4] == y]
        L.append("  %-5s %+6.0f%% | %-31s | %-31s | %-31s" % (y, sp, st(f(S["A"])), st(f(S["B"])), st(f(S["C+"]))))

    L.append("\nONE ACCOUNT, bot rules (30% max at risk, 3 debit spreads max), $10,000 start")
    for label, tr, risk in (("Bot today: A 6% + B 5%", S["A"] + S["B"], {"A": 6, "B": 5, "C": 5}),
                            ("A 6% + B+ 5% (SPY filter)", S["A"] + S["B+"], {"A": 6, "B": 5, "C": 5}),
                            ("A + B + C+ (with bear puts)", S["A"] + S["B"] + S["C+"], {"A": 6, "B": 5, "C": 5}),
                            ("Aggressive: A 8% + B 8%", S["A"] + S["B"], {"A": 8, "B": 8, "C": 8})):
        r = account([dict(x) for x in tr], risk)
        worst = sorted(r["yret"].items(), key=lambda kv: kv[1])[:3]
        L.append("  %-30s → $%s · %+.0f%%/yr · max drawdown %.0f%% (%s) · worst years %s" % (
            label, format(round(r["final"]), ","), r["cagr"], r["mdd"], r["mdd_at"],
            ", ".join("%s %+.0f%%" % kv for kv in worst)))
    rep = "\n".join(L)
    print("\n" + rep)
    REPORT_F.write_text(rep + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
