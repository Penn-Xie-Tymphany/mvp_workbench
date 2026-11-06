"""PySide6 GUI — primary desktop shell (HiDPI-crisp, GPU-accelerated canvas).

Tabs: Workbench (Import/Build/Sim) · I/O 设计 (EEZ-style flow canvas) · Test Panel.
Tkinter (gui_tk.py) remains the fallback when PySide6 is not installed.
"""

from __future__ import annotations

import math
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import io_contract, runner, signal_scan
from .env_isolate import toolchain_status
from .paths import AppPaths

# ---- palette ---------------------------------------------------------------
BG = "#1e1f26"
PANEL = "#2a2b36"
CARD = "#323344"
FG = "#e8e8ef"
MUTED = "#9aa0b4"
ACCENT = "#5b8def"
OK = "#3dba7a"
BAD = "#e35d6a"
LOG_BG = "#15161c"
LOG_FG = "#d0d4e0"
BORDER = "#3f4154"
CANVAS_BG = "#14151a"
GRID = "#22242e"
HEAD = {"input": "#2f57a8", "field": "#1e6e46",
        "output": "#8a6420", "page": "#5a3d82"}
HEAD_LABEL = {"input": "INPUT 外设", "field": "VAR 变量",
              "output": "OUTPUT 输出", "page": "PAGE 页面"}
BODY = "#26272f"
EDGE = "#8a90a8"
PORT_OUT = "#3dba7a"
PORT_IN = "#e6b84d"
WIRE_DATA = "#5b8def"
WIRE_EVENT = "#c98a3d"
PENDING = "#e6b84d"

NODE_W, NODE_H = 200, 66
PAGE_W, PAGE_H = 160, 48
COL_X = {"input": 60, "field": 360, "output": 680}
LANE_TOP = 30
LANE_GAP = 16
EVENT_GAP = 140
PAGE_COLS = 4

QSS = f"""
* {{ color: {FG}; font-size: 13px; }}
QMainWindow, QWidget {{ background: {BG}; }}
QPlainTextEdit, QLineEdit {{ background: {LOG_BG}; color: {LOG_FG};
    border: 1px solid {BORDER}; border-radius: 4px; padding: 4px; }}
QPlainTextEdit[readonly="true"] {{ color: {LOG_FG}; }}
QComboBox {{ background: {CARD}; border: 1px solid {BORDER}; padding: 4px 8px; }}
QPushButton {{ background: {CARD}; border: none; padding: 7px 14px; border-radius: 4px; }}
QPushButton:hover {{ background: #3c3e50; }}
QPushButton#accent {{ background: {ACCENT}; font-weight: bold; }}
QPushButton#accent:hover {{ background: #4a7ad9; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: {CARD}; padding: 8px 18px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {ACCENT}; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; }}
QDockWidget::title {{ background: {PANEL}; padding: 6px; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#chip {{ font-weight: bold; padding: 4px 12px; border-radius: 4px; }}
QLabel#chipOk {{ background: {OK}; color: #0d1a12; }}
QLabel#chipBad {{ background: {BAD}; color: #1a0d0f; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 6px; margin-top: 10px;
    background: {PANEL}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; color: {MUTED}; }}
"""


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


class LogBridge(QObject):
    line = Signal(str)

    def emit(self, s: str) -> None:
        """Thread-safe log relay (PySide6 has no callable QObject.emit)."""
        self.line.emit(str(s))

    # callable-compatible alias used by runner(log=...)
    write = emit


class _Node:
    """Pure-data graph node produced by the designer model."""
    def __init__(self, nid, kind, title, sub, x, y, w, h):
        self.nid, self.kind, self.title, self.sub = nid, kind, title, sub
        self.x, self.y, self.w, self.h = x, y, w, h


class _Wire:
    def __init__(self, a, ap, b, bp, kind, ref, label=""):
        self.a, self.ap, self.b, self.bp = a, ap, b, bp
        self.kind, self.ref, self.label = kind, ref, label


class IODesigner:
    """Graph model for the flow editor — shared by canvas rendering and io.json."""

    def __init__(self, app: "MainWindow") -> None:
        self.app = app
        self.data: dict = {"fields": [], "inputs": [], "outputs": [], "flows": [], "layout": {}}
        self.widgets: dict[str, list[str]] = {}
        self.widget_info: dict[str, dict[str, dict]] = {}
        self.preview_sel: tuple[str, str] | None = None
        self.nodes: list[_Node] = []
        self.wires: list[_Wire] = []

    def _active(self) -> str:
        return self.app.paths.read_active_project("")

    def reload(self) -> None:
        active = self._active()
        if not active:
            self.info_var.setText("没有激活工程 — 先在 Workbench 页 Import")
            return
        try:
            self.data = io_contract.load(self.app.paths, active)
        except Exception as exc:  # noqa: BLE001
            self.app.log_line(f"[io] contract load failed: {exc}")
            return
        try:
            import json as _json
            meta = self.app.paths.mvp_dir(active) / "mvp_meta.json"
            if meta.is_file():
                m = _json.loads(meta.read_text(encoding="utf-8"))
                self.widgets = m.get("widgets", {})
                self.widget_info = m.get("widget_classes", {})
        except Exception:  # noqa: BLE001
            self.widgets = {}
            self.widget_info = {}
        path = io_contract.contract_path(self.app.paths, active)
        self.info_var.setText(f"active={active}  ·  {path}")
        self.rebuild_graph()
        self._refresh_ui()
        self.app.show_inspector(None)

    def _refresh_ui(self) -> None:
        pf = getattr(self.app, "page_flow", None)
        if pf:
            pf.refresh()

    def save_quiet(self) -> None:
        active = self._active()
        if not active:
            return
        try:
            io_contract.save(self.app.paths, active, self.data)
        except Exception as exc:  # noqa: BLE001 — make save failures LOUD
            self.app.log_line(f"[io] !!! 保存失败: {exc}")
            QMessageBox.critical(self.app, "I/O 契约保存失败", str(exc))

    def save(self, note: str = "") -> None:
        self.save_quiet()
        self.app.log_line(f"[io] saved io.json{(' — ' + note) if note else ''}"
                          f"（重新生成 MVP + Build 后生效）")

    # ----- graph build (model) -----
    def rebuild_graph(self) -> None:
        data = self.data
        layout = data.get("layout", {})
        self.nodes.clear()
        self.wires.clear()

        def add(nid, kind, title, sub, x, y, w=NODE_W, h=NODE_H):
            px, py = layout.get(nid, (x, y))
            self.nodes.append(_Node(nid, kind, title, sub, px, py, w, h))
            return py + h

        yb = LANE_TOP
        for inp in data.get("inputs", []):
            nid = f"in:{inp.get('id', '')}"
            yb = max(yb, add(nid, "input", str(inp.get("label") or inp.get("id", "")),
                             f"{inp.get('kind', '')} · {_bind_text(inp)}",
                             COL_X["input"], yb)) + LANE_GAP

        yf = LANE_TOP
        for f in io_contract.field_binds(data):
            nid = f"fld:{f['name']}"
            yf = max(yf, add(nid, "field", f["name"],
                             f"{f['ctype']} · 初值 {f.get('init', 0)}",
                             COL_X["field"], yf)) + LANE_GAP

        yo = LANE_TOP
        for out in data.get("outputs", []):
            nid = f"out:{out.get('id', '')}"
            yo = max(yo, add(nid, "output", str(out.get("label") or out.get("id", "")),
                             f"{out.get('kind', '')} · {_bind_text(out)}",
                             COL_X["output"], yo)) + LANE_GAP

        ev_y0 = max(yb, yf, yo) + EVENT_GAP
        table = self.app.signal_table
        screens = [s.name for s in table.screens] if table else []
        pw, ph, gx, gy = PAGE_W, PAGE_H, 50, 34
        for i, s in enumerate(screens):
            nid = f"page:{s}"
            if nid not in layout:
                r, c = divmod(i, PAGE_COLS)
                layout[nid] = [COL_X["input"] + c * (pw + gx), ev_y0 + r * (ph + gy)]
        for s in screens:
            add(f"page:{s}", "page", s, "", 0, 0, w=pw, h=ph)

        fld_map = {n.nid.split(":", 1)[1]: n.nid for n in self.nodes if n.kind == "field"}

        def fld(name):
            return fld_map.get(io_contract.normalize_name(str(name)))

        for inp in data.get("inputs", []):
            b = inp.get("bind") or {}
            if b.get("type") == "field":
                t = fld(b.get("name", ""))
                if t:
                    self.wires.append(_Wire(f"in:{inp.get('id')}", "out", t, "in",
                                            "input_bind", inp))
        for out in data.get("outputs", []):
            b = out.get("bind") or {}
            src = b.get("name") if b.get("type") == "field" else b.get("field")
            if b.get("type") in ("field", "widget") and src:
                t = fld(src)
                if t:
                    self.wires.append(_Wire(t, "out", f"out:{out.get('id')}", "in",
                                            "output_bind", out))

        for i, fl in enumerate(data.get("flows", [])):
            a = f"page:{str(fl.get('from', '')).upper()}"
            b = f"page:{str(fl.get('to', '')).upper()}"
            if fl.get("from") and fl.get("to") and \
                    any(n.nid == a for n in self.nodes) and any(n.nid == b for n in self.nodes):
                self.wires.append(_Wire(a, "out", b, "in", "flow", fl,
                                        label=str(fl.get("on", ""))))
        for inp in data.get("inputs", []):
            b = inp.get("bind") or {}
            if b.get("type") == "cmd":
                for w in self.wires:
                    if w.kind == "flow" and w.label.upper() == str(b.get("name", "")).upper():
                        self.wires.append(_Wire(f"in:{inp.get('id')}", "out", w.b, "in",
                                                "hint", None))
                        break

    # ----- persistence + ops -----
    def node_at(self, nid: str) -> _Node | None:
        return next((n for n in self.nodes if n.nid == nid), None)

    def connect(self, a: tuple[str, str], b: tuple[str, str]) -> None:
        an, bn = a[0], b[0]
        ka, va = an.split(":", 1)
        kb, vb = bn.split(":", 1)
        if not (ka in ("input", "field") and kb in ("field", "output")):
            QMessageBox.information(self.app, "连线",
                                    "数据流只能：外设 → 变量 → 输出。\n"
                                    "事件流是页面间的连线（由 flow 表生成）。")
            return
        if ka == "input":
            inp = next((i for i in self.data.get("inputs", []) if i.get("id") == va), None)
            if not inp:
                return
            if inp.get("kind") == "button" or (inp.get("bind") or {}).get("type") == "cmd":
                QMessageBox.information(
                    self.app, "连线",
                    "按键属于事件流：在 Inspector 里选 CMD，页面间的连线即该事件跳转。")
                return
            if kb != "field":
                QMessageBox.information(self.app, "连线", "输入外设只能连到变量。")
                return
            inp["bind"] = {"type": "field", "name": vb}
            self.save(f"wire {va} → {vb}")
        elif ka == "field":
            out = next((o for o in self.data.get("outputs", []) if o.get("id") == vb), None)
            if not out:
                return
            b = out.get("bind") or {}
            if b.get("type") == "widget":
                b["field"] = va
            else:
                out["bind"] = {"type": "field", "name": va}
            self.save(f"wire {va} → {vb}")
        self.rebuild_graph()
        self._refresh_ui()

    def delete_wire(self, wire: _Wire) -> None:
        if wire not in self.wires:
            return
        kind = wire.kind
        if kind == "flow":
            if (wire.ref or {}).get("src") != "user":
                QMessageBox.information(
                    self.app, "事件流",
                    "这是 AIDOGUI 导入扫描生成的 flow（重新导入会恢复），不能在此删除。")
                return
            try:
                self.data.get("flows", []).remove(wire.ref)
            except ValueError:
                pass
            self.save("deleted user flow")
        elif kind == "input_bind":
            (wire.ref or {})["bind"] = {"type": "none", "name": ""}
            self.save("unbound input")
        elif kind == "output_bind":
            b = (wire.ref or {}).get("bind") or {}
            if b.get("type") == "widget":
                b["field"] = ""
            else:
                (wire.ref or {})["bind"] = {"type": "none", "name": ""}
            self.save("unbound output")
        self.rebuild_graph()
        self._refresh_ui()
        self.app.show_inspector(None)

    def delete_node(self, nid: str) -> None:
        kind, val = nid.split(":", 1)
        if kind == "in":
            self.data["inputs"] = [i for i in self.data.get("inputs", [])
                                   if i.get("id") != val]
        elif kind == "out":
            self.data["outputs"] = [o for o in self.data.get("outputs", [])
                                    if o.get("id") != val]
        elif kind == "fld":
            self.data["fields"] = [f for f in self.data.get("fields", [])
                                   if f.get("name") != val]
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
        elif kind == "page":
            QMessageBox.information(self.app, "页面", "页面节点来自 UI 导入，不能在此删除。")
            return
        self.data.get("layout", {}).pop(nid, None)
        self.rebuild_graph()
        self._refresh_ui()
        self.app.show_inspector(None)
        self.save("deleted node")

    # ----- factories -----
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
        self.rebuild_graph()
        self._refresh_ui()
        self.app.show_inspector(f"in:{nid}")

    def add_field(self) -> None:
        items = self.data.setdefault("fields", [])
        names = {f.get("name", "") for f in items}
        n = 1
        while f"var{n}" in names:
            n += 1
        name = f"var{n}"
        items.append({"name": name, "ctype": "int", "init": 0})
        self.save(f"add field {name}")
        self.rebuild_graph()
        self._refresh_ui()
        self.app.show_inspector(f"fld:{name}")

    def add_output(self, kind: str) -> None:
        items = self.data.setdefault("outputs", [])
        nid = self._uniq_id("out", items)
        bind = ({"type": "widget", "screen": "", "widget": "", "field": ""}
                if kind == "widget" else {"type": "field", "name": ""})
        items.append({"id": nid, "kind": kind, "label": nid, "bind": bind})
        self.save(f"add output {nid} ({kind})")
        self.rebuild_graph()
        self._refresh_ui()
        self.app.show_inspector(f"out:{nid}")

    def add_flow(self) -> None:
        items = self.data.setdefault("flows", [])
        items.append({"from": "", "on": "", "to": "", "policy": "DEL", "src": "user"})
        self.save("add flow")
        self.rebuild_graph()
        self._refresh_ui()
        self.app.show_inspector(f"flow:{len(items) - 1}")

    # ----- targets -----
    def _targets(self) -> tuple[list[str], list[str], list[str]]:
        cmds: list[str] = []
        screens: list[str] = []
        t = self.app.signal_table
        if t:
            cmds = [c.name for c in t.commands]
            screens = [s.name for s in t.screens]
        fields = [f.get("name", "") for f in self.data.get("fields", []) if f.get("name")]
        cmds += [c for c in io_contract.input_cmds(self.data) if c not in cmds]
        return cmds, fields, screens


