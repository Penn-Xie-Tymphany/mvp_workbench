# AIDOGUI MVP Workbench

[简体中文](#简体中文) | [English](#english)

A desktop workbench that turns **AIDOGUI Designer** exports into real,
MVP-architected LVGL projects: import → simulate → design I/O flows →
auto-generate Model/Presenter code → orchestrate tests → port to hardware.

> The bridge between "what the UI designer exports" and "what runs on your device".

## 简体中文

### 这是什么

AIDOGUI 设计器导出的是"所见即所得"的 LVGL UI 代码：没有架构分层、无法脱离真机测试、
业务与 UI 纠缠。本工作台把它变成一个可仿真的 MVP 工程：

```
AIDOGUI 导出 ──导入──▶ MVP 骨架自动生成 ──▶ SDL2 仿真 ──▶ I/O 编排设计 ──▶ 测试脚本 ──▶ 硬件移植
```

- **导入即架构化**：扫描导出树（屏幕/控件/事件），自动生成 `app_cmd` / `app_model` /
  `app_nav_table` / `app_edges` / `view_bind`；原生交互事件由 MVP 统一接管
  （页面生命周期动效保留给 View）
- **页面流转设计器**：按页面编排"哪个控件触发什么、跳到哪一页（可携带参数）、
  哪个控件显示哪个变量"——设计完自动填充 C 代码
- **仿真 + I/O 面板**：SDL2 窗口 + 虚拟外设面板（按键/旋钮/滑条/传感器），
  通过 stdin/stdout 管道协议（`CMD`/`SET`/`STATE`）驱动与观测
- **测试编排**：仿真面板上的一次点击 = 测试脚本里的一步；同一套事件契约驱动两端
- **性能统计**：FPS / 帧耗时 / LVGL 内存池与碎片率 / 构建产物体积（text/data/bss）
- **移植对称**：Presenter 是稳定边界——PC 端是虚拟外设，硬件端是驱动回调，
  两端消费同一份 I/O 契约（`projects/<工程>/io.json`）

### 快速开始

1. 安装 [Python 3.11+](https://python.org)（勾选 tcl/tk；或装 PySide6 获得完整 UI）
2. 双击 `AIDOGUI_MVP_Workbench.bat`（自动选择 PySide6/Tkinter，不改系统 PATH）
3. Workbench 页 → Browse 选 AIDOGUI "Export UI Files" 目录 → **Import**
4. **Build** → **Run Sim**；「页面流转」页设计 I/O →「重新生成 MVP」→ Build → **Run Sim + I/O**

无 Python 时用 `Tools.bat`（菜单式）；命令行用 `run_cli.bat --self-check`。

### 目录结构

```
desktop_app/        GUI 壳（PySide6 优先 / Tkinter 后备）+ 契约/扫描/运行器
engine/
  app/runtime/      通用 MVP 运行时（工程无关）
  host/ port/       SDL2 仿真器（交互 + 管道协议 + 脚本驱动）
  ui_import/        每工程导入树 + 生成的 mvp/（不入库，见 .gitignore）
scripts/            import_aidogui / gen_mvp / build / run_sim / fetch_lvgl ...
projects/<名>/      io.json 信号契约 + 测试脚本（入库）
toolchain/          内置 MinGW/CMake/SDL2（不入库；解压/自备，见 README_WIN.txt）
engine/vendor/      LVGL 多版本（不入库；scripts/fetch_lvgl.ps1 自动按工程切换）
```

### 工具链

- **LVGL**：`scripts/fetch_lvgl.ps1 -Mode engine`（git 浅克隆；Build 前会按工程
  要求的版本自动切换/补装）
- **MinGW / CMake / SDL2**：放入 `toolchain/`（MinGW-w64 + CMake + SDL2 devel），
  只注入子进程 PATH，不改系统环境；Linux 下用系统 gcc/cmake/SDL2 亦可

详细中文说明见 [README_WIN.txt](README_WIN.txt)。

### 架构约束

- 用户代码保护：`MVP_USER_BEGIN/END` 块重导入不丢失
- 工程隔离：每工程独立 `ui_import/<名>` + `projects/<名>`；工具零预置
- 环境隔离：内置工具链只注入子进程，不写系统 PATH
- 工程切换：改 `.active_project` 后直接 Build（颜色位深/LVGL 版本自动跟随工程）

## English

A workbench that converts **AIDOGUI Designer** LVGL exports into MVP-architected,
simulable, testable projects — and keeps the Presenter boundary stable so the
same orchestration ports to hardware.

See the Chinese section above for the full description; the architecture,
workflow and constraints are identical. Key points:

- Import scans the export tree (screens / widgets / events) and generates the
  MVP skeleton; native interaction events are taken over by the MVP layer while
  screen lifecycle effects stay with the View.
- The page-flow designer edits per-screen bindings (which control triggers what,
  which page it opens — optionally carrying navigation parameters — and which
  widget displays which model variable); C code is generated from that contract.
- The SDL2 simulator pairs with a virtual-peripheral I/O panel over a tiny
  stdin/stdout protocol (`CMD` / `SET` / `STATE`), and the same contract drives
  the scripted test runner.
- Per-project settings (color depth, required LVGL version) are detected from
  the export and applied automatically before each build.

## Status

Work in progress, developed against LVGL 9.3.x on Windows (MinGW-w64 + SDL2).
