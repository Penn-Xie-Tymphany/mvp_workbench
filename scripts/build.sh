#!/usr/bin/env bash
# Configure + build the engine (sim_sdl + sim_script) on Linux.
set -euo pipefail
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
"${SCRIPTS}/detect_env.sh"
source "${SCRIPTS}/_common.sh"

cd "${AIDOGUI_ENGINE_ROOT}"
echo "[build] engine=${AIDOGUI_ENGINE_ROOT}"

ACTIVE_FILE="${AIDOGUI_ENGINE_ROOT}/ui_import/.active_project"
if [[ ! -f "${ACTIVE_FILE}" ]]; then
  echo "ERROR: missing ${ACTIVE_FILE}" >&2
  echo "  Import a project first: scripts/import_aidogui <export_dir> [project_name]" >&2
  exit 1
fi
UI_PROJECT="$(tr -d '\r\n' < "${ACTIVE_FILE}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
if [[ -z "${UI_PROJECT}" ]]; then
  echo "ERROR: ${ACTIVE_FILE} is empty" >&2
  exit 1
fi
echo "[build] UI_PROJECT=${UI_PROJECT}"

cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DLV_CONF_PATH="${LV_CONF_PATH}" \
  -DLV_CONF_BUILD_DISABLE_EXAMPLES=ON \
  -DLV_CONF_BUILD_DISABLE_DEMOS=ON \
  -DLV_CONF_BUILD_DISABLE_THORVG_INTERNAL=ON \
  -DUI_PROJECT="${UI_PROJECT}"
cmake --build build -j"$(nproc)"
echo "[build] OK -> ${ENGINE_BUILD}/sim_sdl , ${ENGINE_BUILD}/sim_script"
