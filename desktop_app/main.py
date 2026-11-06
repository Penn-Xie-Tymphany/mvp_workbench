#!/usr/bin/env python3
"""AIDOGUI MVP Workbench — desktop App entry.

Usage
-----
  # from aidogui_mvp/:
  python -m desktop_app
  python -m desktop_app --self-check
  python desktop_app/main.py --self-check

  # with venv (PySide6 on Linux):
  desktop_app/.venv/bin/python -m desktop_app
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_pkg_path() -> None:
    """Allow ``python desktop_app/main.py`` without install."""
    here = Path(__file__).resolve().parent
    parent = here.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))


def main(argv: list[str] | None = None) -> int:
    _ensure_pkg_path()
    # Prefer package-relative imports when run as module; absolute when script.
    try:
        from desktop_app.paths import resolve_paths
        from desktop_app import self_check
    except ImportError:
        from paths import resolve_paths  # type: ignore
        import self_check  # type: ignore

    parser = argparse.ArgumentParser(description="AIDOGUI MVP Workbench desktop App")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Headless: resolve paths, isolate env, run detect_env (no GUI)",
    )
    parser.add_argument(
        "--detect",
        action="store_true",
        help="Headless detect_env only",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Headless build (can take a while)",
    )
    parser.add_argument(
        "--gui",
        choices=("auto", "tk", "qt", "none"),
        default="auto",
        help="GUI backend (default auto: tk → qt → none)",
    )
    args = parser.parse_args(argv)

    paths = resolve_paths()

    if args.self_check:
        return self_check.run(paths)

    if args.detect or args.build:
        try:
            from desktop_app import runner
        except ImportError:
            import runner  # type: ignore
        code = 0
        if args.detect:
            code = runner.detect_env(paths) or code
        if args.build:
            code = runner.build(paths) or code
        return code

    gui = args.gui
    if gui == "auto":
        try:
            import PySide6  # noqa: F401

            gui = "qt"
        except ImportError:
            try:
                import tkinter  # noqa: F401

                gui = "tk"
            except ImportError:
                gui = "none"

    if gui == "tk":
        try:
            from desktop_app.gui_tk import run_gui
        except ImportError:
            from gui_tk import run_gui  # type: ignore
        return run_gui(paths)

    if gui == "qt":
        try:
            from desktop_app.gui_qt import run_gui
        except ImportError:
            from gui_qt import run_gui  # type: ignore
        return run_gui(paths)

    print(
        "No GUI backend available (need tkinter or PySide6).\n"
        "Run headless:  python -m desktop_app --self-check\n"
        "Or install:    sudo apt install python3-tk   OR   pip install PySide6\n"
        f"Resolved paths:\n"
        f"  app_root={paths.app_root}\n"
        f"  engine={paths.engine_root}\n"
        f"  workbench={paths.wb_root}\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
