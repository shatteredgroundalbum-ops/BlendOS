"""
BledOS Terminal Add-on
========================

A terminal emulator that runs PTY subprocesses and displays output
within Blender's text editor or a custom 3D panel. Supports multiple
terminal sessions, shell command execution, and integration with the
BledOS desktop environment.

Blender version: 4.2+
Location: BledOS Shell > Terminal
"""

bl_info = {
    "name": "BledOS Terminal",
    "author": "BledOS Project",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "BledOS Shell",
    "description": "Terminal emulator for BledOS desktop environment",
    "category": "System",
}

import bpy
import os
import select
import signal
import struct
import sys
import termios
import threading
import fcntl
from pathlib import Path
from subprocess import Popen, PIPE

# ─── Constants ──────────────────────────────────────────────────────────────

MAX_OUTPUT_LINES = 5000
SCROLLBACK_LINES = 1000
DEFAULT_SHELL = "/bin/bash"
POLL_INTERVAL = 0.05  # seconds
TERMINAL_TEXT_PREFIX = "BledOS_Term_"


# ─── PTY Terminal Session ───────────────────────────────────────────────────

class TerminalSession:
    """Manages a single PTY-based terminal session."""

    def __init__(self, session_id, shell=None, working_dir=None, env=None):
        self.session_id = session_id
        self.shell = shell or os.environ.get("SHELL", DEFAULT_SHELL)
        self.working_dir = working_dir or str(Path.home())
        self.running = False
        self.process = None
        self.master_fd = None
        self.output_lines = []
        self._lock = threading.Lock()
        self._reader_thread = None
        self._output_callback = None

        # Build environment
        self.env = dict(os.environ)
        self.env["TERM"] = "xterm-256color"
        self.env["COLORTERM"] = "bledos-terminal"
        self.env["BLEDOs_TERMINAL"] = "1"
        if env:
            self.env.update(env)

    def start(self):
        """Start the terminal session with a PTY."""
        try:
            pid, master_fd = os.forkpty()
        except OSError as e:
            print(f"[BledOS Term] Failed to fork PTY: {e}")
            return False

        if pid == 0:
            # Child process
            try:
                os.chdir(self.working_dir)
                os.execvpe(self.shell, [self.shell], self.env)
            except Exception as e:
                print(f"[BledOS Term] Failed to exec shell: {e}")
                os._exit(1)
        else:
            # Parent process
            self.process_pid = pid
            self.master_fd = master_fd
            self.running = True

            # Set non-blocking I/O
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            # Set terminal size
            self.set_size(80, 24)

            # Start reader thread
            self._reader_thread = threading.Thread(
                target=self._read_output,
                daemon=True,
            )
            self._reader_thread.start()

            print(f"[BledOS Term] Session {self.session_id} started (PID: {pid})")
            return True

    def _read_output(self):
        """Background thread that reads PTY output."""
        buffer = ""
        while self.running:
            try:
                data = os.read(self.master_fd, 4096)
                if not data:
                    self.running = False
                    break

                text = data.decode("utf-8", errors="replace")

                with self._lock:
                    # Split into lines
                    lines = text.split("\n")
                    if buffer:
                        lines[0] = buffer + lines[0]
                        buffer = ""

                    # Handle incomplete last line
                    if not text.endswith("\n"):
                        buffer = lines[-1]
                        lines = lines[:-1]

                    self.output_lines.extend(lines)

                    # Trim to max size
                    if len(self.output_lines) > MAX_OUTPUT_LINES + SCROLLBACK_LINES:
                        self.output_lines = self.output_lines[-MAX_OUTPUT_LINES:]

                # Trigger callback if registered
                if self._output_callback:
                    try:
                        self._output_callback(self.session_id, text)
                    except Exception:
                        pass

            except OSError:
                # PTY closed
                self.running = False
                break
            except Exception as e:
                print(f"[BledOS Term] Read error: {e}")
                self.running = False
                break

        # Process exited
        with self._lock:
            if buffer:
                self.output_lines.append(buffer)
            self.output_lines.append("[Process exited]")

        self.running = False
        print(f"[BledOS Term] Session {self.session_id} ended")

    def write(self, text):
        """Send input to the terminal."""
        if not self.running or self.master_fd is None:
            return False

        try:
            os.write(self.master_fd, text.encode("utf-8"))
            return True
        except OSError as e:
            print(f"[BledOS Term] Write error: {e}")
            return False

    def set_size(self, cols, rows):
        """Set the terminal window size."""
        if self.master_fd is None:
            return

        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except Exception as e:
            print(f"[BledOS Term] Set size error: {e}")

    def get_output(self, last_n=None):
        """Get the terminal output as a string."""
        with self._lock:
            lines = list(self.output_lines)
            if last_n:
                lines = lines[-last_n:]
            return "\n".join(lines)

    def send_signal(self, sig):
        """Send a signal to the terminal process."""
        if self.process_pid and self.running:
            try:
                os.kill(self.process_pid, sig)
            except ProcessLookupError:
                pass

    def terminate(self):
        """Terminate the terminal session."""
        self.running = False
        if self.process_pid:
            try:
                os.kill(self.process_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

    def is_running(self):
        """Check if the terminal session is still running."""
        return self.running


# ─── Terminal Manager ───────────────────────────────────────────────────────

class TerminalManager:
    """Manages multiple terminal sessions."""

    def __init__(self):
        self.sessions = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def create_session(self, shell=None, working_dir=None, env=None):
        """Create a new terminal session."""
        with self._lock:
            session_id = self._next_id
            self._next_id += 1

        session = TerminalSession(
            session_id=session_id,
            shell=shell,
            working_dir=working_dir,
            env=env,
        )

        if session.start():
            with self._lock:
                self.sessions[session_id] = session
            return session_id
        return None

    def get_session(self, session_id):
        """Get a terminal session by ID."""
        return self.sessions.get(session_id)

    def close_session(self, session_id):
        """Close and remove a terminal session."""
        with self._lock:
            session = self.sessions.pop(session_id, None)
        if session:
            session.terminate()

    def close_all(self):
        """Close all terminal sessions."""
        with self._lock:
            for session in self.sessions.values():
                session.terminate()
            self.sessions.clear()

    def list_sessions(self):
        """List all active session IDs."""
        return list(self.sessions.keys())


# Global terminal manager
terminal_manager = TerminalManager()


# ─── Blender Text Block Integration ─────────────────────────────────────────

def update_text_block(session_id):
    """Update the Blender text block with terminal output."""
    session = terminal_manager.get_session(session_id)
    if session is None:
        return

    text_name = f"{TERMINAL_TEXT_PREFIX}{session_id}"
    text_block = bpy.data.texts.get(text_name)

    if text_block is None:
        text_block = bpy.data.texts.new(text_name)

    output = session.get_output(last_n=MAX_OUTPUT_LINES)

    # Update text block content
    text_block.clear()
    text_block.write(output)


# ─── Operators ──────────────────────────────────────────────────────────────

class BLEDOs_OT_term_new(bpy.types.Operator):
    """Open a new terminal session"""
    bl_idname = "bledos.term_new"
    bl_label = "New Terminal"
    bl_options = {"REGISTER"}

    shell: bpy.props.StringProperty(
        name="Shell",
        default="",
    )
    working_dir: bpy.props.StringProperty(
        name="Working Directory",
        default="",
        subtype="DIR_PATH",
    )

    def execute(self, context):
        shell = self.shell if self.shell else None
        work_dir = self.working_dir if self.working_dir else None

        session_id = terminal_manager.create_session(
            shell=shell,
            working_dir=work_dir,
        )

        if session_id is None:
            self.report({"ERROR"}, "Failed to create terminal session")
            return {"CANCELLED"}

        # Create/update the text block
        update_text_block(session_id)

        # Switch to the Text Editor and open the text block
        text_name = f"{TERMINAL_TEXT_PREFIX}{session_id}"
        text_block = bpy.data.texts.get(text_name)

        if text_block:
            # Try to find a text editor area
            for area in context.screen.areas:
                if area.type == "TEXT_EDITOR":
                    for space in area.spaces:
                        if space.type == "TEXT_EDITOR":
                            space.text = text_block
                            break
                    break

        # Set active session
        context.scene.bledos_term_active_session = session_id

        self.report({"INFO"}, f"Terminal session {session_id} created")
        return {"FINISHED"}


class BLEDOs_OT_term_send(bpy.types.Operator):
    """Send a command to the active terminal"""
    bl_idname = "bledos.term_send"
    bl_label = "Send Command"
    bl_options = {"REGISTER"}

    command: bpy.props.StringProperty(
        name="Command",
    )

    def execute(self, context):
        session_id = context.scene.bledos_term_active_session
        session = terminal_manager.get_session(session_id)

        if session is None:
            self.report({"ERROR"}, "No active terminal session")
            return {"CANCELLED"}

        cmd = self.command + "\n"
        if session.write(cmd):
            # Update text block after a short delay
            bpy.app.timers.register(
                lambda: _timer_update(session_id),
                first_interval=0.1,
            )
            self.report({"INFO"}, f"Sent: {self.command}")
        else:
            self.report({"ERROR"}, "Failed to send command")
            return {"CANCELLED"}

        return {"FINISHED"}


def _timer_update(session_id):
    """Timer callback to update terminal text block."""
    update_text_block(session_id)
    return None  # One-shot timer


class BLEDOs_OT_term_close(bpy.types.Operator):
    """Close the active terminal session"""
    bl_idname = "bledos.term_close"
    bl_label = "Close Terminal"
    bl_options = {"REGISTER"}

    session_id: bpy.props.IntProperty(default=0)

    def execute(self, context):
        sid = self.session_id or context.scene.bledos_term_active_session
        if sid == 0:
            self.report({"WARNING"}, "No terminal session to close")
            return {"CANCELLED"}

        terminal_manager.close_session(sid)

        # Clean up text block
        text_name = f"{TERMINAL_TEXT_PREFIX}{sid}"
        text_block = bpy.data.texts.get(text_name)
        if text_block:
            bpy.data.texts.remove(text_block)

        # Switch active session
        remaining = terminal_manager.list_sessions()
        if remaining:
            context.scene.bledos_term_active_session = remaining[-1]
        else:
            context.scene.bledos_term_active_session = 0

        self.report({"INFO"}, f"Terminal session {sid} closed")
        return {"FINISHED"}


class BLEDOs_OT_term_refresh(bpy.types.Operator):
    """Refresh the terminal output display"""
    bl_idname = "bledos.term_refresh"
    bl_label = "Refresh Terminal"
    bl_options = {"REGISTER"}

    def execute(self, context):
        session_id = context.scene.bledos_term_active_session
        if session_id == 0:
            self.report({"WARNING"}, "No active terminal session")
            return {"CANCELLED"}

        update_text_block(session_id)
        self.report({"INFO"}, "Terminal refreshed")
        return {"FINISHED"}


class BLEDOs_OT_term_interrupt(bpy.types.Operator):
    """Send Ctrl+C to the active terminal"""
    bl_idname = "bledos.term_interrupt"
    bl_label = "Send Ctrl+C"
    bl_options = {"REGISTER"}

    def execute(self, context):
        session_id = context.scene.bledos_term_active_session
        session = terminal_manager.get_session(session_id)

        if session is None:
            self.report({"ERROR"}, "No active terminal session")
            return {"CANCELLED"}

        session.write("\x03")  # Ctrl+C
        self.report({"INFO"}, "Sent Ctrl+C")
        return {"FINISHED"}


class BLEDOs_OT_term_eof(bpy.types.Operator):
    """Send Ctrl+D (EOF) to the active terminal"""
    bl_idname = "bledos.term_eof"
    bl_label = "Send Ctrl+D"
    bl_options = {"REGISTER"}

    def execute(self, context):
        session_id = context.scene.bledos_term_active_session
        session = terminal_manager.get_session(session_id)

        if session is None:
            self.report({"ERROR"}, "No active terminal session")
            return {"CANCELLED"}

        session.write("\x04")  # Ctrl+D
        self.report({"INFO"}, "Sent Ctrl+D")
        return {"FINISHED"}


class BLEDOs_OT_term_switch(bpy.types.Operator):
    """Switch to a different terminal session"""
    bl_idname = "bledos.term_switch"
    bl_label = "Switch Terminal"
    bl_options = {"REGISTER"}

    session_id: bpy.props.IntProperty(default=1)

    def execute(self, context):
        if terminal_manager.get_session(self.session_id) is None:
            self.report({"ERROR"}, f"Session {self.session_id} not found")
            return {"CANCELLED"}

        context.scene.bledos_term_active_session = self.session_id
        update_text_block(self.session_id)

        # Switch text editor to this session
        text_name = f"{TERMINAL_TEXT_PREFIX}{self.session_id}"
        text_block = bpy.data.texts.get(text_name)
        if text_block:
            for area in context.screen.areas:
                if area.type == "TEXT_EDITOR":
                    for space in area.spaces:
                        if space.type == "TEXT_EDITOR":
                            space.text = text_block
                            break
                    break

        self.report({"INFO"}, f"Switched to session {self.session_id}")
        return {"FINISHED"}


class BLEDOs_OT_term_quick_command(bpy.types.Operator):
    """Quick execute a shell command and show output"""
    bl_idname = "bledos.term_quick_command"
    bl_label = "Quick Command"
    bl_options = {"REGISTER"}

    command: bpy.props.StringProperty(
        name="Command",
    )

    def execute(self, context):
        if not self.command:
            return {"CANCELLED"}

        # Use the active session if available, otherwise create a temporary one
        session_id = context.scene.bledos_term_active_session
        session = terminal_manager.get_session(session_id)

        if session and session.is_running():
            session.write(self.command + "\n")
            bpy.app.timers.register(
                lambda: _timer_update(session_id),
                first_interval=0.1,
            )
        else:
            # Create a new session and send the command
            new_id = terminal_manager.create_session()
            if new_id:
                context.scene.bledos_term_active_session = new_id
                new_session = terminal_manager.get_session(new_id)
                if new_session:
                    new_session.write(self.command + "\n")
                    bpy.app.timers.register(
                        lambda: _timer_update(new_id),
                        first_interval=0.1,
                    )

        self.report({"INFO"}, f"Executed: {self.command}")
        return {"FINISHED"}


# ─── Properties ─────────────────────────────────────────────────────────────

class BledOSTerminalProperties(bpy.types.PropertyGroup):
    """Properties for the BledOS terminal."""
    active_session: bpy.props.IntProperty(
        name="Active Session",
        default=0,
    )
    command_input: bpy.props.StringProperty(
        name="Command",
        default="",
    )


# ─── Panel ──────────────────────────────────────────────────────────────────

class BLEDOs_PT_terminal(bpy.types.Panel):
    """BledOS Terminal panel"""
    bl_label = "Terminal"
    bl_idname = "BLEDOs_PT_terminal"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "BledOS"

    def draw(self, context):
        layout = self.layout
        props = context.scene.bledos_term_props

        # New terminal
        col = layout.column()
        col.operator("bledos.term_new", text="New Terminal", icon="CONSOLE")
        col.operator("bledos.term_new", text="New Root Terminal", icon="CONSOLE").shell = "sudo -i"

        layout.separator()

        # Active session info
        session_id = props.active_session
        session = terminal_manager.get_session(session_id)

        if session:
            status_icon = "CHECKMARK" if session.is_running() else "X"
            col = layout.column()
            col.label(text=f"Session {session_id}", icon=status_icon)
            col.label(text=f"  Shell: {session.shell}")
            col.label(text=f"  PID: {session.process_pid if session.is_running() else 'exited'}")

            # Terminal controls
            row = layout.row(align=True)
            row.operator("bledos.term_interrupt", text="", icon="X")
            row.operator("bledos.term_eof", text="", icon="TRIA_DOWN")
            row.operator("bledos.term_refresh", text="", icon="FILE_REFRESH")
            row.operator("bledos.term_close", text="", icon="CANCEL")
        else:
            col = layout.column()
            col.label(text="No active terminal", icon="CONSOLE")

        layout.separator()

        # Session list
        sessions = terminal_manager.list_sessions()
        if len(sessions) > 1:
            col = layout.column()
            col.label(text="Sessions:", icon="LINENUMBERS_ON")
            for sid in sessions:
                s = terminal_manager.get_session(sid)
                if s:
                    icon = "CONSOLE" if s.is_running() else "X"
                    row = col.row()
                    row.label(text=f"  #{sid}", icon=icon)
                    op = row.operator("bledos.term_switch", text="Switch")
                    op.session_id = sid

        layout.separator()

        # Quick command
        col = layout.column()
        col.label(text="Quick Command:", icon="RIGHTARROW")
        col.prop(props, "command_input", text="")
        if props.command_input:
            op = col.operator("bledos.term_quick_command", text="Run", icon="PLAY")
            op.command = props.command_input


# ─── 3D Viewport Terminal Panel ─────────────────────────────────────────────

class BLEDOs_PT_terminal_3d(bpy.types.Panel):
    """BledOS Terminal controls in the 3D viewport"""
    bl_label = "Terminal"
    bl_idname = "BLEDOs_PT_terminal_3d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BledOS"

    def draw(self, context):
        layout = self.layout
        props = context.scene.bledos_term_props

        # Quick launch
        col = layout.column()
        col.operator("bledos.term_new", text="New Terminal", icon="CONSOLE")

        # Active session
        session_id = props.active_session
        session = terminal_manager.get_session(session_id)

        if session and session.is_running():
            col.label(text=f"Session #{session_id} running", icon="CHECKMARK")
            col.prop(props, "command_input", text="")
            if props.command_input:
                op = col.operator("bledos.term_quick_command", text="Run", icon="PLAY")
                op.command = props.command_input
            row = col.row(align=True)
            row.operator("bledos.term_interrupt", text="Ctrl+C")
            row.operator("bledos.term_refresh", text="Refresh")


# ─── Registration ───────────────────────────────────────────────────────────

classes = (
    BledOSTerminalProperties,
    BLEDOs_OT_term_new,
    BLEDOs_OT_term_send,
    BLEDOs_OT_term_close,
    BLEDOs_OT_term_refresh,
    BLEDOs_OT_term_interrupt,
    BLEDOs_OT_term_eof,
    BLEDOs_OT_term_switch,
    BLEDOs_OT_term_quick_command,
    BLEDOs_PT_terminal,
    BLEDOs_PT_terminal_3d,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bledos_term_props = bpy.props.PointerProperty(
        type=BledOSTerminalProperties
    )
    bpy.types.Scene.bledos_term_active_session = bpy.props.IntProperty(default=0)
    print("[BledOS] Terminal add-on registered")


def unregister():
    # Close all sessions
    terminal_manager.close_all()

    del bpy.types.Scene.bledos_term_props
    del bpy.types.Scene.bledos_term_active_session

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[BledOS] Terminal add-on unregistered")