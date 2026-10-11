# Changelog

## v3 — Oct 11 2026
- New Bot tab: paper-trading engine that trades the app's signals, with take-profit/stop/time/earnings exits, rules editor, stats by setup/score/trend/vol, self-adjusting rules, graduation checklist, export/import.
- Order layer: every trade is a broker-neutral order; Ticket view renders TOS line, Webull line, OCC symbol, Schwab API body.
- All levels computed live from 1y daily history: S/R pivots, SMAs, RSI, ATR, realized-vol rank (replaces hardcoded ivEst).
- Today, Plan, Swings, Holdings, Earn, Macro, Crowd rebuilt from live data; removed stale August content and fake crowd/flow numbers.
- Strikes show modeled premium, delta, breakeven + Paper/Ticket buttons.
- Holdings: cost basis input, concentration warning, covered-call and hedge cost estimates.
- Macro: live regime (VIX term structure + SPY trend), yields, dollar, oil, gold, BTC.
- Fixes: SPX now pulls the index (^GSPC), premarket/after-hours prices parsed, news links open, Strikes tab highlight, parallel fetching.
- Mobile: scrollable sticky tab bar, bigger tap targets, safe-area insets, pinch-zoom allowed.

## Earlier
- Tabs: Today, Movers, Strikes, P&L, Earn, Macro, Crowd, News, Flow, Pol, Swings, Plan, List, Holdings
- Holdings tab: 600 NVDA, 100 AAPL, 100 AMZN
- optTgt separated from analyst target; high-OI strike hints
- Moved from React artifacts to a standalone HTML app
- Dropped Finnhub for Yahoo Finance + CORS proxies
- Moved hosting to GitHub Pages
