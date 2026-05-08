"""
BledOS Input Router Add-on
============================

Routes input events between Blender's 3D viewport and Wayland clients.
Uses raycasting to determine which application window the user clicked,
then translates viewport coordinates to the client's local coordinate
system and forwards events through the compositor's input socket.

Key features:
- Raycasting from viewport camera to determine clicked surface
- UV coordinate extraction from ray hit for client-local coordinates
- Keyboard focus tracking and event forwarding
- Mouse movement delta calculation and smoothing
- Scroll wheel and gesture translation
- Input grab management for fullscreen apps

Blender version: 4.2+
Location: BledOS Shell > Input Router
"""

bl_info = {
    "name": "BledOS Input Router",
    "author": "BledOS Project",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "BledOS Shell",
    "description": "Input event routing for BledOS desktop environment",
    "category": "System",
}

import bpy
import bmesh
import math
import mathutils
import struct
import time
from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d

# ─── Constants ──────────────────────────────────────────────────────────────

# Input event types (must match compositor protocol)
EVT_MOUSE_MOVE = 0x01
EVT_MOUSE_BUTTON = 0x02
EVT_KEYBOARD_KEY = 0x03
EVT_MOUSE_SCROLL = 0x04
EVT_FOCUS_CHANGE = 0x05

# Mouse button mapping (Blender → Linux input event code)
MOUSE_BUTTON_MAP = {
    "LEFTMOUSE": 0x110,   # BTN_LEFT
    "MIDDLEMOUSE": 0x112, # BTN_MIDDLE
    "RIGHTMOUSE": 0x111,  # BTN_RIGHT
    "BUTTON4MOUSE": 0x113, # BTN_SIDE
    "BUTTON5MOUSE": 0x114, # BTN_EXTRA
}

# Keyboard modifier mapping
MODIFIER_MAP = {
    "LEFT_SHIFT": 0x2A, "RIGHT_SHIFT": 0x36,
    "LEFT_CTRL": 0x1D, "RIGHT_CTRL": 0x1D,
    "LEFT_ALT": 0x38, "RIGHT_ALT": 0x38,
}

# X11/Wayland key codes for common keys (based on evdev keycodes)
KEYCODE_MAP = {
    "RET": 28, "ENTER": 28, "SPACE": 57, "TAB": 15,
    "BACK_SPACE": 14, "DELETE": 111, "HOME": 102, "END": 107,
    "PAGE_UP": 104, "PAGE_DOWN": 109,
    "LEFT_ARROW": 105, "RIGHT_ARROW": 106,
    "UP_ARROW": 103, "DOWN_ARROW": 108,
    "ESC": 1, "F1": 59, "F2": 60, "F3": 61, "F4": 62,
    "F5": 63, "F6": 64, "F7": 65, "F8": 66,
    "F9": 67, "F10": 68, "F11": 87, "F12": 88,
    "ZERO": 11, "ONE": 2, "TWO": 3, "THREE": 4,
    "FOUR": 5, "FIVE": 6, "SIX": 7, "SEVEN": 8,
    "EIGHT": 9, "NINE": 10,
    "A": 30, "B": 48, "C": 46, "D": 32, "E": 18,
    "F": 33, "G": 34, "H": 35, "I": 23, "J": 36,
    "K": 37, "L": 38, "M": 50, "N": 49, "O": 24,
    "P": 25, "Q": 16, "R": 19, "S": 31, "T": 20,
    "U": 22, "V": 47, "W": 17, "X": 45, "Y": 21, "Z": 44,
}

# Double-click threshold in milliseconds
DOUBLE_CLICK_MS = 300


# ─── Raycasting ─────────────────────────────────────────────────────────────

