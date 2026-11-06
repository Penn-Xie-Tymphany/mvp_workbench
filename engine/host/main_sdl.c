/**
 * Human-driven SDL simulator + optional I/O pipe protocol.
 *
 * MVP: mouse clicks → view_bind → presenter_dispatch.
 * Optional letter keys dispatch cmds whose name starts with that letter.
 *
 * I/O protocol (only when stdin is a pipe, i.e. launched by the Workbench):
 *   CMD <NAME>          dispatch a presenter command
 *   SET <field> <val>   write a model field via the generated app_io_table
 *   STATE?              dump state now
 *   QUIT                exit
 * Output lines:
 *   STATE screen=<NAME> <field>=<value> ...   (periodic + after each op)
 * Everything else (logs) passes through unchanged.
 */
#include "host_common.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <ctype.h>
#include <SDL2/SDL.h>

#if defined(__has_include)
#  if __has_include("app_io_table.h")
#    include "app_io_table.h"
#    define HAVE_APP_IO 1
#  endif
#endif

#ifdef _WIN32
#  include <windows.h>
#else
#  include <unistd.h>
#  include <sys/select.h>
#endif

/* ---- stdin plumbing ---------------------------------------------------- */

static bool g_piped = false;

static bool stdin_is_pipe(void)
{
#ifdef _WIN32
    return GetFileType(GetStdHandle(STD_INPUT_HANDLE)) == FILE_TYPE_PIPE;
#else
    return !isatty(fileno(stdin));
#endif
}

/* Pipe mode must be explicitly opted-in (env var set by the Workbench I/O
 * panel) AND stdin must actually be a pipe — ambient stdin of arbitrary
 * launch chains must never flip the sim into protocol mode. */
static bool io_pipe_requested(void)
{
    return getenv("AIDOGUI_SIM_PIPE") != NULL && stdin_is_pipe();
}

/* Non-blocking single line read. Returns false when nothing available. */
static bool io_read_line(char * buf, size_t cap)
{
#ifdef _WIN32
    HANDLE h = GetStdHandle(STD_INPUT_HANDLE);
    DWORD avail = 0;
    if (!PeekNamedPipe(h, NULL, 0, NULL, &avail, NULL) || avail == 0) return false;
    size_t n = 0;
    while (n + 1 < cap) {
        char ch;
        DWORD got = 0;
        if (!ReadFile(h, &ch, 1, &got, NULL) || got == 0) return false;
        if (ch == '\n') break;
        if (ch != '\r') buf[n++] = ch;
    }
    buf[n] = 0;
    return true;
#else
    fd_set fds;
    struct timeval tv = {0, 0};
    FD_ZERO(&fds);
    FD_SET(fileno(stdin), &fds);
    if (select(fileno(stdin) + 1, &fds, NULL, NULL, &tv) <= 0) return false;
    if (!fgets(buf, (int)cap, stdin)) return false;
    size_t n = strlen(buf);
    while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r')) buf[--n] = 0;
    return true;
#endif
}

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

static void io_dump_state(void)
{
    printf("STATE screen=%s", app_screen_name(nav_current()));
#ifdef HAVE_APP_IO
    for (int i = 0; i < app_io_count(); ++i) {
        if (app_io_is_str(i)) {
            const char * s = app_io_str(i);
            printf(" %s=\"%s\"", app_io_name(i), s ? s : "");
            continue;
        }
        double v = 0;
        if (app_io_get(i, &v)) printf(" %s=%.6g", app_io_name(i), v);
    }
#endif
    printf("\n");
    fflush(stdout);
}

static void io_poll(bool * running)
{
    char line[256];
    while (io_read_line(line, sizeof(line))) {
        char * p = trim(line);
        if (!*p || *p == '#') continue;
        if (starts_with_ci(p, "QUIT")) {
            *running = false;
            return;
        }
        if (starts_with_ci(p, "STATE?")) {
            io_dump_state();
            continue;
        }
        if (starts_with_ci(p, "TAP")) {
            lv_obj_t * root = nav_current_root();
            if (root) {
                printf("ACK TAP root=%p valid=%d events=%u\n",
                       (void *)root, (int)lv_obj_is_valid(root),
                       (unsigned)lv_obj_get_event_count(root));
                lv_obj_send_event(root, LV_EVENT_CLICKED, NULL);
            } else {
                /* distinguish: handle zeroed vs object deleted */
                const mvp_screen_desc_t * cd = nav_current_desc();
                lv_obj_t ** rp = cd ? (cd->root_ptr ? cd->root_ptr() : NULL) : NULL;
                printf("ERR no valid root (g_current=%s handle=%p valid_at_ptr=%s)\n",
                       app_screen_name(nav_current()), (void *)(rp ? *rp : NULL),
                       (rp && *rp) ? (lv_obj_is_valid(*rp) ? "yes" : "DELETED") : "NULL");
            }
            fflush(stdout);
            io_dump_state();
            continue;
        }
        if (starts_with_ci(p, "CMD ")) {
            char * name = trim(p + 4);
            app_cmd_t cmd = app_cmd_from_name(name);
            if (cmd == APP_CMD_NONE) {
                printf("ERR unknown CMD %s\n", name);
            } else {
                bool ok = presenter_dispatch(cmd);
                printf("ACK CMD %s %s\n", name, ok ? "ok" : "rejected");
            }
            fflush(stdout);
            io_dump_state();
            continue;
        }
        if (starts_with_ci(p, "SET ")) {
            char * rest = trim(p + 4);
            char * sp = rest;
            while (*sp && !isspace((unsigned char)*sp)) ++sp;
            if (*sp) {
                *sp = 0;
                char * val = trim(sp + 1);
#ifdef HAVE_APP_IO
                bool ok = app_io_set_str_name(rest, val);
                if (!ok) ok = app_io_set_name(rest, atof(val));
                printf("ACK SET %s %s\n", rest, ok ? "ok" : "no-field");
#else
                printf("ERR no io table (design I/O then rebuild)\n");
#endif
            } else {
                printf("ERR SET needs <field> <value>\n");
            }
            fflush(stdout);
            io_dump_state();
            continue;
        }
        printf("ERR unknown line: %s\n", p);
        fflush(stdout);
    }
}

