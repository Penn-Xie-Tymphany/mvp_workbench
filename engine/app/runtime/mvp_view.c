#include "mvp_view.h"
#include "app_presenter.h"
#include "mvp_types.h"
#include "src/core/lv_obj_private.h" /* obj->spec_attr (LVGL 9.3 private struct) */
#include <stdint.h>

static aidogui_ui_t * s_view_ui = NULL;

aidogui_ui_t * mvp_view_ui(void)
{
    return s_view_ui;
}

void mvp_view_set_ui(aidogui_ui_t * ui)
{
    s_view_ui = ui;
}

/* MVP owns its click callback; when re-shimming we skip and let
 * view_bind/mvp_bind_btn re-register it. */
static void on_cmd(lv_event_t * e);

/* Registry of objects bound in the CURRENT view_bind pass. Used by
 * mvp_finish_binds() to put EVENT_BUBBLE on every unbound widget, so
 * clicks on covering children (full-screen bg images, arcs, labels...)
 * bubble up to the screen-level MVP bind instead of being swallowed. */
static lv_obj_t * g_bound[64];
static int g_bound_n = 0;

void mvp_bound_reset(void)
{
    g_bound_n = 0;
}

static bool mvp_is_bound(lv_obj_t * obj)
{
    for (int i = 0; i < g_bound_n; ++i)
        if (g_bound[i] == obj) return true;
    return false;
}

/* Walk a screen tree: everything not MVP-bound bubbles its events upward. */
static void bubble_deep(lv_obj_t * obj)
{
    if (!obj || !lv_obj_is_valid(obj)) return;
    if (!mvp_is_bound(obj))
        lv_obj_add_flag(obj, LV_OBJ_FLAG_EVENT_BUBBLE);
    uint32_t n = lv_obj_get_child_count(obj);
    for (uint32_t i = 0; i < n; ++i)
        bubble_deep(lv_obj_get_child(obj, i));
}

void mvp_finish_binds(aidogui_ui_t * ui)
{
    if (!ui) return;
    for (int i = 0; i < mvp_screen_count; ++i) {
        lv_obj_t ** rp = mvp_screens[i].root_ptr ? mvp_screens[i].root_ptr() : NULL;
        if (rp && *rp && lv_obj_is_valid(*rp)) bubble_deep(*rp);
    }
}

/* Lifecycle events that STAY with the View (AIDOGUI entrance/exit effects).
 * Everything interaction-related is dropped here — the MVP layer re-binds
 * what it needs (see mvp_bind_btn). */
static const lv_event_code_t mvp_lifecycle_events[] = {
    LV_EVENT_SCREEN_LOAD_START,
    LV_EVENT_SCREEN_LOADED,
    LV_EVENT_SCREEN_UNLOAD_START,
    LV_EVENT_SCREEN_UNLOADED,
    LV_EVENT_DELETE, /* imported projects null their ui-struct handles here
                        and stop custom animations targeting deleted widgets */
};

#define MVP_ORIG_CAP 24

void mvp_clear_events(lv_obj_t * obj)
{
    if (!obj || !lv_obj_is_valid(obj)) return;
    if (!obj->spec_attr) return;

    /* LVGL >= 9.3: event removal during an ONGOING dispatch is deferred
     * (mark-deleting + cleanup after iteration). The old idiom
     *   while (lv_obj_get_event_count(obj) > 0) lv_obj_remove_event(obj, 0);
     * never terminated when clearing the list that is currently dispatching
     * (e.g. re-binding the screen root inside its own click handler) — that
     * was the click-freeze. */

    /* Collect originals first: AIDOGUI registers ONE handler with
     * LV_EVENT_ALL per widget whose switch() mixes interaction branches
     * (gestures/clicks) AND lifecycle branches (entrance animations on
     * SCREEN_LOAD_START). We keep only the lifecycle part — re-registered
     * with the ORIGINAL user_data (their handlers read the ui pointer from
     * it) — and drop the interaction part entirely: the MVP layer owns all
     * interaction (view_bind re-adds on_cmd). This pass is idempotent, so
     * repeated nav/view_bind cycles never accumulate duplicates. */
    uint32_t n = lv_obj_get_event_count(obj);
    if (n > MVP_ORIG_CAP) n = MVP_ORIG_CAP;
    lv_event_cb_t cbs[MVP_ORIG_CAP];
    void * uds[MVP_ORIG_CAP];
    for (uint32_t i = 0; i < n; ++i) {
        lv_event_dsc_t * dsc = lv_obj_get_event_dsc(obj, i);
        cbs[i] = lv_event_dsc_get_cb(dsc);
        uds[i] = lv_event_dsc_get_user_data(dsc);
    }

    lv_event_remove_all(&obj->spec_attr->event_list);

    for (uint32_t i = 0; i < n; ++i) {
        if (cbs[i] == on_cmd) continue; /* ours — re-added by view_bind */
        for (unsigned k = 0; k < sizeof(mvp_lifecycle_events) / sizeof(mvp_lifecycle_events[0]); ++k)
            lv_obj_add_event_cb(obj, cbs[i], mvp_lifecycle_events[k], uds[i]);
    }
}

static void on_cmd(lv_event_t * e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED) return;
    app_cmd_t cmd = (app_cmd_t)(uintptr_t)lv_event_get_user_data(e);
    presenter_dispatch(cmd);
}

void mvp_bind_btn(lv_obj_t * btn, app_cmd_t cmd)
{
    if (!btn || !lv_obj_is_valid(btn)) return;
    mvp_clear_events(btn);
    if (g_bound_n < 64) g_bound[g_bound_n++] = btn;
    lv_obj_add_event_cb(btn, on_cmd, LV_EVENT_CLICKED, (void *)(uintptr_t)cmd);
}