def raycast_viewport(context, event):
    """Cast a ray from the viewport camera through the mouse position.

    Returns:
        Tuple of (hit_object, hit_point, hit_normal, uv_coords) or (None, None, None, None)
    """
    region = context.region
    rv3d = context.region_data

    if region is None or rv3d is None:
        return None, None, None, None

    # Get mouse coordinates in region space
    mouse_x = event.mouse_region_x
    mouse_y = event.mouse_region_y

    # Convert to 3D ray
    try:
        ray_origin = region_2d_to_origin_3d(region, rv3d, (mouse_x, mouse_y))
        ray_direction = region_2d_to_vector_3d(region, rv3d, (mouse_x, mouse_y))
    except Exception:
        return None, None, None, None

    # Perform raycast against the scene
    scene = context.scene
    result, hit_location, hit_normal, hit_face_index, hit_object, hit_matrix = scene.ray_cast(
        view_layer=context.view_layer,
        origin=ray_origin,
        direction=ray_direction,
    )

    if not result or hit_object is None:
        return None, None, None, None

    # Compute UV coordinates if possible
    uv_coords = compute_uv_coords(hit_object, hit_location, hit_face_index)

    return hit_object, hit_location, hit_normal, uv_coords


def compute_uv_coords(obj, hit_location, face_index):
    """Compute UV coordinates at a hit point on a mesh object.

    This converts a 3D hit point to 2D texture coordinates that can
    be used to determine the corresponding pixel in an application window.
    """
    if obj is None or obj.type != "MESH" or face_index < 0:
        return None

    try:
        # Get the mesh data
        mesh = obj.data

        # Check if UVs exist
        if not mesh.uv_layers.active:
            return None

        # Transform hit location to object space
        obj_matrix_inv = obj.matrix_world.inverted()
        local_hit = obj_matrix_inv @ mathutils.Vector(hit_location)

        # Get the face
        face = mesh.polygons[face_index]

        # Barycentric coordinate calculation
        verts = [mesh.vertices[v].co for v in face.vertices]
        uv_layer = mesh.uv_layers.active.data

        if len(verts) < 3:
            return None

        # Compute barycentric coordinates
        v0 = verts[1] - verts[0]
        v1 = verts[2] - verts[0]
        v2 = local_hit - verts[0]

        d00 = v0.dot(v0)
        d01 = v0.dot(v1)
        d11 = v1.dot(v1)
        d20 = v2.dot(v0)
        d21 = v2.dot(v1)

        denom = d00 * d11 - d01 * d01
        if abs(denom) < 1e-8:
            return None

        v = (d11 * d20 - d01 * d21) / denom
        w = (d00 * d21 - d01 * d20) / denom
        u = 1.0 - v - w

        # Clamp to valid range
        u = max(0.0, min(1.0, u))
        v = max(0.0, min(1.0, v))
        w = max(0.0, min(1.0, w))

        # Interpolate UV coordinates
        uv_loops = [mesh.loops[i] for i in face.loop_indices]
        uv0 = uv_layer[uv_loops[0].index].uv
        uv1 = uv_layer[uv_loops[1].index].uv
        uv2 = uv_layer[uv_loops[2].index].uv

        final_u = u * uv0[0] + v * uv1[0] + w * uv2[0]
        final_v = u * uv0[1] + v * uv1[1] + w * uv2[1]

        return (final_u, final_v)

    except Exception as e:
        print(f"[BledOS Input] UV computation error: {e}")
        return None


def uv_to_client_coords(uv, width, height):
    """Convert UV coordinates (0-1) to client pixel coordinates."""
    if uv is None:
        return (0, 0)
    x = int(uv[0] * width)
    y = int((1.0 - uv[1]) * height)  # Flip Y axis (UV vs screen coords)
    return (max(0, min(width - 1, x)), max(0, min(height - 1, y)))


# ─── Focus Management ───────────────────────────────────────────────────────

class FocusManager:
    """Tracks which client has keyboard focus and manages focus changes."""

    def __init__(self):
        self.focused_client_id = None
        self.focused_object = None
        self.hovered_client_id = None
        self._last_click_time = 0
        self._last_click_client = None

    def set_focus(self, client_id, obj=None):
        """Set the focused client."""
        if self.focused_client_id == client_id:
            return

        old_client = self.focused_client_id
        self.focused_client_id = client_id
        self.focused_object = obj

        # Notify compositor of focus change
        try:
            from bledos_core import compositor
            if old_client is not None:
                # Unfocus old client
                pass
            if client_id is not None:
                compositor.set_focus(client_id)
        except ImportError:
            pass

        print(f"[BledOS Input] Focus changed: {old_client} → {client_id}")

    def clear_focus(self):
        """Clear the current focus."""
        self.set_focus(None)

    def is_focused(self, client_id):
        """Check if a client has focus."""
        return self.focused_client_id == client_id

    def check_double_click(self, client_id):
        """Check if this click is a double-click."""
        now = time.time() * 1000
        is_double = (
            client_id == self._last_click_client and
            now - self._last_click_time < DOUBLE_CLICK_MS
        )
        self._last_click_time = now
        self._last_click_client = client_id
        return is_double


