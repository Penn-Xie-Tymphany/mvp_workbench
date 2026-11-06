$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$candidates = @(
  (Join-Path $WbRoot "bin\sim_sdl.exe"),
  (Join-Path $EngineBuild "sim_sdl.exe"),
  (Join-Path $EngineBuild "Release\sim_sdl.exe"),
  (Join-Path $EngineBuild "sim_sdl")
)
$bin = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $bin) { throw "sim_sdl not found. Run scripts\build.bat first (or place exe in bin\)." }
Write-Host "[run_sim] $bin"
& $bin @args
exit $LASTEXITCODE
