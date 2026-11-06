# Detect gcc / g++ / cmake / SDL2 for AIDOGUI MVP workbench (Windows).
# Prefers: workbench\toolchain\* → env vars → PATH → common paths.
# Prints OK/MISSING table. Exit 1 if any required tool missing.
$ErrorActionPreference = "Continue"
$ScriptsDir = $PSScriptRoot
$WbRoot = (Resolve-Path (Join-Path $ScriptsDir "..")).Path
$Tb = Join-Path $WbRoot "toolchain"

function Add-PathFront([string]$dir) {
  if (-not $dir) { return }
  if (-not (Test-Path $dir)) { return }
  $parts = @($env:PATH -split ";" | Where-Object { $_ -and $_.Trim() -ne "" })
  if ($parts -contains $dir) { return }
  $env:PATH = "$dir;$env:PATH"
}

function Find-File([string[]]$candidates) {
  foreach ($c in $candidates) {
    if ($c -and (Test-Path -LiteralPath $c)) { return (Resolve-Path -LiteralPath $c).Path }
  }
  return $null
}

function Ver-Line([string]$exe) {
  if (-not $exe) { return "" }
  try {
    $o = & $exe --version 2>&1 | Select-Object -First 1
    return "$o"
  } catch { return "" }
}

# --- MinGW / gcc ---
$gccCandidates = @(
  (Join-Path $Tb "mingw64\bin\gcc.exe"),
  $(if ($env:MINGW_HOME) { Join-Path $env:MINGW_HOME "bin\gcc.exe" } else { $null }),
  "C:\mingw64\bin\gcc.exe",
  "C:\MinGW\bin\gcc.exe"
)
$gccPath = Find-File $gccCandidates
if (-not $gccPath) {
  $cmd = Get-Command gcc -ErrorAction SilentlyContinue
  if ($cmd) { $gccPath = $cmd.Source }
}
if ($gccPath) {
  $mingwBin = Split-Path $gccPath -Parent
  Add-PathFront $mingwBin
  if (-not $env:MINGW_HOME) {
    $env:MINGW_HOME = Split-Path $mingwBin -Parent
  }
}

$gppCandidates = @(
  (Join-Path $Tb "mingw64\bin\g++.exe"),
  $(if ($env:MINGW_HOME) { Join-Path $env:MINGW_HOME "bin\g++.exe" } else { $null }),
  "C:\mingw64\bin\g++.exe"
)
$gppPath = Find-File $gppCandidates
if (-not $gppPath) {
  $cmd = Get-Command g++ -ErrorAction SilentlyContinue
  if ($cmd) { $gppPath = $cmd.Source }
}
if ($gppPath) { Add-PathFront (Split-Path $gppPath -Parent) }

# --- CMake ---
$cmakeCandidates = @(
  (Join-Path $Tb "cmake\bin\cmake.exe"),
  $(if ($env:CMAKE_HOME) { Join-Path $env:CMAKE_HOME "bin\cmake.exe" } else { $null }),
  "C:\cmake\bin\cmake.exe",
  "C:\Program Files\CMake\bin\cmake.exe",
  "C:\Program Files (x86)\CMake\bin\cmake.exe"
)
$cmakePath = Find-File $cmakeCandidates
if (-not $cmakePath) {
  $cmd = Get-Command cmake -ErrorAction SilentlyContinue
  if ($cmd) { $cmakePath = $cmd.Source }
}
if ($cmakePath) {
  Add-PathFront (Split-Path $cmakePath -Parent)
  if (-not $env:CMAKE_HOME) {
    $env:CMAKE_HOME = Split-Path (Split-Path $cmakePath -Parent) -Parent
  }
}

