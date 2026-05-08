"""
BledOS System Settings Add-on
===============================

Provides system configuration panels within Blender for managing
network (NetworkManager), audio (PipeWire), display (wlroots),
power (UPower), and other system services via D-Bus.

Blender version: 4.2+
Location: BledOS Shell > Settings
"""

bl_info = {
    "name": "BledOS System Settings",
    "author": "BledOS Project",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "BledOS Shell",
    "description": "System settings panels for BledOS desktop environment",
    "category": "System",
}

import bpy
import json
import os
import subprocess
import threading
from pathlib import Path

# ─── Constants ──────────────────────────────────────────────────────────────

DBUS_NM_SERVICE = "org.freedesktop.NetworkManager"
DBUS_PW_SERVICE = "org.freedesktop.pipewire0"
DBUS_UPOWER_SERVICE = "org.freedesktop.UPower"
DBUS_UDISKS_SERVICE = "org.freedesktop.UDisks2"

# ─── D-Bus Helper ───────────────────────────────────────────────────────────

def dbus_call(bus_type, service, object_path, interface, method, args=None):
    """Make a D-Bus method call using dbus-send or gdbus.

    Args:
        bus_type: "system" or "session"
        service: D-Bus service name
        object_path: D-Bus object path
        interface: D-Bus interface name
        method: Method name
        args: List of argument strings for dbus-send format

    Returns:
        Parsed output or None on failure
    """
    cmd = ["dbus-send", f"--{bus_type}", "--print-reply",
           f"--dest={service}", object_path,
           f"{interface}.{method}"]
    if args:
        cmd.extend(args)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"[BledOS Settings] D-Bus call failed: {e}")
        return None


def dbus_get_property(bus_type, service, object_path, interface, prop_name):
    """Get a D-Bus property value."""
    return dbus_call(
        bus_type, service, object_path,
        "org.freedesktop.DBus.Properties", "Get",
        [f"string:{interface}", f"string:{prop_name}"]
    )


def parse_dbus_string(output):
    """Parse a D-Bus string reply."""
    if not output:
        return None
    for line in output.split("\n"):
        if "string" in line:
            parts = line.split('"')
            if len(parts) >= 2:
                return parts[1]
    return None


def parse_dbus_int(output):
    """Parse a D-Bus integer reply."""
    if not output:
        return None
    for line in output.split("\n"):
        if "int32" in line or "uint32" in line:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    return int(parts[-1])
                except ValueError:
                    pass
    return None


def parse_dbus_double(output):
    """Parse a D-Bus double reply."""
    if not output:
        return None
    for line in output.split("\n"):
        if "double" in line:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    return float(parts[-1])
                except ValueError:
                    pass
    return None


def parse_dbus_bool(output):
    """Parse a D-Bus boolean reply."""
    if not output:
        return None
    for line in output.split("\n"):
        if "boolean" in line:
            return "true" in line.lower()
    return None


# ─── Network Manager Interface ──────────────────────────────────────────────

