cmake_minimum_required(VERSION 3.16)
project(aidogui_mvp C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

set(MVP_ROOT ${CMAKE_CURRENT_SOURCE_DIR})

# Active UI project: ui_import/.active_project (written by import_aidogui / gen_mvp).
# No hard-coded project name — missing active file → FATAL. Override: -DUI_PROJECT=<name>.
set(_ACTIVE_PROJECT_FILE "${MVP_ROOT}/ui_import/.active_project")
set(_UI_PROJECT_DEFAULT "")
if(EXISTS "${_ACTIVE_PROJECT_FILE}")
  file(STRINGS "${_ACTIVE_PROJECT_FILE}" _ACTIVE_LINES)
  if(_ACTIVE_LINES)
    list(GET _ACTIVE_LINES 0 _ACTIVE_LINE)
    string(STRIP "${_ACTIVE_LINE}" _ACTIVE_LINE)
    if(NOT _ACTIVE_LINE STREQUAL "")
      set(_UI_PROJECT_DEFAULT "${_ACTIVE_LINE}")
    endif()
  endif()
endif()
if(_UI_PROJECT_DEFAULT STREQUAL "")
  message(FATAL_ERROR
    "No active UI project.\n"
    "  Create ui_import/.active_project (one line: project dir name)\n"
    "  or: scripts/import_aidogui <export_dir> <project_name>\n"
    "  or: cmake -DUI_PROJECT=<name> ...")
endif()
# .active_project is the single source of truth: FORCE the cache so switching
# projects only needs a re-configure (scripts/build.bat) — no build-dir wipe.
set(UI_PROJECT "${_UI_PROJECT_DEFAULT}" CACHE STRING "AIDOGUI UI project under ui_import/" FORCE)
set(UI_DIR "${MVP_ROOT}/ui_import/${UI_PROJECT}")
if(NOT EXISTS "${UI_DIR}/CMakeLists.txt")
  message(FATAL_ERROR
    "UI project '${UI_PROJECT}' not found at:\n"
    "  ${UI_DIR}\n"
    "Import an AIDOGUI Export first:\n"
    "  scripts/import_aidogui <export_dir> <project_name>\n"
    "Switching projects: just edit ui_import/.active_project and re-run build.")
endif()
message(STATUS "UI_PROJECT: ${UI_PROJECT}")
message(STATUS "UI_DIR: ${UI_DIR}")

set(LVGL_DIR ${MVP_ROOT}/vendor/lvgl)

# ---------------------------------------------------------------------------
# SDL2 resolution (do not break Linux box paths)
# Priority:
#   1) -DSDL2_DIR=... or ENV{SDL2_DIR}  → workbench/toolchain/sdl2 (Win flattened)
#   2) ../tools/sdl2                    → Linux staged headers/libs
#   3) /tmp/sdl2dev or system libSDL2
#
# WIN PATH NOTE: always file(TO_CMAKE_PATH) before writing linker args.
# MinGW Makefiles / ld treat backslashes as escapes, so
#   W:\foo\bar\lib\libSDL2.dll.a  →  W:foofooliblibSDL2.dll.a
# ---------------------------------------------------------------------------
if(NOT SDL2_DIR AND DEFINED ENV{SDL2_DIR})
  set(SDL2_DIR "$ENV{SDL2_DIR}")
endif()

# Normalize any Windows backslashes early (no-op on already-cmake paths / Unix).
if(SDL2_DIR)
  file(TO_CMAKE_PATH "${SDL2_DIR}" SDL2_DIR)
endif()

set(SDL2_INC_ARCH "")
set(SDL2_EXTRA_LIBS "")

if(SDL2_DIR AND EXISTS "${SDL2_DIR}/include/SDL2/SDL.h")
  set(SDL2_INC_BASE "${SDL2_DIR}/include")
  if(NOT SDL2_LIBRARY)
    if(EXISTS "${SDL2_DIR}/lib/libSDL2.dll.a")
      set(SDL2_LIBRARY "${SDL2_DIR}/lib/libSDL2.dll.a")
    elseif(EXISTS "${SDL2_DIR}/lib/libSDL2.so")
      set(SDL2_LIBRARY "${SDL2_DIR}/lib/libSDL2.so")
    elseif(EXISTS "${SDL2_DIR}/lib/libSDL2.a")
      set(SDL2_LIBRARY "${SDL2_DIR}/lib/libSDL2.a")
    else()
      message(FATAL_ERROR "SDL2_DIR=${SDL2_DIR} has headers but no libSDL2*.a/.so")
    endif()
  endif()
  # Win MinGW: keep console main; LVGL sets SDL_MAIN_HANDLED in its SDL driver.
else()
  set(SDL2_INC_BASE "${MVP_ROOT}/../tools/sdl2/include")
  set(SDL2_INC_ARCH "${SDL2_INC_BASE}/x86_64-linux-gnu")
  if(NOT EXISTS "${SDL2_INC_BASE}/SDL2/SDL.h")
    set(SDL2_INC_BASE "/tmp/sdl2dev/usr/include")
    set(SDL2_INC_ARCH "/tmp/sdl2dev/usr/include/x86_64-linux-gnu")
  endif()
  if(NOT SDL2_LIBRARY)
    set(SDL2_LIBRARY "${MVP_ROOT}/../tools/sdl2/lib/libSDL2.so")
    if(NOT EXISTS "${SDL2_LIBRARY}")
      set(SDL2_LIBRARY "/usr/lib/x86_64-linux-gnu/libSDL2-2.0.so.0")
    endif()
  endif()
endif()

# Hard requirement: linker path must be cmake-style (forward slashes).
if(SDL2_LIBRARY)
  file(TO_CMAKE_PATH "${SDL2_LIBRARY}" SDL2_LIBRARY)
endif()

message(STATUS "SDL2_DIR (if any): ${SDL2_DIR}")
message(STATUS "SDL2 include base: ${SDL2_INC_BASE}")
message(STATUS "SDL2 include arch: ${SDL2_INC_ARCH}")
message(STATUS "SDL2 library: ${SDL2_LIBRARY}")

set(LV_CONF_PATH "${MVP_ROOT}/lv_conf.h" CACHE STRING "" FORCE)
add_subdirectory(${LVGL_DIR} lvgl_build)

set(_SDL2_INCLUDES ${SDL2_INC_BASE})
if(SDL2_INC_ARCH)
  list(APPEND _SDL2_INCLUDES ${SDL2_INC_ARCH})
endif()

target_include_directories(lvgl PUBLIC
  ${MVP_ROOT}
  ${_SDL2_INCLUDES}
)
target_compile_definitions(lvgl PUBLIC LV_CONF_INCLUDE_SIMPLE)
target_compile_definitions(lvgl PUBLIC SDL_MAIN_HANDLED)
if(WIN32 OR MINGW)
  target_link_libraries(lvgl PUBLIC ${SDL2_LIBRARY})
else()
  target_link_libraries(lvgl PUBLIC ${SDL2_LIBRARY} m pthread)
endif()

# Project-agnostic MVP: runtime + per-project generated mvp/ sources.
set(MVP_DIR "${UI_DIR}/mvp")
if(NOT EXISTS "${MVP_DIR}/app_model.h")
  message(FATAL_ERROR
    "MVP sources missing at:\n  ${MVP_DIR}\n"
    "Run: python3 workbench/scripts/gen_mvp.py ${UI_DIR}\n"
    "Or re-import via scripts/import_aidogui.")
endif()
message(STATUS "MVP mode: project-agnostic (runtime + ${UI_PROJECT}/mvp)")

add_subdirectory(${UI_DIR} ui_build)
target_include_directories(ui PUBLIC
  ${MVP_ROOT}
  ${LVGL_DIR}
  ${_SDL2_INCLUDES}
  ${MVP_ROOT}/app/runtime
  ${MVP_DIR}
  ${UI_DIR}
)
# Runtime (generic) + generated per-project MVP sources
file(GLOB _MVP_PROJ_SOURCES CONFIGURE_DEPENDS "${MVP_DIR}/*.c")
target_sources(ui PRIVATE
  ${MVP_ROOT}/app/runtime/mvp_nav.c
  ${MVP_ROOT}/app/runtime/mvp_presenter.c
  ${MVP_ROOT}/app/runtime/mvp_view.c
  ${_MVP_PROJ_SOURCES}
)
target_link_libraries(ui PUBLIC lvgl)

set(MVP_COMMON_SOURCES ${MVP_ROOT}/port/sdl/port_sdl.c)

function(add_sim target_name main_src)
  add_executable(${target_name} ${main_src} ${MVP_COMMON_SOURCES})
  target_include_directories(${target_name} PRIVATE
    ${MVP_ROOT}
    ${MVP_ROOT}/port/sdl
    ${MVP_ROOT}/host
    ${MVP_ROOT}/app/runtime
    ${MVP_DIR}
    ${UI_DIR}
    ${LVGL_DIR}
    ${_SDL2_INCLUDES}
  )
  target_link_libraries(${target_name} PRIVATE ui lvgl ${SDL2_LIBRARY})
  # We provide int main(); never let SDL rename it / never require WinMain.
  target_compile_definitions(${target_name} PRIVATE SDL_MAIN_HANDLED)
  if(WIN32 OR MINGW)
    # Force console subsystem (avoid crtexewin → WinMain).
    set_target_properties(${target_name} PROPERTIES WIN32_EXECUTABLE FALSE)
    target_link_options(${target_name} PRIVATE -mconsole -Wl,-subsystem,console)
    # MinGW needs these; do NOT pull SDL2main (that expects SDL_main + WinMain glue).
    target_link_libraries(${target_name} PRIVATE mingw32 ${SDL2_LIBRARY} winmm imm32 version setupapi)
  else()
    target_link_libraries(${target_name} PRIVATE m pthread)
  endif()
endfunction()

add_sim(sim_sdl ${MVP_ROOT}/host/main_sdl.c)
add_sim(sim_script ${MVP_ROOT}/host/main_script.c)

# Per-project smoke CSV from gen_mvp (fallback: engine tests/transitions.csv)
if(EXISTS "${MVP_DIR}/transitions.csv")
  configure_file(${MVP_DIR}/transitions.csv
                 ${CMAKE_BINARY_DIR}/tests/transitions.csv COPYONLY)
elseif(EXISTS "${MVP_ROOT}/tests/transitions.csv")
  configure_file(${MVP_ROOT}/tests/transitions.csv
                 ${CMAKE_BINARY_DIR}/tests/transitions.csv COPYONLY)
endif()