# --- SDL2 (header → root = parent of "include") ---
$sdlHeaderCandidates = @(
  (Join-Path $Tb "sdl2\include\SDL2\SDL.h"),
  $(if ($env:SDL2_DIR) { Join-Path $env:SDL2_DIR "include\SDL2\SDL.h" } else { $null }),
  "C:\SDL2\include\SDL2\SDL.h",
  "C:\sdl2\include\SDL2\SDL.h"
)
$sdlHeader = Find-File $sdlHeaderCandidates
$sdlRoot = $null
if ($sdlHeader) {
  # file: <root>/include/SDL2/SDL.h
  $sdlRoot = (Resolve-Path (Join-Path (Split-Path $sdlHeader -Parent) "../..")).Path
}
if (-not $sdlRoot -and $env:SDL2_DIR -and (Test-Path $env:SDL2_DIR)) {
  $sdlRoot = (Resolve-Path $env:SDL2_DIR).Path
}
if ($sdlRoot) {
  # Forward slashes for CMake / MinGW make / ld (backslash escapes get eaten)
  # Literal replace (no regex): backslash escapes get eaten by CMake/MinGW
  $env:SDL2_DIR = $sdlRoot.Replace('\', '/')
  Add-PathFront (Join-Path $sdlRoot "bin")
  $sdlLib = Join-Path $sdlRoot "lib"
  if (Test-Path $sdlLib) {
    if ($env:LIBRARY_PATH) { $env:LIBRARY_PATH = "$sdlLib;$env:LIBRARY_PATH" }
    else { $env:LIBRARY_PATH = $sdlLib }
  }
}

if ($gccPath -and -not $env:CMAKE_GENERATOR) {
  $env:CMAKE_GENERATOR = "MinGW Makefiles"
}

$rows = @()
function Add-Row($name, $required, $path, $note) {
  $status = if ($path) { "OK" } else { "MISSING" }
  $script:rows += [pscustomobject]@{
    Component = $name
    Required  = $required
    Status    = $status
    Path      = $(if ($path) { $path } else { "-" })
    Note      = $note
  }
}

Add-Row "gcc" $true $gccPath (Ver-Line $gccPath)
Add-Row "g++" $true $gppPath (Ver-Line $gppPath)
Add-Row "cmake" $true $cmakePath (Ver-Line $cmakePath)
$sdlNote = if ($sdlRoot) { "SDL2_DIR=$sdlRoot" } else { "set SDL2_DIR or place toolchain\sdl2 — see docs\INSTALL_TOOLCHAIN_WIN.md" }
Add-Row "SDL2 headers" $true $(if ($sdlHeader) { $sdlHeader } else { $null }) $sdlNote

$sdlDll = $null
if ($sdlRoot) {
  $sdlDll = Find-File @(
    (Join-Path $sdlRoot "bin\SDL2.dll"),
    (Join-Path $Tb "sdl2\bin\SDL2.dll")
  )
}
Add-Row "SDL2.dll" $false $sdlDll "runtime; build stages next to sim_*.exe when present"

Write-Host ""
Write-Host "=== AIDOGUI MVP workbench · env detect ==="
Write-Host "workbench: $WbRoot"
Write-Host ""
Write-Host ("{0,-14} {1,-8} {2,-8} {3}" -f "Component", "Need", "Status", "Path")
Write-Host ("{0,-14} {1,-8} {2,-8} {3}" -f "---------", "----", "------", "----")
foreach ($r in $rows) {
  $need = if ($r.Required) { "yes" } else { "no" }
  Write-Host ("{0,-14} {1,-8} {2,-8} {3}" -f $r.Component, $need, $r.Status, $r.Path)
}
Write-Host ""
foreach ($r in $rows) {
  if ($r.Note) { Write-Host ("  · {0}: {1}" -f $r.Component, $r.Note) }
}
Write-Host ""

$missing = @($rows | Where-Object { $_.Required -eq $true -and $_.Status -eq "MISSING" })
if ($missing.Count -gt 0) {
  Write-Host "[detect_env] FAILED — missing: $($missing.Component -join ', ')"
  Write-Host "See: workbench\docs\INSTALL_TOOLCHAIN_WIN.md"
  exit 1
}
Write-Host "[detect_env] OK — all required tools found."
exit 0
