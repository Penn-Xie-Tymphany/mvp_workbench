#!/usr/bin/env bash
# Linux twin: detect gcc/g++/cmake/SDL2 for building the engine.
set -euo pipefail
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPTS_DIR}/_common.sh"

ok()   { printf "  %-12s OK       %s\n" "$1" "$2"; }
miss() { printf "  %-12s MISSING  %s\n" "$1" "$2"; FAIL=1; }

FAIL=0
echo ""
echo "=== AIDOGUI MVP workbench · env detect (Linux) ==="
echo "workbench: ${AIDOGUI_WB_ROOT}"
echo ""

if [[ -x /workspace/tools/cmake/bin/cmake ]]; then
  export PATH="/workspace/tools/cmake/bin:${PATH}"
fi

GCC_BIN="$(command -v gcc || true)"
GPP_BIN="$(command -v g++ || true)"
CMAKE_BIN="$(command -v cmake || true)"

if [[ -n "${GCC_BIN}" ]]; then ok "gcc" "${GCC_BIN} ($(gcc --version | head -1))"; else miss "gcc" "install build-essential"; fi
if [[ -n "${GPP_BIN}" ]]; then ok "g++" "${GPP_BIN}"; else miss "g++" "install g++"; fi
if [[ -n "${CMAKE_BIN}" ]]; then ok "cmake" "${CMAKE_BIN} ($(cmake --version | head -1))"; else miss "cmake" "install cmake or use /workspace/tools/cmake"; fi

SDL_HIT=""
for c in \
  "${SDL2_DIR:-}/include/SDL2/SDL.h" \
  /usr/include/SDL2/SDL.h \
  /usr/local/include/SDL2/SDL.h \
  /workspace/tools/sdl2/include/SDL2/SDL.h
do
  if [[ -n "$c" && -f "$c" ]]; then SDL_HIT="$c"; break; fi
done
if [[ -n "${SDL_HIT}" ]]; then ok "SDL2" "${SDL_HIT}"; else miss "SDL2" "libsdl2-dev or SDL2_DIR"; fi

echo ""
if [[ "${FAIL}" -ne 0 ]]; then
  echo "[detect_env] FAILED — see workbench/docs/INSTALL_TOOLCHAIN_WIN.md (Win) or install gcc/cmake/libsdl2-dev"
  exit 1
fi
echo "[detect_env] OK — all required tools found."
exit 0
