# 執行一次票價檢查（Windows）。設計給「工作排程器」呼叫。
#   powershell -ExecutionPolicy Bypass -File scripts\watch.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\watch.ps1 -Args "--dry-run"
param([string]$Args = "")

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

New-Item -ItemType Directory -Force -Path "$Root\logs" | Out-Null
$Log = Join-Path $Root ("logs\watch-" + (Get-Date -Format "yyyyMM") + ".log")

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

$env:PYTHONPATH = Join-Path $Root "src"
$env:PYTHONUNBUFFERED = "1"

"===== 開始 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K') =====" | Out-File -Append -Encoding utf8 $Log
$argList = @("-m", "tripcom_watcher", "run")
if ($Args) { $argList += $Args.Split(" ") }
& $Py $argList *>&1 | Out-File -Append -Encoding utf8 $Log
"===== 結束 status=$LASTEXITCODE =====`n" | Out-File -Append -Encoding utf8 $Log

exit $LASTEXITCODE
