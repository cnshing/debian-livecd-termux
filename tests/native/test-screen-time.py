#!/data/data/com.termux/files/usr/bin/python
"""Test native screen-time limits in a private Xvfb/Shell session.

Requires Xvfb and the GNOME 48 runtime. The test enables Eval only in its private
Shell via a temporary resource overlay; it never changes the live Shell's mode,
settings or history. --overlay DIR can validate unpublished JS resource changes.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time


def wait_for(check, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError('Timed out waiting for screen-time state')


def notification_policies(bus, evaluate):
    from gi.repository import Gio, GLib
    schema = 'org.gnome.desktop.notifications'
    master = Gio.Settings.new(schema)
    app = Gio.Settings.new_with_path(schema + '.application',
                                     '/org/gnome/desktop/notifications/application/livecd-settings-policy-test/')
    def call(method, parameters):
        return bus.call_sync('org.freedesktop.Notifications', '/org/freedesktop/Notifications',
                             'org.freedesktop.Notifications', method, parameters, None,
                             Gio.DBusCallFlags.NONE, 5000, None).unpack()
    def tray():
        return evaluate("""({title: Main.messageTray._notification?.title ?? null,
            queued: Main.messageTray._notificationQueue.map(n => n.title),
            removed: Main.messageTray._notificationRemoved,
            sources: Main.messageTray.getSources().filter(s => s.title === 'Policy acceptance').map(s =>
                ({enabled: s.policy.enable, banners: s.policy.showBanners,
                  titles: s.notifications.map(n => n.title)}))})""")
    for enabled, app_banners, global_banners in [(True, True, True), (True, False, True),
                                                (True, True, False), (False, True, True)]:
        app.set_boolean('enable', enabled)
        app.set_boolean('show-banners', app_banners)
        master.set_boolean('show-banners', global_banners)
        Gio.Settings.sync()
        title = f'Policy {enabled}/{app_banners}/{global_banners}'
        ident = call('Notify', GLib.Variant('(susssasa{sv}i)',
                     ('Policy acceptance', 0, 'preferences-system-notifications-symbolic',
                      title, 'Desktop policy test', [],
                      {'desktop-entry': GLib.Variant('s', 'livecd-settings-policy-test'),
                       'transient': GLib.Variant('b', True)}, 0)))[0]
        if enabled and app_banners and global_banners:
            wait_for(lambda: tray()['title'] == title)
        elif enabled:
            wait_for(lambda: any(title in source['titles'] for source in tray()['sources']))
            current = tray()
            assert current['title'] != title and title not in current['queued'], current
            assert all(not source['banners'] for source in current['sources']), current
        else:
            current = tray()
            assert not current['sources'] and current['title'] != title and title not in current['queued'], current
        call('CloseNotification', GLib.Variant('(u)', (ident,)))
        try:
            wait_for(lambda: tray()['title'] != title or tray()['removed'])
        except AssertionError:
            print('Notification close state:', title, ident, tray(),
                  call('GetServerInformation', None), flush=True)
            raise
    master.set_boolean('show-banners', True)
    Gio.Settings.sync()
    print('PASS: GNOME banners, per-app banner suppression, Do Not Disturb and disabled apps', flush=True)


def inside(directory, panels_ui=False):
    from gi.repository import Gio, GLib
    screen = None
    shell = None
    with open(directory / 'shell.log', 'w+') as log:
        try:
            read_fd, write_fd = os.pipe()
            screen = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd),
                                       '-screen', '0', '1280x720x24', '-nolisten', 'tcp'],
                                      pass_fds=(write_fd,), stdout=log, stderr=log)
            os.close(write_fd)
            with os.fdopen(read_fd) as ready:
                assert select.select([ready], [], [], 15)[0], 'Xvfb did not become ready'
                display = ready.readline().strip()
                assert display.isdecimal(), display
            os.environ['DISPLAY'] = ':' + display
            settings = Gio.Settings.new('org.gnome.desktop.screen-time-limits')
            settings.set_boolean('history-enabled', False)
            settings.set_boolean('daily-limit-enabled', False)
            Gio.Settings.new('org.gnome.desktop.lockdown').set_boolean('disable-lock-screen', True)
            Gio.Settings.new('org.gnome.desktop.session').set_uint('idle-delay', 0)
            Gio.Settings.new('org.gnome.shell').set_boolean('disable-user-extensions', True)
            Gio.Settings.new('org.gnome.desktop.interface').set_boolean('enable-animations', False)
            Gio.Settings.sync()
            fixture = Path(os.environ['XDG_DATA_HOME']) / 'applications/livecd-settings-policy-test.desktop'
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text('[Desktop Entry]\nName=Policy acceptance\nExec=true\nType=Application\nX-GNOME-UsesNotifications=true\n')
            shell = subprocess.Popen(['gnome-shell', '--x11'], cwd=directory, stdout=log, stderr=log)
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

            def evaluate(code):
                assert shell.poll() is None, 'Private Shell exited'
                result = bus.call_sync('org.gnome.Shell', '/org/gnome/Shell', 'org.gnome.Shell',
                                       'Eval', GLib.Variant('(s)', (code,)),
                                       GLib.VariantType.new('(bs)'), Gio.DBusCallFlags.NONE,
                                       5000, None).unpack()
                assert result[0], result[1]
                return json.loads(result[1])

            def ready():
                try:
                    return evaluate('Main.timeLimitsManager !== null')
                except GLib.Error:
                    return False
            wait_for(ready, 30)
            notification_policies(bus, evaluate)

            def state():
                return evaluate('''({state: Main.timeLimitsManager.state,
                    active: Main.timeLimitsManager._userState,
                    idle: Main.timeLimitsManager._loginUser?.IdleHint,
                    grayscale: Main.timeLimitsDispatcher._desaturationEffect?.enabled ?? false,
                    factor: Main.timeLimitsDispatcher._desaturationEffect?.factor ?? 0,
                    notice: Main.timeLimitsDispatcher._notificationSource?._notification?.title ?? null})''')

            def input_event():
                subprocess.run(['xdotool', 'mousemove', '100', '100', 'key', 'F13'],
                               check=True, stdout=log, stderr=log, timeout=10)

            input_event()
            settings.set_boolean('history-enabled', True)
            Gio.Settings.sync()
            wait_for(lambda: state().get('active') == 1)
            print('PASS: screen-time state machine initializes without logind', flush=True)

            assert settings.set_uint('daily-limit-seconds', 10)
            settings.set_boolean('grayscale', True)
            settings.set_boolean('daily-limit-enabled', True)
            Gio.Settings.sync()
            wait_for(lambda: state()['state'] == 2)
            wait_for(lambda: state()['grayscale'] and state()['factor'] > 0.9)
            assert state()['notice'], state()
            print('PASS: a daily limit generates a notification and applies grayscale', flush=True)
            settings.set_boolean('grayscale', False)
            Gio.Settings.sync()
            wait_for(lambda: not state()['grayscale'])
            settings.set_boolean('daily-limit-enabled', False)
            Gio.Settings.sync()
            wait_for(lambda: state()['state'] == 1)
            print('PASS: disabling grayscale and the daily limit removes their effects', flush=True)

            input_event()
            print('Waiting for the 60-second desktop inactivity threshold…', flush=True)
            wait_for(lambda: state().get('idle') is True and state()['active'] == 0, 70)
            history = Path(os.environ['XDG_DATA_HOME']) / 'gnome-shell/session-active-history.json'
            wait_for(lambda: history.exists() and json.loads(history.read_text())[-1]['newState'] == 0)
            print('PASS: idle time is recorded as inactive despite idle-delay=0', flush=True)
            input_event()
            wait_for(lambda: state().get('idle') is False and state()['active'] == 1)
            wait_for(lambda: json.loads(history.read_text())[-1]['newState'] == 1)
            print('PASS: input resumes screen-time accounting', flush=True)
            if panels_ui:
                subprocess.run([sys.executable, str(Path(__file__).with_name('test-settings.py')),
                                '--session', '--panels-ui'], check=True, timeout=90)
        except BaseException:
            log.flush()
            log.seek(0)
            print(log.read()[-18000:], file=sys.stderr)
            raise
        finally:
            for child in (shell, screen):
                if child is not None and child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)


@contextmanager
def relocated_frames(runtime, prefix):
    """Provide Mutter's build-tree fallback while testing an extracted package."""
    if not runtime or (Path(prefix) / 'opt/gnome-48/libexec/mutter-x11-frames').exists():
        yield
        return
    # Shell changes directory to the real home directory on startup. Reserve
    # its fallback path exclusively, never replacing an existing user file.
    frames = Path.home() / 'src/frames'
    created = []
    link = frames / 'mutter-x11-frames'
    linked = False
    try:
        for directory in (frames.parent, frames):
            if not directory.exists():
                directory.mkdir()
                created.append(directory)
        link.symlink_to(runtime / 'libexec/mutter-x11-frames')
        linked = True
        yield
    finally:
        if linked:
            link.unlink()
        for directory in reversed(created):
            directory.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--overlay', type=Path)
    parser.add_argument('--runtime', type=Path, help='Installed or extracted GNOME runtime to validate')
    parser.add_argument('--panels-ui', action='store_true')
    args = parser.parse_args()
    if args.inside:
        inside(args.inside, args.panels_ui)
        return
    sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
    from desktop import session_environment
    env = session_environment()
    runtime = args.runtime.resolve() if args.runtime else None
    if runtime:
        prefix = env['PREFIX']
        env.update(PATH=f'{runtime}/bin:{prefix}/bin:/system/bin',
                   LD_LIBRARY_PATH=f'{runtime}/lib:{runtime}/lib/mutter-16:{runtime}/lib/gnome-shell:{prefix}/lib',
                   GI_TYPELIB_PATH=f'{runtime}/lib/gjs/girepository-1.0:{runtime}/lib/girepository-1.0:{runtime}/lib/mutter-16:{runtime}/lib/gnome-shell:{runtime}/lib/gnome-shell/girepository-1.0:{prefix}/lib/girepository-1.0',
                   GSETTINGS_SCHEMA_DIR=str(runtime / 'share/glib-2.0/schemas'),
                   GNOME_SHELL_DATADIR=str(runtime / 'share/gnome-shell'),
                   GNOME_SHELL_LIBDIR=str(runtime / 'lib/gnome-shell'),
                   XDG_DATA_DIRS=f'{runtime}/share:{prefix}/share')
        subprocess.run(['glib-compile-schemas', str(runtime / 'share/glib-2.0/schemas')],
                       env=env, check=True)
    with tempfile.TemporaryDirectory(prefix='livecd-screen-time-') as name:
        directory = Path(name)
        overlay = directory / 'resources'
        if args.overlay:
            shutil.copytree(args.overlay, overlay)
        (overlay / 'ui').mkdir(parents=True, exist_ok=True)
        # Termux's gresource CLI lacks ELF support; load Shell's registered
        # resources through its GI namespace instead.
        extract = """const Shell = imports.gi.Shell; void Shell.Global;
print(imports.byteArray.toString(imports.gi.Gio.resources_lookup_data(
    '/org/gnome/shell/ui/main.js', 0).get_data()));"""
        source = subprocess.check_output(['gjs', '-c', extract], text=True, env=env)
        assert 'export async function start() {' in source
        (overlay / 'ui/main.js').write_text(source.replace(
            'export async function start() {',
            'export async function start() {\n    global.context.unsafe_mode = true;'))
        for key, subdir in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                            ('XDG_CACHE_HOME', 'cache'), ('XDG_STATE_HOME', 'state'),
                            ('XDG_RUNTIME_DIR', 'run')]:
            path = directory / subdir
            path.mkdir(mode=0o700)
            env[key] = str(path)
        if runtime:
            # Activation files and small GJS launchers contain their installed
            # prefix. Relocate only test copies; the compiled libraries and JS
            # resources under acceptance are never rewritten.
            installed = str(Path(env['PREFIX']) / 'opt/gnome-48')
            services = Path(env['XDG_DATA_HOME']) / 'dbus-1/services'
            scripts = directory / 'services'
            services.mkdir(parents=True)
            scripts.mkdir()
            for service in (runtime / 'share/dbus-1/services').glob('*.service'):
                text = service.read_text().replace(installed, str(runtime))
                script = runtime / 'share/gnome-shell' / service.stem
                if script.is_file():
                    copy = scripts / script.name
                    copy.write_text(script.read_text().replace(installed, str(runtime)))
                    text = text.replace(str(script), str(copy))
                (services / service.name).write_text(text)
        for key in ('DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER', 'DESKTOP_AUTOSTART_ID',
                    'GALLIUM_DRIVER', 'MESA_LOADER_DRIVER_OVERRIDE', 'VK_ICD_FILENAMES',
                    'VK_DRIVER_FILES', 'LD_PRELOAD', 'DCONF_PROFILE'):
            env.pop(key, None)
        env.update(G_RESOURCE_OVERLAYS='/org/gnome/shell=' + str(overlay),
                   LIBGL_ALWAYS_SOFTWARE='1', GALLIUM_DRIVER='llvmpipe', GSK_RENDERER='cairo')
        command = ['dbus-run-session', '--', sys.executable, __file__, '--inside', name]
        if args.panels_ui:
            command.append('--panels-ui')
        with relocated_frames(runtime, env['PREFIX']):
            subprocess.run(command, env=env, check=True, timeout=210)


if __name__ == '__main__':
    main()
