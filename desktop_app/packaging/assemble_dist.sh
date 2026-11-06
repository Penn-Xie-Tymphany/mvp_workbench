#!/usr/bin/env bash
# Assemble Windows-oriented APP_ROOT layout on Linux (box).
# Mirrors packaging/assemble_dist.ps1 + ships bat launchers / Tools menu.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_NAME="AIDOGUI_MVP_Workbench"
DIST_ROOT="${1:-$REPO_ROOT/dist/$DIST_NAME}"
SKIP_TOOLCHAIN_COPY="${SKIP_TOOLCHAIN_COPY:-0}"
USE_HARDLINK_TOOLCHAIN="${USE_HARDLINK_TOOLCHAIN:-1}"

echo "[assemble] REPO_ROOT=$REPO_ROOT"
echo "[assemble] DIST_ROOT=$DIST_ROOT"

rm -rf "$DIST_ROOT"
mkdir -p "$DIST_ROOT"

copy_tree() {
  local src="$1" dest="$2"
  mkdir -p "$dest"
  # Prefer cp -a; exclude via tar when needed
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$src"/ "$dest"/
  else
    cp -a "$src"/. "$dest"/
  fi
}

copy_tree_filtered() {
  # copy engine-like tree excluding heavy/dev dirs
  local src="$1" dest="$2"
  mkdir -p "$dest"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude 'build/' \
      --exclude 'desktop_app/' \
      --exclude 'workbench/' \
      --exclude '.git/' \
      --exclude '__pycache__/' \
      --exclude '.venv/' \
      --exclude 'dist/' \
      --exclude '*.pyc' \
      "$src"/ "$dest"/
  else
    # tar filter copy
    (cd "$src" && tar \
      --exclude='./build' \
      --exclude='./desktop_app' \
      --exclude='./workbench' \
      --exclude='./.git' \
      --exclude='./__pycache__' \
      --exclude='./.venv' \
      --exclude='./dist' \
      --exclude='*.pyc' \
      -cf - .) | (cd "$dest" && tar -xf -)
  fi
}

echo "[assemble] engine/"
copy_tree_filtered "$REPO_ROOT" "$DIST_ROOT/engine"

echo "[assemble] scripts/"
copy_tree "$REPO_ROOT/workbench/scripts" "$DIST_ROOT/scripts"

echo "[assemble] projects/"
copy_tree "$REPO_ROOT/workbench/projects" "$DIST_ROOT/projects"

echo "[assemble] tests/"
copy_tree "$REPO_ROOT/workbench/tests" "$DIST_ROOT/tests"

echo "[assemble] desktop_app/ (no .venv)"
mkdir -p "$DIST_ROOT/desktop_app"
if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.gitignore' \
    "$REPO_ROOT/desktop_app"/ "$DIST_ROOT/desktop_app"/
else
  (cd "$REPO_ROOT/desktop_app" && tar \
    --exclude='./.venv' \
    --exclude='./__pycache__' \
    --exclude='*.pyc' \
    --exclude='./.gitignore' \
    -cf - .) | (cd "$DIST_ROOT/desktop_app" && tar -xf -)
fi

echo "[assemble] toolchain/"
mkdir -p "$DIST_ROOT/toolchain"
if [[ "$SKIP_TOOLCHAIN_COPY" == "1" ]]; then
  echo "[assemble] SKIP_TOOLCHAIN_COPY=1 — only meta files"
  for f in README.md VERSIONS.md bootstrap.bat bootstrap.ps1 env.bat; do
    [[ -f "$REPO_ROOT/workbench/toolchain/$f" ]] && cp -a "$REPO_ROOT/workbench/toolchain/$f" "$DIST_ROOT/toolchain/"
  done
  # still try sdl2 (small)
  if [[ -d "$REPO_ROOT/workbench/toolchain/sdl2" ]]; then
    copy_tree "$REPO_ROOT/workbench/toolchain/sdl2" "$DIST_ROOT/toolchain/sdl2"
  fi
else
  # Copy meta always as real files
  for f in README.md VERSIONS.md bootstrap.bat bootstrap.ps1 env.bat; do
    [[ -f "$REPO_ROOT/workbench/toolchain/$f" ]] && cp -a "$REPO_ROOT/workbench/toolchain/$f" "$DIST_ROOT/toolchain/"
  done
  for d in mingw64 cmake sdl2; do
    src="$REPO_ROOT/workbench/toolchain/$d"
    dst="$DIST_ROOT/toolchain/$d"
    if [[ ! -d "$src" ]]; then
      echo "[assemble] WARN: missing $src"
      continue
    fi
    if [[ "$USE_HARDLINK_TOOLCHAIN" == "1" ]]; then
      echo "[assemble] hardlink-tree $d (cp -al)"
      # cp -al creates hardlinks where possible (same FS); falls back to copy
      if cp -al "$src" "$dst" 2>/dev/null; then
        :
      else
        echo "[assemble] hardlink failed for $d, full copy"
        copy_tree "$src" "$dst"
      fi
    else
      copy_tree "$src" "$dst"
    fi
  done
fi

# Launchers + README into APP_ROOT
PACK="$SCRIPT_DIR/win_launchers"
echo "[assemble] launchers from $PACK"
cp -a "$PACK/AIDOGUI_MVP_Workbench.bat" "$DIST_ROOT/"
cp -a "$PACK/Tools.bat" "$DIST_ROOT/"
cp -a "$PACK/run_cli.bat" "$DIST_ROOT/"

# CRLF all .bat for Windows cmd (LF breaks set/echo into et/cho)
find "$DIST_ROOT" -type f -name '*.bat' ! -path '*/mingw64/*' ! -path '*/cmake/share/*' -print0 | while IFS= read -r -d '' f; do
  python3 -c "from pathlib import Path; import sys; p=Path(sys.argv[1]); b=p.read_bytes().replace(b'\\r\\n',b'\\n').replace(b'\\r',b'\\n'); p.write_bytes(b.replace(b'\\n',b'\\r\\n'))" "$f"
done

cp -a "$PACK/README_WIN.txt" "$DIST_ROOT/"
# Keep a copy of INSTALL note for slim toolchain
cp -a "$PACK/INSTALL_TOOLCHAIN_WIN.txt" "$DIST_ROOT/toolchain/" 2>/dev/null || true

mkdir -p "$DIST_ROOT/runtime"
cat > "$DIST_ROOT/runtime/README.txt" << 'RT'
runtime/
--------
Optional: place Windows embeddable Python here as:

  runtime/python/python.exe
  runtime/python/pythonw.exe

Official embeddable builds do NOT include tkinter/tcl.
If present with tkinter, AIDOGUI_MVP_Workbench.bat prefers them.
Otherwise the bat uses `py -3` / `python` from the machine, or use Tools.bat
(no Python needed for Detect/Build/Sim — only PowerShell + bundled toolchain).
RT

# Marker so paths / humans know this is a packaged APP_ROOT
cat > "$DIST_ROOT/APP_ROOT.txt" << 'M'
AIDOGUI_MVP_Workbench APP_ROOT
Set AIDOGUI_APP_ROOT to this directory when launching desktop_app.
engine/ = engine sources; scripts/ + toolchain/ = workbench surface.
M

echo "[assemble] done → $DIST_ROOT"
du -sh "$DIST_ROOT" "$DIST_ROOT"/* 2>/dev/null | sed 's|^|[assemble] |' || true
