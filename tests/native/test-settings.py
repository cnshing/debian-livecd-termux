#!/data/data/com.termux/files/usr/bin/python
"""Exercise packaged Settings and resolution rollback in a native GNOME session."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
from desktop import session_environment

PANELS = {'applications', 'background', 'display', 'keyboard', 'mouse',
          'multitasking', 'notifications', 'search', 'sound', 'universal-access'}


def resolution_test():
    import importlib.util
    helper = Path(os.environ['PREFIX']) / 'libexec/gnome-control-center/resolution.py'
    spec = importlib.util.spec_from_file_location('resolution', helper)
    resolution = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resolution)
    original = resolution.preferences()

    def wait_line(worker):
        assert select.select([worker.stdout], [], [], 15)[0], 'Resolution helper stalled'
        line = worker.stdout.readline().strip()
        assert line == 'applied', line
        time.sleep(1)
        query = subprocess.check_output(['xrandr', '--query'], text=True)
        assert 'current 1280 x 720' in query, query

    def worker():
        return subprocess.Popen([sys.executable, str(helper), '--watchdog', '1280x720'],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    try:
        child = worker()
        try:
            wait_line(child)
            child.stdin.close()
            child.wait(timeout=15)
            assert child.returncode == 0, child.stderr.read()
            assert resolution.preferences() == original, 'Closing dialog did not restore preferences'
        finally:
            if child.poll() is None:
                child.stdin.close()
                child.wait(timeout=30)
        print('PASS: cancel/parent pipe loss restores the previous resolution')

        child = worker()
        try:
            wait_line(child)
            child.wait(timeout=35)
            assert child.returncode == 0, child.stderr.read()
            assert resolution.preferences() == original, 'Confirmation timeout did not restore preferences'
        finally:
            child.stdin.close()
            if child.poll() is None:
                child.wait(timeout=30)
        print('PASS: unanswered confirmation restores the previous resolution')

        child = worker()
        try:
            wait_line(child)
            child.stdin.write('keep\n')
            child.stdin.flush()
            child.stdin.close()
            child.wait(timeout=15)
            assert child.returncode == 0, child.stderr.read()
            assert resolution.preferences() == resolution.target('1280x720', original)
        finally:
            if child.poll() is None:
                child.stdin.close()
                child.wait(timeout=30)
        print('PASS: explicit confirmation keeps the requested resolution')
    finally:
        resolution.write_preferences(original)
        time.sleep(1)


def notification_test():
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def call(method, parameters=None, result=None):
        return bus.call_sync('org.freedesktop.Notifications', '/org/freedesktop/Notifications',
                             'org.freedesktop.Notifications', method, parameters,
                             GLib.VariantType.new(result) if result else None,
                             Gio.DBusCallFlags.NONE, 5000, None).unpack()
    info = call('GetServerInformation')
    assert info[0] == 'gnome-shell', info
    capabilities = call('GetCapabilities')[0]
    assert 'body' in capabilities and 'actions' in capabilities, capabilities
    settings = Gio.Settings.new('org.gnome.desktop.notifications')
    previous = settings.get_user_value('show-banners')
    try:
        # Verify Shell accepts desktop notifications with Do Not Disturb both
        # enabled and disabled. Visual banner policy needs UI acceptance too.
        for enabled in (False, True):
            settings.set_boolean('show-banners', enabled)
            Gio.Settings.sync()
            time.sleep(0.3)
            ident = call('Notify', GLib.Variant('(susssasa{sv}i)',
                         ('Settings acceptance', 0, 'preferences-system-notifications-symbolic',
                          'Desktop notification test', 'GNOME session notification; no Android bridge.',
                          [], {'transient': GLib.Variant('b', True)}, 1500)), '(u)')[0]
            assert ident > 0
            call('CloseNotification', GLib.Variant('(u)', (ident,)))
    finally:
        if previous is None:
            settings.reset('show-banners')
        else:
            settings.set_value('show-banners', previous)
        Gio.Settings.sync()
    print('PASS: GNOME Shell owns desktop notifications and accepts them with either DND setting')


def panels_test():
    listed = subprocess.check_output(['gnome-control-center', '--list'], text=True)
    found = {line.strip() for line in listed.splitlines()} & PANELS
    assert found == PANELS, listed
    assert not ({'power', 'network', 'wifi', 'bluetooth', 'wwan', 'users'} &
                {line.strip() for line in listed.splitlines()}), listed
    print('PASS: package exposes its declared panel inventory and excludes device power/networking/users')


def main():
    if '--session' not in sys.argv:
        subprocess.run([sys.executable, __file__, '--session', *sys.argv[1:]],
                       env=session_environment(), check=True)
        return
    panels_test()
    notification_test()
    if '--resolution' in sys.argv:
        resolution_test()


if __name__ == '__main__':
    main()