# ============================ node editor (Qt) ==============================

class WireItem(QGraphicsPathItem):
    def __init__(self, view: "FlowView", wire: _Wire, src: QPointF, dst: QPointF) -> None:
        super().__init__()
        self.view = view
        self.wire = wire
        self._src, self._dst = src, dst
        color = QColor(WIRE_EVENT if wire.kind == "flow" else
                       ("#5a5f75" if wire.kind == "hint" else WIRE_DATA))
        self._color = color
        mid = (src.x() + dst.x()) / 2
        path = QPainterPath(src)
        path.cubicTo(QPointF(mid, src.y()), QPointF(mid, dst.y()), dst)
        self.setPath(path)
        w = 2 if wire.kind == "hint" else 4
        self.setPen(QPen(QBrush(color), w, Qt.DashLine if wire.kind == "hint" else
                         Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setZValue(2)
        self._extras: list[QGraphicsItem] = []

    def finalize(self) -> None:
        """Call after the item is added to the scene."""
        scene = self.scene()
        dst, src = self._dst, self._src
        tri = QPolygonF([QPointF(dst.x() - 1, dst.y()),
                         QPointF(dst.x() - 11, dst.y() - 6),
                         QPointF(dst.x() - 11, dst.y() + 6)])
        arrow = scene.addPolygon(tri, QPen(QBrush(self._color), 1),
                                 QBrush(self._color))
        arrow.setZValue(2)
        self._extras.append(arrow)
        if self.wire.label:
            t = scene.addText(self.wire.label, QFont("Consolas", 9, QFont.Bold))
            t.setDefaultTextColor(QColor(FG))
            br = t.boundingRect()
            mid = (src.x() + dst.x()) / 2
            cy = (src.y() + dst.y()) / 2 - 22
            bg = scene.addRect(
                QRectF(mid - br.width() / 2 - 4, cy - 2, br.width() + 8, br.height() + 4),
                QPen(Qt.NoPen), QBrush(QColor(CANVAS_BG)))
            t.setPos(mid - br.width() / 2, cy)
            for it in (bg, t):
                it.setZValue(3)
                self._extras.append(it)

    def shape(self) -> QPainterPath:
        from PySide6.QtGui import QPainterPathStroker
        stroker = QPainterPathStroker()
        stroker.setWidth(14)
        return stroker.createStroke(self.path())


class PortHandle:
    __slots__ = ("nid", "port", "x", "y")

    def __init__(self, nid, port, x, y):
        self.nid, self.port, self.x, self.y = nid, port, x, y


class NodeItem(QGraphicsObject):
    def __init__(self, view: "FlowView", node: _Node) -> None:
        super().__init__()
        self.view = view
        self.node = node
        self.setPos(node.x, node.y)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(10)
        self.setToolTip(f"{node.nid}\n{node.sub}")

    def boundingRect(self) -> QRectF:
        return QRectF(-8, -8, self.node.w + 16, self.node.h + 16)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        n = self.node
        painter.setRenderHint(QPainter.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(QRectF(0, 0, n.w, n.h), 10, 10)
        painter.fillPath(body, QBrush(QColor(BODY)))
        painter.setPen(QPen(QBrush(QColor(PENDING if self.isSelected() else EDGE)),
                            2 if self.isSelected() else 1))
        painter.drawPath(body)
        # header band
        painter.save()
        head = QPainterPath()
        head.addRoundedRect(QRectF(0, 0, n.w, 20), 10, 10)
        painter.setClipRect(QRectF(0, 0, n.w, 20))
        painter.fillPath(head, QBrush(QColor(HEAD[n.kind])))
        painter.restore()
        painter.setPen(QColor("#dfe4f5"))
        painter.setFont(QFont("Microsoft YaHei UI", 7, QFont.Bold))
        painter.drawText(QRectF(0, 1, n.w, 18), Qt.AlignCenter, HEAD_LABEL[n.kind])
        painter.setPen(QColor(FG))
        painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        painter.drawText(QRectF(10, 24, n.w - 20, 18), Qt.AlignLeft, n.title)
        if n.sub:
            painter.setPen(QColor(MUTED))
            painter.setFont(QFont("Consolas", 8))
            fm = painter.fontMetrics()
            sub = fm.elidedText(n.sub, Qt.ElideRight, n.w - 20)
            painter.drawText(QRectF(10, 44, n.w - 20, 14), Qt.AlignLeft, sub)
        # ports
        for port, color in (("out", PORT_OUT), ("in", PORT_IN)):
            if not self.view.has_port(n.nid, port):
                continue
            cx = n.w if port == "out" else 0
            painter.setPen(QPen(QBrush(QColor(CANVAS_BG)), 1))
            painter.setBrush(QBrush(QColor(PENDING if
                                           (self.view.pending == (n.nid, port) or
                                            (self.view.pending and
                                             self.view.pending[0] == n.nid)) else color)))
            painter.drawEllipse(QPointF(cx, n.h / 2), 7, 7)

    def port_handles(self) -> list[PortHandle]:
        n = self.node
        out = []
        for port in ("out", "in"):
            if self.view.has_port(n.nid, port):
                cx = n.w if port == "out" else 0
                out.append(PortHandle(n.nid, port, cx, n.h / 2))
        return out

    def mousePressEvent(self, ev) -> None:
        pos = ev.position() if hasattr(ev, "position") else ev.pos()
        for h in self.port_handles():
            if math.hypot(pos.x() - h.x, pos.y() - h.y) <= 10:
                self.view.begin_connect((h.nid, h.port))
                ev.accept()
                return
        self.scene().clearSelection()
        self.setSelected(True)
        self.view.designer_save_pending = True
        self.view.show_inspector_for(self.node.nid)
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        self.view.save_layout_for(self.node.nid, self.pos())
        super().mouseReleaseEvent(ev)


class FlowView(QGraphicsView):
    """Zoomable / pannable node canvas."""

    def __init__(self, designer: IODesigner, parent=None) -> None:
        super().__init__(parent)
        self.designer = designer
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor(CANVAS_BG)))
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.pending: tuple[str, str] | None = None
        self._preview: QGraphicsPathItem | None = None
        self._node_items: dict[str, NodeItem] = {}
        self._wire_items: list[tuple[WireItem, list]] = []
        self.designer_save_pending = False

    # ---- structure ----
    def rebuild(self) -> None:
        self._scene.clear()
        self._node_items.clear()
        self._wire_items.clear()
        self.pending = None
        self._preview = None
        d = self.designer
        for n in d.nodes:
            it = NodeItem(self, n)
            self._scene.addItem(it)
            self._node_items[n.nid] = it
        for w in d.wires:
            src_node = self._node_items.get(w.a)
            dst_node = self._node_items.get(w.b)
            if not src_node or not dst_node:
                continue
            src = src_node.mapToScene(QPointF(src_node.node.w, src_node.node.h / 2))
            dst = dst_node.mapToScene(QPointF(0, dst_node.node.h / 2))
            item = WireItem(self, w, src, dst)
            self._scene.addItem(item)
            item.finalize()
            self._wire_items.append((item, w))
        self.draw_grid()

    def draw_grid(self) -> None:
        r = self.sceneRect().adjusted(-400, -400, 400, 400)
        step = 26
        xs = int(r.left()) // step * step
        ys = int(r.top()) // step * step
        pen = QPen(QBrush(QColor(GRID)), 1.4)
        while xs <= r.right():
            y = ys
            while y <= r.bottom():
                self._scene.addEllipse(xs, y, 1.6, 1.6, pen, QBrush(QColor(GRID)))
                y += step
            xs += step
        # zone captions
        for label, x in (("输入 外设", COL_X["input"] + NODE_W / 2),
                         ("变量 Model", COL_X["field"] + NODE_W / 2),
                         ("输出", COL_X["output"] + NODE_W / 2)):
            t = self._scene.addText(label, QFont("Microsoft YaHei UI", 9, QFont.Bold))
            t.setDefaultTextColor(QColor(MUTED))
            t.setPos(x - t.boundingRect().width() / 2, 2)
            t.setZValue(1)
        pages = [n for n in self.designer.nodes if n.kind == "page"]
        if pages:
            evy = min(n.y for n in pages) - 30
            t = self._scene.addText("事件流 — 页面 ──CMD──▶ 页面（点连线可删/编）",
                                    QFont("Microsoft YaHei UI", 9, QFont.Bold))
            t.setDefaultTextColor(QColor(MUTED))
            t.setPos(COL_X["input"], evy)
            t.setZValue(1)

    def has_port(self, nid: str, port: str) -> bool:
        k = nid.split(":", 1)[0]
        return not (k == "input" and port == "in") and \
               not (k == "output" and port == "out")

    def show_inspector_for(self, nid: str) -> None:
        self.designer.app.show_inspector(nid)

    def save_layout_for(self, nid: str, pos: QPointF) -> None:
        d = self.designer
        node = d.node_at(nid)
        if node and (abs(node.x - pos.x()) > 0.5 or abs(node.y - pos.y()) > 0.5):
            d.data.setdefault("layout", {})[nid] = [int(pos.x()), int(pos.y())]
            d.save_quiet()

    # ---- connect flow ----
    def begin_connect(self, handle: tuple[str, str]) -> None:
        self.pending = handle
        self._preview = None

    def _port_at_scene(self, sp: QPointF) -> tuple[str, str] | None:
        for item in self.items(sp):
            if isinstance(item, NodeItem):
                local = item.mapFromScene(sp)
                n = item.node
                for h in item.port_handles():
                    if math.hypot(local.x() - h.x, local.y() - h.y) <= 11:
                        return (h.nid, h.port)
        return None

    def mouseMoveEvent(self, ev) -> None:
        if getattr(self, "_panning", False):
            pos = ev.position()
            delta = pos - self._pan_last
            self._pan_last = pos
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            ev.accept()
            return
        if self.pending:
            sp = self.mapToScene(ev.position().toPoint())
            src_node = self._node_items.get(self.pending[0])
            if src_node:
                sx = src_node.node.w if self.pending[1] == "out" else 0
                s = src_node.mapToScene(QPointF(sx, src_node.node.h / 2))
                if self._preview:
                    self._scene.removeItem(self._preview)
                    self._preview = None
                mid = (s.x() + sp.x()) / 2
                path = QPainterPath(s)
                path.cubicTo(QPointF(mid, s.y()), QPointF(mid, sp.y()), sp)
                self._preview = self._scene.addPath(
                    path, QPen(QBrush(QColor(PENDING)), 2, Qt.DashLine))
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if getattr(self, "_panning", False):
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            ev.accept()
            return
        if self.pending:
            sp = self.mapToScene(ev.position().toPoint())
            target = self._port_at_scene(sp)
            a = self.pending
            self.pending = None
            if self._preview:
                self._scene.removeItem(self._preview)
                self._preview = None
            if target and target[0] != a[0]:
                # normalize direction: source(out) → target(in)
                ka = a[0].split(":", 1)[0]
                kb = target[0].split(":", 1)[0]
                if ka == "output" or (ka == "field" and kb == "field"):
                    self.designer.connect(target, a)
                else:
                    self.designer.connect(a, target)
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev) -> None:
        factor = 1.18 if ev.angleDelta().y() > 0 else 1 / 1.18
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        cur = self.transform().m11()
        if 0.25 <= cur * factor <= 3.0:
            self.scale(factor, factor)
        super().wheelEvent(ev)

    def mousePressEvent(self, ev) -> None:
        # middle button or empty-left → manual pan
        if ev.button() == Qt.MiddleButton or (
            ev.button() == Qt.LeftButton and self.itemAt(ev.position().toPoint()) is None
        ):
            self._pan_last = ev.position()
            self._panning = True
            self.setCursor(Qt.ClosedHandCursor)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def keyPressEvent(self, ev) -> None:
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            sel_nodes = [it for it in self._scene.selectedItems() if isinstance(it, NodeItem)]
            if sel_nodes:
                self.designer.delete_node(sel_nodes[0].node.nid)
                return
            sel_wires = [it for it in self._scene.selectedItems() if isinstance(it, WireItem)]
            if sel_wires:
                self.designer.delete_wire(sel_wires[0].wire)
                return
        super().keyPressEvent(ev)

    def select_wire(self, item: WireItem) -> None:
        self._scene.clearSelection()
        item.setSelected(True)
        self.designer.app.show_wire_inspector(item.wire)


