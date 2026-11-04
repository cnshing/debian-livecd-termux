#!/data/data/com.termux/files/usr/bin/python
"""Run in the native desktop: verify delayed and window captures from the package."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf

sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
from desktop import session_environment


def verify(env):
    entry = Path(env['PREFIX']) / 'share/applications/org.gnome.Screenshot.desktop'
    assert 'Exec=gnome-screenshot --interactive' in entry.read_text()
    subprocess.run(['gnome-screenshot', '--version'], env=env, check=True)
    with tempfile.TemporaryDirectory(prefix='livecd-screenshot-') as directory:
        def capture(name, *options):
            path = Path(directory) / (name + '.png')
            before = time.monotonic()
            result = subprocess.run(['gnome-screenshot', *options, '--file=' + str(path)],
                                    env=env, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            elapsed = time.monotonic() - before
            image = GdkPixbuf.Pixbuf.new_from_file(str(path))
            assert image.get_width() > 0 and image.get_height() > 0
            assert len(set(image.get_pixels())) > 16, 'Capture is blank or nearly blank'
            print(f'{name}: {image.get_width()}x{image.get_height()}, {elapsed:.2f}s')
            return elapsed, image

        elapsed, full = capture('delayed-screen', '--delay=3')
        assert elapsed >= 2.8, 'Requested screenshot delay was ignored'
        _, window = capture('active-window', '--window')
        assert window.get_width() <= full.get_width()
        assert window.get_height() <= full.get_height()
    print('PASS: packaged launcher, delayed capture and active-window capture')


def main():
    env = session_environment()
    title = f'LiveCD Screenshot Test {os.getpid()}'
    fixture = subprocess.Popen([sys.executable, '-c', """
import gi, sys
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
window = Gtk.Window(title=sys.argv[1])
window.set_default_size(400, 300)
window.add(Gtk.Label(label='GNOME Screenshot capture verification'))
window.show_all()
Gtk.main()
""", title], env=env)
    try:
        for _ in range(100):
            found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', title],
                                   env=env, capture_output=True, text=True)
            if found.returncode == 0:
                wid = found.stdout.splitlines()[-1]
                subprocess.run(['xdotool', 'windowactivate', '--sync', wid],
                               env=env, check=True, timeout=10)
                break
            if fixture.poll() is not None:
                raise RuntimeError('Capture fixture failed to open')
            time.sleep(0.1)
        else:
            raise RuntimeError('Capture fixture window did not appear')
        verify(env)
    finally:
        fixture.terminate()
        fixture.wait(timeout=10)


if __name__ == '__main__':
    main()
