"""Per-project I/O contract (io.json) — the single source of truth for the
I/O designer tab, the generated model fields / io table, the sim side panel
and the test orchestrator.

Layout::

    projects/<Project>/io.json

Contract v2 shape::

    {
      "version": 2,
      "project": "ComplexHMI",
      "fields":  [ {"name","ctype","init"} ],          # first-class variables
      "inputs":  [ {"id","kind","label","bind":{"type":"cmd|field","name","step"}} ],
      "outputs": [ {"id","kind","label",
                    "bind":{"type":"field|widget|screen",
                            "name"?, "screen"?,"widget"?,"field"?}} ],
      "flows":   [ {"from","on","to","policy","src":"aidogui|user"} ],
      "layout":  { "in:<id>":[x,y], "fld:<name>":[x,y], "out:<id>":[x,y] }
    }

Input kinds : button, switch, knob, slider, sensor
Output kinds: value, bool, screen, widget
Output widget bind: {"type":"widget","screen":S,"widget":W,"field":F}
Flow src    : aidogui (seeded from mvp_meta.json edges) / user (hand-added)
"""

from __future__ import annotations

import json
from pathlib import Path

from .paths import AppPaths

CONTRACT_VERSION = 2
CONTRACT_FILE = "io.json"
LAYOUT_VERSION = 2  # bump invalidates saved node positions (node geometry changed)

INPUT_KINDS = ("button", "switch", "knob", "slider", "sensor")
OUTPUT_KINDS = ("value", "bool", "screen")
CTYPES = ("float", "int", "bool", "string")

DEFAULT_CTYPE = {
    "button": "bool",
    "switch": "bool",
    "knob": "float",
    "slider": "float",
    "sensor": "float",
    "value": "float",
    "bool": "bool",
}


def contract_path(paths: AppPaths, name: str | None = None) -> Path:
    return paths.project_slot(name) / CONTRACT_FILE


def new_contract(project: str) -> dict:
    return {
        "version": CONTRACT_VERSION,
        "project": project,
        "fields": [],
        "inputs": [],
        "outputs": [],
        "flows": [],
        "layout": {},
    }


def _migrate(data: dict) -> dict:
    """v1 → v2: fields / layout sections become first-class."""
    data.setdefault("fields", [])
    if data.get("layout_v") != LAYOUT_VERSION or not isinstance(data.get("layout"), dict):
        data["layout"] = {}  # stale/foreign layout (e.g. Tk-era geometry)
    data["layout_v"] = LAYOUT_VERSION
    for o in data.get("outputs", []):
        b = o.get("bind") or {}
        if b.get("type") == "field" and b.get("ctype"):
            # v1 carried ctype on the bind — move to the fields table
            data.setdefault("fields", []).append(
                {"name": b.get("name", ""), "ctype": b.get("ctype", "float"), "init": 0}
            )
            b.pop("ctype", None)
    data["version"] = CONTRACT_VERSION
    return data


def seed_flows_from_meta(data: dict, mvp_meta: Path) -> int:
    """Fill flows from gen_mvp's mvp_meta.json edges (marked src=aidogui).
    Existing flows (any src) are kept; only missing edges are appended."""
    if not mvp_meta.is_file():
        return 0
    meta = json.loads(mvp_meta.read_text(encoding="utf-8", errors="replace"))
    have = {(f.get("from"), f.get("on"), f.get("to")) for f in data.get("flows", [])}
    btn_of = {}
    for b in meta.get("binds", []):
        btn_of[(str(b.get("screen", "")), str(b.get("cmd", "")))] = str(b.get("btn", ""))
    added = 0
    for e in meta.get("edges", []):
        key = (e.get("from"), e.get("cmd"), e.get("to"))
        if key in have:
            continue
        data.setdefault("flows", []).append(
            {
                "from": e.get("from", ""),
                "on": e.get("cmd", ""),
                "to": e.get("to", ""),
                "policy": e.get("policy", "DEL"),
                "src": "aidogui",
                "widget": btn_of.get((str(e.get("from", "")), str(e.get("cmd", ""))), ""),
            }
        )
        have.add(key)
        added += 1
    return added


def load(paths: AppPaths, name: str | None = None, *, seed: bool = True) -> dict:
    """Load the contract, creating a seeded one if missing (not saved yet)."""
    project = name or paths.read_active_project("")
    path = contract_path(paths, project or "project")
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        data.setdefault("version", CONTRACT_VERSION)
        data.setdefault("project", project)
        for k in ("inputs", "outputs", "flows", "fields"):
            data.setdefault(k, [])
        data = _migrate(data)
    else:
        data = new_contract(project)
    if seed and project:
        seed_flows_from_meta(data, paths.mvp_dir(project) / "mvp_meta.json")
    return data


def save(paths: AppPaths, name: str | None, data: dict) -> Path:
    path = contract_path(paths, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["version"] = CONTRACT_VERSION
    data["layout_v"] = LAYOUT_VERSION
    if name:
        data["project"] = name
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def normalize_name(s: str) -> str:
    """Free text → C-ish identifier fragment (sanitize to [A-Za-z0-9_])."""
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in s.strip())
    return out.strip("_") or "sig"


def input_cmds(data: dict) -> list[str]:
    """CMD names referenced by input binds + user flows (for app_cmd.h merge)."""
    out: list[str] = []
    for src in (
        (inp.get("bind") or {} for inp in data.get("inputs", [])),
        (f for f in data.get("flows", [])),
    ):
        for item in src:
            if item.get("type") == "cmd":
                name = normalize_name(str(item.get("name", ""))).upper()
            elif "on" in item:
                name = normalize_name(str(item.get("on", ""))).upper()
            else:
                continue
            if name and name not in out:
                out.append(name)
    return out


def field_binds(data: dict) -> list[dict]:
    """Unique field bindings (inputs + outputs) → [{name, ctype, rw}].
    rw: 'rw' if driven by an input, 'ro' if only displayed."""
    out: list[dict] = []
    seen: set[str] = set()

    def _add(name: str, ctype: str, rw: str) -> None:
        name = normalize_name(name)
        if name in seen:
            if rw == "rw":
                for e in out:
                    if e["name"] == name:
                        e["rw"] = "rw"
            return
        seen.add(name)
        out.append({"name": name, "ctype": ctype or "float", "rw": rw})

    for f in data.get("fields", []):
        _add(f.get("name", ""), f.get("ctype", "float"), "decl")
    for f in data.get("fields", []):
        _add(f.get("name", ""), f.get("ctype", "float"), "decl")
    for inp in data.get("inputs", []):
        b = inp.get("bind") or {}
        if b.get("type") == "field":
            _add(
                str(b.get("name", "")),
                str(b.get("ctype") or DEFAULT_CTYPE.get(inp.get("kind", ""), "float")),
                "rw",
            )
    for o in data.get("outputs", []):
        b = o.get("bind") or {}
        if b.get("type") == "field":
            _add(
                str(b.get("name", "")),
                str(b.get("ctype") or DEFAULT_CTYPE.get(o.get("kind", ""), "float")),
                "ro",
            )
    return out


def user_flows(data: dict) -> list[dict]:
    return [f for f in data.get("flows", []) if f.get("src") == "user"]