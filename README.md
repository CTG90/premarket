# Premarket Pro

Three pages, same site:
- **index.html — Premarket Live.** Big three (NVDA, AMZN, AAPL) and a watchlist, streaming. Add a free Finnhub key in Settings for tick-by-tick prices over WebSocket; without one it polls Yahoo every 6 s. Shows pre/after-hours, day range, positions and P&L, live candlestick chart, headlines, next earnings.
- **trade.html — Make Me Trade.** One screen for trading: what to do now, signals, bot, track record. 10 tickers only (SPY QQQ NVDA AAPL AMZN MSFT META TSLA AMD PLTR). Refreshes every 3 min in market hours, keep-awake toggle for phones, browser alerts on every bot trade.
- **research.html — Research.** Full dashboard: news, macro, earnings, holdings, swings, congress trades, crowd.

Single-file pages, no build step, no backend. Open in a browser or host on GitHub Pages. The sections below describe the Research page (research.html).

Live URL: https://ctg90.github.io/premarket/

## Tabs
Today, Bot, Movers, Strikes, Swings, Plan, Holdings, P&L, Earn, Macro, News, Flow, Crowd, Pol, List

## How it works
- Quotes: Yahoo Finance v7 (v8 fallback), direct then corsproxy.io then allorigins.win. The route that works is remembered.
- Daily history: 1 year of daily bars per watchlist ticker (v8 chart), cached in localStorage once per ET day.
- Computed from history (nothing hand-typed): support/resistance (clustered swing pivots), 20/50/200-day SMAs, RSI(14), ATR(14), 20-day realized vol and its 1-year rank ("vol rank", used in place of IV rank).
- `scoreM` scores each ticker (move, rel volume, trend alignment, RSI, levels, vol rank) and labels a play.
- Option premiums are modeled with Black-Scholes using realized vol × 1.15. They are estimates, not quotes.
- Auto-refresh every 5 minutes, 4AM–4PM ET weekdays, plus on open and when the tab comes back into view.

## Paper bot (Bot tab)
- Runs after every refresh. Entries only 9:45–3:45 ET on weekdays.
- Opens the top-scoring call/put setups that clear the rules, closes at take-profit / stop / time stop / before earnings / expiry.
- Learns: blocks setups and score ranges that lose over 10+ trades, can require trend alignment.
- Graduation checklist gates any move to real money. See `AUTOMATION.md`.
- Data lives in this browser's localStorage. Export/Import JSON from the Bot tab.

## Deploy / edit workflow (GitHub Pages)
1. File names at the repo root are fixed: `index.html` (Live), `research.html`, `trade.html`.
2. Edit them in place on GitHub (open file, pencil icon, paste, commit). Never upload a renamed copy.
3. Wait about a minute, then hard-refresh.

## Known limits
- Option prices are modeled, not live chains.
- Earnings dates only come through when the v7 quote route works.
- No free economic calendar feed; check TOS for CPI/FOMC days.
- Flow tab is a volume/price estimate, not real options flow.
- The bot only runs while the page is open.
- Yahoo via public proxies can rate-limit or fail.

## Dev checklist before publishing
- `node --check` on the extracted script
- Every tab id is in the `TABS` array and has a `data-tab` button
- No template literals; escape apostrophes in single-quoted strings; careful quoting in inline onclick
