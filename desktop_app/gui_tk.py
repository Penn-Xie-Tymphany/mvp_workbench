"""Tkinter GUI — preferred on Windows (stdlib). Workbench + Test Panel."""

from __future__ import annotations

import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .env_isolate import toolchain_status
from .paths import AppPaths
from . import io_contract
from . import io_gui
from . import runner
from . import signal_scan


# Soft dark-leaning palette (works with default ttk on Win/Linux)
_BG = "#1e1f26"
_PANEL = "#2a2b36"
_CARD = "#323344"
_FG = "#e8e8ef"
_MUTED = "#9aa0b4"
_ACCENT = "#5b8def"
_ACCENT_FG = "#ffffff"
_OK = "#3dba7a"
_BAD = "#e35d6a"
_WARN = "#e6b84d"
_LOG_BG = "#15161c"
_LOG_FG = "#d0d4e0"
_BORDER = "#3f4154"


class WorkbenchApp(tk.Tk):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self.paths = paths
        self.title("AIDOGUI MVP Workbench")
        self.geometry("980x720")
        self.minsize(800, 560)
        self.configure(bg=_BG)
        self._busy = False
        self._status_ready = False
        self._signal_table: signal_scan.SignalTable | None = None

        self._setup_style()
        self._build_ui()
        self.after(100, self._refresh_status)
        self.after(150, self._reload_test_panel)
        self._append(
            f"AppRoot:    {paths.app_root}\n"
            f"Engine:     {paths.engine_root}\n"
            f"Workbench:  {paths.wb_root}\n"
            f"Toolchain:  {paths.toolchain_root}\n"
            "Child processes use isolated PATH (bundled toolchain first).\n"
            "Tip: Win paths to CMake use forward slashes (auto).\n"
            "Tabs: Workbench (Import/Build/Sim) · Test Panel (scan headers / CMD script).\n"
        )

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=_BG, foreground=_FG, fieldbackground=_CARD)
        style.configure("TFrame", background=_BG)
        style.configure("Card.TFrame", background=_PANEL)
        style.configure("TLabel", background=_BG, foreground=_FG, font=("Segoe UI", 10))
        style.configure(
            "Title.TLabel",
            background=_BG,
            foreground=_FG,
            font=("Segoe UI", 16, "bold"),
        )
        style.configure(
            "Sub.TLabel",
            background=_BG,
            foreground=_MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Card.TLabel",
            background=_PANEL,
            foreground=_FG,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Muted.TLabel",
            background=_PANEL,
            foreground=_MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "TEntry",
            fieldbackground=_CARD,
            foreground=_FG,
            insertcolor=_FG,
            bordercolor=_BORDER,
            lightcolor=_ACCENT,
            darkcolor=_BORDER,
            padding=6,
        )
        style.configure(
            "Accent.TButton",
            background=_ACCENT,
            foreground=_ACCENT_FG,
            font=("Segoe UI", 10, "bold"),
            padding=(14, 8),
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#4a7ad9"), ("disabled", "#3a3c4d")],
            foreground=[("disabled", _MUTED)],
        )
        style.configure(
            "Secondary.TButton",
            background=_CARD,
            foreground=_FG,
            font=("Segoe UI", 10),
            padding=(12, 7),
            borderwidth=0,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", _BORDER), ("disabled", "#2a2b36")],
            foreground=[("disabled", _MUTED)],
        )
        style.configure("TNotebook", background=_BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=_CARD,
            foreground=_FG,
            padding=(14, 6),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", _ACCENT)],
            foreground=[("selected", _ACCENT_FG)],
        )
        style.configure("TSeparator", background=_BORDER)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(16, 12, 16, 8))
        outer.pack(fill=tk.BOTH, expand=True)

        hdr = ttk.Frame(outer)
        hdr.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(hdr, text="AIDOGUI MVP Workbench", style="Title.TLabel").pack(
            side=tk.LEFT
        )
        self.chip = tk.Label(
            hdr,
            text=" … ",
            bg=_WARN,
            fg="#1a1a1a",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=3,
        )
        self.chip.pack(side=tk.RIGHT)

        ttk.Label(
            outer,
            text="Import · Build · Simulate · Test Panel — bundled MinGW / CMake / SDL2",
            style="Sub.TLabel",
        ).pack(anchor=tk.W, pady=(0, 8))

        self.nb = ttk.Notebook(outer)
        self.nb.pack(fill=tk.BOTH, expand=True)

        self.tab_wb = ttk.Frame(self.nb)
        self.tab_io = ttk.Frame(self.nb)
        self.tab_test = ttk.Frame(self.nb)
        self.nb.add(self.tab_wb, text="Workbench")
        self.nb.add(self.tab_io, text="I/O 设计")
        self.nb.add(self.tab_test, text="Test Panel")

        self._build_workbench_tab(self.tab_wb)
        self._build_test_tab(self.tab_test)
        self._io_designer = io_gui.build_io_tab(self, self.tab_io)

        self.status = tk.StringVar(value="starting…")
        foot = tk.Label(
            self,
            textvariable=self.status,
            bg=_PANEL,
            fg=_MUTED,
            anchor=tk.W,
            font=("Segoe UI", 9),
            padx=12,
            pady=6,
        )
        foot.pack(fill=tk.X, side=tk.BOTTOM)

    def _build_workbench_tab(self, parent: ttk.Frame) -> None:
        # Project card
        proj = ttk.Frame(parent, style="Card.TFrame", padding=12)
        proj.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(proj, text="PROJECT / EXPORT", style="Muted.TLabel").pack(anchor=tk.W)

        name_row = ttk.Frame(proj, style="Card.TFrame")
        name_row.pack(fill=tk.X, pady=(6, 4))
        ttk.Label(name_row, text="工程名", style="Card.TLabel").pack(side=tk.LEFT)
        self.project_name_var = tk.StringVar(
            value=self.paths.read_active_project("")
        )
        ttk.Entry(name_row, textvariable=self.project_name_var, width=28).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Label(
            name_row,
            text="(Import 写入 ui_import/<名> + .active_project)",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT, padx=(10, 0))

        row = ttk.Frame(proj, style="Card.TFrame")
        row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(row, text="导出目录", style="Card.TLabel").pack(side=tk.LEFT)
        self.project_var = tk.StringVar(value="")
        ent = ttk.Entry(row, textvariable=self.project_var)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        ttk.Button(
            row, text="Browse…", style="Secondary.TButton", command=self._browse
        ).pack(side=tk.LEFT)

        acts = ttk.Frame(parent, style="Card.TFrame", padding=12)
        acts.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(acts, text="ACTIONS", style="Muted.TLabel").pack(anchor=tk.W)
        btnrow = ttk.Frame(acts, style="Card.TFrame")
        btnrow.pack(fill=tk.X, pady=(8, 0))

        for label, cmd in (
            ("Build", self._build),
            ("Run Sim", self._run_sim),
            ("Run Sim + I/O", self._run_sim_io),
        ):
            ttk.Button(btnrow, text=label, style="Accent.TButton", command=cmd).pack(
                side=tk.LEFT, padx=(0, 8)
            )
        for label, cmd in (
            ("Detect Env", self._detect),
            ("Import", self._import),
            ("Run Script", self._run_script),
        ):
            ttk.Button(
                btnrow, text=label, style="Secondary.TButton", command=cmd
            ).pack(side=tk.LEFT, padx=(0, 8))

        info = ttk.Frame(parent, style="Card.TFrame", padding=10)
        info.pack(fill=tk.X, pady=(0, 10))
        self.info_var = tk.StringVar(value="Toolchain: checking…")
        ttk.Label(info, textvariable=self.info_var, style="Card.TLabel").pack(
            anchor=tk.W
        )

        log_wrap = ttk.Frame(parent, style="Card.TFrame", padding=8)
        log_wrap.pack(fill=tk.BOTH, expand=True)
        ttk.Label(log_wrap, text="LOG", style="Muted.TLabel").pack(anchor=tk.W)
        self.log = scrolledtext.ScrolledText(
            log_wrap,
            height=18,
            state=tk.DISABLED,
            bg=_LOG_BG,
            fg=_LOG_FG,
            insertbackground=_FG,
            relief=tk.FLAT,
            font=("Consolas", 10),
            borderwidth=0,
            highlightthickness=0,
        )
        self.log.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

    def _build_test_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Card.TFrame", padding=10)
        top.pack(fill=tk.X, pady=(0, 8))
        self.test_info_var = tk.StringVar(value="active=… · mode=…")
        ttk.Label(top, textvariable=self.test_info_var, style="Card.TLabel").pack(
            anchor=tk.W
        )
        ttk.Label(
            top,
            text="Signals scanned from engine/app/model/app_model.h + presenter/app_cmd.h",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(4, 0))
        btnrow = ttk.Frame(top, style="Card.TFrame")
        btnrow.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            btnrow,
            text="Rescan headers",
            style="Secondary.TButton",
            command=self._reload_test_panel,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            btnrow,
            text="Write signals.json",
            style="Secondary.TButton",
            command=self._write_signals_json,
        ).pack(side=tk.LEFT)

        body = ttk.Frame(parent)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        # Commands
        cmd_card = ttk.Frame(body, style="Card.TFrame", padding=8)
        cmd_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 8))
        ttk.Label(cmd_card, text="COMMANDS (APP_CMD)", style="Muted.TLabel").pack(
            anchor=tk.W
        )
        self.cmd_hint = ttk.Label(cmd_card, text="", style="Muted.TLabel")
        self.cmd_hint.pack(anchor=tk.W, pady=(2, 4))
        self.cmd_btns = ttk.Frame(cmd_card, style="Card.TFrame")
        self.cmd_btns.pack(fill=tk.X)

        # Model fields
        field_card = ttk.Frame(body, style="Card.TFrame", padding=8)
        field_card.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 8))
        ttk.Label(field_card, text="MODEL FIELDS (read-only)", style="Muted.TLabel").pack(
            anchor=tk.W
        )
        self.fields_list = scrolledtext.ScrolledText(
            field_card,
            height=8,
            state=tk.DISABLED,
            bg=_LOG_BG,
            fg=_LOG_FG,
            font=("Consolas", 10),
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
        )
        self.fields_list.pack(fill=tk.BOTH, expand=True, pady=(6, 6))
        ttk.Button(
            field_card,
            text="生成读脚本注释",
            style="Secondary.TButton",
            command=self._append_read_comments,
        ).pack(anchor=tk.W)

        # Script box
        script_card = ttk.Frame(body, style="Card.TFrame", padding=8)
        script_card.grid(row=1, column=0, columnspan=2, sticky="nsew")
        ttk.Label(
            script_card,
            text="SCRIPT  (MVP: one CMD per line, e.g. CMD START)",
            style="Muted.TLabel",
        ).pack(anchor=tk.W)
        self.script_text = scrolledtext.ScrolledText(
            script_card,
            height=12,
            bg=_LOG_BG,
            fg=_LOG_FG,
            insertbackground=_FG,
            font=("Consolas", 10),
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
        )
        self.script_text.pack(fill=tk.BOTH, expand=True, pady=(6, 6))
        srow = ttk.Frame(script_card, style="Card.TFrame")
        srow.pack(fill=tk.X)
        ttk.Button(
            srow, text="Clear", style="Secondary.TButton", command=self._script_clear
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            srow, text="Save", style="Secondary.TButton", command=self._script_save
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            srow, text="Run Script", style="Accent.TButton", command=self._script_run
        ).pack(side=tk.LEFT)

    # ----- shared helpers -----

    def _set_chip(self, ready: bool, label: str) -> None:
        self._status_ready = ready
        self.chip.configure(
            text=f" {label} ",
            bg=_OK if ready else _BAD,
            fg="#0d1a12" if ready else "#1a0d0f",
        )

    def _append(self, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text if text.endswith("\n") else text + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _browse(self) -> None:
        d = filedialog.askdirectory(title="AIDOGUI Export UI Files folder")
        if d:
            self.project_var.set(d)

    def _refresh_status(self) -> None:
        st = toolchain_status(self.paths)
        ready = bool(st["ready"])
        kind = "bundled" if st["bundled"] else "system/fallback"
        flag = "READY" if ready else "NOT READY"
        self._set_chip(ready, flag)
        self.info_var.set(
            f"Toolchain: {flag} ({kind})  ·  root={st['toolchain_root']}"
        )
        active = self.paths.read_active_project("")
        mode = self.paths.mvp_mode_label(active)
        self.status.set(
            f"{'Busy…' if self._busy else 'Idle'}  |  active={active} ({mode})"
            f"  |  engine={self.paths.engine_root.name}  |  {flag}"
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_status()

    def _guard(self) -> bool:
        if self._busy:
            messagebox.showinfo("Busy", "A job is already running.")
            return False
        return True

    def _start(self, stem: str, args: list[str] | None = None) -> None:
        if not self._guard():
            return
        self._set_busy(True)
        self._append(f"\n--- {stem} ---")

        def log_line(line: str) -> None:
            self.after(0, lambda: self._append(line))

        def done(code: int) -> None:
            def _ui() -> None:
                self._append(f"[exit {code}]")
                self._set_busy(False)
                self._reload_test_panel()

            self.after(0, _ui)

        runner.run_script_async(
            self.paths, stem, args, log=log_line, on_done=done
        )

    def _detect(self) -> None:
        if not self._guard():
            return
        self._set_busy(True)
        self._append("\n--- detect_env ---")

        def work() -> None:
            def log_line(line: str) -> None:
                self.after(0, lambda l=line: self._append(l))

            code = runner.detect_env(self.paths, log=log_line)
            self.after(
                0,
                lambda: (
                    self._append(f"[exit {code}]"),
                    self._set_busy(False),
                ),
            )

        threading.Thread(target=work, daemon=True).start()

    def _import(self) -> None:
        src = self.project_var.get().strip()
        if not src:
            messagebox.showerror("Import", "Choose an Export UI Files folder.")
            return
        name = self.project_name_var.get().strip() or ""
        self._start("import_aidogui", [src, name])

    def _build(self) -> None:
        self._start("build")

    def _run_sim(self) -> None:
        self._start("run_sim")

    def _run_sim_io(self) -> None:
        active = self.paths.read_active_project("")
        if not active:
            messagebox.showerror("Run Sim", "没有激活工程 — 先 Import。")
            return
        try:
            contract = io_contract.load(self.paths, active)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Run Sim", f"io.json 读取失败: {exc}")
            return
        panel = io_gui.SimIOPanel(self, contract)
        try:
            handle = runner.start_sim_interactive(
                self.paths, on_line=panel.feed_line, on_exit=panel.on_exit
            )
        except Exception as exc:  # noqa: BLE001
            panel.destroy()
            messagebox.showerror("Run Sim", str(exc))
            return
        panel.attach(handle)
        self._append("[sim] interactive sim started — I/O panel open")

    def _run_script(self) -> None:
        self._start("run_script", [str(self.paths.default_csv)])

    # ----- Test Panel -----

    def _reload_test_panel(self) -> None:
        active = self.paths.read_active_project("")
        # Keep Workbench name field in sync when Import wrote .active_project
        if self.project_name_var.get().strip() != active:
            self.project_name_var.set(active)
        mode = self.paths.mvp_mode_label(active)
        self.test_info_var.set(f"active={active}  ·  mode={mode}")
        self._refresh_status()

        # Clear command buttons
        for w in self.cmd_btns.winfo_children():
            w.destroy()

        self.cmd_hint.configure(
            text="点击按钮追加一行 CMD <name> 到脚本框（只与 Model/Presenter 交互）。"
        )
        try:
            table = signal_scan.scan_from_paths(self.paths, project_hint=active)
            self._signal_table = table
        except Exception as exc:  # noqa: BLE001
            self._signal_table = None
            self.cmd_hint.configure(text=f"扫描失败: {exc}")
            self._set_fields_text(f"scan error: {exc}")
            return

        # Command buttons in a wrap-friendly grid
        cols = 4
        for i, cmd in enumerate(table.commands):
            r, c = divmod(i, cols)
            b = ttk.Button(
                self.cmd_btns,
                text=cmd.name,
                style="Secondary.TButton",
                command=lambda n=cmd.name: self._append_cmd(n),
            )
            b.grid(row=r, column=c, padx=4, pady=4, sticky="ew")
        for c in range(cols):
            self.cmd_btns.columnconfigure(c, weight=1)

        lines = [f"{f.name:16} {f.c_type:24} kind={f.kind}" for f in table.fields]
        lines.append("")
        lines.append("screens: " + ", ".join(s.name for s in table.screens))
        self._set_fields_text("\n".join(lines) if lines else "(no fields)")

        # Prefill script if empty
        if not self.script_text.get("1.0", tk.END).strip():
            self.script_text.insert(
                tk.END,
                "# MVP CMD script — one command per line\n"
                "# CMD START\n"
                "# CMD HELP\n",
            )

        # Keep I/O designer targets in sync with the header scan
        io_gui.refresh_io_tab(self)

    def _set_fields_text(self, text: str) -> None:
        self.fields_list.configure(state=tk.NORMAL)
        self.fields_list.delete("1.0", tk.END)
        self.fields_list.insert(tk.END, text)
        self.fields_list.configure(state=tk.DISABLED)

    def _append_cmd(self, name: str) -> None:
        self.script_text.insert(tk.END, f"CMD {name}\n")
        self.script_text.see(tk.END)

    def _append_read_comments(self) -> None:
        table = self._signal_table
        if not table:
            messagebox.showinfo("Model", "No model fields (scan failed or empty).")
            return
        lines = ["# READ model fields (host IPC not wired yet — comments only)"]
        for f in table.fields:
            lines.append(f"# READ {f.name}:{f.kind}  ({f.c_type})")
        self.script_text.insert(tk.END, "\n".join(lines) + "\n")
        self.script_text.see(tk.END)

    def _script_clear(self) -> None:
        self.script_text.delete("1.0", tk.END)

    def _manual_script_path(self) -> Path:
        active = self.paths.read_active_project("")
        d = self.paths.test_scripts_dir(active)
        d.mkdir(parents=True, exist_ok=True)
        return d / "manual.txt"

    def _script_save(self, *, quiet: bool = False):
        path = self._manual_script_path()
        body = self.script_text.get("1.0", tk.END)
        path.write_text(body, encoding="utf-8")
        # Also write commands.txt (host-readable dump of CMD lines)
        cmds = [
            ln.strip()
            for ln in body.splitlines()
            if ln.strip().upper().startswith("CMD ")
        ]
        (path.parent / "commands.txt").write_text(
            "\n".join(cmds) + ("\n" if cmds else ""), encoding="utf-8"
        )
        # Optional signals.json next to project
        if self._signal_table:
            signal_scan.write_signals_json(
                self._signal_table, path.parent.parent / "signals.json"
            )
        if not quiet:
            self._append(f"[test] saved {path}")
            messagebox.showinfo("Save", f"Saved:\n{path}")
        return path

    def _write_signals_json(self) -> None:
        active = self.paths.read_active_project("")
        try:
            table = signal_scan.scan_from_paths(self.paths, project_hint=active)
            dest_proj = self.paths.project_slot(active) / "signals.json"
            dest_mvp = self.paths.mvp_dir(active) / "model_signals.generated.json"
            signal_scan.write_signals_json(table, dest_proj)
            signal_scan.write_signals_json(table, dest_mvp)
            self._append(f"[test] wrote {dest_proj}\n[test] wrote {dest_mvp}")
            messagebox.showinfo("signals.json", f"Wrote:\n{dest_proj}\n{dest_mvp}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("signals.json", str(exc))

    def _script_run(self) -> None:
        path = self._script_save(quiet=True)
        body = path.read_text(encoding="utf-8", errors="replace")
        self._append("\n--- Test Panel Run Script ---")
        for ln in body.splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            self._append(f"  will exec: {s}")
        self._start("run_script", [str(path)])



def run_gui(paths: AppPaths) -> int:
    app = WorkbenchApp(paths)
    app.mainloop()
    return 0