class PageFlowEditor(QWidget):
    """Page-centric flow editor — 页面流转:
    选中页面 → 该页控件/数据 → 指派控制（跳转/显示/输入外设）。

    All edits write to the same io.json contract (flows / outputs / inputs /
    fields); nothing is canvas-based.
    """

    def __init__(self, main: "MainWindow") -> None:
        super().__init__()
        self.main = main
        self.d = main.designer
        self.page = ""
        self._loading = False
        self._jump_rows: list[dict] = []
        self._disp_rows: list[dict] = []

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(QLabel("页面（来自 UI 导入）"))
        self.page_list = QListWidget()
        self.page_list.itemSelectionChanged.connect(self._on_page_selected)
        left.addWidget(self.page_list, stretch=1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(180)
        root.addWidget(lw)

        mid = QVBoxLayout()
        mid.addWidget(QLabel("页面预览（滚轮缩放 · 点击控件定位 · 双击复位）"))
        self.preview = PagePreview(self.main)
        sa = QScrollArea()
        sa.setWidget(self.preview)
        sa.setWidgetResizable(False)
        sa.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        mid.addWidget(sa, stretch=1)
        self.preview_info = QLabel("")
        self.preview_info.setObjectName("muted")
        self.preview.info_label = self.preview_info
        mid.addWidget(self.preview_info)
        midw = QWidget()
        midw.setLayout(mid)
        midw.setFixedWidth(380)
        root.addWidget(midw)

        right = QVBoxLayout()
        self.page_title = QLabel("（选择左侧页面）")
        self.page_title.setStyleSheet("font-size:15px; font-weight:bold;")
        right.addWidget(self.page_title)

        jump_box = QGroupBox("页面跳转 — 该页触发什么，携带什么参数，跳到哪一页")
        jv = QVBoxLayout(jump_box)
        self.jump_table = QTableWidget(0, 5)
        self.jump_table.setHorizontalHeaderLabels(
            ["触发控件", "CMD", "目标页面", "参数 (键=值)", "卸载策略"])
        self.jump_table.horizontalHeader().setStretchLastSection(True)
        self.jump_table.verticalHeader().setVisible(False)
        jv.addWidget(self.jump_table)
        jrow = QHBoxLayout()
        for label, fn in (("＋添加跳转", self._add_jump), ("删除所选", self._del_jump)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            jrow.addWidget(b)
        self.jump_src_lbl = QLabel("")
        self.jump_src_lbl.setObjectName("muted")
        jrow.addWidget(self.jump_src_lbl)
        jrow.addStretch(1)
        jv.addLayout(jrow)
        right.addWidget(jump_box)

        disp_box = QGroupBox("数据显示 — 该页哪些控件显示哪个变量")
        dv = QVBoxLayout(disp_box)
        self.disp_table = QTableWidget(0, 2)
        self.disp_table.setHorizontalHeaderLabels(["显示控件 (lbl)", "← 变量"])
        self.disp_table.horizontalHeader().setStretchLastSection(True)
        self.disp_table.verticalHeader().setVisible(False)
        dv.addWidget(self.disp_table)
        drow = QHBoxLayout()
        for label, fn in (("＋添加显示绑定", self._add_disp), ("删除所选", self._del_disp)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            drow.addWidget(b)
        drow.addStretch(1)
        dv.addLayout(drow)
        right.addWidget(disp_box)

        var_box = QGroupBox("变量 (Model) — key=空 为普通变量；填参数键则按入口参数存取 (如 rssi 按 device)")
        vv = QVBoxLayout(var_box)
        self.fields_table = QTableWidget(0, 4)
        self.fields_table.setHorizontalHeaderLabels(["变量名", "类型", "按参数索引 (keyed)", "初值"])
        self.fields_table.horizontalHeader().setStretchLastSection(True)
        self.fields_table.verticalHeader().setVisible(False)
        vv.addWidget(self.fields_table)
        vrow = QHBoxLayout()
        for label, fn in (("＋添加变量", self._add_field), ("删除所选", self._del_field)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            vrow.addWidget(b)
        vrow.addStretch(1)
        vv.addLayout(vrow)
        right.addWidget(var_box)

        io_box = QGroupBox("虚拟外设（全局 — 仿真 I/O 面板按键/旋钮/输入框）")
        iv2 = QVBoxLayout(io_box)
        self.io_table = QTableWidget(0, 4)
        self.io_table.setHorizontalHeaderLabels(["显示名", "类型", "绑定", "ID"])
        self.io_table.horizontalHeader().setStretchLastSection(True)
        self.io_table.verticalHeader().setVisible(False)
        iv2.addWidget(self.io_table)
        irow = QHBoxLayout()
        for label, fn in (
            ("＋添加外设", self._add_input),
            ("＋本页数据输入", self._add_page_input),
            ("删除所选", self._del_input),
        ):
            b = QPushButton(label)
            b.clicked.connect(fn)
            irow.addWidget(b)
        irow.addStretch(1)
        iv2.addLayout(irow)
        right.addWidget(io_box)

        right.addStretch(1)
        rw = QWidget()
        rw.setLayout(right)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(rw)
        root.addWidget(scroll, stretch=1)

    # ---- helpers ----
    def refresh(self) -> None:
        table = self.main.signal_table
        screens = [s.name for s in table.screens] if table else []
        cur = self.page
        self.page_list.blockSignals(True)
        self.page_list.clear()
        self.page_list.addItems(screens)
        if cur in screens:
            self.page_list.setCurrentRow(screens.index(cur))
        elif screens:
            self.page_list.setCurrentRow(0)
        self.page_list.blockSignals(False)
        self._fill_page()

    def _current_page(self) -> str:
        it = self.page_list.currentItem()
        return it.text() if it else ""

    def _screen_key(self, page: str) -> str:
        return page.lower()

    def _btns_of(self, page: str) -> list[str]:
        info = self.d.widget_info.get(self._screen_key(page), {})
        buttons = [n for n, m in info.items() if m.get("cls") == "button"]
        if buttons:
            return buttons
        return [w for w in self.d.widgets.get(self._screen_key(page), [])
                if w.startswith("btn_")]

    def _widget_cls(self, page: str, name: str) -> str:
        return (self.d.widget_info.get(self._screen_key(page)) or {}
                ).get(name, {}).get("cls", "")

    def _display_candidates(self, page: str, ctype: str) -> list[tuple[str, str]]:
        """(widget, 显示文本) — 真实类判定：label 可显示任意值；bar/arc/slider 可显示数值。"""
        info = self.d.widget_info.get(self._screen_key(page), {})
        out = []
        for name, m in info.items():
            cls = m.get("cls", "")
            if cls == "label":
                txt = m.get("text", "")
                ann = f' "{txt[:22]}"' if txt else ""
                out.append((name, f"{name} · 标签{ann}"))
            elif ctype in ("int", "float") and cls in ("bar", "arc", "slider"):
                out.append((name, f"{name} · {cls}控件"))
        return out

    def _fields(self) -> list[str]:
        return [f.get("name", "") for f in self.d.data.get("fields", []) if f.get("name")]

    # ---- selection ----
    def _on_page_selected(self) -> None:
        self._fill_page()

    def _fill_page(self) -> None:
        page = self._current_page()
        self.page = page
        if not page:
            return
        self._loading = True
        self.page_title.setText(f"页面：{page}")
        pv = getattr(self, "preview", None)
        if pv:
            pv.set_screen(page)
        self._fill_jumps(page)
        self._fill_disps(page)
        self._fill_fields()
        self._fill_inputs()
        self._loading = False

    # ---- 页面跳转 ----
    def _flows_for(self, page: str) -> list[dict]:
        return [f for f in self.d.data.get("flows", [])
                if str(f.get("from", "")).upper() == page.upper()]

    def _fill_jumps(self, page: str) -> None:
        flows = self._flows_for(page)
        self._jump_rows = flows
        t = self.jump_table
        t.setRowCount(len(flows))
        table = self.main.signal_table
        screens = [s.name for s in table.screens] if table else []
        btns = self._btns_of(page)
        for r, fl in enumerate(flows):
            widget = str(fl.get("widget", ""))
            if widget and widget not in btns:
                btns = [widget] + btns
            # 触发控件
            c = QComboBox()
            c.addItem(widget or "（未指定）")
            for b2 in btns:
                if b2 != widget:
                    c.addItem(b2)
            c.setCurrentIndex(0)
            c.currentTextChanged.connect(
                lambda w, fl=fl: self._set_jump_widget(fl, w))
            t.setCellWidget(r, 0, c)
            # CMD
            e = QLineEdit(str(fl.get("on", "")))
            e.editingFinished.connect(
                lambda e=e, fl=fl: self._set_jump_cmd(fl, e.text().strip().upper()))
            t.setCellWidget(r, 1, e)
            # 目标页面
            to = QComboBox()
            to.addItem(str(fl.get("to", "")))
            for s in screens:
                if s != fl.get("to"):
                    to.addItem(s)
            to.setCurrentIndex(0)
            to.currentTextChanged.connect(
                lambda s, fl=fl: self._set_jump_to(fl, s))
            t.setCellWidget(r, 2, to)
            # 导航参数（键=值，如 device=A → 复用页面按参数取数）
            pe = QLineEdit(str(fl.get("param", "")))
            pe.setPlaceholderText("device=A")
            pe.editingFinished.connect(
                lambda e2=pe, fl=fl: self._set_jump_param(fl, e2.text().strip()))
            t.setCellWidget(r, 3, pe)
            # 卸载策略
            pol = QComboBox()
            pol.addItems(["DEL", "HIDE"])
            pol.setCurrentText(str(fl.get("policy", "DEL")))
            pol.currentTextChanged.connect(
                lambda p, fl=fl: self._set_jump_pol(fl, p))
            t.setCellWidget(r, 4, pol)
        srcs = sorted({str(f.get("src", "")) for f in flows})
        self.jump_src_lbl.setText(f"来源: {', '.join(srcs) or '-'} · "
                                  "aidogui=导入扫描（重新导入恢复）")
        t.setColumnWidth(0, 110)
        t.setColumnWidth(1, 120)
        t.setColumnWidth(2, 130)
        t.setColumnWidth(3, 110)

    def _set_jump_widget(self, fl: dict, widget: str) -> None:
        if self._loading or widget.startswith("（"):
            return
        fl["widget"] = widget
        self.d.save(f"flow {fl.get('from')}→{fl.get('to')}: widget={widget}")

    def _set_jump_cmd(self, fl: dict, cmd: str) -> None:
        if self._loading:
            return
        fl["on"] = cmd
        self.d.save(f"flow {fl.get('from')}: CMD={cmd}")

    def _set_jump_to(self, fl: dict, to: str) -> None:
        if self._loading:
            return
        fl["to"] = to
        self.d.save(f"flow {fl.get('from')} ──{fl.get('on')}──▶ {to}")

    def _set_jump_pol(self, fl: dict, pol: str) -> None:
        if self._loading:
            return
        fl["policy"] = pol
        self.d.save(f"flow policy={pol}")

    def _set_jump_param(self, fl: dict, param: str) -> None:
        if self._loading:
            return
        param = param.strip()
        if param and "=" not in param:
            QMessageBox.information(self, "参数", "格式：键=值，例如 device=A；留空表示无参数。")
            self._fill_page()
            return
        fl["param"] = param
        self.d.save(f"flow {fl.get('from')} ──{fl.get('on')}──▶ {fl.get('to')} param={param}")

    def _add_jump(self) -> None:
        page = self._current_page()
        if not page:
            return
        btns = self._btns_of(page)
        btn = btns[0] if btns else ""
        cmd = ""
        if btn.startswith("btn_"):
            import re as _re
            cmd = _re.sub(r"[^A-Za-z0-9]+", "_", btn[4:]).upper()
        self.d.data.setdefault("flows", []).append(
            {"from": page.lower(), "on": cmd, "to": "", "policy": "DEL",
             "src": "user", "widget": btn})
        self.d.save(f"add flow {page}")
        self._fill_page()

    def _del_jump(self) -> None:
        r = self.jump_table.currentRow()
        if not (0 <= r < len(self._jump_rows)):
            return
        fl = self._jump_rows[r]
        if fl.get("src") != "user":
            QMessageBox.information(
                self, "事件流", "AIDOGUI 导入扫描生成的跳转不能在此删除"
                                 "（重新导入会恢复）；可修改目标页或策略。")
            return
        try:
            self.d.data.get("flows", []).remove(fl)
        except ValueError:
            pass
        self.d.save("deleted user flow")
        self._fill_page()

    # ---- 数据显示绑定 ----
    def _outputs_for(self, page: str) -> list[dict]:
        return [o for o in self.d.data.get("outputs", [])
                if (o.get("bind") or {}).get("type") == "widget"
                and str((o.get("bind") or {}).get("screen", "")).lower() == page.lower()]

    def _fill_disps(self, page: str) -> None:
        outs = self._outputs_for(page)
        self._disp_rows = outs
        t = self.disp_table
        t.setRowCount(len(outs))
        fields = self._fields()
        for r, o in enumerate(outs):
            b = o.get("bind") or {}
            item = QTableWidgetItem(f"{b.get('widget', '')}")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            t.setItem(r, 0, item)
            c = QComboBox()
            c.addItem(b.get("field", "") or "（未绑定）")
            for f in fields:
                if f != b.get("field"):
                    c.addItem(f)
            c.setCurrentIndex(0)
            c.currentTextChanged.connect(
                lambda f2, o=o: self._set_disp_field(o, f2))
            t.setCellWidget(r, 1, c)

    def _set_disp_field(self, o: dict, field: str) -> None:
        if self._loading or field.startswith("（"):
            return
        (o.get("bind") or {})["field"] = field
        self.d.save(f"display {o.get('id')} ← {field}")

    def _add_disp(self) -> None:
        page = self._current_page()
        if not page:
            return
        fields = self._fields()
        var, ctype = "", ""
        if fields:
            items = fields + ["＋新建变量…"]
            var, ok = QInputDialog.getItem(self, "显示绑定", "绑定到哪个变量？",
                                           items, 0, False)
            if not ok:
                return
        if not var or var.startswith("＋"):
            name, ok = QInputDialog.getText(self, "新建变量", "变量名：")
            if not ok or not name.strip():
                return
            var = io_contract.normalize_name(name)
            ctype, ok2 = QInputDialog.getItem(
                self, "新建变量", "类型：", list(io_contract.CTYPES), 0, False)
            if not ok2:
                return
            self.d.data.setdefault("fields", []).append(
                {"name": var, "ctype": ctype, "init": "" if ctype == "string" else 0})
        else:
            ctype = next((f.get("ctype", "float")
                          for f in self.d.data.get("fields", [])
                          if f.get("name") == var), "float")
        cands = self._display_candidates(page, ctype)
        if not cands:
            QMessageBox.information(
                self, "显示绑定",
                f"页面 {page} 没有匹配的显示控件：\n"
                "字符串/布尔 → 标签(label)；int/float → 标签或 bar/arc/slider 控件。\n"
                "（控件类型由屏幕源码扫描识别，先点「重新生成 MVP」刷新）")
            return
        pre = 0
        sel = self.d.preview_sel
        if sel and sel[0].lower() == page.lower():
            for i, (wname, _lbl) in enumerate(cands):
                if wname == sel[1]:
                    pre = i
                    break
        widget, ok = QInputDialog.getItem(
            self, "显示绑定", f"选择 {page} 的显示控件（预览中点选的已预选）：",
            [c[1] for c in cands], pre, False)
        if not ok:
            return
        widget = next(c[0] for c in cands if c[1] == widget)
        prefix = ""
        if ctype not in ("int", "float") or self._widget_cls(page, widget) == "label":
            prefix, _ = QInputDialog.getText(
                self, "显示绑定", "文本前缀（可空，如 RSSI: ）:")
            prefix = prefix.strip()
        items = self.d.data.setdefault("outputs", [])
        nid = self.d._uniq_id("out", items)
        bind = {"type": "widget", "screen": self._screen_key(page),
                "widget": widget, "field": var}
        if prefix:
            bind["prefix"] = prefix
        items.append({"id": nid, "kind": "widget", "label": nid, "bind": bind})
        self.d.save(f"bind {widget} ← {var}")
        self._fill_page()

    def _del_disp(self) -> None:
        r = self.disp_table.currentRow()
        if not (0 <= r < len(self._disp_rows)):
            return
        o = self._disp_rows[r]
        try:
            self.d.data.get("outputs", []).remove(o)
        except ValueError:
            pass
        self.d.save(f"removed display binding {o.get('id')}")
        self._fill_page()

    # ---- 变量 (Model) ----
    def _fill_fields(self) -> None:
        fields = self.d.data.get("fields", [])
        t = self.fields_table
        t.setRowCount(len(fields))
        for r, f in enumerate(fields):
            e = QLineEdit(str(f.get("name", "")))
            e.editingFinished.connect(
                lambda e2=e, f2=f: self._set_field_name(f2, e2.text().strip()))
            t.setCellWidget(r, 0, e)
            c = QComboBox()
            c.addItems(list(io_contract.CTYPES))
            c.setCurrentText(str(f.get("ctype", "int")))
            c.currentTextChanged.connect(
                lambda ct, f2=f: self._set_field(f2, "ctype", ct))
            t.setCellWidget(r, 1, c)
            ke = QLineEdit(str(f.get("keyed", "")))
            ke.setPlaceholderText("空=普通变量")
            ke.editingFinished.connect(
                lambda e2=ke, f2=f: self._set_field(f2, "keyed",
                                                    io_contract.normalize_name(e2.text()) if e2.text().strip() else ""))
            t.setCellWidget(r, 2, ke)
            ie = QLineEdit(str(f.get("init", 0) if f.get("init", 0) != "" else ""))
            ie.editingFinished.connect(
                lambda e2=ie, f2=f: self._set_field(f2, "init", e2.text().strip()))
            t.setCellWidget(r, 3, ie)

    def _set_field(self, f: dict, key: str, value) -> None:
        if self._loading:
            return
        f[key] = value
        self.d.save(f"field {f.get('name')}: {key}={value}")

    def _set_field_name(self, f: dict, new: str) -> None:
        if self._loading:
            return
        old = f.get("name", "")
        new = io_contract.normalize_name(new)
        if not new or new == old:
            return
        f["name"] = new
        for i in self.d.data.get("inputs", []):
            b = i.get("bind") or {}
            if b.get("name") == old:
                b["name"] = new
        for o in self.d.data.get("outputs", []):
            b = o.get("bind") or {}
            if b.get("name") == old:
                b["name"] = new
            if b.get("field") == old:
                b["field"] = new
        self.d.save(f"field renamed {old} → {new}")
        self._fill_page()

    def _add_field(self) -> None:
        name, ok = QInputDialog.getText(self, "新建变量", "变量名：")
        if not ok or not name.strip():
            return
        ctype, ok2 = QInputDialog.getItem(self, "新建变量", "类型：",
                                          list(io_contract.CTYPES), 0, False)
        if not ok2:
            return
        self.d.data.setdefault("fields", []).append(
            {"name": io_contract.normalize_name(name), "ctype": ctype,
             "init": "" if ctype == "string" else 0})
        self.d.save(f"add field {name}")
        self._fill_fields()

    def _del_field(self) -> None:
        r = self.fields_table.currentRow()
        fields = self.d.data.get("fields", [])
        if not (0 <= r < len(fields)):
            return
        f = fields.pop(r)
        old = f.get("name", "")
        for i in self.d.data.get("inputs", []):
            b = i.get("bind") or {}
            if b.get("type") == "field" and b.get("name") == old:
                i["bind"] = {"type": "none", "name": ""}
        for o in self.d.data.get("outputs", []):
            b = o.get("bind") or {}
            if b.get("field") == old or (b.get("type") == "field" and b.get("name") == old):
                if b.get("type") == "widget":
                    b["field"] = ""
                else:
                    o["bind"] = {"type": "none", "name": ""}
        self.d.save(f"removed field {old}")
        self._fill_page()

    # ---- 虚拟外设 ----
    def _fill_inputs(self) -> None:
        inputs = self.d.data.get("inputs", [])
        t = self.io_table
        t.setRowCount(len(inputs))
        fields = self._fields()
        table = self.main.signal_table
        cmds = [c.name for c in table.commands] if table else []
        for r, inp in enumerate(inputs):
            b = inp.get("bind") or {}
            # 显示名
            e = QLineEdit(str(inp.get("label", "")))
            e.editingFinished.connect(
                lambda e=e, inp=inp: self._set_input(inp, "label", e.text().strip()))
            t.setCellWidget(r, 0, e)
            # 类型
            c = QComboBox()
            c.addItems(list(io_contract.INPUT_KINDS))
            c.setCurrentText(str(inp.get("kind", "button")))
            c.currentTextChanged.connect(
                lambda k, inp=inp: self._set_input(inp, "kind", k))
            t.setCellWidget(r, 1, c)
            # 绑定
            cb = QComboBox()
            bind_vals = ["（未绑定）"] + [f"变量  {f}" for f in fields] + \
                [f"CMD  {x}" for x in cmds]
            cb.addItems(bind_vals)
            cb.setCurrentText(
                {"field": f"变量  {b.get('name', '')}", "cmd": f"CMD  {b.get('name', '')}"
                 }.get(b.get("type"), "（未绑定）"))
            cb.currentTextChanged.connect(
                lambda v, inp=inp: self._set_input_bind(inp, v))
            t.setCellWidget(r, 2, cb)
            item = QTableWidgetItem(str(inp.get("id", "")))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            t.setItem(r, 3, item)

    def _set_input(self, inp: dict, key: str, value: str) -> None:
        if self._loading:
            return
        inp[key] = value
        self.d.save(f"input {inp.get('id')}: {key}={value}")

    def _set_input_bind(self, inp: dict, text: str) -> None:
        if self._loading:
            return
        if text.startswith("变量  "):
            inp["bind"] = {"type": "field", "name": text[3:].strip()}
        elif text.startswith("CMD  "):
            inp["bind"] = {"type": "cmd", "name": text[4:].strip()}
        else:
            inp["bind"] = {"type": "none", "name": ""}
        self.d.save(f"input {inp.get('id')} bind={text}")

    def _add_input(self) -> None:
        items = self.d.data.setdefault("inputs", [])
        nid = self.d._uniq_id("in", items)
        items.append({"id": nid, "kind": "button", "label": nid,
                      "bind": {"type": "none", "name": ""}})
        self.d.save(f"add input {nid}")
        self._fill_inputs()

    def _add_page_input(self) -> None:
        """Quick action: 为当前页面加一个数据输入外设（旋钮/滑条/传感器→变量）."""
        fields = self._fields()
        if fields:
            var, ok = QInputDialog.getItem(self, "本页数据输入", "驱动哪个变量？",
                                           fields, 0, False)
        else:
            var, ok = "", False
        if not ok:
            name, ok = QInputDialog.getText(self, "新建变量", "变量名：")
            if not ok or not name.strip():
                return
            var = io_contract.normalize_name(name)
            ctype, ok3 = QInputDialog.getItem(
                self, "新建变量", "类型：", list(io_contract.CTYPES), 2, False)
            if not ok3:
                return
            self.d.data.setdefault("fields", []).append(
                {"name": var, "ctype": ctype, "init": "" if ctype == "string" else 0})
        kind, ok2 = QInputDialog.getItem(
            self, "本页数据输入", "外设类型：", ("旋钮 knob", "滑条 slider", "传感器 sensor"),
            0, False)
        if not ok2:
            return
        kind = kind.split()[1]
        label, ok4 = QInputDialog.getText(self, "本页数据输入", "显示名（如 温度设定）：")
        if not ok4:
            return
        items = self.d.data.setdefault("inputs", [])
        nid = self.d._uniq_id("in", items)
        items.append({"id": nid, "kind": kind, "label": label.strip() or nid,
                      "bind": {"type": "field", "name": var}})
        self.d.save(f"add page input {nid} → {var}")
        self._fill_inputs()

    def _del_input(self) -> None:
        r = self.io_table.currentRow()
        inputs = self.d.data.get("inputs", [])
        if not (0 <= r < len(inputs)):
            return
        inp = inputs.pop(r)
        self.d.save(f"removed input {inp.get('id')}")
        self._fill_inputs()


class PagePreview(QWidget):
    """Wireframe page preview reconstructed from the scanned layout.
    Click a widget to locate it (feeds the binding dialogs)."""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__()
        self.main = main
        self.page = ""
        self.items: list[dict] = []
        self.selected: str | None = None
        self.sw, self.sh = 320, 280
        self.zoom = 1.0
        self.info_label: QLabel | None = None
        self.setMinimumSize(320, 280)

    def set_screen(self, page: str) -> None:
        self.page = page
        self.selected = None
        self.items = self._layout_items(page)
        self._apply_size()

    def _apply_size(self) -> None:
        self.setFixedSize(int(self.sw * self.zoom) + 8, int(self.sh * self.zoom) + 8)
        self._sync_info()
        self.update()

    def _sync_info(self) -> None:
        if not self.info_label:
            return
        if self.selected:
            it = next((i for i in self.items if i["name"] == self.selected), None)
            if it:
                self.info_label.setText(
                    f"已选: {it['name']} · {it['cls']} \"{it['text'][:26]}\""
                    f"  ·  缩放 {int(self.zoom * 100)}%")
                return
        self.info_label.setText(
            f"{self.page} · 点击控件可选中定位  ·  缩放 {int(self.zoom * 100)}%")

    def _layout_items(self, page: str) -> list[dict]:
        info = self.main.designer.widget_info.get(page.lower(), {})
        if not info:
            return []
        root = info.get("root", {})
        self.sw, self.sh = root.get("w", 320), root.get("h", 280)
        AL = {"DEFAULT": ("TOP", "LEFT"), "TOP_LEFT": ("TOP", "LEFT"),
              "TOP_MID": ("TOP", "MID"), "TOP_RIGHT": ("TOP", "RIGHT"),
              "LEFT_MID": ("MID", "LEFT"), "RIGHT_MID": ("MID", "RIGHT"),
              "BOTTOM_LEFT": ("BOTTOM", "LEFT"), "BOTTOM_MID": ("BOTTOM", "MID"),
              "BOTTOM_RIGHT": ("BOTTOM", "RIGHT"), "CENTER": ("MID", "MID")}
        rects: dict[str, tuple] = {}
        items: list[dict] = []
        round_scr = bool((info.get("root") or {}).get("round"))
        self.round_scr = round_scr
        for name, e in info.items():
            cls = e.get("cls", "obj")
            text = e.get("text", "")
            if name == "root":
                rects[name] = (0, 0, self.sw, self.sh)
                continue
            parent = e.get("parent") or "root"
            px, py, pw, ph = rects.get(parent, (0, 0, self.sw, self.sh))

            def rsz(v, is_w):
                if v is None:
                    if cls == "label":
                        return min(max(6 * len(text) + 10, 30), pw)
                    if cls == "image":
                        # LV_SIZE_CONTENT 图片（如圆表盘）≈ 占满父容器
                        return int(min(pw, ph) * 0.92)
                    return 40
                if isinstance(v, str):
                    if v == "content":
                        if cls == "label":
                            return min(max(6 * len(text) + 10, 30), pw)
                        if cls == "image":
                            return int(min(pw, ph) * 0.92)
                        return 40
                    if v.startswith("pct:"):
                        return int((pw if is_w else ph) * int(v[4:]) / 100)
                return v

            w = rsz(e.get("w"), True)
            h = rsz(e.get("h"), False)
            va, ha = AL.get(e.get("align", "TOP_LEFT") or "TOP_LEFT", ("TOP", "LEFT"))
            x, y = e.get("x", 0), e.get("y", 0)
            ox = x + ((pw - w) // 2 if ha == "MID" else (pw - w if ha == "RIGHT" else 0))
            oy = y + ((ph - h) // 2 if va == "MID" else (ph - h if va == "BOTTOM" else 0))
            rects[name] = (px + ox, py + oy, w, h)
            items.append({"name": name, "cls": cls, "text": text,
                          "rect": rects[name], "parent": parent})
        return items

    def _scale(self) -> tuple[float, float, float]:
        return self.zoom, 4, 4

    def wheelEvent(self, ev) -> None:
        f = 1.2 if ev.angleDelta().y() > 0 else 1 / 1.2
        self.zoom = max(0.5, min(3.0, self.zoom * f))
        self._apply_size()
        ev.accept()

    def mouseDoubleClickEvent(self, ev) -> None:
        self.zoom = 1.0
        self._apply_size()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(CANVAS_BG))
        if not self.items:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "无布局数据 — 点「重新生成 MVP」扫描控件")
            return
        s, ox, oy = self._scale()
        p.translate(ox, oy)
        p.scale(s, s)
        p.setRenderHint(QPainter.Antialiasing)
        if getattr(self, "round_scr", False):
            cpath = QPainterPath()
            cpath.addEllipse(0, 0, self.sw, self.sh)
            p.setClipPath(cpath)
        for it in self.items:
            name, cls, text = it["name"], it["cls"], it["text"]
            x, y, w, h = it["rect"]
            if name == "root":
                p.setPen(QPen(QBrush(QColor(EDGE)), 1))
                p.setBrush(QBrush(QColor("#1b1c22")))
                p.drawRect(x, y, w, h)
                continue
            if cls == "obj":
                p.setBrush(QBrush(QColor("#20212a")))
                p.setPen(QPen(QBrush(QColor(BORDER)), 1))
                p.drawRect(x, y, w, h)
            elif cls == "button":
                p.setBrush(QBrush(QColor("#2f57a8")))
                p.setPen(QPen(QBrush(QColor(EDGE)), 1))
                p.drawRect(x, y, w, h)
            elif cls == "label":
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QBrush(QColor("#3a3c4d")), 1, Qt.DotLine))
                p.drawRect(x, y, w, h)
                p.setPen(QColor(FG))
                p.setFont(QFont("Microsoft YaHei UI", 7))
                p.setClipRect(x, y, w, h)
                p.drawText(QRectF(x + 2, y, w - 4, h), Qt.AlignLeft | Qt.AlignVCenter,
                           text)
                p.setClipping(False)
            else:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QBrush(QColor("#8a90a8")), 1, Qt.DotLine))
                p.drawRect(x, y, w, h)
            if self.selected == name:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QBrush(QColor(PENDING)), 2))
                p.drawRect(x - 2, y - 2, w + 4, h + 4)
            # widget name tag
            p.setPen(QColor("#6f7690"))
            p.setFont(QFont("Consolas", 5))
            p.drawText(QRectF(x, y - 9 / max(s, 0.3), w, 9 / max(s, 0.3)),
                       Qt.AlignLeft, name)

    def mousePressEvent(self, ev) -> None:
        if not self.items:
            return
        s, ox, oy = self._scale()
        x = (ev.position().x() - ox) / s
        y = (ev.position().y() - oy) / s
        hit = None
        for it in reversed(self.items):
            if it["name"] == "root":
                continue
            rx, ry, rw, rh = it["rect"]
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                hit = it["name"]
        if hit:
            self.selected = hit
            self.main.designer.preview_sel = (self.page, hit)
            self._sync_info()
            self.update()