# ─── Input Router State ─────────────────────────────────────────────────────

class InputRouterState:
    """Maintains the state of the input routing system."""

    def __init__(self):
        self.focus_manager = FocusManager()
        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_delta_x = 0
        self.mouse_delta_y = 0
        self.mouse_buttons = set()
        self.keyboard_modifiers = set()
        self.input_grabbed = False
        self.grab_client_id = None
        self.enabled = True
        self._last_move_time = 0

    def get_client_from_object(self, obj):
        """Extract client information from a Blender object."""
        if obj is None:
            return None, None, None

        client_id = obj.get("bledos_client_id")
        if client_id is None:
            return None, None, None

        width = obj.get("bledos_width", 800)
        height = obj.get("bledos_height", 600)
        return client_id, width, height


# Global state
input_state = InputRouterState()


# ─── Event Handlers ─────────────────────────────────────────────────────────

def handle_mouse_move(context, event):
    """Handle mouse movement events in the 3D viewport."""
    if not input_state.enabled:
        return

    new_x = event.mouse_region_x
    new_y = event.mouse_region_y

    input_state.mouse_delta_x = new_x - input_state.mouse_x
    input_state.mouse_delta_y = new_y - input_state.mouse_y
    input_state.mouse_x = new_x
    input_state.mouse_y = new_y

    # If input is grabbed, send deltas to grabbed client
    if input_state.input_grabbed and input_state.grab_client_id is not None:
        try:
            from bledos_core import compositor
            compositor.send_mouse_move(
                input_state.mouse_delta_x,
                -input_state.mouse_delta_y,  # Flip Y for Wayland
            )
        except ImportError:
            pass
        return

    # Raycast to determine hovered client
    hit_obj, hit_point, hit_normal, uv = raycast_viewport(context, event)

    if hit_obj and hit_obj.get("bledos_client_id") is not None:
        client_id, width, height = input_state.get_client_from_object(hit_obj)
        input_state.focus_manager.hovered_client_id = client_id

        # Convert to client-local coordinates
        client_x, client_y = uv_to_client_coords(uv, width, height)

        # Send mouse move to hovered client
        try:
            from bledos_core import compositor
            compositor.send_mouse_move(float(client_x), float(client_y))
        except ImportError:
            pass
    else:
        input_state.focus_manager.hovered_client_id = None


def handle_mouse_click(context, event):
    """Handle mouse button press/release events."""
    if not input_state.enabled:
        return

    button_name = event.type
    pressed = event.value == "PRESS"

    # Map button to evdev code
    button_code = MOUSE_BUTTON_MAP.get(button_name)
    if button_code is None:
        return

    if pressed:
        input_state.mouse_buttons.add(button_name)
    else:
        input_state.mouse_buttons.discard(button_name)

    # Raycast to determine clicked client
    hit_obj, hit_point, hit_normal, uv = raycast_viewport(context, event)

    if hit_obj and hit_obj.get("bledos_client_id") is not None:
        client_id, width, height = input_state.get_client_from_object(hit_obj)

        # Set focus on click
        if pressed:
            input_state.focus_manager.set_focus(client_id, hit_obj)
            input_state.focus_manager.check_double_click(client_id)

        # Convert to client-local coordinates
        client_x, client_y = uv_to_client_coords(uv, width, height)

        # Send mouse button event
        try:
            from bledos_core import compositor
            compositor.send_mouse_button(button_code, pressed)
        except ImportError:
            pass
    else:
        # Clicked on empty space or non-client object
        if pressed and button_name == "LEFTMOUSE":
            input_state.focus_manager.clear_focus()


