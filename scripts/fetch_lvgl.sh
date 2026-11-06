#!/usr/bin/env bash
# Download LVGL v9.2.2 into workbench/lvgl/src (or ENGINE vendor if --engine).
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

TAG="v9.2.2"
MODE="${1:-workbench}"  # workbench | engine
URL="https://github.com/lvgl/lvgl/archive/refs/tags/${TAG}.zip"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

echo "[fetch_lvgl] ${URL}"
if command -v curl >/dev/null; then
  curl -fsSL -o "${TMP}/lvgl.zip" "${URL}"
elif command -v wget >/dev/null; then
  wget -q -O "${TMP}/lvgl.zip" "${URL}"
else
  echo "ERROR: need curl or wget"
  exit 1
fi

unzip -q "${TMP}/lvgl.zip" -d "${TMP}/out"
SRC_DIR="$(find "${TMP}/out" -maxdepth 1 -type d -name 'lvgl-*' | head -1)"

if [[ "${MODE}" == "engine" ]]; then
  DEST="${AIDOGUI_ENGINE_ROOT}/vendor/lvgl"
else
  DEST="${AIDOGUI_WB_ROOT}/lvgl/${TAG}"
fi

rm -rf "${DEST}"
mkdir -p "$(dirname "${DEST}")"
mv "${SRC_DIR}" "${DEST}"
echo "[fetch_lvgl] installed -> ${DEST}"
test -f "${DEST}/lvgl.h"
