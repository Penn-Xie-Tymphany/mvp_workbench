#include "app_nav.h"
#include "view_bind.h"
#include "mvp_view.h"
#include "ui.h"
#include <stdio.h>
#include <strings.h>
#include <string.h>

static bool g_alive[64];
static app_screen_id_t g_current = APP_SCREEN_NONE;
static void * g_last_deleted = NULL;
static app_screen_id_t g_last_deleted_screen = APP_SCREEN_NONE;
static app_screen_id_t g_hidden_underlay = APP_SCREEN_NONE;
static bool g_need_indev_reset = false;

static const mvp_screen_desc_t * desc_for(app_screen_id_t id)
{
    for (int i = 0; i < mvp_screen_count; ++i) {
        if (mvp_screens[i].id == id) return &mvp_screens[i];
    }
    return NULL;
}

static void screen_destroy(app_screen_id_t id)
{
    const mvp_screen_desc_t * d = desc_for(id);
    if (!d) return;
    lv_obj_t ** rp = d->root_ptr ? d->root_ptr() : NULL;
    if (rp && *rp && lv_obj_is_valid(*rp)) {
        g_last_deleted = *rp;
        g_last_deleted_screen = id;
        lv_obj_delete_async(*rp);
        /* the async deletion (next timer tick) leaves the input devices
         * holding pointers into the deleted screen — reset them or every
         * subsequent click is swallowed ("only the first click works"). */
        g_need_indev_reset = true;
    }
    if (id >= 0 && id < 64) g_alive[id] = false;
    if (g_hidden_underlay == id) g_hidden_underlay = APP_SCREEN_NONE;
}

static void clear_events_deep(lv_obj_t * obj)
{
    if (!obj || !lv_obj_is_valid(obj)) return;
    mvp_clear_events(obj);
    uint32_t n = lv_obj_get_child_count(obj);
    for (uint32_t i = 0; i < n; ++i) {
        clear_events_deep(lv_obj_get_child(obj, i));
    }
}

static void screen_init(app_screen_id_t id)
{
    const mvp_screen_desc_t * d = desc_for(id);
    if (d && d->init) {
        d->init();
        /* Strip the native INTERACTION handlers from the freshly created
         * screen tree (mvp_clear_events keeps lifecycle/delete handlers).
         * AIDOGUI registers click/gesture handlers on widgets our scan may
         * not have identified — if any survived, a click would take the
         * native _ui_screen_change path and fight the MVP navigator.
         * MVP re-binds its own controls right after via view_bind(). */
        lv_obj_t ** rp = d->root_ptr ? d->root_ptr() : NULL;
        if (rp && *rp && lv_obj_is_valid(*rp)) clear_events_deep(*rp);
    }
}

void nav_bootstrap(void)
{
    app_screen_id_t boot = mvp_bootstrap_screen;
    if (boot < 0 || boot >= APP_SCREEN_COUNT) {
        fprintf(stderr, "[nav] invalid bootstrap screen id %d\n", (int)boot);
        boot = (app_screen_id_t)0;
    }

    g_current = boot;
    g_hidden_underlay = APP_SCREEN_NONE;
    memset(g_alive, 0, sizeof(g_alive));

    for (int i = 0; i < mvp_screen_count; ++i) {
        app_screen_id_t id = mvp_screens[i].id;
        if (id == boot) continue;
        lv_obj_t ** rp = mvp_screens[i].root_ptr ? mvp_screens[i].root_ptr() : NULL;
        if (rp && *rp) screen_destroy(id);
    }

    const mvp_screen_desc_t * bd = desc_for(boot);
    lv_obj_t ** br = bd && bd->root_ptr ? bd->root_ptr() : NULL;
    bool boot_ok = br && *br && lv_obj_is_valid(*br);
    if (!boot_ok) {
        screen_init(boot);
        br = bd->root_ptr ? bd->root_ptr() : NULL;
        boot_ok = br && *br && lv_obj_is_valid(*br);
    }
    if (!boot_ok) {
        fprintf(stderr, "[nav] bootstrap failed for %s (screens=%d)\n",
                app_screen_name(boot), mvp_screen_count);
        return;
    }
    g_alive[boot] = true;
    lv_screen_load(*br);
    view_bind(&aidogui_ui);
    fprintf(stderr, "[nav] bootstrap: current=%s screens=%d\n",
            app_screen_name(boot), mvp_screen_count);
}

