#!/usr/bin/env python3
"""
Make Me Trade — historical strategy tester.

Pulls ~4 years of daily bars from Webull for the watchlist and replays two families:
  A. BUY options on the app's momentum score (what the bot does today)
  B. SELL defined-risk credit spreads with the trend (bull put / bear call)

Option prices are MODELED (Black-Scholes, IV ≈ 1.15 × 20-day realized vol, plus slippage),
because historical option quotes aren't available. Good for ranking strategies, not for
promising returns.

Outputs: backtest_report.txt and backtest_report.html (+ backtest_results.json)
Usage:   python3 backtest.py            (fetches from Webull; caches to bt_bars.json)
         python3 backtest.py --cached   (reuse bt_bars.json)
"""
import argparse
import datetime as dt
import itertools
import json
import math
import os
import sys
from pathlib import Path
from statistics import NormalDist

BASE = Path(__file__).resolve().parent
BARS_F = BASE / "bt_bars.json"
N = NormalDist()
RFR = 0.04
WATCH = ["SPY", "QQQ", "NVDA", "AAPL", "AMZN", "MSFT", "META", "TSLA", "AMD", "PLTR"]

sys.path.insert(0, str(BASE))
import mmt_bot as M  # reuse indicators + scoring so the test matches the live bot


# ── data ──────────────────────────────────────────────────────────────
def fetch_bars(count=1000):
    wb = M.WB()
    out = {}
    for t in WATCH:
        b = {}
        for cnt in (count, 800, 600, 400):
            try:
                b = wb.daily_bars([t], cnt)
            except Exception:
                b = {}
            if b.get(t) and len(b[t]["c"]) > 300:
                break
        try:
            if b.get(t) and len(b[t]["c"]) > 300:
                out[t] = b[t]
                print("bars %s: %d days (%s → %s)" % (t, len(b[t]["c"]), b[t]["t"][0], b[t]["t"][-1]), flush=True)
            else:
                print("bars %s: too few" % t, flush=True)
        except Exception as e:
            print("bars %s failed: %s" % (t, str(e).splitlines()[0][:120]), flush=True)
    BARS_F.write_text(json.dumps(out))
    return out


# ── pricing ───────────────────────────────────────────────────────────
def bs(S, K, T, sig, call):
    if T <= 0 or sig <= 0:
        return max(0.0, S - K if call else K - S)
    sq = sig * math.sqrt(T)
    d1 = (math.log(S / K) + (RFR + sig * sig / 2) * T) / sq
    d2 = d1 - sq
    disc = math.exp(-RFR * T)
    return S * N.cdf(d1) - K * disc * N.cdf(d2) if call else K * disc * N.cdf(-d2) - S * N.cdf(-d1)


def strike_for_delta(S, T, sig, delta, call):
    # call delta = N(d1) ; put delta = N(d1) - 1
    d1 = N.inv_cdf(delta if call else 1 - delta)
    return S * math.exp(-(d1 * sig * math.sqrt(T) - (RFR + sig * sig / 2) * T))


def snap(k, S):
    st = M.strike_step(S)
    return round(k / st) * st


# ── per-ticker precompute ─────────────────────────────────────────────
def prep(B):
    c, h, l, v, t = B["c"], B["h"], B["l"], B["v"], B["t"]
    n = len(c)
    hv = [None] * n
    for i in range(21, n):
        hv[i] = M.hv_at(c, i)
    days = [dt.date.fromisoformat(x) for x in t]
    return {"c": c, "h": h, "l": l, "v": v, "t": t, "d": days, "hv": hv, "n": n}


def ind_at(P, i):
    """Indicators using bars up to and including day i (as the live bot sees at the close)."""
    lo = max(0, i - 300)
    B = {"c": P["c"][lo:i + 1], "h": P["h"][lo:i + 1], "l": P["l"][lo:i + 1], "v": P["v"][lo:i + 1]}
    return M.indicators(B)


def iv_at(P, i):
    hv = P["hv"][i] or 30
    return max(0.12, hv / 100 * 1.15)


def day_index_after(P, i, cal_days):
    target = P["d"][i] + dt.timedelta(days=cal_days)
    while target.weekday() != 4:
        target += dt.timedelta(days=1)
    return target


def T_years(P, j, exp):
    return max(0.0, ((exp - P["d"][j]).days + 0.25) / 365)


