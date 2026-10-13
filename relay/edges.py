#!/usr/bin/env python3
"""
Make Me Trade — edge scanner (deep dig).

Step 1  Pull daily bars for an expanded list (adds NFLX, GOOGL, TSLA, AMD, AVGO, PLTR) into bt_bars.json.
Step 2  Measure ~30 stock-level signals: how often the stock moves the right way 3/5/10 days later,
        vs. the base rate, on the OLDER half and the NEWER half separately.
Step 3  Signals that beat the base rate on BOTH halves get traded with calls/puts (modeled prices),
        again checked on both halves.
Step 4  12-month growth simulation from $2,500 combining the survivors with the credit spreads.

Usage: python3 edges.py           (fetches missing tickers from Webull, then runs)
       python3 edges.py --cached  (no fetching)
"""
import argparse
import datetime as dt
import itertools
import json
import math
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import backtest as BT  # noqa: E402
import swings as SW    # noqa: E402

TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "AMZN", "MSFT", "META", "GOOGL", "NFLX", "TSLA", "AMD", "AVGO", "PLTR"]


def fetch_missing():
    have = json.loads(BT.BARS_F.read_text()) if BT.BARS_F.exists() else {}
    need = [t for t in TICKERS if t not in have or len(have[t]["c"]) < 600]
    if not need:
        return have
    import mmt_bot as M
    wb = M.WB()
    for t in need:
        for attempt in range(3):
            got = None
            for cnt in (1000, 800, 600):
                try:
                    b = wb.daily_bars([t], cnt)
                    if b.get(t) and len(b[t]["c"]) > 400:
                        got = b[t]; break
                except Exception:
                    pass
            if got:
                have[t] = got
                print("bars %s: %d days" % (t, len(got["c"])), flush=True)
                break
            time.sleep(3)
        else:
            print("bars %s: failed" % t, flush=True)
        time.sleep(1)
    BT.BARS_F.write_text(json.dumps(have))
    return have


def enrich(P):
    SW.enrich(P)
    c, h, l = P["c"], P["h"], P["l"]
    n = len(c)
    P["atr"] = [None] * n
    for i in range(15, n):
        P["atr"][i] = BT.M.atr(h[i - 15:i + 1], l[i - 15:i + 1], c[i - 15:i + 1], 14)
    P["hi252"] = [max(c[max(0, i - 252):i]) if i >= 60 else None for i in range(n)]
    P["ibs"] = [((c[i] - l[i]) / (h[i] - l[i])) if h[i] > l[i] else 0.5 for i in range(n)]
    P["ret"] = [None] + [c[i] / c[i - 1] - 1 for i in range(1, n)]
    hv = P["hv"]; P["hvr"] = [None] * n
    for i in range(260, n):
        w = [x for x in hv[i - 252:i + 1] if x is not None]
        P["hvr"][i] = (hv[i] - min(w)) / (max(w) - min(w)) * 100 if w and max(w) > min(w) else 50
    return P


# signal(P, i) -> "C" | "P" | None ; all evaluated at the close of day i
def _up(P, i): return P["c"][i] > P["s200"][i]
def _dn(P, i): return P["c"][i] < P["s200"][i]
def _strong(P, i): return P["c"][i] > P["s50"][i] > P["s200"][i]
def _downs(P, i, k): return all(P["c"][j] < P["c"][j - 1] for j in range(i - k + 1, i + 1))
def _ups(P, i, k): return all(P["c"][j] > P["c"][j - 1] for j in range(i - k + 1, i + 1))
def _shock(P, i): return P["atr"][i] and abs(P["c"][i] - P["c"][i - 1]) > 2.5 * P["atr"][i] and P["v"][i] > 2.5 * P["v20"][i]
def _lowvol(P, i): return P["hvr"][i] is not None and P["hvr"][i] < 50

