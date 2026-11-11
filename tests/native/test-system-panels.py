#!/data/data/com.termux/files/usr/bin/python
"""Check the System and Privacy Settings panels in a private Xvfb session.

Settings are read through AT-SPI and changed in a temporary profile. The live
desktop's display, buses and settings are not used. --sshd also turns Termux's
real sshd listener off and on again with the Secure Shell switch: established
SSH sessions survive, but new connections fail until it is back.
"""
import argparse
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time

SSHD_PID = Path('/data/data/com.termux/files/usr/var/run/sshd.pid')


def wait_for(check, timeout=20, message='condition'):
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            return result
        assert time.monotonic() < deadline, f'Timed out waiting for {message}'
        time.sleep(0.2)


def getprop(name):
    return subprocess.check_output(['getprop', name], text=True).strip()


def sshd_running():
    try:
        pid = int(SSHD_PID.read_text())
        return Path(f'/proc/{pid}/comm').read_text().strip() == 'sshd'
    except (OSError, ValueError):
        return False


def sshd_port_open():
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(('127.0.0.1', 8022)) == 0


def private_accessibility_bus(directory):
    """Serve org.a11y.Bus on the private session bus, pointing at a private AT-SPI bus."""
    from gi.repository import Gio, GLib
    template = Path(os.environ['PREFIX']) / 'share/defaults/at-spi2/accessibility.conf'
    address = f'unix:path={directory}/a11y-bus'
    config = directory / 'accessibility.conf'
    config.write_text(template.read_text().replace('unix:dir=/tmp', address))
    daemon = subprocess.Popen(['dbus-daemon', '--nofork', f'--config-file={config}'])
    wait_for(lambda: (directory / 'a11y-bus').exists(), 10, 'the AT-SPI bus')
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    interface = Gio.DBusNodeInfo.new_for_xml(
        '<node><interface name="org.a11y.Bus"><method name="GetAddress">'
        '<arg type="s" direction="out"/></method></interface></node>').interfaces[0]
    connection.register_object(
        '/org/a11y/bus', interface,
        lambda _c, _s, _p, _i, _m, _a, call: call.return_value(GLib.Variant('(s)', (address,))),
        None, None)
    Gio.bus_own_name_on_connection(connection, 'org.a11y.Bus', Gio.BusNameOwnerFlags.NONE, None, None)
    threading.Thread(target=GLib.MainLoop().run, daemon=True).start()
    os.environ['AT_SPI_BUS_ADDRESS'] = address
    subprocess.run(['xprop', '-root', '-f', 'AT_SPI_BUS', '8s', '-set', 'AT_SPI_BUS', address], check=True)
    return daemon


