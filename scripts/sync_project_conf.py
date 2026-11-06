#!/usr/bin/env python3
"""Sync engine/lv_conf.h LV_COLOR_DEPTH to the ACTIVE UI project.

Called by scripts/build.ps1 before cmake configure, so switching projects
via .active_project never leaves a color-depth mismatch (AIDOGUI exports
put an #error guard in ui.c).
"""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here))
import gen_mvp  # noqa: E402


def main() -> int:
    engine = here.parent / "engine"
    active_file = engine / "ui_import" / ".active_project"
    if not active_file.is_file():
        return 0
    name = active_file.read_text(encoding="utf-8", errors="replace").strip()
    if not name:
        return 0
    proj = engine / "ui_import" / name
    if not proj.is_dir():
        print(f"[sync] WARN: active project '{name}' not found under ui_import/")
        return 0
    print(f"[sync] active project: {name}")
    gen_mvp.sync_lv_conf_depth(proj)
    gen_mvp.ensure_lvgl_version(proj)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())