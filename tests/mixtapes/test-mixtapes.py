#!/data/data/com.termux/files/usr/bin/python
"""Device checks for the installed Mixtapes port, inside the running native desktop.

Usage: livecd-native exec -- python test-mixtapes.py OUTPUT_DIRECTORY [CHECK ...]

Every run uses scratch XDG and music directories, so a real session and real downloads are
untouched. Nothing signs in, and the desktop's Android volume is not changed. Needs network.
"""
from array import array
import json
import math
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
from capture import screenshot  # noqa: E402

PREFIX = Path(os.environ['PREFIX'])
BINARY = PREFIX / 'bin/mixtapes'
HELPER = PREFIX / 'lib/mixtapes/bin/rustypipe-botguard'
VIDEO = 'dQw4w9WgXcQ'
MPRIS = ['--session', '--dest', 'org.mpris.MediaPlayer2.Mixtapes', '--object-path', '/org/mpris/MediaPlayer2']
PLAYER = 'org.mpris.MediaPlayer2.Player'
OUT = Path(sys.argv[1]).absolute()
OUT.mkdir(parents=True, exist_ok=True)
CHECKS = {}


def check(function):
    CHECKS[function.__name__] = function
    return function


def run(*command, timeout=120, **options):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, **options)


class App:
    """One scratch instance of the real binary. `demo` holds upstream's test-harness variables."""

    def __init__(self, name, demo=None, prefs=None, env=None):
        self.name, self.demo, self.prefs, self.env = name, demo, prefs, env or {}

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix='mixtapes-test-', dir=os.environ['TMPDIR']))
        self.music = self.root / 'music'
        # The session's data directory holds the desktop's icon theme, so it stays visible to the app.
        shared = [os.environ[name] for name in ('XDG_DATA_HOME', 'XDG_DATA_DIRS') if name in os.environ]
        env = dict(os.environ, XDG_DATA_HOME=str(self.root / 'data'), XDG_CACHE_HOME=str(self.root / 'cache'),
            XDG_DATA_DIRS=':'.join(shared),
            XDG_CONFIG_HOME=str(self.root / 'config'), XDG_STATE_HOME=str(self.root / 'state'),
            MIXTAPES_MUSIC_DIR=str(self.music), RUST_LOG='info,mixtapes=debug', **self.env)
        if self.demo is not None:
            env.update(MIXTAPES_DEMO='1', MIXTAPES_DEMO_URI='', **self.demo)
        (self.root / 'data/muse').mkdir(parents=True)
        if self.prefs is not None:
            (self.root / 'data/muse/prefs.json').write_text(json.dumps(self.prefs))
        self.log_path = OUT / (self.name + '.log')
        self.log = self.log_path.open('w')
        self.process = subprocess.Popen([str(BINARY)], env=env, stdout=self.log, stderr=subprocess.STDOUT)
        return self

    def alive(self):
        assert self.process.poll() is None, f'{self.name} exited with {self.process.returncode}'

    def text(self):
        return self.log_path.read_text(errors='replace')

    def wait_log(self, needle, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.alive()
            if needle in self.text():
                return True
            time.sleep(0.5)
        return False

    def shot(self, name):
        self.alive()
        park_pointer()
        screenshot(OUT / (name + '.png'))

    def __exit__(self, *_):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
                print(f'  {self.name}: needed SIGKILL after 10 s')
        self.log.close()
        shutil.rmtree(self.root, ignore_errors=True)


def instances():
    """Running copies of the app, by executable: pgrep's name match missed them on this rig."""
    found = []
    for entry in os.listdir('/proc'):
        if entry.isdigit():
            try:
                if os.readlink(f'/proc/{entry}/exe') == str(BINARY):
                    found.append(int(entry))
            except OSError:
                pass
    return found


def park_pointer():
    """Off the dock, whose hover preview would otherwise cover the window."""
    xdo('mousemove', 360, 120)
    time.sleep(1)


SKIPPED = {'login_skipped': True, 'onboarding_done': True, 'show_release_notes': False, 'show_donation_prompt': False}


def default_sink():
    return run('pactl', 'get-default-sink').stdout.strip()


def rms(seconds):
    """Signal level on the default sink's monitor, which is before Android's own volume."""
    recorder = subprocess.Popen(['parec', '--device=' + default_sink() + '.monitor', '--format=s16le',
        '--rate=48000', '--channels=2', '--raw'], stdout=subprocess.PIPE)
    time.sleep(seconds)
    recorder.terminate()
    data = recorder.stdout.read()
    recorder.wait()
    samples = array('h')
    samples.frombytes(data[:len(data) // 2 * 2])
    return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0


def mpris_get(prop):
    return run('gdbus', 'call', *MPRIS, '--method', 'org.freedesktop.DBus.Properties.Get', PLAYER, prop).stdout.strip()


def mpris_position():
    value = mpris_get('Position')
    return int(value.split()[-1].rstrip('>,)')) if 'int64' in value else 0


def mpris_call(method, *args):
    result = run('gdbus', 'call', *MPRIS, '--method', PLAYER + '.' + method, *args)
    assert result.returncode == 0, result.stderr


def wait_for(predicate, seconds, what):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.5)
    raise AssertionError('timed out waiting for ' + what)


def group_usage(root, seconds):
    """CPU over the window as % of one core, and PSS at its end, for a process and its descendants."""
    hz = os.sysconf('SC_CLK_TCK')

    def members():
        parents = {}
        for entry in os.listdir('/proc'):
            if entry.isdigit():
                try:
                    raw = Path('/proc', entry, 'stat').read_text()
                    parents[int(entry)] = int(raw.rsplit(')', 1)[1].split()[1])
                except OSError:
                    pass
        found, todo = set(), [root]
        while todo:
            pid = todo.pop()
            found.add(pid)
            todo += [child for child, parent in parents.items() if parent == pid and child not in found]
        return found

    def ticks(pids):
        total = 0
        for pid in pids:
            try:
                fields = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
                total += int(fields[11]) + int(fields[12])
            except OSError:
                pass
        return total

    before, started = ticks(members()), time.monotonic()
    time.sleep(seconds)
    after, elapsed = ticks(members()), time.monotonic() - started
    pss = 0
    for pid in members():
        try:
            for line in Path('/proc', str(pid), 'smaps_rollup').read_text().splitlines():
                if line.startswith('Pss:'):
                    pss += int(line.split()[1])
        except OSError:
            pass
    return round((after - before) / hz / elapsed * 100, 1), round(pss / 1024)


@check
def identity():
    headers = run('readelf', '-l', str(BINARY)).stdout
    assert '/system/bin/linker64' in headers, 'not linked for Bionic'
    needed = [line.split('[')[1].rstrip(']') for line in run('readelf', '-d', str(BINARY)).stdout.splitlines() if 'NEEDED' in line]
    print('  interpreter: /system/bin/linker64')
    print('  needed:', ' '.join(needed))
    for library in ('libgtk-4.so', 'libadwaita-1.so', 'libwebkitgtk-6.0.so', 'libgstreamer-1.0.so'):
        assert any(name.startswith(library) for name in needed), library + ' not linked'
    assert not any('v8' in name for name in needed)
    assert 'proot' not in Path('/proc/self/cmdline').read_text()
    assert Path('/proc/self/status').read_text().split('TracerPid:')[1].split()[0] == '0', 'traced'
    print('  no tracer on this process tree')


@check
def tls():
    """Does the real binary refuse a certificate that does not chain to a trusted root?"""
    work = Path(tempfile.mkdtemp(prefix='mixtapes-tls-', dir=os.environ['TMPDIR']))
    key, cert = work / 'key.pem', work / 'cert.pem'
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key), '-out', str(cert),
        '-days', '1', '-subj', '/CN=i.ytimg.com', '-addext',
        'subjectAltName=DNS:i.ytimg.com,DNS:music.youtube.com,DNS:www.youtube.com', check=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    connects, failures, requests = [], [], []

    def terminate(raw):
        try:
            with context.wrap_socket(raw, server_side=True) as tls_socket:
                tls_socket.settimeout(5)
                requests.append(tls_socket.recv(200).split(b'\r\n')[0].decode(errors='replace'))
                tls_socket.sendall(b'HTTP/1.1 503 Test\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        except (ssl.SSLError, OSError) as err:
            failures.append(str(err)[:100])

    def proxy():
        while True:
            client, _ = listener.accept()
            first = client.recv(4096).split(b'\r\n')[0].decode(errors='replace')
            connects.append(first)
            client.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
            threading.Thread(target=terminate, args=(client,), daemon=True).start()

    listener = socket.create_server(('127.0.0.1', 0))
    threading.Thread(target=proxy, daemon=True).start()
    address = 'http://127.0.0.1:%d' % listener.getsockname()[1]

    control = run('curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', '--cacert', str(cert), '-x', address,
        'https://i.ytimg.com/control')
    time.sleep(1)
    assert control.stdout == '503' and requests == ['GET /control HTTP/1.1'], ('rig cannot see requests', control, requests)
    print('  control: curl trusting the test CA reached the fake server')
    requests.clear()
    connects.clear()
    with App('tls', {'MIXTAPES_DEMO_VIDEO': VIDEO, 'MIXTAPES_DEMO_TAB': 'home'}, SKIPPED,
             {'HTTPS_PROXY': address, 'https_proxy': address, 'ALL_PROXY': address}):
        time.sleep(30)
    print('  CONNECT requests from the app:', len(connects))
    print('  hosts:', ' '.join(sorted({line.split()[1] for line in connects if ' ' in line})))
    print('  refused handshakes:', len(failures), sorted(set(failures))[:4])
    print('  requests that reached the fake server:', requests)
    shutil.rmtree(work)
    assert connects, 'the app never used the proxy'
    assert not requests, 'a client accepted the untrusted certificate'
    assert failures, 'no handshake was attempted'


@check
def playback():
    with App('playback', {'MIXTAPES_DEMO_VIDEO': VIDEO, 'MIXTAPES_DEMO_AUTOPLAY': '1'}, SKIPPED) as app:
        # MPRIS says Playing while a track is still loading, so only a moving position counts.
        started = time.monotonic()
        wait_for(lambda: mpris_position() > 0, 90, 'the position to move')
        print('  first audio %.1f s after the first poll' % (time.monotonic() - started))
        print('  PlaybackStatus:', mpris_get('PlaybackStatus'))
        print('  Metadata:', mpris_get('Metadata')[:240])
        inputs = run('pactl', 'list', 'sink-inputs').stdout
        assert 'Mixtapes' in inputs or 'mixtapes' in inputs or 'Muse' in inputs, inputs[:800]
        time.sleep(3)
        playing = rms(5)
        print('  monitor RMS while playing:', round(playing, 1))
        assert playing > 50, 'no signal on the sink monitor'
        first = mpris_get('Position')
        app.shot('playback')
        mpris_call('PlayPause')
        wait_for(lambda: 'Paused' in mpris_get('PlaybackStatus'), 15, 'Paused')
        time.sleep(1.5)
        paused = rms(3)
        print('  monitor RMS while paused:', round(paused, 1))
        assert paused < playing / 10, 'pause did not silence the stream'
        mpris_call('PlayPause')
        wait_for(lambda: 'Playing' in mpris_get('PlaybackStatus'), 15, 'Playing again')
        mpris_call('Seek', '60000000')
        time.sleep(4)
        print('  Position before and after a 60 s seek:', first, mpris_get('Position'))
        assert rms(3) > 50, 'no signal after seeking'
        usage = group_usage(app.process.pid, 60)
        print('  playing, window visible, 60 s: %s%% of one core, %s MB PSS' % usage)
        app.alive()
        text = app.text()
    for line in text.splitlines():
        if 'visitor data not warmed' in line or 'player endpoint declined' in line or 'took_ms' in line:
            print('  resolver:', line[line.find('DEBUG'):][:170])
    assert 'panic' not in text.lower(), 'panic in the log'


@check
def idle_usage():
    with App('idle', {}, SKIPPED) as app:
        time.sleep(25)
        print('  idle on Home, 60 s: %s%% of one core, %s MB PSS' % group_usage(app.process.pid, 60))


@check
def download():
    with App('download', {'MIXTAPES_DEMO_DOWNLOAD': VIDEO}, SKIPPED) as app:
        def finished():
            app.alive()
            return [p for p in app.music.rglob('*') if p.suffix in ('.opus', '.m4a', '.mp3', '.ogg', '.flac')
                    and '.part' not in p.name and not p.name.endswith('.temp')]
        files = wait_for(finished, 240, 'a downloaded audio file')
        time.sleep(8)
        for path in files:
            print('  file:', path.relative_to(app.music), path.stat().st_size, 'bytes')
        probe = json.loads(run('ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(files[0])).stdout)
        print('  codec:', probe['streams'][0]['codec_name'], 'duration:', probe['format']['duration'])
        tags = {k.lower(): v for k, v in probe['format'].get('tags', {}).items()}
        tags.update({k.lower(): v for k, v in probe['streams'][0].get('tags', {}).items()})
        print('  tags:', {k: tags[k] for k in ('title', 'artist', 'album') if k in tags})
        assert float(probe['format']['duration']) > 60
        database = app.music / '.mixtapes/library.db'
        with sqlite3.connect(database) as connection:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            print('  library tables:', tables)
            rows = sum(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables)
        print('  library rows:', rows)
        assert rows, 'no library row'


@check
def po_token():
    """The helper's token, on the player client that needs one, past the unauthenticated byte limit."""
    started = time.monotonic()
    minted = run(str(HELPER), VIDEO)
    print('  minted in %.2f s' % (time.monotonic() - started))
    assert minted.returncode == 0, minted.stderr
    line = next(line for line in reversed(minted.stdout.splitlines()) if 'valid_until=' in line)
    token = line.split()[0]
    print('  format matches what the app parses:', line.split()[1:], 'token length', len(token))
    data = run('yt-dlp', '-j', '--no-warnings', '--js-runtimes', 'node', '-f', 'bestaudio',
        '--extractor-args', 'youtube:player_client=web_music', '--extractor-args', 'youtube:po_token=web_music.gvs+' + token,
        'https://music.youtube.com/watch?v=' + VIDEO, timeout=180)
    assert data.returncode == 0, data.stderr[-500:]
    info = json.loads(data.stdout)
    print('  web_music format:', info['format_id'], info.get('acodec'))
    bare = run('yt-dlp', '-j', '--no-warnings', '--js-runtimes', 'node', '-f', 'bestaudio',
        '--extractor-args', 'youtube:player_client=web_music', 'https://music.youtube.com/watch?v=' + VIDEO, timeout=180)
    print('  control, same client with no token: exit', bare.returncode, bare.stderr.strip()[-110:])
    size = run('curl', '-s', '-o', '/dev/null', '-w', '%{http_code} %{size_download}', '-r', '0-2097151', info['url'], timeout=90).stdout
    print('  first 2 MiB with the token:', size)
    assert size.split()[0] in ('200', '206') and int(size.split()[1]) == 2097152


@check
def screens():
    scenes = [
        ('first-run', None, None, 12, {}),
        ('home', None, SKIPPED, 25, {}),
        ('search', {'MIXTAPES_DEMO_TAB': 'search', 'MIXTAPES_DEMO_SEARCH': 'never gonna give you up'}, SKIPPED, 20, {}),
        ('expanded-player', {'MIXTAPES_DEMO_VIDEO': VIDEO, 'MIXTAPES_DEMO_AUTOPLAY': '1', 'MIXTAPES_DEMO_SILENT': '1',
                             'MIXTAPES_DEMO_EXPAND': '12000'}, SKIPPED, 22, {}),
        ('stream-info', {'MIXTAPES_DEMO_VIDEO': VIDEO, 'MIXTAPES_DEMO_AUTOPLAY': '1', 'MIXTAPES_DEMO_SILENT': '1',
                         'MIXTAPES_DEMO_EXPAND': '12000', 'MIXTAPES_DEMO_STREAM_INFO': '20000'}, SKIPPED, 28, {}),
        ('sign-in', {'MIXTAPES_DEMO_LOGIN': '1'}, SKIPPED, 25, {}),
        ('preferences', {'MIXTAPES_DEMO_PREFS': '3000'}, SKIPPED, 9, {}),
    ]
    for name, demo, prefs, wait, env in scenes:
        with App('screen-' + name, demo, prefs, env) as app:
            time.sleep(wait)
            app.shot(name)
            print('  captured', name)


def xdo(*args):
    return subprocess.run(['xdotool', *map(str, args)], capture_output=True, text=True, check=False).stdout.strip()


def click(window, x, y):
    """At x, y in the visible window. GTK's X window also holds its invisible shadow margins."""
    output = subprocess.run(['xprop', '-id', window, '_GTK_FRAME_EXTENTS'], capture_output=True, text=True).stdout
    left, _, top, _ = (int(v) for v in output.split('=')[1].split(',')) if '=' in output else (0, 0, 0, 0)
    xdo('mousemove', '--window', window, x + left, y + top)
    time.sleep(0.7)
    xdo('click', 1)


@check
def lyrics():
    """Open the player with its chevron, then press Lyrics, with real input at the phone's width."""
    with App('lyrics', {'MIXTAPES_DEMO_VIDEO': VIDEO, 'MIXTAPES_DEMO_AUTOPLAY': '1', 'MIXTAPES_DEMO_SILENT': '1'}, SKIPPED) as app:
        assert app.wait_log('lyrics fetched', 60), 'no provider returned lyrics'
        time.sleep(3)
        win = wait_for(lambda: xdo('search', '--onlyvisible', '--name', '^Mixtapes$').split()[-1:], 10, 'the window')[0]
        click(win, 690, 663)
        time.sleep(3)
        park_pointer()
        screenshot(OUT / 'lyrics-player.png')
        click(win, 407, 663)
        time.sleep(8)
        app.shot('lyrics')
        for line in app.text().splitlines():
            if 'lyrics fetched' in line:
                print('  ', line[line.find('lyrics fetched'):][:100])
                break


@check
def real_use():
    """The installed menu entry and real X input, then closing the window and launching again."""
    root = Path(tempfile.mkdtemp(prefix='mixtapes-test-', dir=os.environ['TMPDIR']))
    (root / 'data/muse').mkdir(parents=True)
    (root / 'data/muse/prefs.json').write_text(json.dumps(SKIPPED))
    shared = [os.environ[name] for name in ('XDG_DATA_HOME', 'XDG_DATA_DIRS') if name in os.environ]
    env = dict(os.environ, XDG_DATA_HOME=str(root / 'data'), XDG_CACHE_HOME=str(root / 'cache'),
        XDG_CONFIG_HOME=str(root / 'config'), XDG_STATE_HOME=str(root / 'state'), XDG_DATA_DIRS=':'.join(shared),
        MIXTAPES_MUSIC_DIR=str(root / 'music'))
    launch = ['gtk-launch', 'com.pocoguy.Muse']

    def window():
        found = xdo('search', '--onlyvisible', '--name', '^Mixtapes$').split()
        return found[-1] if found else None

    log = (OUT / 'real-use.log').open('w')
    env['RUST_LOG'] = 'info,mixtapes=debug'
    assert not instances(), f'another copy is already running: {instances()}'
    # The app inherits these, so a pipe here would stay open for as long as the app runs.
    subprocess.run(launch, env=env, check=True, timeout=20, stdout=log, stderr=log)
    pid = None
    try:
        win = wait_for(window, 30, 'the window from the menu entry')
        pid = int(xdo('getwindowpid', win))
        print('  menu entry opened window', win, 'pid', pid)
        environ = Path('/proc', str(pid), 'environ').read_bytes()
        print('  carries the desktop session tag:', b'LIVECD_NATIVE_SESSION=' in environ)
        time.sleep(10)
        xdo('windowactivate', '--sync', win)
        click(win, 22, 23)
        time.sleep(1.5)
        xdo('type', '--delay', 40, 'never gonna give you up')
        xdo('key', 'Return')
        time.sleep(9)
        park_pointer()
        screenshot(OUT / 'real-use-search.png')
        click(win, 360, 228)
        started = time.monotonic()
        wait_for(lambda: mpris_position() > 0, 60, 'playback from the clicked result')
        print('  clicked a search result; first audio after %.1f s' % (time.monotonic() - started))
        time.sleep(3)
        print('  monitor RMS:', round(rms(3), 1))
        park_pointer()
        screenshot(OUT / 'real-use-playing.png')
        xdo('mousemove', 600, 1224, 'click', 1)
        time.sleep(2)
        screenshot(OUT / 'real-use-date-menu.png')
        xdo('key', 'Escape')
        time.sleep(1)
        before = mpris_position()
        xdo('windowquit', win)
        wait_for(lambda: not window(), 10, 'the window to close')
        time.sleep(4)
        assert Path('/proc', str(pid)).exists(), 'closing the window ended the app'
        level = rms(3)
        print('  after closing the window: position %d to %d ms, RMS %.1f' % (before // 1000, mpris_position() // 1000, level))
        assert mpris_position() > before and level > 50, 'background playback stopped'
        subprocess.run(launch, env=env, check=True, timeout=20, stdout=log, stderr=log)
        win = wait_for(window, 15, 'a second launch to show the window')
        time.sleep(2)
        print('  second launch reopened it; running copies:', len(instances()))
        assert instances() == [pid], f'expected only {pid}, found {instances()}'
        run('gdbus', 'call', *MPRIS, '--method', 'org.mpris.MediaPlayer2.Quit')
        wait_for(lambda: not Path('/proc', str(pid)).exists(), 10, 'MPRIS Quit to end the app')
        print('  MPRIS Quit ended the app')
    finally:
        for leftover in instances():
            os.kill(leftover, 15)
        log.close()
        shutil.rmtree(root, ignore_errors=True)


failed = 0
for name in sys.argv[2:] or CHECKS:
    print('===', name)
    try:
        CHECKS[name]()
        print('PASS', name)
    except Exception as err:  # A failure in one check must not hide the others.
        failed += 1
        print('FAIL', name, repr(err)[:1500])
sys.exit(1 if failed else 0)
