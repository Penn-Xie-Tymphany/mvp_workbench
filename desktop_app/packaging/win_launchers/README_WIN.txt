AIDOGUI MVP Workbench — Windows 使用说明
========================================

这是「解压即用」的桌面工作台：内置隔离的 MinGW / CMake / SDL2，
**不会改你的系统 PATH**。工具链只在本软件启动的进程 / 本 cmd 窗口生效。

【解压拼接】
1. 解压 AIDOGUI_MVP_Workbench_app.7z 得到文件夹 AIDOGUI_MVP_Workbench\
2. 若另有 toolchain 大包：解压 AIDOGUI_MVP_Workbench_toolchain.7z，
   把其中的 mingw64\  cmake\  （以及 sdl2\ 若 app 包里没有）
   合并进 AIDOGUI_MVP_Workbench\toolchain\
3. 最终目录应类似：

   AIDOGUI_MVP_Workbench\
     AIDOGUI_MVP_Workbench.bat   ← GUI 启动
     AIDOGUI_MVP_Workbench.exe   ← 可选：本机 build_exe.ps1 产出（须与 _internal\ 同目录）
     _internal\                  ← 可选：PyInstaller 运行时（勿单独挪走 exe）
     Tools.bat                   ← 无 Python 时的菜单后备
     run_cli.bat
     README_WIN.txt
     engine\
     scripts\
     toolchain\  (mingw64, cmake, sdl2, env.bat)
     projects\
     tests\
     desktop_app\
     runtime\    (可选：自备 embeddable Python)

【三步开用】
1. 解压并按上面拼好 toolchain
2. 双击 AIDOGUI_MVP_Workbench.bat
   - 若本机有 Python 3.11+ 且勾选了 tcl/tk → 打开 GUI App
   - 若没有 Python → 会提示；请改双击 Tools.bat
3. 在 GUI（或 Tools 菜单）点 Detect Env → 显示 READY 后 Build → Run Sim

【Tools.bat 菜单】（不需要 Python）
  1 Detect Env
  2 Build
  3 Run Sim
  4 Run Script
  内部会 call toolchain\env.bat，只影响当前窗口 PATH。

【可选：内嵌 Python】
官方 Windows embeddable Python **默认没有 tkinter**，GUI 仍需完整 Python。
若你安装了完整 Python，bat 会自动用 py -3 / python。
也可把 embeddable 解到 runtime\python\ 供 run_cli.bat 做 --self-check。

【可选：真正 EXE】
在本机解压目录执行：
  powershell -NoProfile -ExecutionPolicy Bypass -File desktop_app\packaging\build_exe.ps1
会生成 onedir：AIDOGUI_MVP_Workbench.exe + 同目录 _internal\（必须一起保留，不能只拷 exe）。
bat 仅在两者都在时才优先启动 exe；否则回退 pythonw / Tools.bat。

【不要做】
- 不要手动把 mingw64\bin 加到系统环境变量
- 不要删掉 toolchain\env.bat
- 不要只把 AIDOGUI_MVP_Workbench.exe 挪走而留下 _internal\（会报 Failed to load Python DLL）

问题排查：先跑 Tools.bat → 1 Detect Env，看 gcc/cmake/SDL 是否 OK。

【工程导入】
1. GUI → 工程名填 ComplexHMI（或其它）→ Browse 选 AIDOGUI Export UI Files 目录 → Import
2. Import 写入 engine\ui_import\<名>、.active_project，并生成 mvp/（V/P/Model 骨架）
3. 切换工程后请删除整个 engine\build 再 Build
4. 所有工程统一走 MVP Presenter/Nav（无 Passthrough）

【Test Panel】
GUI 第二页签：扫描当前工程 mvp/app_model.h + app_cmd.h → Commands 追加 "CMD …"
→ Save / Run Script（sim_script 支持 CMD 行或 transitions CSV）；只与 Model 交互。

【办公网】
run_cli.bat --self-check 可忽略；不要对校验脚本单独「另存为测试拷贝」。
公司拦截多半是 powershell/自检脚本特征，与业务无关。

