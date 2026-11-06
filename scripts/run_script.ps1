param(
  [string]$Csv = ""
)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

if (-not $Csv) { $Csv = $WbCsv }
$candidates = @(
  (Join-Path $WbRoot "bin\sim_script.exe"),
  (Join-Path $EngineBuild "sim_script.exe"),
  (Join-Path $EngineBuild "Release\sim_script.exe"),
  (Join-Path $EngineBuild "sim_script")
)
$bin = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $bin) { throw "sim_script not found. Run scripts\build.bat first." }
if (-not (Test-Path $Csv)) { throw "script file not found: $Csv" }

Write-Host "[run_script] bin=$bin"
Write-Host "[run_script] script=$Csv"
# Visible window preferred on Win (product lock); dummy only if user sets it
& $bin $Csv @args
exit $LASTEXITCODE