bool nav_goto(app_screen_id_t to, nav_unload_policy_t policy_for_prev)
{
    if (to < 0 || to >= APP_SCREEN_COUNT) return false;
    const mvp_screen_desc_t * td = desc_for(to);
    if (!td) {
        fprintf(stderr, "[nav] no descriptor for %s\n", app_screen_name(to));
        return false;
    }

    app_screen_id_t from = g_current;
    screen_init(to);
    lv_obj_t ** to_root = td->root_ptr ? td->root_ptr() : NULL;
    if (!to_root || !*to_root || !lv_obj_is_valid(*to_root)) {
        fprintf(stderr, "[nav] failed to create %s\n", app_screen_name(to));
        return false;
    }
    if (to >= 0 && to < 64) g_alive[to] = true;
    lv_screen_load(*to_root);
    /* AIDOGUI screen_init re-registers interaction handlers on every call —
     * view_bind re-strips them and re-adds the MVP bindings. */
    view_bind(&aidogui_ui);

    if (from != APP_SCREEN_NONE && from != to) {
        if (policy_for_prev == NAV_UNLOAD_HIDE) {
            if (from >= 0 && from < 64) g_alive[from] = true;
            g_hidden_underlay = from;
        } else {
            /* DEL: async-delete the screen we are leaving. Safe here even
             * inside the clicked object's event dispatch; the imported
             * project's DELETE handlers null its ui-struct handles. */
            screen_destroy(from);
            /* Leaving an overlay to a third screen: also DEL the HIDE'd underlay. */
            if (g_hidden_underlay != APP_SCREEN_NONE &&
                g_hidden_underlay != to &&
                g_hidden_underlay != from) {
                screen_destroy(g_hidden_underlay);
                g_hidden_underlay = APP_SCREEN_NONE;
            }
        }
    }

    /* Resuming onto the underlay: clear underlay tracking (overlay already DEL). */
    if (to == g_hidden_underlay) {
        g_hidden_underlay = APP_SCREEN_NONE;
    }

    g_current = to;
    app_model_get()->screen = to;
    return true;
}

void nav_process_deletes(void)
{
    if (g_need_indev_reset) {
        lv_indev_reset(NULL, NULL); /* clear dangling indev refs after deletes */
        g_need_indev_reset = false;
    }
}

app_screen_id_t nav_current(void) { return g_current; }

lv_obj_t * nav_current_root(void)
{
    const mvp_screen_desc_t * d = nav_current_desc();
    if (!d || !d->root_ptr) return NULL;
    lv_obj_t ** rp = d->root_ptr();
    if (!rp || !*rp || !lv_obj_is_valid(*rp)) return NULL;
    return *rp;
}

const mvp_screen_desc_t * nav_current_desc(void)
{
    return desc_for(g_current);
}

bool nav_is_alive(app_screen_id_t id)
{
    if (id < 0 || id >= 64) return false;
    return g_alive[id];
}

bool nav_obj_valid(app_screen_id_t id)
{
    if (id < 0 || id >= 64) return false;
    const mvp_screen_desc_t * d = desc_for(id);
    lv_obj_t ** rp = d ? (d->root_ptr ? d->root_ptr() : NULL) : NULL;
    return rp && *rp && lv_obj_is_valid(*rp);
}

void * nav_last_deleted_obj(void) { return g_last_deleted; }
app_screen_id_t nav_last_deleted_screen(void) { return g_last_deleted_screen; }

nav_unload_policy_t nav_policy_from_name(const char * name)
{
    if (!name) return NAV_UNLOAD_DEL;
    if (strcasecmp(name, "HIDE") == 0) return NAV_UNLOAD_HIDE;
    return NAV_UNLOAD_DEL;
}

const char * nav_policy_name(nav_unload_policy_t p)
{
    return p == NAV_UNLOAD_HIDE ? "HIDE" : "DEL";
}