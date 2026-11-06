#ifndef APP_PRESENTER_H
#define APP_PRESENTER_H

#include <stdbool.h>
#include "mvp_types.h"
#include "app_nav.h"

#ifdef __cplusplus
extern "C" {
#endif

void presenter_init(void);

/* Formal path: command → model hook → nav → view_apply. */
bool presenter_dispatch(app_cmd_t cmd);

bool presenter_resolve_edge(app_screen_id_t from, app_cmd_t cmd,
                            app_screen_id_t * out_to, nav_unload_policy_t * out_policy);

#ifdef __cplusplus
}
#endif
#endif
