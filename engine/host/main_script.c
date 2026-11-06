/**
 * Scripted SDL traversal.
 *   - CSV edges: from,cmd,to,unload_policy,notes  (to=REJECT for illegal)
 *   - CMD script: lines "CMD NAME" dispatched from bootstrap
 */
#include "host_common.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdbool.h>
#include <SDL2/SDL.h>

typedef struct {
    char from[32];
    char cmd[32];
    char to[32];
    char policy[16];
    char notes[128];
    bool expect_reject;
} edge_t;

static char * trim(char * s)
{
    while (*s && isspace((unsigned char)*s)) ++s;
    if (!*s) return s;
    char * e = s + strlen(s) - 1;
    while (e > s && isspace((unsigned char)*e)) *e-- = 0;
    return s;
}

static bool starts_with_ci(const char * s, const char * prefix)
{
    for (; *prefix; ++s, ++prefix) {
        if (!*s) return false;
        if (tolower((unsigned char)*s) != tolower((unsigned char)*prefix)) return false;
    }
    return true;
}

static bool file_is_cmd_script(const char * path)
{
    FILE * f = fopen(path, "r");
    if (!f) return false;
    char line[512];
    bool is_cmd = false;
    while (fgets(line, sizeof(line), f)) {
        char * p = trim(line);
        if (!*p || *p == '#') continue;
        is_cmd = starts_with_ci(p, "CMD ");
        break;
    }
    fclose(f);
    return is_cmd;
}

static int load_csv(const char * path, edge_t * out, int maxn)
{
    FILE * f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        return -1;
    }
    char line[512];
    int n = 0;
    bool header = true;
    while (fgets(line, sizeof(line), f)) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') continue;
        if (header) { header = false; continue; }
        edge_t * e = &out[n];
        memset(e, 0, sizeof(*e));
        char * p = line;
        char * cols[5] = {0};
        int ci = 0;
        cols[ci++] = p;
        for (; *p && ci < 5; ++p) {
            if (*p == ',') {
                *p = 0;
                cols[ci++] = p + 1;
            }
        }
        if (ci < 4) continue;
        strncpy(e->from, trim(cols[0]), sizeof(e->from) - 1);
        strncpy(e->cmd, trim(cols[1]), sizeof(e->cmd) - 1);
        strncpy(e->to, trim(cols[2]), sizeof(e->to) - 1);
        strncpy(e->policy, trim(cols[3]), sizeof(e->policy) - 1);
        if (cols[4]) strncpy(e->notes, trim(cols[4]), sizeof(e->notes) - 1);
        e->expect_reject = (strcasecmp(e->to, "REJECT") == 0);
        if (++n >= maxn) break;
    }
    fclose(f);
    return n;
}

static int assert_alive_matrix(app_screen_id_t active, nav_unload_policy_t last_pol,
                               app_screen_id_t from, app_screen_id_t to, char * err, size_t errsz)
{
    if (nav_current() != active) {
        snprintf(err, errsz, "current=%s want=%s", app_screen_name(nav_current()), app_screen_name(active));
        return -1;
    }
    if (!nav_is_alive(active) || !nav_obj_valid(active)) {
        snprintf(err, errsz, "active %s not alive/valid", app_screen_name(active));
        return -1;
    }
    if (from != to && last_pol == NAV_UNLOAD_DEL) {
        if (nav_is_alive(from) || nav_obj_valid(from)) {
            snprintf(err, errsz, "after DEL, %s still alive/valid", app_screen_name(from));
            return -1;
        }
        void * dead = nav_last_deleted_obj();
        if (dead && lv_obj_is_valid(dead)) {
            snprintf(err, errsz, "lv_obj_is_valid(last_deleted)=true for %s",
                     app_screen_name(nav_last_deleted_screen()));
            return -1;
        }
    }
    if (from != to && last_pol == NAV_UNLOAD_HIDE) {
        if (!nav_is_alive(from) || !nav_obj_valid(from)) {
            snprintf(err, errsz, "after HIDE, %s should stay alive", app_screen_name(from));
            return -1;
        }
    }
    return 0;
}

/* BFS via edge table to reach want_from (bounded). */
static bool navigate_toward(app_screen_id_t want)
{
    for (int guard = 0; guard < 24 && nav_current() != want; ++guard) {
        app_screen_id_t cur = nav_current();
        bool stepped = false;
        for (int i = 1; i < (int)APP_CMD_COUNT; ++i) {
            app_screen_id_t to = APP_SCREEN_NONE;
            nav_unload_policy_t pol = NAV_UNLOAD_DEL;
            if (!presenter_resolve_edge(cur, (app_cmd_t)i, &to, &pol)) continue;
            if (to == want || to != cur) {
                /* Prefer direct edge to want; else any forward step */
                if (to == want) {
                    presenter_dispatch((app_cmd_t)i);
                    host_tick_ms(30);
                    stepped = true;
                    break;
                }
            }
        }
        if (nav_current() == want) return true;
        if (!stepped) {
            /* any legal edge */
            for (int i = 1; i < (int)APP_CMD_COUNT; ++i) {
                app_screen_id_t to = APP_SCREEN_NONE;
                nav_unload_policy_t pol = NAV_UNLOAD_DEL;
                if (!presenter_resolve_edge(cur, (app_cmd_t)i, &to, &pol)) continue;
                if (to == cur) continue;
                presenter_dispatch((app_cmd_t)i);
                host_tick_ms(30);
                stepped = true;
                break;
            }
        }
        if (!stepped) return false;
    }
    return nav_current() == want;
}

