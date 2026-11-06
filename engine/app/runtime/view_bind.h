#ifndef VIEW_BIND_H
#define VIEW_BIND_H

#include "aidogui_objects.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Strip AIDOGUI CHANGE_SCREEN handlers and bind Presenter commands.
 * Implementation is per-project (generated view_bind.c). */
void view_bind(aidogui_ui_t * ui);

#ifdef __cplusplus
}
#endif
#endif
