#!/usr/bin/env python3
"""
Make Me Trade — intraday (day-trading) test.

Data (free, via yfinance): 5-minute bars for the last ~60 days, 1-hour bars for the last ~2 years.
Setups tested, each long a call (bullish) or a put (bearish), all closed the same day:
  ORB       opening-range breakout: break of the first 15/30-min (5m data) or first-hour (1h data) range
  VWAP      pullback to VWAP in a trending morning, then reclaim
  GAP-GO    gap > 0.5% that holds the first 30 min → trade in the gap direction
  GAP-FADE  gap > 0.5% that fails in the first 30 min → trade toward the prior close
  RANDOM    random entry 10:00–15:00 in a random direction — the bar every setup has to beat
Options: Black-Scholes, IV = VIX for SPY/QQQ (else 1.15x 20-day vol), ATM 0DTE and ~1-week calls/puts,
half-spread ~2% of premium each side (min $0.02). Exit: stop at the other side of the setup, target 2x risk, or 3:55 pm.
Usage: python3 intraday.py
"""
import datetime as dt
import json
import math
import random
from pathlib import Path
from statistics import NormalDist

BASE = Path(__file__).resolve().parent
F = BASE / "intraday_bars.json"
REPORT = BASE / "intraday_report.txt"
TICKERS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX", "AVGO", "PLTR"]
N = NormalDist()


def fetch():
    import yfinance as yf
    out = {}
    for t in TICKERS + ["^VIX"]:
        out[t] = {}
        for iv, per in (("5m", "60d"), ("1h", "730d"), ("1d", "2y")):
            try:
                df = yf.Ticker(t).history(period=per, interval=iv, auto_adjust=False, prepost=False)
                rows = []
                for idx, r in df.iterrows():
                    if r["Close"] != r["Close"]:
                        continue
                    ts = idx.tz_convert("America/New_York") if idx.tzinfo else idx
                    rows.append([ts.strftime("%Y-%m-%d %H:%M"), float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]), float(r["Volume"] or 0)])
                out[t][iv] = rows
                print("bars %-5s %-3s %d" % (t, iv, len(rows)), flush=True)
            except Exception as e:
                print("bars %-5s %-3s FAILED %s" % (t, iv, str(e)[:80]), flush=True)
    F.write_text(json.dumps(out))
    return out


def bs(S, K, T, sig, call):
    if T <= 1e-6:
        return max(0.0, S - K) if call else max(0.0, K - S)
    sq = sig * math.sqrt(T); d1 = (math.log(S / K) + (0.04 + sig * sig / 2) * T) / sq; d2 = d1 - sq
    return S * N.cdf(d1) - K * math.exp(-0.04 * T) * N.cdf(d2) if call else K * math.exp(-0.04 * T) * N.cdf(-d2) - S * N.cdf(-d1)


def by_day(rows):
    days = {}
    for r in rows:
        d, hm = r[0].split(" ")
        if "09:30" <= hm < "16:00":
            days.setdefault(d, []).append(r)
    return days


def strike_step(S):
    return 5 if S >= 500 else 2.5 if S >= 200 else 1 if S >= 25 else 0.5


def option_ret(S0, S1, t0, t1, day, sig, call, kind):
    """Return on premium for an ATM option bought at time t0 ("HH:MM") and sold at t1 on the same day."""
    k = round(S0 / strike_step(S0)) * strike_step(S0)
    mins = lambda hm: int(hm[:2]) * 60 + int(hm[3:])
    left0 = (960 - mins(t0)) / 390 / 252; left1 = (960 - mins(t1)) / 390 / 252
    if kind == "0dte":
        T0, T1 = left0, left1
    else:
        wd = dt.date.fromisoformat(day).weekday(); dd = (4 - wd) % 7
        dd = dd + 7 if dd < 3 else dd                  # next Friday at least 3 days out
        T0, T1 = left0 + dd / 365, left1 + dd / 365
    p0 = bs(S0, k, T0, sig, call); p1 = bs(S1, k, T1, sig, call)
    if p0 < 0.05:
        return None
    hs0 = max(0.02, p0 * 0.02); hs1 = max(0.02, p1 * 0.02) if p1 > 0.02 else 0.0
    return (max(0.0, p1 - hs1)) / (p0 + hs0) - 1


def daily_vol(drows):
    c = [r[4] for r in drows]; out = {}
    for i in range(21, len(c)):
        rs = [math.log(c[j] / c[j - 1]) for j in range(i - 19, i + 1)]; m = sum(rs) / 20
        out[drows[i][0][:10]] = math.sqrt(sum((x - m) ** 2 for x in rs) / 19 * 252)
    return out


def walk(bars, k, call, stop, target):
    """From bar k (entry at its close), exit at stop/target (checked on later bars) or the 15:55 bar close."""
    e = bars[k][4]
    for j in range(k + 1, len(bars)):
        h, l, c, hm = bars[j][2], bars[j][3], bars[j][4], bars[j][0][11:]
        if call and l <= stop: return j, stop
        if not call and h >= stop: return j, stop
        if call and h >= target: return j, target
        if not call and l <= target: return j, target
        if hm >= "15:55": return j, c
    return len(bars) - 1, bars[-1][4]


