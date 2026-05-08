/*
 * BledOS Compositor - Minimal wlroots-based Wayland compositor
 * for the BledOS operating system.
 *
 * This compositor manages Wayland client surfaces and exports them
 * as DMA-BUF textures to the BledOS Shell (Blender) via a Unix
 * domain socket control interface.
 *
 * Build: meson setup build && ninja -C build
 * Run:   bledos-compositor
 */

#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <json-c/json.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <wayland-server-core.h>
#include <wlr/backend.h>
#include <wlr/backend/headless.h>
#include <wlr/render/allocator.h>
#include <wlr/render/wlr_renderer.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_data_device.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_damage.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_subcompositor.h>
#include <wlr/types/wlr_xdg_shell.h>
#include <wlr/util/log.h>

/* ─── Constants ─────────────────────────────────────────────────── */

#define BLEDOS_SOCK_PATH   "/run/bledos/compositor.sock"
#define BLEDOS_INPUT_PATH  "/run/bledos/input.sock"
#define MAX_CLIENTS        256
#define CMD_BUF_SIZE       4096

/* ─── Data Structures ──────────────────────────────────────────── */

typedef uint32_t client_id_t;

typedef struct bledos_client {
    client_id_t            id;
    pid_t                  pid;
    char                   title[256];
    struct wl_listener     destroy;
    struct wlr_xdg_surface *xdg_surface;
    struct wlr_surface     *surface;
    int                    width, height;
    bool                   mapped;
} bledos_client_t;

typedef struct bledos_compositor {
    struct wl_display      *wl_display;
    struct wlr_backend     *backend;
    struct wlr_renderer    *renderer;
    struct wlr_allocator   *allocator;
    struct wlr_compositor  *compositor;
    struct wlr_scene       *scene;
    struct wlr_seat        *seat;
    struct wlr_xdg_shell   *xdg_shell;

    struct wl_listener     new_xdg_surface;
    struct wl_listener     new_output;

    bledos_client_t        clients[MAX_CLIENTS];
    int                    client_count;
    client_id_t            next_client_id;
    bledos_client_t        *focused_client;

    int                    control_fd;      /* Unix domain socket for commands */
    int                    input_fd;        /* Unix domain socket for input events */
    struct wl_event_source *control_source;
    struct wl_event_source *input_source;
} bledos_compositor_t;

static bledos_compositor_t g_compositor = {0};

/* ─── Client Management ────────────────────────────────────────── */

static bledos_client_t *
find_client_by_surface(struct wlr_surface *surface)
{
    for (int i = 0; i < g_compositor.client_count; i++) {
        if (g_compositor.clients[i].surface == surface && g_compositor.clients[i].mapped) {
            return &g_compositor.clients[i];
        }
    }
    return NULL;
}

static bledos_client_t *
find_client_by_id(client_id_t id)
{
    for (int i = 0; i < g_compositor.client_count; i++) {
        if (g_compositor.clients[i].id == id) {
            return &g_compositor.clients[i];
        }
    }
    return NULL;
}

static void
remove_client(bledos_client_t *client)
{
    if (!client || !client->mapped) return;
    client->mapped = false;

    if (g_compositor.focused_client == client) {
        g_compositor.focused_client = NULL;
    }

    wlr_log(WLR_INFO, "Client %u (%s) destroyed", client->id, client->title);
}

/* ─── XDG Surface Handlers ─────────────────────────────────────── */

static void
xdg_surface_destroy(struct wl_listener *listener, void *data)
{
    bledos_client_t *client = wl_container_of(listener, client, destroy);
    remove_client(client);
}

