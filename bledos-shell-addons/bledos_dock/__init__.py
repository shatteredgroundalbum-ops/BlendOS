"""
BledOS Dock Add-on
====================

Application dock (taskbar) rendered as a 3D object strip at the bottom
of the desktop scene. Shows pinned apps, running apps, and the system tray.
Supports click-to-focus, drag-to-reorder, and right-click context menus.

Blender version: 4.2+
Location: BledOS Shell > Dock
"""

bl_info = {
    "name": "BledOS Dock",
    "author": "BledOS Project",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "BledOS Shell",
    "description": "Application dock for BledOS desktop environment",
    "category": "System",
}

import bpy
import json
import os
import subprocess
from pathlib import Path

# ─── Constants ──────────────────────────────────────────────────────────────

DOCK_COLLECTION = "BledOS_Dock"
DOCK_Y_POSITION = -2.0
DOCK_Z_POSITION = 0.5
DOCK_ITEM_SIZE = 0.8
DOCK_ITEM_SPACING = 1.0
DOCK_HEIGHT = 0.4

# Standard application entries
DEFAULT_PINNED_APPS = [
    {"id": "files", "name": "Files", "icon": "FILE_FOLDER", "command": "bledos.fm_home",
     "desktop_file": "org.gnome.Files.desktop"},
    {"id": "terminal", "name": "Terminal", "icon": "CONSOLE", "command": "bledos.term_new",
     "desktop_file": "org.gnome.Terminal.desktop"},
    {"id": "browser", "name": "Web Browser", "icon": "WORLD", "command": "",
     "desktop_file": "firefox.desktop"},
    {"id": "blender", "name": "Blender", "icon": "BLENDER", "command": "",
     "desktop_file": "blender.desktop"},
    {"id": "settings", "name": "Settings", "icon": "PREFERENCES", "command": "bledos.settings_refresh_all",
     "desktop_file": "gnome-settings.desktop"},
]

DESKTOP_DIRS = [
    Path("/usr/share/applications"),
    Path.home() / ".local/share/applications",
]


# ─── Desktop File Parser ────────────────────────────────────────────────────

def parse_desktop_file(path):
    """Parse a .desktop file and return relevant fields."""
    entry = {
        "name": "",
        "icon": "",
        "exec": "",
        "terminal": False,
        "categories": [],
        "no_display": False,
    }

    try:
        in_desktop_entry = False
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line == "[Desktop Entry]":
                    in_desktop_entry = True
                    continue
                elif line.startswith("[") and line.endswith("]"):
                    in_desktop_entry = False
                    continue

                if not in_desktop_entry:
                    continue

                if "=" not in line:
                    continue

                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()

                if key == "Name":
                    entry["name"] = value
                elif key == "Icon":
                    entry["icon"] = value
                elif key == "Exec":
                    # Remove field codes like %f, %u, etc.
                    import re
                    entry["exec"] = re.sub(r'%[fFuUdDnNickvm]', '', value).strip()
                elif key == "Terminal":
                    entry["terminal"] = value.lower() == "true"
                elif key == "Categories":
                    entry["categories"] = [c.strip() for c in value.split(";") if c.strip()]
                elif key == "NoDisplay":
                    entry["no_display"] = value.lower() == "true"

    except Exception as e:
        print(f"[BledOS Dock] Failed to parse {path}: {e}")

    return entry


def get_all_applications():
    """Scan for all .desktop files and return parsed applications."""
    apps = {}

    for desktop_dir in DESKTOP_DIRS:
        if not desktop_dir.exists():
            continue
        for desktop_file in desktop_dir.glob("*.desktop"):
            entry = parse_desktop_file(desktop_file)
            if entry["name"] and not entry["no_display"] and entry["exec"]:
                apps[desktop_file.name] = entry

    return apps


# ─── 3D Dock Scene Objects ──────────────────────────────────────────────────

