#!/usr/bin/python3
"""
Yafti GTK - A simple GTK GUI for running scripts from yafti.yml
"""

import os
import subprocess
import sys
import ctypes
import ctypes.util
import time
import threading
import argparse
import concurrent.futures

import gi
import yaml

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import GLib, Gtk

# Constants
APP_ID = 'io.github.ublue_os.yafti_gtk'
APP_TITLE = 'Bazzite Portal'
DEFAULT_WINDOW_WIDTH = 815
DEFAULT_WINDOW_HEIGHT = 600
STATUS_TIMEOUT_SECONDS = 3
ACTION_DIALOG_WIDTH = 420
AUTOSTART_DIR = os.path.expanduser('~/.config/autostart')
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, 'bazzite-portal.desktop')
AUTOSTART_CONTENT = """\
[Desktop Entry]
Name=Bazzite Portal
Comment=Helps you setup Bazzite
Exec=yafti_gtk.py /usr/share/yafti/yafti.yml
Icon=io.github.ublue_os.yafti_gtk
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
"""
DEFAULT_ACCENT = "#a47bea"


def controller_button_glyph(command, labels=None):
    """Use SDL's face-button labels, with Xbox glyphs for unknown devices."""
    labels = labels or {}
    glyphs = {1: 'Ⓐ', 2: 'Ⓑ', 3: 'Ⓧ', 4: 'Ⓨ', 5: '✕', 6: '○', 7: '▢', 8: '△'}
    defaults = {'confirm': 'Ⓐ', 'back': 'Ⓑ', 'focus_search': 'Ⓧ', 'toggle_startup': 'Ⓨ'}
    return glyphs.get(labels.get(command), defaults[command])


def controller_legend_text(labels=None):
    select = controller_button_glyph('confirm', labels)
    back = controller_button_glyph('back', labels)
    return f'↑↓ Move · {select} Select · {back} Back · 〔LB〕/〔RB〕 Tabs'