def signals(t, days, prev_close, res_min):
    """Yield (day, entry_idx, call, stop, target, setup)."""
    rng = random.Random(hash(t) & 0xffff)
    for d, bars in days.items():
        if len(bars) < (390 // res_min) * 0.8:
            continue
        pc = prev_close.get(d)
        for orm in ((15, 30) if res_min == 5 else (60,)):
            n0 = orm // res_min; hi = max(b[2] for b in bars[:n0]); lo = min(b[3] for b in bars[:n0]); rngw = hi - lo
            for k in range(n0, len(bars)):
                if bars[k][0][11:] >= "15:00": break
                c = bars[k][4]
                if c > hi:
                    yield d, k, True, lo, c + 2 * (c - lo), "ORB %dm" % orm; break
                if c < lo:
                    yield d, k, False, hi, c - 2 * (hi - c), "ORB %dm" % orm; break
        if res_min == 5:
            pv = vol = 0.0; above = 0
            for k, b in enumerate(bars):
                tp = (b[2] + b[3] + b[4]) / 3; pv += tp * b[5]; vol += b[5]
                vw = pv / vol if vol else b[4]
                hm = b[0][11:]
                if hm < "10:15":
                    above += 1 if b[4] > vw else -1; continue
                if hm >= "14:30": break
                if above >= 6 and b[3] <= vw * 1.0005 and b[4] > vw:     # trending up morning, tagged VWAP, closed back above
                    st = min(b[3], vw) * 0.998; yield d, k, True, st, b[4] + 2 * (b[4] - st), "VWAP pullback"; break
                if above <= -6 and b[2] >= vw * 0.9995 and b[4] < vw:
                    st = max(b[2], vw) * 1.002; yield d, k, False, st, b[4] - 2 * (st - b[4]), "VWAP pullback"; break
        if pc:
            o = bars[0][1]; gap = o / pc - 1; n30 = 30 // res_min if res_min <= 30 else 1
            if abs(gap) > 0.005 and len(bars) > n30:
                c30 = bars[n30 - 1][4]
                holds = (c30 > o) if gap > 0 else (c30 < o)
                if holds:
                    call = gap > 0; st = o * (0.997 if call else 1.003)
                    yield d, n30 - 1, call, st, c30 + (2 if call else -2) * abs(c30 - st), "GAP-GO"
                else:
                    call = gap < 0; st = bars[n30 - 1][3 if call else 2] * (0.998 if call else 1.002); tg = pc
                    if (call and tg > c30) or (not call and tg < c30):
                        yield d, n30 - 1, call, st, tg, "GAP-FADE"
        for _ in range(2):
            cand = [k for k, b in enumerate(bars) if "10:00" <= b[0][11:] < "15:00"]
            if cand:
                k = rng.choice(cand); call = rng.random() < 0.5; c = bars[k][4]; r = c * 0.003
                yield d, k, call, c - r if call else c + r, c + 2 * r if call else c - 2 * r, "RANDOM"


def main():
    raw = fetch()
    vix_d = {r[0][:10]: r[4] for r in raw.get("^VIX", {}).get("1d", [])}
    L = ["INTRADAY TEST · day trades, all closed same day · option = ATM, bought at entry bar close",
         "move = underlying move in your favor (%) · 0DTE / 1wk = avg return on option premium · beat RANDOM to count", ""]
    for res, iv in ((5, "5m"), (60, "1h")):
        stats = {}
        span = []
        for t in TICKERS:
            rows = raw.get(t, {}).get(iv) or []
            if not rows:
                continue
            days = by_day(rows); span += [min(days), max(days)] if days else []
            dl = raw[t].get("1d") or []
            prev = {}; ds = [r[0][:10] for r in dl]
            for i in range(1, len(dl)):
                prev[ds[i]] = dl[i - 1][4]
            hv = daily_vol(dl)
            grp = "SPY/QQQ" if t in ("SPY", "QQQ") else "stocks"
            for d, k, call, stop, target, setup in signals(t, days, prev, res):
                bars = days[d]; j, px = walk(bars, k, call, stop, target)
                S0 = bars[k][4]; mv = (px / S0 - 1) * (1 if call else -1)
                sig = (vix_d.get(d, 18) / 100) if t in ("SPY", "QQQ") else max(0.15, hv.get(d, 0.35) * 1.15)
                o0 = option_ret(S0, px, bars[k][0][11:], bars[j][0][11:] if bars[j][0][11:] < "16:00" else "15:59", d, sig, call, "0dte")
                o1 = option_ret(S0, px, bars[k][0][11:], bars[j][0][11:], d, sig, call, "1wk")
                s = stats.setdefault((setup, grp), {"n": 0, "mv": [], "o0": [], "o1": []})
                s["n"] += 1; s["mv"].append(mv)
                if o0 is not None: s["o0"].append(o0)
                if o1 is not None: s["o1"].append(o1)
        L.append("=== %s bars · %s → %s ===" % (iv, min(span) if span else "?", max(span) if span else "?"))
        L.append("  %-14s %-8s %5s %6s %8s | %-16s | %-16s" % ("setup", "group", "n", "win", "move", "0DTE option", "1-week option"))
        for (setup, grp) in sorted(stats, key=lambda x: (x[1], x[0])):
            s = stats[(setup, grp)]; n = s["n"]
            avg = lambda a: 100 * sum(a) / len(a) if a else 0
            win = lambda a: 100 * sum(x > 0 for x in a) / len(a) if a else 0
            L.append("  %-14s %-8s %5d %5.0f%% %+7.2f%% | win %3.0f%% avg %+6.1f%% | win %3.0f%% avg %+6.1f%%" % (
                setup, grp, n, win(s["mv"]), avg(s["mv"]), win(s["o0"]), avg(s["o0"]), win(s["o1"]), avg(s["o1"])))
        L.append("")
    rep = "\n".join(L); print("\n" + rep); REPORT.write_text(rep + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
