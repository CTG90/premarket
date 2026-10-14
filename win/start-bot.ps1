# Make Me Trade - run the bot (Webull PAPER). Leave this window open. Run via start-bot.bat.
$root = Split-Path $PSScriptRoot -Parent
$relay = Join-Path $root 'relay'
Set-Location $relay
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
$Host.UI.RawUI.WindowTitle = 'Make Me Trade bot (paper) - leave open'
$vpy = Join-Path $relay '.venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) { Write-Host 'Run setup.bat first.'; Read-Host 'Press Enter to close'; exit 1 }
Write-Host '=== Make Me Trade bot (paper) ==='
Write-Host 'Keeps this PC awake while running. Close this window to stop.'
Write-Host ''
# open the dashboard once the bot has written it
Start-Process cmd -ArgumentList '/c timeout /t 30 /nobreak >nul & start "" "status.html"' -WindowStyle Hidden -WorkingDirectory $relay
while ($true) {
    & $vpy -u mmt_bot.py --log bot.log
    if ($LASTEXITCODE -eq 75) { Write-Host 'Update detected - reloading the bot...'; continue }
    Write-Host "`nBot exited (code $LASTEXITCODE). Restarting in 60 seconds - close this window to stop it for good."
    Start-Sleep -Seconds 60
}
