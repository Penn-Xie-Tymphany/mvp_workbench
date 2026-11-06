# aidogui_mvp

> **主入口：桌面 App**（像 Guider）→ [`desktop_app/`](desktop_app/)；产品定位 [`workbench/PRODUCT.md`](workbench/PRODUCT.md)。  
> 本目录是 MVP + SDL **引擎**；App 调用 `workbench/scripts/` + 内置 `workbench/toolchain/`（子进程隔离 PATH）。


在 AIDOGUI **Export UI Files** 之上补齐 TouchGFX 风格 **MVP**（Model / Presenter / Nav），本机 **SDL** 仿真：

- `sim_sdl`：人类键鼠遍历
- `sim_script`：CSV 自动穷举切页，并断言旧屏按策略清干净

样例 UI：`ui_import/SnakeHandheld/`、`ui_import/ComplexHMI/`（导入后由 gen_mvp 生成工程无关 MVP；业务只改各工程 mvp/ USER 区）。

## 布局

```
aidogui_mvp/
  vendor/lvgl/              # LVGL 9.2.2
  lv_conf.h                 # COLOR_DEPTH=32, LV_USE_SDL=1
  ui_import/<Project>/      # AIDOGUI 导出 + mvp/（gen_mvp 生成）
  app/model|presenter|nav|view
  port/sdl/
  host/main_sdl.c
  host/main_script.c
  tests/transitions.csv
  CMakeLists.txt
```

**不要**把 `app/`、`host/`、`tests/` 放进 AIDOGUI 工程。  
`ui_import/.../custom/custom.c` 为用户维护文件（重导出默认不覆盖），内调 `nav_bootstrap()` + `view_bind()`。

## 卸载策略

| 边 | 策略 |
|----|------|
| 默认离开上一屏 | **DEL**（`ui_*_screen_destroy`，可用 `lv_obj_is_valid` 断言已死） |
| `GAME → PAUSE` | **HIDE**（Game 保持存活） |
| `PAUSE → MENU` | DEL Pause，并额外 DEL 底下的 Game |

正式路径：**只有 `app/nav` 负责 load/unload**。  
`view_bind` 清掉导出按钮上的 CHANGE_SCREEN，改绑 `presenter_dispatch`；每次 `screen_init` 后会再次 `view_bind`。

## 构建（本机已验证）

```bash
export PATH=/workspace/tools/cmake/bin:$PATH
cd /workspace/aidogui_mvp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DLV_CONF_PATH=/workspace/aidogui_mvp/lv_conf.h \
  -DLV_CONF_BUILD_DISABLE_EXAMPLES=ON \
  -DLV_CONF_BUILD_DISABLE_DEMOS=ON \
  -DLV_CONF_BUILD_DISABLE_THORVG_INTERNAL=ON
cmake --build build -j$(nproc)
```

说明：若系统 apt 不可用，CMake/SDL2 头文件可落在 `/workspace/tools/`（见该目录）；链接系统 `libSDL2.so`。

## 运行

人类（有显示器）：

```bash
./build/sim_sdl
# 鼠标点按钮；或按键 S/H/P/R/D/B/Esc/Q
```

脚本（无显示 CI / 本机 headless）：

```bash
SDL_VIDEODRIVER=dummy ./build/sim_script /workspace/aidogui_mvp/tests/transitions.csv
# 或
xvfb-run -a ./build/sim_script /workspace/aidogui_mvp/tests/transitions.csv
```

退出码 **0** = 全部 PASS（当前 CSV：20 条边，含 3 条非法 REJECT）。

## 替换 ui_import

1. AIDOGUI → Export UI Files  
2. 保留/合并 `custom/custom.c`（MVP 入口）  
3. `scripts/import_aidogui <export> [name]` → `ui_import/<name>/` + gen MVP  
4. 重新 build  

画布尺寸需与 `port_sdl`（320×280）一致。

## 阶段 2 缺口

- 真实蛇逻辑与十字键 Model
- 非法边全组合自动生成
- 板级 display / indev
- LVGL Test 金标截图
- 设计器侧事件改为发 Command（减少运行时 neutralize）


## MVP generation (project-agnostic)

```bash
python3 workbench/scripts/gen_mvp.py ui_import/<Project>
```

Import (`scripts/import_aidogui`) copies the AIDOGUI export then runs `gen_mvp.py`.
Edit business logic only in `ui_import/<Project>/mvp/app_model.c` (USER block) and
optional `view_apply.c` / `app_model_user.h`. Workbench `app/runtime/` has no project binding.
