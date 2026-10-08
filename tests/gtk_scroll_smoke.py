"""Run on Linux with GTK4: xvfb-run -a python3 tests/gtk_scroll_smoke.py."""
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yafti_gtk as app


def drain(seconds):
    deadline = time.monotonic() + seconds
    context = app.GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(.003)


def assert_visible(target):
    scrolled = target.get_ancestor(app.Gtk.ScrolledWindow)
    viewport = scrolled.get_child()
    # Check the rendered viewport coordinates, including the content's margins.
    success, bounds = target.compute_bounds(viewport)
    assert success
    adjustment = scrolled.get_vadjustment()
    top = bounds.get_y()
    bottom = top + bounds.get_height()
    start = 0
    end = viewport.get_height()
    assert top >= start - 1 and bottom <= end + 1, (top, bottom, start, end)
    return adjustment.get_value()


def exercise(window, actions):
    # Visit every row, checking both visibility and scroll direction after GTK
    # settles. Previously the adjustment bounced back up halfway down the list.
    previous = 0
    for target in actions:
        window.focus_controller_target(target)
        drain(.3)
        value = assert_visible(target)
        assert value >= previous - 1, ('downward scroll reversed', previous, value)
        previous = value
    for target in reversed(actions):
        window.focus_controller_target(target)
        drain(.3)
        value = assert_visible(target)
        assert value <= previous + 1, ('upward scroll reversed', previous, value)
        previous = value
    # Match held-stick repeat timing, then check that scrolling converges to the
    # latest focused row rather than retaining a stale scroll request.
    actions[0].grab_focus()
    drain(.3)
    for _ in range(len(actions) - 1):
        window.dispatch_controller('down')
        drain(.1)
    drain(.35)
    assert window.controller_focus == actions[-1]
    assert_visible(actions[-1])


def main():
    app.initialize_gtk()
    actions = [{'title': f'Long list action {index}',
                'description': 'Wrapped description. ' * (3 + index % 5),
                'script': 'true'} for index in range(24)]
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / 'config.yml'
        config.write_text(app.yaml.safe_dump({'screens': [{'title': 'Long list', 'actions': actions}]}))
        window = app.YaftiGTK(str(config))
        # This test drives GTK navigation directly; no controller hardware needed.
        window.start_controller = lambda: False
        window.present()
        drain(.4)
        window.controller_used = True
        window.controller_legend.set_visible(True)
        drain(.3)
        page = window.screen_stack.get_visible_child()
        exercise(window, page.controller_targets)
        window.search_entry.set_text('Long list')
        window.on_search_changed(window.search_entry)
        drain(.4)
        exercise(window, window.search_targets)
        window.on_controller_close_request()
        window.destroy()
        print('PASS: long tab/search lists stay visible in both directions and after held-input repeats')


if __name__ == '__main__':
    main()
