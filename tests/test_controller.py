"""Hardware-independent input and GTK routing tests; no GI/SDL install needed."""
import ctypes
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Widget:
    def __init__(self, owner=None):
        self.owner = owner
        self.mapped = self.sensitive = True
        self.classes = set()
        self.activations = 0

    def get_mapped(self):
        return self.mapped

    def is_sensitive(self):
        return self.sensitive

    def is_ancestor(self, other):
        return False

    def grab_focus(self):
        self.owner.focus = self

    def get_ancestor(self, _kind):
        return None

    def add_css_class(self, name):
        self.classes.add(name)

    def remove_css_class(self, name):
        self.classes.discard(name)

    def activate(self):
        self.activations += 1


class Switch(Widget):
    active = False

    def get_active(self):
        return self.active

    def set_active(self, active):
        self.active = active


class Viewport:
    def __init__(self):
        self.set_scroll_to_focus = Mock()


gi = types.ModuleType('gi')
gi.require_version = Mock()
repository = types.ModuleType('gi.repository')
repository.GLib = Mock()
repository.Gtk = types.SimpleNamespace(Window=object, Switch=Switch, ScrolledWindow=object, Viewport=Viewport)
spec = importlib.util.spec_from_file_location('portal_controller_tests', Path(__file__).resolve().parents[1] / 'yafti_gtk.py')
app = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'gi': gi, 'gi.repository': repository, 'yaml': types.ModuleType('yaml')}):
    spec.loader.exec_module(app)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.input = app.ControllerInput()
        self.input.update(set(), 0, 0, 0)

    def test_button_edges(self):
        for button in ('confirm', 'back', 'focus_search', 'toggle_startup', 'previous_tab', 'next_tab'):
            self.assertEqual(self.input.update({button}, 0, 0, 0), [button])
            self.assertEqual(self.input.update({button}, 0, 0, 1), [])
            self.input.update(set(), 0, 0, 2)
            self.assertEqual(self.input.update({button}, 0, 0, 3), [button])
            self.input.update(set(), 0, 0, 4)

    def test_dead_zone_and_dominant_axis(self):
        self.assertEqual(self.input.update(set(), .34, -.34, 0), [])
        self.assertEqual(self.input.update(set(), .35, 0, 0), [])
        self.assertEqual(self.input.update(set(), .6, -.8, .1), ['up'])
        self.assertEqual(self.input.update({'down'}, 1, 0, .2), ['down'])

    def test_horizontal_controls_do_not_navigate(self):
        for buttons, x, y in [({'left'}, 0, 0), ({'right'}, 0, 0), (set(), -1, 0), (set(), 1, .5)]:
            self.assertEqual(self.input.update(buttons, x, y, 0), [])

    def test_repeat_and_direction_change(self):
        self.assertEqual(self.input.update({'down'}, 0, 0, 0), ['down'])
        self.assertEqual(self.input.update({'down'}, 0, 0, .349), [])
        self.assertEqual(self.input.update({'down'}, 0, 0, .350), ['down'])
        self.assertEqual(self.input.update({'down'}, 0, 0, .449), [])
        self.assertEqual(self.input.update({'down'}, 0, 0, .451), ['down'])
        self.assertEqual(self.input.update({'up'}, 0, 0, .46), ['up'])

    def test_reset_requires_neutral(self):
        self.input.reset()
        self.assertEqual(self.input.update({'confirm'}, 0, 0, 0), [])
        self.assertEqual(self.input.update(set(), .8, 0, 1), [])
        self.assertEqual(self.input.update(set(), 0, 0, 2), [])
        self.assertEqual(self.input.update({'confirm'}, 0, 0, 3), ['confirm'])


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.sample.return_value = [(1, set(), 0, 0, {})]
        self.scheduler = Mock()
        self.scheduler.timeout_add.return_value = 42
        self.context = 'main'
        self.commands = []
        self.driver = app.ControllerDriver(self.backend, lambda: self.context, self.commands.append, self.scheduler)
        self.driver.poll()

    def test_focus_gates_input_and_release(self):
        self.context = None
        self.backend.sample.return_value = [(1, {'confirm'}, 0, 0, {})]
        self.driver.poll()
        self.context = 'main'
        self.driver.poll()
        self.assertEqual(self.commands, [])
        self.backend.sample.return_value = [(1, set(), 0, 0, {})]
        self.driver.poll()
        self.backend.sample.return_value = [(1, {'confirm'}, 0, 0, {})]
        self.driver.poll()
        self.driver.poll()
        self.assertEqual(self.commands, ['confirm'])

    def test_disconnect_and_reconnect_held_button(self):
        self.backend.sample.return_value = []
        self.driver.poll()
        self.backend.sample.return_value = [(2, {'back'}, 0, 0, {})]
        self.driver.poll()
        self.assertEqual(self.commands, [])
        self.backend.sample.return_value = [(2, set(), 0, 0, {})]
        self.driver.poll()
        self.backend.sample.return_value = [(2, {'back'}, 0, 0, {})]
        self.driver.poll()
        self.assertEqual(self.commands, ['back'])

    def test_modal_context_requires_release(self):
        self.context = 'dialog'
        self.backend.sample.return_value = [(1, {'confirm'}, 0, 0, {})]
        self.driver.poll()
        self.assertEqual(self.commands, [])

    def test_activation_discards_remaining_commands(self):
        self.backend.sample.return_value = [(1, {'confirm', 'next_tab'}, 0, 0, {})]
        self.driver.poll()
        self.assertEqual(self.commands, ['confirm'])

    def test_cleanup(self):
        self.driver.close()
        self.driver.close()
        self.scheduler.source_remove.assert_called_once_with(42)

    def test_backend_failure_stops_timer(self):
        self.backend.sample.side_effect = RuntimeError('device error')
        with patch('sys.stderr'):
            self.assertFalse(self.driver.poll())
        self.backend.close.assert_called_once()
        self.assertIsNone(self.driver.source)

    def test_all_controllers_have_independent_button_edges(self):
        self.backend.sample.return_value = [(1, set(), 0, 0, {}), (2, set(), 0, 0, {'confirm': 5})]
        self.driver.poll()
        self.backend.sample.return_value = [(1, {'next_tab'}, 0, 0, {}), (2, {'previous_tab'}, 0, 0, {'confirm': 5})]
        self.driver.poll()
        self.driver.poll()
        self.assertEqual(self.commands, ['next_tab', 'previous_tab'])
        self.assertEqual(self.backend.button_labels, {'confirm': 5})

    def test_unrelated_disconnect_preserves_held_button_state(self):
        self.backend.sample.return_value = [(1, set(), 0, 0, {}), (2, set(), 0, 0, {})]
        self.driver.poll()
        self.backend.sample.return_value = [(2, {'next_tab'}, 0, 0, {})]
        self.driver.poll()
        self.driver.poll()
        self.assertEqual(self.commands, ['next_tab'])
        self.assertEqual(set(self.driver.inputs), {2})

    def test_simultaneous_confirm_does_not_activate_twice(self):
        self.backend.sample.return_value = [(1, set(), 0, 0, {}), (2, set(), 0, 0, {})]
        self.driver.poll()
        self.backend.sample.return_value = [(1, {'confirm'}, 0, 0, {}), (2, {'confirm'}, 0, 0, {})]
        self.driver.poll()
        self.driver.poll()
        self.assertEqual(self.commands, ['confirm'])

    def test_idle_controller_does_not_block_other_controller_repeat(self):
        self.backend.sample.return_value = [(1, set(), 0, 0, {}), (2, set(), 0, 0, {})]
        self.driver.poll()
        self.backend.sample.return_value = [(1, set(), 0, 0, {}), (2, {'down'}, 0, 0, {})]
        with patch.object(app.time, 'monotonic', side_effect=[0, .35, .451]):
            for _ in range(3):
                self.driver.poll()
        self.assertEqual(self.commands, ['down', 'down', 'down'])

    def test_distinct_controllers_keep_simultaneous_navigation(self):
        self.backend.sample.return_value = [(1, set(), 0, 0, {}), (2, set(), 0, 0, {})]
        self.driver.poll()
        self.backend.sample.return_value = [(1, {'down'}, 0, 0, {}), (2, {'down'}, 0, 0, {})]
        self.driver.poll()
        self.assertEqual(self.commands, ['down', 'down'])


