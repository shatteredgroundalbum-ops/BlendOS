"""
BledOS App Launcher Add-on
============================

Application launcher menu that scans .desktop files, categorizes
applications, and provides a searchable Blender UI for launching apps.
Also supports 3D object-based app launching in the desktop scene.

Blender version: 4.2+
Location: BledOS Shell > App Launcher
"""

bl_info = {
    "name": "BledOS App Launcher",
    "author": "BledOS Project",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "BledOS Shell",
    "description": "Application launcher for BledOS desktop environment",
    "category": "System",
}

import bpy
import json
import os
import re
import subprocess
from pathlib import Path

# ─── Constants ──────────────────────────────────────────────────────────────

LAUNCHER_COLLECTION = "BledOS_AppLauncher"
DESKTOP_DIRS = [
    Path("/usr/share/applications"),
    Path.home() / ".local/share/applications",
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/flatpak/exports/share/applications",
]

# Category icons (Blender icon names)
CATEGORY_ICONS = {
    "AudioVideo": "PLAY", "Audio": "PLAY", "Video": "PLAY",
    "Development": "SCRIPT", "IDE": "SCRIPT",
    "Education": "HELP", "Science": "LIGHT_AREA",
    "Game": "GAME", "ActionGame": "GAME",
    "Graphics": "IMAGE_DATA", "2DGraphics": "IMAGE_DATA",
    "Network": "INTERNET", "WebBrowser": "INTERNET",
    "Office": "FILE_TEXT", "Spreadsheet": "FILE_TEXT",
    "Settings": "PREFERENCES", "System": "SYSTEM",
    "Utility": "TOOL_SETTINGS", "TextEditor": "TEXT",
    "FileManager": "FILE_FOLDER",
}


# ─── Desktop File Scanner ───────────────────────────────────────────────────

class AppEntry:
    """Represents a parsed .desktop file entry."""

    def __init__(self, desktop_file_path):
        self.path = Path(desktop_file_path)
        self.filename = self.path.name
        self.name = ""
        self.generic_name = ""
        self.comment = ""
        self.icon_name = ""
        self.exec_cmd = ""
        self.terminal = False
        self.categories = []
        self.no_display = False
        self.hidden = False
        self.keywords = []
        self._parse()

    def _parse(self):
        """Parse the .desktop file."""
        try:
            in_entry = False
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line == "[Desktop Entry]":
                        in_entry = True
                        continue
                    elif line.startswith("[") and line.endswith("]"):
                        in_entry = False
                        continue
                    if not in_entry or "=" not in line:
                        continue

                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()

                    if key == "Name":
                        self.name = value
                    elif key == "GenericName":
                        self.generic_name = value
                    elif key == "Comment":
                        self.comment = value
                    elif key == "Icon":
                        self.icon_name = value
                    elif key == "Exec":
                        self.exec_cmd = re.sub(r'%[fFuUdDnNickvm]', '', value).strip()
                    elif key == "Terminal":
                        self.terminal = value.lower() == "true"
                    elif key == "Categories":
                        self.categories = [c.strip() for c in value.split(";") if c.strip()]
                    elif key == "NoDisplay":
                        self.no_display = value.lower() == "true"
                    elif key == "Hidden":
                        self.hidden = value.lower() == "true"
                    elif key == "Keywords":
                        self.keywords = [k.strip() for k in value.split(";") if k.strip()]

        except Exception as e:
            print(f"[BledOS Launcher] Parse error: {self.path}: {e}")

    @property
    def is_valid(self):
        """Check if this is a launchable application."""
        return bool(self.name and self.exec_cmd and not self.no_display and not self.hidden)

    @property
    def primary_category(self):
        """Get the primary category."""
        if self.categories:
            return self.categories[0]
        return "Other"

    @property
    def search_text(self):
        """Get all searchable text combined."""
        parts = [self.name, self.generic_name, self.comment]
        parts.extend(self.keywords)
        parts.extend(self.categories)
        return " ".join(p.lower() for p in parts if p)

    def to_dict(self):
        """Convert to a dictionary for serialization."""
        return {
            "filename": self.filename,
            "name": self.name,
            "generic_name": self.generic_name,
            "comment": self.comment,
            "icon_name": self.icon_name,
            "exec_cmd": self.exec_cmd,
            "terminal": self.terminal,
            "categories": self.categories,
            "primary_category": self.primary_category,
        }


