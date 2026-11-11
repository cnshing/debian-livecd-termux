#!/data/data/com.termux/files/usr/bin/python
"""Regression: the Ghostty menu entry and New Window action map real X11 windows.

Run with livecd-native exec -- python tests/native/test-ghostty-menu.py.
"""
import subprocess
import time

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio


def windows():
    result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--class', 'ghostty'],
                            text=True, capture_output=True)
    return set(result.stdout.split())


def wait(predicate):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError('Ghostty menu launch did not reach the expected window state')


entry = Gio.DesktopAppInfo.new('com.mitchellh.ghostty.desktop')
assert entry is not None
assert not entry.get_boolean('DBusActivatable'), entry.get_filename()
for action in (None, 'new-window'):
    before = windows()
    if action is None:
        assert entry.launch([], None)
    else:
        assert action in entry.list_actions()
        entry.launch_action(action, None)
    window = next(iter(wait(lambda: windows() - before)))
    try:
        subprocess.run(['xdotool', 'windowactivate', '--sync', window], check=True)
        # A functioning shell proves the terminal surface initialized as well.
        subprocess.run(['xdotool', 'type', '--clearmodifiers', 'exit'], check=True)
        subprocess.run(['xdotool', 'key', 'Return'], check=True)
        wait(lambda: window not in windows())
    finally:
        if window in windows():
            subprocess.run(['xdotool', 'windowquit', window], check=False)
    print(f'PASS: Ghostty {action or "menu entry"} opened a visible window and shell exit closed it')