static void
new_xdg_surface(struct wl_listener *listener, void *data)
{
    struct wlr_xdg_surface *xdg_surface = data;

    if (xdg_surface->role != WLR_XDG_SURFACE_ROLE_TOPLEVEL) {
        return;
    }

    /* Allocate a new client slot */
    if (g_compositor.client_count >= MAX_CLIENTS) {
        wlr_log(WLR_ERROR, "Maximum client count reached, rejecting");
        return;
    }

    bledos_client_t *client = &g_compositor.clients[g_compositor.client_count];
    memset(client, 0, sizeof(*client));

    client->id = g_compositor.next_client_id++;
    client->xdg_surface = xdg_surface;
    client->surface = xdg_surface->surface;
    client->mapped = true;
    client->pid = -1; /* TODO: get PID from wl_client */

    /* Get title */
    const char *title = xdg_surface->toplevel->title;
    if (title) {
        strncpy(client->title, title, sizeof(client->title) - 1);
    } else {
        snprintf(client->title, sizeof(client->title), "Client %u", client->id);
    }

    /* Listen for destruction */
    client->destroy.notify = xdg_surface_destroy;
    wl_signal_add(&xdg_surface->events.destroy, &client->destroy);

    /* Add to scene graph for rendering */
    struct wlr_scene_tree *tree = wlr_scene_xdg_surface_create(
        &g_compositor.scene->tree, xdg_surface);
    if (!tree) {
        wlr_log(WLR_ERROR, "Failed to create scene node for client %u", client->id);
        return;
    }

    /* Set initial size */
    struct wlr_box geo;
    wlr_xdg_surface_get_geometry(xdg_surface, &geo);
    client->width = geo.width > 0 ? geo.width : 800;
    client->height = geo.height > 0 ? geo.height : 600;

    g_compositor.client_count++;

    wlr_log(WLR_INFO, "New client %u: %s (%dx%d)",
            client->id, client->title, client->width, client->height);

    /* Notify the BledOS Shell via the control socket */
    /* TODO: Send JSON event notification */
}

/* ─── Control Socket Protocol ──────────────────────────────────── */

static void
send_response(int fd, const char *json_str)
{
    size_t len = strlen(json_str);
    send(fd, json_str, len, MSG_NOSIGNAL);
    send(fd, "\n", 1, MSG_NOSIGNAL);
}

static void
handle_list_clients(int fd)
{
    json_object *root = json_object_new_object();
    json_object *status = json_object_new_string("ok");
    json_object *clients_arr = json_object_new_array();

    for (int i = 0; i < g_compositor.client_count; i++) {
        bledos_client_t *c = &g_compositor.clients[i];
        if (!c->mapped) continue;

        json_object *obj = json_object_new_object();
        json_object *cid = json_object_new_int(c->id);
        json_object *title = json_object_new_string(c->title);
        json_object *pid = json_object_new_int(c->pid);

        json_object *size_arr = json_object_new_array();
        json_object_array_add(size_arr, json_object_new_int(c->width));
        json_object_array_add(size_arr, json_object_new_int(c->height));

        json_object_object_add(obj, "client_id", cid);
        json_object_object_add(obj, "title", title);
        json_object_object_add(obj, "pid", pid);
        json_object_object_add(obj, "size", size_arr);

        json_object_array_add(clients_arr, obj);
    }

    json_object_object_add(root, "status", status);
    json_object_object_add(root, "clients", clients_arr);

    const char *json_str = json_object_to_json_string(root);
    send_response(fd, json_str);

    json_object_put(root);
}

static void
handle_close_client(int fd, client_id_t id)
{
    json_object *root = json_object_new_object();

    bledos_client_t *client = find_client_by_id(id);
    if (!client || !client->mapped) {
        json_object_object_add(root, "status", json_object_new_string("error"));
        json_object_object_add(root, "message", json_object_new_string("Client not found"));
    } else {
        /* Send close event to the client */
        wlr_xdg_toplevel_send_close(client->xdg_surface->toplevel);
        json_object_object_add(root, "status", json_object_new_string("ok"));
    }

    const char *json_str = json_object_to_json_string(root);
    send_response(fd, json_str);
    json_object_put(root);
}

static void
handle_set_focus(client_id_t id)
{
    bledos_client_t *client = find_client_by_id(id);
    if (client && client->mapped) {
        g_compositor.focused_client = client;
        wlr_seat_keyboard_notify_enter(
            g_compositor.seat,
            client->surface,
            NULL, 0, NULL);
        wlr_log(WLR_INFO, "Focus set to client %u", id);
    }
}