def get_or_create_dock_collection():
    """Get or create the dock collection."""
    scene = bpy.data.scenes.get("BledOS Desktop")
    if scene is None:
        return None

    collection = bpy.data.collections.get(DOCK_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(DOCK_COLLECTION)
        scene.collection.children.link(collection)

    return collection


def clear_dock_objects():
    """Remove all dock objects from the scene."""
    collection = bpy.data.collections.get(DOCK_COLLECTION)
    if collection is None:
        return

    objs_to_remove = list(collection.objects)
    for obj in objs_to_remove:
        bpy.data.objects.remove(obj, do_unlink=True)

    for mat in bpy.data.materials:
        if mat.name.startswith("BledOS_Dock_") and mat.users == 0:
            bpy.data.materials.remove(mat)


def create_dock_bar(collection, num_items):
    """Create the dock background bar."""
    bar_name = "BledOS_Dock_Bar"
    if bar_name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[bar_name], do_unlink=True)

    total_width = num_items * DOCK_ITEM_SPACING + 1.0

    bpy.ops.mesh.primitive_cube_add(
        size=1.0,
        location=(0, DOCK_Y_POSITION, DOCK_Z_POSITION - 0.1),
    )
    obj = bpy.context.active_object
    obj.name = bar_name
    obj.scale = (total_width / 2, 0.3, DOCK_HEIGHT / 2)

    # Dark translucent material
    mat = bpy.data.materials.new(name="BledOS_Dock_Bar_Mat")
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = (0.12, 0.12, 0.15, 0.8)
        principled.inputs["Alpha"].default_value = 0.85
        principled.inputs["Roughness"].default_value = 0.3
        principled.inputs["Emission Color"].default_value = (0.05, 0.05, 0.08, 1.0)
        principled.inputs["Emission Strength"].default_value = 0.2
    mat.blend_method = "BLEND" if hasattr(mat, "blend_method") else None
    obj.data.materials.append(mat)

    # Store metadata
    obj["bledos_type"] = "dock_bar"

    if obj.name not in collection.objects:
        collection.objects.link(obj)
        for coll in obj.users_collection:
            if coll != collection:
                coll.objects.unlink(obj)

    return obj


def create_dock_item(app_info, index, total, collection, is_running=False):
    """Create a single dock item as a 3D object."""
    item_name = f"BledOS_Dock_Item_{app_info['id']}"

    # Position along X axis centered
    x_offset = (index - total / 2 + 0.5) * DOCK_ITEM_SPACING
    position = (x_offset, DOCK_Y_POSITION, DOCK_Z_POSITION + DOCK_HEIGHT / 2)

    bpy.ops.mesh.primitive_cube_add(size=DOCK_ITEM_SIZE * 0.8, location=position)
    obj = bpy.context.active_object
    obj.name = item_name
    obj.scale = (0.4, 0.25, 0.4)

    # Store metadata
    obj["bledos_type"] = "dock_item"
    obj["bledos_app_id"] = app_info["id"]
    obj["bledos_app_name"] = app_info["name"]
    obj["bledos_app_command"] = app_info.get("command", "")
    obj["bledos_app_exec"] = app_info.get("exec", "")
    obj["bledos_app_icon"] = app_info.get("icon", "")
    obj["bledos_running"] = is_running

    # Material: different color for running apps
    mat = bpy.data.materials.new(name=f"BledOS_Dock_ItemMat_{app_info['id']}")
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    if principled:
        if is_running:
            principled.inputs["Base Color"].default_value = (0.3, 0.5, 0.7, 1.0)
            principled.inputs["Emission Color"].default_value = (0.1, 0.2, 0.3, 1.0)
            principled.inputs["Emission Strength"].default_value = 0.5
        else:
            principled.inputs["Base Color"].default_value = (0.25, 0.25, 0.3, 1.0)
            principled.inputs["Emission Color"].default_value = (0.05, 0.05, 0.08, 1.0)
            principled.inputs["Emission Strength"].default_value = 0.2
        principled.inputs["Roughness"].default_value = 0.4
    obj.data.materials.append(mat)

    # Running indicator dot
    if is_running:
        dot_name = f"BledOS_Dock_Dot_{app_info['id']}"
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=0.05,
            location=(position[0], position[1], position[2] - 0.35),
        )
        dot = bpy.context.active_object
        dot.name = dot_name
        dot["bledos_type"] = "dock_indicator"
        dot["bledos_app_id"] = app_info["id"]

        dot_mat = bpy.data.materials.new(name=f"BledOS_Dock_DotMat_{app_info['id']}")
        dot_mat.use_nodes = True
        dot_principled = dot_mat.node_tree.nodes.get("Principled BSDF")
        if dot_principled:
            dot_principled.inputs["Base Color"].default_value = (0.4, 0.8, 1.0, 1.0)
            dot_principled.inputs["Emission Color"].default_value = (0.3, 0.6, 1.0, 1.0)
            dot_principled.inputs["Emission Strength"].default_value = 2.0
        dot.data.materials.append(dot_mat)

        if dot.name not in collection.objects:
            collection.objects.link(dot)
            for coll in dot.users_collection:
                if coll != collection:
                    coll.objects.unlink(dot)

    if obj.name not in collection.objects:
        collection.objects.link(obj)
        for coll in obj.users_collection:
            if coll != collection:
                coll.objects.unlink(obj)

    return obj


