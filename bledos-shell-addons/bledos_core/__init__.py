"""
BledOS Core Shell Add-on
=========================

This is the main add-on that initializes the BledOS desktop environment
within Blender. It connects to the BledOS Compositor via Unix domain
sockets, manages the desktop workspace scene, and coordinates all other
BledOS add-ons.

Blender version: 4.2+
Location: BledOS Shell
"""

bl_info = {
    "name": "BledOS Core Shell",
    "author": "BledOS Project",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "BledOS Shell",
    "description": "Core desktop environment shell for BledOS",
    "category": "System",
}

import bpy
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path

# ─── Constants ──────────────────────────────────────────────────────

COMPOSITOR_SOCK = "/run/bledos/compositor.sock"
INPUT_SOCK = "/run/bledos/input.sock"
BLEDOs_SCENE_NAME = "BledOS Desktop"
DEFAULT_ROOM_SCALE = 20.0

# Input event types (must match compositor)
EVT_MOUSE_MOVE = 0x01
EVT_MOUSE_BUTTON = 0x02
EVT_KEYBOARD_KEY = 0x03
EVT_MOUSE_SCROLL = 0x04
EVT_FOCUS_CHANGE = 0x05


# ─── Compositor Connection ──────────────────────────────────────────

class CompositorConnection:
    """Manages the connection to the BledOS Compositor."""

    def __init__(self):
        self.control_sock = None
        self.input_sock = None
        self.connected = False
        self.clients = {}  # client_id -> client_info dict
        self._lock = threading.Lock()

    def connect(self):
        """Connect to the BledOS Compositor."""
        try:
            # Connect control socket
            self.control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.control_sock.connect(COMPOSITOR_SOCK)
            self.control_sock.settimeout(5.0)

            # Connect input socket
            self.input_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.input_sock.connect(INPUT_SOCK)
            self.input_sock.settimeout(5.0)

            self.connected = True
            print("[BledOS] Connected to compositor")

            # Test connection
            response = self.send_command({"cmd": "ping"})
            if response and response.get("status") == "ok":
                print("[BledOS] Compositor pong received")
                return True
            else:
                print("[BledOS] Compositor ping failed")
                self.disconnect()
                return False

        except (ConnectionRefusedError, FileNotFoundError) as e:
            print(f"[BledOS] Failed to connect to compositor: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from the compositor."""
        self.connected = False
        if self.control_sock:
            self.control_sock.close()
            self.control_sock = None
        if self.input_sock:
            self.input_sock.close()
            self.input_sock = None
        self.clients.clear()
        print("[BledOS] Disconnected from compositor")

    def send_command(self, cmd_dict):
        """Send a JSON command to the compositor and return the response."""
        if not self.connected or not self.control_sock:
            return None

        try:
            msg = json.dumps(cmd_dict) + "\n"
            self.control_sock.sendall(msg.encode("utf-8"))

            # Read response (line-delimited JSON)
            data = b""
            while True:
                chunk = self.control_sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            if data:
                response_str = data.decode("utf-8").strip()
                return json.loads(response_str)
            return None

        except (socket.timeout, ConnectionError, json.JSONDecodeError) as e:
            print(f"[BledOS] Command error: {e}")
            return None

    def list_clients(self):
        """Get the list of active Wayland clients."""
        response = self.send_command({"cmd": "list_clients"})
        if response and response.get("status") == "ok":
            with self._lock:
                for client in response.get("clients", []):
                    cid = client["client_id"]
                    self.clients[cid] = client
            return response.get("clients", [])
        return []

    def close_client(self, client_id):
        """Close a Wayland client."""
        return self.send_command({"cmd": "close", "client_id": client_id})

    def set_focus(self, client_id):
        """Set input focus to a client."""
        result = self.send_command({"cmd": "set_focus", "client_id": client_id})
        if result and result.get("status") == "ok":
            self.send_input_event(EVT_FOCUS_CHANGE, struct.pack("!I", client_id))
        return result

    def send_input_event(self, event_type, data):
        """Send a binary input event to the compositor."""
        if not self.connected or not self.input_sock:
            return False

        try:
            timestamp = int(time.time() * 1000) & 0xFFFFFFFF
            header = struct.pack("!BI", event_type, timestamp)
            self.input_sock.sendall(header + data)
            return True
        except ConnectionError as e:
            print(f"[BledOS] Input event error: {e}")
            return False

    def send_mouse_move(self, x, y):
        """Forward a mouse move event to the compositor."""
        data = struct.pack("!ff", x, y)
        return self.send_input_event(EVT_MOUSE_MOVE, data)

    def send_mouse_button(self, button, pressed):
        """Forward a mouse button event to the compositor."""
        data = struct.pack("!BB", button, 1 if pressed else 0)
        return self.send_input_event(EVT_MOUSE_BUTTON, data)

    def send_key(self, keycode, pressed):
        """Forward a keyboard event to the compositor."""
        data = struct.pack("!IB", keycode, 1 if pressed else 0)
        return self.send_input_event(EVT_KEYBOARD_KEY, data)

    def send_scroll(self, dx, dy):
        """Forward a scroll event to the compositor."""
        data = struct.pack("!ff", dx, dy)
        return self.send_input_event(EVT_MOUSE_SCROLL, data)


# ─── Global State ───────────────────────────────────────────────────

compositor = CompositorConnection()


# ─── Desktop Scene Setup ────────────────────────────────────────────

def create_desktop_scene():
    """Create the default BledOS desktop scene with a room environment."""

    # Create or get the desktop scene
    scene = bpy.data.scenes.get(BLEDOs_SCENE_NAME)
    if scene is None:
        scene = bpy.data.scenes.new(BLEDOs_SCENE_NAME)

    # Set up the room floor
    floor_name = "BledOS_Floor"
    if floor_name not in bpy.data.objects:
        bpy.ops.mesh.primitive_plane_add(
            size=DEFAULT_ROOM_SCALE,
            location=(0, 0, 0),
        )
        floor = bpy.context.active_object
        floor.name = floor_name

        # Apply a grid material
        mat = bpy.data.materials.new(name="BledOS_Floor_Material")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # Clear default nodes
        for node in nodes:
            nodes.remove(node)

        # Create a simple grid shader
        output = nodes.new("ShaderNodeOutputMaterial")
        principled = nodes.new("ShaderNodeBsdfPrincipled")
        principled.inputs["Base Color"].default_value = (0.15, 0.15, 0.18, 1.0)
        principled.inputs["Roughness"].default_value = 0.8

        links.new(principled.outputs["BSDF"], output.inputs["Surface"])
        floor.data.materials.append(mat)

    # Set up lighting
    light_name = "BledOS_Room_Light"
    if light_name not in bpy.data.objects:
        light_data = bpy.data.lights.new(name="BledOS_Room_Light_Data", type="AREA")
        light_data.energy = 500
        light_data.size = 10
        light_obj = bpy.data.objects.new(light_name, light_data)
        scene.collection.objects.link(light_obj)
        light_obj.location = (0, 0, 5)
        light_obj.rotation_euler = (0, 0, 0)

    # Set up the camera
    cam_name = "BledOS_Desktop_Camera"
    if cam_name not in bpy.data.objects:
        cam_data = bpy.data.cameras.new(name="BledOS_Desktop_Camera_Data")
        cam_data.lens = 50
        cam_obj = bpy.data.objects.new(cam_name, cam_data)
        scene.collection.objects.link(cam_obj)
        cam_obj.location = (0, -8, 5)
        cam_obj.rotation_euler = (1.1, 0, 0)  # Looking slightly downward
        scene.camera = cam_obj

    # Set up world background (dark gradient)
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("BledOS_World")
        scene.world = world

    world.use_nodes = True
    bg_node = world.node_tree.nodes.get("Background")
    if bg_node:
        bg_node.inputs["Color"].default_value = (0.05, 0.05, 0.08, 1.0)
        bg_node.inputs["Strength"].default_value = 0.5

    return scene


def create_app_window_object(client_id, title, width, height):
    """Create a 3D object in the desktop scene representing an application window."""

    scene = bpy.data.scenes.get(BLEDOs_SCENE_NAME)
    if scene is None:
        return None

    obj_name = f"BledOS_App_{client_id}"
    if obj_name in bpy.data.objects:
        return bpy.data.objects[obj_name]

    # Create a plane for the window
    aspect = width / height if height > 0 else 1.0
    plane_width = 4.0 * aspect
    plane_height = 4.0

    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0, 0, plane_height / 2 + 0.5),
    )
    obj = bpy.context.active_object
    obj.name = obj_name
    obj.scale = (plane_width / 2, plane_height / 2, 1.0)

    # Store client metadata as custom properties
    obj["bledos_client_id"] = client_id
    obj["bledos_title"] = title
    obj["bledos_width"] = width
    obj["bledos_height"] = height
    obj["bledos_type"] = "app_window"

    # Create a material with a placeholder texture
    mat = bpy.data.materials.new(name=f"BledOS_App_Mat_{client_id}")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Clear defaults
    for node in nodes:
        nodes.remove(node)

    output = nodes.new("ShaderNodeOutputMaterial")
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    tex_image = nodes.new("ShaderNodeTexImage")

    # Placeholder color
    principled.inputs["Base Color"].default_value = (0.2, 0.2, 0.25, 1.0)
    principled.inputs["Emission Color"].default_value = (0.1, 0.1, 0.15, 1.0)
    principled.inputs["Emission Strength"].default_value = 0.5

    links.new(tex_image.outputs["Color"], principled.inputs["Base Color"])
    links.new(tex_image.outputs["Color"], principled.inputs["Emission Color"])
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    obj.data.materials.append(mat)

    # Position the window (simple layout: offset each new window)
    offset_x = len([o for o in scene.objects
                     if o.get("bledos_type") == "app_window"]) * 5.0
    obj.location.x = offset_x

    return obj


