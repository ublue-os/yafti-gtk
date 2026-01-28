#!/usr/bin/env python3
"""
Yafti GTK - A simple GTK GUI for running scripts from yafti.yml
"""

import gi
import yaml
import subprocess
import os
import sys

gi.require_version('Gtk', '3.0')
gi.require_version('Vte', '2.91')
from gi.repository import Gtk, Vte, GLib

# Constants
APP_ID = 'io.github.ublue_os.yafti_gtk'
APP_TITLE = 'Bazzite Portal'
DEFAULT_WINDOW_WIDTH = 800
DEFAULT_WINDOW_HEIGHT = 600
DIALOG_WIDTH = 700
DIALOG_HEIGHT = 400
SCROLLBACK_LINES = 10000
TERMINAL_CHECK_TIMEOUT = 2
FLATPAK_SPAWN = '/usr/bin/flatpak-spawn'


def set_widget_margins(widget, top=10, bottom=10, start=10, end=10):
    """Apply consistent margins to a widget."""
    widget.set_margin_top(top)
    widget.set_margin_bottom(bottom)
    widget.set_margin_start(start)
    widget.set_margin_end(end)


def clear_container(container):
    """Remove all children from a container widget."""
    for child in container.get_children():
        container.remove(child)


def show_error_dialog(parent, title, message):
    """Display an error dialog with the given title and message."""
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        flags=0,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.OK,
        text=title
    )
    dialog.format_secondary_text(message)
    dialog.run()
    dialog.destroy()


def setup_theme():
    """Apply dark theme at startup."""
    GLib.set_prgname(APP_ID)

    # Set dark theme
    os.environ['GTK_THEME'] = 'Adwaita:dark'
    
    Gtk.init([])

    try:
        Gtk.Window.set_default_icon_name(APP_ID)
    except Exception as e:
        print(f"Warning: Could not set app icon: {e}")
    
    settings = Gtk.Settings.get_default()
    if settings:
        settings.set_property('gtk-application-prefer-dark-theme', True)


