#!/usr/bin/env bash
# Copy an AIDOGUI "Export UI Files" directory into the engine ui_import slot,
# generate MVP V/P/Model skeleton, and refresh the workbench project pointer.
#
# Usage: import_aidogui.sh <export_dir> [project_name]
# project_name defaults to the export directory basename (required conceptually).
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

SRC="${1:-}"
NAME="${2:-}"
if [[ -z "${SRC}" || ! -d "${SRC}" ]]; then
  echo "Usage: $0 <aidogui_export_dir> [project_name]"
  echo "  project_name defaults to basename of export_dir"
  exit 2
fi
if [[ -z "${NAME}" ]]; then
  NAME="$(basename "${SRC}")"
fi
if [[ ! -f "${SRC}/ui.h" ]]; then
  echo "ERROR: ${SRC} has no ui.h — not an Export UI Files tree?"
  exit 1
fi

DEST_ENGINE="${AIDOGUI_ENGINE_ROOT}/ui_import/${NAME}"
DEST_WB="${AIDOGUI_WB_ROOT}/projects/${NAME}"

mkdir -p "$(dirname "${DEST_ENGINE}")" "${DEST_WB}"

# Preserve custom/custom.c and mvp USER files if present
CUSTOM_BAK=""
MVP_BAK=""
if [[ -f "${DEST_ENGINE}/custom/custom.c" ]]; then
  CUSTOM_BAK="$(mktemp)"
  cp -a "${DEST_ENGINE}/custom/custom.c" "${CUSTOM_BAK}"
  echo "[import] backed up custom/custom.c"
fi
if [[ -d "${DEST_ENGINE}/mvp" ]]; then
  MVP_BAK="$(mktemp -d)"
  cp -a "${DEST_ENGINE}/mvp/." "${MVP_BAK}/"
  echo "[import] backed up mvp/ (for USER merge)"
fi

rm -rf "${DEST_ENGINE}"
mkdir -p "${DEST_ENGINE}"
cp -a "${SRC}/." "${DEST_ENGINE}/"

if [[ -n "${CUSTOM_BAK}" ]]; then
  mkdir -p "${DEST_ENGINE}/custom"
  cp -a "${CUSTOM_BAK}" "${DEST_ENGINE}/custom/custom.c"
  rm -f "${CUSTOM_BAK}"
  echo "[import] restored custom/custom.c"
fi
if [[ -n "${MVP_BAK}" ]]; then
  mkdir -p "${DEST_ENGINE}/mvp"
  # Restore USER-bearing files so gen_mvp keeps them
  for f in app_model.c view_apply.c app_model_user.h; do
    if [[ -f "${MVP_BAK}/${f}" ]]; then
      cp -a "${MVP_BAK}/${f}" "${DEST_ENGINE}/mvp/${f}"
    fi
  done
  rm -rf "${MVP_BAK}"
  echo "[import] restored mvp USER files"
fi

# Generate / refresh MVP V+P+Model skeleton
GEN_PY="${AIDOGUI_WB_ROOT}/scripts/gen_mvp.py"
if [[ ! -f "${GEN_PY}" ]]; then
  GEN_PY="${AIDOGUI_ENGINE_ROOT}/../workbench/scripts/gen_mvp.py"
fi
if [[ -f "${GEN_PY}" ]]; then
  python3 "${GEN_PY}" "${DEST_ENGINE}"
else
  echo "WARNING: gen_mvp.py not found — MVP sources not generated"
fi

# Workbench project slot: symlink ui -> engine import (Linux)
ln -sfn "${DEST_ENGINE}" "${DEST_WB}/ui"

# Remember active project for cmake -DUI_PROJECT
ACTIVE_FILE="${AIDOGUI_ENGINE_ROOT}/ui_import/.active_project"
printf '%s\n' "${NAME}" > "${ACTIVE_FILE}"
echo "[import] active project: ${NAME} (${ACTIVE_FILE})"

echo "[import] engine: ${DEST_ENGINE}"
echo "[import] workbench projects/${NAME}/ui -> engine"
echo "[import] done. Next: scripts/build.sh && scripts/run_script.sh"