# ─── Operators ───────────────────────────────────────────────────────

class BLEDOs_OT_connect_compositor(bpy.types.Operator):
    """Connect to the BledOS Compositor"""
    bl_idname = "bledos.connect_compositor"
    bl_label = "Connect to Compositor"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if compositor.connect():
            self.report({"INFO"}, "Connected to BledOS Compositor")
            compositor.list_clients()
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, "Failed to connect to compositor")
            return {"CANCELLED"}


class BLEDOs_OT_disconnect_compositor(bpy.types.Operator):
    """Disconnect from the BledOS Compositor"""
    bl_idname = "bledos.disconnect_compositor"
    bl_label = "Disconnect from Compositor"
    bl_options = {"REGISTER"}

    def execute(self, context):
        compositor.disconnect()
        self.report({"INFO"}, "Disconnected from compositor")
        return {"FINISHED"}


class BLEDOs_OT_list_clients(bpy.types.Operator):
    """List active Wayland clients"""
    bl_idname = "bledos.list_clients"
    bl_label = "List Clients"
    bl_options = {"REGISTER"}

    def execute(self, context):
        clients = compositor.list_clients()
        if clients:
            for c in clients:
                print(f"  Client {c['client_id']}: {c['title']} ({c['size'][0]}x{c['size'][1]})")
            self.report({"INFO"}, f"Found {len(clients)} clients")
        else:
            self.report({"INFO"}, "No clients found")
        return {"FINISHED"}


