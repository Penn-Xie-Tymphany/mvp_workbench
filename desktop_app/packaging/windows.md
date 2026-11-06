# Windows 打包规划 · AIDOGUI MVP Workbench

目标：用户得到 **像 Guider 的桌面 App**——解压后双击启动，内置 MinGW+CMake+SDL，
界面 Import / Build / Run（或 `Tools.bat` 菜单），**不用改系统 PATH**。

## Win 路径 → CMake（必读）

传给 CMake / MinGW make / ld 的路径**必须用正斜杠** `/`。
反斜杠会被当成转义，链接阶段出现：

`cannot find W:AIDOGUI...toolchainsdl2/lib/libSDL2.dll.a`

已在 `CMakeLists.txt`（`file(TO_CMAKE_PATH)`）、`build.ps1`、`env.bat`、
`env_isolate.cmake_path()` 统一处理。详见 `workbench/docs/WIN_CMAKE_PATHS.md`。

## 实际发行布局（APP_ROOT）

```
AIDOGUI_MVP_Workbench/                 ← 解压根 = APP_ROOT = WB_ROOT
  AIDOGUI_MVP_Workbench.exe            ← 可选：Win 上 build_exe.ps1（onedir）
  _internal/                           ← 可选：必须与 .exe 同目录（Python DLL）
  AIDOGUI_MVP_Workbench.bat            ← GUI 启动（exe+_internal → pythonw → VBS）
  Tools.bat                            ← 无 Python/tk 时的菜单后备
  run_cli.bat
  README_WIN.txt
  engine/
  scripts/
  toolchain/   mingw64/  cmake/  sdl2/  env.bat
  desktop_app/
  runtime/python/                      ← 可选 embeddable（通常无 tk）
```

## 打成真正的 EXE（在用户 Windows 上）

本 Linux box **不产出**可信的 Windows GUI exe。请在 Win 解压目录执行：

```powershell
cd W:\AIDOGUI_MVP_Workbench
powershell -NoProfile -ExecutionPolicy Bypass -File desktop_app\packaging\build_exe.ps1
```

脚本会：`pip install pyinstaller` → windowed **onedir** → 用 robocopy 把
`_pyi_dist\AIDOGUI_MVP_Workbench\` 整树同步到 APP_ROOT（**exe + `_internal\`**）。
**勿只拷走 .exe**，否则报 `Failed to load Python DLL ... _internal\python3xx.dll`。
之后双击 bat 或 exe 即可（无黑框）；bat 仅在 exe 与 `_internal\` 同在时才优先 exe。

需要：本机 Python 3.11+ 且安装时勾选 **tcl/tk**。

## 本 box 装配（Linux）

```bash
bash desktop_app/packaging/assemble_dist.sh
```

## 启动器行为

- **不写用户 PATH**。隔离：`env_isolate.build_child_env` / `toolchain\env.bat`
- bat 仅当 `.exe` **与** `_internal\` 同目录时优先启动 exe，否则 `pythonw` / VBS 隐窗
- GUI 已做卡片分区 + READY/FAIL 色块（`gui_tk.py`）

## 自检（box）

```bash
export AIDOGUI_APP_ROOT=/workspace/aidogui_mvp/dist/AIDOGUI_MVP_Workbench
export AIDOGUI_WB_ROOT=$AIDOGUI_APP_ROOT
export AIDOGUI_ENGINE_ROOT=$AIDOGUI_APP_ROOT/engine
export PYTHONPATH=$AIDOGUI_APP_ROOT
python3 -m desktop_app --self-check
python3 desktop_app/tests/test_cmake_path.py
```

## 检查清单

- [x] SDL 链接路径正斜杠修复
- [x] GUI 美化（卡片 / 主次按钮 / 状态色块）
- [x] `build_exe.ps1` onedir 整树发布（exe + `_internal`）+ 文档
- [x] bat 仅 exe+_internal 时优先 / 否则 pythonw / VBS
- [ ] 真实 Windows 冒烟（Detect → Build → Run）
- [ ] 预编译 exe 随包（需 Win 机跑一次 build_exe.ps1 后回传）