static int run_cmd_script(const char * path)
{
    FILE * f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        return 2;
    }
    printf("sim_script: CMD mode file=%s\n", path);
    if (!host_boot("AIDOGUI MVP sim_script CMD")) {
        fclose(f);
        return 1;
    }
    host_tick_ms(50);

    char line[512];
    int n = 0, pass = 0, fail = 0;
    while (fgets(line, sizeof(line), f)) {
        char * p = trim(line);
        if (!*p || *p == '#') continue;
        if (!starts_with_ci(p, "CMD ")) {
            printf("SKIP[%d] not a CMD line: %s\n", n, p);
            continue;
        }
        char * name = trim(p + 4);
        app_cmd_t cmd = app_cmd_from_name(name);
        app_screen_id_t before = nav_current();
        bool ok = false;
        if (cmd == APP_CMD_NONE) {
            printf("FAIL[%d] unknown CMD %s (at %s)\n", n, name, app_screen_name(before));
            fail++;
        } else {
            ok = presenter_dispatch(cmd);
            host_tick_ms(40);
            printf("%s[%d] CMD %s  %s -> %s  dispatch=%s\n",
                   ok ? "PASS" : "WARN",
                   n, name,
                   app_screen_name(before),
                   app_screen_name(nav_current()),
                   ok ? "ok" : "rejected");
            if (ok) pass++; else fail++;
        }
        n++;
    }
    fclose(f);
    printf("\n=== CMD result: %d ok-ish, %d fail-or-reject / %d ===\n", pass, fail, n);
    printf("final screen=%s\n", app_screen_name(nav_current()));
    aidogui_destroy();
    return fail ? 1 : 0;
}

static int run_csv_script(const char * csv)
{
    printf("sim_script: CSV=%s\n", csv);
    edge_t edges[128];
    int n = load_csv(csv, edges, 128);
    if (n <= 0) return 2;

    if (!host_boot("AIDOGUI MVP sim_script")) return 1;
    host_tick_ms(50);

    int pass = 0, fail = 0;

    for (int i = 0; i < n; ++i) {
        edge_t * e = &edges[i];
        app_screen_id_t want_from = app_screen_from_name(e->from);
        app_cmd_t cmd = app_cmd_from_name(e->cmd);
        app_screen_id_t want_to = e->expect_reject ? APP_SCREEN_NONE : app_screen_from_name(e->to);
        nav_unload_policy_t pol = nav_policy_from_name(e->policy);

        if (nav_current() != want_from) {
            printf("  setup: navigate toward %s from %s ...\n",
                   app_screen_name(want_from), app_screen_name(nav_current()));
            navigate_toward(want_from);
        }

        if (nav_current() != want_from) {
            printf("FAIL[%d] need from=%s but at %s (%s)\n", i, e->from,
                   app_screen_name(nav_current()), e->notes);
            fail++;
            continue;
        }

        app_screen_id_t from = nav_current();
        bool ok = presenter_dispatch(cmd);
        host_tick_ms(40);

        char err[256] = {0};
        if (e->expect_reject) {
            if (ok) {
                snprintf(err, sizeof(err), "expected REJECT but dispatch succeeded");
            } else if (nav_current() != from) {
                snprintf(err, sizeof(err), "reject mutated screen to %s", app_screen_name(nav_current()));
            }
        } else {
            if (!ok) {
                snprintf(err, sizeof(err), "dispatch failed");
            } else if (want_to != nav_current()) {
                snprintf(err, sizeof(err), "landed %s want %s", app_screen_name(nav_current()), e->to);
            } else if (assert_alive_matrix(want_to, pol, from, want_to, err, sizeof(err)) != 0) {
                /* err set */
            }
        }

        if (err[0]) {
            printf("FAIL[%d] %s -%s/%s-> %s :: %s\n", i, e->from, e->cmd, e->policy, e->to, err);
            fail++;
        } else {
            printf("PASS[%d] %s -%s/%s-> %s  %s\n", i, e->from, e->cmd, e->policy, e->to,
                   e->notes);
            pass++;
        }
    }

    printf("\n=== result: %d pass, %d fail / %d ===\n", pass, fail, n);
    aidogui_destroy();
    return fail ? 1 : 0;
}

int main(int argc, char ** argv)
{
    const char * path = "tests/transitions.csv";
    if (argc >= 2) path = argv[1];

    if (file_is_cmd_script(path))
        return run_cmd_script(path);
    return run_csv_script(path);
}
