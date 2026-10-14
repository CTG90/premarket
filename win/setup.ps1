# Make Me Trade - one-time Windows setup (Webull PAPER). Run via setup.bat.
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
$relay = Join-Path $root 'relay'
$keyfile = Join-Path $root '.webull_paper'
$env:PYTHONUTF8 = '1'
Write-Host "=== Make Me Trade - Windows setup ===`n"

# 1) Python
function Find-Python {
    foreach ($c in @(@{exe = 'py'; a = @('-3')}, @{exe = 'python'; a = @()})) {
        try { $pa = $c.a; $v = & $c.exe @pa --version 2>&1; if ($LASTEXITCODE -eq 0 -and "$v" -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 9) { return $c } } catch {}
    }
    return $null
}
$py = Find-Python
if (-not $py) {
    Write-Host "Python isn't installed. Installing Python 3.12 (one time)..."
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    Write-Host "`nPython installed. CLOSE this window and double-click setup.bat again."
    Read-Host 'Press Enter to close'; exit 1
}
$pa = $py.a; Write-Host "Python found: $(& $py.exe @pa --version 2>&1)"

# 2) Keys (copied from the Mac, or entered here)
if (-not (Test-Path $keyfile) -or (Get-Item $keyfile).Length -eq 0) {
    Write-Host "`nNo keys yet. (If you copied the MakeMeTrade folder from the Mac with its .webull_paper file, you'd skip this.)"
    $k = (Read-Host 'Paste your Webull PAPER App Key').Trim()
    $sec = Read-Host 'Paste your Webull PAPER App Secret (hidden)' -AsSecureString
    $s = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)).Trim()
    if (-not $k -or -not $s) { Write-Host 'Key or secret was empty. Run setup.bat again.'; Read-Host 'Press Enter to close'; exit 1 }
    [IO.File]::WriteAllText($keyfile, "export WEBULL_APP_KEY='$k'`nexport WEBULL_APP_SECRET='$s'`n")
    Write-Host 'Keys saved to MakeMeTrade\.webull_paper'
} else { Write-Host "`nKeys found in MakeMeTrade\.webull_paper" }
# only this Windows user can read the key file
icacls $keyfile /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null

# 3) Python environment + Webull SDK
Set-Location $relay
# a .venv copied over from the Mac doesn't work on Windows - rebuild it
if ((Test-Path '.venv') -and -not (Test-Path '.venv\Scripts\python.exe')) { Remove-Item -Recurse -Force '.venv' }
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Write-Host "`nSetting up Python (first run takes a minute)..."
    $pa = $py.a; & $py.exe @pa -m venv .venv
}
$vpy = Join-Path $relay '.venv\Scripts\python.exe'
& $vpy -m pip install -q --upgrade pip 2>&1 | Out-Null
& $vpy -m pip install -q --upgrade webull-openapi-python-sdk tzdata yfinance
if ($LASTEXITCODE -ne 0) { & $vpy -m pip install -q "git+https://github.com/webull-inc/webull-openapi-python-sdk" tzdata }

# 4) Accounts + account ID
Write-Host "`n=== Your Webull paper accounts ==="
& $vpy relay.py accounts 2>&1 | Tee-Object -FilePath accounts_output.txt
if (-not (Select-String -Path $keyfile -Pattern 'WEBULL_ACCOUNT_ID' -Quiet)) {
    $a = (Read-Host "`nPaste the paper account_id shown above").Trim()
    if ($a) { Add-Content -Path $keyfile -Value "export WEBULL_ACCOUNT_ID='$a'" -Encoding ascii }
}

# 5) Connection check (dry run: reads data, places nothing)
Write-Host "`n=== Connection check (dry run, no orders) ==="
& $vpy -u mmt_bot.py --once --dry 2>&1 | Select-Object -Last 15
Write-Host "`nSetup done. Next: double-click start-bot.bat (and autostart.bat if this is the dedicated bot PC)."
Read-Host 'Press Enter to close'