def rebuild_dock(pinned_apps=None, running_apps=None):
    """Rebuild the entire dock from scratch."""
    collection = get_or_create_dock_collection()
    if collection is None:
        return

    clear_dock_objects()

    if pinned_apps is None:
        pinned_apps = DEFAULT_PINNED_APPS

    if running_apps is None:
        running_apps = []

    # Build combined list: pinned apps + running apps not already pinned
    pinned_ids = {app["id"] for app in pinned_apps}
    all_items = list(pinned_apps)

    for running in running_apps:
        if running.get("id") not in pinned_ids:
            all_items.append(running)

    total = len(all_items)

    # Create dock bar
    create_dock_bar(collection, total)

    # Create dock items
    for idx, app in enumerate(all_items):
        is_running = app.get("id") in {r.get("id") for r in running_apps}
        create_dock_item(app, idx, total, collection, is_running)


# ─── Properties ─────────────────────────────────────────────────────────────

class BledOSDockProperties(bpy.types.PropertyGroup):
    """Properties for the BledOS dock."""

    pinned_apps_json: bpy.props.StringProperty(
        name="Pinned Apps",
        default=json.dumps(DEFAULT_PINNED_APPS),
    )

    dock_visible: bpy.props.BoolProperty(
        name="Dock Visible",
        default=True,
    )

    dock_scale: bpy.props.FloatProperty(
        name="Dock Scale",
        default=1.0,
        min=0.5,
        max=2.0,
    )

    dock_position: bpy.props.EnumProperty(
        name="Dock Position",
        items=[
            ("BOTTOM", "Bottom", "Dock at bottom of screen"),
            ("LEFT", "Left", "Dock on left side"),
            ("RIGHT", "Right", "Dock on right side"),
        ],
        default="BOTTOM",
    )

    @property
    def pinned_apps(self):
        try:
            return json.loads(self.pinned_apps_json)
        except (json.JSONDecodeError, TypeError):
            return DEFAULT_PINNED_APPS

    @pinned_apps.setter
    def pinned_apps(self, value):
        self.pinned_apps_json = json.dumps(value)


# ─── Operators ──────────────────────────────────────────────────────────────

