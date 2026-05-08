# BledOS - Blender as Operating System - Project Plan

## Phase 1: Research & Feasibility ✅
- [x] Research Blender's architecture, Python API capabilities, and headless mode
- [x] Research minimal Linux distributions suitable as a base (Arch, Alpine, Debian minimal)
- [x] Research X11/Wayland window management and how to make Blender the sole compositor
- [x] Research Blender's event system and input handling outside of windowed mode
- [x] Research existing similar projects (Blender as kiosk, custom compositors)

## Phase 2: Architecture Design & Specification ✅
- [x] Design the OS architecture layers (kernel → display server → Blender)
- [x] Design the Blender-based shell/deck system (file manager, terminal, app launcher)
- [x] Design inter-process communication (Blender Python ↔ system services)
- [x] Design the window management strategy within Blender's 3D viewport
- [x] Design security and permission model

## Phase 3: Technical Specification Document ✅
- [x] Write comprehensive technical specification (BledOS_Technical_Specification.md)
- [x] Create architecture diagrams
- [x] Define API boundaries between components
- [x] Specify hardware requirements and supported platforms

## Phase 4: Core Implementation (In Progress)
- [x] Compositor skeleton (bledos-compositor/src/main.c + meson.build)
- [x] Core shell add-on (bledos-shell-addons/bledos_core/__init__.py)
- [x] Application template (bledos-default-template/startup.py)
- [x] Systemd services (bledos-compositor.service, bledos-shell.service)
- [x] Arch ISO build system (packages.x86_64, build-iso.sh)
- [x] README and project documentation
- [ ] File Manager add-on (bledos_filemanager)
- [ ] Terminal add-on (bledos_terminal)
- [ ] Settings add-on (bledos_settings)
- [ ] Dock add-on (bledos_dock)
- [ ] App Launcher add-on (bledos_app_launcher)
- [ ] Input Router add-on (bledos_input_router)
- [ ] Window Manager add-on (bledos_window_manager)
- [ ] System Tray add-on (bledos_system_tray)
- [ ] Notification add-on (bledos_notification)
- [ ] Power add-on (bledos_power)

## Phase 5: Integration & Testing
- [ ] Integration testing of all add-ons together
- [ ] Test ISO build in QEMU
- [ ] Input routing end-to-end validation
- [ ] DMA-BUF texture sharing prototype
- [ ] Performance profiling and optimization