class SimIOPanel(QWidget):
    """Qt I/O side panel for a running sim (CMD/SET/STATE pipe)."""

    def __init__(self, main: "MainWindow", contract: dict) -> None:
        super().__init__(None)
        self.main = main
        self.contract = contract
        self.handle: runner.SimHandle | None = None
        self.bridge = LogBridge()
        self.bridge.line.connect(self._on_line)

        active = main.paths.read_active_project("")
        self.setWindowTitle(f"仿真 I/O — {active}")
        self.resize(460, 680)
        root = QVBoxLayout(self)
        head = QHBoxLayout()
        self.state_lbl = QLabel("sim: starting…")
        head.addWidget(self.state_lbl)
        head.addStretch(1)
        stop = QPushButton("Stop")
        stop.clicked.connect(self._stop)
        head.addWidget(stop)
        root.addLayout(head)

        self.perf_lbl = QLabel("性能: 等待统计…（FPS / 帧耗时 / CPU / LVGL 内存池 / 碎片）")
        self.perf_lbl.setObjectName("muted")
        root.addWidget(self.perf_lbl)

        body = QHBoxLayout()
        in_card = QGroupBox("INPUTS")
        inv = QVBoxLayout(in_card)
        self._build_inputs(inv)
        body.addWidget(in_card, stretch=1)
        out_card = QGroupBox("OUTPUTS (STATE)")
        ov = QVBoxLayout(out_card)
        self.out_text = QPlainTextEdit()
        self.out_text.setReadOnly(True)
        ov.addWidget(self.out_text)
        body.addWidget(out_card, stretch=1)
        root.addLayout(body, stretch=1)

        self.sim_log = QPlainTextEdit()
        self.sim_log.setFixedHeight(140)
        self.sim_log.setReadOnly(True)
        root.addWidget(self.sim_log)

    def _build_inputs(self, v: QVBoxLayout) -> None:
        for inp in self.contract.get("inputs", []):
            kind = inp.get("kind", "button")
            b = inp.get("bind") or {}
            label = inp.get("label") or inp.get("id")
            row = QHBoxLayout()
            if b.get("type") == "cmd":
                btn = QPushButton(f"▸ {label}  (CMD {b.get('name', '')})")
                btn.setObjectName("accent")
                btn.clicked.connect(lambda _=False, n=str(b.get("name", "")):
                                    self._send(f"CMD {n}"))
                row.addWidget(btn)
            elif kind == "switch":
                cb = QCheckBox(label)
                cb.toggled.connect(lambda on, n=str(b.get("name", "")):
                                   self._send(f"SET {n} {1 if on else 0}"))
                row.addWidget(cb)
            else:
                ent = QLineEdit()
                ent.setFixedWidth(110)
                row.addWidget(ent)
                row.addWidget(QLabel(f"← {label} ({b.get('name', '')})"))
                row.addStretch(1)
                set_btn = QPushButton("Set")
                set_btn.clicked.connect(lambda _=False, n=str(b.get("name", "")), e=ent:
                                        self._send(f"SET {n} {e.text().strip()}"))
                row.addWidget(set_btn)
                if kind in ("knob", "slider", "sensor"):
                    pass  # precise entry is primary; sliders omitted for space
            wrap = QWidget()
            wrap.setLayout(row)
            v.addWidget(wrap)
        v.addStretch(1)

    def attach(self, handle: runner.SimHandle) -> None:
        self.handle = handle
        self.state_lbl.setText("sim: running")

    def _send(self, line: str) -> None:
        if self.handle:
            self.handle.send(line)

    def _stop(self) -> None:
        if self.handle:
            self.handle.stop()
            self.handle = None
        self.close()

    def _on_line(self, line: str) -> None:
        self.sim_log.appendPlainText(line)
        if line.startswith("STAT "):
            self._apply_stat(line)
        elif line.startswith("STATE "):
            self.out_text.setPlainText("\n".join(line.split()[1:]))

    def _apply_stat(self, line: str) -> None:
        kv = {}
        for p in line.split()[1:]:
            if "=" in p:
                k, _, v = p.partition("=")
                kv[k] = v
        try:
            mem_used = int(kv.get("mem_used", "0")) / 1024.0
            mem_total = int(kv.get("mem_total", "0")) / 1024.0
            self.perf_lbl.setText(
                f"性能: FPS {kv.get('fps', '-')} · 帧耗时 avg {kv.get('frame_avg', '-')}ms "
                f"/ max {kv.get('frame_max', '-')}ms · CPU {kv.get('cpu', '-')}% · "
                f"LVGL 内存 {mem_used:.1f}/{mem_total:.0f}KB ({kv.get('used_pct', '-')}%) "
                f"· 碎片 {kv.get('frag', '-')}%")
        except ValueError:
            pass