class NetworkManager:
    """Interface to NetworkManager via D-Bus."""

    NM_PATH = "/org/freedesktop/NetworkManager"
    NM_IFACE = "org.freedesktop.NetworkManager"

    @staticmethod
    def get_state():
        """Get the overall networking state."""
        output = dbus_get_property(
            "system", DBUS_NM_SERVICE,
            NetworkManager.NM_PATH,
            NetworkManager.NM_IFACE, "State"
        )
        state = parse_dbus_int(output)
        # NM states: 0=unknown, 10=asleep, 20=disconnected, 30=disconnecting,
        #           40=connecting, 50=connected-local, 60=connected-site, 70=connected-global
        state_names = {
            0: "Unknown", 10: "Asleep", 20: "Disconnected",
            30: "Disconnecting", 40: "Connecting",
            50: "Connected (Local)", 60: "Connected (Site)",
            70: "Connected (Global)",
        }
        return state_names.get(state, "Unknown") if state is not None else "Unavailable"

    @staticmethod
    def get_wifi_devices():
        """Get list of WiFi device paths."""
        output = dbus_call(
            "system", DBUS_NM_SERVICE,
            NetworkManager.NM_PATH,
            NetworkManager.NM_IFACE, "GetDevices",
        )
        if not output:
            return []
        # Parse device paths from output
        devices = []
        for line in output.split("\n"):
            if "object path" in line:
                path = line.split('"')[1] if '"' in line else ""
                if path:
                    devices.append(path)
        return devices

    @staticmethod
    def get_active_connections():
        """Get list of active connection paths."""
        output = dbus_get_property(
            "system", DBUS_NM_SERVICE,
            NetworkManager.NM_PATH,
            NetworkManager.NM_IFACE, "ActiveConnections"
        )
        if not output:
            return []
        connections = []
        for line in output.split("\n"):
            if "object path" in line:
                path = line.split('"')[1] if '"' in line else ""
                if path and path != "/":
                    connections.append(path)
        return connections

    @staticmethod
    def get_connection_info(conn_path):
        """Get details about an active connection."""
        info = {"id": "Unknown", "type": "Unknown", "state": "Unknown"}

        # Get connection ID
        output = dbus_get_property(
            "system", DBUS_NM_SERVICE, conn_path,
            "org.freedesktop.NetworkManager.Connection.Active", "Id"
        )
        conn_id = parse_dbus_string(output)
        if conn_id:
            info["id"] = conn_id

        # Get connection type
        output = dbus_get_property(
            "system", DBUS_NM_SERVICE, conn_path,
            "org.freedesktop.NetworkManager.Connection.Active", "Type"
        )
        conn_type = parse_dbus_string(output)
        if conn_type:
            info["type"] = conn_type

        return info

    @staticmethod
    def wifi_scan():
        """Request a WiFi scan."""
        # This would trigger a scan on all WiFi devices
        # For now, use nmcli as a simpler interface
        try:
            result = subprocess.run(
                ["nmcli", "device", "wifi", "list", "--output-json"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception as e:
            print(f"[BledOS Settings] WiFi scan failed: {e}")
        return None

    @staticmethod
    def wifi_connect(ssid, password=""):
        """Connect to a WiFi network."""
        cmd = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            cmd.extend(["password", password])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0
        except Exception as e:
            print(f"[BledOS Settings] WiFi connect failed: {e}")
            return False

    @staticmethod
    def wifi_disconnect():
        """Disconnect from the current WiFi network."""
        try:
            result = subprocess.run(
                ["nmcli", "device", "disconnect", "wlan0"],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False


# ─── Audio (PipeWire) Interface ─────────────────────────────────────────────

class AudioManager:
    """Interface to PipeWire/PulseAudio via pactl/wpctl."""

    @staticmethod
    def get_volume():
        """Get the current master volume (0-100)."""
        try:
            result = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                # Output like "Volume: 0.75 [MUTED]"
                parts = result.stdout.strip().split()
                if len(parts) >= 2:
                    vol = float(parts[1])
                    return int(vol * 100)
        except Exception:
            pass
        return 75

    @staticmethod
    def set_volume(percent):
        """Set the master volume (0-150)."""
        vol = max(0, min(150, percent)) / 100.0
        try:
            subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", str(vol)],
                capture_output=True, timeout=5
            )
            return True
        except Exception:
            return False

    @staticmethod
    def get_muted():
        """Check if audio is muted."""
        try:
            result = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True, timeout=5
            )
            return "MUTED" in result.stdout
        except Exception:
            return False

    @staticmethod
    def toggle_mute():
        """Toggle audio mute."""
        try:
            subprocess.run(
                ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
                capture_output=True, timeout=5
            )
            return True
        except Exception:
            return False

    @staticmethod
    def get_sinks():
        """List available audio output devices."""
        try:
            result = subprocess.run(
                ["wpctl", "status"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout
        except Exception:
            pass
        return "No audio devices found"

    @staticmethod
    def set_default_sink(sink_id):
        """Set the default audio output."""
        try:
            subprocess.run(
                ["wpctl", "set-default", str(sink_id)],
                capture_output=True, timeout=5
            )
            return True
        except Exception:
            return False


# ─── Power (UPower) Interface ───────────────────────────────────────────────

class PowerManager:
    """Interface to UPower via D-Bus for battery and power management."""

    UPOWER_PATH = "/org/freedesktop/UPower"
    UPOWER_IFACE = "org.freedesktop.UPower"

    @staticmethod
    def get_battery_info():
        """Get battery status information."""
        info = {
            "present": False,
            "percentage": 100,
            "state": "Unknown",
            "charging": False,
            "time_remaining": 0,
        }

        # Find the battery device
        try:
            result = subprocess.run(
                ["upower", "-e"],
                capture_output=True, text=True, timeout=5
            )
            battery_path = None
            for line in result.stdout.split("\n"):
                if "BAT" in line:
                    battery_path = line.strip()
                    break

            if battery_path:
                result = subprocess.run(
                    ["upower", "-i", battery_path],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.split("\n"):
                    if "percentage" in line:
                        pct = line.split(":")[-1].strip().replace("%", "")
                        try:
                            info["percentage"] = int(pct)
                        except ValueError:
                            pass
                    elif "state" in line and "charging" in line.lower():
                        info["charging"] = True
                        info["state"] = "Charging"
                    elif "state" in line and "discharging" in line.lower():
                        info["state"] = "Discharging"
                    elif "state" in line and "fully-charged" in line.lower():
                        info["state"] = "Fully Charged"
                    elif "time to" in line:
                        info["time_remaining"] = line.split(":")[-1].strip()
                    elif "present" in line and "yes" in line.lower():
                        info["present"] = True
        except Exception as e:
            print(f"[BledOS Settings] Battery info failed: {e}")

        return info

    @staticmethod
    def suspend():
        """Suspend the system."""
        try:
            subprocess.run(["systemctl", "suspend"],
                         capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    @staticmethod
    def hibernate():
        """Hibernate the system."""
        try:
            subprocess.run(["systemctl", "hibernate"],
                         capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    @staticmethod
    def reboot():
        """Reboot the system."""
        try:
            subprocess.run(["systemctl", "reboot"],
                         capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    @staticmethod
    def power_off():
        """Power off the system."""
        try:
            subprocess.run(["systemctl", "poweroff"],
                         capture_output=True, timeout=5)
            return True
        except Exception:
            return False


# ─── Display Settings ───────────────────────────────────────────────────────

class DisplayManager:
    """Display configuration via wlr-randr or custom compositor commands."""

    @staticmethod
    def get_outputs():
        """Get list of display outputs."""
        try:
            result = subprocess.run(
                ["wlr-randr"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout
        except FileNotFoundError:
            pass

        # Fallback: try querying the compositor
        try:
            sock = os.environ.get("BLEDOs_COMPOSITOR_SOCK", "/run/bledos/compositor.sock")
            # Would send a JSON command to list outputs
            # For now return basic info
        except Exception:
            pass

        return "No display information available"

    @staticmethod
    def set_resolution(output, width, height):
        """Set the resolution for a display output."""
        try:
            subprocess.run(
                ["wlr-randr", "--output", output,
                 "--mode", f"{width}x{height}"],
                capture_output=True, timeout=5
            )
            return True
        except Exception:
            return False

    @staticmethod
    def set_scale(output, scale):
        """Set the scale factor for a display output."""
        try:
            subprocess.run(
                ["wlr-randr", "--output", output,
                 "--scale", str(scale)],
                capture_output=True, timeout=5
            )
            return True
        except Exception:
            return False

    @staticmethod
    def set_brightness(percent):
        """Set display brightness (0-100)."""
        # Try backlight control
        backlight_path = Path("/sys/class/backlight")
        try:
            for bl in backlight_path.iterdir():
                max_file = bl / "max_brightness"
                cur_file = bl / "brightness"
                if max_file.exists() and cur_file.exists():
                    max_val = int(max_file.read_text().strip())
                    new_val = int(max_val * percent / 100)
                    cur_file.write_text(str(new_val))
                    return True
        except (PermissionError, FileNotFoundError):
            pass

        # Fallback: try brightnessctl
        try:
            subprocess.run(
                ["brightnessctl", "set", f"{percent}%"],
                capture_output=True, timeout=5
            )
            return True
        except Exception:
            return False


# ─── Disk Management Interface ──────────────────────────────────────────────

class DiskManager:
    """Interface to udisks2 for disk management."""

    @staticmethod
    def list_disks():
        """List available disk devices."""
        try:
            result = subprocess.run(
                ["lsblk", "--json", "--output",
                 "NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception:
            pass
        return None

    @staticmethod
    def mount_device(device):
        """Mount a device using udisks2."""
        try:
            result = subprocess.run(
                ["udisksctl", "mount", "-b", device],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def unmount_device(device):
        """Unmount a device using udisks2."""
        try:
            result = subprocess.run(
                ["udisksctl", "unmount", "-b", device],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False


# ─── Properties ─────────────────────────────────────────────────────────────

class BledOSSettingsProperties(bpy.types.PropertyGroup):
    """Properties for the BledOS system settings."""

    # Network
    network_state: bpy.props.StringProperty(name="Network State", default="Unknown")
    wifi_ssid: bpy.props.StringProperty(name="WiFi SSID", default="")
    wifi_password: bpy.props.StringProperty(name="WiFi Password", default="", subtype="PASSWORD")

    # Audio
    volume_level: bpy.props.IntProperty(name="Volume", default=75, min=0, max=150)
    audio_muted: bpy.props.BoolProperty(name="Muted", default=False)

    # Display
    display_brightness: bpy.props.IntProperty(name="Brightness", default=100, min=0, max=100)
    display_scale: bpy.props.FloatProperty(name="Scale", default=1.0, min=0.5, max=3.0)

    # Power
    battery_percentage: bpy.props.IntProperty(name="Battery", default=100, min=0, max=100)
    battery_state: bpy.props.StringProperty(name="Battery State", default="Unknown")
    on_battery: bpy.props.BoolProperty(name="On Battery", default=False)


# ─── Operators ──────────────────────────────────────────────────────────────

class BLEDOs_OT_settings_refresh_network(bpy.types.Operator):
    """Refresh network status"""
    bl_idname = "bledos.settings_refresh_network"
    bl_label = "Refresh Network"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.bledos_settings_props
        props.network_state = NetworkManager.get_state()
        self.report({"INFO"}, f"Network: {props.network_state}")
        return {"FINISHED"}


class BLEDOs_OT_settings_wifi_connect(bpy.types.Operator):
    """Connect to a WiFi network"""
    bl_idname = "bledos.settings_wifi_connect"
    bl_label = "Connect WiFi"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.bledos_settings_props
        ssid = props.wifi_ssid
        password = props.wifi_password

        if not ssid:
            self.report({"ERROR"}, "No SSID specified")
            return {"CANCELLED"}

        success = NetworkManager.wifi_connect(ssid, password)
        if success:
            props.network_state = "Connected"
            self.report({"INFO"}, f"Connected to {ssid}")
        else:
            self.report({"ERROR"}, f"Failed to connect to {ssid}")
            return {"CANCELLED"}

        return {"FINISHED"}


class BLEDOs_OT_settings_wifi_disconnect(bpy.types.Operator):
    """Disconnect from WiFi"""
    bl_idname = "bledos.settings_wifi_disconnect"
    bl_label = "Disconnect WiFi"
    bl_options = {"REGISTER"}

    def execute(self, context):
        NetworkManager.wifi_disconnect()
        context.scene.bledos_settings_props.network_state = "Disconnected"
        self.report({"INFO"}, "Disconnected from WiFi")
        return {"FINISHED"}


class BLEDOs_OT_settings_wifi_scan(bpy.types.Operator):
    """Scan for WiFi networks"""
    bl_idname = "bledos.settings_wifi_scan"
    bl_label = "Scan WiFi"
    bl_options = {"REGISTER"}

    def execute(self, context):
        networks = NetworkManager.wifi_scan()
        if networks:
            self.report({"INFO"}, "WiFi scan complete")
        else:
            self.report({"WARNING"}, "No WiFi networks found")
        return {"FINISHED"}


class BLEDOs_OT_settings_volume_set(bpy.types.Operator):
    """Set the system volume"""
    bl_idname = "bledos.settings_volume_set"
    bl_label = "Set Volume"
    bl_options = {"REGISTER"}

    volume: bpy.props.IntProperty(name="Volume", min=0, max=150, default=75)

    def execute(self, context):
        AudioManager.set_volume(self.volume)
        context.scene.bledos_settings_props.volume_level = self.volume
        self.report({"INFO"}, f"Volume set to {self.volume}%")
        return {"FINISHED"}


class BLEDOs_OT_settings_toggle_mute(bpy.types.Operator):
    """Toggle audio mute"""
    bl_idname = "bledos.settings_toggle_mute"
    bl_label = "Toggle Mute"
    bl_options = {"REGISTER"}

    def execute(self, context):
        AudioManager.toggle_mute()
        props = context.scene.bledos_settings_props
        props.audio_muted = not props.audio_muted
        state = "muted" if props.audio_muted else "unmuted"
        self.report({"INFO"}, f"Audio {state}")
        return {"FINISHED"}


class BLEDOs_OT_settings_brightness_set(bpy.types.Operator):
    """Set display brightness"""
    bl_idname = "bledos.settings_brightness_set"
    bl_label = "Set Brightness"
    bl_options = {"REGISTER"}

    brightness: bpy.props.IntProperty(name="Brightness", min=0, max=100, default=100)

    def execute(self, context):
        DisplayManager.set_brightness(self.brightness)
        context.scene.bledos_settings_props.display_brightness = self.brightness
        self.report({"INFO"}, f"Brightness set to {self.brightness}%")
        return {"FINISHED"}


class BLEDOs_OT_settings_refresh_power(bpy.types.Operator):
    """Refresh power/battery status"""
    bl_idname = "bledos.settings_refresh_power"
    bl_label = "Refresh Power"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.bledos_settings_props
        info = PowerManager.get_battery_info()
        props.battery_percentage = info["percentage"]
        props.battery_state = info["state"]
        props.on_battery = info["state"] == "Discharging"
        self.report({"INFO"}, f"Battery: {info['percentage']}% ({info['state']})")
        return {"FINISHED"}


class BLEDOs_OT_settings_suspend(bpy.types.Operator):
    """Suspend the system"""
    bl_idname = "bledos.settings_suspend"
    bl_label = "Suspend"
    bl_options = {"REGISTER"}

    def execute(self, context):
        PowerManager.suspend()
        return {"FINISHED"}


class BLEDOs_OT_settings_reboot(bpy.types.Operator):
    """Reboot the system"""
    bl_idname = "bledos.settings_reboot"
    bl_label = "Reboot"
    bl_options = {"REGISTER"}

    def execute(self, context):
        PowerManager.reboot()
        return {"FINISHED"}


class BLEDOs_OT_settings_poweroff(bpy.types.Operator):
    """Power off the system"""
    bl_idname = "bledos.settings_poweroff"
    bl_label = "Power Off"
    bl_options = {"REGISTER"}

    def execute(self, context):
        PowerManager.power_off()
        return {"FINISHED"}


class BLEDOs_OT_settings_refresh_all(bpy.types.Operator):
    """Refresh all system settings"""
    bl_idname = "bledos.settings_refresh_all"
    bl_label = "Refresh All"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.bledos_settings_props

        # Network
        props.network_state = NetworkManager.get_state()

        # Audio
        props.volume_level = AudioManager.get_volume()
        props.audio_muted = AudioManager.get_muted()

        # Power
        info = PowerManager.get_battery_info()
        props.battery_percentage = info["percentage"]
        props.battery_state = info["state"]
        props.on_battery = info["state"] == "Discharging"

        self.report({"INFO"}, "All settings refreshed")
        return {"FINISHED"}


# ─── Panels ─────────────────────────────────────────────────────────────────

class BLEDOs_PT_settings_network(bpy.types.Panel):
    """Network settings panel"""
    bl_label = "Network"
    bl_idname = "BLEDOs_PT_settings_network"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS Settings"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.bledos_settings_props

        # Status
        col = layout.column()
        state = props.network_state
        icon = "INTERNET" if "Connected" in state else "INTERNET_FAKE"
        col.label(text=f"Status: {state}", icon=icon)

        # WiFi connection
        layout.separator()
        col = layout.column()
        col.prop(props, "wifi_ssid", text="SSID")
        col.prop(props, "wifi_password", text="Password")

        row = col.row(align=True)
        row.operator("bledos.settings_wifi_connect", text="Connect", icon="INTERNET")
        row.operator("bledos.settings_wifi_disconnect", text="Disconnect", icon="X")

        row = layout.row()
        row.operator("bledos.settings_wifi_scan", text="Scan", icon="VIEWZOOM")
        row.operator("bledos.settings_refresh_network", text="Refresh", icon="FILE_REFRESH")


class BLEDOs_PT_settings_audio(bpy.types.Panel):
    """Audio settings panel"""
    bl_label = "Audio"
    bl_idname = "BLEDOs_PT_settings_audio"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS Settings"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.bledos_settings_props

        col = layout.column()
        col.label(text=f"Volume: {props.volume_level}%", icon="SPEAKER")

        # Volume slider
        col.prop(props, "volume_level", text="Volume", slider=True)
        op = col.operator("bledos.settings_volume_set", text="Apply Volume")
        op.volume = props.volume_level

        # Mute toggle
        col.operator("bledos.settings_toggle_mute",
                     text="Unmute" if props.audio_muted else "Mute",
                     icon="MUTE_IPO" if props.audio_muted else "SPEAKER")


class BLEDOs_PT_settings_display(bpy.types.Panel):
    """Display settings panel"""
    bl_label = "Display"
    bl_idname = "BLEDOs_PT_settings_display"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS Settings"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.bledos_settings_props

        col = layout.column()
        col.label(text=f"Brightness: {props.display_brightness}%", icon="LIGHT_SUN")
        col.prop(props, "display_brightness", text="Brightness", slider=True)
        op = col.operator("bledos.settings_brightness_set", text="Apply Brightness")
        op.brightness = props.display_brightness

        layout.separator()
        col = layout.column()
        col.prop(props, "display_scale", text="Scale Factor", slider=True)


class BLEDOs_PT_settings_power(bpy.types.Panel):
    """Power settings panel"""
    bl_label = "Power"
    bl_idname = "BLEDOs_PT_settings_power"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS Settings"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.bledos_settings_props

        # Battery info
        col = layout.column()
        if props.on_battery:
            icon = "BATTERY"
            col.label(text=f"Battery: {props.battery_percentage}%", icon=icon)
            col.label(text=f"State: {props.battery_state}")
        else:
            col.label(text=f"Battery: {props.battery_percentage}% (Charging)", icon="BATTERY")

        # Battery bar
        col.prop(props, "battery_percentage", text="Level", slider=True)

        layout.separator()

        # Power actions
        col = layout.column()
        col.operator("bledos.settings_suspend", text="Suspend", icon="SORTTIME")
        col.operator("bledos.settings_reboot", text="Reboot", icon="RECOVER_LAST")
        col.operator("bledos.settings_poweroff", text="Power Off", icon="QUIT")

        layout.separator()
        col.operator("bledos.settings_refresh_power", text="Refresh", icon="FILE_REFRESH")


class BLEDOs_PT_settings_main(bpy.types.Panel):
    """Main settings panel with overview"""
    bl_label = "System Settings"
    bl_idname = "BLEDOs_PT_settings_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS"

    def draw(self, context):
        layout = self.layout
        props = context.scene.bledos_settings_props

        # Overview
        col = layout.column()

        # Network status
        net_state = props.network_state
        net_icon = "INTERNET" if "Connected" in net_state else "INTERNET_FAKE"
        col.label(text=f"Network: {net_state}", icon=net_icon)

        # Audio
        vol_text = f"Volume: {props.volume_level}%"
        if props.audio_muted:
            vol_text += " (Muted)"
        col.label(text=vol_text, icon="SPEAKER")

        # Power
        if props.on_battery:
            col.label(text=f"Battery: {props.battery_percentage}% ({props.battery_state})",
                     icon="BATTERY")
        else:
            col.label(text=f"Battery: {props.battery_percentage}%", icon="BATTERY")

        layout.separator()
        col.operator("bledos.settings_refresh_all", text="Refresh All", icon="FILE_REFRESH")


# ─── Registration ───────────────────────────────────────────────────────────

classes = (
    BledOSSettingsProperties,
    BLEDOs_OT_settings_refresh_network,
    BLEDOs_OT_settings_wifi_connect,
    BLEDOs_OT_settings_wifi_disconnect,
    BLEDOs_OT_settings_wifi_scan,
    BLEDOs_OT_settings_volume_set,
    BLEDOs_OT_settings_toggle_mute,
    BLEDOs_OT_settings_brightness_set,
    BLEDOs_OT_settings_refresh_power,
    BLEDOs_OT_settings_suspend,
    BLEDOs_OT_settings_reboot,
    BLEDOs_OT_settings_poweroff,
    BLEDOs_OT_settings_refresh_all,
    BLEDOs_PT_settings_network,
    BLEDOs_PT_settings_audio,
    BLEDOs_PT_settings_display,
    BLEDOs_PT_settings_power,
    BLEDOs_PT_settings_main,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bledos_settings_props = bpy.props.PointerProperty(
        type=BledOSSettingsProperties
    )
    print("[BledOS] System Settings add-on registered")


def unregister():
    del bpy.types.Scene.bledos_settings_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[BledOS] System Settings add-on unregistered")