# Make Me Trade on Windows (dedicated bot PC)

Same bot as the Mac — `relay/mmt_bot.py`, Webull **paper** only. Windows just uses `.bat` launchers.

## One-time setup
1. Put the `MakeMeTrade` folder anywhere on the PC (e.g. `C:\MakeMeTrade`).
   - Copying it from the Mac brings the keys (`.webull_paper`, a hidden file) and the bot's trade history (`relay\bot_state.json`).
   - Or unzip `MakeMeTrade-windows.zip` — setup will ask for the keys.
2. Double-click **setup.bat**. It installs Python if needed (then run setup.bat again), installs the Webull SDK,
   saves your keys (only your Windows user can read them), lists your paper accounts, and runs a dry-run check.
3. Double-click **autostart.bat** so the bot starts whenever you log in (run again to turn off).

## Every day
Nothing. With autostart on, it runs after login, keeps the PC awake, restarts itself if it crashes, and sleeps overnight.
Manual start: **start-bot.bat**. Stop: close its window.

## PC settings for a dedicated bot box
- Settings → System → Power: **Sleep = Never** (plugged in). The bot also blocks sleep while running.
- Windows Update can reboot overnight: autostart brings the bot back after you (or auto-login) sign in.
  Set Active Hours to cover 9:00 am–4:30 pm ET.

## Rules
- **Run ONE bot per Webull account.** Mac and PC at the same time = double orders. Stop the Mac bot before starting the PC.
- Dashboard: `relay\status.html`. Log: `relay\bot.log`. Pause new entries: create a file named `STOP` in the MakeMeTrade folder.

## Phone dashboard
The bot serves a read-only live dashboard on port 8765. On start it saves the link (with its private key) to `relay\phone_link.txt`.
- When Windows Firewall asks, allow Python on **Private** networks.
- Same Wi-Fi: open the link on your phone → Share → Add to Home Screen.
- Away from home: install Tailscale on this PC and your phone, and use the PC's Tailscale name instead of the IP.
- Tip: reserve this PC's IP in your router so the link never changes.

## Updates
The bot reloads itself within ~15 s when its code is updated. No restart needed.
