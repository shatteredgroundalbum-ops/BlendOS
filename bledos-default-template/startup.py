"""
BledOS Application Template - Startup Script
=============================================

This script runs automatically when Blender starts with the BledOS
application template. It configures the workspace layout, enables
BledOS add-ons, and initializes the desktop environment.

Usage:
    blender --app-template BledOS

The template directory structure:
    BledOS/
    ├── startup.blend     # Default scene with desktop workspace
    ├── startup.py        # This script
    └── scripts/
        └── addons/       # BledOS add-ons (symlinked to system add-ons)
"""

import bpy
import os
import sys


def setup_bledos_workspaces():
    """Create or configure the BledOS workspace layout."""

    # Ensure we have a clean starting point
    scene = bpy.context.scene

    # ─── Desktop Workspace ─────────────────────────────────────
    if "Desktop" not in bpy.data.workspaces:
        bpy.ops.workspace.append_activate(
            idname="Desktop",
            filepath=""
        )

    # Configure Desktop workspace: 3D viewport filling the screen
    desktop = bpy.data.workspaces.get("Desktop")
    if desktop:
        # Set up the desktop 3D viewport
        for screen in desktop.screens:
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    for space in area.spaces:
                        if space.type == "VIEW_3D":
                            # Set viewport shading to Material Preview
                            space.shading.type = "MATERIAL"
                            # Show the BledOS sidebar
                            space.show_region_ui = True
                            # Set region type to BledOS category
                            for region in area.regions:
                                pass  # Region configuration happens after UI draw

    # ─── Files Workspace ───────────────────────────────────────
    # Will be created by the bledos_filemanager add-on

    # ─── Terminal Workspace ────────────────────────────────────
    # Will be created by the bledos_terminal add-on

    # ─── Settings Workspace ────────────────────────────────────
    # Will be created by the bledos_settings add-on

    # ─── Create Workspace (full Blender) ───────────────────────
    if "Create" not in bpy.data.workspaces:
        # Create a workspace with the default Blender layout
        # This gives users full access to Blender's tools
        pass

    print("[BledOS Template] Workspaces configured")


def setup_bledos_keymap():
    """Add BledOS-specific key bindings."""

    kc = bpy.context.window_manager.keyconfigs.user

    # BledOS keymap for the 3D viewport
    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")

    # Super+T: Open terminal
    kmi = km.keymap_items.new(
        "bledos.open_terminal",
        type="T",
        value="PRESS",
        oskey=True,
    )

    # Super+A: Application launcher
    kmi = km.keymap_items.new(
        "bledos.app_launcher",
        type="A",
        value="PRESS",
        oskey=True,
    )

    # Super+F: File manager
    kmi = km.keymap_items.new(
        "bledos.open_filemanager",
        type="F",
        value="PRESS",
        oskey=True,
    )

    # Super+L: Lock screen
    kmi = km.keymap_items.new(
        "bledos.lock_screen",
        type="L",
        value="PRESS",
        oskey=True,
    )

    # Super+Space: Application launcher (alternative)
    kmi = km.keymap_items.new(
        "bledos.app_launcher",
        type="SPACE",
        value="PRESS",
        oskey=True,
    )

    # Alt+Tab: Switch between app windows
    kmi = km.keymap_items.new(
        "bledos.switch_window",
        type="TAB",
        value="PRESS",
        alt=True,
    )

    # Ctrl+Alt+T: Terminal (alternative, common Linux shortcut)
    kmi = km.keymap_items.new(
        "bledos.open_terminal",
        type="T",
        value="PRESS",
        ctrl=True,
        alt=True,
    )

    print("[BledOS Template] Keymap configured")


def setup_bledos_theme():
    """Apply the BledOS custom theme for better desktop usability."""

    # BledOS uses a slightly modified Blender dark theme with:
    # - Larger fonts for readability at desktop distances
    # - Higher contrast for outdoor/bright environments
    # - Custom accent color (teal/cyan) for BledOS branding

    prefs = bpy.context.preferences
    prefs.view.font_size_ui = 13  # Slightly larger than default 11
    prefs.view.ui_scale = 1.1     # Slightly larger UI elements

    # Interface settings for desktop use
    prefs.system.use_region_overlap = True  # Transparent sidebars
    prefs.view.show_splash = False          # No splash screen on desktop boot

    print("[BledOS Template] Theme configured")


def enable_bledos_addons():
    """Enable all BledOS add-ons."""

    bledos_addons = [
        "bledos_core",
        "bledos_filemanager",
        "bledos_terminal",
        "bledos_settings",
        "bledos_dock",
        "bledos_app_launcher",
        "bledos_input_router",
        "bledos_window_manager",
        "bledos_system_tray",
        "bledos_notification",
        "bledos_power",
        "bledos_clipboard",
        "bledos_mount",
        "bledos_desktop_scene",
    ]

    for addon_name in bledos_addons:
        try:
            bpy.ops.preferences.addon_enable(module=addon_name)
        except Exception as e:
            print(f"[BledOS Template] Could not enable {addon_name}: {e}")

    print("[BledOS Template] Add-ons enabled")


def start_bledos():
    """Main entry point for the BledOS desktop environment."""

    print("=" * 60)
    print("  BledOS Desktop Environment Starting...")
    print("  Blender as Operating System")
    print("=" * 60)

    # 1. Configure theme first (affects all subsequent UI)
    setup_bledos_theme()

    # 2. Set up workspaces
    setup_bledos_workspaces()

    # 3. Configure keymap
    setup_bledos_keymap()

    # 4. Enable BledOS add-ons
    enable_bledos_addons()

    # 5. Initialize the desktop scene
    bpy.ops.bledos.setup_desktop()

    # 6. Go fullscreen (kiosk-like, but with escape hatch)
    bpy.ops.wm.window_fullscreen_toggle()

    # 7. Connect to the compositor
    bpy.ops.bledos.connect_compositor()

    print("[BledOS Template] Desktop environment ready!")


# ─── Auto-start ──────────────────────────────────────────────────────
# This runs when the .blend file is opened with this template

def register():
    """Called when the blend file with this template is loaded."""
    # Use a delayed startup to let Blender fully initialize
    bpy.app.timers.register(
        start_bledos,
        first_interval=0.5,  # Wait 500ms for Blender to finish loading
    )


def unregister():
    """Called when switching away from this template."""
    print("[BledOS Template] Shutting down...")