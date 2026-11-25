# Install from the PUBLIC GitHub ZIP, exactly as a new user would (models/callbook/QRZ already present).
# An install restarts the station, and a restart during a net loses what is on the air at that moment (found
# 2026-11-25: two installs the evening before each cut about 17 s out of a net being recorded). So this waits for the
# station to be quiet: no scheduled net on the air and no signal on any radio for a minute. A net in progress = not
# installed (exit 3): run it again after the net. -Force installs anyway.
param([switch]$Force)
if (-not $Force) {
    $ProgressPreference = 'SilentlyContinue'
    $quiet = 0
    for ($i = 0; $i -lt 30 -and $quiet -lt 3; $i++) {
        try { $st = (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8091/api/state' -TimeoutSec 15).Content | ConvertFrom-Json }
        catch { $st = $null }                                   # not running: nothing to interrupt
        if ($null -eq $st) { break }
        if ($st.net -and $st.net.current) {
            "NOT INSTALLED: the net '$($st.net.current.name)' is on the air on this station until $($st.net.current.end). Run again after it."
            exit 3
        }
        $busy = @($st.radios | Where-Object { $_.carrier -eq $true }).Count
        if ($busy) { $quiet = 0 } else { $quiet++ }
        if ($quiet -lt 3) { Start-Sleep -Seconds 20 }
    }
    if ($null -ne $st -and $quiet -lt 3) { "NOT INSTALLED: a radio here has been receiving for 10 minutes. Run again when it is quiet."; exit 3 }
}
$ErrorActionPreference = 'Stop'
$dl = "$env:USERPROFILE\hamsidekick-admin"; New-Item -ItemType Directory -Force $dl | Out-Null
$zip = "$dl\hamsidekick-master.zip"; $dir = "$dl\hamsidekick-public"
Remove-Item -Force $zip -ErrorAction SilentlyContinue; Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
[Net.ServicePointManager]::SecurityProtocol = 'Tls12'
Invoke-WebRequest -UseBasicParsing 'https://github.com/travislhilton/hamsidekick/archive/refs/heads/master.zip' -OutFile $zip
"zip bytes: $((Get-Item $zip).Length)"
Expand-Archive $zip $dir
$src = Get-ChildItem $dir -Directory | Select-Object -First 1
"source: $($src.FullName)"
Get-Content "$($src.FullName)\README.md" -TotalCount 1
$ErrorActionPreference = 'Continue'
& powershell -NoProfile -ExecutionPolicy Bypass -File "$($src.FullName)\install\windows\install.ps1" -SkipModels -SkipCallbook -SkipQrz 2>&1 | Out-String -Width 220
"install exit: $LASTEXITCODE"
