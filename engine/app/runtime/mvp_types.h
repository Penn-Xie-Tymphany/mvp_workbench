#ifndef MVP_TYPES_H
#define MVP_TYPES_H

#include <stdbool.h>
#include "lvgl.h"
#include "app_model.h"
#include "app_cmd.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    NAV_UNLOAD_DEL = 0,
    NAV_UNLOAD_HIDE = 1
} nav_unload_policy_t;

/* Per-screen vtable filled by generated app_nav_table.c */
typedef struct {
    app_screen_id_t id;
    void (*init)(void);
    void (*destroy)(void);
    lv_obj_t ** (*root_ptr)(void);
    void (*zero_handles)(void);
} mvp_screen_desc_t;

typedef struct {
    app_screen_id_t from;
    app_cmd_t cmd;
    app_screen_id_t to;
    nav_unload_policy_t policy;
    /* Optional navigation context (page parameter). When non-NULL the
     * presenter writes param_val into the model field param_key before
     * view_apply — this is how a shared page shows per-entry data. */
    const char *param_key;
    const char *param_val;
} mvp_edge_t;

/* Provided by per-project generated sources */
extern const mvp_screen_desc_t mvp_screens[];
extern const int mvp_screen_count;
extern const app_screen_id_t mvp_bootstrap_screen;
extern const mvp_edge_t mvp_edges[];
extern const int mvp_edge_count;

/* Optional model hook (defined in project app_model.c USER section). */
void model_on_cmd(app_model_t * m, app_cmd_t cmd,
                  app_screen_id_t from, app_screen_id_t to);

#ifdef __cplusplus
}
#endif
#endif
