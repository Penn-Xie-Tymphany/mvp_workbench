"""Header scan must see APP_CMD_START / score / etc."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop_app.signal_scan import scan_headers, write_signals_json  # noqa: E402


def test_scan_snake_headers() -> None:
    table = scan_headers(
        ROOT / "app" / "model" / "app_model.h",
        ROOT / "app" / "presenter" / "app_cmd.h",
    )
    names = {c.name for c in table.commands}
    enums = {c.enum for c in table.commands}
    fields = {f.name: f.kind for f in table.fields}
    screens = {s.name for s in table.screens}
    assert "START" in names and "APP_CMD_START" in enums
    assert "HELP" in names
    assert "HOME" in names
    assert "NONE" not in names and "COUNT" not in names
    assert fields.get("score") == "int"
    assert fields.get("paused") == "bool"
    assert fields.get("screen") == "enum"
    assert "MENU" in screens and "GAME" in screens
    out = ROOT / "app" / "model_signals.generated.json"
    write_signals_json(table, out)
    assert out.is_file() and "START" in out.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_scan_snake_headers()
    print("OK: test_signal_scan passed")
