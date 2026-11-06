#!/usr/bin/env bash
# Launch human SDL simulator.
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

BIN="${AIDOGUI_WB_ROOT}/bin/sim_sdl"
[[ -x "${BIN}" ]] || BIN="${ENGINE_BUILD}/sim_sdl"
if [[ ! -x "${BIN}" ]]; then
  echo "ERROR: sim_sdl not found. Run scripts/build.sh first."
  exit 1
fi
echo "[run_sim] ${BIN}"
exec "${BIN}" "$@"
