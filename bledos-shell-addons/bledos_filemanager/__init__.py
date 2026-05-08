"""
BledOS File Manager Add-on
===========================

A 3D file browser that represents files and directories as objects
in the Blender scene. Directories appear as colored cubes, files as
flat panels with icon/text overlays. Navigation uses Blender's
viewport controls, and file operations are exposed as Blender operators.

Blender version: 4.2+
Location: BledOS Shell > File Manager
"""

bl_info = {
    "name": "BledOS File Manager",
    "author": "BledOS Project",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "BledOS Shell",
    "description": "3D file browser for BledOS desktop environment",
    "category": "System",
}

import bpy
import os
import shutil
import stat
import subprocess
from pathlib import Path
from datetime import datetime

# ─── Constants ──────────────────────────────────────────────────────────────

FILE_MANAGER_COLLECTION = "BledOS_Files"
ICON_SIZE = 0.8
ICON_SPACING = 1.2
ICONS_PER_ROW = 8
MAX_VISIBLE_ITEMS = 64

# File type color mapping
FILE_TYPE_COLORS = {
    "directory": (0.3, 0.5, 0.8, 1.0),
    "image": (0.8, 0.4, 0.6, 1.0),
    "video": (0.6, 0.3, 0.8, 1.0),
    "audio": (0.8, 0.6, 0.3, 1.0),
    "document": (0.3, 0.7, 0.4, 1.0),
    "archive": (0.6, 0.6, 0.3, 1.0),
    "executable": (0.8, 0.3, 0.3, 1.0),
    "code": (0.4, 0.8, 0.7, 1.0),
    "default": (0.5, 0.5, 0.55, 1.0),
}

# File extension to type mapping
EXTENSION_MAP = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".bmp": "image",
    ".gif": "image", ".tiff": "image", ".svg": "image", ".webp": "image",
    ".mp4": "video", ".mkv": "video", ".avi": "video", ".mov": "video",
    ".webm": "video", ".flv": "video",
    ".mp3": "audio", ".wav": "audio", ".flac": "audio", ".ogg": "audio",
    ".aac": "audio", ".m4a": "audio",
    ".pdf": "document", ".doc": "document", ".docx": "document",
    ".odt": "document", ".txt": "document", ".rtf": "document",
    ".xls": "document", ".xlsx": "document", ".csv": "document",
    ".ppt": "document", ".pptx": "document",
    ".zip": "archive", ".tar": "archive", ".gz": "archive",
    ".bz2": "archive", ".xz": "archive", ".7z": "archive", ".rar": "archive",
    ".py": "code", ".js": "code", ".c": "code", ".cpp": "code", ".h": "code",
    ".java": "code", ".rs": "code", ".go": "code", ".sh": "code",
    ".html": "code", ".css": "code", ".json": "code", ".xml": "code",
    ".yaml": "code", ".yml": "code", ".toml": "code", ".md": "code",
}


def get_file_type(path):
    """Determine the file type based on extension and permissions."""
    if path.is_dir():
        return "directory"
    ext = path.suffix.lower()
    if ext in EXTENSION_MAP:
        return EXTENSION_MAP[ext]
    if path.exists() and os.access(str(path), os.X_OK):
        return "executable"
    return "default"