class Settings:
    """A gnome-control-center process opened on one panel, inspected through AT-SPI."""

    def __init__(self, panel, log):
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        self.Atspi = Atspi
        self.process = subprocess.Popen(['gnome-control-center', *panel.split()], stdout=log, stderr=log,
                                        env={**os.environ, 'G_DEBUG': 'fatal-criticals'})
        self.app = wait_for(self._application, 20, f'the {panel} panel')

    def _application(self):
        assert self.process.poll() is None, 'Settings exited'
        desktop = self.Atspi.get_desktop(0)
        for index in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(index)
            if app is not None and app.get_process_id() == self.process.pid and app.get_child_count():
                return app
        return None

    def nodes(self, node=None, depth=0):
        node = node or self.app
        yield node
        if depth < 60:
            for index in range(node.get_child_count()):
                child = node.get_child_at_index(index)
                if child is not None:
                    yield from self.nodes(child, depth + 1)

    def showing(self, node):
        return node.get_state_set().contains(self.Atspi.StateType.SHOWING)

    def texts(self):
        found = []
        for node in self.nodes():
            if self.showing(node):
                found += [text for text in (node.get_name(), node.get_description()) if text]
        return found

    def find(self, name, role=None, actionable=False):
        # Rows such as AdwSwitchRow contain an inner control with the same name and role.
        def match():
            for node in self.nodes():
                if (node.get_name() == name and self.showing(node) and role in (None, node.get_role_name())
                        and (not actionable or node.get_n_actions() > 0)):
                    return node
            return None
        return wait_for(match, 10, f'{role or "node"} {name!r}')

    def toggle(self, name):
        self.find(name, 'switch', actionable=True).do_action(0)

    def click(self, name, role='button'):
        # List rows expose no AT-SPI action. Without a window manager the
        # window sits at the private screen's origin, so click the row there.
        extents = self.find(name, role).get_extents(self.Atspi.CoordType.WINDOW)
        subprocess.run(['xdotool', 'mousemove', '--sync', str(extents.x + extents.width // 2),
                        str(extents.y + extents.height // 2), 'click', '1'], check=True, timeout=10)

    def checked(self, node):
        return node.get_state_set().contains(self.Atspi.StateType.CHECKED)

    def close(self):
        subprocess.run(['gapplication', 'action', 'org.gnome.Settings', 'quit'], timeout=10)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        assert self.process.returncode == 0, self.process.returncode


def about_test(log):
    from gi.repository import GLib
    vendor = getprop('ro.product.manufacturer')
    device = f'{vendor[:1].upper()}{vendor[1:]} {getprop("ro.product.model")}'
    def read(name):
        try:
            return Path(f'/sys/devices/soc0/{name}').read_text().strip()
        except OSError:
            return ''
    # The panel prefers soc0, which Exynos phones keep from apps, then Android's SoC properties.
    if read('machine'):
        soc = ' '.join(part for part in map(read, ('vendor', 'family', 'machine')) if part)
    else:
        soc = ' '.join(part for part in (getprop('ro.soc.manufacturer'), getprop('ro.soc.model')) if part)
    stat = os.statvfs(Path.home())
    expected = [f'Android {getprop("ro.build.version.release")}', device,
                f'{soc} × {os.sysconf("SC_NPROCESSORS_CONF")}',
                GLib.format_size(stat.f_blocks * stat.f_frsize)]
    settings = Settings('system about', log)
    try:
        texts = wait_for(lambda: all(value in settings.texts() for value in expected) and settings.texts(),
                         10, f'About values {expected}')
        assert 'Unknown' not in texts, texts
    finally:
        settings.close()
    print('PASS: About shows Android, the device, its SoC and data partition size', flush=True)


def datetime_test(log):
    from gi.repository import Gio, GLib
    now = GLib.DateTime.new_now_local()
    city = now.get_timezone().get_identifier().rsplit('/', 1)[-1].replace('_', ' ')
    zone = f'{now.get_timezone_abbreviation()} ({city})'
    clock = Gio.Settings.new('org.gnome.desktop.interface')
    settings = Settings('system datetime', log)
    try:
        assert zone in wait_for(settings.texts, 10, 'Date & Time contents'), settings.texts()
        for title in ('Date & Time', 'Time Zone'):
            row = settings.find(title, 'button')
            labels = [node.get_name() for node in settings.nodes(row)]
            assert 'Set in Android settings' in labels, labels
            assert not row.get_state_set().contains(settings.Atspi.StateType.SENSITIVE), title
        assert not any(text.startswith('Automatic') for text in settings.texts()), settings.texts()
        weekday = clock.get_boolean('clock-show-weekday')
        settings.toggle('Week Day')
        wait_for(lambda: clock.get_boolean('clock-show-weekday') != weekday, 10, 'clock-show-weekday')
    finally:
        settings.close()
    print(f'PASS: Date & Time shows Android\'s {zone} read-only and changes clock preferences', flush=True)


def privacy_test(log, directory):
    from gi.repository import Gio
    privacy = Gio.Settings.new('org.gnome.desktop.privacy')
    settings = Settings('privacy', log)
    try:
        rows = {node.get_name() for node in settings.nodes() if settings.showing(node)}
        for absent in ('Screen Lock', 'Location', 'Cameras', 'Diagnostics', 'Thunderbolt', 'Device Security'):
            assert absent not in rows, absent
        settings.find('File History & Trash', 'button')
    finally:
        settings.close()
    settings = Settings('privacy usage', log)
    try:
        texts = wait_for(lambda: 'File History Duration' in settings.texts() and settings.texts(),
                         10, 'File History & Trash')
        assert 'Automatically Empty Trash' not in texts and 'Delete Temporary Files…' not in texts, texts
        enabled = privacy.get_boolean('remember-recent-files')
        settings.toggle('File History')
        wait_for(lambda: privacy.get_boolean('remember-recent-files') != enabled, 10, 'remember-recent-files')
        # The trash is in this test's private data directory.
        trash = Path(os.environ['XDG_DATA_HOME']) / 'Trash/files'
        victim = directory / 'trash-me.txt'
        victim.write_text('test')
        subprocess.run(['gio', 'trash', str(victim)], check=True, timeout=20)
        assert [path.name for path in trash.iterdir()] == ['trash-me.txt'], list(trash.iterdir())
        settings.click('Empty Trash…')
        settings.find('Empty Trash', 'button', actionable=True).do_action(0)
        wait_for(lambda: not any(trash.iterdir()), 15, 'the trash to be emptied')
    finally:
        settings.close()
    print('PASS: Privacy offers File History & Trash only; its switch changes remember-recent-files '
          'and Empty Trash empties the trash', flush=True)

    # GTK reads file history preferences from XSettings, not GSettings.
    bridge_directory = directory / 'xsettings'
    bridge_directory.mkdir()
    bridge = bridge_directory / 'xsettings.py'
    bridge.write_text((Path(__file__).parents[2] / 'src/native/xsettings.py').read_text())
    probe = ('import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk; Gtk.init(); '
             's = Gtk.Settings.get_default(); '
             'print(int(s.props.gtk_recent_files_enabled), s.props.gtk_recent_files_max_age)')
    daemon = subprocess.Popen([sys.executable, str(bridge)], stdout=log, stderr=log, start_new_session=True)
    try:
        for enabled, age in ((False, 7), (True, 30)):
            privacy.set_boolean('remember-recent-files', enabled)
            privacy.set_int('recent-files-max-age', age)
            Gio.Settings.sync()
            expected = f'{int(enabled)} {age}'
            wait_for(lambda: subprocess.check_output([sys.executable, '-c', probe], text=True).strip() == expected,
                     15, f'GTK recent-file settings {expected}')
    finally:
        os.killpg(daemon.pid, 15)
        daemon.wait(timeout=10)
    print('PASS: the XSettings bridge passes file history preferences to GTK', flush=True)


def secure_shell_test(log, toggle):
    addresses = set(subprocess.check_output(['ip', '-4', '-o', 'addr', 'show'], text=True).split())
    running = sshd_running()
    settings = Settings('system', log)
    try:
        settings.click('Secure Shell')
        command = wait_for(lambda: next((text for text in settings.texts() if text.startswith('ssh -p ')), None),
                           10, 'the SSH login command')
        port, address = command.split()[2:]
        assert port == '8022', command
        assert any(item.startswith(address + '/') for item in addresses) or address == 'localhost', command
        switch = settings.find('Secure Shell', 'switch', actionable=True)
        assert settings.checked(switch) == running, (settings.checked(switch), running)
        print(f'PASS: Secure Shell shows {command!r} and sshd running={running}', flush=True)
        if not toggle:
            return
        assert running, 'Start sshd before testing the Secure Shell switch'
        try:
            switch.do_action(0)
            wait_for(lambda: not sshd_running() and not sshd_port_open(), 10, 'sshd to stop')
            switch.do_action(0)
            wait_for(lambda: sshd_running() and sshd_port_open(), 10, 'sshd to start')
            wait_for(lambda: settings.checked(switch), 10, 'the switch to show sshd running')
        finally:
            if not sshd_running():
                subprocess.run(['sshd'], check=True)
        print('PASS: the Secure Shell switch stops and restarts Termux sshd', flush=True)
    finally:
        settings.close()


def inside(directory, toggle_sshd):
    with open(directory / 'settings.log', 'w+') as log:
        screen = daemon = None
        try:
            read_fd, write_fd = os.pipe()
            # -noreset: Xvfb's reset after its last client leaves cannot reopen its listeners here.
            screen = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x720x24',
                                       '-nolisten', 'tcp', '-noreset'], pass_fds=(write_fd,), stdout=log, stderr=log)
            os.close(write_fd)
            with os.fdopen(read_fd) as ready:
                assert select.select([ready], [], [], 15)[0], 'Xvfb did not become ready'
                os.environ['DISPLAY'] = ':' + ready.readline().strip()
            time.sleep(0.5)
            assert screen.poll() is None, f'Xvfb could not listen on {os.environ["DISPLAY"]}'
            daemon = private_accessibility_bus(directory)
            about_test(log)
            datetime_test(log)
            privacy_test(log, directory)
            secure_shell_test(log, toggle_sshd)
            log.seek(0)
            output = log.read()
            assert 'CRITICAL' not in output, output[-6000:]
        except BaseException:
            log.flush()
            log.seek(0)
            print(log.read()[-12000:], file=sys.stderr)
            raise
        finally:
            for child in (daemon, screen):
                if child is not None and child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--sshd', action='store_true', help='also stop and restart the real sshd listener')
    args = parser.parse_args()
    if args.inside:
        inside(args.inside, args.sshd)
        return
    sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
    from desktop import session_environment
    env = session_environment()
    with tempfile.TemporaryDirectory(prefix='livecd-system-panels-') as name:
        for key in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR'):
            path = Path(name) / key.lower()
            path.mkdir(mode=0o700)
            env[key] = str(path)
        for key in ('DBUS_SESSION_BUS_ADDRESS', 'DCONF_PROFILE', 'LD_PRELOAD', 'AT_SPI_BUS_ADDRESS'):
            env.pop(key, None)
        env.update(GTK_A11Y='atspi', GSK_RENDERER='cairo', GSETTINGS_BACKEND='dconf')
        command = ['dbus-run-session', '--', sys.executable, __file__, '--inside', name]
        if args.sshd:
            command.append('--sshd')
        subprocess.run(command, env=env, check=True, timeout=240)


if __name__ == '__main__':
    main()
