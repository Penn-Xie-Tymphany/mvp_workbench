# Shared path resolution for Windows workbench scripts.
$script:ScriptsDir = $PSScriptRoot
$script:WbRoot = (Resolve-Path (Join-Path $ScriptsDir "..")).Path
# Packaged: WB_ROOT/engine ; Dev workbench: engine = parent of workbench
$packagedEngine = Join-Path $script:WbRoot "engine"
if (Test-Path (Join-Path $packagedEngine "CMakeLists.txt")) {
  $script:EngineRoot = (Resolve-Path $packagedEngine).Path
} else {
  $script:EngineRoot = (Resolve-Path (Join-Path $script:WbRoot "..")).Path
}
$env:AIDOGUI_WB_ROOT = $script:WbRoot
$env:AIDOGUI_ENGINE_ROOT = $script:EngineRoot
$script:EngineBuild = Join-Path $script:EngineRoot "build"
$script:WbCsv = Join-Path $script:WbRoot "tests\transitions_snake.csv"
$script:LvConf = Join-Path $script:EngineRoot "lv_conf.h"

# Win → CMake: paths with \ get eaten by MinGW make/ld. Prefer / for SDL2_DIR.
function ConvertTo-CmakePath([string]$p) {
  if (-not $p) { return $p }
  return ($p -replace '\\', '/')
}

# Load portable toolchain into this process PATH
$envBat = Join-Path $script:WbRoot "toolchain\env.bat"
if (Test-Path $envBat) {
  # env.bat echoes; call via cmd to mutate PATH for child — for PS we prepend manually
  $tb = Join-Path $script:WbRoot "toolchain"
  foreach ($p in @(
      (Join-Path $tb "mingw64\bin"),
      (Join-Path $tb "cmake\bin"),
      (Join-Path $tb "sdl2\bin")
    )) {
    if (Test-Path $p) {
      if (-not (($env:PATH -split ";") -contains $p)) {
        $env:PATH = "$p;$env:PATH"
      }
    }
  }
  $sdl2 = Join-Path $tb "sdl2"
  if (Test-Path $sdl2) {
    # Keep native form for Test-Path / Copy-Item; also expose cmake-style
    $env:SDL2_DIR = (ConvertTo-CmakePath $sdl2)
    $sdlLib = Join-Path $sdl2 "lib"
    if (Test-Path $sdlLib) {
      if ($env:LIBRARY_PATH) {
        $env:LIBRARY_PATH = "$sdlLib;$env:LIBRARY_PATH"
      } else {
        $env:LIBRARY_PATH = $sdlLib
      }
    }
  }
  $mingw = Join-Path $tb "mingw64"
  $crt = Join-Path $mingw "x86_64-w64-mingw32\lib\crt2.o"
  if (Test-Path $crt) {
    $lib = "$(Join-Path $mingw 'x86_64-w64-mingw32\lib');$(Join-Path $mingw 'lib')"
    if ($env:LIBRARY_PATH) {
      $env:LIBRARY_PATH = "$lib;$env:LIBRARY_PATH"
    } else {
      $env:LIBRARY_PATH = $lib
    }
    $inc = "$(Join-Path $mingw 'x86_64-w64-mingw32\include');$(Join-Path $mingw 'include')"
    $env:C_INCLUDE_PATH = $inc
    $env:CPLUS_INCLUDE_PATH = $inc
  }
  if (Test-Path (Join-Path $tb "mingw64\bin\gcc.exe")) {
    $env:CMAKE_GENERATOR = "MinGW Makefiles"
  }
}