# ============================ main window ===================================

class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self.paths = paths
        self.setWindowTitle("AIDOGUI MVP Workbench")
        self.resize(1240, 800)
        self.signal_table = None
        self.designer = IODesigner(self)
        self._sim_panel: SimIOPanel | None = None
        self._sim_bridge = LogBridge()
        self._sim_bridge.line.connect(self.log_line)

        self.setStyleSheet(QSS)

        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        # ---- Workbench tab ----
        wb = QWidget()
        v = QVBoxLayout(wb)
        proj = QGroupBox("PROJECT / EXPORT")
        pv = QVBoxLayout(proj)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("工程名"))
        self.name_edit = QLineEdit(paths.read_active_project(""))
        self.name_edit.setFixedWidth(220)
        r1.addWidget(self.name_edit)
        r1.addWidget(QLabel("(Import 写入 ui_import/<名> + .active_project)"))
        r1.addStretch(1)
        pv.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("导出目录"))
        self.path_edit = QLineEdit()
        r2.addWidget(self.path_edit, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        r2.addWidget(browse)
        pv.addLayout(r2)
        v.addWidget(proj)

        acts = QGroupBox("ACTIONS")
        av = QHBoxLayout(acts)
        for label, slot, accent in (
            ("Detect Env", self._detect, False),
            ("Import", self._import, False),
            ("Build", self._build, True),
            ("Run Sim", self._run_sim, True),
            ("Run Sim + I/O", self._run_sim_io, True),
            ("Run Script", self._run_script, False),
        ):
            b = QPushButton(label)
            if accent:
                b.setObjectName("accent")
            b.clicked.connect(slot)
            av.addWidget(b)
        av.addStretch(1)
        v.addWidget(acts)

        self.info_lbl = QLabel("Toolchain: checking…")
        self.info_lbl.setObjectName("muted")
        v.addWidget(self.info_lbl)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        v.addWidget(self.log_box, stretch=1)
        tabs.addTab(wb, "Workbench")

        # ---- I/O 页面流转 tab ----
        io_tab = QWidget()
        iv = QVBoxLayout(io_tab)
        io_head = QHBoxLayout()
        self.io_info = QLabel("loading…")
        self.designer.info_var = self.io_info
        io_head.addWidget(self.io_info, stretch=1)
        io_head.addStretch(1)
        regen = QPushButton("重新生成 MVP")
        regen.setObjectName("accent")
        regen.clicked.connect(self._regen_mvp)
        io_head.addWidget(regen)
        build = QPushButton("Build")
        build.setObjectName("accent")
        build.clicked.connect(self._build)
        io_head.addWidget(build)
        simio = QPushButton("Run Sim + I/O")
        simio.setObjectName("accent")
        simio.clicked.connect(self._run_sim_io)
        io_head.addWidget(simio)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.designer.reload)
        io_head.addWidget(refresh)
        iv.addLayout(io_head)

        self.page_flow = PageFlowEditor(self)
        iv.addWidget(self.page_flow, stretch=1)
        tabs.addTab(io_tab, "页面流转")

        # ---- Test Panel tab ----
        tp = QWidget()
        tv = QVBoxLayout(tp)
        self.test_info = QLabel("active=… · mode=…")
        tv.addWidget(self.test_info)
        tr = QHBoxLayout()
        resc = QPushButton("Rescan headers")
        resc.clicked.connect(self._reload_test_panel)
        tr.addWidget(resc)
        wr = QPushButton("Write signals.json")
        wr.clicked.connect(self._write_signals_json)
        tr.addWidget(wr)
        tr.addStretch(1)
        tv.addLayout(tr)

        tgrid = QGridLayout()
        cmd_card = QGroupBox("COMMANDS (APP_CMD)")
        self.cmd_btn_box = QVBoxLayout(cmd_card)
        tgrid.addWidget(cmd_card, 0, 0)
        field_card = QGroupBox("MODEL FIELDS")
        fv = QVBoxLayout(field_card)
        self.fields_box = QPlainTextEdit()
        self.fields_box.setReadOnly(True)
        fv.addWidget(self.fields_box)
        tgrid.addWidget(field_card, 0, 1)
        tv.addLayout(tgrid, stretch=1)

        script_card = QGroupBox("SCRIPT — one CMD per line (e.g. CMD START)")
        sv = QVBoxLayout(script_card)
        self.script_box = QPlainTextEdit()
        sv.addWidget(self.script_box, stretch=1)
        srow = QHBoxLayout()
        for label, slot in (("Clear", self._script_clear),
                            ("Save", self._script_save),
                            ("Run Script", self._script_run)):
            b = QPushButton(label)
            if label == "Run Script":
                b.setObjectName("accent")
            b.clicked.connect(slot)
            srow.addWidget(b)
        srow.addStretch(1)
        sv.addLayout(srow)
        tv.addWidget(script_card, stretch=1)
        tabs.addTab(tp, "Test Panel")

        # status bar
        self.chip = QLabel(" … ")
        self.chip.setObjectName("chipBad")
        sb = QStatusBar()
        sb.addWidget(self.chip)
        self.status_lbl = QLabel("starting…")
        sb.addWidget(self.status_lbl)
        self.setStatusBar(sb)

        self._append(
            f"AppRoot:    {paths.app_root}\nEngine:     {paths.engine_root}\n"
            f"Workbench:  {paths.wb_root}\nToolchain:  {paths.toolchain_root}\n"
        )
        QTimer.singleShot(120, self._refresh_all)

    # ---- shared helpers ----
    def log_line(self, text: str) -> None:
        self.log_box.appendPlainText(str(text).rstrip("\n"))

    def _append(self, text: str) -> None:
        self.log_box.setPlainText(self.log_box.toPlainText() + text)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "AIDOGUI Export UI Files folder")
        if d:
            self.path_edit.setText(d)

    def _refresh_all(self) -> None:
        st = toolchain_status(self.paths)
        ready = bool(st["ready"])
        kind = "bundled" if st["bundled"] else "system/fallback"
        self.chip.setText(f" {'READY' if ready else 'NOT READY'} ")
        self.chip.setObjectName("chipOk" if ready else "chipBad")
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)
        self.info_lbl.setText(f"Toolchain: {'READY' if ready else 'NOT READY'} ({kind}) "
                              f"· root={st['toolchain_root']}")
        active = self.paths.read_active_project("")
        self.status_lbl.setText(
            f"Idle  |  active={active} (MVP)  |  engine={self.paths.engine_root.name}")
        self._reload_test_panel()
        self.designer.reload()
        self.log_line("Qt GUI ready — 滚轮缩放画布，空白拖动平移。")

    def _reload_test_panel(self) -> None:
        active = self.paths.read_active_project("")
        if self.name_edit.text().strip() != active:
            self.name_edit.setText(active)
        self.test_info.setText(f"active={active} · mode=MVP ({active})")
        for w in list(self.cmd_btn_box.children()):
            if isinstance(w, QWidget):
                w.setParent(None)
                w.deleteLater()
        try:
            table = signal_scan.scan_from_paths(self.paths, project_hint=active)
            self.signal_table = table
        except Exception as exc:  # noqa: BLE001
            self.signal_table = None
            self.fields_box.setPlainText(f"scan error: {exc}")
            return
        while self.cmd_btn_box.count():
            item = self.cmd_btn_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        grid = QGridLayout()
        cols = 4
        for i, cmd in enumerate(table.commands):
            b = QPushButton(cmd.name)
            b.clicked.connect(lambda _=False, n=cmd.name: self._append_cmd(n))
            grid.addWidget(b, i // cols, i % cols)
        holder = QWidget()
        holder.setLayout(grid)
        self.cmd_btn_box.addWidget(holder)
        lines = [f"{f.name:16} {f.c_type:24} kind={f.kind}" for f in table.fields]
        lines.append("")
        lines.append("screens: " + ", ".join(s.name for s in table.screens))
        self.fields_box.setPlainText("\n".join(lines))

    def _append_cmd(self, name: str) -> None:
        self.script_box.appendPlainText(f"CMD {name}")

    # ---- actions ----
    def _detect(self) -> None:
        self._start("detect_env")

    def _import(self) -> None:
        src = self.path_edit.text().strip()
        if not src:
            QMessageBox.warning(self, "Import", "Choose an Export UI Files folder.")
            return
        self._start("import_aidogui", [src, self.name_edit.text().strip()])

    def _build(self) -> None:
        self._start("build")

    def _run_sim(self) -> None:
        self._start("run_sim")

    def _run_script(self) -> None:
        self._start("run_script", [str(self.paths.default_csv)])

    def _run_sim_io(self) -> None:
        active = self.paths.read_active_project("")
        if not active:
            QMessageBox.warning(self, "Run Sim", "没有激活工程 — 先 Import。")
            return
        try:
            contract = io_contract.load(self.paths, active)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Run Sim", f"io.json 读取失败: {exc}")
            return
        panel = SimIOPanel(self, contract)
        try:
            handle = runner.start_sim_interactive(
                self.paths, on_line=panel.bridge.emit, on_exit=None)
        except Exception as exc:  # noqa: BLE001
            panel.close()
            QMessageBox.critical(self, "Run Sim", str(exc))
            return
        panel.attach(handle)
        panel.show()
        self._sim_panel = panel
        self.log_line("[sim] interactive sim started — I/O panel open")

    def _start(self, stem: str, args: list[str] | None = None) -> None:
        self.log_line(f"\n--- {stem} ---")
        bridge = LogBridge()
        bridge.line.connect(self.log_line)

        def work() -> None:
            try:
                code = runner.run_script(self.paths, stem, args, log=bridge.emit)
            except Exception as exc:  # noqa: BLE001
                bridge.emit(f"[error] {exc}")
                code = 1
            bridge.emit(f"[exit {code}]")

        threading.Thread(target=work, daemon=True).start()

    def _regen_mvp(self) -> None:
        active = self.paths.read_active_project("")
        if not active:
            QMessageBox.information(self, "I/O", "没有激活工程 — 先 Import。")
            return
        gen_py = self.paths.wb_root / "scripts" / "gen_mvp.py"
        mvp_dir = self.paths.ui_project_dir(active)
        self.log_line(f"\n--- gen_mvp (io contract) {active} ---")

        def work() -> None:
            try:
                proc = subprocess.run(
                    [sys.executable, str(gen_py), str(mvp_dir)],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120,
                )
                out = (proc.stdout or "") + (proc.stderr or "")
                for ln in out.splitlines():
                    self._append_q(ln)
                self._append_q(f"[exit {proc.returncode}]")
            except Exception as exc:  # noqa: BLE001
                self._append_q(f"[gen_mvp] error: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _append_q(self, text: str) -> None:
        QTimer.singleShot(0, lambda: self.log_line(text))

    # ---- inspector ----
    def show_inspector(self, nid: str | None) -> None:
        if not hasattr(self, "ins_layout"):
            return  # inspector dock removed (page-flow editor has its own forms)
        # clear
        while self.ins_layout.count() > 1:
            item = self.ins_layout.takeAt(1)
            w = item.widget()
            if w:
                w.deleteLater()
        if nid is None:
            return
        d = self.designer
        kind, val = nid.split(":", 1)
        entry: dict | None = None
        if kind == "in":
            entry = next((i for i in d.data.get("inputs", []) if i.get("id") == val), None)
        elif kind == "out":
            entry = next((o for o in d.data.get("outputs", []) if o.get("id") == val), None)
        elif kind == "fld":
            entry = next((f for f in d.data.get("fields", []) if f.get("name") == val), None)
        elif kind == "flow":
            flows = d.data.get("flows", [])
            idx = int(val) if val.isdigit() and int(val) < len(flows) else -1
            entry = flows[idx] if idx >= 0 else None

        title = QLabel(f"编辑 {nid}")
        self.ins_layout.addWidget(title)

        if kind == "page":
            flows = [f for f in d.data.get("flows", [])
                     if str(f.get("from", "")).upper() == val.upper()
                     or str(f.get("to", "")).upper() == val.upper()]
            self.ins_layout.addWidget(QLabel(f"来自 UI 导入的屏幕。\n相关事件流 {len(flows)} 条。"))
            self.ins_hint.setText("页面节点可拖动布局；页面本身由 AIDOGUI UI 定义。")
            return
        if entry is None:
            self.ins_hint.setText("条目不存在。")
            return

        cmds, fields, screens = d._targets()
        widget_list = sorted(
            {f"{s}.{w}" for s, ws in d.widgets.items()
             for w in ws if w.startswith(("lbl_", "label_"))})
        form = QFormLayout()
        edits: dict[str, QLineEdit | QComboBox] = {}

        def row(label: str, key: str, values: list[str] | None = None,
                readonly: bool = False):
            if values is None:
                e = QLineEdit()
                e.setReadOnly(readonly)
                e.setText(str(entry.get(key, "")))
            else:
                e = QComboBox()
                e.addItems(values)
                if readonly:
                    e.setEnabled(False)
                cur = str(entry.get(key, ""))
                if cur in values:
                    e.setCurrentText(cur)
            form.addRow(label, e)
            edits[key] = e

        if kind == "in":
            row("ID", "id", readonly=True)
            row("显示名", "label")
            row("类型", "kind", list(io_contract.INPUT_KINDS))
            b = entry.get("bind") or {}
            bind_vals = ["(未绑定)"] + [f"变量  {f}" for f in fields] + \
                [f"CMD  {c}" for c in cmds]
            row("绑定", "bind", bind_vals)
            edits["bind"].setCurrentText(
                {"field": f"变量  {b.get('name', '')}", "cmd": f"CMD  {b.get('name', '')}"
                 }.get(b.get("type"), "(未绑定)"))
        elif kind == "fld":
            row("变量名", "name")
            row("类型", "ctype", list(io_contract.CTYPES))
            row("初值", "init")
        elif kind == "out":
            row("ID", "id", readonly=True)
            row("显示名", "label")
            row("类型", "kind", list(io_contract.OUTPUT_KINDS))
            b = entry.get("bind") or {}
            if b.get("type") == "widget":
                row("屏幕.控件", "widget", widget_list)
                edits["widget"].setCurrentText(
                    f"{b.get('screen', '')}.{b.get('widget', '')}")
                row("来源变量", "field", fields)
                edits["field"].setCurrentText(str(b.get("field", "")))
            else:
                row("来源变量", "name", fields)
                edits["name"].setCurrentText(str(b.get("name", "")))
        else:  # flow
            row("来源页面", "from", screens)
            row("事件 CMD", "on", cmds)
            row("目标页面", "to", screens)
            row("卸载策略", "policy", ["DEL", "HIDE"])

        holder = QWidget()
        holder.setLayout(form)
        self.ins_layout.addWidget(holder)

        def on_ok() -> None:
            def val(k: str) -> str:
                e = edits[k]
                return e.currentText() if isinstance(e, QComboBox) else e.text().strip()

            if kind == "in":
                entry["label"] = val("label") or entry["id"]
                entry["kind"] = val("kind")
                raw = val("bind")
                if raw.startswith("变量  "):
                    entry["bind"] = {"type": "field", "name": raw[3:].strip()}
                elif raw.startswith("CMD  "):
                    entry["bind"] = {"type": "cmd", "name": raw[4:].strip()}
                else:
                    entry["bind"] = {"type": "none", "name": ""}
            elif kind == "fld":
                old = entry.get("name", "")
                new = io_contract.normalize_name(val("name"))
                entry["name"] = new
                entry["ctype"] = val("ctype")
                try:
                    entry["init"] = float(val("init"))
                except ValueError:
                    entry["init"] = 0
                if old != new:
                    for i in d.data.get("inputs", []):
                        bb = i.get("bind") or {}
                        if bb.get("name") == old:
                            bb["name"] = new
                    for o in d.data.get("outputs", []):
                        bb = o.get("bind") or {}
                        if bb.get("name") == old:
                            bb["name"] = new
                        if bb.get("field") == old:
                            bb["field"] = new
            elif kind == "out":
                entry["label"] = val("label") or entry["id"]
                entry["kind"] = val("kind")
                b = entry.get("bind") or {}
                if b.get("type") == "widget":
                    screen, _, widget = val("widget").partition(".")
                    b["screen"], b["widget"] = screen.strip(), widget.strip()
                    b["field"] = val("field")
                else:
                    entry["bind"] = {"type": "field", "name": val("name")}
                    if entry["kind"] == "widget":
                        entry["kind"] = "value"
            else:  # flow
                entry["from"] = val("from")
                entry["on"] = val("on")
                entry["to"] = val("to")
                entry["policy"] = val("policy")
            d.save("edited " + nid)
            d.rebuild_graph()
            self.flow_view.rebuild()

        brow = QHBoxLayout()
        ok_b = QPushButton("应用")
        ok_b.setObjectName("accent")
        ok_b.clicked.connect(on_ok)
        del_b = QPushButton("删除节点")
        del_b.clicked.connect(lambda: d.delete_node(nid))
        brow.addWidget(ok_b)
        brow.addWidget(del_b)
        brow.addStretch(1)
        self.ins_layout.addLayout(brow)
        self.ins_hint.setText("改完点「应用」；契约改动要点「重新生成 MVP」+ Build 才进 C 代码。")

    def show_wire_inspector(self, wire: _Wire) -> None:
        if not hasattr(self, "ins_layout"):
            return
        while self.ins_layout.count() > 1:
            item = self.ins_layout.takeAt(1)
            w = item.widget()
            if w:
                w.deleteLater()
        kind = wire.kind
        if kind == "flow":
            fl = wire.ref or {}
            self.ins_layout.addWidget(QLabel(
                f"事件流  {fl.get('from', '')} ──{fl.get('on', '')}──▶ {fl.get('to', '')}\n"
                f"策略 {fl.get('policy', '')} · 来源 {fl.get('src', '')}"))
            if fl.get("src") == "user":
                idx = next((i for i, f in enumerate(self.designer.data.get("flows", []))
                            if f is fl), -1)
                edit_b = QPushButton("编辑此事件流")
                edit_b.setObjectName("accent")
                edit_b.clicked.connect(
                    lambda: self.show_inspector(f"flow:{idx}" if idx >= 0 else ""))
                self.ins_layout.addWidget(edit_b)
            del_b = QPushButton("删除连线")
            del_b.clicked.connect(lambda: self.designer.delete_wire(wire))
            self.ins_layout.addWidget(del_b)
        else:
            self.ins_layout.addWidget(QLabel(
                "输入→变量 绑定" if kind == "input_bind" else "变量→输出 绑定"))
            del_b = QPushButton("删除连线")
            del_b.clicked.connect(lambda: self.designer.delete_wire(wire))
            self.ins_layout.addWidget(del_b)
        self.ins_hint.setText("")

    # ---- test panel helpers ----
    def _script_clear(self) -> None:
        self.script_box.clear()

    def _manual_script_path(self) -> Path:
        active = self.paths.read_active_project("")
        d = self.paths.test_scripts_dir(active)
        d.mkdir(parents=True, exist_ok=True)
        return d / "manual.txt"

    def _script_save(self) -> None:
        path = self._manual_script_path()
        body = self.script_box.toPlainText()
        path.write_text(body, encoding="utf-8")
        cmds = [ln.strip() for ln in body.splitlines()
                if ln.strip().upper().startswith("CMD ")]
        (path.parent / "commands.txt").write_text(
            "\n".join(cmds) + ("\n" if cmds else ""), encoding="utf-8")
        if self.signal_table:
            signal_scan.write_signals_json(
                self.signal_table, path.parent.parent / "signals.json")
        self.log_line(f"[test] saved {path}")

    def _script_run(self) -> None:
        path = self._script_save()
        self._start("run_script", [str(path)])

    def _write_signals_json(self) -> None:
        active = self.paths.read_active_project("")
        try:
            table = signal_scan.scan_from_paths(self.paths, project_hint=active)
            signal_scan.write_signals_json(table, self.paths.project_slot(active) / "signals.json")
            signal_scan.write_signals_json(
                table, self.paths.mvp_dir(active) / "model_signals.generated.json")
            self.log_line("[test] wrote signals.json")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "signals.json", str(exc))


def run_gui(paths: AppPaths) -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow(paths)
    win.show()
    return app.exec()