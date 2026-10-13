#!/usr/bin/env python3
"""
Make Me Trade — swing strategy lab + growth simulator.

Tests classic swing setups on the watchlist (daily bars from bt_bars.json), traded with
long calls/puts, then picks robust ones (chosen on the OLDER half, checked on the NEWER half)
and runs a Monte Carlo of 12 months starting from $2,500 at several risk levels.

Setups
  S1 pullback call   : uptrend (close > 200d) + RSI(2) washed out  → call, exit on bounce over 5d MA
  S2 bounce put      : downtrend (close < 200d) + RSI(2) overbought → put,  exit on drop under 5d MA
  S3 breakout call   : 20-day high on 1.5x volume in an uptrend     → call
  S4 breakdown put   : 20-day low on 1.5x volume in a downtrend     → put
  S5 20-MA pullback  : strong uptrend, dips to the 20d MA and holds → call

Option prices are MODELED (Black-Scholes, IV ≈ 1.15 × 20-day realized vol, 1% + 2c slippage each way).
Usage: python3 swings.py      (needs relay/bt_bars.json from backtest.py)
"""
import datetime as dt
import itertools
import json
import math
import random
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import backtest as BT  # noqa: E402
import mmt_bot as M    # noqa: E402

START = 2500.0
TARGET = 100000.0


def sma_series(c, k):
    out = [None] * len(c); s = 0.0
    for i, x in enumerate(c):
        s += x
        if i >= k: s -= c[i - k]
        if i >= k - 1: out[i] = s / k
    return out


