# Premarket Pro

Single-file options and stock trading dashboard with a paper-trading bot. No build step, no backend. Open `index.html` in a browser, or host it on GitHub Pages.

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
1. The file at the repo root must be named exactly `index.html`.
2. Edit it in place on GitHub (open file, pencil icon, paste, commit). Never upload a renamed copy.
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
