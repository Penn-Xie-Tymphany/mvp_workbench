# Skeleton: assemble PyInstaller dist folder with engine + toolchain.
# Run on Windows after: py -3 -m PyInstaller ...
param(
  [string]$Dist = "dist\AIDOGUI_MVP_Workbench",
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)
$ErrorActionPreference = "Stop"
Write-Host "[assemble] Dist=$Dist RepoRoot=$RepoRoot"
New-Item -ItemType Directory -Force -Path $Dist | Out-Null
# Engine (exclude heavy/dev dirs)
$engineDest = Join-Path $Dist "engine"
New-Item -ItemType Directory -Force -Path $engineDest | Out-Null
robocopy $RepoRoot $engineDest /E /NFL /NDL /NJH /NJS /XD build desktop_app workbench .git __pycache__ .venv | Out-Null
robocopy (Join-Path $RepoRoot "workbench\scripts") (Join-Path $Dist "scripts") /E | Out-Null
robocopy (Join-Path $RepoRoot "workbench\toolchain") (Join-Path $Dist "toolchain") /E | Out-Null
robocopy (Join-Path $RepoRoot "workbench\projects") (Join-Path $Dist "projects") /E | Out-Null
robocopy (Join-Path $RepoRoot "workbench\tests") (Join-Path $Dist "tests") /E | Out-Null
Write-Host "[assemble] done. Place AIDOGUI_MVP_Workbench.exe into $Dist"