class BLEDOs_OT_dock_launch(bpy.types.Operator):
    """Launch an application from the dock"""
    bl_idname = "bledos.dock_launch"
    bl_label = "Launch Application"
    bl_options = {"REGISTER"}

    app_id: bpy.props.StringProperty()
    command: bpy.props.StringProperty()
    exec_cmd: bpy.props.StringProperty()

    def execute(self, context):
        # Try Blender operator command first
        if self.command:
            try:
                bpy.ops.idname_parse(self.command)
                return {"FINISHED"}
            except Exception:
                pass

        # Try exec command
        if self.exec_cmd:
            try:
                subprocess.Popen(
                    self.exec_cmd, shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.report({"INFO"}, f"Launched: {self.app_id}")
            except Exception as e:
                self.report({"ERROR"}, f"Failed to launch: {e}")
                return {"CANCELLED"}
        else:
            self.report({"WARNING"}, f"No command for {self.app_id}")
            return {"CANCELLED"}

        return {"FINISHED"}


class BLEDOs_OT_dock_rebuild(bpy.types.Operator):
    """Rebuild the dock from the current configuration"""
    bl_idname = "bledos.dock_rebuild"
    bl_label = "Rebuild Dock"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.bledos_dock_props
        rebuild_dock(pinned_apps=props.pinned_apps)
        self.report({"INFO"}, "Dock rebuilt")
        return {"FINISHED"}


class BLEDOs_OT_dock_pin_app(bpy.types.Operator):
    """Pin an application to the dock"""
    bl_idname = "bledos.dock_pin_app"
    bl_label = "Pin to Dock"
    bl_options = {"REGISTER"}

    app_id: bpy.props.StringProperty()
    app_name: bpy.props.StringProperty()
    app_exec: bpy.props.StringProperty()
    app_icon: bpy.props.StringProperty(default="FILE_BLANK")

    def execute(self, context):
        props = context.scene.bledos_dock_props
        apps = props.pinned_apps

        # Check if already pinned
        if any(a.get("id") == self.app_id for a in apps):
            self.report({"INFO"}, f"{self.app_name} is already pinned")
            return {"CANCELLED"}

        new_app = {
            "id": self.app_id,
            "name": self.app_name,
            "icon": self.app_icon,
            "command": "",
            "exec": self.app_exec,
        }
        apps.append(new_app)
        props.pinned_apps = apps

        rebuild_dock(pinned_apps=apps)
        self.report({"INFO"}, f"Pinned {self.app_name}")
        return {"FINISHED"}


class BLEDOs_OT_dock_unpin_app(bpy.types.Operator):
    """Unpin an application from the dock"""
    bl_idname = "bledos.dock_unpin_app"
    bl_label = "Unpin from Dock"
    bl_options = {"REGISTER"}

    app_id: bpy.props.StringProperty()

    def execute(self, context):
        props = context.scene.bledos_dock_props
        apps = props.pinned_apps

        new_apps = [a for a in apps if a.get("id") != self.app_id]
        if len(new_apps) == len(apps):
            self.report({"INFO"}, "App not found in dock")
            return {"CANCELLED"}

        props.pinned_apps = new_apps
        rebuild_dock(pinned_apps=new_apps)
        self.report({"INFO"}, f"Unpinned {self.app_id}")
        return {"FINISHED"}


class BLEDOs_OT_dock_scan_apps(bpy.types.Operator):
    """Scan for installed applications"""
    bl_idname = "bledos.dock_scan_apps"
    bl_label = "Scan Applications"
    bl_options = {"REGISTER"}

    def execute(self, context):
        apps = get_all_applications()
        count = len(apps)
        self.report({"INFO"}, f"Found {count} applications")
        return {"FINISHED"}


class BLEDOs_OT_dock_click_item(bpy.types.Operator):
    """Handle clicking on a dock item"""
    bl_idname = "bledos.dock_click_item"
    bl_label = "Dock Item Click"
    bl_options = {"REGISTER"}

    app_id: bpy.props.StringProperty()

    def execute(self, context):
        props = context.scene.bledos_dock_props
        apps = props.pinned_apps

        for app in apps:
            if app.get("id") == self.app_id:
                # Launch the app
                op = bpy.ops.bledos.dock_launch(
                    app_id=app["id"],
                    command=app.get("command", ""),
                    exec_cmd=app.get("exec", ""),
                )
                break

        self.report({"INFO"}, f"Clicked: {self.app_id}")
        return {"FINISHED"}


# ─── Panel ──────────────────────────────────────────────────────────────────

class BLEDOs_PT_dock(bpy.types.Panel):
    """BledOS Dock configuration panel"""
    bl_label = "Dock"
    bl_idname = "BLEDOs_PT_dock"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS"

    def draw(self, context):
        layout = self.layout
        props = context.scene.bledos_dock_props

        # Dock settings
        col = layout.column()
        col.prop(props, "dock_visible", text="Show Dock")
        col.prop(props, "dock_scale", text="Scale")
        col.prop(props, "dock_position", text="Position")

        layout.separator()

        # Rebuild button
        col = layout.column()
        col.operator("bledos.dock_rebuild", text="Rebuild Dock", icon="MOD_BUILD")

        # Scan for apps
        col.operator("bledos.dock_scan_apps", text="Scan Applications", icon="VIEWZOOM")

        layout.separator()

        # Pinned apps list
        col = layout.column()
        col.label(text="Pinned Applications:", icon="PINNED")
        apps = props.pinned_apps
        for app in apps:
            row = col.row(align=True)
            row.label(text=app.get("name", "Unknown"))
            op = row.operator("bledos.dock_unpin_app", text="", icon="X")
            op.app_id = app.get("id", "")


# ─── Registration ───────────────────────────────────────────────────────────

classes = (
    BledOSDockProperties,
    BLEDOs_OT_dock_launch,
    BLEDOs_OT_dock_rebuild,
    BLEDOs_OT_dock_pin_app,
    BLEDOs_OT_dock_unpin_app,
    BLEDOs_OT_dock_scan_apps,
    BLEDOs_OT_dock_click_item,
    BLEDOs_PT_dock,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bledos_dock_props = bpy.props.PointerProperty(
        type=BledOSDockProperties
    )
    print("[BledOS] Dock add-on registered")

    # Auto-build the dock
    try:
        rebuild_dock()
    except Exception:
        pass


def unregister():
    del bpy.types.Scene.bledos_dock_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[BledOS] Dock add-on unregistered")