SIGNALS = {
    # mean-reversion longs (calls)
    "RSI2<5 in uptrend":              lambda P, i: "C" if _up(P, i) and P["r2"][i] < 5 else None,
    "RSI2<10 in uptrend":             lambda P, i: "C" if _up(P, i) and P["r2"][i] < 10 else None,
    "RSI2<10 strong trend":           lambda P, i: "C" if _strong(P, i) and P["r2"][i] < 10 else None,
    "RSI2<10 uptrend + low vol":      lambda P, i: "C" if _up(P, i) and P["r2"][i] < 10 and _lowvol(P, i) else None,
    "3 down days in uptrend":         lambda P, i: "C" if _up(P, i) and _downs(P, i, 3) else None,
    "4 down days in uptrend":         lambda P, i: "C" if _up(P, i) and _downs(P, i, 4) else None,
    "IBS<0.15 in uptrend":            lambda P, i: "C" if _up(P, i) and P["ibs"][i] < 0.15 else None,
    "IBS<0.15 + RSI2<20 uptrend":     lambda P, i: "C" if _up(P, i) and P["ibs"][i] < 0.15 and P["r2"][i] < 20 else None,
    ">3% under 10d MA in uptrend":    lambda P, i: "C" if _up(P, i) and P["c"][i] < P["s10"][i] * 0.97 else None,
    ">5% under 10d MA in uptrend":    lambda P, i: "C" if _up(P, i) and P["c"][i] < P["s10"][i] * 0.95 else None,
    "Shock drop in uptrend (fade)":   lambda P, i: "C" if _up(P, i) and _shock(P, i) and P["ret"][i] < 0 else None,
    # momentum longs
    "Shock pop (follow)":             lambda P, i: "C" if _shock(P, i) and P["ret"][i] > 0 else None,
    "New 52w high":                   lambda P, i: "C" if P["hi252"][i] and P["c"][i] > P["hi252"][i] else None,
    "New 52w high + low vol":         lambda P, i: "C" if P["hi252"][i] and P["c"][i] > P["hi252"][i] and _lowvol(P, i) else None,
    "20d breakout on volume":         lambda P, i: "C" if P["c"][i] > P["hi20"][i] and P["v"][i] > 1.5 * P["v20"][i] and _strong(P, i) else None,
    "3 up days strong trend":         lambda P, i: "C" if _strong(P, i) and _ups(P, i, 3) else None,
    # puts
    "RSI2>95 in downtrend":           lambda P, i: "P" if _dn(P, i) and P["r2"][i] > 95 else None,
    "RSI2>90 in downtrend":           lambda P, i: "P" if _dn(P, i) and P["r2"][i] > 90 else None,
    "3 up days in downtrend":         lambda P, i: "P" if _dn(P, i) and _ups(P, i, 3) else None,
    "IBS>0.85 in downtrend":          lambda P, i: "P" if _dn(P, i) and P["ibs"][i] > 0.85 else None,
    "Shock drop (follow)":            lambda P, i: "P" if _shock(P, i) and P["ret"][i] < 0 else None,
    "20d breakdown on volume":        lambda P, i: "P" if P["c"][i] < P["lo20"][i] and P["v"][i] > 1.5 * P["v20"][i] and P["c"][i] < P["s50"][i] < P["s200"][i] else None,
    "RSI2>95 in UPtrend (fade top)":  lambda P, i: "P" if _up(P, i) and P["r2"][i] > 97 and P["c"][i] > P["s10"][i] * 1.05 else None,
}


PUTS = {"RSI2>95 in downtrend", "RSI2>90 in downtrend", "3 up days in downtrend", "IBS>0.85 in downtrend",
        "Shock drop (follow)", "20d breakdown on volume", "RSI2>95 in UPtrend (fade top)"}


def ready(P, i):
    return i >= 260 and None not in (P["s200"][i], P["s50"][i], P["s10"][i], P["r2"][i], P["hi20"][i], P["v20"][i], P["atr"][i])


