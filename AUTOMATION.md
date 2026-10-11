# Automation Roadmap — paper → real orders

## Where things stand (v3)
- The **Bot tab** paper-trades the app's own signals on every refresh during market hours (entries 9:45–3:45 ET).
- Every order goes through one function, `executeOrder(order)`. Today the only route is `paper`.
- Orders are stored in a broker-neutral shape, and the Ticket view already renders each one as:
  - a thinkorswim order line
  - a Webull order description
  - an OCC option symbol
  - a Schwab Trader API order body (single-leg LIMIT, `BUY_TO_OPEN` / `SELL_TO_CLOSE`)
- Option prices are **modeled** (Black-Scholes on realized vol × 1.15, plus a simulated spread). Real fills will be worse on wide-spread names.

## Gate 1 — prove it on paper (in the app)
All five checks in Bot → "Ready for real money?":
1. 50+ closed trades
2. 6+ weeks of history
3. Positive expectancy
4. Profit factor ≥ 1.3
5. Max drawdown ≤ 20%

If a setup loses over 10+ trades, the bot blocks it automatically ("What it has learned").

## Gate 2 — prove it against real fills (manual)
Two weeks, 1 contract per signal, placed by hand from the Ticket view in TOS or Webull. Compare real fill vs modeled fill. If real P&L is meaningfully below paper, fix the fill model before going further.

## Gate 3 — server relay (only after Gates 1–2)
Live orders cannot run from a GitHub Pages file: broker API keys and OAuth tokens would be exposed to anyone who opens the page, and the bot stops when the tab closes.

What a relay needs:
- A small always-on server (e.g. a $5/mo VPS or a serverless function on a schedule) holding the broker credentials.
  - **TOS / Schwab:** Schwab Trader API (developer.schwab.com). OAuth app approval, refresh token renewed every 7 days.
  - **Webull:** Webull OpenAPI (requires application/approval).
- The same signal + rules logic as the app (port `scoreM`, `botTick`, `learned`).
- Hard limits enforced server-side, not in the browser:
  - max $ per trade, max open positions, max daily loss → kill switch
  - limit orders only, never market orders on options
  - no orders in the first 15 minutes or last 15 minutes
- Every order logged; a phone notification on every fill.
- Start at 1 contract regardless of what the sizing rules say.

`toSchwab()` in index.html produces the request body. Verify field names against the current Schwab Trader API docs before using it. The option symbol format (root padded to 6 chars + YYMMDD + C/P + strike×1000 padded to 8) matches the schwab-py documentation.

## Risks to keep in mind
- Paper results overstate real results (fills, slippage, partial fills, halts).
- Buying short-dated options loses to theta by default; the edge has to come from direction and timing.
- An automated bug repeats itself every 5 minutes. The daily-loss kill switch is not optional.