def handle_keyboard(context, event):
    """Handle keyboard events."""
    if not input_state.enabled:
        return

    key_name = event.type
    pressed = event.value == "PRESS"

    # Check if the focused client should receive this key
    if input_state.focus_manager.focused_client_id is None:
        return

    # Get the keycode
    keycode = KEYCODE_MAP.get(key_name)
    if keycode is None:
        # Try character-based mapping
        if len(key_name) == 1 and key_name.isalpha():
            keycode = KEYCODE_MAP.get(key_name.upper())

    if keycode is None:
        return

    # Handle modifiers
    if key_name in MODIFIER_MAP:
        keycode = MODIFIER_MAP[key_name]

    # Forward to compositor
    try:
        from bledos_core import compositor
        compositor.send_key(keycode, pressed)
    except ImportError:
        pass


def handle_scroll(context, event):
    """Handle scroll wheel events."""
    if not input_state.enabled:
        return

    if input_state.focus_manager.focused_client_id is None:
        return

    # Blender scroll events
    dx = 0.0
    dy = 0.0

    if event.type == "WHEELUPMOUSE":
        dy = 3.0  # Scroll up
    elif event.type == "WHEELDOWNMOUSE":
        dy = -3.0  # Scroll down
    elif event.type == "WHEELINMOUSE":
        dy = 3.0
    elif event.type == "WHEELOUTMOUSE":
        dy = -3.0

    try:
        from bledos_core import compositor
        compositor.send_scroll(dx, dy)
    except ImportError:
        pass


def grab_input(client_id):
    """Grab all input for a client (e.g., fullscreen games)."""
    input_state.input_grabbed = True
    input_state.grab_client_id = client_id
    # Hide cursor in viewport
    print(f"[BledOS Input] Input grabbed by client {client_id}")


def ungrab_input():
    """Release the input grab."""
    input_state.input_grabbed = False
    input_state.grab_client_id = None
    print("[BledOS Input] Input grab released")


# ─── Modal Operator ─────────────────────────────────────────────────────────

class BLEDOs_OT_input_router_modal(bpy.types.Operator):
    """Modal operator that captures and routes input events"""
    bl_idname = "bledos.input_router_modal"
    bl_label = "BledOS Input Router"
    bl_options = {"REGISTER", "UNDO"}

    _timer = None

    def modal(self, context, event):
        """Handle events in the modal loop."""
        # Only process events in the 3D viewport
        if context.area and context.area.type != "VIEW_3D":
            return {"PASS_THROUGH"}

        # Skip if event is from the UI
        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            handle_mouse_move(context, event)
            return {"PASS_THROUGH"}

        if event.type in MOUSE_BUTTON_MAP:
            handle_mouse_click(context, event)
            return {"PASS_THROUGH"}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE",
                          "WHEELINMOUSE", "WHEELOUTMOUSE"}:
            handle_scroll(context, event)
            return {"PASS_THROUGH"}

        # Keyboard events
        if event.type in KEYCODE_MAP or event.type in MODIFIER_MAP or \
           (len(event.type) == 1 and event.type.isalpha()):
            handle_keyboard(context, event)
            return {"PASS_THROUGH"}

        return {"PASS_THROUGH"}

    def execute(self, context):
        """Start the modal input router."""
        if context.area:
            context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


# ─── Operators ──────────────────────────────────────────────────────────────

class BLEDOs_OT_input_start(bpy.types.Operator):
    """Start the BledOS input router"""
    bl_idname = "bledos.input_start"
    bl_label = "Start Input Router"
    bl_options = {"REGISTER"}

    def execute(self, context):
        bpy.ops.bledos.input_router_modal()
        input_state.enabled = True
        self.report({"INFO"}, "BledOS input router started")
        return {"FINISHED"}


class BLEDOs_OT_input_stop(bpy.types.Operator):
    """Stop the BledOS input router"""
    bl_idname = "bledos.input_stop"
    bl_label = "Stop Input Router"
    bl_options = {"REGISTER"}

    def execute(self, context):
        input_state.enabled = False
        self.report({"INFO"}, "BledOS input router stopped")
        return {"FINISHED"}


