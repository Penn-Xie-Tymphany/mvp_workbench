#ifndef VIEW_APPLY_H
#define VIEW_APPLY_H

#include "app_model.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Push model state into widgets. Per-project (generated view_apply.c). */
void view_apply(const app_model_t * m);

#ifdef __cplusplus
}
#endif
#endif
