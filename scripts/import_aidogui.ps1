# Copy AIDOGUI Export into engine ui_import and generate MVP skeleton.
# Usage: import_aidogui.ps1 -ExportDir <path> [-ProjectName <name>]
param(
  [Parameter(Mandatory = $true)][string]$ExportDir,
  [string]$ProjectName = ""
)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

if (-not (Test-Path -LiteralPath $ExportDir -PathType Container)) {
  Write-Error "Export dir not found: $ExportDir"
}
if (-not $ProjectName) {
  $ProjectName = Split-Path -Leaf $ExportDir
}
$uiH = Join-Path $ExportDir "ui.h"
if (-not (Test-Path -LiteralPath $uiH)) {
  Write-Error "No ui.h in $ExportDir — not an Export UI Files tree?"
}

$destEngine = Join-Path $script:EngineRoot "ui_import\$ProjectName"
$destWb = Join-Path $script:WbRoot "projects\$ProjectName"
New-Item -ItemType Directory -Force -Path (Split-Path $destEngine) | Out-Null
New-Item -ItemType Directory -Force -Path $destWb | Out-Null

$customBak = $null
$mvpBak = $null
$customSrc = Join-Path $destEngine "custom\custom.c"
if (Test-Path -LiteralPath $customSrc) {
  $customBak = Join-Path $env:TEMP ("aidogui_custom_" + [guid]::NewGuid().ToString() + ".c")
  Copy-Item -LiteralPath $customSrc -Destination $customBak -Force
  Write-Host "[import] backed up custom/custom.c"
}
$mvpSrc = Join-Path $destEngine "mvp"
if (Test-Path -LiteralPath $mvpSrc) {
  $mvpBak = Join-Path $env:TEMP ("aidogui_mvp_" + [guid]::NewGuid().ToString())
  New-Item -ItemType Directory -Force -Path $mvpBak | Out-Null
  Copy-Item -LiteralPath (Join-Path $mvpSrc "*") -Destination $mvpBak -Recurse -Force
  Write-Host "[import] backed up mvp/"
}

if (Test-Path -LiteralPath $destEngine) { Remove-Item -LiteralPath $destEngine -Recurse -Force }
New-Item -ItemType Directory -Force -Path $destEngine | Out-Null
# -Path (NOT -LiteralPath): the trailing "\*" must be treated as a wildcard,
# otherwise zero files get copied into the fresh project dir.
Copy-Item -Path (Join-Path $ExportDir "*") -Destination $destEngine -Recurse -Force

if ($customBak) {
  $customDir = Join-Path $destEngine "custom"
  New-Item -ItemType Directory -Force -Path $customDir | Out-Null
  Copy-Item -LiteralPath $customBak -Destination (Join-Path $customDir "custom.c") -Force
  Remove-Item -LiteralPath $customBak -Force
  Write-Host "[import] restored custom/custom.c"
}
if ($mvpBak) {
  $mvpDir = Join-Path $destEngine "mvp"
  New-Item -ItemType Directory -Force -Path $mvpDir | Out-Null
  foreach ($f in @("app_model.c", "view_apply.c", "app_model_user.h")) {
    $src = Join-Path $mvpBak $f
    if (Test-Path -LiteralPath $src) {
      Copy-Item -LiteralPath $src -Destination (Join-Path $mvpDir $f) -Force
    }
  }
  Remove-Item -LiteralPath $mvpBak -Recurse -Force
  Write-Host "[import] restored mvp USER files"
}

$genPy = Join-Path $script:WbRoot "scripts\gen_mvp.py"
if (-not (Test-Path -LiteralPath $genPy)) {
  $genPy = Join-Path $AIDOGUI_ENGINE_ROOT "..\workbench\scripts\gen_mvp.py"
}
if (Test-Path -LiteralPath $genPy) {
  & python $genPy $destEngine
  if ($LASTEXITCODE -ne 0) { Write-Error "gen_mvp.py failed" }
} else {
  Write-Warning "gen_mvp.py not found — MVP sources not generated"
}

# Junction / link for workbench projects
$uiLink = Join-Path $destWb "ui"
if (Test-Path -LiteralPath $uiLink) { Remove-Item -LiteralPath $uiLink -Force -Recurse -ErrorAction SilentlyContinue }
cmd /c mklink /J "$uiLink" "$destEngine" | Out-Null

$active = Join-Path $script:EngineRoot "ui_import\.active_project"
Set-Content -LiteralPath $active -Value $ProjectName -NoNewline -Encoding Ascii
Write-Host "[import] active project: $ProjectName"
Write-Host "[import] engine: $destEngine"
Write-Host "[import] done."
