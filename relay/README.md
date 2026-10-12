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