def rsi_series(c, n=2):
    out = [None] * len(c)
    if len(c) <= n: return out
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]; g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    out[n] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n; l = (l * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def enrich(P):
    c, v, lo = P["c"], P["v"], P["l"]
    P["s5"], P["s10"], P["s20"], P["s50"], P["s200"] = (sma_series(c, k) for k in (5, 10, 20, 50, 200))
    P["r2"] = rsi_series(c, 2)
    n = len(c)
    P["hi20"] = [max(c[i - 20:i]) if i >= 20 else None for i in range(n)]
    P["lo20"] = [min(c[i - 20:i]) if i >= 20 else None for i in range(n)]
    P["v20"] = [sum(v[i - 20:i]) / 20 if i >= 20 else None for i in range(n)]
    return P


def signal(P, i, s, p):
    c = P["c"][i]; s5, s20, s50, s200 = P["s5"][i], P["s20"][i], P["s50"][i], P["s200"][i]
    if None in (s20, s50, s200, P["r2"][i], P["hi20"][i], P["v20"][i]): return None
    r2 = P["r2"][i]; vol_ok = P["v"][i] > 1.5 * P["v20"][i]
    if s == "S1" and c > s200 and r2 < p["rsi_lo"]: return "C"
    if s == "S2" and c < s200 and r2 > p["rsi_hi"]: return "P"
    if s == "S3" and c > P["hi20"][i] and vol_ok and c > s50 > s200: return "C"
    if s == "S4" and c < P["lo20"][i] and vol_ok and c < s50 < s200: return "P"
    if s == "S5" and c > s50 > s200 and P["l"][i] <= s20 * 1.005 and c > s20: return "C"
    return None


def signal_exit(P, j, s, call):
    c = P["c"][j]
    if s in ("S1", "S5"): return c > P["s5"][j]
    if s == "S2": return c < P["s5"][j]
    if s == "S3": return c < P["s10"][j]
    if s == "S4": return c > P["s10"][j]
    return False


def run(data, s, p):
    trades = []
    for t, P in data.items():
        busy = -1
        for i in range(210, P["n"] - 2):
            if i <= busy: continue
            d = signal(P, i, s, p)
            if not d: continue
            call = d == "C"; S = P["c"][i]
            exp = BT.day_index_after(P, i, p["dte"]); T = BT.T_years(P, i, exp); sig = BT.iv_at(P, i)
            K = BT.snap(BT.strike_for_delta(S, T, sig, p["delta"], call), S)
            mid = BT.bs(S, K, T, sig, call)
            if mid < 0.2: continue
            entry = mid + max(0.02, mid * 0.01)
            out = None; j = i
            while j + 1 < P["n"]:
                j += 1
                v = BT.bs(P["c"][j], K, BT.T_years(P, j, exp), BT.iv_at(P, j), call)
                bid = max(0.0, v - max(0.02, v * 0.01))
                pct = (bid / entry - 1) * 100
                why = None
                if p["tp"] and pct >= p["tp"]: why = "tp"
                elif p["sl"] and pct <= -p["sl"]: why = "sl"
                elif p["sig_exit"] and signal_exit(P, j, s, call): why = "signal"
                elif j - i >= p["max_hold"]: why = "time"
                elif (exp - P["d"][j]).days <= 5: why = "expiry"
                if why: out = (bid, why); break
            if not out: break
            stock_ret = (P["c"][j] / S - 1) * (1 if call else -1)
            trades.append({"t": t, "d": P["t"][i], "pnl": (out[0] - entry) * 100, "risk": entry * 100,
                           "r": out[0] / entry - 1, "why": out[1], "days": j - i, "stock_win": stock_ret > 0})
            busy = j
    return trades


def stats(tr):
    s = BT.summarize(tr)
    if not s: return None
    s["avg_r"] = sum(x["r"] for x in tr) / len(tr) * 100
    s["stock_wr"] = sum(1 for x in tr if x["stock_win"]) / len(tr) * 100
    return s


def credit_trades(data):
    """Small-account credit spread winner, for the combined simulation."""
    cache = {}
    sub = {t: data[t] for t in ("SPY", "QQQ") if t in data}
    for t, P in sub.items():
        cache[t] = {}
        for i in range(260, P["n"]):
            ind = BT.ind_at(P, i)
            cache[t][i] = (ind, None)
    p = dict(delta=0.30, dte=45, width_pct=0, width_usd=2, tp=75, stop_mult=0, exit_dte=7, both_sides=True,
             etf_only=True, max_rsi=70, ladder=2, spacing=5, max_risk=0, fee=0.26)
    tr = BT.run_credit(sub, cache, p)
    for x in tr:
        x["r"] = x["pnl"] / x["risk"] if x["risk"] else 0
    return tr


def monte_carlo(streams, risk_pct, months=12, runs=10000, seed=7):
    """streams: list of (returns list r, trades per year). Each trade risks risk_pct of current equity;
    r = return on the money risked (-1 = lose all of it)."""
    rnd = random.Random(seed)
    finals = []; ruined = 0
    for _ in range(runs):
        eq = START; low = START
        events = []
        for rs, per_yr in streams:
            n = int(round(per_yr * months / 12 + rnd.gauss(0, math.sqrt(per_yr * months / 12))))
            events += [rs] * max(0, n)
        rnd.shuffle(events)
        for rs in events:
            stake = eq * risk_pct / 100
            eq += stake * rnd.choice(rs)
            low = min(low, eq)
            if eq < 100: eq = 0; break
        finals.append(eq)
        if low <= START * 0.5: ruined += 1
    finals.sort()
    q = lambda f: finals[min(len(finals) - 1, int(f * len(finals)))]
    return {"p10": q(0.10), "median": q(0.5), "p90": q(0.90), "hit": sum(1 for x in finals if x >= TARGET) / runs * 100,
            "half": ruined / runs * 100, "wipe": sum(1 for x in finals if x < START * 0.1) / runs * 100}


def main():
    if not BT.BARS_F.exists():
        sys.exit("Run backtest.py first (needs bt_bars.json).")
    raw = json.loads(BT.BARS_F.read_text())
    data = {t: enrich(BT.prep(B)) for t, B in raw.items()}
    dates = sorted({P["t"][i] for P in data.values() for i in range(210, P["n"])})
    split = dates[len(dates) // 2]
    years = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days / 365
    print("Data %s → %s · %d tickers · split %s" % (dates[0], dates[-1], len(data), split), flush=True)

    grid = []
    for s in ("S1", "S2", "S3", "S4", "S5"):
        for delta, dte, tp, sl, mh, se in itertools.product([0.5, 0.7], [21, 45], [0, 30, 50], [0, 50], [3, 5, 10], [True, False]):
            for lo, hi in ([(5, 95), (10, 90)] if s in ("S1", "S2") else [(10, 90)]):
                grid.append((s, dict(delta=delta, dte=dte, tp=tp, sl=sl, max_hold=mh, sig_exit=se, rsi_lo=lo, rsi_hi=hi)))
    res = []
    for k, (s, p) in enumerate(grid):
        tr = run(data, s, p)
        a = stats(tr)
        if not a or a["n"] < 30: continue
        old = stats([x for x in tr if x["d"] < split]); new = stats([x for x in tr if x["d"] >= split])
        res.append({"s": s, "p": p, "all": a, "old": old, "new": new, "per_yr": a["n"] / years, "tr": tr})
        if k % 200 == 0: print("swing configs %d/%d" % (k, len(grid)), flush=True)

    def robust(r, wr):
        return r["old"] and r["new"] and r["old"]["n"] >= 12 and r["new"]["n"] >= 12 and r["old"]["exp"] > 0 and r["new"]["exp"] > 0 \
            and r["old"]["wr"] >= wr and r["new"]["wr"] >= wr - 5
    names = {"S1": "Pullback CALL (uptrend, RSI2 dip)", "S2": "Bounce PUT (downtrend, RSI2 pop)", "S3": "Breakout CALL",
             "S4": "Breakdown PUT", "S5": "20-day MA pullback CALL"}
    L = ["SWING LAB · %s → %s · %d tickers · modeled option prices · picked on older half, checked on newer half" % (dates[0], dates[-1], len(data))]
    best = {}
    for s in names:
        rs = [r for r in res if r["s"] == s]
        if not rs: continue
        rob = sorted([r for r in rs if robust(r, 60)], key=lambda r: -r["old"]["avg_r"])
        top = rob[0] if rob else sorted(rs, key=lambda r: -r["old"]["avg_r"])[0]
        best[s] = (top, bool(rob))
        a, o, n = top["all"], top["old"], top["new"]
        L.append("\n%s %s — %s" % (s, names[s], "HOLDS UP on newer data" if rob else "does NOT hold up (best shown)"))
        L.append("  stock direction right: %.0f%% · option trades n=%d (%.0f/yr) win=%.0f%% avg return on premium %+.1f%% exp=$%.0f/contract worst=$%.0f" % (
            a["stock_wr"], a["n"], top["per_yr"], a["wr"], a["avg_r"], a["exp"], a["worst"]))
        L.append("  older half: win %.0f%% avg %+.1f%% · newer half: win %.0f%% avg %+.1f%%" % (o["wr"], o["avg_r"], n["wr"], n["avg_r"]) if o and n else "  halves: n/a")
        L.append("  settings: %s · robust configs: %d of %d" % (json.dumps(top["p"]), len(rob), len(rs)))

    # growth simulation
    streams = {}
    ct = credit_trades(data)
    if ct:
        streams["Credit spreads ($2, SPY/QQQ)"] = ([x["r"] for x in ct], len(ct) / max(years, 0.5))
    for s, (top, ok) in best.items():
        if ok:
            streams["%s %s" % (s, names[s])] = ([x["r"] for x in top["tr"]], top["per_yr"])
    L.append("\n\nGROWTH SIMULATION · start $2,500 · 12 months · 10,000 runs · each trade risks X% of the account")
    L.append("(P50 = typical outcome · P10/P90 = bad/good years · 'hit' = chance of reaching $100K · 'lost half' = chance the account fell 50%+ at some point)")
    combos = list(streams.items())
    if len(combos) > 1:
        combos.append(("ALL robust strategies together", None))
    for name, st in combos:
        L.append("\n" + name + ("" if st is None else "  (%.0f trades/yr, avg return per trade %+.1f%% of risk)" % (st[1], sum(st[0]) / len(st[0]) * 100)))
        for rp in (2, 5, 10, 20, 35):
            mc = monte_carlo([st] if st else list(streams.values()), rp)
            L.append("  risk %2d%%/trade → P10 $%-8s P50 $%-8s P90 $%-9s · hit $100K %4.1f%% · lost half %4.1f%% · wiped out %4.1f%%" % (
                rp, format(round(mc["p10"]), ","), format(round(mc["median"]), ","), format(round(mc["p90"]), ","), mc["hit"], mc["half"], mc["wipe"]))
    rep = "\n".join(L)
    print("\n" + rep)
    (BASE / "swing_report.txt").write_text(rep + "\n")


if __name__ == "__main__":
    main()
