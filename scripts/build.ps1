$ErrorActionPreference = "Stop"

# Detect / inject PATH + SDL2_DIR before _common (detect also prepends toolchain if present)
$detect = Join-Path $PSScriptRoot "detect_env.ps1"
& $detect
if ($LASTEXITCODE -ne 0) {
  throw "Environment check failed. Install tools per workbench\docs\INSTALL_TOOLCHAIN_WIN.md then re-run scripts\detect_env.bat"
}

. "$PSScriptRoot\_common.ps1"

# Win → CMake/MinGW: backslashes in -D paths get eaten by make/ld.
# Always pass forward-slash (cmake-style) paths for SDL2_DIR / SDL2_LIBRARY.
function ConvertTo-CmakePath([string]$p) {
  if (-not $p) { return $p }
  return ($p -replace '\\', '/')
}

Write-Host "[build] engine=$EngineRoot"
$cmake = Get-Command cmake -ErrorAction SilentlyContinue
if (-not $cmake) {
  throw "cmake not found after detect. See docs\INSTALL_TOOLCHAIN_WIN.md"
}
$gcc = Get-Command gcc -ErrorAction SilentlyContinue
if (-not $gcc) {
  throw "gcc not found after detect. See docs\INSTALL_TOOLCHAIN_WIN.md"
}

$buildDir = Join-Path $EngineRoot "build"
$genArgs = @()
if ($env:CMAKE_GENERATOR) {
  $genArgs += @("-G", $env:CMAKE_GENERATOR)
}

$cmakeExtra = @()
$sdlDirNative = $null
if ($env:SDL2_DIR) {
  $sdlDirNative = $env:SDL2_DIR
} elseif (Test-Path (Join-Path $WbRoot "toolchain\sdl2\include\SDL2\SDL.h")) {
  $sdlDirNative = (Resolve-Path (Join-Path $WbRoot "toolchain\sdl2")).Path
}

if ($sdlDirNative) {
  $sdlCmake = ConvertTo-CmakePath $sdlDirNative
  $env:SDL2_DIR = $sdlCmake
  $cmakeExtra += "-DSDL2_DIR=$sdlCmake"
  $libDllA = Join-Path $sdlDirNative "lib\libSDL2.dll.a"
  $libA = Join-Path $sdlDirNative "lib\libSDL2.a"
  $libSo = Join-Path $sdlDirNative "lib\libSDL2.so"
  if (Test-Path $libDllA) {
    $cmakeExtra += "-DSDL2_LIBRARY=$(ConvertTo-CmakePath $libDllA)"
  } elseif (Test-Path $libA) {
    $cmakeExtra += "-DSDL2_LIBRARY=$(ConvertTo-CmakePath $libA)"
  } elseif (Test-Path $libSo) {
    $cmakeExtra += "-DSDL2_LIBRARY=$(ConvertTo-CmakePath $libSo)"
  }
  Write-Host "[build] SDL2_DIR(cmake)=$sdlCmake"
}


# Active UI project (optional override via -DUI_PROJECT)
$uiProject = $null
$activeProj = Join-Path $EngineRoot "ui_import\.active_project"
if (Test-Path $activeProj) {
  $uiProject = (Get-Content -Path $activeProj -Raw).Trim()
}
if (-not $uiProject) {
  throw "No active UI project. Create ui_import\.active_project or Import first."
}
$cmakeExtra += "-DUI_PROJECT=$uiProject"
Write-Host "[build] UI_PROJECT=$uiProject"

$lvConfCmake = ConvertTo-CmakePath $LvConf
$engineCmake = ConvertTo-CmakePath $EngineRoot
$buildCmake = ConvertTo-CmakePath $buildDir

# Sync lv_conf.h LV_COLOR_DEPTH to the ACTIVE project (AIDOGUI exports carry
# per-project color-depth guards in ui.c — mismatch = #error at compile).
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
  & python (Join-Path $PSScriptRoot "sync_project_conf.py")
}

