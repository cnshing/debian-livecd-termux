#!/data/data/com.termux/files/usr/bin/python
"""Exercise packaged Settings and resolution rollback in a native GNOME session."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
from desktop import session_environment

PANELS = {'applications', 'background', 'display', 'keyboard', 'mouse',
          'multitasking', 'notifications', 'search', 'sound', 'universal-access',
          'wellbeing'}


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


def wellbeing_test():
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def state():
        return bus.call_sync('org.gnome.Shell', '/org/gnome/Shell/ScreenTime',
                             'org.freedesktop.DBus.Properties', 'Get',
                             GLib.Variant('(ss)', ('org.gnome.Shell.ScreenTime', 'State')),
                             GLib.VariantType.new('(v)'), Gio.DBusCallFlags.NONE,
                             5000, None).unpack()[0]
    def wait_state(expected):
        deadline = time.monotonic() + 10
        while state() != expected:
            assert time.monotonic() < deadline, f'Shell break state {state()}, expected {expected}'
            time.sleep(0.2)
    settings = Gio.Settings.new('org.gnome.desktop.break-reminders')
    previous = settings.get_user_value('selected-breaks')
    try:
        # The panel's schedule switch writes these keys; Shell's break manager
        # is the backend that must react (0 disabled, 1 waiting for a break).
        settings.set_strv('selected-breaks', [])
        Gio.Settings.sync()
        wait_state(0)
        settings.set_strv('selected-breaks', ['movement'])
        Gio.Settings.sync()
        wait_state(1)
    finally:
        if previous is None:
            settings.reset('selected-breaks')
        else:
            settings.set_value('selected-breaks', previous)
        Gio.Settings.sync()
    wait_state(1 if settings.get_strv('selected-breaks') else 0)
    history = Path(GLib.get_user_data_dir()) / 'gnome-shell/session-active-history.json'
    if Gio.Settings.new('org.gnome.desktop.screen-time-limits').get_boolean('history-enabled'):
        entries = json.loads(history.read_text())
        assert entries and {'oldState', 'newState', 'wallTimeSecs'} <= entries[-1].keys(), entries
    print('PASS: Shell break manager follows the Wellbeing schedule and its screen time history is readable')


def panels_test():
    listed = subprocess.check_output(['gnome-control-center', '--list'], text=True)
    found = {line.strip() for line in listed.splitlines()} & PANELS
    assert found == PANELS, listed
    assert not ({'power', 'network', 'wifi', 'bluetooth', 'wwan', 'users'} &
                {line.strip() for line in listed.splitlines()}), listed
    print('PASS: package exposes its declared panel inventory and excludes device power/networking/users')


def panels_ui_test():
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    names = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                          'org.freedesktop.DBus', 'ListNames', None, None,
                          Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    assert 'org.gnome.Settings' not in names, 'Close Settings before the optional panel UI test'
    settings = Gio.Settings.new('org.gnome.Settings')
    original = {key: settings.get_user_value(key) for key in ('last-panel', 'window-state')}
    try:
        for panel in sorted(PANELS):
            with tempfile.TemporaryFile(mode='w+') as log:
                child = subprocess.Popen(['gnome-control-center', panel],
                                         env={**os.environ, 'G_DEBUG': 'fatal-criticals'},
                                         stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        context = GLib.MainContext.default()
                        while context.pending():
                            context.iteration(False)
                        if child.poll() is not None:
                            break
                        if settings.get_string('last-panel') == panel:
                            # Allow asynchronous template/service initialization.
                            time.sleep(1)
                            assert child.poll() is None
                            break
                        time.sleep(0.1)
                    assert settings.get_string('last-panel') == panel
                    assert child.poll() is None
                    subprocess.run(['gapplication', 'action', 'org.gnome.Settings', 'quit'],
                                   check=True, timeout=10)
                    child.wait(timeout=10)
                    log.seek(0)
                    output = log.read()
                    assert child.returncode == 0, (child.returncode, output)
                    assert 'CRITICAL' not in output and 'ERROR' not in output, output
                    print(f'PASS: {panel} opens with fatal GLib criticals enabled')
                except BaseException:
                    log.seek(0)
                    print(f'{panel}: exit={child.poll()}, selected={settings.get_string("last-panel")}',
                          file=sys.stderr)
                    print(log.read(), file=sys.stderr, flush=True)
                    raise
                finally:
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=10)
    finally:
        for key, value in original.items():
            if value is None:
                settings.reset(key)
            else:
                settings.set_value(key, value)
        Gio.Settings.sync()


def main():
    if '--session' not in sys.argv:
        subprocess.run([sys.executable, __file__, '--session', *sys.argv[1:]],
                       env=session_environment(), check=True)
        return
    panels_test()
    notification_test()
    wellbeing_test()
    if '--resolution' in sys.argv:
        resolution_test()
    if '--panels-ui' in sys.argv:
        panels_ui_test()


if __name__ == '__main__':
    main()
