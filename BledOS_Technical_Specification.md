# BledOS Technical Specification
## Building a Full-Fledged Operating System with Blender 3D as the Desktop Environment

**Version:** 0.1.0 (Draft)  
**Date:** June 2025  
**Status:** Pre-Development Design Document

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Vision & Philosophy](#2-vision--philosophy)
3. [Feasibility Analysis](#3-feasibility-analysis)
4. [System Architecture](#4-system-architecture)
5. [The BledOS Shell](#5-the-bledos-shell)
6. [Window Management System](#6-window-management-system)
7. [Inter-Process Communication](#7-inter-process-communication)
8. [Core OS Services](#8-core-os-services)
9. [Application Model](#9-application-model)
10. [Security Model](#10-security-model)
11. [Build System & Distribution](#11-build-system--distribution)
12. [Proof of Concept Roadmap](#12-proof-of-concept-roadmap)
13. [Technical Challenges & Mitigations](#13-technical-challenges--mitigations)
14. [Hardware Requirements](#14-hardware-requirements)
15. [Appendices](#15-appendices)

---

## 1. Executive Summary

BledOS is a Linux-based operating system that replaces the traditional desktop environment with Blender 3D as its primary user interface layer. Unlike a kiosk mode that simply locks a user into a single application, BledOS is designed as a fully functional operating system where Blender serves as the compositor, window manager, file manager, application launcher, and system settings interface—all while retaining Blender's native 3D creation capabilities. The result is an operating system where the boundary between "using a computer" and "creating in 3D" dissolves entirely.

The system is built on a minimal Linux foundation (Arch Linux), uses a custom Wayland compositor based on wlroots that delegates all rendering and interaction to Blender, and leverages Blender's Python API (bpy), Application Templates, and the GHOST window abstraction layer to create a cohesive desktop experience. External applications (terminals, web browsers, editors) run as Wayland clients whose surfaces are captured and composited as textures within Blender's 3D viewport, allowing them to exist as objects in 3D space alongside native Blender tools.

This document specifies the architecture, component design, communication protocols, build system, and development roadmap for BledOS.

---

## 2. Vision & Philosophy

### 2.1 Core Concept

Traditional operating systems present a 2D desktop metaphor: flat windows on a flat screen. BledOS rejects this limitation. By using Blender as the OS interface, the entire computer becomes a 3D workspace where:

- Files and directories are 3D objects with spatial relationships
- Applications exist as panels, screens, or objects positioned in 3D space
- The user navigates their computing environment using Blender's industry-standard 3D navigation (orbit, pan, zoom, fly/walk)
- System utilities are Blender add-ons with custom panels
- Multiple virtual workspaces are literal 3D scenes you can fly between
- The full power of Blender's modeling, animation, and rendering pipeline is always one keystroke away

### 2.2 Design Principles

**Spatial Computing First.** Every element of the OS interface should leverage the third dimension. The Z-axis is not decorative; it is functional. Windows can be angled, stacked, and arranged in 3D space for depth-based organization.

**Blender Native, Not Blended.** BledOS does not fight Blender's UI paradigm—it extends it. The OS shell is a Blender workspace. System operations use Blender's operator system. The keymap is Blender's keymap. Users who know Blender already know 80% of BledOS.

**Progressive Disclosure.** A new user sees a clean desktop. A power user sees the full Blender interface. The system scales from "I just want to browse files" to "I'm building a procedural city with geometry nodes" without mode-switching.

**Open and Extensible.** All OS functionality is implemented as Blender add-ons using the Python API. Anyone can extend or replace any component of the shell.

---

## 3. Feasibility Analysis

### 3.1 Why This Can Work

**Blender's Application Template System.** Blender natively supports Application Templates—custom startup configurations that can completely redefine the workspace layout, available editors, and add-on set. This is Blender's built-in mechanism for creating domain-specific distributions (similar to how Blender already ships with templates for Sculpting, VFX, and Video Editing). BledOS is, at its core, a Blender Application Template called "BledOS" that replaces the default workspace with OS-specific workspaces.

**Blender as a Python Module (bpy).** Blender can be compiled as a Python importable module (`import bpy`). This means the Blender runtime can be embedded within a larger Python application, which in turn can manage system services, D-Bus communication, and process lifecycle. The BledOS init system launches a Python orchestrator that imports bpy, loads the BledOS template, and begins rendering.

**GHOST Abstraction Layer.** Blender's platform abstraction library, GHOST (General Handy Operating System Toolkit), handles all window management, input events, and display server communication. GHOST already supports X11, Wayland, and DRM/KMS directly. For BledOS, a custom GHOST backend can be written that connects directly to the wlroots-based compositor, bypassing the need for a separate X11 or Wayland client relationship—Blender effectively becomes the compositor itself.

**Blender's Python API Completeness.** The bpy API provides access to virtually every Blender feature: UI layout, event handling, property definitions, operators, mesh data, scene graph, rendering, and more. Combined with Python's standard library (subprocess, socket, json, pathlib, asyncio), this is sufficient to implement all OS shell functionality without C/C++ modifications to Blender itself.

**Blender's GPU Module.** The `gpu` Python module provides direct access to OpenGL/Vulkan rendering, custom shaders, framebuffers, and offscreen rendering. This is the mechanism by which external application surfaces (captured as textures) are composited into the 3D viewport.

### 3.2 What Makes This Hard

**Blender Was Not Designed as a Shell.** Blender is a content creation application, not a desktop environment. It does not natively support: embedding foreign application windows, managing multiple independent process lifecycles, responding to system-level events (network changes, battery status, USB insertion), or providing a file dialog for non-Blender file types. Every one of these capabilities must be built as add-on code.

**No Native Wayland Compositor Integration.** Blender is a Wayland client, not a Wayland compositor. To make Blender the compositor, we must either: (a) run a minimal wlroots compositor that delegates all rendering to Blender, or (b) modify Blender's GHOST backend to act as a Wayland compositor. Option (a) is more feasible for the initial prototype.

**Input Routing Complexity.** When external applications are rendered as textures in Blender's viewport, keyboard and mouse events must be intercepted by Blender, routed to the correct application based on which texture the user clicked, and translated into Wayland input events for that client. This requires a custom input multiplexer.

**Performance Overhead.** Running a full desktop environment inside a 3D rendering engine introduces overhead. Blender's viewport rendering, Python scripting, and texture compositing add latency compared to a native Wayland compositor like Sway or Hyprland.

### 3.3 Verdict

BledOS is technically feasible with the following constraints: it requires a custom wlroots-based compositor as an intermediary layer (at least initially), it depends heavily on Blender's Python API for all OS functionality, and it will have higher resource requirements than traditional desktop environments. The project is ambitious but grounded in existing, well-documented technologies.

---

## 4. System Architecture

### 4.1 Layer Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER SPACE                               │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    BledOS Shell (Blender)                    │ │
│  │                                                               │ │
│  │  ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐ │ │
│  │  │ BledOS    │ │ BledOS   │ │ BledOS   │ │ External App  │ │ │
│  │  │ File      │ │ Terminal │ │ Settings │ │ Compositor    │ │ │
│  │  │ Manager   │ │ Emulator │ │ Panel    │ │ (gpu module)  │ │ │
│  │  └───────────┘ └──────────┘ └──────────┘ └───────────────┘ │ │
│  │                                                               │ │
│  │  ┌─────────────────────────────────────────────────────────┐ │ │
│  │  │            Blender Application Template: BledOS         │ │ │
│  │  │  (startup.blend + add-ons + workspace definitions)      │ │ │
│  │  └─────────────────────────────────────────────────────────┘ │ │
│  │                                                               │ │
│  │  ┌─────────────────────────────────────────────────────────┐ │ │
│  │  │            Blender Runtime (bpy + GHOST + GPU)           │ │ │
│  │  └─────────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                              │                                    │
│                              │ shared memory / Wayland protocol   │
│                              ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              BledOS Compositor (wlroots-based)               │ │
│  │                                                               │ │
│  │  • Manages Wayland clients (external apps)                   │ │
│  │  • Captures client surfaces as DMA-BUF textures             │ │
│  │  • Routes input events from Blender to clients              │ │
│  │  • Exposes compositor API over Unix socket                  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                              │                                    │
│                              │ D-Bus / Unix sockets               │
│                              ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                BledOS System Services                         │ │
│  │                                                               │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │ │
│  │  │ Network  │ │ Power    │ │ Audio    │ │ Mount        │  │ │
│  │  │ Manager  │ │ Manager  │ │ (PipeW.) │ │ Manager      │  │ │
│  │  │ (NM/iwd) │ │ (UPower) │ │          │ │ (udisks2)    │  │ │
│  │  └──────────┘ └──────────┘ └──────────┘ ┌──────────────┘  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                              │                                    │
│                              ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              Linux Kernel (standard Arch kernel)              │ │
│  │              DRM/KMS · evdev · ALSA · netfilter              │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Component Responsibilities

**Linux Kernel.** Standard Arch Linux kernel with no custom modifications. Provides hardware abstraction, process scheduling, memory management, filesystem support, and device drivers.

**BledOS System Services.** Standard Linux system daemons (NetworkManager, UPower, PipeWire, udisks2, systemd-logind, dbus-daemon) managed by a minimal init system. These services expose their functionality over D-Bus, which the BledOS Shell accesses via Python's `dbus-python` or `pydbus` libraries.

**BledOS Compositor.** A lightweight Wayland compositor built on the wlroots library (written in C, approximately 2000–4000 lines of code). Its sole purpose is to manage Wayland client surfaces and make them available to Blender. It does not render anything itself—it delegates all rendering to Blender. It communicates with the BledOS Shell via a custom Unix domain socket protocol and shared memory (DMA-BUF file descriptors). Key responsibilities:

1. Accept Wayland client connections and manage their surfaces
2. Export each client's surface as a DMA-BUF file descriptor that Blender can import as an OpenGL/Vulkan texture
3. Accept input event forwarding from Blender (mouse position, keyboard state, focus changes) and route them to the appropriate Wayland client
4. Provide a control API over Unix socket for listing clients, resizing surfaces, closing applications, and managing outputs

**BledOS Shell (Blender).** The heart of the system. This is a standard Blender runtime launched with the `--app-template BledOS` flag, which loads the BledOS Application Template. The template configures:

1. Custom workspaces (Desktop, Files, Terminal, Settings, Create)
2. Auto-loading add-ons that implement OS shell functionality
3. A custom splash screen that replaces Blender's default
4. A modified keymap that adds OS-level shortcuts (e.g., Super+T for new terminal)
5. A custom theme optimized for daily computing (larger fonts, high-contrast elements)

### 4.3 Boot Sequence

The BledOS boot sequence proceeds as follows:

1. **Kernel loads** from the boot loader (GRUB or systemd-boot).
2. **initramfs** mounts the root filesystem.
3. **systemd** starts as PID 1 and begins service management.
4. **Multi-user target** activates core system services: D-Bus, NetworkManager, PipeWire, UPower, udisks2, dbus-daemon.
5. **bledos-compositor.service** starts the BledOS Compositor on the primary DRM output (using wlroots' DRM backend). At this point, the screen is black—no rendering occurs yet.
6. **bledos-shell.service** starts Blender with the BledOS application template: `/usr/bin/blender --app-template BledOS --python-expr "import bledos; bledos.start()"`. This connects to the compositor's control socket and begins rendering.
7. **Blender's GHOST backend** connects to the wlroots compositor as the primary rendering surface. The compositor provides Blender with the DRM output for direct scanout.
8. **BledOS Shell add-ons** initialize: the desktop workspace loads, the file manager panel populates, the system tray begins polling D-Bus for network/battery status, and the autostart directory is scanned for user applications.
9. **Login screen** (if configured) appears as a Blender panel overlay. After authentication, the user's desktop workspace is restored from their saved `.blend` file.

---

## 5. The BledOS Shell

### 5.1 Workspaces

BledOS defines five primary workspaces, each mapped to a Blender workspace tab in the top bar:

**Desktop.** The default workspace. Presents a 3D environment (a "room" or "infinite plane") where application windows exist as textured planes positioned in 3D space. A shelf along the bottom holds launchers (like a dock). The top bar shows the system tray (network, battery, clock, volume). This is the user's home base.

**Files.** A full-screen file browser implemented as a custom Blender space type (or a heavily customized File Browser editor). Files and directories are displayed as 3D objects—folders are containers you can "enter" by flying into them, files are objects with type-based icons and metadata. Supports drag-and-drop, multiple selection, and context menus via Blender's operator system.

**Terminal.** A terminal emulator implemented as a Blender add-on that runs PTY subprocesses. Each terminal instance is a panel in the Blender UI. The add-on uses Python's `pty` module to spawn shell processes and renders their output using Blender's text drawing API or the GPU module's custom shader pipeline. Multiple terminals are supported via tabbed panels.

**Settings.** A Blender properties editor replacement that exposes system configuration: network connections, display resolution, audio devices, keyboard layout, user accounts, Bluetooth, and default applications. Each category is a panel in the sidebar, powered by D-Bus calls to the appropriate system service.

**Create.** The full, unmodified Blender 3D viewport with all editors and tools available. This workspace is for 3D content creation—the reason Blender exists. From here, the user has complete access to Blender's modeling, sculpting, animation, rendering, compositing, and geometry nodes systems.

### 5.2 Desktop Workspace: 3D Spatial UI

The Desktop workspace is the most innovative and complex component of BledOS. It replaces the traditional 2D window manager with a 3D spatial environment.

**The Room.** The default scene is a procedurally generated "room"—a floor plane with a subtle grid texture, ambient lighting, and a skybox (HDRI environment). The room can be customized: users can change the floor material, the lighting, the background, or load entirely custom scenes. The room is simply a Blender scene; power users can edit it with Blender's full toolset.

**Application Windows as 3D Objects.** Each running external application (Wayland client) is represented as a textured plane in the 3D scene. The plane's material uses an image texture node whose source is a DMA-BUF imported from the compositor. The plane is positioned in 3D space, can be rotated and scaled with Blender's transform tools, and responds to clicks that are forwarded to the underlying Wayland client.

**The Dock.** A horizontal strip of 3D objects (cubes, spheres, or custom meshes) along the bottom of the viewport, each representing a pinned or running application. Clicking a dock item launches or focuses the application. The dock is implemented as a collection of Blender objects with custom properties that the BledOS Dock add-on reads to determine which application each object represents.

**Window Management in 3D.** Windows (application planes) can be:
- **Moved** by grabbing and dragging in 3D space (using Blender's built-in move tool)
- **Resized** by dragging edge handles (custom gizmos)
- **Minimized** by scaling them down and moving them to the dock
- **Maximized** by snapping them to fill the camera's view
- **Closed** by clicking an X gizmo or via the window's context menu
- **Stacked** by positioning them at different Z-depths
- **Angled** by rotating them for ergonomic viewing or to show depth relationships

**Camera System.** The user's viewpoint is controlled by Blender's camera or walk/fly navigation. The default camera provides a "desk view" looking slightly downward at the application planes. The user can orbit around their workspace, fly to different areas, or switch to orthographic top-down view for overview. Camera bookmarks allow quick navigation between saved viewpoints.

### 5.3 System Tray & Notifications

The system tray lives in Blender's top bar (the `TOPBAR` region). It displays:

- **Network status** (WiFi icon, connection name, signal strength) via NetworkManager D-Bus
- **Battery status** (icon, percentage, charging state) via UPower D-Bus
- **Audio volume** (icon, slider on click) via PipeWire D-Bus (or `pactl`)
- **Clipboard manager** (recent items accessible via dropdown)
- **Clock/Calendar** (current time, date, simple calendar popup)
- **Notification area** (recent notifications from applications)

Notifications are Blender popups (using `bpy.ops.wm.popup_menu` or custom GPU-drawn overlays) that appear briefly and are logged to a notification panel. Applications send notifications via the freedesktop.org Notification specification, which a BledOS D-Bus listener translates into Blender UI events.

---

## 6. Window Management System

### 6.1 Compositor Architecture

The BledOS compositor is a minimal wlroots-based Wayland compositor whose purpose is to manage Wayland client lifecycles and expose their surfaces to Blender. It is intentionally minimal—it does not implement its own rendering, window decoration, or input routing. Those responsibilities belong to the BledOS Shell.

The compositor runs as a separate process from Blender, connected via:

1. **Control Socket** (`/run/bledos/compositor.sock`): A Unix domain socket with a JSON-based protocol for commands like `list-clients`, `get-surface-dmabuf <client-id>`, `resize-surface <client-id> <w> <h>`, `close-client <client-id>`, `set-input-focus <client-id>`.
2. **DMA-BUF File Descriptors**: Passed over the control socket using `SCM_RIGHTS`, these are the actual GPU memory buffers containing each client's rendered surface.
3. **Input Socket** (`/run/bledos/input.sock`): A Unix domain socket through which Blender forwards input events (mouse position, button presses, key events, scroll events) to the compositor for routing to the focused Wayland client.

### 6.2 Surface Capture Pipeline

When an external application (e.g., a web browser) is launched in BledOS:

1. The BledOS Shell add-on calls the compositor's control socket: `launch-app <command>`.
2. The compositor forks the application as a Wayland client. The client connects to the compositor's Wayland display.
3. The client renders its surface into a wlroots-managed buffer.
4. The compositor exports the buffer as a DMA-BUF file descriptor and sends it to Blender via the control socket.
5. The BledOS Shell add-on receives the DMA-BUF fd and creates an OpenGL texture from it using Blender's GPU module: `gpu.texture.create_from_dmabuf(fd, width, height, format)`. (Note: this requires a small extension to Blender's GPU module; alternatively, the texture can be copied via `eglCreateImageKHR` and `glEGLImageTargetTexture2DOES`.)
6. A new plane mesh is created in the 3D scene, and its material uses this texture.
7. On each frame, the texture is refreshed from the DMA-BUF (which the client may have re-rendered into).

### 6.3 Input Forwarding

Input forwarding is the most complex aspect of the window management system. When the user clicks on an application window's textured plane in Blender's 3D viewport:

1. Blender's event system reports a mouse click at screen coordinates (sx, sy).
2. The BledOS Input Router add-on performs a raycast from the camera through the click point into the 3D scene.
3. If the ray hits an object that represents an external application (identified by a custom Blender property like `bledos_client_id`), the hit point's UV coordinates are computed.
4. The UV coordinates are mapped to the application's surface coordinates: `(app_x, app_y) = (uv.x * surface_width, uv.y * surface_height)`.
5. The input event (with translated coordinates) is sent over the input socket to the compositor.
6. The compositor forwards the event to the appropriate Wayland client via the Wayland protocol.
7. Keyboard events are simpler: they are sent to whichever client currently has input focus (tracked by the BledOS Shell).

### 6.4 Tiling and Floating Modes

BledOS supports two window arrangement modes in the Desktop workspace:

**Floating Mode (default).** Application planes are freely positioned in 3D space. The user arranges them manually. This is the natural mode for a 3D spatial interface.

**Tiling Mode.** Application planes are automatically arranged in a grid or column layout on a virtual "wall" in the 3D scene. This provides familiar tiling-window-manager ergonomics within the 3D environment. Tiling is implemented as a Blender add-on that adjusts object positions and scales based on layout algorithms.

---

## 7. Inter-Process Communication

### 7.1 Communication Matrix

| From | To | Protocol | Purpose |
|------|------|----------|---------|
| BledOS Shell | Compositor | Unix socket (JSON) | Launch/close apps, get surface buffers |
| BledOS Shell | System Services | D-Bus | Network, power, audio, mount management |
| BledOS Shell | Compositor | Unix socket (binary) | Forward input events to clients |
| Compositor | BledOS Shell | Unix socket (JSON + fd) | Surface updates, client lifecycle events |
| BledOS Shell | Blender | bpy Python API | UI updates, scene manipulation, operators |
| External Apps | Compositor | Wayland protocol | Standard Wayland client communication |
| BledOS Shell | Notifications | D-Bus (freedesktop) | Receive and display app notifications |

### 7.2 Compositor Control Protocol

The compositor control socket uses a simple JSON-based request-response protocol:

**Launch Application:**
```json
→ {"cmd": "launch", "exec": "firefox", "env": {"DISPLAY": "", "WAYLAND_DISPLAY": "bledos-0"}}
← {"status": "ok", "client_id": "c42", "pid": 12345}
```

**Get Surface Buffer:**
```json
→ {"cmd": "get_surface", "client_id": "c42"}
← {"status": "ok", "width": 1920, "height": 1080, "format": "ARGB8888", "dmabuf_fd": 7}
```
(The DMA-BUF file descriptor is sent as an ancillary message with `SCM_RIGHTS`.)

**List Clients:**
```json
→ {"cmd": "list_clients"}
← {"status": "ok", "clients": [{"client_id": "c42", "title": "Firefox", "pid": 12345, "size": [1920, 1080]}]}
```

**Close Client:**
```json
→ {"cmd": "close", "client_id": "c42"}
← {"status": "ok"}
```

**Set Input Focus:**
```json
→ {"cmd": "set_focus", "client_id": "c42"}
← {"status": "ok"}
```

**Subscribe to Events:**
```json
→ {"cmd": "subscribe", "events": ["client_created", "client_destroyed", "surface_updated"]}
← {"status": "ok"}
```
(Event notifications are pushed asynchronously on the same socket.)

### 7.3 Input Event Protocol

Input events are sent over a dedicated Unix socket in a compact binary format:

```
[1 byte: event type] [4 bytes: timestamp] [variable: event data]

Event types:
0x01 = MOUSE_MOVE     (4 bytes: x, 4 bytes: y)
0x02 = MOUSE_BUTTON   (1 byte: button, 1 byte: state)
0x03 = KEYBOARD_KEY   (4 bytes: keycode, 1 byte: state)
0x04 = MOUSE_SCROLL   (4 bytes: dx, 4 bytes: dy)
0x05 = FOCUS_CHANGE   (4 bytes: client_id)
```

### 7.4 D-Bus Integration

The BledOS Shell communicates with system services over D-Bus using Python's `pydbus` library. Key integrations:

**NetworkManager (`org.freedesktop.NetworkManager`):**
- List WiFi networks, get connection status, connect/disconnect
- Exposed in the Settings workspace and system tray

**UPower (`org.freedesktop.UPower`):**
- Battery percentage, charging state, time remaining
- Exposed in the system tray

**PipeWire (`org.freedesktop.portal.Desktop`):**
- Audio volume control, device selection
- Screen sharing (for video calls within embedded browser windows)

**udisks2 (`org.freedesktop.UDisks2`):**
- Mount/unmount USB drives, display storage device information
- Auto-mount notifications via D-Bus

**logind (`org.freedesktop.login1`):**
- Session management, screen locking, suspend/hibernate/shutdown
- Power menu in the system tray

---

## 8. Core OS Services

### 8.1 Init System

BledOS uses systemd as its init system, inherited from Arch Linux. Custom BledOS service units include:

- `bledos-compositor.service`: Starts the BledOS Compositor on the primary GPU output
- `bledos-shell.service`: Starts Blender with the BledOS template (depends on compositor)
- `bledos-first-setup.service`: One-shot service for initial system configuration (user creation, locale, timezone)

### 8.2 Package Management

BledOS uses Arch Linux's pacman package manager. Software installation is exposed through:

1. **Blender Terminal**: Users can run `pacman -S <package>` directly
2. **BledOS Software Center**: A Blender add-on that wraps `pacman` with a graphical interface—searching, browsing categories, installing, and removing packages. Package metadata is fetched from the Arch repositories via `pyalpm`.
3. **File Association**: `.pkg.tar.zst` files opened from the file manager trigger the Software Center add-on

### 8.3 Audio

PipeWire provides the audio subsystem, with WirePlumber as the session manager. The BledOS Settings add-on exposes volume controls per-application and per-device. Audio from external applications (browsers, media players) flows through PipeWire naturally, as they are standard Linux processes.

### 8.4 Networking

NetworkManager manages network connections. The BledOS Settings add-on provides a WiFi scanner and connection editor. VPN support is available through NetworkManager's VPN plugins. Network status is displayed in the system tray.

### 8.5 Storage & Mounting

udisks2 handles automatic mounting of USB drives and other removable media. When a drive is inserted, a notification appears, and the drive appears in the Files workspace. The BledOS Mount Manager add-on listens for udisks2 D-Bus events and updates the Blender scene accordingly.

---

## 9. Application Model

### 9.1 Native BledOS Applications

Native BledOS applications are Blender add-ons. They have full access to the bpy API, can create custom panels, operators, and UI elements, and can manipulate the 3D scene directly. Examples of native applications:

- **BledOS File Manager**: Navigates the filesystem, opens files, manages bookmarks
- **BledOS Terminal**: Runs PTY subprocesses, renders terminal output
- **BledOS Image Viewer**: Displays images on textured planes in 3D space
- **BledOS Text Editor**: A simplified text editor using Blender's Text editor
- **BledOS Calculator**: A panel-based calculator
- **BledOS System Monitor**: Displays CPU, RAM, disk, and network usage as animated 3D graphs

Native applications are installed as Blender add-ons in `/usr/share/blender/BledOS/scripts/addons/` (system-wide) or `~/.config/blender/BledOS/scripts/addons/` (per-user).

### 9.2 External Applications (Wayland Clients)

External applications are standard Linux applications that connect to the BledOS Compositor as Wayland clients. They are rendered as textured planes in the 3D scene. Examples:

- **Firefox**: Web browsing via a textured plane
- **LibreOffice**: Office suite via textured planes
- **Alacritty / Kitty**: GPU-accelerated terminal emulators (alternative to the native terminal)
- **VS Code**: Code editor via textured plane
- **MPV**: Media player via textured plane (with hardware-accelerated video decoding)

External applications are launched from the Dock, the Application Launcher (a Blender menu), or the terminal. They are standard Linux packages installed via pacman.

### 9.3 Application Launcher

The Application Launcher is a Blender operator (`bpy.ops.bledos.app_launcher`) triggered by Super+A (or clicking the BledOS logo in the top bar). It displays a searchable list of installed applications, reading `.desktop` files from standard freedesktop.org locations. Selecting an application either activates its native BledOS add-on or launches it as a Wayland client via the compositor.

---

## 10. Security Model

### 10.1 Process Isolation

BledOS inherits Linux's standard process isolation. External applications run as separate processes with their own UID/GID, namespace isolation, and cgroup resource limits. The BledOS Compositor runs as the logged-in user and only has access to Wayland client surfaces, not the client's memory or filesystem.

### 10.2 Blender Python Sandboxing

Blender's Python interpreter has full access to the user's account (by design—Blender needs filesystem access for saving/loading files). BledOS add-ons that interact with system services should use D-Bus, which provides its own permission layer. There is no Python sandbox within Blender—this is consistent with Blender's design philosophy.

### 10.3 Screen Locking

Screen locking is handled by a BledOS add-on that blanks the 3D scene and displays a password prompt. The add-on is triggered by logind's "Lock" signal (on timeout or lid close). While locked, the Blender event system is captured by the lock screen, preventing interaction with running applications.

### 10.4 Wayland Security

BledOS benefits from Wayland's security model: clients cannot read other clients' surfaces, inject input events into other clients, or access the screen contents without explicit permission (via XDG-desktop-portal).

---

## 11. Build System & Distribution

### 11.1 Base Distribution

BledOS is built on Arch Linux for the following reasons:

1. **Rolling release**: Always up-to-date packages, including the latest Blender
2. **Minimal base**: No pre-installed desktop environment to strip out
3. **Archiso**: Mature, well-documented tool for building custom ISO images
4. **AUR**: Access to the Arch User Repository for niche packages
5. **Bleeding-edge kernels and drivers**: Important for GPU-heavy workloads

### 11.2 ISO Build Process

BledOS ISO images are built using Archiso with the following customization layers:

1. **Base Archiso profile**: Standard releng profile as starting point
2. **Package list** (`packages.x86_64`): Adds blender, wlroots, bledos-compositor, pipeewire, networkmanager, and all required system packages
3. **Custom pacman repository**: Hosts BledOS-specific packages (bledos-compositor, bledos-shell-addons, bledos-default-template)
4. **Overlay filesystem**: Adds systemd service units, configuration files, default user setup, and the BledOS Blender template
5. **Post-install script** (`customize_airootfs.sh`): Configures services, sets default Blender template, creates bledos user, installs GRUB/systemd-boot

### 11.3 BledOS Packages

BledOS distributes the following custom packages:

**`bledos-compositor`** (C + wlroots):
- The minimal Wayland compositor
- Sources: ~2000–4000 lines of C
- Dependencies: wlroots, wayland, libinput, libdrm
- Builds with Meson

**`bledos-shell-addons`** (Python):
- All Blender add-ons that implement the OS shell
- Packages: bledos_filemanager, bledos_terminal, bledos_settings, bledos_dock, bledos_app_launcher, bledos_input_router, bledos_notification, bledos_system_tray, bledos_window_manager, bledos_power
- Dependencies: blender, python-pydbus, python-pyalpm

**`bledos-default-template`** (Blend files + config):
- The BledOS Application Template
- Contains: startup.blend (with Desktop workspace scene), workspace definitions, keymap overrides, theme XML
- Dependencies: bledos-shell-addons

**`bledos-wallpapers`** (HDRIs + scenes):
- Procedural and pre-rendered HDRI environment maps and Blender scenes for the Desktop workspace
- Dependencies: bledos-default-template

### 11.4 Installation

BledOS offers two installation paths:

1. **ISO Installation**: Boot the BledOS ISO, follow the Calamares installer (graphical) or the guided install script (terminal). Installs the full system to disk.
2. **Existing Arch Installation**: Add the BledOS repository to pacman, install `bledos-meta` (a meta-package that pulls in all BledOS components), and configure systemd to start the BledOS compositor and shell instead of a traditional display manager.

---

## 12. Proof of Concept Roadmap

### Phase 0: Feasibility Demonstration (2 weeks)

**Goal:** Prove that Blender can display external application surfaces as textures in its 3D viewport.

1. Write a minimal wlroots compositor (~500 lines) that exports client surfaces as DMA-BUFs
2. Write a Blender add-on that imports a DMA-BUF as a texture and renders it on a plane
3. Launch a simple Wayland client (e.g., `weston-terminal`) and display its output on the plane
4. Forward mouse clicks from Blender to the client via the compositor

**Success criteria:** A terminal window rendered on a 3D plane in Blender that responds to clicks and keyboard input.

### Phase 1: Basic Shell (4 weeks)

**Goal:** Create a bootable ISO that launches into Blender with the BledOS template and basic OS functionality.

1. Build the BledOS compositor with full client management and input forwarding
2. Create the BledOS Application Template with the Desktop workspace
3. Implement the Dock add-on (application launcher)
4. Implement the System Tray add-on (network, battery, clock via D-Bus)
5. Implement the native Terminal add-on (PTY subprocess)
6. Implement the File Manager add-on (basic directory browsing)
7. Build an Archiso-based ISO with all components
8. Test boot in a VM (QEMU/KVM with virtio-gpu)

**Success criteria:** Boot from ISO, see a 3D desktop in Blender, launch a terminal, browse files, see network status.

### Phase 2: Window Management (4 weeks)

**Goal:** Full window management for external applications in the 3D viewport.

1. Implement the Input Router add-on (raycast → UV → Wayland input translation)
2. Implement the Window Manager add-on (move, resize, minimize, maximize, close)
3. Implement tiling mode
4. Implement the Application Launcher (`.desktop` file parser)
5. Add keyboard shortcuts for window management (Super+arrow keys, Alt+Tab, etc.)
6. Test with Firefox, Alacritty, and other common applications

**Success criteria:** Launch Firefox, navigate the web, resize the window, switch between multiple applications.

### Phase 3: System Integration (3 weeks)

**Goal:** Complete integration with system services for daily-driver readiness.

1. Implement the Settings add-on (network, audio, display, keyboard, bluetooth)
2. Implement notifications (freedesktop.org spec via D-Bus)
3. Implement screen locking
4. Implement auto-mounting (udisks2)
5. Implement the Software Center add-on (pacman wrapper)
6. Implement session save/restore (save desktop layout as .blend file)

**Success criteria:** Connect to WiFi, adjust volume, install a package, receive a notification, lock the screen.

### Phase 4: Polish & Distribution (4 weeks)

**Goal:** Production-ready distribution with documentation and installer.

1. Calamares installer integration
2. Default theme and wallpaper pack
3. User documentation and onboarding tutorial
4. Performance optimization (reduce input latency, improve texture refresh rate)
5. Bug fixing and stability testing
6. Release BledOS 0.1.0 ISO

**Success criteria:** A new user can download, install, and use BledOS as their daily driver for basic computing tasks.

---

## 13. Technical Challenges & Mitigations

### 13.1 Input Latency

**Challenge:** Input events must travel from the kernel → compositor → Blender → Python add-on → back to compositor → Wayland client. This adds latency compared to direct compositor → client routing.

**Mitigation:**
- Use binary input protocol (not JSON) for the input socket
- Minimize Python processing in the input hot path (pre-compute raycast acceleration structures)
- Use Blender's `bpy.app.handlers` for frame-synchronized input processing
- Target < 16ms additional latency (one frame at 60fps) for acceptable responsiveness

### 13.2 Texture Refresh Performance

**Challenge:** Each frame, Blender must re-import DMA-BUF textures for all visible applications. With multiple applications at high resolution, this could be expensive.

**Mitigation:**
- Use EGLImage-based texture sharing (zero-copy on GPU)
- Only refresh textures that have been updated (track damage regions from wlroots)
- Limit the number of simultaneously visible applications with textures
- Use lower-resolution textures for backgrounded/minimized windows

### 13.3 Blender Startup Time

**Challenge:** Blender takes several seconds to start, even on fast hardware. A desktop environment should be responsive within 1–2 seconds of login.

**Mitigation:**
- Pre-warm Blender during the boot process (start it before the login screen)
- Use Blender's `--background` mode for initial setup, then switch to full UI
- Optimize the BledOS template to load minimal add-ons on startup, lazy-loading others
- Cache the Blender virtual memory state for fast restore

### 13.4 GPU Driver Compatibility

**Challenge:** DMA-BUF sharing between the compositor and Blender requires compatible GPU drivers and EGL extensions. This works well with Mesa (AMD, Intel) but may have issues with NVIDIA's proprietary driver.

**Mitigation:**
- Target Mesa/GPU drivers as the primary supported platform (AMD, Intel)
- Provide a fallback mode using CPU-based texture copies for NVIDIA
- Long-term: implement NVIDIA-specific paths using their DMA-BUF import extensions
- Document GPU compatibility requirements clearly

### 13.5 Blender Version Coupling

**Challenge:** BledOS add-ons depend on Blender's Python API, which changes between major versions. A Blender update could break the entire shell.

**Mitigation:**
- Pin the Blender version in BledOS packages (do not auto-update)
- Test all add-ons against new Blender versions before updating the package
- Use stable bpy APIs where possible (avoid `bpy.data` version-specific changes)
- Maintain a compatibility shim layer for API changes

### 13.6 Text Rendering in 3D

**Challenge:** Blender's built-in text rendering is designed for 3D text objects, not for crisp 2D text on UI elements. Text in the 3D desktop may look blurry or poorly rendered.

**Mitigation:**
- Use Blender's GPU module for custom 2D text rendering with signed distance field (SDF) fonts
- For system tray and overlays, use Blender's native 2D UI regions (which use proper font rendering)
- Consider integrating a lightweight font rendering library (e.g., Fontstash) via a Python C extension

---

## 14. Hardware Requirements

### Minimum Requirements

| Component | Specification |
|-----------|--------------|
| CPU | 4-core x86_64 processor (Intel Haswell or newer, AMD Zen or newer) |
| RAM | 8 GB DDR4 |
| GPU | OpenGL 4.6 compatible with at least 2 GB VRAM (AMD Radeon RX 560, Intel UHD 630, or equivalent) |
| Storage | 32 GB SSD |
| Display | 1920×1080 @ 60 Hz |
| Input | Keyboard and 3-button mouse (scroll wheel recommended) |

### Recommended Requirements

| Component | Specification |
|-----------|--------------|
| CPU | 8-core x86_64 processor (Intel Coffee Lake or newer, AMD Zen 2 or newer) |
| RAM | 16 GB DDR4 |
| GPU | Vulkan 1.3 compatible with at least 6 GB VRAM (AMD Radeon RX 6700 XT, NVIDIA RTX 3060, or equivalent) |
| Storage | 256 GB NVMe SSD |
| Display | 2560×1440 @ 144 Hz |
| Input | Keyboard, 3-button mouse, and graphics tablet (for Blender sculpting) |

### Notes

- BledOS is GPU-intensive by nature (running a 3D rendering engine as the desktop). Systems with weak GPUs will have a poor experience.
- NVIDIA proprietary drivers are supported on a best-effort basis. Mesa (AMD/Intel) is recommended.
- Multi-monitor support requires additional compositor configuration (not planned for Phase 1).

---

## 15. Appendices

### Appendix A: Key Blender APIs Used

| API | Purpose |
|-----|---------|
| `bpy.types.WorkSpace` | Define custom workspaces (Desktop, Files, Terminal, Settings, Create) |
| `bpy.types.Panel` | Create UI panels for shell components |
| `bpy.types.Operator` | Define custom operators for OS actions (launch app, toggle wifi, etc.) |
| `bpy.types.Menu` | Create custom menus (Application Launcher, power menu) |
| `bpy.app.handlers` | Frame-change handlers for texture refresh and input processing |
| `bpy.props` | Define custom properties for application objects in the scene |
| `gpu.shader` | Custom shaders for 3D window borders, focus highlights, and effects |
| `gpu.texture` | Import DMA-BUF textures from external applications |
| `gpu.framebuffer` | Offscreen rendering for texture compositing |
| `bmesh` | Dynamic mesh creation for window planes and dock items |
| `bpy.ops.view3d` | Camera navigation, fly/walk mode |
| `bpy.types.SpaceView3D` | Custom overlays and drawing in the 3D viewport |
| `mathutils` | Vector math for raycasting, UV mapping, and 3D transforms |

### Appendix B: Key System Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| wlroots | 0.18+ | Wayland compositor framework |
| wayland | 1.22+ | Wayland protocol |
| libinput | 1.24+ | Input device handling |
| libdrm | 2.4+ | DRM/KMS for direct display output |
| Mesa | 24.0+ | OpenGL/Vulkan drivers, EGL, DMA-BUF sharing |
| PipeWire | 1.0+ | Audio routing |
| NetworkManager | 1.44+ | Network management |
| UPower | 0.99+ | Power management |
| udisks2 | 2.10+ | Storage management |
| D-Bus | 1.14+ | Inter-process communication |
| systemd | 255+ | Init and service management |
| Blender | 4.2+ | Desktop environment runtime |

### Appendix C: BledOS Add-on Registry

| Add-on | Blender Module | Description |
|--------|---------------|-------------|
| `bledos_core` | `bledos_core` | Core shell initialization, compositor connection, event loop |
| `bledos_filemanager` | `bledos_filemanager` | File browser with 3D object representation |
| `bledos_terminal` | `bledos_terminal` | Terminal emulator using PTY subprocesses |
| `bledos_settings` | `bledos_settings` | System settings panels (network, audio, display, etc.) |
| `bledos_dock` | `bledos_dock` | Application dock (taskbar) |
| `bledos_app_launcher` | `bledos_app_launcher` | Application launcher menu (`.desktop` parser) |
| `bledos_input_router` | `bledos_input_router` | Input event routing between Blender and Wayland clients |
| `bledos_window_manager` | `bledos_window_manager` | Window management (move, resize, minimize, maximize, close) |
| `bledos_system_tray` | `bledos_system_tray` | System tray (network, battery, clock, volume) |
| `bledos_notification` | `bledos_notification` | Notification display and management |
| `bledos_power` | `bledos_power` | Power management (lock, suspend, shutdown) |
| `bledos_software_center` | `bledos_software_center` | Package manager GUI (pacman wrapper) |
| `bledos_clipboard` | `bledos_clipboard` | Clipboard manager |
| `bledos_mount` | `bledos_mount` | USB drive auto-mounting via udisks2 |
| `bledos_desktop_scene` | `bledos_desktop_scene` | Desktop scene generation and customization |

### Appendix D: References

- Blender Python API Documentation: https://docs.blender.org/api/current/
- Blender Application Templates: https://docs.blender.org/manual/en/latest/advanced/app_templates.html
- Blender as a Python Module: https://docs.blender.org/api/current/info_advanced_blender_as_bpy.html
- Blender Source Code Layout: https://developer.blender.org/docs/features/code_layout/
- wlroots Wayland Compositor Library: https://gitlab.freedesktop.org/wlroots/wlroots
- Wayland Protocol Specification: https://wayland.app/protocols/
- DMA-BUF Sharing: https://docs.kernel.org/driver-api/dma-buf.html
- Archiso Documentation: https://wiki.archlinux.org/title/Archiso
- NetworkManager D-Bus API: https://networkmanager.dev/docs/api/latest/
- freedesktop.org Desktop Entry Specification: https://specifications.freedesktop.org/desktop-entry-spec/latest/
- freedesktop.org Notification Specification: https://specifications.freedesktop.org/notification-spec/latest/

---

*This document is a living specification. As development progresses, each section will be expanded with implementation details, API specifications, and testing criteria. The BledOS project is open source and welcomes contributions from the Blender and Linux communities.*