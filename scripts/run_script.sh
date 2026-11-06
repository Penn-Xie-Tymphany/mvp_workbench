#!/usr/bin/env bash
# Run CSV or CMD-script automation (headless-friendly).
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

CSV="${1:-${WB_CSV}}"
BIN="${AIDOGUI_WB_ROOT}/bin/sim_script"
[[ -x "${BIN}" ]] || BIN="${ENGINE_BUILD}/sim_script"
if [[ ! -x "${BIN}" ]]; then
  echo "ERROR: sim_script not found. Run scripts/build.sh first."
  exit 1
fi
if [[ ! -f "${CSV}" ]]; then
  echo "ERROR: script file not found: ${CSV}"
  exit 1
fi
echo "[run_script] bin=${BIN}"
echo "[run_script] script=${CSV}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-dummy}"
exec "${BIN}" "${CSV}"