class BLEDOs_OT_setup_desktop(bpy.types.Operator):
    """Set up the BledOS desktop scene"""
    bl_idname = "bledos.setup_desktop"
    bl_label = "Setup Desktop"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = create_desktop_scene()
        bpy.context.window.scene = scene
        self.report({"INFO"}, "BledOS desktop scene created")
        return {"FINISHED"}


class BLEDOs_OT_lock_screen(bpy.types.Operator):
    """Lock the BledOS screen"""
    bl_idname = "bledos.lock_screen"
    bl_label = "Lock Screen"
    bl_options = {"REGISTER"}

    def execute(self, context):
        # TODO: Implement screen locking with password prompt
        self.report({"INFO"}, "Screen lock not yet implemented")
        return {"FINISHED"}


class BLEDOs_OT_power_menu(bpy.types.Operator):
    """Show the BledOS power menu"""
    bl_idname = "bledos.power_menu"
    bl_label = "Power Menu"
    bl_options = {"REGISTER"}

    def execute(self, context):
        # TODO: Implement power menu (suspend, restart, shutdown)
        self.report({"INFO"}, "Power menu not yet implemented")
        return {"FINISHED"}


# ─── Panel ──────────────────────────────────────────────────────────

class BLEDOs_PT_shell_status(bpy.types.Panel):
    """BledOS Shell status panel"""
    bl_label = "BledOS Shell"
    bl_idname = "BLEDOs_PT_shell_status"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS"

    def draw(self, context):
        layout = self.layout

        # Connection status
        col = layout.column()
        if compositor.connected:
            col.label(text="● Connected", icon="CHECKMARK")
            col.operator("bledos.disconnect_compositor", text="Disconnect")
        else:
            col.label(text="○ Disconnected", icon="X")
            col.operator("bledos.connect_compositor", text="Connect")

        layout.separator()

        # Desktop setup
        col = layout.column()
        col.operator("bledos.setup_desktop", text="Setup Desktop", icon="HOME")

        layout.separator()

        # Client list
        col = layout.column()
        col.operator("bledos.list_clients", text="Refresh Clients", icon="FILE_REFRESH")

        with compositor._lock:
            for cid, info in compositor.clients.items():
                row = col.row()
                row.label(text=f"{info.get('title', 'Unknown')}", icon="WINDOW")
                # TODO: Add focus/close buttons per client

        layout.separator()

        # Power options
        col = layout.column()
        col.operator("bledos.lock_screen", text="Lock", icon="LOCKED")
        col.operator("bledos.power_menu", text="Power", icon="QUIT")


