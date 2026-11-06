# AIDOGUI MVP Workbench · Desktop App

**主入口**（像 GUI Guider）：安装/解压后打开本桌面 App，界面一点即可 **Import / Build / Run Sim / Run Script**。  
编译与仿真工具链由 App **内置并隔离注入子进程**，**不写、不依赖用户系统 PATH**。

引擎仍是上级 `aidogui_mvp/`（MVP + SDL）。`workbench/scripts/*` 继续被 App 调用；`.bat` 仅作 App 内部或调试后备，**不是**主 UX。

## 本机启动（开发）

```bash
cd /workspace/aidogui_mvp

# 无显示 / CI：路径 + 隔离环境 + detect_env
python3 -m desktop_app --self-check

# GUI（本 box 无 tkinter 时用 venv 里的 PySide6）
desktop_app/.venv/bin/python -m desktop_app
# 或强制 Qt / 仅自检：
desktop_app/.venv/bin/python -m desktop_app --gui qt
```

Windows 开发机（官方 Python 自带 tkinter）：

```bat
cd aidogui_mvp
py -3 -m desktop_app
```

## 目录关系

```
aidogui_mvp/                    ← ENGINE（开发时）
  desktop_app/                  ← 本 App（APP_ROOT）
    main.py / gui_*.py / ...
    packaging/windows.md
  workbench/                    ← WB_ROOT：scripts / toolchain / projects
    scripts/                    ← App 调用的 build/import/run_*
    toolchain/                  ← 内置 MinGW+CMake+SDL（Win）
    projects/
```

打包后（见 `packaging/windows.md`）：

```
AIDOGUI_MVP_Workbench/          ← APP_ROOT = WB_ROOT
  AIDOGUI_MVP_Workbench.exe
  engine/                       ← 引擎树
  scripts/  toolchain/  projects/  tests/
```

## 环境隔离

`env_isolate.build_child_env()` 为 **每个** 编译/仿真子进程构造 `env`：

- 前置 `toolchain/mingw64/bin`、`toolchain/cmake/bin`、`toolchain/sdl2/bin`
- 设置 `SDL2_DIR` / `CMAKE_PREFIX_PATH` /（Win）`LIBRARY_PATH` 等
- **绝不**修改用户机器的系统 PATH 或注册表

Linux 开发机可回落到 `/workspace/tools/cmake`、系统 `gcc`/`libsdl2`，但解析路径仍走同一套 AppRoot/toolchain 逻辑。

## 按钮 ↔ 脚本

| UI | 脚本 |
|----|------|
| Detect Env | `scripts/detect_env.(sh\|bat)` + 状态栏 |
| Import | `scripts/import_aidogui.*` ← Export UI Files 目录 |
| Build | `scripts/build.*` |
| Run Sim | `scripts/run_sim.*` |
| Run Script | `scripts/run_script.*` + `tests/transitions_snake.csv` |

## 打 Windows 包

见 [`packaging/windows.md`](packaging/windows.md)。尚未在本 box 产出 `.exe`；下一步在 Windows 机跑 PyInstaller 并把 `workbench/toolchain` 旁挂进发行目录。
