param(
  [ValidateSet("workbench", "engine")]
  [string]$Mode = "workbench",
  [string]$Tag = ""   # e.g. v9.3.0; empty = baseline default
)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

if (-not $Tag) { $Tag = "v9.3.0" }   # baseline LVGL for new installs
$Ver = $Tag.TrimStart("v")
$tmp = Join-Path $env:TEMP "lvgl_fetch_$PID"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

# Prefer git shallow clone (fast); fall back to zip.
$src = $null
$gitDest = Join-Path $tmp "git"
git clone --depth 1 --branch $Tag --single-branch https://github.com/lvgl/lvgl.git $gitDest 2>$null
if (Test-Path (Join-Path $gitDest "lv_version.h")) {
    $src = $gitDest
} else {
    $zip = Join-Path $tmp "lvgl.zip"
    $Url = "https://github.com/lvgl/lvgl/archive/refs/tags/$Tag.zip"
    Write-Host "[fetch_lvgl] $Url"
    Invoke-WebRequest -Uri $Url -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp "out") -Force
    $src = Get-ChildItem (Join-Path $tmp "out") -Directory | Where-Object { $_.Name -like "lvgl-*" } | Select-Object -First 1
}
if (-not $src) { throw "download failed or unexpected layout" }

if ($Mode -eq "engine") {
    # Versioned layout: vendor/lvgl_versions/<ver> + junction vendor/lvgl
    $versionsDir = Join-Path $EngineRoot "vendor\lvgl_versions"
    New-Item -ItemType Directory -Force -Path $versionsDir | Out-Null
    $verDir = Join-Path $versionsDir $Ver
    if (Test-Path $verDir) { Remove-Item -Recurse -Force $verDir }
    Move-Item $src.FullName $verDir
    $link = Join-Path $EngineRoot "vendor\lvgl"
    if (Test-Path $link) {
        if ((Get-Item $link).LinkType -eq "Junction") {
            [System.IO.Directory]::Delete($link, $false)  # junction only
        } else {
            Remove-Item -Recurse -Force $link  # legacy plain dir
        }
    }
    cmd /c mklink /J "$link" "$verDir" | Out-Null
    Set-Content -Path (Join-Path $EngineRoot "vendor\lvgl_active.txt") -Value $Ver -Encoding Ascii
    Write-Host "[fetch_lvgl] $Tag -> vendor\lvgl_versions\$Ver (junction active)"
} else {
    $dest = Join-Path $WbRoot "lvgl\$Tag"
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    Move-Item $src.FullName $dest
    Write-Host "[fetch_lvgl] installed -> $dest"
}
Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue