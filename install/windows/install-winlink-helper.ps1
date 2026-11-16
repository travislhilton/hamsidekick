<#
HAM Sidekick Winlink helper: install or update on a Windows PC that has Winlink Express, so the station's Winlink
window can put its messages in THIS PC's Outbox (station/winlink_helper.py). Idempotent; no administrator rights.

The station serves this script and a ready-made install.cmd: open the dashboard on this PC, Winlink window ->
"Get the helper for this PC", run the downloaded file. Or by hand:
  install-winlink-helper.ps1 -Station http://STATIONPC:8091

What it does (only for the signed-in user):
  1. Python 3.12 (64-bit): the one already here, or installs it for this user (winget, else python.org).
  2. Copies the helper (four small files, served by the station) to %LOCALAPPDATA%\HAM Sidekick Winlink Helper\app.
  3. Asks the station once (a check), then registers the task "HAM Sidekick Winlink Helper": it starts at sign-in,
     with no window, and comes back within 2 minutes if it stops.
Remove: Unregister-ScheduledTask 'HAM Sidekick Winlink Helper' and delete that folder.
#>
param([Parameter(Mandatory = $true)][string]$Station)
$ErrorActionPreference = 'Stop'
$Station = $Station.TrimEnd('/')
function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }

Step "Python 3.12"
function Find-Python312 {
  $c = @('C:\Program Files\Python312\python.exe', "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")
  foreach ($hive in 'HKCU:\SOFTWARE\Python\PythonCore\3.12', 'HKLM:\SOFTWARE\Python\PythonCore\3.12', 'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore\3.12') {
    $k = Get-ItemProperty "$hive\InstallPath" -ErrorAction SilentlyContinue
    if ($k) { if ($k.ExecutablePath) { $c += $k.ExecutablePath }; if ($k.'(default)') { $c += (Join-Path $k.'(default)' 'python.exe') } }
  }
  foreach ($x in $c) {
    if ($x -and (Test-Path $x)) {
      $v = & $x -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>$null
      if ("$v".Trim() -eq '3 12') { return $x }
    }
  }
  return $null
}
$py = Find-Python312
if (-not $py) {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    & winget install --id Python.Python.3.12 -e --source winget --scope user --silent `
      --accept-source-agreements --accept-package-agreements --disable-interactivity
    $py = Find-Python312
  }
  if (-not $py) {
    $exe = "$env:TEMP\python-3.12.10-amd64.exe"
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $exe -TimeoutSec 600
    $p = Start-Process $exe -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_test=0' -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Python install failed (exit $($p.ExitCode))" }
    $py = Find-Python312
  }
  if (-not $py) { throw 'Python 3.12 did not install' }
}
Write-Host "  $py"
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'

Step "The helper -> $env:LOCALAPPDATA\HAM Sidekick Winlink Helper"
$base = Join-Path $env:LOCALAPPDATA 'HAM Sidekick Winlink Helper'
$app = Join-Path $base 'app'
New-Item -ItemType Directory -Force (Join-Path $app 'station') | Out-Null
foreach ($f in '__init__.py', 'winlink.py', 'lzhuf.py', 'winlink_helper.py') {
  Invoke-WebRequest -UseBasicParsing -Uri "$Station/winlink-helper/files/$f" -OutFile (Join-Path $app "station\$f") -TimeoutSec 60
}

Step "Asking the station once ($Station)"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*station.winlink_helper*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Push-Location $app
try { & $py -m station.winlink_helper --station $Station --once; if ($LASTEXITCODE -ne 0) { throw "the check failed (exit $LASTEXITCODE)" } }
finally { Pop-Location }

Step "Start at sign-in"
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$act = New-ScheduledTaskAction -Execute $pyw -Argument '-m station.winlink_helper' -WorkingDirectory $app
$trg = New-ScheduledTaskTrigger -AtLogOn -User $user
$trg2 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 2)
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 -MultipleInstances IgnoreNew
$prn = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'HAM Sidekick Winlink Helper' -Action $act -Trigger $trg, $trg2 -Settings $set -Principal $prn `
  -Description 'Puts HAM Sidekick Station Winlink messages in this PC''s Winlink Express Outbox' -Force | Out-Null
Start-ScheduledTask -TaskName 'HAM Sidekick Winlink Helper'
Write-Host "`n  Done. In the station's Winlink window, choose '$env:COMPUTERNAME' under 'Put them in the Outbox on'." -ForegroundColor Green
Write-Host "  Log: $base\helper.log"
