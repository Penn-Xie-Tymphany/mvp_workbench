#include "port_sdl.h"
#include <stdio.h>

lv_display_t * port_sdl_init(int32_t hor, int32_t ver, const char * title)
{
    lv_display_t * disp = lv_sdl_window_create(hor, ver);
    if (!disp) {
        fprintf(stderr, "[port_sdl] lv_sdl_window_create failed\n");
        return NULL;
    }
    if (title) lv_sdl_window_set_title(disp, title);
    lv_sdl_window_set_resizeable(disp, false);

    lv_group_t * g = lv_group_create();
    lv_group_set_default(g);

    lv_indev_t * mouse = lv_sdl_mouse_create();
    if (mouse) lv_indev_set_group(mouse, g);

    lv_indev_t * kb = lv_sdl_keyboard_create();
    if (kb) lv_indev_set_group(kb, g);

#if defined(LV_SDL_MOUSEWHEEL_MODE) && (LV_SDL_MOUSEWHEEL_MODE == LV_SDL_MOUSEWHEEL_MODE_ENCODER)
    lv_indev_t * wheel = lv_sdl_mousewheel_create();
    if (wheel) lv_indev_set_group(wheel, g);
#endif

    printf("[port_sdl] display %dx%d ready\n", (int)hor, (int)ver);
    return disp;
}

void port_sdl_poll(void)
{
    /* SDL events are drained by LVGL's internal sdl_event_handler timer. */
}