class ControllerInput:
    """Translate SDL's positional controls into commands, without GTK dependencies."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.armed = False
        self.previous = set()
        self.direction = None
        self.repeat_at = 0

    def update(self, buttons, x, y, now):
        direction = None
        if 'up' in buttons:
            direction = 'up'
        elif 'down' in buttons:
            direction = 'down'
        elif abs(y) >= 0.35 and abs(y) >= abs(x):
            direction = 'down' if y > 0 else 'up'
        if not self.armed:
            self.armed = not buttons and direction is None
            return []
        commands = []
        if direction != self.direction:
            if direction:
                commands.append(direction)
                self.repeat_at = now + 0.350
        elif direction and now >= self.repeat_at:
            commands.append(direction)
            self.repeat_at = now + 0.100
        self.direction = direction
        for command in ('back', 'confirm', 'focus_search', 'toggle_startup', 'previous_tab', 'next_tab'):
            if command in buttons and command not in self.previous:
                commands.append(command)
        self.previous = set(buttons)
        return commands


class SDLGamepad:
    """Small, typed SDL3 adapter. SDL owns input only; GTK owns all windows."""

    BUTTONS = {'confirm': 0, 'back': 1, 'focus_search': 2, 'toggle_startup': 3, 'previous_tab': 9, 'next_tab': 10,
               'up': 11, 'down': 12, 'left': 13, 'right': 14}
    INIT_GAMEPAD = 0x00002000

    def __init__(self):
        library = ctypes.util.find_library('SDL3') or 'libSDL3.so.0'
        self.sdl = ctypes.CDLL(library)
        self.gamepads = {}
        self.connection_serial = 0
        self.button_labels = {}
        self.initialized = False
        signatures = {
            'SDL_SetHint': (ctypes.c_bool, [ctypes.c_char_p, ctypes.c_char_p]),
            'SDL_InitSubSystem': (ctypes.c_bool, [ctypes.c_uint32]),
            'SDL_QuitSubSystem': (None, [ctypes.c_uint32]),
            'SDL_GetError': (ctypes.c_char_p, []),
            'SDL_UpdateGamepads': (None, []),
            'SDL_PumpEvents': (None, []),
            'SDL_FlushEvents': (None, [ctypes.c_uint32, ctypes.c_uint32]),
            'SDL_SetGamepadEventsEnabled': (None, [ctypes.c_bool]),
            'SDL_SetJoystickEventsEnabled': (None, [ctypes.c_bool]),
            'SDL_GetGamepads': (ctypes.POINTER(ctypes.c_uint32), [ctypes.POINTER(ctypes.c_int)]),
            'SDL_free': (None, [ctypes.c_void_p]),
            'SDL_OpenGamepad': (ctypes.c_void_p, [ctypes.c_uint32]),
            'SDL_CloseGamepad': (None, [ctypes.c_void_p]),
            'SDL_GamepadConnected': (ctypes.c_bool, [ctypes.c_void_p]),
            'SDL_GetGamepadButton': (ctypes.c_bool, [ctypes.c_void_p, ctypes.c_int]),
            'SDL_GetGamepadButtonLabel': (ctypes.c_int, [ctypes.c_void_p, ctypes.c_int]),
            'SDL_GetGamepadAxis': (ctypes.c_int16, [ctypes.c_void_p, ctypes.c_int]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.sdl, name)
            function.restype, function.argtypes = result, arguments
        # SDL has no window to track focus. The GTK dispatcher gates input instead.
        self.sdl.SDL_SetHint(b'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', b'1')
        if not self.sdl.SDL_InitSubSystem(self.INIT_GAMEPAD):
            error = self.sdl.SDL_GetError()
            self.sdl.SDL_QuitSubSystem(self.INIT_GAMEPAD)
            raise RuntimeError(error.decode('utf-8', errors='replace') if error else 'SDL initialization failed')
        self.initialized = True
        self.sdl.SDL_SetGamepadEventsEnabled(False)
        self.sdl.SDL_SetJoystickEventsEnabled(False)

    def sample(self):
        # Linux udev hot-plug notifications are processed by the SDL event pump,
        # even when button/axis events are disabled and we read state directly.
        self.sdl.SDL_PumpEvents()
        self.sdl.SDL_UpdateGamepads()
        self.sdl.SDL_FlushEvents(0, 0xFFFF)
        for device, (handle, _serial, _labels) in list(self.gamepads.items()):
            if not self.sdl.SDL_GamepadConnected(handle):
                self.sdl.SDL_CloseGamepad(handle)
                del self.gamepads[device]
        count = ctypes.c_int()
        ids = self.sdl.SDL_GetGamepads(ctypes.byref(count))
        try:
            if ids:
                for index in range(count.value):
                    device = ids[index]
                    if device in self.gamepads:
                        continue
                    handle = self.sdl.SDL_OpenGamepad(device)
                    if handle:
                        self.connection_serial += 1
                        labels = {command: self.sdl.SDL_GetGamepadButtonLabel(handle, self.BUTTONS[command])
                                  for command in ('confirm', 'back', 'focus_search', 'toggle_startup')}
                        self.gamepads[device] = (handle, self.connection_serial, labels)
        finally:
            if ids:
                self.sdl.SDL_free(ids)
        samples = []
        for handle, serial, labels in self.gamepads.values():
            buttons = {name for name, button in self.BUTTONS.items()
                       if self.sdl.SDL_GetGamepadButton(handle, button)}
            x = self.sdl.SDL_GetGamepadAxis(handle, 0) / 32768.0
            y = self.sdl.SDL_GetGamepadAxis(handle, 1) / 32768.0
            samples.append((serial, buttons, x, y, labels))
        return samples

    def close(self):
        for handle, _serial, _labels in self.gamepads.values():
            self.sdl.SDL_CloseGamepad(handle)
        self.gamepads.clear()
        if self.initialized:
            self.sdl.SDL_QuitSubSystem(self.INIT_GAMEPAD)
            self.initialized = False


class ControllerDriver:
    """GLib timer lifecycle and focus gating, also usable with mocked backends."""

    def __init__(self, backend, context, dispatch, scheduler=GLib):
        self.backend, self.context, self.dispatch = backend, context, dispatch
        self.scheduler = scheduler
        self.inputs = {}
        self.last_context = None
        self.source = scheduler.timeout_add(16, self.poll)

    def reset_inputs(self):
        for state in self.inputs.values():
            state.reset()

    def poll(self):
        try:
            samples = self.backend.sample()
            context = self.context()
            connected = {sample[0] for sample in samples}
            self.inputs = {serial: state for serial, state in self.inputs.items() if serial in connected}
            if context != self.last_context:
                self.reset_inputs()
                self.last_context = context
            if not context:
                self.reset_inputs()
                return True
            pending = []
            now = time.monotonic()
            for serial, buttons, x, y, labels in samples:
                state = self.inputs.get(serial)
                if state is None:
                    state = self.inputs[serial] = ControllerInput()
                pending.extend((command, labels) for command in state.update(buttons, x, y, now))
            for command, labels in pending:
                self.backend.button_labels = labels
                self.dispatch(command)
                # Activation can open a modal or launch a terminal. Discard the
                # rest of this sample rather than dispatching into a new context.
                if command in ('confirm', 'back', 'focus_search', 'toggle_startup') or self.context() != context:
                    self.reset_inputs()
                    break
            return True
        except Exception as error:
            print(f'Warning: Controller support disabled: {error}', file=sys.stderr)
            self.source = None
            self.backend.close()
            return False

    def close(self):
        if self.source is not None:
            self.scheduler.source_remove(self.source)
            self.source = None
        self.backend.close()
        self.inputs.clear()


def set_widget_margins(widget, top=10, bottom=10, start=10, end=10):
    """Apply consistent margins to a widget."""
    widget.set_margin_top(top)
    widget.set_margin_bottom(bottom)
    widget.set_margin_start(start)
    widget.set_margin_end(end)


def clear_container(container):
    """Remove all children from a container widget."""
    if hasattr(container, 'remove'):
        # For regular containers (Box, etc.)
        while container.get_first_child() is not None:
            container.remove(container.get_first_child())
    elif hasattr(container, 'set_child'):
        # For dialogs and single-child containers
        container.set_child(None)


def show_error_dialog(parent, title, message):
    """Display an error dialog with the given title and message."""
    dialog = Gtk.Dialog(title=title, transient_for=parent.controller_window(), modal=True)
    dialog.set_destroy_with_parent(True)
    dialog.set_default_size(ACTION_DIALOG_WIDTH, -1)
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    set_widget_margins(root, 16, 16, 16, 16)
    label = Gtk.Label(label=message, wrap=True, selectable=True)
    label.set_max_width_chars(60)
    root.append(label)
    button = Gtk.Button(label="OK")
    button.connect('clicked', lambda _button: parent.close_controller_dialog(dialog))
    root.append(button)
    dialog.set_child(root)
    parent.register_controller_dialog(dialog, [button])
    dialog.present()
    button.grab_focus()


def initialize_gtk():
    """Initialize GTK and application metadata, then load Adwaita depending on DE."""
    GLib.set_prgname(APP_ID)
    Gtk.init()
    
    current_desktop = os.environ.get("XDG_CURRENT_DESKTOP","").upper()
    if "KDE" not in current_desktop:
        from gi.repository import Adw
        if Gtk.Settings.get_default().get_property('gtk-application-prefer-dark-theme'):
            Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', False)
        Adw.init()
    try:
        Gtk.Window.set_default_icon_name(APP_ID)
    except Exception as e:
        print(f"Warning: Could not set app icon: {e}")


def build_terminal_command(script):
    """Return the default terminal launcher command."""
    return [
        "xdg-terminal-exec",
        f"--app-id={APP_ID}",
        f"--title={APP_TITLE}",
        "--",
        "bash",
        "--noprofile",
        "--norc",
        "-lc",
        script,
    ]


def build_headless_command(script):
    """Return the non-interactive command used for status checks."""
    return [
        "bash",
        "--noprofile",
        "--norc",
        "-lc",
        script,
    ]


def escape_markup(text):
    """Escape text before using it in a GTK markup label."""
    return GLib.markup_escape_text(text or "")


class YaftiGTK(Gtk.Window):
    def __init__(self, config_file='yafti.yml'):
        super().__init__(title=APP_TITLE)
        self.set_default_size(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.active_dialog_state = None
        self.controller_dialogs = []
        self.controller_driver = None
        self.controller_focus = None
        self.controller_used = False
        self.action_widgets = {}  # action_id -> (button)
        self.action_status_widgets = {}

        # Load YAML configuration
        self.config = self.load_config(config_file)
        self.screens = self.config.get('screens', [])
        self.actions_index = self._build_actions_index()

        # Create main container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(vbox)

        # Search bar at the top
        search_entry = Gtk.SearchEntry()
        self.search_entry = search_entry
        search_entry.set_placeholder_text(" Search Apps and Actions")
        set_widget_margins(search_entry, 10, 10, 10, 10)
        search_entry.connect("search-changed", self.on_search_changed)
        vbox.append(search_entry)

        # Container to hold the switcher and pages together so they disappear during search
        tabs_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Stack for screen pages
        self.screen_stack = Gtk.Stack()
        self.screen_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.screen_stack.set_transition_duration(150)
        self.screen_stack.set_vexpand(True)
        self.screen_stack.set_hexpand(True)

        # Tab switcher
        self.tab_switcher = Gtk.StackSwitcher()
        self.tab_switcher.set_stack(self.screen_stack)
        set_widget_margins(self.tab_switcher, 10, 10, 10, 10)

        # Assemble into container
        tabs_container.append(self.tab_switcher)
        tabs_container.append(self.screen_stack)

        # Map page actions for updating
        self.page_actions_map = {}
        # Add tabs for each screen from YAML
        for screen in self.screens:
            page = self.create_screen_page(screen)
            label = screen.get('title', 'Tab')
            self.screen_stack.add_titled(page, label, label)
            self.page_actions_map[label] = screen.get('actions', [])

        # Stack to switch between container and search results
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.set_transition_duration(150)

        # Map our tabs view structure to the view name index
        self.content_stack.add_named(tabs_container, "tabs")

        # Search results page
        search_scrolled = Gtk.ScrolledWindow()
        search_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        results_box.set_vexpand(True)
        set_widget_margins(results_box, 10, 10, 10, 10)
        self.search_results_box = results_box
        self.search_targets = []
        search_scrolled.set_child(results_box)
        self.content_stack.add_named(search_scrolled, "search")

        # Start with tabs visible
        self.content_stack.set_visible_child_name("tabs")

        vbox.append(self.content_stack)

        # Bottom bar with autostart toggle
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        set_widget_margins(bottom_bar, top=6, bottom=4, start=6, end=6)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bottom_bar.append(spacer)

        self.controller_legend = Gtk.Label(label=controller_legend_text())
        self.controller_legend.add_css_class('dim-label')
        self.controller_legend.set_wrap(True)
        self.controller_legend.set_visible(False)
        bottom_bar.prepend(self.controller_legend)

        autostart_label = Gtk.Label(label="Launch at startup")
        autostart_label.add_css_class('dim-label')
        bottom_bar.append(autostart_label)

        self.autostart_switch = Gtk.Switch()
        self.autostart_switch.set_active(self._autostart_enabled())
        self.autostart_switch.set_valign(Gtk.Align.CENTER)
        self.autostart_switch.connect("notify::active", self._on_autostart_toggled)
        bottom_bar.append(self.autostart_switch)

        self.startup_controller_glyph = Gtk.Label(label=controller_button_glyph('toggle_startup'))
        self.startup_controller_glyph.set_visible(False)
        self.startup_controller_glyph.set_tooltip_text('Toggle Launch at startup')
        bottom_bar.append(self.startup_controller_glyph)

        vbox.append(bottom_bar)
        # Load CSS for highlighting
        GLib.idle_add(self._load_css)

        self.connect("notify::is-active", self.on_window_active_changed)
        focus_controller = Gtk.EventControllerFocus.new()
        focus_controller.connect("enter", self.on_window_focus_in)
        self.add_controller(focus_controller)
        self.current_page_name = None
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.screen_stack.connect("notify::visible-child", self.on_page_changed)
        self.connect("destroy", self.on_destroy)
        self.connect("close-request", self.on_controller_close_request)
        self.connect('notify::focus-widget', self.on_controller_focus_changed)
        GLib.idle_add(self.start_controller)

    def start_controller(self):
        backend = None
        try:
            backend = SDLGamepad()
            self.controller_driver = ControllerDriver(
                backend, self.controller_context, self.dispatch_controller)
        except Exception as error:
            if backend:
                backend.close()
            print(f'Warning: Controller support disabled: {error}', file=sys.stderr)
        return False

    def on_controller_close_request(self, *_args):
        if self.controller_driver:
            self.controller_driver.close()
            self.controller_driver = None
        for record in list(reversed(self.controller_dialogs)):
            self.close_controller_dialog(record['dialog'])
        return False

    def register_controller_dialog(self, dialog, targets):
        record = {'dialog': dialog, 'targets': targets, 'return_focus': self.controller_window().get_focus()}
        self.controller_dialogs.append(record)
        dialog.connect('destroy', self.on_controller_dialog_destroy, record)
        dialog.connect('close-request', self.on_controller_dialog_close_request, record)
        dialog.connect('notify::focus-widget', self.on_controller_focus_changed)
        dialog.connect('notify::is-active', self.on_controller_context_changed)
        self.on_controller_context_changed()

    def on_controller_dialog_destroy(self, _dialog, record):
        if record not in self.controller_dialogs:
            return
        state = self.active_dialog_state
        if state and state['dialog'] == record['dialog']:
            self.on_dialog_destroy(record['dialog'], state)
        self.controller_dialogs.remove(record)
        self.on_controller_context_changed()
        target = record['return_focus']
        if target and target.get_mapped():
            target.grab_focus()
        self.on_controller_focus_changed()

    def on_controller_dialog_close_request(self, dialog, record):
        self.on_controller_dialog_destroy(dialog, record)
        return False

    def close_controller_dialog(self, dialog):
        # GTK4 may defer the destroy signal while Python still holds references.
        # Mark status requests closed before destroying the window, so a pending
        # result cannot present a destroyed dialog again.
        for record in list(self.controller_dialogs):
            if record['dialog'] == dialog:
                self.on_controller_dialog_destroy(dialog, record)
                break
        dialog.destroy()

    def controller_window(self):
        return self.controller_dialogs[-1]['dialog'] if self.controller_dialogs else self

    def controller_context(self):
        window = self.controller_window()
        return window if window.get_property('is-active') else None

    def on_controller_context_changed(self, *_args):
        if self.controller_driver:
            self.controller_driver.reset_inputs()

    def controller_targets(self):
        if self.controller_dialogs:
            targets = self.controller_dialogs[-1]['targets']
        else:
            if self.content_stack.get_visible_child_name() == 'search':
                actions = self.search_targets
            else:
                page = self.screen_stack.get_visible_child()
                actions = getattr(page, 'controller_targets', [])
            targets = actions
        return [target for target in targets if target.get_mapped() and target.is_sensitive()]

    def on_controller_focus_changed(self, *_args):
        if self.controller_focus:
            self.controller_focus.remove_css_class('controller-focus')
        self.controller_focus = None
        if not self.controller_used:
            return
        focused = self.controller_window().get_focus()
        targets = self.controller_targets()
        if not self.controller_dialogs:
            targets = [self.search_entry, *targets]
        for target in targets:
            if focused == target or (focused and focused.is_ancestor(target)):
                target.add_css_class('controller-focus')
                self.controller_focus = target
                break

    def focus_controller_target(self, target):
        scrolled = target.get_ancestor(Gtk.ScrolledWindow)
        if scrolled:
            viewport = scrolled.get_child()
            if isinstance(viewport, Gtk.Viewport):
                # Let GTK follow focus in its own coordinate space. Manual
                # adjustment math against the viewport double-counts scrolling
                # and competes with GTK's focus-scroll animation.
                viewport.set_scroll_to_focus(True)
        target.grab_focus()
        self.on_controller_focus_changed()

    def dispatch_controller(self, command):
        self.controller_used = True
        labels = self.controller_driver.backend.button_labels if self.controller_driver else None
        self.controller_legend.set_label(controller_legend_text(labels))
        self.controller_legend.set_visible(True)
        search_glyph = controller_button_glyph('focus_search', labels)
        self.search_entry.set_placeholder_text(f'{search_glyph} Search Apps and Actions')
        self.startup_controller_glyph.set_label(controller_button_glyph('toggle_startup', labels))
        self.startup_controller_glyph.set_visible(True)
        window = self.controller_window()
        if command == 'focus_search':
            if not self.controller_dialogs:
                self.focus_controller_target(self.search_entry)
                GLib.idle_add(self.request_steam_keyboard)
            return
        if command == 'toggle_startup':
            if not self.controller_dialogs and self.autostart_switch.is_sensitive():
                self.autostart_switch.set_active(not self.autostart_switch.get_active())
            return
        if command == 'back':
            if self.controller_dialogs:
                self.close_controller_dialog(window)
            elif self.search_entry.get_text():
                self.search_entry.set_text('')
                # SearchEntry normally delays search-changed; rebuild now.
                self.on_search_changed(self.search_entry)
            return
        if command in ('previous_tab', 'next_tab'):
            if self.controller_dialogs or self.content_stack.get_visible_child_name() == 'search':
                return
            pages = self.screen_stack.get_pages()
            names = [pages.get_item(index).get_name() for index in range(pages.get_n_items())]
            if names:
                current = self.screen_stack.get_visible_child_name()
                index = names.index(current) if current in names else 0
                step = -1 if command == 'previous_tab' else 1
                self.screen_stack.set_visible_child_name(names[(index + step) % len(names)])
                targets = self.controller_targets()
                if targets:
                    self.focus_controller_target(targets[0])
            return
        targets = self.controller_targets()
        if not targets:
            return
        focused = window.get_focus()
        selected = next((target for target in targets
                         if focused == target or (focused and focused.is_ancestor(target))), None)
        if command == 'confirm':
            if selected is None:
                self.focus_controller_target(targets[0])
            else:
                self.on_controller_focus_changed()
                selected.activate()
            return
        if command in ('up', 'down'):
            if (command == 'up' and not self.controller_dialogs
                    and (focused == self.search_entry
                         or (focused and focused.is_ancestor(self.search_entry)))):
                return
            step = -1 if command == 'up' else 1
            index = targets.index(selected) if selected else (-1 if step > 0 else len(targets))
            index = max(0, min(len(targets) - 1, index + step))
            self.focus_controller_target(targets[index])

    def request_steam_keyboard(self):
        """Best-effort Steam URI request after controller focus reaches search."""
        desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
        if not ('gamescope' in desktop or os.environ.get('SteamGamepadUI') == '1'):
            return False
        if self.controller_dialogs or not self.search_entry.get_mapped():
            return False
        focus = self.get_focus()
        if not (focus == self.search_entry or (focus and focus.is_ancestor(self.search_entry))):
            return False
        try:
            subprocess.Popen(['steam', '-ifrunning', 'steam://open/keyboard'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            print(f'Warning: Could not request Steam keyboard: {error}', file=sys.stderr)
        return False

    def on_page_changed(self, stack, _pspec):
        """Triggered to refresh actions if the visible page changes."""
        visible_name = stack.get_visible_child_name()
        if visible_name and visible_name != self.current_page_name:
            self.current_page_name = visible_name
        self.refresh_current_page_actions()

    def _load_css(self):
        """Loads CSS to highlight the selected action."""
        def _get_system_accent_color():
            """Fetches the system accent color via XDG Portal."""
            import re
            try:
                out = subprocess.check_output([
                    "gdbus", "call", "-e",
                    "-d", "org.freedesktop.portal.Desktop",
                    "-o", "/org/freedesktop/portal/desktop",
                    "-m", "org.freedesktop.portal.Settings.Read",
                    "'org.freedesktop.appearance'", "'accent-color'"
                ], text=True, stderr=subprocess.DEVNULL)

                r, g, b = map(float, re.findall(r"\d+\.\d+", out)[:3])
                return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
            except Exception:
                return DEFAULT_ACCENT

        accent = _get_system_accent_color()
        css = f"""
        @define-color accent {accent};
        @define-color accent_bg alpha(@accent, 0.3);

        .controller-focus {{
            outline: 3px solid @accent;
            outline-offset: -3px;
        }}

        slider,
        .slider {{
            min-height: 8px;
            min-width: 8px;
        }}

        @keyframes flash-animation {{
            0% {{
                border-color: @accent;
            }}
            50% {{
                background-color: @accent_bg;
                border-color: @accent;
            }}
            100% {{
                border-color: @accent;
            }}
        }}

        .highlighted-action {{
            border: 2px solid @accent;
            animation: flash-animation 1000ms ease-in-out 2;
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _autostart_enabled(self):
        """Check if the autostart desktop file exists."""
        return os.path.isfile(AUTOSTART_FILE)

    def _on_autostart_toggled(self, switch, _param):
        """Write or remove the autostart desktop file based on switch state."""
        if switch.get_active():
            try:
                os.makedirs(AUTOSTART_DIR, exist_ok=True)
                with open(AUTOSTART_FILE, 'w') as f:
                    f.write(AUTOSTART_CONTENT)
            except Exception as e:
                show_error_dialog(self, "Autostart error", f"Could not create autostart entry:\n{e}")
                switch.set_active(False)
        else:
            try:
                if os.path.isfile(AUTOSTART_FILE):
                    os.remove(AUTOSTART_FILE)
            except Exception as e:
                show_error_dialog(self, "Autostart error", f"Could not remove autostart entry:\n{e}")
                switch.set_active(True)

    def load_config(self, config_file):
        """Load and parse the YAML configuration file."""
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            show_error_dialog(
                self,
                "Configuration file not found",
                f"Could not find {config_file} in the current directory."
            )
            sys.exit(1)
        except yaml.YAMLError as e:
            show_error_dialog(self, "YAML parsing error", str(e))
            sys.exit(1)

    def create_screen_page(self, screen):
        """Create a page for a screen with all its actions."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        set_widget_margins(page_box, 10, 10, 10, 10)

        scrolled.controller_targets = []
        for action in screen.get('actions', []):
            item = self.create_action_item(action)
            page_box.append(item)
            scrolled.controller_targets.append(item.get_child())

        scrolled.set_child(page_box)
        return scrolled

    def create_action_item(self, action):
        """Create a clickable action item."""
        button = Gtk.Button()
        button.set_hexpand(True)
        button.set_halign(Gtk.Align.FILL)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        set_widget_margins(button_box, 8, 8, 8, 8)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)

        title_label = Gtk.Label()
        title_label.set_markup(f"<b>{escape_markup(action.get('title', 'Action'))}</b>")
        title_label.set_xalign(0)
        text_box.append(title_label)

        if action.get('description'):
            desc_label = Gtk.Label(label=action['description'])
            desc_label.set_xalign(0)
            desc_label.set_wrap(True)
            desc_label.set_max_width_chars(120)
            desc_label.add_css_class('dim-label')
            text_box.append(desc_label)

        button_box.append(text_box)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_box.set_valign(Gtk.Align.CENTER)
        status_box.set_size_request(80, -1)

        # Start with a default "loading" or "pending" emoji
        status_label = Gtk.Label(label="⏳ Checking...")
        status_label.add_css_class('dim-label')
        status_label.set_xalign(0)

        status_box.append(status_label)
        button_box.append(status_box)

        button.set_child(button_box)
        button.connect("clicked", self.on_action_clicked, action)

        frame = Gtk.Frame()
        frame.set_child(button)

        # Store references
        action_id = action.get('id')
        if action_id:
            self.action_widgets[action_id] = button
            if action.get('status_script'):
                self.action_status_widgets[action_id] = status_label
            else:
                status_box.set_visible(False)

        return frame

    def _build_actions_index(self):
        """Flatten actions for search lookup."""
        index = []
        for screen in self.screens or []:
            for action in screen.get('actions', []):
                index.append(action)
        return index

    def get_action_options(self, action):
        """Return explicit modal options from the config."""
        options = action.get('options')
        if isinstance(options, list) and options:
            return options
        return []

    def action_uses_modal(self, action):
        """Return True when the action should open the management modal."""
        if self.get_action_options(action):
            return True
        return bool((action.get('status_script') or "").strip())

    def on_search_changed(self, entry):
        previous_focus = self.controller_window().get_focus()
        focus_in_results = previous_focus in self.search_targets
        self.search_targets = []
        query = entry.get_text().strip()
        if not query:
            clear_container(self.search_results_box)
            self.current_search_matches = []
            self.content_stack.set_visible_child_name("tabs")
            if focus_in_results:
                self.search_entry.grab_focus()
            self.on_controller_focus_changed()
            return

        lowered = query.lower()
        matches = []
        for action in self.actions_index:
            title = action.get('title', '')
            desc = action.get('description', '')
            if lowered in title.lower() or lowered in desc.lower():
                matches.append(action)

        self.current_search_matches = matches
        clear_container(self.search_results_box)

        header = Gtk.Label()
        header.set_markup("<b>Search results</b>")
        header.set_xalign(0)
        self.search_results_box.append(header)

        if matches:
            for action in matches:
                item = self.create_action_item(action)
                self.search_results_box.append(item)
                self.search_targets.append(item.get_child())
        else:
            empty = Gtk.Label(label="No matches found")
            empty.set_xalign(0)
            self.search_results_box.append(empty)

        self.search_results_box.set_visible(True)
        self.content_stack.set_visible_child_name("search")
        if focus_in_results:
            (self.search_targets[0] if self.search_targets else self.search_entry).grab_focus()
        self.on_controller_focus_changed()
        self.refresh_current_page_actions()

    def on_action_clicked(self, _button, action):
        """Open a management modal or run the action directly."""
        if not self.action_uses_modal(action):
            script = (action.get('script') or "").strip()
            if not script:
                return

            error_message = self.launch_terminal(script)
            if isinstance(error_message, subprocess.Popen):
                return

            show_error_dialog(
                self,
                "No terminal available",
                f"{error_message}\n\nCould not open a terminal automatically.\nYou can also run the following command manually:\n\n{script}"
            )
            return

        dialog = Gtk.Dialog(title=action.get('title', 'Action'), transient_for=self)
        dialog.set_modal(True)
        dialog.set_destroy_with_parent(True)
        dialog.set_default_size(ACTION_DIALOG_WIDTH, -1)
        dialog.set_resizable(False)

        state = {
            'action': action,
            'dialog': dialog,
            'dirty': False,
            'loading': False,
            'closed': False,
            'request_id': 0,
            'status_token': None,
            'status_timed_out': False,
        }
        self.active_dialog_state = state
        self.register_controller_dialog(dialog, [])

        dialog.connect("destroy", self.on_dialog_destroy, state)
        dialog.connect("notify::is-active", self.on_dialog_active_changed, state)
        focus_controller = Gtk.EventControllerFocus.new()
        focus_controller.connect("enter", self.on_dialog_focus_in, state)
        dialog.add_controller(focus_controller)

        if (action.get('status_script') or "").strip():
            self.refresh_action_dialog(state)
        else:
            self.build_action_dialog_content(state, None)

    def on_dialog_destroy(self, _dialog, state):
        """Clear the active dialog reference when the modal closes."""
        state['closed'] = True
        if self.active_dialog_state is state:
            self.active_dialog_state = None

    def on_window_active_changed(self, window, _pspec):
        """Refresh the active dialog when the portal window becomes active."""
        self.on_controller_context_changed()
        if window.get_property("is-active"):
            GLib.idle_add(self.refresh_active_dialog_if_needed)

    def on_dialog_active_changed(self, dialog, _pspec, state):
        """Refresh the dialog when it becomes active again."""
        if dialog.get_property("is-active"):
            self.refresh_dialog_if_needed(state)

    def on_window_focus_in(self, _controller):
        """Refresh the active dialog on focus return when needed."""
        GLib.idle_add(self.refresh_active_dialog_if_needed)
        return False

    def on_dialog_focus_in(self, _controller, state):
        """Refresh the focused dialog after a launched action when needed."""
        GLib.idle_add(self.refresh_dialog_if_needed, state)
        return False

    def refresh_active_dialog_if_needed(self):
        """Refresh the active dialog if a launched action may have changed status."""
        self.refresh_dialog_if_needed(self.active_dialog_state)

    def refresh_dialog_if_needed(self, state):
        """Refresh a dialog when its status is dirty."""
        if self.should_refresh_dialog(state):
            self.refresh_action_dialog(state, background_only=True)

    def should_refresh_dialog(self, state):
        """Return True when a dialog should refresh its status on focus return."""
        if not state or state.get('closed'):
            return False
        if self.active_dialog_state is not state:
            return False
        if state.get('loading'):
            return False
        return state.get('dirty', False)

    def refresh_action_dialog(self, state, background_only=False):
        """Show the loading state and rerun the dialog status check."""
        if not state or state.get('closed'):
            return

        action = state['action']
        status_script = (action.get('status_script') or "").strip()
        if not status_script:
            self.build_action_dialog_content(state, None)
            return

        state['dirty'] = False
        state['request_id'] += 1
        request_id = state['request_id']
        if not background_only:
            self.build_action_dialog_loading(state)

        thread = threading.Thread(
            target=self.run_status_check,
            args=(state, request_id, status_script, background_only),
            daemon=True,
        )
        thread.start()

    def build_action_dialog_loading(self, state):
        """Render the loading-only modal view."""
        dialog = state['dialog']
        clear_container(dialog)
        state['loading'] = True

        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        loading_box.set_halign(Gtk.Align.CENTER)
        loading_box.set_valign(Gtk.Align.CENTER)
        set_widget_margins(loading_box, 24, 24, 24, 24)

        spinner = Gtk.Spinner()
        spinner.start()
        loading_box.append(spinner)

        label = Gtk.Label(label="Loading...")
        loading_box.append(label)

        close_button = Gtk.Button(label="Close")
        close_button.connect('clicked', lambda _button: self.close_controller_dialog(dialog))
        loading_box.append(close_button)
        self.set_dialog_controller_targets(dialog, [close_button])

        dialog.set_child(loading_box)
        dialog.set_visible(True)
        close_button.grab_focus()

    def set_dialog_controller_targets(self, dialog, targets):
        for record in self.controller_dialogs:
            if record['dialog'] == dialog:
                record['targets'] = targets
                break
        self.on_controller_context_changed()

    def run_status_check(self, state, request_id, status_script, background_only=False):
        """Run the modal status check in the background."""
        status_token = "unknown"
        status_timed_out = False

        try:
            result = subprocess.run(
                build_headless_command(status_script),
                capture_output=True,
                text=True,
                timeout=STATUS_TIMEOUT_SECONDS,
                check=False,
            )

            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    token = line.strip()
                    if token:
                        status_token = token
                        break
        except subprocess.TimeoutExpired:
            status_timed_out = True
        except Exception:
            status_token = "unknown"

        GLib.idle_add(
            self.finish_status_check,
            state,
            request_id,
            status_token,
            status_timed_out,
            background_only,
        )

    def finish_status_check(self, state, request_id, status_token, status_timed_out, background_only=False):
        """Update the dialog once the status check completes."""
        if not state or state.get('closed'):
            return False
        if self.active_dialog_state is not state:
            return False
        if state.get('request_id') != request_id:
            return False

        if background_only and not state.get('loading'):
            self.update_dialog_highlights(state, status_token)
        else:
            self.build_action_dialog_content(state, status_token, status_timed_out)
        return False

    def update_dialog_highlights(self, state, status_token):
        """Updates button highlights in-place without rebuilding the dialog layout."""
        state['status_token'] = status_token
        for button, option in state.get('option_buttons', []):
            if self.option_is_highlighted(option, status_token):
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")

    def build_action_dialog_content(self, state, status_token, status_timed_out=False):
        """Render the full action dialog after status is known."""
        dialog = state['dialog']
        action = state['action']
        clear_container(dialog)

        state['loading'] = False
        state['status_token'] = status_token
        state['status_timed_out'] = status_timed_out

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        set_widget_margins(root, 16, 16, 16, 16)

        title_label = Gtk.Label()
        title_label.set_markup(f"<big><b>{escape_markup(action.get('title', 'Action'))}</b></big>")
        title_label.set_xalign(0)
        root.append(title_label)

        description = action.get('description')
        if description:
            desc_label = Gtk.Label(label=description)
            desc_label.set_xalign(0)
            desc_label.set_wrap(True)
            desc_label.add_css_class('dim-label')
            root.append(desc_label)

        if status_timed_out:
            status_label = Gtk.Label()
            status_label.set_markup(
                "<span foreground='red'><b>Status check timed out. You can still run the action.</b></span>"
            )
            status_label.set_xalign(0)
            status_label.set_wrap(True)
            root.append(status_label)

        actions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        active_button = None
        option_buttons = []
        for option in self.get_action_options(action):
            option_button = Gtk.Button(label=option.get('label', 'Run'))
            option_button.set_hexpand(True)
            option_button.set_halign(Gtk.Align.FILL)

            if self.option_is_highlighted(option, status_token):
                option_button.add_css_class("suggested-action")
                active_button = option_button

            option_button.connect("clicked", self.on_option_clicked, state, option)
            actions_box.append(option_button)
            option_buttons.append((option_button, option))

        root.append(actions_box)

        close_button = Gtk.Button(label="Close")
        close_button.connect("clicked", lambda _button: self.close_controller_dialog(dialog))
        root.append(close_button)
        state['option_buttons'] = option_buttons
        self.set_dialog_controller_targets(dialog, [button for button, _option in option_buttons] + [close_button])

        dialog.set_child(root)
        dialog.set_visible(True)

        dialog.set_focus(active_button or (option_buttons[0][0] if option_buttons else close_button))
        self.on_controller_focus_changed()

    def option_is_highlighted(self, option, status_token):
        """Return True when the option ID matches the current status token."""
        if not status_token or status_token == "unknown":
            return False

        option_id = (option.get('id') or "").strip().lower()
        current_status = status_token.strip().lower()
        return bool(option_id) and option_id == current_status

    def on_option_clicked(self, _button, state, option):
        """Launch the selected modal action in a terminal."""
        script = (option.get('script') or "").strip()
        if not script:
            return

        result = self.launch_terminal(script)

        if isinstance(result, subprocess.Popen):
            if (state['action'].get('status_script') or "").strip():
                state['dirty'] = True

                # Create a thread to wait for the terminal to close, then update UI
                def wait_and_refresh():
                    result.wait()
                    GLib.idle_add(self.refresh_action_dialog, state, True)
                    GLib.idle_add(self.fetch_and_update_single_status, state['action'].get('id'), state['action'].get('status_script'))

                threading.Thread(target=wait_and_refresh, daemon=True).start()
            return

        show_error_dialog(
            self,
            "No terminal available",
            f"{result}\n\nCould not open a terminal automatically.\nYou can also run the following command manually:\n\n{script}"
        )

    def launch_terminal(self, script):
        """Attempt to run a command in a terminal. Returns None on success."""
        try:
            self.on_controller_context_changed()
            process = subprocess.Popen(build_terminal_command(script))
            return process
        except FileNotFoundError:
            return "The default terminal launcher (xdg-terminal-exec) was not found."
        except Exception as e:
            return f"Terminal launch failed: {e}"

    def refresh_current_page_actions(self):
        """Run status check for the page the user is currently on."""
        if hasattr(self, 'content_stack') and self.content_stack.get_visible_child_name() == "search":
            actions = getattr(self, 'current_search_matches', [])
        else:
            if not self.current_page_name:
                return
            actions = self.page_actions_map.get(self.current_page_name, [])
        actions_to_check = [action for action in actions
                            if action.get('status_script')
                            and self.action_status_widgets.get(action.get('id')) is not None
                            and self.action_status_widgets[action.get('id')].get_text() == "⏳ Checking..."]

        if not actions_to_check:
            return
        actions_iterator = iter(actions_to_check)
        def _submit_next_task():
            try:
                action = next(actions_iterator)
                self.action_status_widgets.get(action.get('id')).set_text("⏳ Fetching...")
                self.executor.submit(
                    self.fetch_and_update_single_status,
                    action.get('id'),
                    action.get('status_script')
                )
                return GLib.SOURCE_CONTINUE
            except StopIteration:
                return GLib.SOURCE_REMOVE
        GLib.idle_add(_submit_next_task)

    def on_destroy(self, widget):
        """Let executor threads finish naturally"""
        self.on_controller_close_request()
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)

    def fetch_and_update_single_status(self, action_id, status_script):
        """Executes a single script and schedules a UI update."""
        status_token = "unknown"
        try:
            result = subprocess.run(
                build_headless_command(status_script),
                capture_output=True,
                text=True,
                timeout=STATUS_TIMEOUT_SECONDS,
                check=False,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    token = line.strip()
                    if token:
                        status_token = token
                        break
        except Exception:
            pass

        # Safely update the GTK UI from the background thread
        GLib.idle_add(self._update_status_ui, action_id, status_token)

    def _update_status_ui(self, action_id, status_token):
        """Updates the icon and label on the main GTK thread."""
        widgets = self.action_status_widgets.get(action_id)
        if not widgets:
            return False

        token_lower = status_token.lower()
        if token_lower in ["install", "active", "enable", "add", "upgraded"]:
            emoji = "🟢"
        elif token_lower in ["uninstall", "inactive", "disable", "disabled", "remove", "unset", "mismatch"]:
            emoji = "🟠"
        elif token_lower == "unknown":
            emoji = "⚪"
        else:
            emoji = "🔵"

        # Map token to human-readable text
        if status_token == "unknown":
            display_text = "Unknown"
        elif token_lower in ["install"]:
            display_text = "Installed"
        elif token_lower in ["enable"]:
            display_text = "Enabled"
        elif token_lower in ["uninstall"]:
            display_text = "Not installed"
        elif token_lower in ["disable"]:
            display_text = "Disabled"
        elif token_lower in ["remove"]:
            display_text = "Removed"
        else:
            display_text = status_token.capitalize()

        # Update the single label with both the emoji and text
        widgets.set_text(f"{emoji} {display_text}")
        return False

    def _get_page_for_widget(self, widget):
        """Gets the page number of the widget to switch to. Returns None on fail."""
        current = widget
        while current is not None:
            parent = current.get_parent()
            # Parent is screen stack, current is stack of screens
            if parent == self.screen_stack:
                page_name = self.screen_stack.get_page(current).get_name()
                return page_name
            current = parent
        return None

    def _apply_highlight(self, button):
        """Scroll and applies highlight"""
        scrolled = button.get_ancestor(Gtk.ScrolledWindow)
        if scrolled:
            try:
                scrolled.scroll_to_child(button, None)
            except AttributeError:
                pass
        button.add_css_class("highlighted-action")
        if button.get_mapped():
            self.set_focus(button)

    def highlight_action(self, action_id):
        if action_id not in self.action_widgets:
            return

        button = self.action_widgets[action_id]
        page_name = self._get_page_for_widget(button)
        self.content_stack.set_visible_child_name("tabs")
        self.screen_stack.set_visible_child_name(page_name)
        GLib.timeout_add(250, lambda: [self._apply_highlight(button), False][1])

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Bazzite Portal")
    parser.add_argument("CONFIG_FILE", help="Path to the yafti.yml configuration file")
    parser.add_argument("--action-id", help="ID of the action to highlight", default=None)
    args = parser.parse_args()

    # Initialize GTK before creating the window.
    initialize_gtk()

    loop = GLib.MainLoop()

    # Create and show window
    win = YaftiGTK(args.CONFIG_FILE)
    win.connect("close-request", lambda *_: loop.quit())
    win.set_visible(True)

    # If an action ID was provided, highlight it after window is shown
    if args.action_id:
        GLib.idle_add(win.highlight_action, args.action_id)

    loop.run()


if __name__ == '__main__':
    main()
