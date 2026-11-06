"""python -m desktop_app entry. Absolute import so PyInstaller misuse also works."""
from desktop_app.main import main

raise SystemExit(main())
