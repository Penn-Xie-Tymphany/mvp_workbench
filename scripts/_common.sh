#!/usr/bin/env bash
# Resolve workbench + engine roots for Linux twin scripts.
set -euo pipefail
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AIDOGUI_WB_ROOT="$(cd "${SCRIPTS_DIR}/.." && pwd)"
# Packaged: WB_ROOT/engine ; Dev: engine = parent of workbench/
if [[ -f "${AIDOGUI_WB_ROOT}/engine/CMakeLists.txt" ]]; then
  export AIDOGUI_ENGINE_ROOT="$(cd "${AIDOGUI_WB_ROOT}/engine" && pwd)"
else
  export AIDOGUI_ENGINE_ROOT="$(cd "${AIDOGUI_WB_ROOT}/.." && pwd)"
fi

# Prefer staged cmake on the box
if [[ -x /workspace/tools/cmake/bin/cmake ]]; then
  export PATH="/workspace/tools/cmake/bin:${PATH}"
fi

export LV_CONF_PATH="${AIDOGUI_ENGINE_ROOT}/lv_conf.h"
export ENGINE_BUILD="${AIDOGUI_ENGINE_ROOT}/build"
export WB_CSV="${AIDOGUI_WB_ROOT}/tests/transitions_snake.csv"
