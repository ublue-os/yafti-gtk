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

class YaftiGTK(Gtk.Window):
    def __init__(self, config_file='yafti.yml'):
        super().__init__(title="Yafti Portal")
        self.set_default_size(800, 600)
        self.set_border_width(10)
        
        # Load YAML configuration
        self.config = self.load_config(config_file)
        
        # Create main container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(vbox)
        
        # Add title label
        title_label = Gtk.Label()
        title_label.set_markup(f"<span size='x-large' weight='bold'>{self.config.get('title', 'Yafti Portal')}</span>")
        title_label.set_margin_bottom(10)
        vbox.pack_start(title_label, False, False, 0)
        
        # Create notebook (tabs) for screens
        notebook = Gtk.Notebook()
        vbox.pack_start(notebook, True, True, 0)
        
        # Add each screen as a tab
        for screen in self.config.get('screens', []):
            page = self.create_screen_page(screen)
            label = Gtk.Label(label=screen.get('title', 'Screen'))
            notebook.append_page(page, label)
        
        # Add status bar at bottom
        self.statusbar = Gtk.Statusbar()
        self.status_context = self.statusbar.get_context_id("status")
        vbox.pack_start(self.statusbar, False, False, 0)
        
    def load_config(self, config_file):
        """Load and parse the YAML configuration file"""
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Configuration file not found"
            )
            dialog.format_secondary_text(
                f"Could not find {config_file} in the current directory."
            )
            dialog.run()
            dialog.destroy()
            sys.exit(1)
        except yaml.YAMLError as e:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="YAML parsing error"
            )
            dialog.format_secondary_text(str(e))
            dialog.run()
            dialog.destroy()
            sys.exit(1)
    
    def create_screen_page(self, screen):
        """Create a page for a screen with all its actions"""
        # Create scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        # Create main box for the page
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page_box.set_margin_top(10)
        page_box.set_margin_bottom(10)
        page_box.set_margin_start(10)
        page_box.set_margin_end(10)
        
        # Add description
        if screen.get('description'):
            desc_label = Gtk.Label(label=screen['description'])
            desc_label.set_line_wrap(True)
            desc_label.set_xalign(0)
            desc_label.set_margin_bottom(10)
            page_box.pack_start(desc_label, False, False, 0)
            
            separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            page_box.pack_start(separator, False, False, 0)
        
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
        button_box.set_margin_top(5)
        button_box.set_margin_bottom(5)
        button_box.set_margin_start(5)
        button_box.set_margin_end(5)
        
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
    
    def on_action_clicked(self, button, title, script):
        """Handle action button click - run script in terminal window"""
        if not script:
            self.statusbar.push(self.status_context, "No script defined for this action")
            return
        
        # Update statusbar
        self.statusbar.push(self.status_context, f"Running: {title}")
        
        # Create dialog with terminal
        dialog = Gtk.Dialog(
            title=f"Running: {title}",
            transient_for=self,
            flags=0
        )
        dialog.set_default_size(700, 400)
        
        # Create terminal widget
        terminal = Vte.Terminal()
        terminal.set_scroll_on_output(True)
        terminal.set_scrollback_lines(10000)
        
        # Create scrolled window for terminal
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(terminal)
        
        dialog.vbox.pack_start(scrolled, True, True, 0)
        
        # Add close button
        close_button = dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        
        # Show dialog
        dialog.show_all()
        
        # Spawn the script in the terminal. When running inside a Flatpak sandbox
        # prefer `flatpak-spawn --host` so `ujust` and other host tools run on the host.
        try:
            if os.environ.get('FLATPAK_ID'):
                cmd = ['/usr/bin/flatpak-spawn', '--host', '/bin/bash', '-c', script]
            else:
                cmd = ['/bin/bash', '-c', script]

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
            error_dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Error running script"
            )
            error_dialog.format_secondary_text(str(e))
            error_dialog.run()
            error_dialog.destroy()
            dialog.destroy()
        
        # Handle dialog response
        dialog.connect("response", lambda d, r: d.destroy())
    
    def on_terminal_spawn_callback(self, terminal, pid, error, user_data):
        """Callback after terminal spawn"""
        dialog, title = user_data
        if error:
            self.statusbar.push(self.status_context, f"Error running {title}")
            print(f"Error: {error}")
        else:
            # Watch for child exit
            terminal.connect("child-exited", self.on_terminal_child_exited, dialog, title)
    
    def on_terminal_child_exited(self, terminal, status, dialog, title):
        """Handle terminal process exit"""
        if status == 0:
            self.statusbar.push(self.status_context, f"Completed: {title}")
        else:
            self.statusbar.push(self.status_context, f"Failed: {title} (exit code: {status})")

def main():
    # Check if config file exists
    config_file = 'yafti.yml'
    if not os.path.exists(config_file):
        print(f"Error: {config_file} not found in current directory")
        sys.exit(1)
    
    # Create and show window
    win = YaftiGTK(config_file)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

if __name__ == '__main__':
    main()