class AppScanner:
    """Scans for and caches application entries."""

    def __init__(self):
        self._apps = {}
        self._categories = {}
        self._last_scan = 0

    def scan(self, force=False):
        """Scan all desktop directories for applications."""
        import time
        now = time.time()

        # Cache for 30 seconds
        if not force and self._apps and (now - self._last_scan) < 30:
            return self._apps

        self._apps.clear()
        self._categories.clear()

        for desktop_dir in DESKTOP_DIRS:
            if not desktop_dir.exists():
                continue
            for desktop_file in desktop_dir.glob("*.desktop"):
                entry = AppEntry(desktop_file)
                if entry.is_valid:
                    self._apps[entry.filename] = entry

                    # Index by category
                    for cat in entry.categories:
                        if cat not in self._categories:
                            self._categories[cat] = []
                        self._categories[cat].append(entry.filename)

        self._last_scan = now
        print(f"[BledOS Launcher] Scanned {len(self._apps)} applications in {len(self._categories)} categories")
        return self._apps

    def get_apps(self):
        """Get all cached applications."""
        if not self._apps:
            self.scan()
        return self._apps

    def get_categories(self):
        """Get the category index."""
        if not self._categories:
            self.scan()
        return self._categories

    def search(self, query):
        """Search applications by name, comment, keywords, or category."""
        if not self._apps:
            self.scan()

        query = query.lower().strip()
        if not query:
            return list(self._apps.values())

        results = []
        for entry in self._apps.values():
            if query in entry.search_text:
                results.append(entry)

        # Sort by relevance: name match first, then category, then others
        def sort_key(entry):
            name_lower = entry.name.lower()
            if name_lower == query:
                return 0
            elif name_lower.startswith(query):
                return 1
            elif query in name_lower:
                return 2
            elif any(query in c.lower() for c in entry.categories):
                return 3
            else:
                return 4

        results.sort(key=sort_key)
        return results

    def get_by_category(self, category):
        """Get applications in a specific category."""
        if not self._apps:
            self.scan()

        filenames = self._categories.get(category, [])
        return [self._apps[f] for f in filenames if f in self._apps]


# Global scanner
app_scanner = AppScanner()


# ─── Application Launcher ──────────────────────────────────────────────────

def launch_application(exec_cmd, terminal=False):
    """Launch an application by its exec command."""
    if not exec_cmd:
        return False

    try:
        if terminal:
            # Launch in a terminal
            cmd = f"alacritty -e {exec_cmd}"
        else:
            cmd = exec_cmd

        subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception as e:
        print(f"[BledOS Launcher] Launch failed: {e}")
        return False


# ─── Properties ─────────────────────────────────────────────────────────────

class BledOSAppLauncherProperties(bpy.types.PropertyGroup):
    """Properties for the BledOS app launcher."""

    search_query: bpy.props.StringProperty(
        name="Search",
        default="",
    )
    selected_category: bpy.props.EnumProperty(
        name="Category",
        items=[
            ("ALL", "All", "Show all applications"),
            ("AudioVideo", "Media", "Audio and Video"),
            ("Development", "Development", "Development tools"),
            ("Education", "Education", "Educational software"),
            ("Game", "Games", "Games"),
            ("Graphics", "Graphics", "Graphics applications"),
            ("Network", "Network", "Network and Internet"),
            ("Office", "Office", "Office applications"),
            ("Settings", "Settings", "System settings"),
            ("System", "System", "System utilities"),
            ("Utility", "Utilities", "General utilities"),
        ],
        default="ALL",
    )
    last_results_json: bpy.props.StringProperty(
        name="Last Results",
        default="[]",
    )


# ─── Operators ──────────────────────────────────────────────────────────────

class BLEDOs_OT_launcher_search(bpy.types.Operator):
    """Search for applications"""
    bl_idname = "bledos.launcher_search"
    bl_label = "Search Applications"
    bl_options = {"REGISTER"}

    query: bpy.props.StringProperty(name="Search Query")

    def execute(self, context):
        props = context.scene.bledos_launcher_props
        query = self.query or props.search_query

        results = app_scanner.search(query)
        props.last_results_json = json.dumps([r.to_dict() for r in results[:50]])
        props.search_query = query

        self.report({"INFO"}, f"Found {len(results)} applications")
        return {"FINISHED"}


class BLEDOs_OT_launcher_launch(bpy.types.Operator):
    """Launch an application"""
    bl_idname = "bledos.launcher_launch"
    bl_label = "Launch Application"
    bl_options = {"REGISTER"}

    exec_cmd: bpy.props.StringProperty(name="Command")
    app_name: bpy.props.StringProperty(name="App Name", default="")
    terminal: bpy.props.BoolProperty(name="Run in Terminal", default=False)

    def execute(self, context):
        if launch_application(self.exec_cmd, self.terminal):
            self.report({"INFO"}, f"Launched: {self.app_name or self.exec_cmd}")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, f"Failed to launch: {self.app_name}")
            return {"CANCELLED"}