static int
on_control_data(int fd, uint32_t mask, void *data)
{
    char buf[CMD_BUF_SIZE];
    ssize_t n = recv(fd, buf, sizeof(buf) - 1, 0);
    if (n <= 0) {
        /* Connection closed or error */
        wl_event_source_remove(g_compositor.control_source);
        close(fd);
        return 0;
    }
    buf[n] = '\0';

    /* Parse JSON command */
    json_object *root = json_object_from_string(buf);
    if (!root) {
        const char *err = "{\"status\":\"error\",\"message\":\"Invalid JSON\"}";
        send_response(fd, err);
        return 0;
    }

    json_object *cmd_obj;
    if (!json_object_object_get_ex(root, "cmd", &cmd_obj)) {
        const char *err = "{\"status\":\"error\",\"message\":\"Missing cmd field\"}";
        send_response(fd, err);
        json_object_put(root);
        return 0;
    }

    const char *cmd = json_object_get_string(cmd_obj);

    if (strcmp(cmd, "list_clients") == 0) {
        handle_list_clients(fd);
    } else if (strcmp(cmd, "close") == 0) {
        json_object *cid_obj;
        if (json_object_object_get_ex(root, "client_id", &cid_obj)) {
            handle_close_client(fd, (client_id_t)json_object_get_int(cid_obj));
        }
    } else if (strcmp(cmd, "set_focus") == 0) {
        json_object *cid_obj;
        if (json_object_object_get_ex(root, "client_id", &cid_obj)) {
            handle_set_focus((client_id_t)json_object_get_int(cid_obj));
        }
    } else if (strcmp(cmd, "ping") == 0) {
        send_response(fd, "{\"status\":\"ok\",\"message\":\"pong\"}");
    } else {
        char errbuf[256];
        snprintf(errbuf, sizeof(errbuf),
                 "{\"status\":\"error\",\"message\":\"Unknown command: %s\"}", cmd);
        send_response(fd, errbuf);
    }

    json_object_put(root);
    return 0;
}

static int
on_control_connect(int fd, uint32_t mask, void *data)
{
    struct sockaddr_un addr;
    socklen_t len = sizeof(addr);
    int client_fd = accept(fd, (struct sockaddr *)&addr, &len);
    if (client_fd < 0) {
        wlr_log(WLR_ERROR, "Failed to accept control connection: %s", strerror(errno));
        return 0;
    }

    wlr_log(WLR_INFO, "BledOS Shell connected to control socket");

    /* Add the client fd to the event loop */
    struct wl_event_loop *loop = wl_display_get_event_loop(g_compositor.wl_display);
    g_compositor.control_source = wl_event_loop_add_fd(
        loop, client_fd, WL_EVENT_READABLE, on_control_data, NULL);

    return 0;
}

static int
on_input_data(int fd, uint32_t mask, void *data)
{
    /* Read binary input events and forward to the focused Wayland client */
    uint8_t type;
    ssize_t n = recv(fd, &type, 1, MSG_DONTWAIT);
    if (n <= 0) return 0;

    /* TODO: Implement full input event parsing and forwarding.
     * Event format:
     *   [1 byte: type] [4 bytes: timestamp] [variable: data]
     *
     * Types:
     *   0x01 = MOUSE_MOVE     (4+4 bytes: x, y)
     *   0x02 = MOUSE_BUTTON   (1+1 bytes: button, state)
     *   0x03 = KEYBOARD_KEY   (4+1 bytes: keycode, state)
     *   0x04 = MOUSE_SCROLL   (4+4 bytes: dx, dy)
     *   0x05 = FOCUS_CHANGE   (4 bytes: client_id)
     */

    return 0;
}

/* ─── Socket Setup ─────────────────────────────────────────────── */

static int
create_unix_socket(const char *path)
{
    struct sockaddr_un addr;
    int fd;

    unlink(path); /* Remove stale socket */

    fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        wlr_log(WLR_ERROR, "Failed to create socket %s: %s", path, strerror(errno));
        return -1;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        wlr_log(WLR_ERROR, "Failed to bind socket %s: %s", path, strerror(errno));
        close(fd);
        return -1;
    }

    if (listen(fd, 5) < 0) {
        wlr_log(WLR_ERROR, "Failed to listen on socket %s: %s", path, strerror(errno));
        close(fd);
        return -1;
    }

    /* Set permissions */
    chmod(path, 0660);

    wlr_log(WLR_INFO, "Listening on %s", path);
    return fd;
}

/* ─── Output Handler ───────────────────────────────────────────── */

static void
new_output(struct wl_listener *listener, void *data)
{
    struct wlr_output *wlr_output = data;

    wlr_output_init_render(wlr_output, g_compositor.allocator, g_compositor.renderer);

    struct wlr_output_state state;
    wlr_output_state_init(&state);
    wlr_output_state_set_enabled(&state, true);

    struct wlr_output_mode *mode = wlr_output_preferred_mode(wlr_output);
    if (mode) {
        wlr_output_state_set_mode(&state, mode);
    }

    if (!wlr_output_commit_state(wlr_output, &state)) {
        wlr_log(WLR_ERROR, "Failed to commit output state");
    }
    wlr_output_state_finish(&state);

    wlr_output_create_global(wlr_output);
    wlr_log(WLR_INFO, "New output: %s", wlr_output->name);
}

/* ─── Main ─────────────────────────────────────────────────────── */