# ─── System Tray Properties ─────────────────────────────────────────

class BledOSSystemTrayProperties(bpy.types.PropertyGroup):
    """Properties for the BledOS system tray display."""
    network_status: bpy.props.StringProperty(
        name="Network Status",
        default="Unknown",
    )
    network_ssid: bpy.props.StringProperty(
        name="WiFi SSID",
        default="",
    )
    battery_percent: bpy.props.IntProperty(
        name="Battery Percentage",
        default=100,
        min=0,
        max=100,
    )
    battery_charging: bpy.props.BoolProperty(
        name="Battery Charging",
        default=False,
    )
    volume_level: bpy.props.FloatProperty(
        name="Volume Level",
        default=0.75,
        min=0.0,
        max=1.0,
    )
    clock_time: bpy.props.StringProperty(
        name="Current Time",
        default="",
    )


# ─── Registration ───────────────────────────────────────────────────

classes = (
    BLEDOs_OT_connect_compositor,
    BLEDOs_OT_disconnect_compositor,
    BLEDOs_OT_list_clients,
    BLEDOs_OT_setup_desktop,
    BLEDOs_OT_lock_screen,
    BLEDOs_OT_power_menu,
    BLEDOs_PT_shell_status,
    BledOSSystemTrayProperties,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bledos_system_tray = bpy.props.PointerProperty(
        type=BledOSSystemTrayProperties
    )
    print("[BledOS] Core shell add-on registered")

    # Auto-connect to compositor if available
    if os.path.exists(COMPOSITOR_SOCK):
        compositor.connect()


def unregister():
    if compositor.connected:
        compositor.disconnect()
    del bpy.types.Scene.bledos_system_tray
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[BledOS] Core shell add-on unregistered")