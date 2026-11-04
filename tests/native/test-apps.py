#!/data/data/com.termux/files/usr/bin/python
"""Exercise real X11 applications in the existing desktop; fixtures are private."""
import json
import os
from pathlib import Path
import subprocess
import time
import wave
import math
import struct
import ctypes
import zipfile
import sys

sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
from capture import screenshot

ROOT = Path.home() / 'Documents/livecd-native-validation'
LOG = Path.home() / '.local/state/livecd-native'


def xd(*args):
    return subprocess.check_output(['xdotool', *map(str, args)], text=True).strip()


def window(pattern, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            return xd('search', '--onlyvisible', '--name', pattern).splitlines()[-1]
        except subprocess.CalledProcessError:
            time.sleep(0.25)
    raise RuntimeError('Window did not appear: ' + pattern)


def activate(wid):
    xd('keyup', 'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L', 'Alt_R', 'Super_L', 'Super_R')
    xd('windowactivate', '--sync', wid)
    xd('windowraise', wid)
    time.sleep(1.5)


def mapped_key(name):
    # Trixie's xdotool F2 opened GNOME's Run dialog on this XKB map. Use
    # the mapped keycode, which opened Rename like native Termux xdotool.
    x11 = ctypes.CDLL('libX11.so')
    xtst = ctypes.CDLL('libXtst.so')
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
    x11.XStringToKeysym.restype = ctypes.c_ulong
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_ubyte
    xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(None)
    assert display
    code = x11.XKeysymToKeycode(display, x11.XStringToKeysym(name.encode()))
    assert code
    xtst.XTestFakeKeyEvent(display, code, 1, 0)
    xtst.XTestFakeKeyEvent(display, code, 0, 0)
    x11.XCloseDisplay(display)


def shot(name):
    screenshot(LOG / (name + '.png'))


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    results = {}
    children = []
    logs = []
    xd('key', 'Escape', 'Escape')

    def app(name, args):
        stream = open(LOG / (name + '-test.log'), 'w')
        logs.append(stream)
        proc = subprocess.Popen(args, stdout=stream, stderr=subprocess.STDOUT)
        children.append(proc)
        return proc

    try:
        app('nautilus', ['nautilus', str(ROOT)])
        for _ in range(80):
            try:
                wid = xd('search', '--onlyvisible', '--class', 'org.gnome.Nautilus').splitlines()[-1]
                if ROOT.name in xd('getwindowname', wid):
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError('Nautilus did not open the validation folder')
        activate(wid)
        shot('nautilus')
        results['nautilus_local_folder'] = xd('getwindowname', wid)
        print('NAUTILUS_PASS', flush=True)

        # Exercise Nautilus actions on a dedicated disposable folder.
        operations = ROOT / f'file-operations-{os.getpid()}'
        operations.mkdir()
        original = operations / 'original.txt'
        original.write_text('LiveCD file action fixture\n')
        app('nautilus-operations', ['nautilus', '--new-window', str(operations)])
        wid = window(operations.name)
        activate(wid)
        xd('key', 'ctrl+a')
        mapped_key('F2')
        time.sleep(0.5)
        xd('key', 'ctrl+a')
        xd('type', '--clearmodifiers', 'renamed.txt')
        xd('key', 'Return')
        renamed = operations / 'renamed.txt'
        for _ in range(40):
            if renamed.exists():
                break
            time.sleep(0.25)
        assert renamed.read_text() == 'LiveCD file action fixture\n'
        xd('key', 'ctrl+a')
        xd('key', 'ctrl+c')
        xd('key', 'ctrl+v')
        for _ in range(40):
            files = list(operations.iterdir())
            if len(files) == 2:
                break
            time.sleep(0.25)
        assert len(files) == 2 and all(p.read_text() == renamed.read_text() for p in files)
        # The filesystem copy finishes before GTK's view/selection refresh.
        time.sleep(1.5)
        for _ in range(4):
            xd('key', 'ctrl+a')
            mapped_key('Delete')
            time.sleep(1)
            if not list(operations.iterdir()):
                break
        assert not list(operations.iterdir()), 'Nautilus trash action did not empty fixture folder'
        results['nautilus_rename_copy_trash'] = [p.name for p in files]
        print('NAUTILUS_FILE_ACTIONS_PASS', flush=True)

        html = ROOT / 'browser.html'
        html.write_text('<!doctype html><title>LiveCD Browser Validation</title><h1>Local browser works</h1><p>Native Termux on Android</p>')
        app('firefox', ['firefox', '--new-window', html.as_uri()])
        wid = window('LiveCD Browser Validation', timeout=60)
        activate(wid)
        shot('firefox')
        results['firefox_local_page'] = xd('getwindowname', wid)
        results['firefox_environment'] = {k: os.environ.get(k) for k in ('MOZ_FAKE_NO_SANDBOX', 'MOZ_SHM_NO_SEALS')}
        print('FIREFOX_PASS', flush=True)
        app('firefox-network', ['firefox', '--new-window', 'https://example.com'])
        try:
            wid = window('Example Domain', timeout=45)
            activate(wid)
            shot('firefox-network')
            results['firefox_https_page'] = xd('getwindowname', wid)
            print('FIREFOX_HTTPS_PASS', flush=True)
        except RuntimeError as error:
            results['firefox_https_page'] = 'NOT_ACCEPTED: ' + str(error)
            print('FIREFOX_HTTPS_NOT_ACCEPTED', flush=True)

        # A small tone verifies data reaches the Android-facing sink monitor.
        tone = ROOT / 'tone.wav'
        with wave.open(str(tone), 'wb') as audio:
            audio.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            frame = b''.join(struct.pack('<hh', *(int(2000 * math.sin(2*math.pi*440*n/48000)),)*2) for n in range(48000))
            audio.writeframes(frame * 2)
        raw = LOG / 'audio-monitor.raw'
        with raw.open('wb') as capture:
            recorder = subprocess.Popen(['parec', '--device=OpenSL_ES_sink.monitor', '--format=s16le',
                '--rate=48000', '--channels=2'], stdout=capture, stderr=subprocess.DEVNULL)
            try:
                time.sleep(0.5)
                # Name the sink: with a Bluetooth headset connected, the default is the headset.
                subprocess.run(['paplay', '--device=OpenSL_ES_sink', str(tone)], check=True, timeout=15)
                time.sleep(0.5)
            finally:
                recorder.terminate()
                recorder.wait(timeout=5)
        data = raw.read_bytes()
        values = struct.unpack('<' + 'h' * (len(data)//2), data[:len(data)//2*2])
        peak = max(map(abs, values), default=0)
        assert peak > 100, peak
        results['pulse_sink_monitor'] = {'bytes': len(data), 'peak_s16': peak}
        print('AUDIO_PASS', flush=True)

        # Writer's document engine and file filters, then its actual GTK window.
        source = ROOT / f'writer-{os.getpid()}.txt'
        source.write_text('LibreOffice Writer validation\nSaved in native Termux.\n')
        subprocess.run(['libreoffice', '-env:UserInstallation=' + (LOG / f'writer-test-profile-{os.getpid()}').as_uri(),
            '--headless', '--convert-to', 'odt', '--outdir', str(ROOT), str(source)], check=True, timeout=45)
        odt = source.with_suffix('.odt')
        assert odt.is_file() and odt.stat().st_size > 1000
        app('writer', ['libreoffice', '-env:UserInstallation=' + (LOG / f'writer-test-profile-{os.getpid()}').as_uri(), '--writer', str(odt)])
        wid = window(odt.name, timeout=45)
        activate(wid)
        # Writer publishes its title before its first document frame paints.
        time.sleep(5)
        welcome = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name',
            '^Welcome to LibreOffice!$'], capture_output=True, text=True)
        for dialog in welcome.stdout.splitlines():
            xd('windowquit', dialog)
        activate(wid)
        xd('key', 'ctrl+End', 'Return')
        edited = 'Edited and saved through native Writer X11.'
        xd('type', '--clearmodifiers', '--delay', '5', edited)
        xd('key', 'ctrl+s')
        for _ in range(80):
            with zipfile.ZipFile(odt) as archive:
                saved = edited.encode() in archive.read('content.xml')
            if saved:
                break
            time.sleep(0.25)
        assert saved, 'Writer did not save the typed text in the ODT'
        shot('writer')
        results['writer_odt_and_window'] = {'bytes': odt.stat().st_size,
            'title': xd('getwindowname', wid), 'saved_gui_text': edited}
        xd('windowquit', wid)
        print('WRITER_PASS', flush=True)
        results['result'] = 'PASS_LOCAL_WITH_NETWORK_LIMIT' if results['firefox_https_page'].startswith('NOT_ACCEPTED:') else 'PASS'
        (LOG / 'application-validation.json').write_text(json.dumps(results, indent=2))
        print(json.dumps(results, indent=2), flush=True)
    finally:
        for proc in reversed(children):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        for stream in logs:
            stream.close()


if __name__ == '__main__':
    main()
