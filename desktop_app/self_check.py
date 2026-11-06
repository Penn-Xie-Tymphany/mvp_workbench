"""Headless self-check for the AIDOGUI MVP Workbench desktop App.

Usage (see main.py / run_cli.bat)::

    python -m desktop_app --self-check

Checks, in order:
  1. Layout: app_root / engine_root / workbench resolve to real dirs.
  2. Engine: CMakeLists.txt, lv_conf.h, app/ present.
  3. Scripts: detect_env / build / run_sim / run_script present (.bat on Win).
  4. Toolchain: bundled gcc / cmake / SDL2 visible in the *child* env only
     (the App never writes the user PATH).
  5. GUI backend: tkinter (or PySide6) importable for the real launch.
  6. Finally runs the workbench detect_env script for a live verdict.

Exit code 0 == READY (green light for Build / Run Sim).
"""

from __future__ import annotations

import sys
from pathlib import Path

from .env_isolate import toolchain_status
from .paths import AppPaths

OK = "OK  "
MISS = "MISS"


def _line(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", flush=True)


def run(paths: AppPaths) -> int:
    print("=== AIDOGUI MVP Workbench self-check ===", flush=True)

    # 1) Layout ------------------------------------------------------------
    _line("info", f"app_root:    {paths.app_root}")
    _line("info", f"engine_root: {paths.engine_root}")
    _line("info", f"wb_root:     {paths.wb_root}")
    _line("info", f"toolchain:   {paths.toolchain_root}")
    _line("info", f"python:      {sys.version.split()[0]} ({sys.executable})")

    fail = False

    for label, d in (
        ("app_root", paths.app_root),
        ("engine_root", paths.engine_root),
        ("wb_root", paths.wb_root),
    ):
        if d.is_dir():
            _line(OK, f"{label} exists")
        else:
            _line(MISS, f"{label} not a directory: {d}")
            fail = True

    # 2) Engine ------------------------------------------------------------
    for p in (paths.engine_root / "CMakeLists.txt", paths.lv_conf, paths.engine_root / "app"):
        if p.exists():
            _line(OK, f"engine: {p.name}")
        else:
            _line(MISS, f"engine: {p}")
            fail = True

    # 3) Scripts -----------------------------------------------------------
    exts = (".bat", ".cmd", ".ps1") if sys.platform == "win32" else (".sh",)
    for stem in ("detect_env", "build", "run_sim", "run_script"):
        hit = next(
            (paths.scripts_dir / f"{stem}{e}" for e in exts if (paths.scripts_dir / f"{stem}{e}").is_file()),
            None,
        )
        if hit:
            _line(OK, f"script: {hit.name}")
        else:
            _line(MISS, f"script: {stem}{exts[0]} under {paths.scripts_dir}")
            fail = True

    # 4) Toolchain (isolated child view) -----------------------------------
    st = toolchain_status(paths)
    _line("info", f"toolchain bundled={st['bundled']} ready={st['ready']}")
    for d in st["details"]:  # type: ignore[union-attr]
        print(f"       {d}", flush=True)
    if not st["ready"]:
        fail = True

    # 5) GUI backend -------------------------------------------------------
    try:
        import tkinter  # noqa: F401

        _line(OK, "gui backend: tkinter")
    except ImportError:
        try:
            import PySide6  # noqa: F401

            _line(OK, "gui backend: PySide6")
        except ImportError:
            _line(MISS, "gui backend: neither tkinter nor PySide6 (Tools.bat still works)")
            fail = True

    # 6) Live detect_env ---------------------------------------------------
    print("--- running scripts/detect_env ---", flush=True)
    try:
        from . import runner

        code = runner.detect_env(paths)
    except Exception as exc:  # noqa: BLE001 — self-check must never crash
        _line("FAIL", f"detect_env raised: {exc}")
        return 1

    print("=== self-check " + ("READY" if (code == 0 and not fail) else "FAILED") + " ===", flush=True)
    return 0 if (code == 0 and not fail) else 1