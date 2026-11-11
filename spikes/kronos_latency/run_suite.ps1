# P0 latency suite. Throwaway. Logs to out/suite.log
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$bench = Join-Path $PSScriptRoot "bench.py"
$log = Join-Path $PSScriptRoot "out\suite.log"

New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot "out") | Out-Null
"=== suite start $(Get-Date -Format o) ===" | Tee-Object -FilePath $log

& $py $bench --model small --tf M15 --lookback 288 --horizon 12 --runs 3 *>&1 | Tee-Object -FilePath $log -Append
& $py $bench --model base  --tf M15 --lookback 288 --horizon 12 --runs 2 *>&1 | Tee-Object -FilePath $log -Append
& $py $bench --model mini  --tf M15 --lookback 288 --horizon 12 --runs 3 --threads 4 *>&1 | Tee-Object -FilePath $log -Append
& $py $bench --model mini  --tf M5  --lookback 288 --horizon 12 --runs 3 *>&1 | Tee-Object -FilePath $log -Append
& $py $bench --model small --tf M5  --lookback 288 --horizon 12 --runs 2 *>&1 | Tee-Object -FilePath $log -Append

"=== suite done $(Get-Date -Format o) ===" | Tee-Object -FilePath $log -Append