class BLEDOs_OT_launcher_scan(bpy.types.Operator):
    """Force rescan for applications"""
    bl_idname = "bledos.launcher_scan"
    bl_label = "Rescan Applications"
    bl_options = {"REGISTER"}

    def execute(self, context):
        app_scanner.scan(force=True)
        count = len(app_scanner.get_apps())
        self.report({"INFO"}, f"Found {count} applications")
        return {"FINISHED"}


class BLEDOs_OT_launcher_category(bpy.types.Operator):
    """Browse applications by category"""
    bl_idname = "bledos.launcher_category"
    bl_label = "Browse Category"
    bl_options = {"REGISTER"}

    category: bpy.props.StringProperty(default="ALL")

    def execute(self, context):
        props = context.scene.bledos_launcher_props
        props.selected_category = self.category

        if self.category == "ALL":
            results = list(app_scanner.get_apps().values())
        else:
            results = app_scanner.get_by_category(self.category)

        results.sort(key=lambda r: r.name.lower())
        props.last_results_json = json.dumps([r.to_dict() for r in results[:50]])

        self.report({"INFO"}, f"Category: {self.category} ({len(results)} apps)")
        return {"FINISHED"}


class BLEDOs_OT_launcher_open_desktop_dir(bpy.types.Operator):
    """Open the user applications directory"""
    bl_idname = "bledos.launcher_open_desktop_dir"
    bl_label = "Open Applications Folder"
    bl_options = {"REGISTER"}

    def execute(self, context):
        user_dir = Path.home() / ".local/share/applications"
        user_dir.mkdir(parents=True, exist_ok=True)

        # Use file manager to open
        try:
            bpy.ops.bledos.fm_browse(directory=str(user_dir))
        except Exception:
            subprocess.Popen(["xdg-open", str(user_dir)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return {"FINISHED"}


# ─── Panel ──────────────────────────────────────────────────────────────────

class BLEDOs_PT_app_launcher(bpy.types.Panel):
    """BledOS Application Launcher panel"""
    bl_label = "App Launcher"
    bl_idname = "BLEDOs_PT_app_launcher"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS"

    def draw(self, context):
        layout = self.layout
        props = context.scene.bledos_launcher_props

        # Search bar
        col = layout.column()
        col.prop(props, "search_query", text="", icon="VIEWZOOM")
        col.operator("bledos.launcher_search", text="Search", icon="VIEWZOOM")

        layout.separator()

        # Category filter
        row = layout.row()
        row.prop(props, "selected_category", text="")
        op = row.operator("bledos.launcher_category", text="", icon="FILE_REFRESH")
        op.category = props.selected_category

        layout.separator()

        # Application list
        try:
            results = json.loads(props.last_results_json)
        except (json.JSONDecodeError, TypeError):
            results = []

        if not results:
            # Show scan prompt
            col = layout.column()
            col.label(text="No applications loaded", icon="INFO")
            col.operator("bledos.launcher_scan", text="Scan for Applications", icon="VIEWZOOM")
        else:
            col = layout.column()
            col.label(text=f"Applications ({len(results)}):", icon="APP")

            for app in results[:20]:  # Show max 20 in panel
                row = col.row(align=True)

                # App name and comment
                name = app.get("name", "Unknown")
                comment = app.get("comment", "")
                display_text = name if len(name) <= 25 else name[:22] + "..."

                row.label(text=display_text, icon="DOT")

                # Launch button
                op = row.operator("bledos.launcher_launch", text="", icon="PLAY")
                op.exec_cmd = app.get("exec_cmd", "")
                op.app_name = name
                op.terminal = app.get("terminal", False)

                # Terminal launch button
                if not app.get("terminal", False):
                    op2 = row.operator("bledos.launcher_launch", text="", icon="CONSOLE")
                    op2.exec_cmd = app.get("exec_cmd", "")
                    op2.app_name = name
                    op2.terminal = True

            if len(results) > 20:
                col.label(text=f"... and {len(results) - 20} more")

        layout.separator()
        col = layout.column()
        col.operator("bledos.launcher_scan", text="Rescan", icon="FILE_REFRESH")
        col.operator("bledos.launcher_open_desktop_dir", text="User Apps Folder", icon="FILE_FOLDER")


# ─── Registration ───────────────────────────────────────────────────────────

classes = (
    BledOSAppLauncherProperties,
    BLEDOs_OT_launcher_search,
    BLEDOs_OT_launcher_launch,
    BLEDOs_OT_launcher_scan,
    BLEDOs_OT_launcher_category,
    BLEDOs_OT_launcher_open_desktop_dir,
    BLEDOs_PT_app_launcher,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bledos_launcher_props = bpy.props.PointerProperty(
        type=BledOSAppLauncherProperties
    )
    print("[BledOS] App Launcher add-on registered")

    # Auto-scan on register
    try:
        app_scanner.scan()
    except Exception:
        pass


def unregister():
    del bpy.types.Scene.bledos_launcher_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[BledOS] App Launcher add-on unregistered")