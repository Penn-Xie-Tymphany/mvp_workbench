#ifndef MVP_VIEW_H
#define MVP_VIEW_H

#include "lvgl.h"
#include "app_cmd.h"
#include "ui.h"

#ifdef __cplusplus
extern "C" {
#endif

void mvp_clear_events(lv_obj_t * obj);
void mvp_bind_btn(lv_obj_t * btn, app_cmd_t cmd);
void mvp_bound_reset(void);
void mvp_finish_binds(aidogui_ui_t * ui);
aidogui_ui_t * mvp_view_ui(void);
void mvp_view_set_ui(aidogui_ui_t * ui);

#ifdef __cplusplus
}
#endif
#endif
