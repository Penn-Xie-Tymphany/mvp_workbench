"""Build a subprocess environment with App-bundled toolchain only.

Never mutates the user/global PATH of the parent process. Callers pass the
returned dict as ``env=`` to ``subprocess.Popen`` / ``run``.

On Windows the App packages MinGW + CMake + SDL2 under ``toolchain/``.
On Linux (dev box) the same resolver prefers ``toolchain/`` if present,
then falls back to ``/workspace/tools/{cmake,sdl2}`` and system gcc — still
only for the child env, not by writing the user's shell profile.

WIN PATH NOTE
-------------
Paths passed to CMake / MinGW make / ld **must use forward slashes**.
Backslashes are treated as escapes, e.g.
``W:\\foo\\bar\\lib\\libSDL2.dll.a`` → ``W:foofooliblibSDL2.dll.a``.
Use :func:`cmake_path` for ``SDL2_DIR`` / ``CMAKE_PREFIX_PATH`` / any
``-D…=path`` value. Native ``PATH`` / ``LIBRARY_PATH`` may keep ``\\``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping

from .paths import AppPaths


def cmake_path(p: str | Path) -> str:
    """Convert a filesystem path to cmake-style (forward slashes).

    Safe on Unix (no-op aside from normalizing). Required on Windows before
    handing paths to CMake, MinGW Makefiles, or gcc/ld linker args.
    """
    s = os.fspath(p)
    return s.replace("\\", "/")


def _prepend_path(env: dict[str, str], *dirs: Path) -> None:
    sep = ";" if sys.platform == "win32" else ":"
    existing = env.get("PATH", os.environ.get("PATH", ""))
    parts = [str(d) for d in dirs if d.is_dir()]
    if not parts:
        return
    env["PATH"] = sep.join(parts + ([existing] if existing else []))


def _prepend_lib_path(env: dict[str, str], *dirs: Path) -> None:
    sep = ";" if sys.platform == "win32" else ":"
    parts = [str(d) for d in dirs if d.is_dir()]
    if not parts:
        return
    existing = env.get("LIBRARY_PATH", "")
    env["LIBRARY_PATH"] = sep.join(parts + ([existing] if existing else []))


def toolchain_status(paths: AppPaths) -> dict[str, object]:
    """Return readiness flags for status bar / Detect Env."""
    tb = paths.toolchain_root
    win = sys.platform == "win32"
    status: dict[str, object] = {
        "toolchain_root": str(tb),
        "platform": sys.platform,
        "bundled": False,
        "ready": False,
        "details": [],
    }
    details: list[str] = []

    if win:
        gcc = tb / "mingw64" / "bin" / "gcc.exe"
        gpp = tb / "mingw64" / "bin" / "g++.exe"
        cmake = tb / "cmake" / "bin" / "cmake.exe"
        sdl_h = tb / "sdl2" / "include" / "SDL2" / "SDL.h"
        sdl_dll = tb / "sdl2" / "bin" / "SDL2.dll"
        sdl_lib = tb / "sdl2" / "lib" / "libSDL2.dll.a"
        checks = [
            ("gcc", gcc),
            ("g++", gpp),
            ("cmake", cmake),
            ("SDL2.h", sdl_h),
            ("SDL2.dll", sdl_dll),
            ("libSDL2.dll.a", sdl_lib),
        ]
        ok_all = True
        for name, p in checks:
            hit = p.is_file()
            details.append(f"{'OK' if hit else 'MISSING'}  {name}: {p}")
            ok_all = ok_all and hit
        status["bundled"] = ok_all
        status["ready"] = ok_all
    else:
        # Linux: bundled optional; system /workspace/tools OK for ready
        cmake_candidates = [
            tb / "cmake" / "bin" / "cmake",
            Path("/workspace/tools/cmake/bin/cmake"),
        ]
        sdl_candidates = [
            tb / "sdl2" / "include" / "SDL2" / "SDL.h",
            Path("/workspace/tools/sdl2/include/SDL2/SDL.h"),
            Path("/usr/include/SDL2/SDL.h"),
            Path("/usr/local/include/SDL2/SDL.h"),
        ]
        import shutil

        gcc = shutil.which("gcc")
        gpp = shutil.which("g++")
        cmake_hit = next((p for p in cmake_candidates if p.is_file()), None)
        if cmake_hit is None:
            w = shutil.which("cmake")
            cmake_hit = Path(w) if w else None
        sdl_hit = next((p for p in sdl_candidates if p.is_file()), None)

        details.append(f"{'OK' if gcc else 'MISSING'}  gcc: {gcc or '(not in PATH)'}")
        details.append(f"{'OK' if gpp else 'MISSING'}  g++: {gpp or '(not in PATH)'}")
        details.append(f"{'OK' if cmake_hit else 'MISSING'}  cmake: {cmake_hit or ''}")
        details.append(f"{'OK' if sdl_hit else 'MISSING'}  SDL2: {sdl_hit or ''}")
        status["bundled"] = (tb / "cmake").is_dir() or (tb / "mingw64").is_dir()
        status["ready"] = bool(gcc and gpp and cmake_hit and sdl_hit)

    status["details"] = details
    return status


def build_child_env(
    paths: AppPaths,
    base: Mapping[str, str] | None = None,
    *,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return env for compile/sim subprocesses — isolated toolchain inject.

    Parent ``os.environ`` is copied; PATH is rewritten with toolchain bins
    **prepended**. User global PATH is never written back.
    """
    env = dict(base if base is not None else os.environ)
    tb = paths.toolchain_root

    env["AIDOGUI_APP_ROOT"] = str(paths.app_root)
    env["AIDOGUI_WB_ROOT"] = str(paths.wb_root)
    env["AIDOGUI_ENGINE_ROOT"] = str(paths.engine_root)
    env["LV_CONF_PATH"] = str(paths.lv_conf)

    if sys.platform == "win32":
        mingw = tb / "mingw64"
        cmake_bin = tb / "cmake" / "bin"
        sdl2 = tb / "sdl2"
        sdl2_bin = sdl2 / "bin"
        sdl2_lib = sdl2 / "lib"
        _prepend_path(env, mingw / "bin", cmake_bin, sdl2_bin)

        # Match workbench/toolchain/env.bat sysroot hints
        crt = mingw / "x86_64-w64-mingw32" / "lib" / "crt2.o"
        lib_dirs: list[Path] = []
        if crt.is_file():
            lib_dirs.extend(
                [
                    mingw / "x86_64-w64-mingw32" / "lib",
                    mingw / "lib",
                ]
            )
            inc = (
                str(mingw / "x86_64-w64-mingw32" / "include")
                + ";"
                + str(mingw / "include")
            )
            env["C_INCLUDE_PATH"] = inc
            env["CPLUS_INCLUDE_PATH"] = inc
        if sdl2_lib.is_dir():
            lib_dirs.append(sdl2_lib)
        if lib_dirs:
            _prepend_lib_path(env, *lib_dirs)

        if sdl2.is_dir():
            # Forward slashes for CMake / MinGW make / ld
            env["SDL2_DIR"] = cmake_path(sdl2)
            env["CMAKE_PREFIX_PATH"] = cmake_path(sdl2)
            dll_a = sdl2_lib / "libSDL2.dll.a"
            if dll_a.is_file():
                env["SDL2_LIBRARY"] = cmake_path(dll_a)
        if (mingw / "bin" / "gcc.exe").is_file():
            env["CMAKE_GENERATOR"] = "MinGW Makefiles"
    else:
        # Linux: prefer staged tools, then any toolchain cmake
        pref: list[Path] = []
        for d in (
            tb / "cmake" / "bin",
            Path("/workspace/tools/cmake/bin"),
            tb / "mingw64" / "bin",  # unusual on Linux but harmless
            tb / "sdl2" / "bin",
            Path("/workspace/tools/sdl2/bin"),
        ):
            if d.is_dir():
                pref.append(d)
        _prepend_path(env, *pref)

        sdl2 = tb / "sdl2"
        if (sdl2 / "include" / "SDL2" / "SDL.h").is_file():
            env["SDL2_DIR"] = cmake_path(sdl2)
            env["CMAKE_PREFIX_PATH"] = cmake_path(sdl2)
        elif Path("/workspace/tools/sdl2/include/SDL2/SDL.h").is_file():
            env["SDL2_DIR"] = "/workspace/tools/sdl2"
            # Keep CMAKE_PREFIX_PATH if already useful
            env.setdefault("CMAKE_PREFIX_PATH", "/workspace/tools/sdl2")

    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env
