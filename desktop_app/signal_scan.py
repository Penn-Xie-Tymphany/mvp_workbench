"""Scan project MVP headers / mvp_meta.json → signal table (cmds / fields / screens).

Lightweight regex parse — no clang. Used by Test Panel and optional JSON export.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


_ENUM_BODY = re.compile(
    r"typedef\s+enum\s*\{(?P<body>.*?)\}\s*(?P<name>\w+)\s*;",
    re.DOTALL,
)
_STRUCT_BODY = re.compile(
    r"typedef\s+struct\s*\{(?P<body>.*?)\}\s*(?P<name>\w+)\s*;",
    re.DOTALL,
)
_ENUM_ITEM = re.compile(r"\b([A-Z][A-Z0-9_]*)\b\s*(?:=\s*[^,}/]+)?")
_FIELD = re.compile(r"^\s*([A-Za-z_][\w\s\*]*?)\s+([A-Za-z_]\w*)\s*;", re.MULTILINE)


@dataclass
class SignalCommand:
    name: str
    enum: str


@dataclass
class SignalField:
    name: str
    c_type: str
    kind: str


@dataclass
class SignalScreen:
    name: str
    enum: str


@dataclass
class SignalTable:
    project_hint: str = ""
    commands: list[SignalCommand] = field(default_factory=list)
    fields: list[SignalField] = field(default_factory=list)
    screens: list[SignalScreen] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "project_hint": self.project_hint,
            "commands": [asdict(c) for c in self.commands],
            "fields": [asdict(f) for f in self.fields],
            "screens": [asdict(s) for s in self.screens],
            "sources": dict(self.sources),
        }


def _strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    return text


def _classify_c_type(c_type: str) -> str:
    t = " ".join(c_type.replace("*", " * ").split())
    low = t.lower()
    if low == "bool" or low == "_bool":
        return "bool"
    if any(
        x in low
        for x in (
            "int", "uint", "short", "long", "size_t",
            "int8", "int16", "int32", "int64",
            "uint8", "uint16", "uint32", "uint64",
        )
    ):
        return "int"
    if low.endswith("_t") or low.startswith("app_") or "enum" in low:
        return "enum"
    return "other"


def _parse_enum_items(body: str, prefix: str, skip_suffixes: Iterable[str]) -> list[tuple[str, str]]:
    skip = {f"{prefix}{s}" for s in skip_suffixes}
    skip |= {prefix + "NONE", prefix + "COUNT"}
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _ENUM_ITEM.finditer(body):
        enum = m.group(1)
        if not enum.startswith(prefix):
            continue
        if enum in skip or enum in seen:
            continue
        seen.add(enum)
        short = enum[len(prefix) :]
        if short in ("NONE", "COUNT"):
            continue
        out.append((short, enum))
    return out


def scan_cmd_header(text: str) -> list[SignalCommand]:
    text = _strip_c_comments(text)
    cmds: list[SignalCommand] = []
    for m in _ENUM_BODY.finditer(text):
        if m.group("name") != "app_cmd_t":
            continue
        for short, enum in _parse_enum_items(m.group("body"), "APP_CMD_", ("NONE", "COUNT")):
            cmds.append(SignalCommand(name=short, enum=enum))
    return cmds


def scan_model_header(text: str) -> tuple[list[SignalScreen], list[SignalField]]:
    text = _strip_c_comments(text)
    screens: list[SignalScreen] = []
    fields: list[SignalField] = []
    for m in _ENUM_BODY.finditer(text):
        if m.group("name") != "app_screen_id_t":
            continue
        for short, enum in _parse_enum_items(
            m.group("body"), "APP_SCREEN_", ("NONE", "COUNT")
        ):
            screens.append(SignalScreen(name=short, enum=enum))
    for m in _STRUCT_BODY.finditer(text):
        if m.group("name") != "app_model_t":
            continue
        body = m.group("body")
        # Drop preprocessor lines inside struct before field scan
        body = re.sub(r"^\s*#.*$", "", body, flags=re.MULTILINE)
        for fm in _FIELD.finditer(body):
            c_type = " ".join(fm.group(1).split())
            name = fm.group(2)
            fields.append(
                SignalField(name=name, c_type=c_type, kind=_classify_c_type(c_type))
            )
    return screens, fields


def scan_user_fields(text: str) -> list[SignalField]:
    """Parse bare field declarations from app_model_user.h (included inside struct)."""
    text = _strip_c_comments(text)
    text = re.sub(r"^\s*#.*$", "", text, flags=re.MULTILINE)
    fields: list[SignalField] = []
    for fm in _FIELD.finditer(text):
        c_type = " ".join(fm.group(1).split())
        name = fm.group(2)
        fields.append(SignalField(name=name, c_type=c_type, kind=_classify_c_type(c_type)))
    return fields


def scan_headers(
    model_h: Path | str,
    cmd_h: Path | str,
    *,
    project_hint: str = "",
    user_h: Path | str | None = None,
) -> SignalTable:
    model_path = Path(model_h)
    cmd_path = Path(cmd_h)
    model_txt = model_path.read_text(encoding="utf-8", errors="replace")
    cmd_txt = cmd_path.read_text(encoding="utf-8", errors="replace")
    screens, fields = scan_model_header(model_txt)
    commands = scan_cmd_header(cmd_txt)
    sources = {"app_model.h": str(model_path), "app_cmd.h": str(cmd_path)}
    if user_h and Path(user_h).is_file():
        uf = scan_user_fields(Path(user_h).read_text(encoding="utf-8", errors="replace"))
        existing = {f.name for f in fields}
        for f in uf:
            if f.name not in existing:
                fields.append(f)
        sources["app_model_user.h"] = str(Path(user_h))
    return SignalTable(
        project_hint=project_hint,
        commands=commands,
        fields=fields,
        screens=screens,
        sources=sources,
    )


def scan_mvp_dir(mvp_dir: Path | str, *, project_hint: str = "") -> SignalTable:
    mvp = Path(mvp_dir)
    meta = mvp / "mvp_meta.json"
    model_h = mvp / "app_model.h"
    cmd_h = mvp / "app_cmd.h"
    user_h = mvp / "app_model_user.h"
    if model_h.is_file() and cmd_h.is_file():
        return scan_headers(
            model_h, cmd_h, project_hint=project_hint or mvp.parent.name, user_h=user_h
        )
    if meta.is_file():
        data = json.loads(meta.read_text(encoding="utf-8"))
        table = SignalTable(project_hint=data.get("project", project_hint))
        for c in data.get("commands", []):
            table.commands.append(SignalCommand(name=c, enum=f"APP_CMD_{c}"))
        for s in data.get("screens", []):
            table.screens.append(SignalScreen(name=s.upper(), enum=f"APP_SCREEN_{s.upper()}"))
        table.fields.append(SignalField(name="screen", c_type="app_screen_id_t", kind="enum"))
        table.sources["mvp_meta.json"] = str(meta)
        return table
    raise FileNotFoundError(f"no MVP headers or meta in {mvp}")


def write_signals_json(table: SignalTable, dest: Path | str) -> Path:
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(table.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def scan_from_paths(paths, *, project_hint: str | None = None) -> SignalTable:
    hint = project_hint or paths.read_active_project("")
    mvp = paths.mvp_dir(hint) if hint else None
    if mvp and mvp.is_dir():
        return scan_mvp_dir(mvp, project_hint=hint)
    return scan_headers(
        paths.model_header,
        paths.cmd_header,
        project_hint=hint,
        user_h=paths.mvp_dir(hint) / "app_model_user.h" if hint else None,
    )


def _self_test(repo_engine: Path) -> None:
    snake = repo_engine / "ui_import" / "SnakeHandheld" / "mvp"
    table = scan_mvp_dir(snake, project_hint="SnakeHandheld")
    cmd_names = {c.name for c in table.commands}
    field_names = {f.name for f in table.fields}
    screen_names = {s.name for s in table.screens}
    assert "START" in cmd_names, cmd_names
    assert "HELP" in cmd_names, cmd_names
    assert "PAUSE" in cmd_names, cmd_names
    assert "score" in field_names, field_names
    assert "paused" in field_names, field_names
    assert "screen" in field_names, field_names
    assert "MENU" in screen_names, screen_names
    assert "GAME" in screen_names, screen_names
    hmi = repo_engine / "ui_import" / "ComplexHMI" / "mvp"
    t2 = scan_mvp_dir(hmi, project_hint="ComplexHMI")
    assert "HOME" in {s.name for s in t2.screens} or "home".upper() in {s.name for s in t2.screens}
    assert any(c.name == "DASHBOARD" for c in t2.commands), [c.name for c in t2.commands]
    print(
        f"OK signal_scan snake cmds={sorted(cmd_names)} fields={sorted(field_names)} "
        f"hmi cmds={len(t2.commands)} screens={len(t2.screens)}"
    )


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parents[1]
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        _self_test(root)
        raise SystemExit(0)
    active_f = root / "ui_import" / ".active_project"
    if not active_f.is_file():
        raise SystemExit("missing ui_import/.active_project — Import a project first")
    active = active_f.read_text().strip()
    if not active:
        raise SystemExit("ui_import/.active_project is empty")
    mvp = root / "ui_import" / active / "mvp"
    table = scan_mvp_dir(mvp, project_hint=active)
    out = mvp / "model_signals.generated.json"
    write_signals_json(table, out)
    print(f"wrote {out} ({len(table.commands)} cmds, {len(table.fields)} fields)")