# ── strategy A: buy options on score ──────────────────────────────────
def run_buy(data, cache, p):
    trades = []
    for t, P in data.items():
        busy_until = -1
        for i in range(260, P["n"] - 2):
            if i <= busy_until:
                continue
            ind, sc = cache[t][i]
            if not sc or sc["s"] < p["min_score"] or not sc["dir"]:
                continue
            if p["trend_only"] and sc["trend"] not in ("up", "down"):
                continue
            if p["trend_only"] and (sc["trend"] == "up") != (sc["dir"] == "C"):
                continue
            call = sc["dir"] == "C"
            S = P["c"][i]
            exp = day_index_after(P, i, p["dte"])
            K = snap(S * (1 + p["otm"] / 100 if call else 1 - p["otm"] / 100), S)
            mid = bs(S, K, T_years(P, i, exp), iv_at(P, i), call)
            if mid < 0.1:
                continue
            entry = mid * 1.03 + 0.02
            peak = entry; out = None
            j = i
            while j + 1 < P["n"]:
                j += 1
                T = T_years(P, j, exp)
                val = bs(P["c"][j], K, T, iv_at(P, j), call)
                bid = max(0.0, val * 0.97 - 0.02)
                peak = max(peak, bid)
                pct = (bid / entry - 1) * 100
                reason = None
                if p["trail"] and peak >= entry * (1 + p["tp"] / 100):
                    if bid <= peak * (1 - p["trail"] / 100):
                        reason = "trail"
                elif not p["trail"] and pct >= p["tp"]:
                    reason = "tp"
                if not reason and pct <= -p["sl"]:
                    reason = "sl"
                if not reason and (exp - P["d"][j]).days <= p["time_stop"]:
                    reason = "time"
                if reason:
                    out = (bid, reason); break
            if not out:
                break
            trades.append({"t": t, "d": P["t"][i], "pnl": (out[0] - entry) * 100, "risk": entry * 100, "why": out[1], "days": j - i})
            busy_until = j
    return trades


# ── strategy B: credit spreads with the trend ─────────────────────────
def run_credit(data, cache, p):
    trades = []
    for t, P in data.items():
        if p["etf_only"] and t not in ("SPY", "QQQ"):
            continue
        busy_until = -1
        for i in range(260, P["n"] - 2):
            if i <= busy_until:
                continue
            ind, sc = cache[t][i]
            if not ind:
                continue
            S = P["c"][i]
            tr = M.trend_of(ind, S)
            if tr == "up":
                call = False  # bull put spread
            elif tr == "down" and p["both_sides"]:
                call = True   # bear call spread
            elif p["trend_filter"]:
                continue
            else:
                call = False
            if p["max_rsi"] and ind["rsi"] is not None and not call and ind["rsi"] > p["max_rsi"]:
                continue
            exp = day_index_after(P, i, p["dte"])
            T = T_years(P, i, exp); sig = iv_at(P, i)
            short_k = snap(strike_for_delta(S, T, sig, p["delta"], call), S)
            width = max(M.strike_step(S), snap(S * p["width_pct"] / 100, S))
            long_k = short_k + width if call else short_k - width
            credit_mid = bs(S, short_k, T, sig, call) - bs(S, long_k, T, sig, call)
            credit = credit_mid * 0.95 - 0.02
            if credit < width * 0.08:   # too little premium for the risk
                continue
            max_loss = width - credit
            out = None; j = i
            while j + 1 < P["n"]:
                j += 1
                Tj = T_years(P, j, exp); sj = iv_at(P, j); Sj = P["c"][j]
                val = bs(Sj, short_k, Tj, sj, call) - bs(Sj, long_k, Tj, sj, call)
                cost = min(width, val * 1.05 + 0.02)
                pnl = credit - cost
                reason = None
                if pnl >= credit * p["tp"] / 100:
                    reason = "tp"
                elif p["stop_mult"] and cost >= credit * p["stop_mult"]:
                    reason = "sl"
                elif (exp - P["d"][j]).days <= p["exit_dte"]:
                    reason = "time"
                if reason:
                    out = (pnl, reason); break
            if not out:
                break
            trades.append({"t": t, "d": P["t"][i], "pnl": out[0] * 100, "risk": max_loss * 100, "why": out[1], "days": j - i})
            busy_until = j
    return trades


# ── scoring the results ───────────────────────────────────────────────
def summarize(trades):
    n = len(trades)
    if not n:
        return None
    wins = [x for x in trades if x["pnl"] > 0]
    losses = [x for x in trades if x["pnl"] <= 0]
    gw = sum(x["pnl"] for x in wins); gl = -sum(x["pnl"] for x in losses)
    eq = pk = 0; dd = 0
    for x in sorted(trades, key=lambda z: z["d"]):
        eq += x["pnl"]; pk = max(pk, eq); dd = max(dd, pk - eq)
    risk = sum(x["risk"] for x in trades) / n
    return {"n": n, "wr": len(wins) / n * 100, "avg_win": gw / len(wins) if wins else 0,
            "avg_loss": -gl / len(losses) if losses else 0, "exp": (gw - gl) / n, "pf": gw / gl if gl else 99,
            "total": gw - gl, "max_dd": dd, "worst": min(x["pnl"] for x in trades), "avg_risk": risk,
            "ret_on_risk": (gw - gl) / n / risk * 100 if risk else 0,
            "avg_days": sum(x["days"] for x in trades) / n,
            "years": sorted({x["d"][:4] for x in trades})}


