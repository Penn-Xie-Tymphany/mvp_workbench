"""Invoke workbench scripts / cmake with isolated child env."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from .env_isolate import build_child_env, toolchain_status
from .paths import AppPaths

LogFn = Callable[[str], None]


def _log(log: LogFn | None, line: str) -> None:
    if log:
        log(line)
    else:
        print(line)


def _script(paths: AppPaths, stem: str) -> Path:
    """Pick .sh on POSIX, .bat/.ps1 preference on Windows."""
    d = paths.scripts_dir
    if sys.platform == "win32":
        for ext in (".bat", ".ps1", ".cmd"):
            p = d / f"{stem}{ext}"
            if p.is_file():
                return p
    else:
        p = d / f"{stem}.sh"
        if p.is_file():
            return p
    raise FileNotFoundError(f"script not found: {stem} under {d}")


def _popen_cmd(script: Path, args: list[str]) -> list[str]:
    if script.suffix.lower() == ".ps1":
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *args,
        ]
    if script.suffix.lower() in (".bat", ".cmd"):
        return ["cmd", "/c", str(script), *args]
    return ["bash", str(script), *args]


def run_script(
    paths: AppPaths,
    stem: str,
    args: list[str] | None = None,
    *,
    log: LogFn | None = None,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> int:
    """Run a workbench script in an isolated toolchain env. Returns exit code."""
    script = _script(paths, stem)
    cmd = _popen_cmd(script, args or [])
    env = build_child_env(paths, extra=extra_env)
    _log(log, f"$ {' '.join(cmd)}")
    _log(log, f"  cwd={cwd or paths.wb_root}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd or paths.wb_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        _log(log, line.rstrip("\n"))
    return proc.wait(timeout=timeout)


def run_script_async(
    paths: AppPaths,
    stem: str,
    args: list[str] | None = None,
    *,
    log: LogFn | None = None,
    on_done: Callable[[int], None] | None = None,
    extra_env: dict[str, str] | None = None,
) -> threading.Thread:
    def _target() -> None:
        try:
            code = run_script(paths, stem, args, log=log, extra_env=extra_env)
        except Exception as exc:  # noqa: BLE001 — surface to UI log
            _log(log, f"[error] {exc}")
            code = 1
        if on_done:
            on_done(code)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return t


def detect_env(paths: AppPaths, *, log: LogFn | None = None) -> int:
    st = toolchain_status(paths)
    _log(log, "=== toolchain status (App-isolated view) ===")
    _log(log, f"app_root:    {paths.app_root}")
    _log(log, f"engine_root: {paths.engine_root}")
    _log(log, f"wb_root:     {paths.wb_root}")
    _log(log, f"toolchain:   {paths.toolchain_root}")
    _log(log, f"bundled:     {st['bundled']}  ready: {st['ready']}")
    for d in st["details"]:  # type: ignore[union-attr]
        _log(log, f"  {d}")
    try:
        return run_script(paths, "detect_env", log=log)
    except FileNotFoundError as exc:
        _log(log, f"[warn] script missing ({exc}); status-only")
        return 0 if st["ready"] else 1


def import_aidogui(
    paths: AppPaths,
    export_dir: str | Path,
    project_name: str = "",
    *,
    log: LogFn | None = None,
) -> int:
    name = (project_name or Path(export_dir).name).strip()
    if not name:
        raise ValueError("project_name required (or pass export_dir with a basename)")
    project_name = name
    return run_script(
        paths,
        "import_aidogui",
        [str(export_dir), project_name],
        log=log,
    )


def build(paths: AppPaths, *, log: LogFn | None = None) -> int:
    return run_script(paths, "build", log=log)


def run_sim(paths: AppPaths, *, log: LogFn | None = None) -> int:
    return run_script(paths, "run_sim", log=log)


def run_script_csv(
    paths: AppPaths,
    csv: str | Path | None = None,
    *,
    log: LogFn | None = None,
) -> int:
    args = [str(csv)] if csv else None
    extra = {"SDL_VIDEODRIVER": "dummy"} if sys.platform != "win32" else None
    return run_script(paths, "run_script", args, log=log, extra_env=extra)


def which_in_child(paths: AppPaths, name: str) -> str | None:
    """Resolve a binary as the child would see it (for self-check)."""
    env = build_child_env(paths)
    path = env.get("PATH", "")
    return shutil.which(name, path=path)


# ---------------------------------------------------------------------------
# Interactive sim with I/O pipe (Workbench drives CMD/SET, reads STATE)
# ---------------------------------------------------------------------------

class SimHandle:
    """A running sim_sdl.exe with piped stdin/stdout. Thread-safe send()."""

    def __init__(self, proc: subprocess.Popen, on_line=None, on_exit=None) -> None:
        self.proc = proc
        self._on_line = on_line
        self._on_exit = on_exit
        self._lock = threading.Lock()
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._exit_watch, daemon=True).start()

    def send(self, line: str) -> None:
        if self.proc.poll() is None and self.proc.stdin:
            with self._lock:
                try:
                    self.proc.stdin.write(line.strip() + "\n")
                    self.proc.stdin.flush()
                except (OSError, ValueError):
                    pass

    def stop(self) -> None:
        self.send("QUIT")
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def _read_loop(self) -> None:
        if not self.proc.stdout:
            return
        for raw in self.proc.stdout:
            line = raw.rstrip("\r\n")
            if self._on_line:
                try:
                    self._on_line(line)
                except Exception:  # noqa: BLE001 — UI callback must not kill reader
                    pass

    def _exit_watch(self) -> None:
        code = self.proc.wait()
        if self._on_exit:
            try:
                self._on_exit(code)
            except Exception:  # noqa: BLE001
                pass


def _find_sim_exe(paths: AppPaths) -> Path:
    cands = [
        paths.engine_build / "sim_sdl.exe",
        paths.engine_build / "sim_sdl",
        paths.wb_root / "bin" / "sim_sdl.exe",
        paths.wb_root / "bin" / "sim_sdl",
    ]
    for c in cands:
        if c.is_file():
            return c
    raise FileNotFoundError(
        f"sim_sdl not found — Build first (looked in {paths.engine_build} and bin/)"
    )


def start_sim_interactive(
    paths: AppPaths,
    *,
    on_line=None,
    on_exit=None,
) -> SimHandle:
    """Launch sim_sdl with piped stdin/stdout for the I/O side panel."""
    exe = _find_sim_exe(paths)
    env = build_child_env(paths)
    env["AIDOGUI_SIM_PIPE"] = "1"  # opt-in for the sim's stdin protocol
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        [str(exe)],
        cwd=str(paths.engine_build),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **kwargs,
    )
    return SimHandle(proc, on_line=on_line, on_exit=on_exit)
