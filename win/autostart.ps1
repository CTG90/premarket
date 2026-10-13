# Make Me Trade - toggle "start the bot when this PC logs in". Run via autostart.bat.
$root = Split-Path $PSScriptRoot -Parent
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Make Me Trade bot.lnk'
if (Test-Path $lnk) {
    Remove-Item $lnk
    Write-Host 'Autostart is now OFF. The bot will not start at login.'
} else {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $s.TargetPath = Join-Path $root 'start-bot.bat'
    $s.WorkingDirectory = $root
    $s.WindowStyle = 7   # start minimized
    $s.Save()
    Write-Host 'Autostart is now ON. The bot starts every time you log in to this PC.'
    Write-Host 'Run autostart.bat again to turn it off.'
}
Read-Host 'Press Enter to close'
