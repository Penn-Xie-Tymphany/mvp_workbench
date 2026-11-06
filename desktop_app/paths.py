"""Resolve AppRoot / engine / workbench / toolchain layout.

Two supported layouts
--------------------
Development (this repo)::

    aidogui_mvp/                 <- ENGINE_ROOT
      desktop_app/               <- APP_ROOT (this package)
      workbench/                 <- WB_ROOT (scripts, toolchain, projects)
        scripts/
        toolchain/
        projects/

Packaged Windows (PyInstaller one-folder)::

    AIDOGUI_MVP_Workbench/       <- APP_ROOT (= WB_ROOT)
      AIDOGUI_MVP_Workbench.exe
      engine/                    <- ENGINE_ROOT (copied aidogui_mvp engine tree)
      scripts/
      toolchain/
      projects/
      tests/

Override with env:
  AIDOGUI_APP_ROOT, AIDOGUI_ENGINE_ROOT, AIDOGUI_WB_ROOT
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _env_path(name: str) -> Path | None:
    v = os.environ.get(name, "").strip()
    return Path(v).resolve() if v else None


def _looks_like_engine(p: Path) -> bool:
    return (p / "CMakeLists.txt").is_file() and (p / "app").is_dir()


def _looks_like_workbench(p: Path) -> bool:
    return (p / "scripts").is_dir() and (
        (p / "toolchain").is_dir() or (p / "scripts" / "build.sh").is_file()
    )


@dataclass(frozen=True)
class AppPaths:
    app_root: Path
    engine_root: Path
    wb_root: Path

    @property
    def toolchain_root(self) -> Path:
        return self.wb_root / "toolchain"

    @property
    def scripts_dir(self) -> Path:
        return self.wb_root / "scripts"

    @property
    def projects_dir(self) -> Path:
        return self.wb_root / "projects"

    @property
    def tests_dir(self) -> Path:
        return self.wb_root / "tests"

    @property
    def default_csv(self) -> Path:
        return self.tests_dir / "transitions.csv"

    @property
    def engine_build(self) -> Path:
        return self.engine_root / "build"

    @property
    def lv_conf(self) -> Path:
        return self.engine_root / "lv_conf.h"

    @property
    def ui_import_dir(self) -> Path:
        return self.engine_root / "ui_import"


    @property
    def active_project_file(self) -> Path:
        return self.ui_import_dir / ".active_project"

    def read_active_project(self, default: str = "") -> str:
        p = self.active_project_file
        if not p.is_file():
            return default
        name = p.read_text(encoding="utf-8", errors="replace").strip()
        return name or default

    def write_active_project(self, name: str) -> None:
        self.ui_import_dir.mkdir(parents=True, exist_ok=True)
        self.active_project_file.write_text(name.strip() + "\n", encoding="ascii")



    def ui_project_dir(self, name: str | None = None) -> Path:
        return self.ui_import_dir / (name or self.read_active_project())

    def mvp_dir(self, name: str | None = None) -> Path:
        return self.ui_project_dir(name) / "mvp"

    @property
    def model_header(self) -> Path:
        # Prefer per-project generated header
        mvp = self.mvp_dir() / "app_model.h"
        if mvp.is_file():
            return mvp
        return self.engine_root / "app" / "runtime" / "app_model.h"  # unused fallback

    @property
    def cmd_header(self) -> Path:
        mvp = self.mvp_dir() / "app_cmd.h"
        if mvp.is_file():
            return mvp
        return self.engine_root / "app" / "runtime" / "app_cmd.h"

    def project_slot(self, name: str | None = None) -> Path:
        return self.projects_dir / (name or self.read_active_project() or "project")

    def test_scripts_dir(self, name: str | None = None) -> Path:
        return self.project_slot(name) / "test_scripts"

    def mvp_mode_label(self, name: str | None = None) -> str:
        proj = name or self.read_active_project() or "?"
        return f"MVP ({proj})"


def resolve_app_root() -> Path:
    override = _env_path("AIDOGUI_APP_ROOT")
    if override:
        return override
    # Frozen (PyInstaller)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Package dir = desktop_app/
    return Path(__file__).resolve().parent


def resolve_paths(app_root: Path | None = None) -> AppPaths:
    app = app_root or resolve_app_root()

    eng = _env_path("AIDOGUI_ENGINE_ROOT")
    wb = _env_path("AIDOGUI_WB_ROOT")

    if eng is None:
        # Packaged: APP_ROOT/engine (APP_ROOT = exe dir or env)
        cand = app / "engine"
        if _looks_like_engine(cand):
            eng = cand
        # Packaged source: desktop_app/ next to engine/
        elif _looks_like_engine(app.parent / "engine"):
            eng = app.parent / "engine"
        # Dev: parent of desktop_app is aidogui_mvp
        elif _looks_like_engine(app.parent):
            eng = app.parent
        else:
            eng = app.parent  # best-effort

    if wb is None:
        # Packaged: scripts next to exe → APP_ROOT is workbench
        if _looks_like_workbench(app):
            wb = app
        # Packaged source: desktop_app/ sibling of scripts/
        elif _looks_like_workbench(app.parent):
            wb = app.parent
        # Dev: sibling workbench/
        elif _looks_like_workbench(app.parent / "workbench"):
            wb = app.parent / "workbench"
        # Nested: APP_ROOT/workbench
        elif _looks_like_workbench(app / "workbench"):
            wb = app / "workbench"
        else:
            wb = app.parent / "workbench"

    return AppPaths(app_root=app.resolve(), engine_root=eng.resolve(), wb_root=wb.resolve())