# LVGL >= 9.3 uses new CONFIG_* build options (thorvg internal fails under
# MinGW); keep the old LV_CONF_BUILD_* flags too for LVGL 9.2 compatibility.
# NOTE: no comments inside the backtick-continued command below!
& cmake -S $engineCmake -B $buildCmake @genArgs -DCMAKE_BUILD_TYPE=Release `
  "-DLV_CONF_PATH=$lvConfCmake" `
  -DLV_CONF_BUILD_DISABLE_EXAMPLES=ON `
  -DLV_CONF_BUILD_DISABLE_DEMOS=ON `
  -DLV_CONF_BUILD_DISABLE_THORVG_INTERNAL=ON `
  -DCONFIG_LV_BUILD_EXAMPLES=OFF `
  -DCONFIG_LV_BUILD_DEMOS=OFF `
  -DCONFIG_LV_USE_THORVG_INTERNAL=OFF `
  @cmakeExtra
if ($LASTEXITCODE -ne 0) { throw "cmake configure failed" }

$jobs = [Environment]::ProcessorCount
if ($env:CMAKE_GENERATOR -match "MinGW") {
  & cmake --build $buildCmake -- -j $jobs
} else {
  & cmake --build $buildCmake --config Release -j $jobs
}
if ($LASTEXITCODE -ne 0) { throw "cmake build failed" }

# Stage SDL2.dll next to exes and into workbench\bin for run_*.bat
$sdlDllCandidates = @()
if ($sdlDirNative) { $sdlDllCandidates += (Join-Path $sdlDirNative "bin\SDL2.dll") }
if ($env:SDL2_DIR) { $sdlDllCandidates += (Join-Path (($env:SDL2_DIR -replace '/', '\')) "bin\SDL2.dll") }
$sdlDllCandidates += (Join-Path $WbRoot "toolchain\sdl2\bin\SDL2.dll")
$sdlDll = $null
foreach ($c in $sdlDllCandidates) {
  if ($c -and (Test-Path $c)) { $sdlDll = $c; break }
}
$binDir = Join-Path $WbRoot "bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
foreach ($name in @("sim_sdl.exe", "sim_script.exe")) {
  $src = Join-Path $buildDir $name
  if (-not (Test-Path $src)) { $src = Join-Path $buildDir "Release\$name" }
  if (Test-Path $src) {
    Copy-Item -Force $src (Join-Path $binDir $name)
    if ($sdlDll) {
      Copy-Item -Force $sdlDll (Join-Path $binDir "SDL2.dll")
      Copy-Item -Force $sdlDll (Join-Path (Split-Path $src -Parent) "SDL2.dll")
    }
  }
}

# --- footprint report (static sizes — rough flash/RAM reference) ---
$sizeExe = Join-Path $WbRoot "toolchain\mingw64\bin\size.exe"
if (Test-Path $sizeExe) {
  foreach ($name in @("sim_sdl.exe", "sim_script.exe")) {
    $exe = Join-Path $buildDir $name
    if (Test-Path $exe) {
      $out = & $sizeExe $exe 2>$null
      if ($out -and $out.Count -ge 2) {
        $cols = ($out[1] -split '\s+') | Where-Object { $_ -ne "" }
        if ($cols.Count -ge 4) {
          $text = [long]$cols[0]; $data = [long]$cols[1]; $bss = [long]$cols[2]; $dec = [long]$cols[3]
          Write-Host ("[size] {0}: text={1}KB data={2}KB bss={3}KB -> flash~{4}KB / staticRAM~{5}KB" -f `
            $name, [int]($text / 1024), [int]($data / 1024), [int]($bss / 1024), `
            [int]($dec / 1024), [int](($data + $bss) / 1024))
        }
      }
    }
  }
}

Write-Host "[build] OK -> $buildDir\sim_sdl.exe , sim_script.exe (also staged to bin\)"
