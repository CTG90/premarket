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
def fetch_bars(count=1700):
    wb = M.WB()
    out = {}
    for t in WATCH:
        b = {}
        for cnt in (count, 1500, 1250, 1000, 800):
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
        open_exits = []; last_entry = -999
        for i in range(260, P["n"] - 2):
            open_exits = [x for x in open_exits if x > i]
            if len(open_exits) >= p["ladder"] or i - last_entry < p["spacing"]:
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
            else:
                continue
            if p["max_rsi"] and ind["rsi"] is not None and not call and ind["rsi"] > p["max_rsi"]:
                continue
            exp = day_index_after(P, i, p["dte"])
            T = T_years(P, i, exp); sig = iv_at(P, i)
            short_k = snap(strike_for_delta(S, T, sig, p["delta"], call), S)
            width = p["width_usd"] if p["width_usd"] else max(M.strike_step(S), snap(S * p["width_pct"] / 100, S))
            long_k = short_k + width if call else short_k - width
            credit_mid = bs(S, short_k, T, sig, call) - bs(S, long_k, T, sig, call)
            credit = credit_mid * 0.95 - 0.02
            if credit < width * 0.08:
                continue
            max_loss = width - credit
            if p["max_risk"] and max_loss * 100 > p["max_risk"]:
                continue
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
            trades.append({"t": t, "d": P["t"][i], "pnl": out[0] * 100 - p.get("fee", 0.26), "risk": max_loss * 100, "why": out[1], "days": j - i})
            open_exits.append(j); last_entry = i
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
    ap.add_argument("--small", type=float, default=0, help="account size: test narrow spreads sized for it")
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

    if a.small:
        return small_account(data, cache, a.small)
    all_dates = sorted({P["t"][i] for P in data.values() for i in range(260, P["n"])})
    split = all_dates[len(all_dates) // 2]
    yrs = max(0.5, (dt.date.fromisoformat(all_dates[-1]) - dt.date.fromisoformat(all_dates[0])).days / 365)

    def evaluate(family, p, trades):
        s_all = summarize(trades)
        if not s_all or s_all["n"] < 30:
            return None
        tr = summarize([x for x in trades if x["d"] < split]); te = summarize([x for x in trades if x["d"] >= split])
        return {"family": family, "p": p, "s": s_all, "train": tr, "test": te, "per_year": s_all["total"] / yrs,
                "years": {y: {"n": v["n"], "wr": round(v["wr"]), "total": round(v["total"])} for y, v in by_year(trades).items()}}

    results = []
    grid_buy = [dict(min_score=ms, otm=otm, dte=dte, tp=tp, sl=sl, trail=tr, time_stop=7, trend_only=to)
                for ms, otm, dte, tp, sl, tr, to in itertools.product(
                    [55, 60, 70, 80], [0, 2], [21, 35, 60], [10, 20, 50], [35, 50, 100], [0, 15, 25], [False, True])]
    for k, p in enumerate(grid_buy):
        r = evaluate("A · buy options", p, run_buy(data, cache, p))
        if r: results.append(r)
        if k % 200 == 0: print("buy configs %d/%d" % (k, len(grid_buy)), flush=True)
    grid_cr = [dict(delta=d, dte=dte, width_pct=wp, width_usd=wu, tp=tp, stop_mult=sm, exit_dte=ed, both_sides=bsd,
                    etf_only=eo, max_rsi=70, ladder=ld, spacing=sp, max_risk=mr)
               for d, dte, (wp, wu), tp, sm, ed, bsd, eo, (ld, sp), mr in itertools.product(
                   [0.10, 0.16, 0.20, 0.30], [30, 45], [(0, 5), (2, 0)], [50, 75], [0, 2, 3], [7, 21], [False, True], [True, False],
                   [(1, 1), (4, 5)], [750])]
    for k, p in enumerate(grid_cr):
        r = evaluate("B · credit spreads", p, run_credit(data, cache, p))
        if r: results.append(r)
        if k % 200 == 0: print("credit configs %d/%d" % (k, len(grid_cr)), flush=True)

    def good(x, wr=75):
        return x and x["n"] >= 15 and x["wr"] >= wr and x["exp"] > 0
    # choose on the OLDER half only, then show how the choice did on the NEWER half
    picks = sorted([r for r in results if good(r["train"])], key=lambda r: -r["train"]["ret_on_risk"])[:12]
    held = [r for r in picks if good(r["test"], 70)]
    buy_picks = sorted([r for r in results if r["family"].startswith("A") and r["train"] and r["train"]["n"] >= 15 and r["train"]["exp"] > 0],
                       key=lambda r: -r["train"]["exp"])[:6]
    cur = [r for r in results if r["family"].startswith("A") and r["p"] == dict(min_score=60, otm=2, dte=21, tp=20, sl=35, trail=0, time_stop=7, trend_only=False)]

    def fmt(r):
        def part(name, s):
            if not s: return "%s: n=0" % name
            return "%s: n=%d win=%.0f%% exp=$%.0f PF=%.2f" % (name, s["n"], s["wr"], s["exp"], s["pf"])
        s = r["s"]
        return ("%-18s ALL n=%-4d win=%4.1f%% avgW=$%-5.0f avgL=$%-6.0f exp=$%-5.0f ret/risk=%5.1f%% PF=%4.2f worst=$%-6.0f maxDD=$%-6.0f $/yr=%-6.0f\n"
                "      %s | %s\n      %s\n      by year %s") % (
            r["family"], s["n"], s["wr"], s["avg_win"], s["avg_loss"], s["exp"], s["ret_on_risk"], s["pf"], s["worst"], s["max_dd"], r["per_year"],
            part("OLDER half", r["train"]), part("NEWER half", r["test"]), json.dumps(r["p"]), json.dumps(r["years"]))

    span = "%s → %s (split %s)" % (all_dates[0], all_dates[-1], split)
    L = ["MAKE ME TRADE — BACKTEST v2  %s · %d tickers · modeled option prices" % (span, len(data)),
         "Configs tested: %d · with 30+ trades: %d" % (len(grid_buy) + len(grid_cr), len(results)),
         "Picked on OLDER half with ≥75%% wins & profitable: %d · of those still ≥70%% & profitable on NEWER half: %d" % (len(picks), len(held)),
         "\nCURRENT BOT RULES:"] + [fmt(r) for r in cur]
    L.append("\nHIGH-WIN-RATE PICKS (chosen on older half, ranked by return on risk):")
    L += [fmt(r) for r in picks] or ["(none)"]
    L.append("\nBEST BUY-OPTIONS SETTINGS (chosen on older half by $/trade):")
    L += [fmt(r) for r in buy_picks] or ["(none)"]
    rep = "\n".join(L)
    print("\n" + rep)
    (BASE / "backtest_report.txt").write_text(rep + "\n")
    (BASE / "backtest_results.json").write_text(json.dumps({"span": span, "current": cur, "picks": picks, "buy_picks": buy_picks}, default=str))


def small_account(data, cache, acct):
    """Narrow SPY/QQQ credit spreads sized for a small account. Simulates the account balance."""
    rows = []
    grid = [dict(delta=d, dte=dte, width_pct=0, width_usd=w, tp=tp, stop_mult=0, exit_dte=7, both_sides=True,
                 etf_only=True, max_rsi=70, ladder=ld, spacing=5, max_risk=0, fee=0.26)
            for d, dte, w, tp, ld in itertools.product([0.20, 0.25, 0.30], [30, 45], [1, 2, 3, 5], [50, 75], [1, 2])]
    for p in grid:
        tr = sorted(run_credit(data, cache, p), key=lambda x: x["d"])
        s = summarize(tr)
        if not s or s["n"] < 30:
            continue
        # account sim: open positions overlap; approximate peak capital at risk by max concurrent risk
        bal = acct; peak = acct; dd = 0
        for x in tr:
            bal += x["pnl"]; peak = max(peak, bal); dd = max(dd, (peak - bal) / peak * 100)
        span_days = (dt.date.fromisoformat(tr[-1]["d"]) - dt.date.fromisoformat(tr[0]["d"])).days or 1
        per_yr = s["total"] / span_days * 365
        max_concurrent = 2 * p["ladder"]
        worst_case = max_concurrent * s["avg_risk"]
        half = len(tr) // 2
        a1, a2 = summarize(tr[:half]), summarize(tr[half:])
        rows.append({"p": p, "s": s, "per_yr": per_yr, "pct_yr": per_yr / acct * 100, "dd_pct": dd,
                     "risk_pct": s["avg_risk"] / acct * 100, "worst_case_pct": worst_case / acct * 100,
                     "older": a1, "newer": a2})
    ok = [r for r in rows if r["risk_pct"] <= 6 and r["worst_case_pct"] <= 30 and r["s"]["exp"] > 0
          and r["older"] and r["newer"] and r["older"]["exp"] > 0 and r["newer"]["exp"] > 0]
    ok.sort(key=lambda r: -r["per_yr"])
    L = ["SMALL ACCOUNT TEST · $%.0f · SPY/QQQ credit spreads, fee $0.26/spread round trip" % acct,
         "Configs: %d · fit risk rules (≤6%% per trade, ≤30%% all open) and profitable in BOTH halves: %d" % (len(rows), len(ok))]
    for r in ok[:12]:
        s, p = r["s"], r["p"]
        L.append("width $%d Δ%.2f %dDTE tp%d%% ladder%d | n=%d win=%.0f%% exp=$%.1f/trade | $%.0f/yr (%.0f%%/yr) | risk/trade %.1f%% · all-open %.0f%% · maxDD %.1f%% | older %.0f%%/$%.1f newer %.0f%%/$%.1f" % (
            p["width_usd"], p["delta"], p["dte"], p["tp"], p["ladder"], s["n"], s["wr"], s["exp"], r["per_yr"], r["pct_yr"],
            r["risk_pct"], r["worst_case_pct"], r["dd_pct"], r["older"]["wr"], r["older"]["exp"], r["newer"]["wr"], r["newer"]["exp"]))
    if not ok:
        L.append("(nothing fits the risk rules and stays profitable)")
    L.append("\nAll widths for reference (best per width by $/yr):")
    for w in (1, 2, 3, 5):
        ws = sorted([r for r in rows if r["p"]["width_usd"] == w], key=lambda r: -r["per_yr"])[:2]
        for r in ws:
            L.append("  $%d: win=%.0f%% exp=$%.1f $/yr=%.0f risk/trade=%.1f%% older $%.1f newer $%.1f" % (
                w, r["s"]["wr"], r["s"]["exp"], r["per_yr"], r["risk_pct"], r["older"]["exp"] if r["older"] else 0, r["newer"]["exp"] if r["newer"] else 0))
    rep = "\n".join(L)
    print(rep)
    (BASE / "small_account_report.txt").write_text(rep + "\n")
    (BASE / "small_account_results.json").write_text(json.dumps(ok[:12], default=str))


if __name__ == "__main__":
    main()