def format_file_size(size_bytes):
    """Format a file size in human-readable form."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def format_timestamp(timestamp):
    """Format a Unix timestamp as a readable date string."""
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M")


# ─── Scene Object Management ───────────────────────────────────────────────

def get_or_create_collection():
    """Get or create the BledOS Files collection in the desktop scene."""
    scene = bpy.data.scenes.get("BledOS Desktop")
    if scene is None:
        return None

    collection = bpy.data.collections.get(FILE_MANAGER_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(FILE_MANAGER_COLLECTION)
        scene.collection.children.link(collection)

    return collection


def clear_file_objects():
    """Remove all file manager objects from the scene."""
    collection = bpy.data.collections.get(FILE_MANAGER_COLLECTION)
    if collection is None:
        return

    # Remove all objects from the collection
    objs_to_remove = list(collection.objects)
    for obj in objs_to_remove:
        bpy.data.objects.remove(obj, do_unlink=True)

    # Remove orphan materials
    for mat in bpy.data.materials:
        if mat.name.startswith("BledOS_FM_") and mat.users == 0:
            bpy.data.materials.remove(mat)


def create_directory_object(path, position, collection):
    """Create a 3D cube representing a directory."""
    name = path.name
    obj_name = f"BledOS_FM_Dir_{name}"

    bpy.ops.mesh.primitive_cube_add(size=ICON_SIZE, location=position)
    obj = bpy.context.active_object
    obj.name = obj_name
    obj.scale = (0.5, 0.5, 0.6)

    # Store metadata
    obj["bledos_type"] = "file_item"
    obj["bledos_file_type"] = "directory"
    obj["bledos_path"] = str(path)
    obj["bledos_name"] = name

    # Apply directory material
    mat = bpy.data.materials.new(name=f"BledOS_FM_DirMat_{name}")
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    if principled:
        color = FILE_TYPE_COLORS["directory"]
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Roughness"].default_value = 0.4
        principled.inputs["Emission Color"].default_value = (color[0]*0.3, color[1]*0.3, color[2]*0.3, 1.0)
        principled.inputs["Emission Strength"].default_value = 0.3
    obj.data.materials.append(mat)

    # Link to collection if not already there
    if obj.name not in collection.objects:
        collection.objects.link(obj)
        # Unlink from default collection if linked there
        for coll in obj.users_collection:
            if coll != collection:
                coll.objects.unlink(obj)

    return obj


def create_file_object(path, position, collection):
    """Create a 3D flat panel representing a file."""
    name = path.name
    file_type = get_file_type(path)
    obj_name = f"BledOS_FM_File_{name}"

    bpy.ops.mesh.primitive_plane_add(size=ICON_SIZE, location=position)
    obj = bpy.context.active_object
    obj.name = obj_name
    obj.scale = (0.5, 0.5, 1.0)
    obj.rotation_euler = (0, 0, 0)

    # Store metadata
    obj["bledos_type"] = "file_item"
    obj["bledos_file_type"] = file_type
    obj["bledos_path"] = str(path)
    obj["bledos_name"] = name

    try:
        stat_info = path.stat()
        obj["bledos_size"] = stat_info.st_size
        obj["bledos_modified"] = stat_info.st_mtime
    except OSError:
        obj["bledos_size"] = 0
        obj["bledos_modified"] = 0

    # Apply file type material
    mat = bpy.data.materials.new(name=f"BledOS_FM_FileMat_{name}")
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    if principled:
        color = FILE_TYPE_COLORS.get(file_type, FILE_TYPE_COLORS["default"])
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Roughness"].default_value = 0.6
        principled.inputs["Emission Color"].default_value = (color[0]*0.2, color[1]*0.2, color[2]*0.2, 1.0)
        principled.inputs["Emission Strength"].default_value = 0.2
    obj.data.materials.append(mat)

    # Link to collection if not already there
    if obj.name not in collection.objects:
        collection.objects.link(obj)
        for coll in obj.users_collection:
            if coll != collection:
                coll.objects.unlink(obj)

    return obj


# ─── Directory Navigation ───────────────────────────────────────────────────

class BledOSFileManagerSettings(bpy.types.PropertyGroup):
    """Settings for the file manager, stored per scene."""
    current_path: bpy.props.StringProperty(
        name="Current Path",
        default=str(Path.home()),
        subtype="DIR_PATH",
    )
    show_hidden: bpy.props.BoolProperty(
        name="Show Hidden Files",
        default=False,
    )
    sort_by: bpy.props.EnumProperty(
        name="Sort By",
        items=[
            ("NAME", "Name", "Sort alphabetically by name"),
            ("SIZE", "Size", "Sort by file size"),
            ("TYPE", "Type", "Sort by file type"),
            ("MODIFIED", "Modified", "Sort by modification time"),
        ],
        default="NAME",
    )
    grid_scale: bpy.props.FloatProperty(
        name="Grid Scale",
        default=1.0,
        min=0.5,
        max=3.0,
    )


def browse_directory(directory_path, show_hidden=False, sort_by="NAME"):
    """Populate the scene with 3D objects representing files in the directory."""
    collection = get_or_create_collection()
    if collection is None:
        return []

    clear_file_objects()

    path = Path(directory_path)
    if not path.is_dir():
        print(f"[BledOS FM] Not a directory: {directory_path}")
        return []

    # Collect items
    try:
        items = list(path.iterdir())
    except PermissionError:
        print(f"[BledOS FM] Permission denied: {directory_path}")
        return []

    # Filter hidden files
    if not show_hidden:
        items = [i for i in items if not i.name.startswith(".")]

    # Sort items
    if sort_by == "NAME":
        items.sort(key=lambda p: p.name.lower())
    elif sort_by == "SIZE":
        items.sort(key=lambda p: p.stat().st_size if p.is_file() else 0, reverse=True)
    elif sort_by == "TYPE":
        items.sort(key=lambda p: (0 if p.is_dir() else 1, get_file_type(p), p.name.lower()))
    elif sort_by == "MODIFIED":
        items.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    # Always put directories first
    dirs = [i for i in items if i.is_dir()]
    files = [i for i in items if not i.is_dir()]
    items = dirs + files

    # Limit visible items
    items = items[:MAX_VISIBLE_ITEMS]

    # Create 3D objects in a grid layout
    created_objects = []
    for idx, item in enumerate(items):
        row = idx // ICONS_PER_ROW
        col = idx % ICONS_PER_ROW

        x = (col - ICONS_PER_ROW / 2) * ICON_SPACING
        y = 0
        z = (-row * ICON_SPACING) + 3.0

        position = (x, y, z)

        if item.is_dir():
            obj = create_directory_object(item, position, collection)
        else:
            obj = create_file_object(item, position, collection)

        if obj:
            created_objects.append(obj)

    return created_objects


# ─── Operators ──────────────────────────────────────────────────────────────

class BLEDOs_OT_fm_browse(bpy.types.Operator):
    """Browse to a directory path"""
    bl_idname = "bledos.fm_browse"
    bl_label = "Browse Directory"
    bl_options = {"REGISTER", "UNDO"}

    directory: bpy.props.StringProperty(
        name="Directory",
        subtype="DIR_PATH",
    )

    def execute(self, context):
        settings = context.scene.bledos_fm_settings
        path = self.directory or settings.current_path

        if not Path(path).is_dir():
            self.report({"ERROR"}, f"Not a valid directory: {path}")
            return {"CANCELLED"}

        settings.current_path = path
        browse_directory(
            path,
            show_hidden=settings.show_hidden,
            sort_by=settings.sort_by,
        )
        self.report({"INFO"}, f"Browsing: {path}")
        return {"FINISHED"}


class BLEDOs_OT_fm_navigate_up(bpy.types.Operator):
    """Navigate to the parent directory"""
    bl_idname = "bledos.fm_navigate_up"
    bl_label = "Navigate Up"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.bledos_fm_settings
        current = Path(settings.current_path)
        parent = current.parent

        if parent == current:
            self.report({"INFO"}, "Already at root directory")
            return {"CANCELLED"}

        settings.current_path = str(parent)
        browse_directory(
            str(parent),
            show_hidden=settings.show_hidden,
            sort_by=settings.sort_by,
        )
        self.report({"INFO"}, f"Browsing: {parent}")
        return {"FINISHED"}


class BLEDOs_OT_fm_open(bpy.types.Operator):
    """Open the selected file or navigate into the selected directory"""
    bl_idname = "bledos.fm_open"
    bl_label = "Open Selected"
    bl_options = {"REGISTER"}

    def execute(self, context):
        # Get the active object in the file collection
        obj = context.active_object
        if obj is None or obj.get("bledos_type") != "file_item":
            self.report({"WARNING"}, "No file item selected")
            return {"CANCELLED"}

        path_str = obj.get("bledos_path", "")
        path = Path(path_str)

        if not path.exists():
            self.report({"ERROR"}, f"Path does not exist: {path_str}")
            return {"CANCELLED"}

        if path.is_dir():
            # Navigate into directory
            settings = context.scene.bledos_fm_settings
            settings.current_path = str(path)
            browse_directory(
                str(path),
                show_hidden=settings.show_hidden,
                sort_by=settings.sort_by,
            )
            self.report({"INFO"}, f"Entered: {path}")
        else:
            # Open file with default application
            try:
                subprocess.Popen(["xdg-open", str(path)],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
                self.report({"INFO"}, f"Opened: {path.name}")
            except Exception as e:
                self.report({"ERROR"}, f"Failed to open: {e}")

        return {"FINISHED"}


class BLEDOs_OT_fm_delete(bpy.types.Operator):
    """Move the selected file to trash"""
    bl_idname = "bledos.fm_delete"
    bl_label = "Delete Selected"
    bl_options = {"REGISTER"}

    path_to_delete: bpy.props.StringProperty()

    def execute(self, context):
        path = Path(self.path_to_delete)
        if not path.exists():
            self.report({"ERROR"}, "File not found")
            return {"CANCELLED"}

        try:
            if path.is_dir():
                shutil.rmtree(str(path))
            else:
                path.unlink()
            self.report({"INFO"}, f"Deleted: {path.name}")

            # Refresh the view
            settings = context.scene.bledos_fm_settings
            browse_directory(
                settings.current_path,
                show_hidden=settings.show_hidden,
                sort_by=settings.sort_by,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Delete failed: {e}")
            return {"CANCELLED"}

        return {"FINISHED"}


class BLEDOs_OT_fm_copy(bpy.types.Operator):
    """Copy the selected file path to clipboard"""
    bl_idname = "bledos.fm_copy"
    bl_label = "Copy Path"
    bl_options = {"REGISTER"}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.get("bledos_type") != "file_item":
            self.report({"WARNING"}, "No file item selected")
            return {"CANCELLED"}

        path = obj.get("bledos_path", "")
        context.window_manager.clipboard = path
        self.report({"INFO"}, f"Copied: {path}")
        return {"FINISHED"}


class BLEDOs_OT_fm_rename(bpy.types.Operator):
    """Rename the selected file or directory"""
    bl_idname = "bledos.fm_rename"
    bl_label = "Rename Selected"
    bl_options = {"REGISTER"}

    new_name: bpy.props.StringProperty(
        name="New Name",
    )

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.get("bledos_type") != "file_item":
            self.report({"WARNING"}, "No file item selected")
            return {"CANCELLED"}

        old_path = Path(obj.get("bledos_path", ""))
        if not old_path.exists():
            self.report({"ERROR"}, "File not found")
            return {"CANCELLED"}

        new_path = old_path.parent / self.new_name
        if new_path.exists():
            self.report({"ERROR"}, "A file with that name already exists")
            return {"CANCELLED"}

        try:
            old_path.rename(new_path)
            self.report({"INFO"}, f"Renamed to: {self.new_name}")

            # Refresh
            settings = context.scene.bledos_fm_settings
            browse_directory(
                settings.current_path,
                show_hidden=settings.show_hidden,
                sort_by=settings.sort_by,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Rename failed: {e}")
            return {"CANCELLED"}

        return {"FINISHED"}

    def invoke(self, context, event):
        obj = context.active_object
        if obj and obj.get("bledos_type") == "file_item":
            self.new_name = obj.get("bledos_name", "")
        return context.window_manager.invoke_props_dialog(self)


class BLEDOs_OT_fm_new_folder(bpy.types.Operator):
    """Create a new folder in the current directory"""
    bl_idname = "bledos.fm_new_folder"
    bl_label = "New Folder"
    bl_options = {"REGISTER"}

    folder_name: bpy.props.StringProperty(
        name="Folder Name",
        default="New Folder",
    )

    def execute(self, context):
        settings = context.scene.bledos_fm_settings
        new_path = Path(settings.current_path) / self.folder_name

        try:
            new_path.mkdir(parents=False, exist_ok=False)
            self.report({"INFO"}, f"Created: {self.folder_name}")

            # Refresh
            browse_directory(
                settings.current_path,
                show_hidden=settings.show_hidden,
                sort_by=settings.sort_by,
            )
        except FileExistsError:
            self.report({"ERROR"}, "Folder already exists")
            return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Create failed: {e}")
            return {"CANCELLED"}

        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BLEDOs_OT_fm_refresh(bpy.types.Operator):
    """Refresh the current directory view"""
    bl_idname = "bledos.fm_refresh"
    bl_label = "Refresh"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.bledos_fm_settings
        browse_directory(
            settings.current_path,
            show_hidden=settings.show_hidden,
            sort_by=settings.sort_by,
        )
        self.report({"INFO"}, "Refreshed")
        return {"FINISHED"}


class BLEDOs_OT_fm_home(bpy.types.Operator):
    """Navigate to the home directory"""
    bl_idname = "bledos.fm_home"
    bl_label = "Home Directory"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.bledos_fm_settings
        settings.current_path = str(Path.home())
        browse_directory(
            settings.current_path,
            show_hidden=settings.show_hidden,
            sort_by=settings.sort_by,
        )
        self.report({"INFO"}, f"Home: {settings.current_path}")
        return {"FINISHED"}


class BLEDOs_OT_fm_toggle_hidden(bpy.types.Operator):
    """Toggle showing hidden files"""
    bl_idname = "bledos.fm_toggle_hidden"
    bl_label = "Toggle Hidden Files"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.bledos_fm_settings
        settings.show_hidden = not settings.show_hidden
        browse_directory(
            settings.current_path,
            show_hidden=settings.show_hidden,
            sort_by=settings.sort_by,
        )
        state = "shown" if settings.show_hidden else "hidden"
        self.report({"INFO"}, f"Hidden files {state}")
        return {"FINISHED"}


# ─── Panel ──────────────────────────────────────────────────────────────────

class BLEDOs_PT_file_manager(bpy.types.Panel):
    """BledOS File Manager panel"""
    bl_label = "File Manager"
    bl_idname = "BLEDOs_PT_file_manager"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.bledos_fm_settings

        # Current path
        col = layout.column()
        col.label(text="Current Directory:", icon="FILE_FOLDER")
        col.prop(settings, "current_path", text="")

        # Navigation buttons
        row = layout.row(align=True)
        row.operator("bledos.fm_home", text="", icon="HOME")
        row.operator("bledos.fm_navigate_up", text="", icon="FILE_PARENT")
        row.operator("bledos.fm_refresh", text="", icon="FILE_REFRESH")

        layout.separator()

        # Sort and filter
        row = layout.row(align=True)
        row.prop(settings, "sort_by", text="")
        row.operator("bledos.fm_toggle_hidden",
                     text=".*" if not settings.show_hidden else ".*",
                     icon="HIDE_OFF" if settings.show_hidden else "HIDE_ON")

        layout.separator()

        # File operations
        col = layout.column()
        col.operator("bledos.fm_open", text="Open", icon="FILEBROWSER")
        col.operator("bledos.fm_new_folder", text="New Folder", icon="NEWFOLDER")

        row = col.row(align=True)
        row.operator("bledos.fm_copy", text="Copy Path", icon="COPYDOWN")
        row.operator("bledos.fm_rename", text="Rename", icon="FONT_DATA")

        # Selected file info
        obj = context.active_object
        if obj and obj.get("bledos_type") == "file_item":
            layout.separator()
            col = layout.column()
            col.label(text="Selected:", icon="FILE")
            col.label(text=f"  Name: {obj.get('bledos_name', '?')}")
            col.label(text=f"  Type: {obj.get('bledos_file_type', '?')}")

            file_size = obj.get("bledos_size", -1)
            if file_size >= 0:
                col.label(text=f"  Size: {format_file_size(file_size)}")

            file_mtime = obj.get("bledos_modified", 0)
            if file_mtime > 0:
                col.label(text=f"  Modified: {format_timestamp(file_mtime)}")


# ─── Registration ───────────────────────────────────────────────────────────

classes = (
    BledOSFileManagerSettings,
    BLEDOs_OT_fm_browse,
    BLEDOs_OT_fm_navigate_up,
    BLEDOs_OT_fm_open,
    BLEDOs_OT_fm_delete,
    BLEDOs_OT_fm_copy,
    BLEDOs_OT_fm_rename,
    BLEDOs_OT_fm_new_folder,
    BLEDOs_OT_fm_refresh,
    BLEDOs_OT_fm_home,
    BLEDOs_OT_fm_toggle_hidden,
    BLEDOs_PT_file_manager,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bledos_fm_settings = bpy.props.PointerProperty(
        type=BledOSFileManagerSettings
    )
    print("[BledOS] File Manager add-on registered")


def unregister():
    del bpy.types.Scene.bledos_fm_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[BledOS] File Manager add-on unregistered")