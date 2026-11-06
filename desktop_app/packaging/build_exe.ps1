#Requires -Version 5.1
<#
.SYNOPSIS
  Build AIDOGUI_MVP_Workbench.exe on Windows with PyInstaller (windowed onedir).

.DESCRIPTION
  Run this ON THE USER'S WINDOWS MACHINE (or a Windows CI box), from APP_ROOT
  or from the repo desktop_app folder. Linux box cannot produce a trustworthy
  Win GUI exe.

  Uses PyInstaller --onedir (NOT --onefile). Publishes BOTH the .exe AND the
  sibling _internal\ tree into APP_ROOT. Moving only the .exe will fail with
  "Failed to load Python DLL ... _internal\python311.dll".

  Prerequisites:
    - Python 3.11+ with tcl/tk (python.org installer, "tcl/tk" checked)
    - pip available

.EXAMPLE
  cd W:\AIDOGUI_MVP_Workbench
  powershell -NoProfile -ExecutionPolicy Bypass -File desktop_app\packaging\build_exe.ps1
#>
$ErrorActionPreference = "Stop"

$here = $PSScriptRoot
# packaging/ → desktop_app/ → APP_ROOT (packaged) or aidogui_mvp/desktop_app (dev)
$desktopApp = (Resolve-Path (Join-Path $here "..")).Path
$appRootCandidate = (Resolve-Path (Join-Path $desktopApp "..")).Path

if (Test-Path (Join-Path $appRootCandidate "engine\CMakeLists.txt")) {
  $AppRoot = $appRootCandidate
  $WorkDir = $AppRoot
} else {
  # Dev layout: package lives under aidogui_mvp/desktop_app
  $AppRoot = $desktopApp
  $WorkDir = $desktopApp
}

Write-Host "[build_exe] desktop_app = $desktopApp"
Write-Host "[build_exe] APP_ROOT    = $AppRoot"

$py = $null
$pyArgs = @()
foreach ($c in @(
    @{ Cmd = "py"; Args = @("-3") },
    @{ Cmd = "python"; Args = @() }
  )) {
  $cmd = Get-Command $c.Cmd -ErrorAction SilentlyContinue
  if ($cmd) {
    & $cmd.Source @($c.Args) -c "import tkinter, sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0) {
      $pyOut = & $cmd.Source @($c.Args) -c "import sys; print(sys.executable)"
      $py = $pyOut.Trim()
      $pyArgs = $c.Args
      break
    }
  }
}
if (-not $py) {
  throw "Python 3 + tkinter required. Install from python.org (check tcl/tk)."
}
Write-Host "[build_exe] python = $py"

& $py -m pip install --upgrade pip pyinstaller | Out-Host
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }

$distDir = Join-Path $WorkDir "_pyi_dist"
$workPyi = Join-Path $WorkDir "_pyi_work"
$specDir = Join-Path $WorkDir "_pyi_spec"
foreach ($d in @($distDir, $workPyi, $specDir)) {
  if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}

# NEVER use package __main__.py as PyInstaller entry — relative "from .main"
# becomes "attempted relative import with no known parent package".
New-Item -ItemType Directory -Force -Path $specDir | Out-Null
$entry = Join-Path $specDir "launch_aidogui.py"
@"
# PyInstaller entry (absolute imports only)
import sys
from pathlib import Path

# Frozen: _internal next to exe; also allow APP_ROOT on sys.path for desktop_app sources if needed
if getattr(sys, "frozen", False):
    app_root = Path(sys.executable).resolve().parent
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

from desktop_app.main import main
raise SystemExit(main())
"@ | Set-Content -Encoding UTF8 $entry

Push-Location $AppRoot
try {
  $env:PYTHONPATH = $AppRoot
  # Explicit onedir: produces _pyi_dist\AIDOGUI_MVP_Workbench\{exe,_internal\}
  & $py -m PyInstaller `
    --noconfirm `
    --windowed `
    --onedir `
    --name "AIDOGUI_MVP_Workbench" `
    --paths $AppRoot `
    --distpath $distDir `
    --workpath $workPyi `
    --specpath $specDir `
    --collect-all tkinter `
    --hidden-import desktop_app `
    --hidden-import desktop_app.gui_tk `
    --hidden-import desktop_app.env_isolate `
    --hidden-import desktop_app.runner `
    --hidden-import desktop_app.paths `
    $entry
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
} finally {
  Pop-Location
}

$onedir = Join-Path $distDir "AIDOGUI_MVP_Workbench"
$builtExe = Join-Path $onedir "AIDOGUI_MVP_Workbench.exe"
$builtInternal = Join-Path $onedir "_internal"
if (-not (Test-Path $builtExe)) {
  throw "EXE not found under $onedir (expected onedir layout)"
}
if (-not (Test-Path $builtInternal)) {
  throw "_internal folder missing under $onedir — refuse to publish a bare exe (would break Python DLL load)"
}

# Sync entire onedir contents into APP_ROOT (exe + _internal tree + any other assets)
Write-Host "[build_exe] Publishing onedir -> $AppRoot (exe + _internal\) ..."
$robolog = Join-Path $env:TEMP ("aidogui_pyi_publish_{0}.log" -f [guid]::NewGuid().ToString("N"))
& robocopy $onedir $AppRoot /E /IS /IT /NFL /NDL /NJH /NJS /nc /ns /np /LOG:$robolog | Out-Null
$rc = $LASTEXITCODE
# robocopy: 0-7 = success-ish; >=8 = failure
if ($rc -ge 8) {
  throw "robocopy failed with exit $rc (log: $robolog)"
}

$destExe = Join-Path $AppRoot "AIDOGUI_MVP_Workbench.exe"
$destInternal = Join-Path $AppRoot "_internal"
if (-not (Test-Path $destExe) -or -not (Test-Path $destInternal)) {
  throw "Publish incomplete: need both $destExe and $destInternal"
}

Write-Host ""
Write-Host "[build_exe] OK"
Write-Host "  EXE      : $destExe"
Write-Host "  _internal: $destInternal"
Write-Host ""
Write-Host "IMPORTANT: Keep AIDOGUI_MVP_Workbench.exe and _internal\ in the SAME folder."
Write-Host "           Do NOT move/copy only the .exe — Python DLL lives under _internal\"
Write-Host "           (error without it: Failed to load Python DLL ... _internal\python3xx.dll)."
Write-Host ""
Write-Host "Double-click AIDOGUI_MVP_Workbench.exe (or .bat). Keep engine/, scripts/, toolchain/ beside them."
Write-Host "Optional cleanup: remove _pyi_dist / _pyi_work / _pyi_spec"
