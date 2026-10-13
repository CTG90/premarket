#!/usr/bin/env python3
"""
Make Me Trade — micro-futures trend-following backtest.

Uses ETF daily bars as stand-ins for micro futures (same underlying moves):
  SPY→MES (micro S&P)   QQQ→MNQ (micro Nasdaq)   IWM→M2K (micro Russell)
  GLD→MGC (micro gold)  SLV→SIL (micro silver)   USO→MCL (micro crude)
  TLT→ (micro bond proxy)  UUP→ (dollar)  FXE→M6E (micro euro)

Strategy family (documented: time-series momentum / trend following):
  long when the trend is up, short when it's down, sized so each market carries equal risk,
  rebalanced weekly. Variants: 200-day trend, 50/200 cross, 100-day breakout, blended.
Shows (a) the ideal version (fractional sizing) and (b) what you can actually trade with
whole micro contracts at $2.5K / $10K / $25K / $50K accounts.
Usage: python3 futures.py   (fetches ETF bars from Webull into ft_bars.json once)
"""
import datetime as dt
import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
FT_F = BASE / "ft_bars.json"
# proxy ETF → (micro contract, $ notional per contract per $1 of ETF price, fee per round trip)
MAP = {
    "SPY": ("MES micro S&P", 50.0, 1.5),       # SPX≈10×SPY, $5/pt
    "QQQ": ("MNQ micro Nasdaq", 82.0, 1.5),    # NDX≈41×QQQ, $2/pt
    "IWM": ("M2K micro Russell", 50.0, 1.5),   # RUT≈10×IWM, $5/pt
    "GLD": ("MGC micro gold", 109.0, 1.5),     # gold≈10.9×GLD, 10 oz
    "SLV": ("SIL micro silver", 1100.0, 1.5),  # silver≈1.1×SLV, 1000 oz
    "USO": ("MCL micro crude", 90.0, 1.5),     # rough: ~$7-8K notional at current prices
    "TLT": ("micro bond proxy", 1000.0, 1.5),  # ~ $90-110K notional (ZN-like) — large
    "FXE": ("M6E micro euro", 115.0, 1.5),     # 12,500 EUR
}


def fetch():
    if FT_F.exists():
        d = json.loads(FT_F.read_text())
        if len(d) >= 6:
            return d
    sys.path.insert(0, str(BASE))
    import mmt_bot as M
    wb = M.WB(); out = {}
    for t in MAP:
        for cnt in (1000, 800):
            try:
                b = wb.daily_bars([t], cnt)
                if b.get(t) and len(b[t]["c"]) > 400:
                    out[t] = b[t]; print("bars %s: %d" % (t, len(b[t]["c"])), flush=True); break
            except Exception:
                pass
    FT_F.write_text(json.dumps(out))
    return out


def sma(c, i, k):
    return sum(c[i - k + 1:i + 1]) / k if i >= k - 1 else None


def signal(c, i, kind):
    if i < 252: return 0
    if kind == "trend200":
        return 1 if c[i] > sma(c, i, 200) else -1
    if kind == "cross50_200":
        return 1 if sma(c, i, 50) > sma(c, i, 200) else -1
    if kind == "breakout100":
        hi, lo = max(c[i - 100:i]), min(c[i - 100:i])
        return 1 if c[i] >= hi else -1 if c[i] <= lo else None  # None = keep previous
    if kind == "mom252":
        return 1 if c[i] > c[i - 252] else -1
    if kind == "blend":
        s = [1 if c[i] > c[i - k] else -1 for k in (63, 126, 252)]
        return sum(s) / 3
    return 0


def vol(c, i, n=40):
    r = [math.log(c[j] / c[j - 1]) for j in range(i - n + 1, i + 1)]
    m = sum(r) / n
    return math.sqrt(sum((x - m) ** 2 for x in r) / (n - 1) * 252)