def stock_edges(data, split):
    """forward return stats per signal vs base rate, per half"""
    H = (3, 5, 10)
    base = {h: {"old": [0, 0], "new": [0, 0]} for h in H}
    out = {}
    for name, fn in SIGNALS.items():
        out[name] = {h: {"old": [], "new": []} for h in H}
    for t, P in data.items():
        for i in range(260, P["n"] - 11):
            if not ready(P, i):
                continue
            half = "old" if P["t"][i] < split else "new"
            for h in H:
                r = P["c"][i + h] / P["c"][i] - 1
                base[h][half][0] += r > 0; base[h][half][1] += 1
            for name, fn in SIGNALS.items():
                d = fn(P, i)
                if not d:
                    continue
                for h in H:
                    r = (P["c"][i + h] / P["c"][i] - 1) * (1 if d == "C" else -1)
                    out[name][h][half].append(r)
    rows = []
    for name, by_h in out.items():
        for h in H:
            o, n = by_h[h]["old"], by_h[h]["new"]
            if len(o) < 15 or len(n) < 15:
                continue
            bo = base[h]["old"][0] / base[h]["old"][1] * 100; bn = base[h]["new"][0] / base[h]["new"][1] * 100
            if name in PUTS:
                bo, bn = 100 - bo, 100 - bn
            wo = sum(1 for x in o if x > 0) / len(o) * 100; wn = sum(1 for x in n if x > 0) / len(n) * 100
            ao = sum(o) / len(o) * 100; an = sum(n) / len(n) * 100
            rows.append({"name": name, "h": h, "n": len(o) + len(n), "wo": wo, "wn": wn, "bo": bo, "bn": bn, "ao": ao, "an": an,
                         "edge": min(wo - bo, wn - bn), "robust": wo - bo >= 5 and wn - bn >= 5 and ao > 0 and an > 0})
    return rows


