#!/data/data/com.termux/files/usr/bin/python
"""Which applications get a generic icon in the dock? Run inside the native desktop.

Usage: livecd-native exec -- python test-window-icons.py [--already-running | NAME ...]

GNOME Shell shows an application's icon only when it can match the window to a desktop entry.
Its order is _GTK_APPLICATION_ID, then StartupWMClass, then a desktop file named after the
window class. A window with no match becomes a nameless app with the generic icon, even when the
icon files are installed. Each application here opens one window with a scratch profile. A wrapper
can change a window's class, so test what a menu entry actually runs, not only the bare program.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio  # noqa: E402

PREFIX = Path(os.environ['PREFIX'])
SCRATCH = Path(tempfile.mkdtemp(prefix='window-icons-', dir=os.environ['TMPDIR']))
(SCRATCH / 'firefox').mkdir()
APPLICATIONS = {
    'Firefox': ['firefox', '--profile', str(SCRATCH / 'firefox'), '--no-remote', 'about:blank'],
    'Code OSS': ['code-oss', '--user-data-dir=' + str(SCRATCH / 'code-oss'), '--new-window'],
    'Nautilus': ['nautilus', '--new-window', str(SCRATCH)],
    'Ghostty': ['ghostty'],
    'Ghostty menu entry': ['gtk-launch', 'com.mitchellh.ghostty'],
    'mpv': ['mpv', '--force-window=yes', '--idle=yes', '--vo=x11', '--ao=null', '--no-config'],
    'Mission Center': ['missioncenter'],
    'Mixtapes': ['env', 'XDG_DATA_HOME=' + str(SCRATCH / 'data'), 'XDG_CACHE_HOME=' + str(SCRATCH / 'cache'), 'mixtapes'],
    'Chromium': ['chromium-browser', '--user-data-dir=' + str(SCRATCH / 'chromium'), '--no-first-run', 'about:blank'],
    'Google Chrome': ['google-chrome', '--user-data-dir=' + str(SCRATCH / 'chrome'), '--no-first-run', 'about:blank'],
    'Mixer': ['pavucontrol'],
    'LibreOffice Writer': ['libreoffice', '-env:UserInstallation=' + (SCRATCH / 'office').as_uri(), '--writer', '--norestore'],
}


def prop(window, name):
    output = subprocess.run(['xprop', '-id', window, name], capture_output=True, text=True).stdout
    return [] if 'not found' in output or '=' not in output else json.loads('[' + output.split('=', 1)[1].strip() + ']')


def is_desktop(window):
    """DING's full-screen window has no dock entry to match."""
    output = subprocess.run(['xprop', '-id', window, '_NET_WM_WINDOW_TYPE'], capture_output=True, text=True).stdout
    return 'WINDOW_TYPE_DESKTOP' in output


def windows():
    found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '.'], capture_output=True, text=True)
    return {w for w in found.stdout.split() if prop(w, 'WM_CLASS') and not is_desktop(w)}


def entries():
    return [a for a in Gio.AppInfo.get_all() if isinstance(a, Gio.DesktopAppInfo)]


def has_entry(apps, name):
    return any(app.get_id() == name for app in apps)


def match(window, apps):
    """The desktop entry GNOME Shell's window tracker would choose, and by which rule."""
    gtk_id = prop(window, '_GTK_APPLICATION_ID')
    if gtk_id and has_entry(apps, gtk_id[0] + '.desktop'):
        return gtk_id[0] + '.desktop', '_GTK_APPLICATION_ID'
    names = prop(window, 'WM_CLASS')
    for name in names:
        for app in apps:
            if app.get_startup_wm_class() == name:
                return app.get_id(), 'StartupWMClass'
    for name in names:
        for candidate in (name, name.lower().replace(' ', '-')):
            if has_entry(apps, candidate + '.desktop'):
                return candidate + '.desktop', 'class name'
    return None, 'none'


def report(label, window, apps):
    entry, rule = match(window, apps)
    print('%-20s class=%-42s %s' % (label, ','.join(prop(window, 'WM_CLASS')),
        'GENERIC ICON: no matching entry' if entry is None else '%s by %s' % (entry, rule)))
    return entry is not None


apps = entries()
matched, total = 0, 0
before = windows()
for window in sorted(before):
    total += 1
    matched += report('(already open)', window, apps)
if '--already-running' not in sys.argv:
    for label, command in APPLICATIONS.items():
        if sys.argv[1:] and label not in sys.argv[1:]:
            continue
        if not shutil.which(command[0]):
            print('%-20s not installed' % label)
            continue
        current = windows()
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        new = set()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and not new:
            time.sleep(1)
            new = windows() - current
        if not new:
            print('%-20s no window within 45 s' % label)
        else:
            time.sleep(2)  # Some applications set their class after mapping.
            total += 1
            matched += report(label, sorted(windows() - current)[0], apps)
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
        for window in windows() - current:
            subprocess.run(['xdotool', 'windowquit', window], check=False)
        time.sleep(1)
print('matched %d of %d windows' % (matched, total))
shutil.rmtree(SCRATCH, ignore_errors=True)