class SDLTests(unittest.TestCase):
    def setUp(self):
        self.sdl = Mock()
        self.sdl.SDL_InitSubSystem.return_value = True
        self.sdl.SDL_GetGamepadAxis.return_value = 0
        self.sdl.SDL_GetGamepadButton.return_value = False
        self.sdl.SDL_GamepadConnected.return_value = True
        self.sdl.SDL_OpenGamepad.side_effect = lambda device: 123 if device == 7 else None
        self.ids = (ctypes.c_uint32 * 2)(7, 0)

        def enumerate_devices(count):
            ctypes.cast(count, ctypes.POINTER(ctypes.c_int))[0] = 1
            return self.ids

        self.sdl.SDL_GetGamepads.side_effect = enumerate_devices
        with patch.object(app.ctypes, 'CDLL', return_value=self.sdl), patch.object(app.ctypes.util, 'find_library', return_value='SDL3'):
            self.backend = app.SDLGamepad()

    def test_typed_bindings_and_single_subsystem(self):
        self.sdl.SDL_InitSubSystem.assert_called_once_with(0x2000)
        self.assertEqual(self.sdl.SDL_GetGamepadAxis.restype, ctypes.c_int16)
        self.assertEqual(self.sdl.SDL_GetGamepadButton.restype, ctypes.c_bool)
        self.sdl.SDL_SetJoystickEventsEnabled.assert_called_once_with(False)

    def test_reconnect_even_when_pointer_reused(self):
        first = self.backend.sample()
        self.sdl.SDL_GamepadConnected.return_value = False
        second = self.backend.sample()
        self.assertNotEqual(first[0][0], second[0][0])
        self.sdl.SDL_CloseGamepad.assert_called_once_with(123)
        self.assertEqual(self.sdl.SDL_free.call_count, 2)

    def test_cleanup_is_idempotent(self):
        self.backend.sample()
        self.backend.close()
        self.backend.close()
        self.sdl.SDL_CloseGamepad.assert_called_once_with(123)
        self.sdl.SDL_QuitSubSystem.assert_called_once_with(0x2000)

    def test_opens_and_reads_all_connected_controllers(self):
        self.sdl.SDL_OpenGamepad.side_effect = lambda device: {7: 123, 8: 456}[device]

        def enumerate_devices(count):
            ctypes.cast(count, ctypes.POINTER(ctypes.c_int))[0] = 2
            return (ctypes.c_uint32 * 3)(7, 8, 0)

        self.sdl.SDL_GetGamepads.side_effect = enumerate_devices
        self.sdl.SDL_GetGamepadButton.side_effect = lambda handle, button: handle == 456 and button == 0
        samples = self.backend.sample()
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0][1], set())
        self.assertEqual(samples[1][1], {'confirm'})
        self.backend.sample()
        self.assertEqual(self.sdl.SDL_OpenGamepad.call_count, 2)
        self.backend.close()
        self.sdl.SDL_CloseGamepad.assert_any_call(123)
        self.sdl.SDL_CloseGamepad.assert_any_call(456)

    def test_hotplug_device_is_discovered_through_event_pump(self):
        devices = []

        def enumerate_devices(count):
            ctypes.cast(count, ctypes.POINTER(ctypes.c_int))[0] = len(devices)
            return (ctypes.c_uint32 * (len(devices) + 1))(*devices, 0)

        self.sdl.SDL_GetGamepads.side_effect = enumerate_devices
        self.assertEqual(self.backend.sample(), [])
        self.sdl.SDL_PumpEvents.side_effect = lambda: devices.append(7) if not devices else None
        samples = self.backend.sample()
        self.assertEqual(len(samples), 1)
        self.sdl.SDL_OpenGamepad.assert_called_once_with(7)
        self.sdl.SDL_FlushEvents.assert_called_with(0, 0xFFFF)

    def test_preserves_sdl_default_filtering_and_user_environment(self):
        with patch.dict(app.os.environ, {}, clear=True), patch.object(app.ctypes.util, 'find_library', return_value='SDL3'), patch.object(app.ctypes, 'CDLL', return_value=self.sdl):
            app.SDLGamepad().close()
            self.assertNotIn('SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD', app.os.environ)
        for value in ('0', '1'):
            with patch.dict(app.os.environ, {'SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD': value}), patch.object(app.ctypes, 'CDLL', return_value=self.sdl):
                app.SDLGamepad().close()
                self.assertEqual(app.os.environ['SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD'], value)

    def test_missing_library(self):
        with patch.object(app.ctypes, 'CDLL', side_effect=OSError('missing')):
            with self.assertRaises(OSError):
                app.SDLGamepad()

    def test_init_failure(self):
        self.sdl.SDL_InitSubSystem.return_value = False
        self.sdl.SDL_GetError.return_value = b'failed'
        with patch.object(app.ctypes, 'CDLL', return_value=self.sdl):
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                app.SDLGamepad()
        self.sdl.SDL_QuitSubSystem.assert_called_once()


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.window = object.__new__(app.YaftiGTK)
        self.window.controller_dialogs = []
        self.window.active_dialog_state = None
        self.window.controller_driver = None
        self.window.controller_focus = None
        self.window.controller_used = False
        self.window.controller_legend = Mock()
        self.window.startup_controller_glyph = Mock()
        app.GLib.idle_add.reset_mock()
        self.window.focus = None
        self.window.get_focus = lambda: self.window.focus
        self.window.get_property = lambda _name: True
        self.window.search_entry = Widget(self.window)
        self.window.search_entry.get_text = lambda: ''
        self.window.search_entry.set_placeholder_text = Mock()
        self.window.autostart_switch = Switch(self.window)
        self.actions = [Widget(self.window) for _ in range(3)]
        self.page = types.SimpleNamespace(controller_targets=self.actions)
        self.window.screen_stack = Mock()
        self.window.screen_stack.get_visible_child.return_value = self.page
        self.window.content_stack = Mock()
        self.window.content_stack.get_visible_child_name.return_value = 'tabs'

    def test_navigation_includes_actions_without_ids_and_skips_toggle(self):
        self.window.dispatch_controller('down')
        self.assertIs(self.window.focus, self.actions[0])
        self.window.dispatch_controller('confirm')
        self.assertEqual(self.actions[0].activations, 1)
        for _ in range(3):
            self.window.dispatch_controller('down')
        self.assertIs(self.window.focus, self.actions[-1])
        self.assertFalse(self.window.autostart_switch.active)
        self.assertIn('controller-focus', self.actions[-1].classes)
        self.assertNotIn('controller-focus', self.actions[0].classes)

    def test_empty_page_and_disabled_targets(self):
        self.page.controller_targets = []
        self.window.dispatch_controller('up')
        self.assertIsNone(self.window.focus)
        self.window.autostart_switch.sensitive = False
        self.assertEqual(self.window.controller_targets(), [])

    def test_status_refresh_without_action_id(self):
        self.window.current_page_name = 'one'
        self.window.page_actions_map = {'one': [{'title': 'Managed', 'status_script': 'echo enable'}]}
        self.window.action_status_widgets = {}
        self.window.refresh_current_page_actions()

    def test_search_targets(self):
        self.window.content_stack.get_visible_child_name.return_value = 'search'
        self.window.search_targets = [self.actions[2]]
        self.assertEqual(self.window.controller_targets(), [self.actions[2]])
        self.window.dispatch_controller('next_tab')
        self.window.screen_stack.set_visible_child_name.assert_not_called()

    def test_top_modal_close_and_loading_targets(self):
        dialog = Mock()
        button = Widget(dialog)
        dialog.focus = None
        dialog.get_focus.side_effect = lambda: dialog.focus
        self.window.controller_dialogs = [{'dialog': Mock(), 'targets': [], 'return_focus': None}, {'dialog': dialog, 'targets': [button], 'return_focus': None}]
        self.window.dispatch_controller('down')
        self.assertIs(dialog.focus, button)
        self.window.dispatch_controller('confirm')
        self.assertEqual(button.activations, 1)
        self.window.dispatch_controller('next_tab')
        self.window.screen_stack.set_visible_child_name.assert_not_called()
        self.window.dispatch_controller('toggle_startup')
        self.assertFalse(self.window.autostart_switch.active)
        self.window.dispatch_controller('focus_search')
        self.assertIs(dialog.focus, button)
        app.GLib.idle_add.assert_not_called()
        self.window.dispatch_controller('back')
        dialog.destroy.assert_called_once()

    def test_startup_shortcut_preserves_focus_and_works_in_search(self):
        self.actions[1].grab_focus()
        self.window.dispatch_controller('toggle_startup')
        self.assertTrue(self.window.autostart_switch.active)
        self.assertIs(self.window.focus, self.actions[1])
        self.window.content_stack.get_visible_child_name.return_value = 'search'
        self.window.dispatch_controller('toggle_startup')
        self.assertFalse(self.window.autostart_switch.active)

    def test_legend_glyphs_and_visibility(self):
        self.assertIn('Ⓐ Select', app.controller_legend_text())
        self.assertNotIn('Startup', app.controller_legend_text())
        self.assertNotIn('Search', app.controller_legend_text())
        self.assertEqual(app.controller_button_glyph('focus_search'), 'Ⓧ')
        self.assertEqual(app.controller_button_glyph('toggle_startup'), 'Ⓨ')
        sony = app.controller_legend_text({'confirm': 5, 'back': 6, 'focus_search': 7, 'toggle_startup': 8})
        self.assertIn('✕ Select', sony)
        self.assertIn('○ Back', sony)
        self.assertEqual(app.controller_button_glyph('focus_search', {'focus_search': 7}), '▢')
        self.assertFalse(self.window.controller_used)
        self.window.controller_legend.set_visible.assert_not_called()
        self.window.dispatch_controller('down')
        self.window.controller_legend.set_visible.assert_called_with(True)
        self.window.startup_controller_glyph.set_label.assert_called_with('Ⓨ')
        self.window.search_entry.set_placeholder_text.assert_called_with('Ⓧ Search Apps and Actions')

    def test_search_shortcut_and_vertical_only_navigation(self):
        self.actions[1].grab_focus()
        for command in ('left', 'right'):
            self.window.dispatch_controller(command)
            self.assertIs(self.window.focus, self.actions[1])
        self.window.dispatch_controller('focus_search')
        self.assertIs(self.window.focus, self.window.search_entry)
        app.GLib.idle_add.assert_called_once_with(self.window.request_steam_keyboard)
        self.assertIn('controller-focus', self.window.search_entry.classes)
        self.window.dispatch_controller('up')
        self.window.dispatch_controller('up')
        self.assertIs(self.window.focus, self.window.search_entry)
        self.window.dispatch_controller('down')
        self.assertIs(self.window.focus, self.actions[0])

    def test_up_stays_in_search_internal_text_widget(self):
        text = Widget(self.window)
        text.is_ancestor = lambda ancestor: ancestor == self.window.search_entry
        text.grab_focus()
        self.window.content_stack.get_visible_child_name.return_value = 'search'
        self.window.search_targets = [self.actions[2]]
        self.window.dispatch_controller('up')
        self.assertIs(self.window.focus, text)
        self.window.dispatch_controller('down')
        self.assertIs(self.window.focus, self.actions[2])
        self.window.dispatch_controller('up')
        self.assertIs(self.window.focus, self.actions[2])

    def test_steam_keyboard_request_only_in_gaming_mode(self):
        self.window.search_entry.grab_focus()
        with patch.dict(app.os.environ, {'XDG_CURRENT_DESKTOP': 'gamescope'}), patch.object(app.subprocess, 'Popen') as launch:
            self.window.request_steam_keyboard()
            launch.assert_called_once_with(['steam', '-ifrunning', 'steam://open/keyboard'], stdout=app.subprocess.DEVNULL, stderr=app.subprocess.DEVNULL)
        with patch.dict(app.os.environ, {'XDG_CURRENT_DESKTOP': 'KDE', 'SteamGamepadUI': '0'}), patch.object(app.subprocess, 'Popen') as launch:
            self.window.request_steam_keyboard()
            launch.assert_not_called()

    def test_dialog_rebuild_and_restore_focus(self):
        self.actions[1].grab_focus()
        dialog = Mock()
        self.window.register_controller_dialog(dialog, [])
        replacement = Widget(dialog)
        self.window.set_dialog_controller_targets(dialog, [replacement])
        self.assertEqual(self.window.controller_targets(), [replacement])
        record = self.window.controller_dialogs[-1]
        self.window.on_controller_dialog_destroy(dialog, record)
        self.assertIs(self.window.focus, self.actions[1])

    def test_close_marks_status_request_closed_before_destroy_signal(self):
        dialog = Mock()
        state = {'dialog': dialog, 'closed': False}
        self.window.active_dialog_state = state
        self.window.register_controller_dialog(dialog, [])
        self.window.close_controller_dialog(dialog)
        self.assertTrue(state['closed'])
        self.assertIsNone(self.window.active_dialog_state)
        self.assertEqual(self.window.controller_dialogs, [])
        dialog.destroy.assert_called_once()

    def test_tab_wrap(self):
        names = ['one', 'two']
        pages = Mock()
        pages.get_n_items.return_value = 2
        pages.get_item.side_effect = lambda index: types.SimpleNamespace(get_name=lambda: names[index])
        self.window.screen_stack.get_pages.return_value = pages
        self.window.screen_stack.get_visible_child_name.return_value = 'one'
        self.window.dispatch_controller('previous_tab')
        self.window.screen_stack.set_visible_child_name.assert_called_once_with('two')

    def test_scroll_focus_into_view(self):
        scrolled = Mock()
        viewport = Viewport()
        scrolled.get_child.return_value = viewport
        target = self.actions[0]
        target.get_ancestor = lambda _kind: scrolled
        target.compute_bounds = Mock(side_effect=AssertionError('Do not use viewport coordinates for adjustment math'))
        original_focus = target.grab_focus

        def focus():
            viewport.set_scroll_to_focus.assert_called_with(True)
            original_focus()

        target.grab_focus = focus
        self.window.focus_controller_target(target)
        self.assertIs(self.window.focus, target)
        scrolled.get_vadjustment.assert_not_called()


if __name__ == '__main__':
    unittest.main()