int
main(int argc, char *argv[])
{
    wlr_log_init(WLR_DEBUG, NULL);
    wlr_log(WLR_INFO, "BledOS Compositor starting...");

    /* Create Wayland display */
    g_compositor.wl_display = wl_display_create();
    if (!g_compositor.wl_display) {
        wlr_log(WLR_ERROR, "Failed to create Wayland display");
        return 1;
    }

    /* Create backend (headless for development; DRM for production) */
    g_compositor.backend = wlr_headless_backend_create(g_compositor.wl_display);
    /* For production: g_compositor.backend = wlr_backend_autocreate(g_compositor.wl_display, NULL); */
    if (!g_compositor.backend) {
        wlr_log(WLR_ERROR, "Failed to create backend");
        return 1;
    }

    /* Create renderer */
    g_compositor.renderer = wlr_renderer_autocreate(g_compositor.backend);
    if (!g_compositor.renderer) {
        wlr_log(WLR_ERROR, "Failed to create renderer");
        return 1;
    }
    wlr_renderer_init_wl_display(g_compositor.renderer, g_compositor.wl_display);

    /* Create allocator */
    g_compositor.allocator = wlr_allocator_autocreate(
        g_compositor.backend, g_compositor.renderer);
    if (!g_compositor.allocator) {
        wlr_log(WLR_ERROR, "Failed to create allocator");
        return 1;
    }

    /* Create scene graph */
    g_compositor.scene = wlr_scene_create();
    if (!g_compositor.scene) {
        wlr_log(WLR_ERROR, "Failed to create scene");
        return 1;
    }

    /* Create compositor and sub-compositor */
    g_compositor.compositor = wlr_compositor_create(
        g_compositor.wl_display, 5, g_compositor.renderer);
    wlr_subcompositor_create(g_compositor.wl_display);
    wlr_data_device_manager_create(g_compositor.wl_display);

    /* Create XDG shell */
    g_compositor.xdg_shell = wlr_xdg_shell_create(g_compositor.wl_display, 3);
    g_compositor.new_xdg_surface.notify = new_xdg_surface;
    wl_signal_add(&g_compositor.xdg_shell->events.new_surface, &g_compositor.new_xdg_surface);

    /* Create seat */
    g_compositor.seat = wlr_seat_create(g_compositor.wl_display, "seat0");
    wlr_seat_set_capabilities(g_compositor.seat,
        WL_SEAT_CAPABILITY_POINTER | WL_SEAT_CAPABILITY_KEYBOARD);

    /* Set up output handler */
    g_compositor.new_output.notify = new_output;
    wl_signal_add(&g_compositor.backend->events.new_output, &g_compositor.new_output);

    /* Create control socket */
    g_compositor.control_fd = create_unix_socket(BLEDOS_SOCK_PATH);
    if (g_compositor.control_fd < 0) {
        return 1;
    }

    /* Create input socket */
    g_compositor.input_fd = create_unix_socket(BLEDOS_INPUT_PATH);
    if (g_compositor.input_fd < 0) {
        return 1;
    }

    /* Add sockets to the event loop */
    struct wl_event_loop *loop = wl_display_get_event_loop(g_compositor.wl_display);
    wl_event_loop_add_fd(loop, g_compositor.control_fd, WL_EVENT_READABLE,
                         on_control_connect, NULL);
    wl_event_loop_add_fd(loop, g_compositor.input_fd, WL_EVENT_READABLE,
                         on_input_data, NULL);

    /* Start backend */
    if (!wlr_backend_start(g_compositor.backend)) {
        wlr_log(WLR_ERROR, "Failed to start backend");
        return 1;
    }

    /* Set WAYLAND_DISPLAY for clients */
    const char *socket_name = wl_display_add_socket_auto(g_compositor.wl_display);
    if (!socket_name) {
        wlr_log(WLR_ERROR, "Failed to create Wayland socket");
        return 1;
    }
    setenv("WAYLAND_DISPLAY", socket_name, 1);

    wlr_log(WLR_INFO, "BledOS Compositor running on WAYLAND_DISPLAY=%s", socket_name);
    wlr_log(WLR_INFO, "Control socket: %s", BLEDOS_SOCK_PATH);
    wlr_log(WLR_INFO, "Input socket: %s", BLEDOS_INPUT_PATH);

    /* Run the event loop */
    wl_display_run(g_compositor.wl_display);

    /* Cleanup */
    wl_display_destroy_clients(g_compositor.wl_display);
    wl_display_destroy(g_compositor.wl_display);
    unlink(BLEDOS_SOCK_PATH);
    unlink(BLEDOS_INPUT_PATH);

    return 0;
}