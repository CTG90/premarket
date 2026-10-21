# Changelog

## Premarket Live — Oct 20 2026
- New front page (index.html): live view of the big three (NVDA, AMZN, AAPL) plus a watchlist.
- Streaming: with a free Finnhub key (Settings), every trade arrives over a WebSocket and the price, day range, 1-minute candle and position value update on each print. Without a key, Yahoo is polled every 6 s for the big three and every 30 s for the watchlist (was every 5 min).
- Freshness is honest: each card shows the time of the last trade it has (not the fetch time), a draining bar, and flags quotes with no trade in 90 s.
- Pre-market / after-hours price and change on every card and row.
- Positions: shares and avg cost per holding (defaults 600 NVDA, 100 AMZN, 100 AAPL; reads avg cost from the Research Holdings tab), day P&L and total gain, big-three total.
- Candlestick chart (1D live, 5D, 1M, 6M, 1Y) with previous-close and your-cost lines; headlines per ticker; next earnings date (Finnhub).
- Keep-screen-on toggle, light/dark/auto theme, phone layout.
- Old index.html moved to research.html (unchanged apart from a Live link). trade.html links to both.

## Speed fix — Oct 12 2026
- Yahoo v7 quote endpoint needs a login crumb and was failing on every call; app tried it 3x per ticker before falling back. Now tried once per day, then skipped.
- Dropped the direct-to-Yahoo attempt (always blocked by CORS from github.io).
- Both CORS proxies are raced in parallel; fastest answer wins.
- Prices render as they arrive; history loads after, VIX fetched in parallel.
- Steady-state refresh: ~24 requests in one parallel wave vs ~48 sequential attempts.
- Avg volume now computed from cached daily history (v8 doesn't return it).
- Make Me Trade warns when earnings dates are unavailable (earnings guard can't work).

## Make Me Trade — Oct 12 2026
- New trade.html: single-screen trading app on 10 liquid tickers (~12 requests per refresh vs ~70).
- "What to do now" card driven by session phase (premarket / opening range / open / closing / closed).
- Signal status per ticker shows exactly why the bot will or won't take it (score, blocked, regime, earnings, cost, max positions).
- Keep-awake (Wake Lock) so phones don't pause the bot; browser notifications on bot opens/closes.
- Shares bot engine and paper history with the research app; cross-links between the two.
- Webull sandbox relay in relay/ (dry-run default, hard caps).

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
