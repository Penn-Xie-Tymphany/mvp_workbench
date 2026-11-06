#include "app_presenter.h"
#include "view_apply.h"
#include "mvp_view.h"
#include <stdio.h>

#if defined(__has_include)
#  if __has_include("app_io_table.h")
#    include "app_io_table.h"
#    define HAVE_IO_TABLE 1
#  endif
#  if __has_include("io_view.h")
#    include "io_view.h"
#    define HAVE_IO_VIEW 1
#  endif
#endif

void presenter_init(void)
{
    app_model_init(NULL);
}

static const mvp_edge_t * find_edge(app_screen_id_t from, app_cmd_t cmd)
{
    for (int i = 0; i < mvp_edge_count; ++i) {
        const mvp_edge_t * e = &mvp_edges[i];
        if (e->from == from && e->cmd == cmd) return e;
    }
    return NULL;
}

bool presenter_resolve_edge(app_screen_id_t from, app_cmd_t cmd,
                            app_screen_id_t * out_to, nav_unload_policy_t * out_policy)
{
    const mvp_edge_t * e = find_edge(from, cmd);
    if (e) {
        if (out_to) *out_to = e->to;
        if (out_policy) *out_policy = e->policy;
        return true;
    }
    return false;
}

bool presenter_dispatch(app_cmd_t cmd)
{
    app_model_t * m = app_model_get();
    app_screen_id_t from = nav_current();
    app_screen_id_t to = APP_SCREEN_NONE;
    nav_unload_policy_t pol = NAV_UNLOAD_DEL;
    const mvp_edge_t * e = find_edge(from, cmd);

    if (!e || !presenter_resolve_edge(from, cmd, &to, &pol)) {
        printf("[presenter] REJECT cmd=%s from=%s\n",
               app_cmd_name(cmd), app_screen_name(from));
        return false;
    }

    model_on_cmd(m, cmd, from, to);

    printf("[presenter] %s --%s/%s--> %s\n",
           app_screen_name(from), app_cmd_name(cmd), nav_policy_name(pol),
           app_screen_name(to));

    if (!nav_goto(to, pol)) return false;
#ifdef HAVE_IO_TABLE
    if (e->param_key && e->param_key[0]) {
        /* navigation context: e.g. DEVICEA → devicedetail carries device=A */
        app_io_set_str_name(e->param_key, e->param_val ? e->param_val : "");
    }
#endif
    view_apply(m);
#ifdef HAVE_IO_VIEW
    io_view_apply(mvp_view_ui(), m);
#endif
    return true;
}
