#ifndef HOST_COMMON_H
#define HOST_COMMON_H

#include <stdio.h>
#include "lvgl.h"
#include "ui.h"
#include "port_sdl.h"
#include "app_presenter.h"
#include "app_nav.h"
#include "view_apply.h"
#include "mvp_view.h"
#if defined(__has_include)
#  if __has_include("app_io_table.h")
#    include "app_io_table.h"
#    define HOST_HAVE_IO_TABLE 1
#  endif
#  if __has_include("io_view.h")
#    include "io_view.h"
#    define HOST_HAVE_IO_VIEW 1
#  endif
#endif
/* Keep our own main(); do not let SDL.h rename it to SDL_main (WinMain trap on MinGW). */
#ifndef SDL_MAIN_HANDLED
#define SDL_MAIN_HANDLED
#endif
#include <SDL2/SDL.h>

static inline lv_display_t * host_boot(const char * title)
{
    lv_init();
    lv_display_t * disp = port_sdl_init(SCREEN_WIDTH, SCREEN_HEIGHT, title);
    if (!disp) return NULL;
    aidogui_init(); /* custom_init → presenter_init + nav_bootstrap + view_bind */
#ifdef HOST_HAVE_IO_TABLE
    app_io_init(); /* io.json declared defaults */
#endif
    view_apply(app_model_get());
#ifdef HOST_HAVE_IO_VIEW
    io_view_apply(mvp_view_ui(), app_model_get()); /* widget bindings, first paint */
#endif
    return disp;
}

static inline void host_tick_ms(uint32_t ms)
{
    uint32_t start = lv_tick_get();
    while (lv_tick_elaps(start) < ms) {
        uint32_t delay = lv_timer_handler();
        nav_process_deletes(); /* async deletions fired inside the handler */
        if (delay == 0) delay = 1;
        if (delay > 20) delay = 20;
        SDL_Delay(delay);
    }
    nav_process_deletes();
}

#endif
