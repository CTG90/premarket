# Webull relay (v0, sandbox first)

Takes the app's paper trades (Bot tab → Export) and sends the opening orders to Webull's OpenAPI.
It's the bridge in AUTOMATION.md Gate 3. Right now it's for the **sandbox** only: real order formats,
fake money.

## Safety defaults
| Guard | Default |
|---|---|
| Sends anything? | No. Dry run unless `--send` |
| Environment | Sandbox host unless `--live` **and** `WEBULL_ALLOW_LIVE=1` |
| Order type | LIMIT + DAY only |
| Size | 1 contract max, $750 max per order, 5 orders/day |
| Duplicates | Each app trade id sent once (`sent.json`) |
| Index options (SPX) | Blocked. Webull OpenAPI doesn't support them |

## Status
- Oct 12 2026: connected to Webull **paper** OpenAPI. Working host is `api.sandbox.webull.com` with the App Key exactly as issued (including the `us.` prefix). Bot account: Individual Margin DEV8M8T6.
- Keys + account id live in `MakeMeTrade/.webull_paper` (gitignored, chmod 600) on the Mac.
- Mac scripts: `setup.command` (one-time), `probe.command` (read-only connection check). Run with `bash ~/AI/MakeMeTrade/<name>.command`.

## Strategy (Oct 12 2026 backtest)
- Buying calls/puts on momentum: lost money (current rules ~41% win, -$14/trade); best-looking buy settings failed on the newer half of the data.
- **Live strategy: SPY/QQQ credit spreads** — trend-following bull put / bear call, $5 wide, ~0.30 delta short, 45 DTE, take profit at 75% of credit, exit at 7 DTE, RSI ≤ 70 for puts, new entry weekly, up to 4 open per ticker.
  Backtest (Oct 2023–Oct 2026, modeled prices): 182 trades, 84.6% win, +$59/spread, worst -$367, max drawdown -$2,026; older half 86% / newer half 83%.
- Caveats: no 2022-style crash in sample (Webull gives 1,000 days), modeled option prices, 2026 weaker (69%).
- Webull API: vertical spreads go through order_v3 with option_strategy VERTICAL, side SELL + positive credit (confirmed by preview).

## Mac bot (mmt_bot.py)
Runs the Make Me Trade playbook against Webull paper with Webull's own quotes, daily bars and option bid/ask/IV.
- Start: `bash ~/AI/MakeMeTrade/start-bot.command` (keeps the Mac awake, opens relay/status.html)
- Rules: relay/bot_config.json (created on first run). Hard cap 1 contract.
- Pause new entries: create a file named `STOP` in MakeMeTrade. Exits keep being managed.
- Order checks: limit DAY orders at mid + 1/4 spread; skips spreads > 12% of mid, open interest < 50, cost > $750.
- Unfilled orders are cancelled after ~7 minutes.
- Earnings guard not available yet (no earnings feed in Webull data API).
- Format check without placing: `bash ~/AI/MakeMeTrade/testorder.command`

## Setup (once)
1. Apply at webull.com → avatar → **Developer Tool** → OpenAPI Management → My Application.
   The **sandbox** application auto-approves in minutes; production takes 1–2 business days.
2. Generate sandbox App Key / App Secret.
3. On your computer (Python 3.8–3.14):
   ```bash
   pip3 install --upgrade webull-openapi-python-sdk
   # if pip can't find it: pip3 install git+https://github.com/webull-inc/webull-openapi-python-sdk
   export WEBULL_APP_KEY=your_sandbox_key
   export WEBULL_APP_SECRET=your_sandbox_secret
   ```
   Keep keys in your shell/env only. Never put them in index.html or commit them.

## Use
```bash
python3 relay.py accounts                                   # get your sandbox account_id
python3 relay.py place premarket-paper-2026-10-12.json      # dry run: prints payloads
python3 relay.py place premarket-paper-2026-10-12.json --send --account <account_id>
```
Then compare sandbox fills against the app's modeled fills.

## Known gaps (v0)
- Opens only. Closing (take profit / stop) still happens in the app; next version mirrors exits.
- Manual run from an export file, not a live loop.
- Webull's docs use `option_expire_date` in the Python sample and `init_exp_date` in the JSON
  sample. The relay uses `option_expire_date` (matches the SDK's v2 sample). If sandbox rejects
  the order on that field, swap it.