/* ---- SDL key → CMD (legacy manual control) ------------------------------ */

static void try_key_cmd(char letter)
{
    char up = (char)toupper((unsigned char)letter);
    for (int i = 1; i < (int)APP_CMD_COUNT; ++i) {
        app_cmd_t cmd = (app_cmd_t)i;
        const char * n = app_cmd_name(cmd);
        if (n && n[0] && toupper((unsigned char)n[0]) == up) {
            presenter_dispatch(cmd);
            return;
        }
    }
}

int main(int argc, char ** argv)
{
    (void)argc; (void)argv;
    g_piped = io_pipe_requested();
    if (g_piped) {
        /* GUI drives us over the pipe: keep logs/STATE flowing immediately. */
        setvbuf(stdout, NULL, 2 /* _ION — MinGW -std=c11 hides the macro */, 0);
        printf("sim_sdl: pipe mode — CMD/SET/STATE?/QUIT accepted\n");
    } else {
        printf("sim_sdl: AIDOGUI MVP — clicks drive presenter; Q quit\n");
        printf("Keys: letter → first CMD whose name starts with that letter\n");
    }
    fflush(stdout);
    if (!host_boot("AIDOGUI MVP sim_sdl")) return 1;
    if (g_piped) io_dump_state();

    uint8_t prev[SDL_NUM_SCANCODES];
    memset(prev, 0, sizeof(prev));

    uint32_t last_dump = lv_tick_get();
    uint32_t stat_t0 = last_dump;
    uint32_t frames = 0, fmax_ms = 0, busy_ms = 0;
    double fsum_ms = 0.0;
    bool running = true;
    while (running) {
        uint32_t h0 = lv_tick_get();
        if (g_piped) {
            io_poll(&running);
            if (lv_tick_get() - last_dump > 250) {
                io_dump_state();
                last_dump = lv_tick_get();
            }
        }

        const Uint8 * st = SDL_GetKeyboardState(NULL);
        #define EDGE(sc) (st[(sc)] && !prev[(sc)])
        if (EDGE(SDL_SCANCODE_Q)) running = false;
        /* A-Z → try matching CMD */
        for (int sc = SDL_SCANCODE_A; sc <= SDL_SCANCODE_Z; ++sc) {
            if (sc == SDL_SCANCODE_Q) continue;
            if (EDGE(sc)) try_key_cmd((char)('a' + (sc - SDL_SCANCODE_A)));
        }
        #undef EDGE
        memcpy(prev, st, SDL_NUM_SCANCODES);

        if (!lv_display_get_default()) running = false;

        uint32_t d = lv_timer_handler();
        nav_process_deletes(); /* async deletions fired inside the handler */
        uint32_t h1 = lv_tick_get();
        uint32_t handler_ms = h1 - h0;
        frames++;
        fsum_ms += (double)handler_ms;
        if (handler_ms > fmax_ms) fmax_ms = handler_ms;
        busy_ms += handler_ms;
        if (g_piped && h1 - stat_t0 >= 1000) {
            uint32_t win = h1 - stat_t0;
            uint32_t fps = (win > 0) ? frames * 1000 / win : 0;
            double favg = frames ? fsum_ms / frames : 0.0;
            printf("STAT fps=%u frame_avg=%.1f frame_max=%u cpu=%u",
                   fps, favg, fmax_ms, (uint32_t)(busy_ms * 100 / (win ? win : 1)));
#ifdef HAVE_APP_IO
            {
                lv_mem_monitor_t mon;
                lv_mem_monitor(&mon);
                printf(" mem_used=%u mem_total=%u used_pct=%u frag=%u",
                       (unsigned)(mon.total_size - mon.free_size),
                       (unsigned)mon.total_size,
                       (unsigned)mon.used_pct, (unsigned)mon.frag_pct);
            }
#endif
            printf("\n");
            fflush(stdout);
            stat_t0 = h1;
            frames = 0; fmax_ms = 0; busy_ms = 0; fsum_ms = 0.0;
        }
        if (d > 20) d = 20;
        if (d == 0) d = 1;
        SDL_Delay(d);
    }

    aidogui_destroy();
    return 0;
}