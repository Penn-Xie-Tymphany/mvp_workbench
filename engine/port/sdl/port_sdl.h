#ifndef PORT_SDL_H
#define PORT_SDL_H

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

lv_display_t * port_sdl_init(int32_t hor, int32_t ver, const char * title);
void port_sdl_poll(void); /* optional; LVGL SDL timer already pumps events */

#ifdef __cplusplus
}
#endif
#endif
