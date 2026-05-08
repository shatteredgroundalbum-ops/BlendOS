# BledOS — Blender as Operating System

> **A Linux-based operating system that uses Blender 3D as its full-fledged desktop environment.**

BledOS is not a kiosk. It is not a skin. It is a complete operating system where Blender *is* the desktop—the compositor, the window manager, the file browser, the application launcher, and the settings panel—all while retaining the full creative power of Blender's 3D suite. Every file is a 3D object. Every application window exists in three-dimensional space. Your desktop is a scene. Your computer is a viewport.

---

## The Vision

Imagine sitting down at your computer and instead of a flat 2D desktop with flat 2D windows, you see a 3D room. Application windows are textured planes floating in space—you can orbit around them, angle them for ergonomic viewing, stack them at different depths, or fly between entirely different workspace scenes. The dock at the bottom is a collection of 3D objects. The file manager lets you fly into folders. And at any moment, you can switch to Blender's full 3D creation toolset without changing applications—because the desktop *is* Blender.

This is BledOS.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                 BledOS Shell (Blender)                    │
│   Desktop │ Files │ Terminal │ Settings │ Create         │
│   ── Blender Application Template + Python Add-ons ──    │
├─────────────────────────────────────────────────────────┤
│           BledOS Compositor (wlroots-based)              │
│   Wayland client mgmt · DMA-BUF export · Input routing   │
├─────────────────────────────────────────────────────────┤
│             BledOS System Services                       │
│   NetworkManager · PipeWire · UPower · udisks2 · D-Bus   │
├─────────────────────────────────────────────────────────┤
│                Linux Kernel (Arch)                        │
│            DRM/KMS · evdev · ALSA · netfilter            │
└─────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **BledOS Shell** | Blender + Python (bpy) | Desktop environment UI, window management, system tray |
| **BledOS Compositor** | C + wlroots | Wayland client management, surface capture, input routing |
| **BledOS Add-ons** | Python (Blender add-ons) | File manager, terminal, settings, dock, notifications |
| **BledOS Template** | Blender App Template | Workspace definitions, keymaps, theme, startup scene |
| **Base System** | Arch Linux | Kernel, systemd, drivers, packages |

---

## Project Structure

```
BledOS/
├── README.md                              # This file
├── BledOS_Technical_Specification.md      # Full technical specification
├── build-iso.sh                           # ISO build script
│
├── bledos-compositor/                     # Wayland compositor (C + wlroots)
│   ├── meson.build                        # Build configuration
│   └── src/
│       └── main.c                         # Compositor source code
│
├── bledos-shell-addons/                   # Blender add-ons (Python)
│   └── bledos_core/
│       └── __init__.py                    # Core shell add-on
│
├── bledos-default-template/               # Blender application template
│   └── startup.py                         # Template startup script
│
├── bledos-services/                       # systemd service files
│   ├── bledos-compositor.service          # Compositor service
│   └── bledos-shell.service               # Shell service
│
└── bledos-archiso/                        # Archiso ISO configuration
    └── packages.x86_64                    # Package list for ISO
```

---

## Quick Start

### Prerequisites

- Arch Linux host system
- `archiso` package installed (`sudo pacman -S archiso`)
- At least 25 GB free disk space
- Internet connection

### Build the ISO

```bash
# Clone the repository
git clone https://github.com/bledos/bledos.git
cd bledos

# Make the build script executable
chmod +x build-iso.sh

# Build the ISO (runs as root)
sudo ./build-iso.sh
```

### Test in QEMU

```bash
qemu-system-x86_64 \
    -m 4G -smp 4 \
    -enable-kvm \
    -cdrom bledos-iso-output/BledOS-0.1.0-x86_64.iso
```

### Flash to USB

```bash
sudo dd if=bledos-iso-output/BledOS-0.1.0-x86_64.iso \
    of=/dev/sdX bs=4M status=progress && sync
```

---

## The Five Workspaces

| Workspace | Description |
|-----------|-------------|
| **Desktop** | 3D spatial environment with floating app windows, dock, and system tray |
| **Files** | File browser with 3D object representation — fly into folders |
| **Terminal** | Built-in terminal emulator running PTY subprocesses |
| **Settings** | System configuration: network, audio, display, bluetooth, accounts |
| **Create** | Full Blender 3D viewport — modeling, sculpting, animation, rendering |

---

## How It Works

### External Applications in 3D

When you launch an application (like Firefox), it runs as a standard Wayland client connected to the BledOS Compositor. The compositor captures the application's rendered surface as a DMA-BUF texture and sends it to Blender. Blender displays this texture on a 3D plane in the Desktop workspace. When you click on the plane, Blender raycasts the click to determine the UV coordinates, translates them to application surface coordinates, and forwards the input event to the compositor for delivery to the application.

### Native vs. External Apps

- **Native BledOS apps** are Blender add-ons with full access to bpy, the 3D scene, and Blender's UI system. They're fast, integrated, and can manipulate the desktop directly.
- **External apps** are standard Linux Wayland applications (Firefox, LibreOffice, etc.) rendered as textured planes. They work normally but live "inside" the 3D environment.

### System Integration

BledOS uses standard Linux system services (NetworkManager, PipeWire, UPower, udisks2) accessed via D-Bus from Python. The system tray, settings panel, and notifications all communicate with these services through standard freedesktop.org protocols.

---

## Development Roadmap

- [x] Phase 0: Feasibility analysis and technical specification
- [ ] Phase 1: Basic compositor + Blender shell prototype
- [ ] Phase 2: External application rendering and input forwarding
- [ ] Phase 3: System integration (network, audio, power, notifications)
- [ ] Phase 4: Polish, installer, and 0.1.0 release

---

## Technical Requirements

### Minimum

- 4-core x86_64 CPU (Haswell/Zen or newer)
- 8 GB RAM
- GPU with OpenGL 4.6 and 2 GB VRAM (Mesa/AMD or Mesa/Intel)
- 32 GB SSD

### Recommended

- 8-core x86_64 CPU (Coffee Lake/Zen 2 or newer)
- 16 GB RAM
- GPU with Vulkan 1.3 and 6 GB VRAM
- 256 GB NVMe SSD

> **Note:** BledOS is GPU-intensive by nature. Systems with weak GPUs will have a poor experience. AMD and Intel GPUs with Mesa drivers are recommended. NVIDIA proprietary drivers are supported on a best-effort basis.

---

## Contributing

BledOS is open source and welcomes contributions. Areas of particular need:

- **Compositor development** (C + wlroots) — DMA-BUF export, input forwarding
- **Blender add-ons** (Python) — file manager, terminal, settings panels
- **3D assets** — desktop environment models, HDRI maps, themes
- **Testing** — hardware compatibility, application compatibility
- **Documentation** — user guides, developer guides, API docs

---

## License

BledOS itself is licensed under the **GNU General Public License v3.0**.

Blender is licensed under the **GNU General Public License v2.0** (or later).

Arch Linux packages are licensed under their respective licenses.

---

## Acknowledgments

- **Blender Foundation** — for creating and maintaining Blender as free software
- **wlroots / Sway** — for the excellent Wayland compositor library
- **Arch Linux** — for the rolling-release foundation that makes BledOS possible
- **Drew DeVault** — for wlroots and the Wayland compositor ecosystem

---

*BledOS: Where your desktop is a scene and your computer is a viewport.*