class BLEDOs_OT_input_grab(bpy.types.Operator):
    """Grab input for a client"""
    bl_idname = "bledos.input_grab"
    bl_label = "Grab Input"
    bl_options = {"REGISTER"}

    client_id: bpy.props.IntProperty()

    def execute(self, context):
        grab_input(self.client_id)
        return {"FINISHED"}


class BLEDOs_OT_input_ungrab(bpy.types.Operator):
    """Release input grab"""
    bl_idname = "bledos.input_ungrab"
    bl_label = "Release Input Grab"
    bl_options = {"REGISTER"}

    def execute(self, context):
        ungrab_input()
        return {"FINISHED"}


class BLEDOs_OT_input_test_raycast(bpy.types.Operator):
    """Test raycasting from the current viewport"""
    bl_idname = "bledos.input_test_raycast"
    bl_label = "Test Raycast"
    bl_options = {"REGISTER"}

    def execute(self, context):
        # Perform a test raycast from the center of the viewport
        region = context.region
        rv3d = context.region_data

        if region and rv3d:
            center_x = region.width // 2
            center_y = region.height // 2

            ray_origin = region_2d_to_origin_3d(region, rv3d, (center_x, center_y))
            ray_direction = region_2d_to_vector_3d(region, rv3d, (center_x, center_y))

            result, hit_loc, hit_normal, face_idx, hit_obj, matrix = context.scene.ray_cast(
                view_layer=context.view_layer,
                origin=ray_origin,
                direction=ray_direction,
            )

            if result and hit_obj:
                client_id = hit_obj.get("bledos_client_id", "N/A")
                self.report({"INFO"},
                    f"Hit: {hit_obj.name} (client={client_id}) at {hit_loc}")
            else:
                self.report({"INFO"}, "Raycast: No hit")

        return {"FINISHED"}


# ─── Panel ──────────────────────────────────────────────────────────────────

class BLEDOs_PT_input_router(bpy.types.Panel):
    """BledOS Input Router panel"""
    bl_label = "Input Router"
    bl_idname = "BLEDOs_PT_input_router"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS"

    def draw(self, context):
        layout = self.layout

        # Status
        col = layout.column()
        state_text = "Active" if input_state.enabled else "Inactive"
        icon = "CHECKMARK" if input_state.enabled else "X"
        col.label(text=f"Status: {state_text}", icon=icon)

        # Focus info
        focus_id = input_state.focus_manager.focused_client_id
        if focus_id is not None:
            col.label(text=f"Focused: Client {focus_id}", icon="WINDOW")
        else:
            col.label(text="No client focused", icon="MOUSE_L")

        # Grab info
        if input_state.input_grabbed:
            col.label(text=f"Input grabbed: Client {input_state.grab_client_id}",
                     icon="RESTRICT_SELECT_ON")

        layout.separator()

        # Controls
        col = layout.column()
        col.operator("bledos.input_start", text="Start Router", icon="PLAY")
        col.operator("bledos.input_stop", text="Stop Router", icon="PAUSE")
        col.operator("bledos.input_test_raycast", text="Test Raycast", icon="CURSOR")
        col.operator("bledos.input_ungrab", text="Release Grab", icon="RESTRICT_SELECT_OFF")

        layout.separator()

        # Mouse state
        col = layout.column()
        col.label(text="Mouse State:", icon="MOUSE_L")
        col.label(text=f"  Position: ({input_state.mouse_x}, {input_state.mouse_y})")
        col.label(text=f"  Buttons: {', '.join(input_state.mouse_buttons) or 'None'}")

        # Keyboard state
        col = layout.column()
        col.label(text="Keyboard State:", icon="EVENT")
        mods = input_state.keyboard_modifiers
        col.label(text=f"  Modifiers: {', '.join(mods) if mods else 'None'}")


# ─── Registration ───────────────────────────────────────────────────────────

classes = (
    BLEDOs_OT_input_router_modal,
    BLEDOs_OT_input_start,
    BLEDOs_OT_input_stop,
    BLEDOs_OT_input_grab,
    BLEDOs_OT_input_ungrab,
    BLEDOs_OT_input_test_raycast,
    BLEDOs_PT_input_router,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    print("[BledOS] Input Router add-on registered")


def unregister():
    # Stop input routing
    input_state.enabled = False

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[BledOS] Input Router add-on unregistered")