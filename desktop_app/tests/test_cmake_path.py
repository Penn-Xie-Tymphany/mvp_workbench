"""Regression: Win paths handed to CMake must use forward slashes.

Root cause of link failure:
  ld: cannot find W:AIDOGUI...toolchainsdl2/lib/libSDL2.dll.a
Backslashes were eaten by MinGW make as escape sequences.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `python3 tests/test_cmake_path.py` from repo or package
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop_app.env_isolate import cmake_path  # noqa: E402


def test_win_drive_path() -> None:
    raw = r"W:\AIDOGUI_MVP_Workbench_full\AIDOGUI_MVP_Workbench\toolchain\sdl2"
    got = cmake_path(raw)
    assert "\\" not in got, got
    assert got == "W:/AIDOGUI_MVP_Workbench_full/AIDOGUI_MVP_Workbench/toolchain/sdl2"
    lib = cmake_path(raw + r"\lib\libSDL2.dll.a")
    assert lib == (
        "W:/AIDOGUI_MVP_Workbench_full/AIDOGUI_MVP_Workbench/toolchain/sdl2/lib/libSDL2.dll.a"
    )
    # Prove the broken form is NOT what we emit
    assert "W:AIDOGUI" not in lib


def test_unix_noop() -> None:
    p = "/workspace/tools/sdl2"
    assert cmake_path(p) == p


def test_pathlib() -> None:
    # Path on Posix won't invent backslashes; still must not introduce them
    assert "\\" not in cmake_path(Path("/tmp/foo/bar"))


if __name__ == "__main__":
    test_win_drive_path()
    test_unix_noop()
    test_pathlib()
    print("OK: cmake_path regression passed")