def run_opts(data, fn, p):
    trades = []
    for t, P in data.items():
        busy = -1
        for i in range(260, P["n"] - 2):
            if i <= busy or not ready(P, i):
                continue
            d = fn(P, i)
            if not d:
                continue
            call = d == "C"; S = P["c"][i]
            exp = BT.day_index_after(P, i, p["dte"]); T = BT.T_years(P, i, exp); sig = BT.iv_at(P, i)
            K = BT.snap(BT.strike_for_delta(S, T, sig, p["delta"], call), S)
            mid = BT.bs(S, K, T, sig, call)
            if mid < 0.2:
                continue
            entry = mid + max(0.02, mid * 0.015)
            out = None; j = i
            while j + 1 < P["n"]:
                j += 1
                v = BT.bs(P["c"][j], K, BT.T_years(P, j, exp), BT.iv_at(P, j), call)
                bid = max(0.0, v - max(0.02, v * 0.015))
                pct = (bid / entry - 1) * 100
                why = None
                if p["tp"] and pct >= p["tp"]: why = "tp"
                elif p["sl"] and pct <= -p["sl"]: why = "sl"
                elif j - i >= p["hold"]: why = "time"
                if why:
                    out = (bid, why); break
            if not out:
                break
            trades.append({"t": t, "d": P["t"][i], "pnl": (out[0] - entry) * 100, "risk": entry * 100, "r": out[0] / entry - 1,
                           "why": out[1], "days": j - i, "stock_win": (P["c"][j] / S - 1) * (1 if call else -1) > 0})
            busy = j
    return trades


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--cached", action="store_true"); a = ap.parse_args()
    raw = json.loads(BT.BARS_F.read_text()) if a.cached else fetch_missing()
    data = {t: enrich(BT.prep(B)) for t, B in raw.items() if len(B["c"]) > 400}
    dates = sorted({P["t"][i] for P in data.values() for i in range(260, P["n"])})
    split = dates[len(dates) // 2]
    years = (dt.date.fromisoformat(dates[-1]) - dt.date.fromisoformat(dates[0])).days / 365
    L = ["EDGE SCANNER · %s → %s · %d tickers: %s · split %s" % (dates[0], dates[-1], len(data), ",".join(sorted(data)), split)]

    rows = stock_edges(data, split)
    rob = sorted([r for r in rows if r["robust"]], key=lambda r: -r["edge"])
    L.append("\nSTEP 1 — STOCK SIGNALS THAT BEAT THE BASE RATE BY 5+ PTS ON BOTH HALVES (%d of %d signal/horizon combos)" % (len(rob), len(rows)))
    L.append("  (win = stock moved the right way after N days · base = how often ANY day did · avg = avg stock move in your favor)")
    for r in rob[:20]:
        L.append("  %-30s %2dd  n=%-4d  older win %2.0f%% (base %2.0f, avg %+.2f%%)  newer win %2.0f%% (base %2.0f, avg %+.2f%%)" % (
            r["name"], r["h"], r["n"], r["wo"], r["bo"], r["ao"], r["wn"], r["bn"], r["an"]))
    if not rob:
        L.append("  (none)")
    weak = sorted([r for r in rows if not r["robust"]], key=lambda r: -r["edge"])[:6]
    L.append("  Closest misses: " + "; ".join("%s %dd (%.0f/%.0f vs %.0f/%.0f)" % (r["name"], r["h"], r["wo"], r["wn"], r["bo"], r["bn"]) for r in weak))

    # step 2: options on robust signals
    names = list(dict.fromkeys(r["name"] for r in rob))[:10]
    L.append("\nSTEP 2 — TRADED WITH OPTIONS (modeled prices, 1.5%+2c slippage each way) — best settings picked on OLDER half")
    winners = []
    for name in names:
        fn = SIGNALS[name]; best = None
        for delta, dte, tp, sl, hold in itertools.product([0.5, 0.7, 0.85], [30, 45, 75], [0, 25, 50], [0, 50], [3, 5, 10]):
            p = dict(delta=delta, dte=dte, tp=tp, sl=sl, hold=hold)
            tr = run_opts(data, fn, p)
            old = SW.stats([x for x in tr if x["d"] < split]); new = SW.stats([x for x in tr if x["d"] >= split])
            if not old or not new or old["n"] < 12 or new["n"] < 12:
                continue
            if best is None or old["avg_r"] > best["old"]["avg_r"]:
                best = {"name": name, "p": p, "old": old, "new": new, "all": SW.stats(tr), "tr": tr}
        if not best:
            continue
        ok = best["new"]["avg_r"] > 0 and best["new"]["exp"] > 0
        b = best
        L.append("  %s %-30s  n=%d (%.0f/yr) win %.0f%% avg %+.1f%%/trade · older %.0f%%/%+.1f%% · newer %.0f%%/%+.1f%% · worst $%.0f · %s" % (
            "✅" if ok else "❌", name, b["all"]["n"], b["all"]["n"] / years, b["all"]["wr"], b["all"]["avg_r"],
            b["old"]["wr"], b["old"]["avg_r"], b["new"]["wr"], b["new"]["avg_r"], b["all"]["worst"], json.dumps(b["p"])))
        if ok:
            b["per_yr"] = b["all"]["n"] / years
            winners.append(b)

    # step 3: growth sim
    streams = []
    ct = SW.credit_trades(data)
    if ct:
        streams.append(("Credit spreads", [x["r"] for x in ct], len(ct) / years))
    used = set()
    for w in sorted(winners, key=lambda w: -w["new"]["avg_r"]):
        streams.append((w["name"] + " (options)", [x["r"] for x in w["tr"]], w["per_yr"]))
    L.append("\nSTEP 3 — 12-MONTH GROWTH SIM FROM $2,500 (10,000 runs; optimistic: ignores overlapping trades & crashes)")
    for label, sel in (("Credit spreads only", streams[:1]), ("Everything that survived", streams)):
        if not sel:
            continue
        L.append("  " + label + ": " + ", ".join("%s %.0f/yr avg %+.1f%%" % (s[0], s[2], sum(s[1]) / len(s[1]) * 100) for s in sel))
        for rp in (3, 5, 10, 15):
            mc = SW.monte_carlo([(s[1], s[2]) for s in sel], rp)
            L.append("    risk %2d%%/trade → P10 $%s · P50 $%s · P90 $%s · hit $100K %.1f%% · lost half %.1f%%" % (
                rp, format(round(mc["p10"]), ","), format(round(mc["median"]), ","), format(round(mc["p90"]), ","), mc["hit"], mc["half"]))
    rep = "\n".join(L)
    print("\n" + rep)
    (BASE / "edges_report.txt").write_text(rep + "\n")
    (BASE / "edges_winners.json").write_text(json.dumps([{k: v for k, v in w.items() if k != "tr"} for w in winners], default=str))


if __name__ == "__main__":
    main()