def backtest(data, kind, acct, target_vol=0.20, whole=True, long_only_eq=False):
    tick = sorted(data)
    dates = sorted(set.intersection(*[set(data[t]["t"]) for t in tick]))
    idx = {t: {d: k for k, d in enumerate(data[t]["t"])} for t in tick}
    eq = acct; peak = acct; mdd = 0; pos = {t: 0.0 for t in tick}; sigs = {t: 0 for t in tick}
    curve = []; fees = 0; traded = set(); months = {}
    per_mkt = target_vol / math.sqrt(len(tick))
    for n, d in enumerate(dates):
        if n == 0: continue
        # mark to market
        pnl = 0
        for t in tick:
            c = data[t]["c"]; i = idx[t][d]
            pnl += pos[t] * (c[i] - c[i - 1]) * MAP[t][1] if whole else pos[t] * (c[i] / c[i - 1] - 1)
        eq += pnl
        if eq <= 0:
            eq = 0; curve.append((d, eq)); break
        # weekly rebalance (Fridays or every 5th day)
        if n % 5 == 0:
            for t in tick:
                c = data[t]["c"]; i = idx[t][d]
                if i < 260: continue
                s = signal(c, i, kind)
                if s is None: s = sigs[t]
                sigs[t] = s
                if long_only_eq and t in ("SPY", "QQQ", "IWM") and s < 0: s = 0
                v = vol(c, i)
                notional = eq * per_mkt / v * s if v > 0 else 0
                if whole:
                    per_c = c[i] * MAP[t][1]
                    want = int(notional / per_c) if per_c else 0   # truncate toward zero
                    if want != pos[t]:
                        fees += abs(want - pos[t]) * MAP[t][2]; eq -= abs(want - pos[t]) * MAP[t][2]
                    if want: traded.add(t)
                    pos[t] = want
                else:
                    pos[t] = notional; traded.add(t)
        peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak * 100 if peak else 0)
        curve.append((d, eq)); months.setdefault(d[:7], []).append(eq)
    yrs = (dt.date.fromisoformat(curve[-1][0]) - dt.date.fromisoformat(dates[1])).days / 365 if curve else 1
    cagr = ((eq / acct) ** (1 / yrs) - 1) * 100 if eq > 0 and yrs > 0 else -100
    rets = [curve[k][1] / curve[k - 1][1] - 1 for k in range(1, len(curve)) if curve[k - 1][1] > 0]
    sh = (sum(rets) / len(rets)) / (math.sqrt(sum((x - sum(rets) / len(rets)) ** 2 for x in rets) / (len(rets) - 1)) or 1) * math.sqrt(252) if len(rets) > 2 else 0
    mvals = sorted(months)
    mrets = [months[mvals[k]][-1] / months[mvals[k - 1]][-1] - 1 for k in range(1, len(mvals)) if months[mvals[k - 1]][-1] > 0]
    return {"final": eq, "cagr": cagr, "mdd": mdd, "sharpe": sh, "markets": len(traded), "fees": fees,
            "worst_month": min(mrets) * 100 if mrets else 0, "best_month": max(mrets) * 100 if mrets else 0, "years": yrs}


def main():
    data = fetch()
    if len(data) < 4:
        sys.exit("Not enough futures-proxy data.")
    L = ["MICRO-FUTURES TREND BACKTEST · %d markets (%s) · ETF proxies · weekly rebalance · 20%% target vol" % (len(data), ",".join(sorted(data)))]
    L.append("\nA) IDEAL (fractional sizing — shows whether the strategy itself has an edge)")
    for kind in ("trend200", "cross50_200", "breakout100", "mom252", "blend"):
        r = backtest(data, kind, 100000, whole=False)
        L.append("  %-12s CAGR %+5.1f%% · max drawdown %4.1f%% · Sharpe %.2f · worst month %+.1f%% · best %+.1f%%" % (
            kind, r["cagr"], r["mdd"], r["sharpe"], r["worst_month"], r["best_month"]))
    best = max(("trend200", "cross50_200", "breakout100", "mom252", "blend"), key=lambda k: backtest(data, k, 100000, whole=False)["sharpe"])
    L.append("\nB) REAL (whole micro contracts) using '%s'" % best)
    for acct in (2500, 10000, 25000, 50000):
        r = backtest(data, best, acct, whole=True)
        L.append("  $%-6s → $%s after %.1f yrs · CAGR %+5.1f%% · max drawdown %4.1f%% · markets actually traded %d/%d · worst month %+.1f%%" % (
            format(acct, ","), format(round(r["final"]), ","), r["years"], r["cagr"], r["mdd"], r["markets"], len(data), r["worst_month"]))
    # C) what a small account actually faces: forced 1 micro contract in one market
    L.append("\nC) FORCED 1 CONTRACT, single market, '%s' signal (what $2,500 can actually do)" % best)
    for t in [x for x in ("SPY", "QQQ", "GLD", "USO") if x in data]:
        c, ts = data[t]["c"], data[t]["t"]; pos = 0; pnl = 0; peak = 0; worst = 0; sig = 0; fees = 0
        for i in range(261, len(c)):
            pnl += pos * (c[i] - c[i - 1]) * MAP[t][1]
            if i % 5 == 0:
                s = signal(c, i, best); s = sig if s is None else s; sig = s
                want = 1 if s > 0 else -1 if s < 0 else 0
                if want != pos: fees += abs(want - pos) * MAP[t][2]; pnl -= abs(want - pos) * MAP[t][2]
                pos = want
            peak = max(peak, pnl); worst = max(worst, peak - pnl)
        L.append("  1x %-18s total P&L $%+8s over %.1f yrs · worst peak-to-trough $%s (%s of a $2,500 account)" % (
            MAP[t][0], format(round(pnl), ","), (len(c) - 261) / 252, format(round(worst), ","),
            "%.0f%%" % (worst / 2500 * 100)))
    L.append("\nOne micro contract ≈ notional: " + " · ".join("%s $%s" % (MAP[t][0].split()[0], format(round(data[t]["c"][-1] * MAP[t][1]), ",")) for t in sorted(data)))
    rep = "\n".join(L); print(rep); (BASE / "futures_report.txt").write_text(rep + "\n")


if __name__ == "__main__":
    main()