def by_year(trades):
    out = {}
    for x in trades:
        out.setdefault(x["d"][:4], []).append(x)
    return {y: summarize(v) for y, v in sorted(out.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", action="store_true")
    a = ap.parse_args()
    data_raw = json.loads(BARS_F.read_text()) if (a.cached and BARS_F.exists()) else fetch_bars()
    if not data_raw:
        sys.exit("No price history loaded.")
    data = {t: prep(B) for t, B in data_raw.items()}
    print("Precomputing daily scores…", flush=True)
    cache = {}
    for t, P in data.items():
        cache[t] = {}
        for i in range(260, P["n"]):
            ind = ind_at(P, i)
            if not ind:
                cache[t][i] = (None, None); continue
            pc = P["c"][i - 1]
            m = {"ticker": t, "price": P["c"][i], "pct": (P["c"][i] - pc) / pc * 100, "vol": P["v"][i]}
            M.session_frac = lambda: 1.0
            # use indicators from the prior day for avg volume comparisons, current close for price
            cache[t][i] = (ind, M.score(m, ind))

    results = []
    grid_buy = [dict(min_score=ms, otm=otm, dte=dte, tp=tp, sl=sl, trail=tr, time_stop=7, trend_only=to)
                for ms, otm, dte, tp, sl, tr, to in itertools.product(
                    [55, 60, 70], [0, 2], [21, 35], [10, 20, 50], [35, 50, 100], [0, 15], [False, True])]
    for p in grid_buy:
        s = summarize(run_buy(data, cache, p))
        if s:
            results.append({"family": "A · buy options", "p": p, "s": s})
    grid_cr = [dict(delta=d, dte=dte, width_pct=w, tp=tp, stop_mult=sm, exit_dte=ed, trend_filter=tf, both_sides=bsd, etf_only=eo, max_rsi=mr)
               for d, dte, w, tp, sm, ed, tf, bsd, eo, mr in itertools.product(
                   [0.10, 0.16, 0.20, 0.30], [30, 45], [2, 4], [50, 75], [0, 2, 3], [7, 21], [True], [False, True], [True, False], [0, 70])]
    for k, p in enumerate(grid_cr):
        s = summarize(run_credit(data, cache, p))
        if s:
            results.append({"family": "B · credit spreads", "p": p, "s": s})
        if k % 100 == 0:
            print("credit configs %d/%d" % (k, len(grid_cr)), flush=True)

    ok = [r for r in results if r["s"]["n"] >= 30]
    target = [r for r in ok if r["s"]["wr"] >= 75 and r["s"]["exp"] > 0]
    target.sort(key=lambda r: (-r["s"]["ret_on_risk"], -r["s"]["wr"]))
    best_any = sorted(ok, key=lambda r: -r["s"]["exp"])[:10]
    cur = [r for r in ok if r["family"].startswith("A") and r["p"] == dict(min_score=60, otm=2, dte=21, tp=20, sl=35, trail=0, time_stop=7, trend_only=False)]

    # per-year check for the top candidates (robustness)
    top = target[:8]
    for r in top:
        tr = run_credit(data, cache, r["p"]) if r["family"].startswith("B") else run_buy(data, cache, r["p"])
        r["years"] = {y: {"n": s["n"], "wr": round(s["wr"]), "total": round(s["total"])} for y, s in by_year(tr).items()}

    span = "%s → %s" % (min(P["t"][260] for P in data.values()), max(P["t"][-1] for P in data.values()))
    L = []
    L.append("MAKE ME TRADE — BACKTEST  (%s, %d tickers, modeled option prices)" % (span, len(data)))
    L.append("Configs tested: %d · with 30+ trades: %d · hitting ≥75%% wins AND profitable: %d" % (len(results), len(ok), len(target)))
    def fmt(r):
        s, p = r["s"], r["p"]
        return "%-18s n=%-4d win=%4.1f%%  avg win=$%-6.0f avg loss=$%-7.0f exp=$%-6.0f/trade  ret/risk=%5.1f%%  PF=%4.2f  worst=$%-6.0f maxDD=$%-6.0f  %s" % (
            r["family"], s["n"], s["wr"], s["avg_win"], s["avg_loss"], s["exp"], s["ret_on_risk"], s["pf"], s["worst"], s["max_dd"], json.dumps(p))
    L.append("\nCURRENT BOT SETTINGS (buy, score≥60, 2% OTM, 21 DTE, +20% / -35%):")
    L += [fmt(r) for r in cur] or ["(not enough trades)"]
    L.append("\nTOP CONFIGS WITH ≥75% WIN RATE AND POSITIVE EXPECTANCY (by return on risk):")
    for r in top:
        L.append(fmt(r)); L.append("     by year: " + json.dumps(r.get("years")))
    if not top:
        L.append("(none)")
    L.append("\nTOP 10 BY EXPECTANCY (any win rate):")
    L += [fmt(r) for r in best_any]
    rep = "\n".join(L)
    print("\n" + rep)
    (BASE / "backtest_report.txt").write_text(rep + "\n")
    (BASE / "backtest_results.json").write_text(json.dumps({"span": span, "current": cur, "target": target[:25], "best_any": best_any}, default=str))


if __name__ == "__main__":
    main()
