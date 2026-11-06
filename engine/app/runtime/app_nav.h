#ifndef APP_NAV_H
#define APP_NAV_H

#include <stdbool.h>
#include "mvp_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Call after aidogui_init: keep bootstrap screen, destroy the rest. */
void nav_bootstrap(void);

/* Navigate to target. Returns false if target invalid.
 * Screen DELETION (DEL policy) is deferred: call nav_process_deletes()
 * once per main-loop iteration (it runs outside event dispatch context). */
bool nav_goto(app_screen_id_t to, nav_unload_policy_t policy_for_prev);
void nav_process_deletes(void);

app_screen_id_t nav_current(void);
lv_obj_t * nav_current_root(void);
const mvp_screen_desc_t * nav_current_desc(void);
bool nav_is_alive(app_screen_id_t id);
bool nav_obj_valid(app_screen_id_t id);

void * nav_last_deleted_obj(void);
app_screen_id_t nav_last_deleted_screen(void);

nav_unload_policy_t nav_policy_from_name(const char * name);
const char * nav_policy_name(nav_unload_policy_t p);

#ifdef __cplusplus
}
#endif
#endif
