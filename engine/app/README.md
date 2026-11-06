# MVP application layer

- `runtime/` — **project-agnostic** nav / presenter / view helpers (`mvp_*.c`, public `app_nav.h`, `app_presenter.h`, …).
- Per-project generated sources live in `ui_import/<Project>/mvp/` (created by `workbench/scripts/gen_mvp.py`).

Do **not** put game- or product-specific screens/cmds/score here.