class YaftiGTK(Gtk.Window):
    def __init__(self, config_file='yafti.yml'):
        super().__init__(title=APP_TITLE)
        self.set_default_size(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.set_border_width(10)
        
        # Load YAML configuration
        self.config = self.load_config(config_file)
        self.screens = self.config.get('screens', [])
        self.actions_index = self._build_actions_index()
        
        # Create main container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)
        
        # Search bar at the top
        search_entry = Gtk.SearchEntry()
        search_entry.set_placeholder_text("Search Apps and Actions")
        set_widget_margins(search_entry, 4, 4, 4, 4)
        search_entry.connect("search-changed", self.on_search_changed)
        self.search_entry = search_entry
        vbox.pack_start(search_entry, False, False, 0)

        # Notebook (tabs) directly below search
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        
        # Add tabs for each screen from YAML
        for screen in self.screens:
            page = self.create_screen_page(screen)
            label = Gtk.Label(label=screen.get('title', 'Tab'))
            self.notebook.append_page(page, label)

        # Stack to switch between notebook and search results
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.set_transition_duration(150)
        
        # Add notebook to stack
        self.content_stack.add_named(self.notebook, "tabs")
        
        # Search results page
        search_scrolled = Gtk.ScrolledWindow()
        search_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        set_widget_margins(results_box, 10, 10, 10, 10)
        self.search_results_box = results_box
        search_scrolled.add(results_box)
        self.content_stack.add_named(search_scrolled, "search")
        
        # Start with tabs visible
        self.content_stack.set_visible_child_name("tabs")
        
        vbox.pack_start(self.content_stack, True, True, 0)
        
    def load_config(self, config_file):
        """Load and parse the YAML configuration file"""
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f)
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
        """Create a page for a screen with all its actions"""
        # Create scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        # Create main box for the page
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        set_widget_margins(page_box, 10, 10, 10, 10)
        
        # Create action items
        for action in screen.get('actions', []):
            action_box = self.create_action_item(action)
            page_box.pack_start(action_box, False, False, 0)
        
        scrolled.add(page_box)
        return scrolled
    
    def create_action_item(self, action):
        """Create a clickable action item"""
        # Create a button for the action
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        
        # Create box for button content
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        set_widget_margins(button_box, 5, 5, 5, 5)
        
        # Add icon (play button)
        icon = Gtk.Image.new_from_icon_name("media-playback-start", Gtk.IconSize.BUTTON)
        button_box.pack_start(icon, False, False, 0)
        
        # Create text box
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        
        # Title label
        title_label = Gtk.Label()
        title_label.set_markup(f"<b>{action.get('title', 'Action')}</b>")
        title_label.set_xalign(0)
        text_box.pack_start(title_label, False, False, 0)
        
        # Description label
        if action.get('description'):
            desc_label = Gtk.Label(label=action['description'])
            desc_label.set_xalign(0)
            desc_label.set_line_wrap(True)
            desc_label.set_max_width_chars(60)
            desc_label.get_style_context().add_class('dim-label')
            text_box.pack_start(desc_label, False, False, 0)
        
        button_box.pack_start(text_box, True, True, 0)
        button.add(button_box)
        
        # Connect click event
        script = action.get('script', '')
        button.connect("clicked", self.on_action_clicked, action.get('title', 'Action'), script)
        
        # Add frame around button
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.add(button)
        
        return frame

    def _build_actions_index(self):
        """Flatten actions for search lookup."""
        index = []
        for screen in self.screens or []:
            for action in screen.get('actions', []):
                index.append({'screen_title': screen.get('title', ''), 'action': action})
        return index

    def on_search_changed(self, entry):
        query = entry.get_text().strip()
        if not query:
            clear_container(self.search_results_box)
            self.content_stack.set_visible_child_name("tabs")
            return

        lowered = query.lower()
        matches = []
        for item in self.actions_index:
            action = item['action']
            title = action.get('title', '')
            desc = action.get('description', '')
            if lowered in title.lower() or lowered in desc.lower():
                matches.append(item)

        # Clear old results
        clear_container(self.search_results_box)
        
        header = Gtk.Label()
        header.set_markup("<b>Search results</b>")
        header.set_xalign(0)
        self.search_results_box.pack_start(header, False, False, 0)

        if matches:
            for item in matches:
                self.search_results_box.pack_start(
                    self.create_action_item(item['action']), False, False, 0
                )
        else:
            empty = Gtk.Label(label="No matches found")
            empty.set_xalign(0)
            self.search_results_box.pack_start(empty, False, False, 0)

        self.search_results_box.show_all()
        self.content_stack.set_visible_child_name("search")
    
    def on_action_clicked(self, button, title, script):
        """Handle action button click - run script in terminal window"""
        if not script:
            return

        # Try host terminal first; fall back to embedded VTE if it fails
        if self.launch_host_terminal(script.strip()):
            return
        
        # Create dialog with terminal
        dialog = Gtk.Dialog(
            title=f"Running: {title}",
            transient_for=self,
            flags=0
        )
        dialog.set_default_size(DIALOG_WIDTH, DIALOG_HEIGHT)
        
        # Create terminal widget
        terminal = Vte.Terminal()
        terminal.set_scroll_on_output(True)
        terminal.set_scrollback_lines(SCROLLBACK_LINES)
        
        # Create scrolled window for terminal
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(terminal)
        
        dialog.vbox.pack_start(scrolled, True, True, 0)
        
        # Add close button
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        
        # Show dialog
        dialog.show_all()
        
        # Spawn the script in the terminal using flatpak-spawn to execute on the host
        # so ujust and other host tools are available
        try:
            cmd = [FLATPAK_SPAWN, '--host', '/bin/bash', '-c', script]

            terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                os.getcwd(),
                cmd,
                None,
                GLib.SpawnFlags.DEFAULT,
                None,
                None,
                -1,
                None,
                self.on_terminal_spawn_callback,
                (dialog, title)
            )
        except Exception as e:
            show_error_dialog(self, "Error running script", str(e))
            dialog.destroy()
        
        # Handle dialog response
        dialog.connect("response", lambda d, r: d.destroy())

    def launch_host_terminal(self, script):
        """Attempt to run a command in a host terminal. Returns True if launched."""
        candidate_terminals = [
            "ptyxis",
            "konsole",
            "gnome-terminal",
            "xterm",
        ]
        
        for terminal in candidate_terminals:
            try:
                # First check if terminal exists on host
                check = subprocess.run(
                    [FLATPAK_SPAWN, "--host", "which", terminal],
                    capture_output=True,
                    timeout=TERMINAL_CHECK_TIMEOUT
                )
                if check.returncode != 0:
                    continue  # Terminal not found, try next
                    
                # Terminal exists, launch it
                cmd = [
                    FLATPAK_SPAWN,
                    "--host",
                    terminal,
                    "--",
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-lc",
                    script,
                ]
                subprocess.Popen(cmd)
                return True
            except Exception as e:
                print(f"Host terminal '{terminal}' launch failed: {e}")
                continue
        
        print("Host terminal launch failed: no suitable terminal found.")
        return False
    
    def on_terminal_spawn_callback(self, terminal, pid, error, user_data, *args):
        """Callback after terminal spawn"""
        dialog, title = user_data

        if error:
            print(f"Error spawning terminal for {title}: {error}")
            return
        terminal.connect("child-exited", self.on_terminal_child_exited, dialog, title)
    
    def on_terminal_child_exited(self, terminal, status, dialog, title):
        """Handle terminal process exit"""
        if status != 0:
            print(f"Script '{title}' exited with code {status}")


def main():
    # Check command-line arguments
    if len(sys.argv) != 2:
        print(f"Usage: {APP_ID} CONFIG_FILE")
        print(f"Example: flatpak run {APP_ID} /run/host/usr/share/yafti/yafti.yml")
        sys.exit(1)
    
    config_file = sys.argv[1]
    
    # Apply theme before creating window
    setup_theme()

    # Validate config file exists
    if not os.path.exists(config_file):
        print(f"Error: yafti config not found at {config_file}")
        sys.exit(1)
    
    # Create and show window
    win = YaftiGTK(config_file)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == '__main__':
    main()
