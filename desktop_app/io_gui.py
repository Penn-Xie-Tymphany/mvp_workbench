"""EEZ-Studio-style I/O flow editor + simulation I/O side panel (Tk).

Canvas model (view over projects/<Project>/io.json v2):

  数据流:  [输入外设] ──▶ [Model 变量] ──▶ [输出: 显示值 / 屏幕控件]
  事件流:  [页面A] ──CMD──▶ [页面B]   (pages are nodes; flows are labeled wires)

Interactions:
  · palette buttons add nodes
  · click node → select → inspector (inline edit)
  · drag from a green out-port to a yellow in-port → wire (= binding),
    with live rubber-band preview
  · drag empty canvas → pan; drag node body → move (saved to io.json)
  · click a wire → select → 删除连线 (user-owned bindings only)
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from . import io_contract, runner, signal_scan
from .paths import AppPaths

# ---- canvas geometry / colors --------------------------------------------
NODE_W, NODE_H = 172, 56
PAGE_W, PAGE_H = 150, 42
COL_X = {"input": 60, "field": 330, "output": 620}
LANE_TOP = 30
LANE_GAP = 14
EVENT_GAP = 120
PAGE_COLS = 4

_BG = "#14151a"
_GRID = "#22242e"
_HEAD = {
    "input": "#2f57a8",
    "field": "#1e6e46",
    "output": "#8a6420",
    "page": "#5a3d82",
}
_HEAD_LABEL = {"input": "INPUT 外设", "field": "VAR 变量",
               "output": "OUTPUT 输出", "page": "PAGE 页面"}
_BODY = "#26272f"
_EDGE = "#8a90a8"
_PORT_OUT = "#3dba7a"
_PORT_IN = "#e6b84d"
_WIRE_DATA = "#5b8def"
_WIRE_EVENT = "#c98a3d"
_PENDING = "#e6b84d"
_FG = "#e8e8ef"
_MUTED = "#9aa0b4"

_INPUT_KINDS_CN = {
    "button": "＋按键", "switch": "＋开关", "knob": "＋旋钮",
    "slider": "＋滑条", "sensor": "＋传感器",
}


def _bind_text(entry: dict) -> str:
    b = entry.get("bind") or {}
    t = b.get("type", "?")
    if t == "widget":
        return f"控件 {b.get('screen', '')}.{b.get('widget', '')} ← {b.get('field', '')}"
    if t == "cmd":
        return f"CMD {b.get('name', '')}"
    if t == "field":
        return f"→ {b.get('name', '')}"
    return "未绑定 (拖端口连线)"


def _round_rect(x1, y1, x2, y2, r=9, steps=6):
    """Points for a smooth rounded rectangle polygon."""
    pts = []
    import math
    for (cx, cy, a0, a1) in (
        (x2 - r, y1 + r, -90, 0), (x2 - r, y2 - r, 0, 90),
        (x1 + r, y2 - r, 90, 180), (x1 + r, y1 + r, 180, 270),
    ):
        for i in range(steps + 1):
            a = math.radians(a0 + (a1 - a0) * i / steps)
            pts.extend((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _dist_to_seg(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    cx, cy = x1 + t * dx, y1 + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


class FlowCanvas(tk.Canvas):
    """Node-wire canvas, EEZ-Studio flavored."""

    def __init__(self, master, designer: "IODesigner") -> None:
        super().__init__(master, bg=_BG, highlightthickness=0)
        self.designer = designer
        self.nodes: dict[str, dict] = {}
        self.wires: list[dict] = []
        self.pending: tuple[str, str] | None = None
        self.sel_node: str | None = None
        self.sel_wire: int | None = None
        self._drag: tuple[str, int, int] | None = None
        self._pan = False
        self._mouse = (0, 0)

        xbar = ttk.Scrollbar(master, orient=tk.HORIZONTAL, command=self.xview)
        ybar = ttk.Scrollbar(master, orient=tk.VERTICAL, command=self.yview)
        self.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)

        self.bind("<Button-1>", self._on_down)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_up)
        self.bind("<Delete>", self._on_delete)

    # ================= graph build =================
    def rebuild(self) -> None:
        d = self.designer
        data = d.data
        layout = data.get("layout", {})
        self.nodes.clear()
        self.wires.clear()
        self.pending = None

        def place(nid: str, kind: str, title: str, sub: str, x: float, y: float,
                  w=NODE_W, h=NODE_H) -> float:
            px, py = layout.get(nid, (x, y))
            self.nodes[nid] = {"x": px, "y": py, "kind": kind, "title": title,
                               "sub": sub, "w": w, "h": h}
            return py + h

        # --- data zone ---
        yb = LANE_TOP
        inputs = data.get("inputs", [])
        for inp in inputs:
            nid = f"in:{inp.get('id', '')}"
            yb = max(yb, place(nid, "input", str(inp.get("label") or inp.get("id", "")),
                               f"{inp.get('kind', '')} · {_bind_text(inp)}",
                               COL_X["input"], yb)) + LANE_GAP

        yf = LANE_TOP
        fields = io_contract.field_binds(data)
        for f in fields:
            nid = f"fld:{f['name']}"
            yf = max(yf, place(nid, "field", f["name"],
                               f"{f['ctype']} · 初值 {f.get('init', 0)}",
                               COL_X["field"], yf)) + LANE_GAP

        yo = LANE_TOP
        for out in data.get("outputs", []):
            nid = f"out:{out.get('id', '')}"
            yo = max(yo, place(nid, "output", str(out.get("label") or out.get("id", "")),
                               f"{out.get('kind', '')} · {_bind_text(out)}",
                               COL_X["output"], yo)) + LANE_GAP

        # --- event zone: page nodes in an auto grid (draggable) ---
        ev_y0 = max(yb, yf, yo) + EVENT_GAP
        screens = [s.name for s in getattr(d.app, "_signal_table", None).screens] \
            if getattr(d.app, "_signal_table", None) else []
        pw, ph, gx, gy = PAGE_W, PAGE_H, 46, 32
        for i, s in enumerate(screens):
            nid = f"page:{s}"
            if nid not in layout:
                r, c = divmod(i, PAGE_COLS)
                layout[nid] = [COL_X["input"] + c * (pw + gx), ev_y0 + r * (ph + gy)]
        for s in screens:
            place(f"page:{s}", "page", s, "", 0, 0, w=pw, h=ph)

        # --- wires ---
        fld_node = {n.split(":", 1)[1]: n for n, nd in self.nodes.items()
                    if nd["kind"] == "field"}

        def fld(name: str) -> str | None:
            return fld_node.get(io_contract.normalize_name(str(name)))

        for inp in inputs:
            b = inp.get("bind") or {}
            if b.get("type") == "field":
                t = fld(b.get("name", ""))
                if t:
                    self.wires.append({"a": f"in:{inp.get('id')}", "ap": "out",
                                       "b": t, "bp": "in", "kind": "input_bind",
                                       "ref": inp, "label": ""})
        for out in data.get("outputs", []):
            b = out.get("bind") or {}
            src = b.get("name") if b.get("type") == "field" else b.get("field")
            if b.get("type") in ("field", "widget") and src:
                t = fld(src)
                if t:
                    self.wires.append({"a": t, "ap": "out", "b": f"out:{out.get('id')}",
                                       "bp": "in", "kind": "output_bind",
                                       "ref": out, "label": ""})

        screens_set = set(screens)
        for i, fl in enumerate(data.get("flows", [])):
            a = f"page:{str(fl.get('from', '')).upper()}"
            b = f"page:{str(fl.get('to', '')).upper()}"
            if fl.get("from") and fl.get("to") and a in self.nodes and b in self.nodes:
                self.wires.append({"a": a, "ap": "out", "b": b, "bp": "in",
                                   "kind": "flow", "ref": fl, "idx": i,
                                   "label": str(fl.get("on", ""))})

        # button → page dashed hint wires (same CMD)
        for inp in inputs:
            b = inp.get("bind") or {}
            if b.get("type") == "cmd":
                for w in self.wires:
                    if w["kind"] == "flow" and w["label"].upper() == str(b.get("name", "")).upper():
                        self.wires.append({"a": f"in:{inp.get('id')}", "ap": "out",
                                           "b": w["b"], "bp": "in", "kind": "hint",
                                           "ref": None, "label": ""})
                        break

        self._draw()

    # ================= drawing =================
    def _port_xy(self, nid: str, port: str) -> tuple[float, float]:
        n = self.nodes[nid]
        w = n.get("w", NODE_W)
        h = n.get("h", NODE_H)
        return (n["x"] + w, n["y"] + h / 2) if port == "out" else (n["x"], n["y"] + h / 2)

    def _has_port(self, nid: str, port: str) -> bool:
        k = self.nodes[nid]["kind"]
        return not (k == "input" and port == "in") and \
               not (k == "output" and port == "out") and k != "flow"

    def _draw(self) -> None:
        self.delete("all")
        # dotted grid
        x0, y0 = self.canvasx(0), self.canvasy(0)
        x1 = self.canvasx(self.winfo_width())
        y1 = self.canvasy(self.winfo_height())
        step = 26
        gx = (int(x0) // step) * step
        gy = (int(y0) // step) * step
        xx = gx
        while xx <= x1:
            yy = gy
            while yy <= y1:
                self.create_oval(xx, yy, xx + 1.4, yy + 1.4, fill=_GRID, outline="")
                yy += step
            xx += step

        # zone captions
        self.create_text(COL_X["input"] + NODE_W / 2, 10, text="输入 外设",
                         fill=_MUTED, font=("Segoe UI", 9, "bold"))
        self.create_text(COL_X["field"] + NODE_W / 2, 10, text="变量 Model",
                         fill=_MUTED, font=("Segoe UI", 9, "bold"))
        self.create_text(COL_X["output"] + NODE_W / 2, 10, text="输出",
                         fill=_MUTED, font=("Segoe UI", 9, "bold"))
        ev_y = min([n["y"] for n in self.nodes.values() if n["kind"] == "page"] or [400]) - 26
        self.create_text(80, ev_y, text="事件流 — 页面 ▶ 页面（线上是 CMD）",
                         fill=_MUTED, font=("Segoe UI", 9, "bold"), anchor=tk.W)

        # wires
        for wi, w in enumerate(self.wires):
            x1, y1 = self._port_xy(w["a"], w["ap"])
            x2, y2 = self._port_xy(w["b"], w["bp"])
            mx = (x1 + x2) / 2
            pts = (x1, y1, mx, y1, mx, y2, x2, y2)
            color = _WIRE_EVENT if w["kind"] == "flow" else (
                "#5a5f75" if w["kind"] == "hint" else _WIRE_DATA)
            kw = dict(smooth=True, width=2, fill=color)
            if w["kind"] == "hint":
                kw["dash"] = (4, 4)
            if self.sel_wire == wi:
                kw["width"] = 4
            self.create_line(*pts, **kw)
            # arrowhead (all wires go left→right)
            ax1, ay1 = x2 - 8, y2 - 5
            ax2, ay2 = x2 - 8, y2 + 5
            self.create_polygon(x2, y2, ax1, ay1, ax2, ay2, fill=color, outline="")
            if w["label"]:
                self.create_text(mx, (y1 + y2) / 2 - 9, text=w["label"],
                                 fill=_FG, font=("Consolas", 8, "bold"))

        # pending rubber band
        if self.pending:
            x1, y1 = self._port_xy(self.pending[0], self.pending[1])
            self.create_line(x1, y1, self._mouse[0], self._mouse[1],
                             fill=_PENDING, width=2, dash=(5, 4))

        # nodes
        for nid, n in self.nodes.items():
            w = n.get("w", NODE_W)
            h = n.get("h", NODE_H)
            x, y = n["x"], n["y"]
            sel = self.sel_node == nid
            outline = _PENDING if sel else _EDGE
            self.create_polygon(_round_rect(x, y, x + w, y + h), fill=_BODY,
                                outline=outline, width=2 if sel else 1,
                                tags=("node", nid))
            hh = 16
            self.create_polygon(_round_rect(x, y, x + w, y + hh, r=6), fill=_HEAD[n["kind"]],
                                outline="", tags=("node", nid))
            self.create_text(x + w / 2, y + hh / 2, text=_HEAD_LABEL[n["kind"]],
                             fill="#dfe4f5", font=("Segoe UI", 7, "bold"),
                             tags=("node", nid))
            self.create_text(x + 8, y + hh + 8, text=n["title"], anchor=tk.W,
                             fill=_FG, font=("Segoe UI", 10, "bold"), tags=("node", nid))
            if n["sub"]:
                self.create_text(x + 8, y + hh + 27, text=n["sub"][:34], anchor=tk.W,
                                 fill=_MUTED, font=("Consolas", 8), tags=("node", nid))
            for port in ("out", "in"):
                if not self._has_port(nid, port):
                    continue
                px, py = self._port_xy(nid, port)
                is_pend = self.pending == (nid, port) or (
                    self.pending and self.pending[1] == nid)
                col = _PENDING if is_pend else (_PORT_OUT if port == "out" else _PORT_IN)
                self.create_oval(px - 6, py - 6, px + 6, py + 6, fill=col,
                                 outline=_BG, width=1, tags=("port", nid, port))

        max_x = max([n["x"] + n.get("w", NODE_W) for n in self.nodes.values()] + [1000])
        max_y = max([n["y"] + n.get("h", NODE_H) for n in self.nodes.values()] + [700])
        self.configure(scrollregion=(0, 0, max_x + 60, max_y + 60))

    # ================= hit tests =================
    def _node_at(self, x: float, y: float) -> str | None:
        for nid, n in self.nodes.items():
            w = n.get("w", NODE_W)
            h = n.get("h", NODE_H)
            if n["x"] <= x <= n["x"] + w and n["y"] <= y <= n["y"] + h:
                return nid
        return None

    def _port_at(self, x: float, y: float) -> tuple[str, str] | None:
        for nid, n in self.nodes.items():
            for port in ("out", "in"):
                if not self._has_port(nid, port):
                    continue
                px, py = self._port_xy(nid, port)
                if abs(px - x) <= 9 and abs(py - y) <= 9:
                    return (nid, port)
        return None

    def _wire_at(self, x: float, y: float) -> int | None:
        for wi, w in enumerate(self.wires):
            x1, y1 = self._port_xy(w["a"], w["ap"])
            x2, y2 = self._port_xy(w["b"], w["bp"])
            mx = (x1 + x2) / 2
            for (ax, ay, bx, by) in ((x1, y1, mx, y1), (mx, y1, mx, y2), (mx, y2, x2, y2)):
                if _dist_to_seg(x, y, ax, ay, bx, by) < 6:
                    return wi
        return None

    def _xy(self, ev) -> tuple[float, float]:
        return (self.canvasx(ev.x), self.canvasy(ev.y))

    # ================= events =================
    def _on_down(self, ev) -> None:
        self.focus_set()
        x, y = self._xy(ev)
        self._mouse = (x, y)
        port = self._port_at(x, y)
        if port:
            if self.pending and self.pending[0] != port[0]:
                self.designer.connect(self.pending, port)
                self.pending = None
            elif self.pending and self.pending[0] == port[0]:
                self.pending = None
            else:
                self.pending = port
            self._draw()
            return
        wire = self._wire_at(x, y)
        if wire is not None:
            self.sel_wire = wire
            self.sel_node = None
            self.designer.show_wire_inspector(wire)
            self._draw()
            return
        nid = self._node_at(x, y)
        if nid:
            self.sel_node = nid
            self.sel_wire = None
            self._drag = (nid, int(x - self.nodes[nid]["x"]), int(y - self.nodes[nid]["y"]))
            self.designer.show_inspector(nid)
            self._draw()
            return
        # empty space → pan + deselect
        self._pan = True
        self.scan_mark(ev.x, ev.y)
        if self.sel_node or self.sel_wire is not None:
            self.sel_node = None
            self.sel_wire = None
            self.designer._inspector_clear("点击节点编辑；拖端口连线。")
            self._draw()

    def _on_motion(self, ev) -> None:
        x, y = self._xy(ev)
        self._mouse = (x, y)
        if self._drag:
            nid, dx, dy = self._drag
            self.nodes[nid]["x"] = max(0, x - dx)
            self.nodes[nid]["y"] = max(0, y - dy)
            self._draw()
        elif self._pan:
            self.scan_dragto(ev.x, ev.y, gain=1)
        elif self.pending:
            self.delete("preview")
            x1, y1 = self._port_xy(self.pending[0], self.pending[1])
            self.create_line(x1, y1, x, y, fill=_PENDING, width=2, dash=(5, 4),
                             tags=("preview",))

    def _on_up(self, ev) -> None:
        if self._drag:
            nid = self._drag[0]
            n = self.nodes[nid]
            self.designer.data.setdefault("layout", {})[nid] = [int(n["x"]), int(n["y"])]
            self.designer.save_quiet()
            self._drag = None
        self._pan = False

    def _on_delete(self, _ev) -> None:
        if self.sel_wire is not None:
            self.designer.delete_wire(self.sel_wire)
        elif self.sel_node:
            self.designer.delete_node(self.sel_node)


class IODesigner:
    """EEZ-style flow editor tab."""

    def __init__(self, app) -> None:
        self.app = app
        self.data: dict = {"fields": [], "inputs": [], "outputs": [], "flows": [], "layout": {}}
        self.widgets: dict[str, list[str]] = {}
        self.canvas: FlowCanvas | None = None

    def _active(self) -> str:
        return self.app.paths.read_active_project("")

    def reload(self) -> None:
        active = self._active()
        if not active:
            if hasattr(self, "info_var"):
                self.info_var.set("没有激活工程 — 先在 Workbench 页 Import")
            return
        try:
            self.data = io_contract.load(self.app.paths, active)
        except Exception as exc:  # noqa: BLE001
            self.app._append(f"[io] contract load failed: {exc}")
            return
        try:
            import json as _json
            meta = self.app.paths.mvp_dir(active) / "mvp_meta.json"
            if meta.is_file():
                self.widgets = _json.loads(meta.read_text(encoding="utf-8")).get("widgets", {})
        except Exception:  # noqa: BLE001
            self.widgets = {}
        if hasattr(self, "info_var"):
            path = io_contract.contract_path(self.app.paths, active)
            self.info_var.set(f"active={active}  ·  {path}")
        if self.canvas:
            self.canvas.rebuild()
        self._inspector_clear()

    # ----- persistence -----
    def save_quiet(self) -> None:
        active = self._active()
        if not active:
            return
        io_contract.save(self.app.paths, active, self.data)

    def save(self, note: str = "") -> None:
        self.save_quiet()
        self.app._append(f"[io] saved io.json{(' — ' + note) if note else ''}"
                         f"（重新生成 MVP + Build 后生效）")

    # ----- UI -----
    def build(self, parent: ttk.Frame) -> None:
        info = ttk.Frame(parent, style="Card.TFrame", padding=8)
        info.pack(fill=tk.X)
        self.info_var = tk.StringVar(value="loading…")
        ttk.Label(info, textvariable=self.info_var, style="Card.TLabel").pack(anchor=tk.W)
        ttk.Label(
            info,
            text="数据流：外设 ──▶ 变量 ──▶ 输出 · 事件流：页面 ──CMD──▶ 页面 · "
                 "操作：加节点 → 拖端口连线 → 点节点/连线在右侧编辑 → 空白处拖动平移",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(2, 4))
        row = ttk.Frame(info, style="Card.TFrame")
        row.pack(fill=tk.X, pady=(2, 0))
        for kind in io_contract.INPUT_KINDS:
            ttk.Button(row, text=_INPUT_KINDS_CN[kind], style="Secondary.TButton",
                       command=lambda k=kind: self.add_input(k)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row, text="＋变量", style="Secondary.TButton",
                   command=self.add_field).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row, text="＋显示值", style="Secondary.TButton",
                   command=lambda: self.add_output("value")).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row, text="＋控件绑定", style="Secondary.TButton",
                   command=lambda: self.add_output("widget")).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row, text="＋页面事件", style="Secondary.TButton",
                   command=self.add_flow).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row, text="重新生成 MVP", style="Accent.TButton",
                   command=self._regen).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(row, text="刷新", style="Secondary.TButton",
                   command=self.reload).pack(side=tk.LEFT, padx=(6, 0))

        main = ttk.Frame(parent)
        main.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        self.canvas = FlowCanvas(main, self)
        self.canvas.rebuild()

        ins = ttk.Frame(main, style="Card.TFrame", padding=10)
        ins.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.ins_title = tk.StringVar(value="Inspector")
        ttk.Label(ins, textvariable=self.ins_title, style="Muted.TLabel").pack(anchor=tk.W)
        self.ins_body = ttk.Frame(ins, style="Card.TFrame")
        self.ins_body.pack(fill=tk.X, pady=(8, 0))
        self.ins_hint = tk.StringVar(
            value="点节点编辑；从绿点拖到黄点连线；点连线可删除。"
        )
        ttk.Label(ins, textvariable=self.ins_hint, style="Muted.TLabel",
                  wraplength=270, justify=tk.LEFT).pack(anchor=tk.W, pady=(10, 0))

    def _regen(self) -> None:
        regen_mvp_async(self.app, self.app.paths)

    # ----- node factories -----
    def _uniq_id(self, base: str, items: list[dict]) -> str:
        ids = {e.get("id", "") for e in items}
        n = 1
        while f"{base}{n}" in ids:
            n += 1
        return f"{base}{n}"

    def add_input(self, kind: str) -> None:
        items = self.data.setdefault("inputs", [])
        nid = self._uniq_id("in", items)
        items.append({"id": nid, "kind": kind, "label": nid,
                      "bind": {"type": "none", "name": ""}})
        self.save(f"add input {nid} ({kind})")
        self.canvas.rebuild()
        self.show_inspector(f"in:{nid}")

    def add_field(self) -> None:
        items = self.data.setdefault("fields", [])
        names = {f.get("name", "") for f in items}
        n = 1
        while f"var{n}" in names:
            n += 1
        name = f"var{n}"
        items.append({"name": name, "ctype": "int", "init": 0})
        self.save(f"add field {name}")
        self.canvas.rebuild()
        self.show_inspector(f"fld:{name}")

    def add_output(self, kind: str) -> None:
        items = self.data.setdefault("outputs", [])
        nid = self._uniq_id("out", items)
        bind = (
            {"type": "widget", "screen": "", "widget": "", "field": ""}
            if kind == "widget"
            else {"type": "field", "name": ""}
        )
        items.append({"id": nid, "kind": kind, "label": nid, "bind": bind})
        self.save(f"add output {nid} ({kind})")
        self.canvas.rebuild()
        self.show_inspector(f"out:{nid}")

    def add_flow(self) -> None:
        items = self.data.setdefault("flows", [])
        items.append({"from": "", "on": "", "to": "", "policy": "DEL", "src": "user"})
        self.save("add flow")
        self.canvas.rebuild()
        self.show_inspector(f"flow:{len(items) - 1}")

    # ----- wiring -----
    def connect(self, a: tuple[str, str], b: tuple[str, str]) -> None:
        an, bn = a[0], b[0]
        ka, va = an.split(":", 1)
        kb, vb = bn.split(":", 1)
        if not (ka in ("input", "field") and kb in ("field", "output")):
            messagebox.showinfo("连线", "数据流只能：外设 → 变量 → 输出。\n"
                                        "事件流请在页面节点间连线（由 flow 表生成）。")
            return
        if ka == "input":
            inp = next((i for i in self.data.get("inputs", []) if i.get("id") == va), None)
            if not inp:
                return
            if inp.get("kind") == "button" or (inp.get("bind") or {}).get("type") == "cmd":
                messagebox.showinfo("连线", "按键属于事件流：在 Inspector 里选 CMD，"
                                            "页面间的连线即表示该事件跳转。")
                return
            if kb != "field":
                messagebox.showinfo("连线", "输入外设只能连到变量。")
                return
            inp["bind"] = {"type": "field", "name": vb}
            self.save(f"wire {va} → {vb}")
        elif ka == "field":
            if kb != "output":
                return
            out = next((o for o in self.data.get("outputs", []) if o.get("id") == vb), None)
            if not out:
                return
            b = out.get("bind") or {}
            if b.get("type") == "widget":
                b["field"] = va
            else:
                out["bind"] = {"type": "field", "name": va}
            self.save(f"wire {va} → {vb}")
        self.canvas.rebuild()

    def delete_wire(self, wi: int) -> None:
        if not (0 <= wi < len(self.wires)):
            return
        w = self.wires[wi]
        kind = w["kind"]
        if kind == "flow":
            if (w["ref"] or {}).get("src") != "user":
                messagebox.showinfo(
                    "事件流", "这是 AIDOGUI 导入扫描生成的 flow（重新导入会恢复）。\n"
                              "如需改动请改 UI 事件后重新导入。")
                return
            self.data.get("flows", []).pop(w.get("idx", -1))
            self.save("deleted user flow")
        elif kind == "input_bind":
            (w["ref"] or {})["bind"] = {"type": "none", "name": ""}
            self.save("unbound input")
        elif kind == "output_bind":
            b = (w["ref"] or {}).get("bind") or {}
            if b.get("type") == "widget":
                b["field"] = ""
            else:
                (w["ref"] or {})["bind"] = {"type": "none", "name": ""}
            self.save("unbound output")
        self.canvas.rebuild()
        self._inspector_clear("连线已删除。")

    def delete_node(self, nid: str) -> None:
        kind, val = nid.split(":", 1)
        if kind == "in":
            self.data["inputs"] = [i for i in self.data.get("inputs", []) if i.get("id") != val]
        elif kind == "out":
            self.data["outputs"] = [o for o in self.data.get("outputs", []) if o.get("id") != val]
        elif kind == "fld":
            self.data["fields"] = [f for f in self.data.get("fields", []) if f.get("name") != val]
            for i in self.data.get("inputs", []):
                b = i.get("bind") or {}
                if b.get("type") == "field" and b.get("name") == val:
                    i["bind"] = {"type": "none", "name": ""}
            for o in self.data.get("outputs", []):
                b = o.get("bind") or {}
                if b.get("field") == val or (b.get("type") == "field" and b.get("name") == val):
                    if b.get("type") == "widget":
                        b["field"] = ""
                    else:
                        o["bind"] = {"type": "none", "name": ""}
        elif kind == "flow":
            idx = int(val)
            flows = self.data.get("flows", [])
            if 0 <= idx < len(flows):
                flows.pop(idx)
        elif kind == "page":
            messagebox.showinfo("页面", "页面节点来自 UI 导入，不能在此删除。")
            return
        self.data.get("layout", {}).pop(nid, None)
        self._inspector_clear()
        self.save("deleted node")
        self.canvas.rebuild()

    # ----- inspector -----
    def _inspector_clear(self, hint: str | None = None) -> None:
        if not hasattr(self, "ins_body"):
            return
        self.ins_title.set("Inspector")
        for w in self.ins_body.winfo_children():
            w.destroy()
        if hint:
            self.ins_hint.set(hint)

    def show_wire_inspector(self, wi: int) -> None:
        if not (0 <= wi < len(self.wires)):
            return
        w = self.wires[wi]
        kind = w["kind"]
        self.ins_title.set("编辑 连线")
        for c in self.ins_body.winfo_children():
            c.destroy()
        if kind == "flow":
            fl = w["ref"] or {}
            txt = (f"事件流  {fl.get('from', '')} ──{fl.get('on', '')}──▶ "
                   f"{fl.get('to', '')}\n策略 {fl.get('policy', '')} · "
                   f"来源 {fl.get('src', '')}")
            ttk.Label(self.ins_body, text=txt, style="Card.TLabel",
                      justify=tk.LEFT).pack(anchor=tk.W)
            if fl.get("src") == "user":
                ttk.Button(
                    self.ins_body, text="编辑此事件流", style="Accent.TButton",
                    command=lambda i=w.get("idx", -1): self.show_inspector(f"flow:{i}"),
                ).pack(anchor=tk.W, pady=(8, 0))
            ttk.Button(self.ins_body, text="删除连线", style="Secondary.TButton",
                       command=lambda: self.delete_wire(wi)).pack(anchor=tk.W, pady=(8, 0))
            self.ins_hint.set("用户自建的事件流可编辑/删除；"
                              "AIDOGUI 导入扫描的 flow 重新导入时会恢复。")
        elif kind == "input_bind":
            ttk.Label(self.ins_body, text="输入 → 变量 绑定",
                      style="Card.TLabel").pack(anchor=tk.W)
            ttk.Button(self.ins_body, text="删除连线", style="Secondary.TButton",
                       command=lambda: self.delete_wire(wi)).pack(anchor=tk.W, pady=(8, 0))
        else:
            ttk.Label(self.ins_body, text="变量 → 输出 绑定",
                      style="Card.TLabel").pack(anchor=tk.W)
            ttk.Button(self.ins_body, text="删除连线", style="Secondary.TButton",
                       command=lambda: self.delete_wire(wi)).pack(anchor=tk.W, pady=(8, 0))
        self.ins_hint.set("")

    def show_inspector(self, nid: str) -> None:
        kind, val = nid.split(":", 1)
        if kind == "page":
            self.ins_title.set(f"页面 {val}")
            for c in self.ins_body.winfo_children():
                c.destroy()
            flows = [f for f in self.data.get("flows", [])
                     if str(f.get("from", "")).upper() == val.upper()
                     or str(f.get("to", "")).upper() == val.upper()]
            ttk.Label(self.ins_body, text=f"来自 UI 导入的屏幕。\n相关事件流 {len(flows)} 条。",
                      style="Card.TLabel", justify=tk.LEFT).pack(anchor=tk.W)
            self.ins_hint.set("页面节点可拖动布局；页面本身由 AIDOGUI UI 定义。")
            return

        entry: dict | None = None
        if kind == "in":
            entry = next((i for i in self.data.get("inputs", []) if i.get("id") == val), None)
        elif kind == "out":
            entry = next((o for o in self.data.get("outputs", []) if o.get("id") == val), None)
        elif kind == "fld":
            entry = next((f for f in self.data.get("fields", []) if f.get("name") == val), None)
        elif kind == "flow":
            flows = self.data.get("flows", [])
            idx = int(val) if val.isdigit() and int(val) < len(flows) else -1
            entry = flows[idx] if idx >= 0 else None
        if entry is None:
            self._inspector_clear()
            return

        cmds, fields, screens = self._targets()
        widget_list = sorted(
            {f"{s}.{w}" for s, ws in self.widgets.items()
             for w in ws if w.startswith(("lbl_", "label_"))}
        )
        self.ins_title.set(f"编辑 {nid}")
        for c in self.ins_body.winfo_children():
            c.destroy()
        vars_: dict[str, tk.StringVar] = {}

        def add_row(label: str, key: str, values: list[str] | None = None,
                    readonly: bool = False) -> tk.StringVar:
            r = ttk.Frame(self.ins_body, style="Card.TFrame")
            r.pack(fill=tk.X, pady=3)
            ttk.Label(r, text=label, style="Muted.TLabel").pack(side=tk.LEFT)
            var = tk.StringVar()
            vars_[key] = var
            if values is None:
                ttk.Entry(r, textvariable=var, width=16,
                          state="disabled" if readonly else "normal").pack(
                    side=tk.RIGHT, fill=tk.X, expand=True)
            else:
                ttk.Combobox(
                    r, textvariable=var, values=values,
                    state="disabled" if readonly else "readonly", width=14,
                ).pack(side=tk.RIGHT, fill=tk.X, expand=True)
            return var

        if kind == "in":
            add_row("ID", "id", readonly=True).set(entry.get("id", ""))
            add_row("显示名", "label").set(str(entry.get("label", "")))
            add_row("类型", "kind", list(io_contract.INPUT_KINDS)).set(str(entry.get("kind", "")))
            b = entry.get("bind") or {}
            v_bind = add_row("绑定", "bind", ["(未绑定)"] + [
                f"变量  {f}" for f in fields] + [f"CMD  {c}" for c in cmds])
            v_bind.set({"field": f"变量  {b.get('name', '')}",
                        "cmd": f"CMD  {b.get('name', '')}"
                        }.get(b.get("type"), "(未绑定)"))
        elif kind == "fld":
            add_row("变量名", "name").set(str(entry.get("name", "")))
            add_row("类型", "ctype", list(io_contract.CTYPES)).set(str(entry.get("ctype", "int")))
            add_row("初值", "init").set(str(entry.get("init", 0)))
        elif kind == "out":
            add_row("ID", "id", readonly=True).set(entry.get("id", ""))
            add_row("显示名", "label").set(str(entry.get("label", "")))
            add_row("类型", "kind", list(io_contract.OUTPUT_KINDS)).set(str(entry.get("kind", "")))
            b = entry.get("bind") or {}
            if b.get("type") == "widget":
                add_row("屏幕.控件", "widget", widget_list).set(
                    f"{b.get('screen', '')}.{b.get('widget', '')}")
                add_row("来源变量", "field", fields).set(str(b.get("field", "")))
            else:
                add_row("来源变量", "name", fields).set(str(b.get("name", "")))
        else:  # flow
            add_row("来源页面", "from", screens).set(str(entry.get("from", "")))
            add_row("事件 CMD", "on", cmds).set(str(entry.get("on", "")))
            add_row("目标页面", "to", screens).set(str(entry.get("to", "")))
            add_row("卸载策略", "policy", ["DEL", "HIDE"]).set(str(entry.get("policy", "DEL")))

        def on_ok() -> None:
            if kind == "in":
                entry["label"] = vars_["label"].get().strip() or entry["id"]
                entry["kind"] = vars_["kind"].get()
                raw = vars_["bind"].get()
                if raw.startswith("变量  "):
                    entry["bind"] = {"type": "field", "name": raw[3:].strip()}
                elif raw.startswith("CMD  "):
                    entry["bind"] = {"type": "cmd", "name": raw[4:].strip()}
                else:
                    entry["bind"] = {"type": "none", "name": ""}
            elif kind == "fld":
                old = entry.get("name", "")
                new = io_contract.normalize_name(vars_["name"].get())
                entry["name"] = new
                entry["ctype"] = vars_["ctype"].get()
                try:
                    entry["init"] = float(vars_["init"].get())
                except ValueError:
                    entry["init"] = 0
                if old != new:
                    for i in self.data.get("inputs", []):
                        b = i.get("bind") or {}
                        if b.get("name") == old:
                            b["name"] = new
                    for o in self.data.get("outputs", []):
                        b = o.get("bind") or {}
                        if b.get("name") == old:
                            b["name"] = new
                        if b.get("field") == old:
                            b["field"] = new
            elif kind == "out":
                entry["label"] = vars_["label"].get().strip() or entry["id"]
                entry["kind"] = vars_["kind"].get()
                b = entry.get("bind") or {}
                if b.get("type") == "widget":
                    sw = vars_["widget"].get().strip()
                    screen, _, widget = sw.partition(".")
                    b["screen"], b["widget"] = screen.strip(), widget.strip()
                    b["field"] = vars_["field"].get().strip()
                else:
                    entry["bind"] = {"type": "field", "name": vars_["name"].get().strip()}
                    if entry["kind"] == "widget":
                        entry["kind"] = "value"
            else:  # flow
                entry["from"] = vars_["from"].get().strip()
                entry["on"] = vars_["on"].get().strip()
                entry["to"] = vars_["to"].get().strip()
                entry["policy"] = vars_["policy"].get()
            self.save("edited " + nid)
            self.canvas.rebuild()

        btns = ttk.Frame(self.ins_body, style="Card.TFrame")
        btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btns, text="应用", style="Accent.TButton", command=on_ok).pack(
            side=tk.LEFT, padx=(0, 6))
        if kind in ("in", "out", "fld"):
            ttk.Button(
                btns, text="删除节点", style="Secondary.TButton",
                command=lambda: self.delete_node(nid),
            ).pack(side=tk.LEFT)
        self.ins_hint.set("改完点「应用」；契约改动要点「重新生成 MVP」+ Build 才进 C 代码。")

    # ----- targets -----
    def _targets(self) -> tuple[list[str], list[str], list[str]]:
        cmds: list[str] = []
        screens: list[str] = []
        t = getattr(self.app, "_signal_table", None)
        if t:
            cmds = [c.name for c in t.commands]
            screens = [s.name for s in t.screens]
        fields = [f.get("name", "") for f in self.data.get("fields", []) if f.get("name")]
        cmds += [c for c in io_contract.input_cmds(self.data) if c not in cmds]
        return cmds, fields, screens


class SimIOPanel(tk.Toplevel):
    """Floating panel rendered from the io contract; drives a running sim
    over the CMD/SET/STATE pipe and shows live STATE values."""

    def __init__(self, app, contract: dict) -> None:
        super().__init__(app)
        self.app = app
        self.contract = contract
        self.handle: runner.SimHandle | None = None
        self.q: queue.Queue[str] = queue.Queue()

        active = app.paths.read_active_project("")
        self.title(f"仿真 I/O — {active}")
        self.configure(bg="#1e1f26")
        try:
            app_x = app.winfo_x()
            app_y = app.winfo_y()
            app_w = app.winfo_width()
            x = min(app_x + app_w + 8, self.winfo_screenwidth() - 440)
            y = max(0, min(app_y, self.winfo_screenheight() - 660))
            self.geometry(f"420x640+{max(0, x)}+{y}")
        except tk.TclError:
            pass

        head = ttk.Frame(self, style="Card.TFrame", padding=8)
        head.pack(fill=tk.X)
        self.state_var = tk.StringVar(value="sim: starting…")
        ttk.Label(head, textvariable=self.state_var, style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Button(
            head, text="Stop", style="Secondary.TButton", command=self._stop
        ).pack(side=tk.RIGHT)

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        in_card = ttk.Frame(body, style="Card.TFrame", padding=8)
        in_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        ttk.Label(in_card, text="INPUTS", style="Muted.TLabel").pack(anchor=tk.W)
        self._build_inputs(in_card)

        out_card = ttk.Frame(body, style="Card.TFrame", padding=8)
        out_card.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ttk.Label(out_card, text="OUTPUTS (STATE)", style="Muted.TLabel").pack(anchor=tk.W)
        self.out_list = scrolledtext.ScrolledText(
            out_card, bg="#15161c", fg="#d0d4e0", font=("Consolas", 10),
            relief=tk.FLAT, borderwidth=0, highlightthickness=0, state=tk.DISABLED,
        )
        self.out_list.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        log_card = ttk.Frame(self, style="Card.TFrame", padding=8)
        log_card.pack(fill=tk.X, side=tk.BOTTOM)
        self.sim_log = scrolledtext.ScrolledText(
            log_card, height=6, bg="#15161c", fg="#9aa0b4", font=("Consolas", 8),
            relief=tk.FLAT, borderwidth=0, highlightthickness=0, state=tk.DISABLED,
        )
        self.sim_log.pack(fill=tk.X)

        self.protocol("WM_DELETE_WINDOW", self._stop)
        self.after(120, self._poll)

    def _build_inputs(self, parent: ttk.Frame) -> None:
        for inp in self.contract.get("inputs", []):
            kind = inp.get("kind", "button")
            b = inp.get("bind") or {}
            label = inp.get("label") or inp.get("id")
            row = ttk.Frame(parent, style="Card.TFrame")
            row.pack(fill=tk.X, pady=4)
            if b.get("type") == "cmd":
                ttk.Button(
                    row, text=f"▸ {label}  (CMD {b.get('name', '')})",
                    style="Accent.TButton",
                    command=lambda n=str(b.get("name", "")): self._send(f"CMD {n}"),
                ).pack(fill=tk.X)
            elif kind == "switch":
                var = tk.BooleanVar(value=False)
                ttk.Checkbutton(
                    row, text=label, variable=var,
                    command=lambda n=str(b.get("name", "")), v=var: self._send(
                        f"SET {n} {1 if v.get() else 0}"
                    ),
                ).pack(anchor=tk.W)
            else:
                step = float(b.get("step") or 1)
                erow = ttk.Frame(row, style="Card.TFrame")
                erow.pack(fill=tk.X)
                ent = ttk.Entry(erow, width=12)
                ent.pack(side=tk.LEFT)
                ttk.Label(erow, text=f"← {label}  ({b.get('name', '')})",
                          style="Muted.TLabel").pack(side=tk.LEFT, padx=(6, 0))
                ttk.Button(
                    erow, text="Set", style="Secondary.TButton",
                    command=lambda n=str(b.get("name", "")), e2=ent: self._send(
                        f"SET {n} {e2.get().strip()}"
                    ),
                ).pack(side=tk.LEFT, padx=(6, 0))
                if kind in ("knob", "slider", "sensor"):
                    var = tk.DoubleVar(value=0.0)
                    scale = ttk.Scale(row, from_=0.0, to=100.0, variable=var,
                                      orient=tk.HORIZONTAL)
                    scale.pack(fill=tk.X, pady=(2, 0))
                    val_lab = ttk.Label(row, text=f"{label}  = 0", style="Muted.TLabel")
                    val_lab.pack(anchor=tk.W)

                    def on_release(_ev, v=var, n=str(b.get("name", "")),
                                   st=step, lab=val_lab):
                        raw = v.get()
                        snapped = round(raw / st) * st if st > 0 else raw
                        self._send(f"SET {n} {snapped:g}")
                        lab.configure(text=f"{lab.cget('text').split('  =')[0]}  = {snapped:g}")

                    scale.bind("<ButtonRelease-1>", on_release)

    def attach(self, handle: runner.SimHandle) -> None:
        self.handle = handle
        self.state_var.set("sim: running")

    def feed_line(self, line: str) -> None:
        self.q.put(line)

    def on_exit(self, code: int) -> None:
        self.q.put(f"\n[sim exited code={code}]")
        self.q.put("__EXIT__")

    def _send(self, line: str) -> None:
        if self.handle:
            self.handle.send(line)

    def _stop(self) -> None:
        if self.handle:
            self.handle.stop()
            self.handle = None
        self.destroy()

    def _poll(self) -> None:
        try:
            while True:
                line = self.q.get_nowait()
                if line == "__EXIT__":
                    self.state_var.set("sim: stopped")
                    return
                self._log(line)
                if line.startswith("STATE "):
                    self._apply_state(line)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(120, self._poll)

    def _log(self, line: str) -> None:
        self.sim_log.configure(state=tk.NORMAL)
        self.sim_log.insert(tk.END, line + "\n")
        self.sim_log.see(tk.END)
        if float(self.sim_log.index(tk.END).split(".")[0]) > 400:
            self.sim_log.delete("1.0", "50.0")
        self.sim_log.configure(state=tk.DISABLED)

    def _apply_state(self, line: str) -> None:
        parts = line.split()[1:]
        self.out_list.configure(state=tk.NORMAL)
        self.out_list.delete("1.0", tk.END)
        for p in parts:
            self.out_list.insert(tk.END, p + "\n")
        self.out_list.configure(state=tk.DISABLED)


def build_io_tab(app, parent: ttk.Frame) -> IODesigner:
    designer = IODesigner(app)
    designer.build(parent)
    return designer


def refresh_io_tab(app) -> None:
    d: IODesigner | None = getattr(app, "_io_designer", None)
    if d:
        d.reload()


def regen_mvp_async(app, paths: AppPaths) -> None:
    """Re-run scripts/gen_mvp.py for the active project (picks up io.json)."""
    active = paths.read_active_project("")
    if not active:
        messagebox.showinfo("I/O", "没有激活工程 — 先 Import。")
        return
    gen_py = paths.wb_root / "scripts" / "gen_mvp.py"
    mvp_dir = paths.ui_project_dir(active)  # project root (must contain ui.h)
    app._set_busy(True)
    app._append(f"\n--- gen_mvp (io contract) {active} ---")

    def work() -> None:
        try:
            proc = subprocess.run(
                [sys.executable, str(gen_py), str(mvp_dir)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=120,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            for ln in out.splitlines():
                app.after(0, lambda l=ln: app._append(l))
            code = proc.returncode
        except Exception as exc:  # noqa: BLE001
            app.after(0, lambda: app._append(f"[gen_mvp] error: {exc}"))
            code = 1
        app.after(0, lambda: (app._append(f"[exit {code}]"), app._set_busy(False)))

    threading.Thread(target=work, daemon=True).start()