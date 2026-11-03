#!/data/data/com.termux/files/usr/bin/python
"""Drive a real browser on a fresh profile through its debugging protocol.

Checks that it is native, that the live CD's extensions install, stay installed and
render, and that uBlock blocks a real ad host that loads without it. Nothing here
signs in to an extension.
"""
import argparse
import base64
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

PREFIX = Path(os.environ['PREFIX'])
SESSIONS = {}
CHROMIUM_EXTENSIONS = {'ddkjiahejlhfcafbddmgiahcphecmpfh': 'uBlock Origin Lite',
    'nngceckbapebfimnlniiiahkandclblb': 'Bitwarden', 'ghmbeldphafepmbegfdlkpapadhbakde': 'Proton Pass'}
FIREFOX_EXTENSIONS = {'uBlock0@raymondhill.net': 'uBlock Origin',
    '{446900e4-71c2-419f-a6a7-df9c091e268b}': 'Bitwarden', '78272b6fa58f4a1abaac99321d503a20@proton.me': 'Proton Pass'}
BROWSERS = {
    'chromium': (PREFIX / 'bin/chromium-vaapi', PREFIX / 'opt/livecd-browsers/chromium-extensions', CHROMIUM_EXTENSIONS)
        if (PREFIX / 'bin/chromium-vaapi').is_file() else
        (PREFIX / 'bin/chromium-browser', PREFIX / 'lib/chromium/extensions', CHROMIUM_EXTENSIONS),
    'ungoogled-chromium': (PREFIX / 'bin/ungoogled-chromium',
        PREFIX / 'opt/livecd-browsers/ungoogled-chromium-extensions', CHROMIUM_EXTENSIONS),
    'chrome': (PREFIX / 'bin/google-chrome', PREFIX / 'opt/google/chrome/extensions', CHROMIUM_EXTENSIONS),
    'firefox': (PREFIX / 'bin/firefox', PREFIX / 'share/mozilla/extensions/{ec8030f7-c20a-464f-9b0e-13a3a9e97384}', FIREFOX_EXTENSIONS),
}
# Hosts uBlock blocks outright. Others prove nothing here: it answers requests for scripts
# such as adsbygoogle.js, and fetches to some ad hosts, with local surrogates that still load.
AD_URLS = ['https://adservice.google.com/', 'https://www.googleadservices.com/']
CONTROL_URL = 'https://example.com/'
# A no-cors fetch resolves on any HTTP response, and rejects only if the request is stopped.
AD_PAGE = """<!doctype html><title>ad probe</title><script>
const probe = url => fetch(url, {mode: 'no-cors', cache: 'no-store'}).then(() => 'loaded', () => 'blocked');
Promise.all([Promise.all(%s.map(probe)), probe(%r)]).then(([ads, control]) => {
  document.title = ads + ' ' + control;
  navigator.sendBeacon('/result', JSON.stringify({ads, control})); });
</script>""" % (json.dumps(AD_URLS), CONTROL_URL)
TONE_PAGE = """<!doctype html><title>tone</title><script>
const c = new AudioContext(), o = c.createOscillator(), g = c.createGain();
g.gain.value = 0.2; o.connect(g).connect(c.destination); o.start(); c.resume();
</script>"""
CAPABILITIES = """(async () => { const gl = document.createElement('canvas').getContext('webgl');
  const video = document.createElement('video');
  const widevine = await navigator.requestMediaKeySystemAccess('com.widevine.alpha', [{initDataTypes: ['cenc'],
    videoCapabilities: [{contentType: 'video/mp4; codecs="avc1.42E01E"'}]}]).then(() => true, e => e.name);
  return {h264: video.canPlayType('video/mp4; codecs="avc1.42E01E"'), vp9: video.canPlayType('video/webm; codecs="vp9"'),
    webgl: gl ? gl.getParameter(gl.VERSION) : null, wasm: typeof WebAssembly === 'object', widevine}; })()"""
ADDONS = """const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
const list = await AddonManager.getAddonsByTypes(['extension']);
return list.filter(a => !a.isBuiltin && !a.isSystem).map(a => ({id: a.id, name: a.name, version: a.version,
  enabled: a.isActive, scope: a.scope, signed: a.signedState, base: WebExtensionPolicy.getByID(a.id)?.getURL('')}));"""
EXTENSION_PREFS = """return {autoDisableScopes: Services.prefs.getIntPref('extensions.autoDisableScopes'),
  startupScanScopes: Services.prefs.getIntPref('extensions.startupScanScopes'),
  enabledScopes: Services.prefs.getIntPref('extensions.enabledScopes', -1)};"""
SANDBOX = """const {AppConstants} = ChromeUtils.importESModule('resource://gre/modules/AppConstants.sys.mjs');
const flag = key => { try { return Services.sysinfo.getPropertyAsBool(key); } catch { return null; } };
return {compiled: AppConstants.MOZ_SANDBOX, contentLevel: Services.prefs.getIntPref('security.sandbox.content.level', -1),
  seccomp: flag('hasSeccompBPF'), userNamespaces: flag('hasUserNamespaces')};"""


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def wait_for(probe, timeout, what):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = probe()
            if value:
                return value
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            last = error
        time.sleep(0.5)
    raise RuntimeError(f'Timed out waiting for {what}: {last}')


class Pages(http.server.BaseHTTPRequestHandler):
    results = []

    def do_GET(self):
        body = {'/ad.html': AD_PAGE, '/tone.html': TONE_PAGE}.get(self.path, '<title>blank</title>').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.results.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


class Chromium:
    """A DevTools Protocol client: one page target over a small RFC 6455 socket."""

    def __init__(self, command, profile, tag, extra=()):
        self.port = free_port()
        self.process = launch([str(command), f'--user-data-dir={profile}', f'--remote-debugging-port={self.port}',
            '--no-first-run', '--no-default-browser-check', '--autoplay-policy=no-user-gesture-required',
            '--window-size=1200,760', *extra, 'about:blank'], tag)
        self.next_id = 0
        self.sock = None
        wait_for(lambda: self.http('/json/version'), 150, 'DevTools')
        self.version = self.http('/json/version')['Browser']
        page = wait_for(lambda: [t for t in self.http('/json/list') if t['type'] == 'page'], 60, 'a page')[0]
        self.connect(page['webSocketDebuggerUrl'])
        self.call('Page.enable')

    def http(self, path, method='GET'):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', method=method)
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def connect(self, url):
        if self.sock:
            self.sock.close()
        path = urllib.parse.urlparse(url).path
        self.sock = socket.create_connection(('127.0.0.1', self.port), timeout=120)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nUpgrade: websocket\r\n'
            f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        reply = b''
        while b'\r\n\r\n' not in reply:
            reply += self.sock.recv(1)
        if b' 101 ' not in reply.split(b'\r\n', 1)[0]:
            raise RuntimeError('WebSocket refused: ' + reply.decode(errors='replace'))

    def exactly(self, count):
        data = b''
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise OSError('DevTools socket closed')
            data += chunk
        return data

    def receive(self):
        message = b''
        while True:
            first, second = self.exactly(2)
            length = second & 0x7f
            if length == 126:
                length = struct.unpack('>H', self.exactly(2))[0]
            elif length == 127:
                length = struct.unpack('>Q', self.exactly(8))[0]
            message += self.exactly(length)
            if first & 0x80:
                return json.loads(message)

    def call(self, method, **params):
        self.next_id += 1
        data = json.dumps({'id': self.next_id, 'method': method, 'params': params}).encode()
        mask = os.urandom(4)
        header = bytes([0x81])
        if len(data) < 126:
            header += bytes([0x80 | len(data)])
        else:
            header += bytes([0x80 | 126]) + struct.pack('>H', len(data))
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        while True:
            reply = self.receive()
            if reply.get('id') == self.next_id:
                if 'error' in reply:
                    raise RuntimeError(f'{method}: {reply["error"]}')
                return reply['result']

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', expression=expression, awaitPromise=True, returnByValue=True)
        if 'exceptionDetails' in result:
            raise RuntimeError(json.dumps(result['exceptionDetails'])[:400])
        return result['result'].get('value')

    def open(self, url):
        self.call('Page.navigate', url=url)
        wait_for(lambda: self.evaluate('document.readyState') == 'complete', 90, 'page load: ' + url)

    def screenshot(self, path):
        # An extension's onboarding tab can take focus, and a background tab paints no frames.
        self.call('Page.bringToFront')
        path.write_bytes(base64.b64decode(self.call('Page.captureScreenshot', format='png')['data']))

    def extensions(self):
        page = self.sock
        target = self.http('/json/new?chrome://extensions', method='PUT')
        self.sock = None
        try:
            self.connect(target['webSocketDebuggerUrl'])
            wait_for(lambda: self.evaluate('!!(chrome && chrome.management)'), 30, 'the extensions page')
            found = self.evaluate('chrome.management.getAll()')
            return [{'id': e['id'], 'name': e['name'], 'version': e['version'], 'enabled': e['enabled'],
                     'installType': e['installType'], 'manifest': e.get('manifestVersion')} for e in found]
        finally:
            if self.sock:
                self.sock.close()
            self.sock = page
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json/close/{target["id"]}', timeout=20).read()
            except OSError:
                pass

    def extension_url(self, entry, path):
        return f'chrome-extension://{entry["id"]}/{path}'

    def quit(self):
        try:
            self.call('Browser.close')
        except OSError:
            pass


class Firefox:
    """A Marionette client: length-prefixed JSON over one local socket."""

    def __init__(self, command, profile, tag, prefs=(), preserve_prefs=False):
        self.port = free_port()
        # Marionette otherwise applies automation prefs that switch off the system add-on
        # directory, which is the install path under test.
        settings = {'marionette.port': self.port, 'remote.prefs.recommended': False, 'browser.aboutwelcome.enabled': False,
            'browser.shell.checkDefaultBrowser': False, 'datareporting.policy.dataSubmissionEnabled': False,
            'media.autoplay.default': 0, 'media.autoplay.blocking_policy': 0, **dict(prefs)}
        preferences = profile / 'user.js'
        previous = preferences.read_text() if preserve_prefs and preferences.exists() else ''
        preferences.write_text(previous + '\n' + ''.join(
            f'user_pref({json.dumps(k)}, {json.dumps(v)});\n' for k, v in settings.items()))
        self.process = launch([str(command), '--marionette', '--no-remote',
            '--profile', str(profile), 'about:blank'], tag)
        self.next_id = 0
        self.sock = wait_for(lambda: socket.create_connection(('127.0.0.1', self.port), timeout=120), 150, 'Marionette')
        self.stream = self.sock.makefile('rb')
        self.read()
        session = self.call('WebDriver:NewSession', capabilities={'alwaysMatch': {'pageLoadStrategy': 'normal'}})
        self.version = session['capabilities']['browserName'] + ' ' + session['capabilities']['browserVersion']

    def read(self):
        length = b''
        while (byte := self.stream.read(1)) != b':':
            if not byte:
                raise OSError('Marionette closed')
            length += byte
        return json.loads(self.stream.read(int(length)))

    def call(self, command, **params):
        self.next_id += 1
        data = json.dumps([0, self.next_id, command, params]).encode()
        self.sock.sendall(str(len(data)).encode() + b':' + data)
        _, _, error, result = self.read()
        if error:
            raise RuntimeError(f'{command}: {error.get("message", error)}')
        return result

    def chrome(self, script):
        self.call('Marionette:SetContext', value='chrome')
        try:
            return self.call('WebDriver:ExecuteScript', script='return (async () => {' + script + '})();', args=[])['value']
        finally:
            self.call('Marionette:SetContext', value='content')

    def evaluate(self, expression):
        return self.call('WebDriver:ExecuteScript', script='return (' + expression + ');', args=[])['value']

    def open(self, url):
        self.call('WebDriver:Navigate', url=url)

    def screenshot(self, path):
        path.write_bytes(base64.b64decode(self.call('WebDriver:TakeScreenshot', full=False)['value']))

    def extensions(self):
        return self.chrome(ADDONS)

    def extension_url(self, entry, path):
        return entry['base'] + path

    def quit(self):
        try:
            self.call('Marionette:Quit')
        except OSError:
            pass


def launch(command, tag):
    # Firefox's Marionette needs the variable to read add-on state; Chromium ignores it.
    env = {**os.environ, 'LIVECD_BROWSER_TEST': tag, 'MOZ_REMOTE_ALLOW_SYSTEM_ACCESS': '1'}
    log = open(OUT / (tag + '.log'), 'ab')
    process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    SESSIONS[tag] = process.pid
    return process


def tagged(tag):
    # Chrome overwrites its own environ, so its processes are found by session as well.
    marker = ('LIVECD_BROWSER_TEST=' + tag).encode()
    found = []
    for proc in Path('/proc').iterdir():
        if proc.name.isdigit():
            try:
                fields = (proc / 'stat').read_text(errors='replace').rsplit(')', 1)[1].split()
                if fields[0] != 'Z' and (int(fields[3]) == SESSIONS.get(tag)
                        or marker in (proc / 'environ').read_bytes().split(b'\0')):
                    found.append(int(proc.name))
            except OSError:
                pass
    return found


def stop(tag, grace=20):
    """Return what survived a clean quit, after making sure it is gone."""
    deadline = time.monotonic() + grace
    while tagged(tag) and time.monotonic() < deadline:
        time.sleep(0.25)
    survivors = tagged(tag)
    for pid in survivors:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return survivors


def identity(tag):
    """Report what each process really is, from the kernel rather than from its name."""
    records = {}
    for pid in tagged(tag):
        try:
            maps = Path(f'/proc/{pid}/maps').read_text(errors='replace')
            status = Path(f'/proc/{pid}/status').read_text()
            exe = os.readlink(f'/proc/{pid}/exe')
        except OSError:
            continue
        loader = 'glibc' if '/glibc/lib/ld-linux-aarch64.so.1' in maps else 'bionic' if '/linker64' in maps else 'unknown'
        tracer = int(re.search(r'TracerPid:\s+(\d+)', status).group(1))
        ancestry = []
        parent = pid
        while parent > 1:
            try:
                stat = Path(f'/proc/{parent}/stat').read_text(errors='replace')
            except OSError:
                break
            ancestry.append(stat[stat.index('(') + 1:stat.rindex(')')])
            parent = int(stat.rsplit(')', 1)[1].split()[1])
        records.setdefault(exe, {'count': 0, 'loader': loader, 'tracers': set(), 'proot_ancestor': False})
        record = records[exe]
        record['count'] += 1
        record['tracers'].add(tracer)
        record['proot_ancestor'] |= any('proot' in name for name in ancestry)
    return {exe: {**record, 'tracers': sorted(record['tracers'])} for exe, record in records.items()}


def popup_path(browser, extension_id):
    _, directory, _ = BROWSERS[browser]
    archive = directory / (extension_id + ('.xpi' if browser == 'firefox' else '.crx'))
    if ARGS.xpi_dir and browser == 'firefox':
        archive = Path(ARGS.xpi_dir) / (extension_id + '.xpi')
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
    return (manifest.get('action') or manifest.get('browser_action') or {})['default_popup'], manifest['manifest_version']


def x11_screenshot(path):
    size = re.search(r'dimensions:\s+(\d+x\d+)', subprocess.check_output(['xdpyinfo'], text=True)).group(1)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', size,
        '-i', os.environ['DISPLAY'], '-frames:v', '1', '-y', str(path)], check=True)


def xdotool(*args):
    return subprocess.run(['xdotool', *map(str, args)], check=True, capture_output=True, text=True).stdout.strip()


def focus(window):
    # A private Xvfb display has no window manager to ask.
    try:
        xdotool('windowactivate', '--sync', window)
    except subprocess.CalledProcessError:
        xdotool('windowfocus', window)


def windows(pid_pattern):
    try:
        return xdotool('search', '--onlyvisible', '--class', pid_pattern).split()
    except subprocess.CalledProcessError:
        return []


def has_window_manager():
    return 'window id' in subprocess.run(['xprop', '-root', '_NET_SUPPORTING_WM_CHECK'], capture_output=True, text=True).stdout


def desktop_stop_reaches(browser, profile, tag):
    """Return what survives the desktop's own shutdown code, or None without that desktop."""
    sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
    try:
        from desktop import cleanup
    except ImportError:
        return None
    # A private value, so that this cannot touch a real session this test runs inside.
    private = uuid.uuid4().hex
    previous = os.environ.get('LIVECD_NATIVE_SESSION')
    os.environ['LIVECD_NATIVE_SESSION'] = private
    try:
        start(browser, profile, tag)
        time.sleep(5)
        cleanup(private)
    finally:
        if previous is None:
            del os.environ['LIVECD_NATIVE_SESSION']
        else:
            os.environ['LIVECD_NATIVE_SESSION'] = previous
    return stop(tag, grace=3)


def browser_window(browser):
    pattern = {'chromium': 'chromium', 'ungoogled-chromium': 'chromium',
               'chrome': 'google-chrome', 'firefox': 'firefox'}[browser]
    return wait_for(lambda: windows(pattern), 20, 'browser window')[-1]


def file_dialog(browser, name):
    focus(browser_window(browser))
    time.sleep(1)
    xdotool('key', 'ctrl+o')

    def dialog():
        try:
            return xdotool('search', '--onlyvisible', '--name', '^(Open|File Upload)')
        except subprocess.CalledProcessError:
            return None  # xdotool fails when nothing matches yet
    found = wait_for(dialog, 25, 'native file dialog').split()[-1]
    title = xdotool('getwindowname', found)
    time.sleep(3)
    x11_screenshot(OUT / f'{name}-file-dialog.png')
    focus(found)
    xdotool('key', 'Escape')
    time.sleep(1)
    return title


def audio_probe(driver, base):
    """Return the loudest sample on the sink monitor while the browser plays a tone."""
    if not os.environ.get('PULSE_SERVER') or subprocess.run(['pactl', 'info'], capture_output=True).returncode:
        return {'skipped': 'no PulseAudio server in this environment'}
    sink = subprocess.check_output(['pactl', 'get-default-sink'], text=True).strip()
    driver.open(base + '/tone.html')
    time.sleep(3)
    clients = subprocess.check_output(['pactl', 'list', 'sink-inputs'], text=True)
    capture = OUT / 'tone.raw'
    with capture.open('wb') as stream:
        recorder = subprocess.Popen(['parec', f'--device={sink}.monitor', '--format=s16le', '--rate=48000', '--channels=2'],
            stdout=stream, stderr=subprocess.DEVNULL)
        time.sleep(3)
        recorder.terminate()
        recorder.wait(timeout=5)
    driver.open(base + '/blank.html')
    data = capture.read_bytes()
    capture.unlink()
    samples = struct.unpack('<' + 'h' * (len(data) // 2), data[:len(data) // 2 * 2])
    return {'peak': max(map(abs, samples), default=0), 'bytes': len(data),
        'stream': re.findall(r'application\.(?:name|process\.binary) = "(.*)"', clients)[:4]}


def ad_probe(driver, base, attempts=4):
    """Load the probe until both results arrive; uBlock needs moments after startup."""
    outcome = None
    for _ in range(attempts):
        Pages.results.clear()
        driver.open(base + '/ad.html')
        outcome = wait_for(lambda: Pages.results[-1] if Pages.results else None, 60, 'ad probe result')
        if set(outcome['ads']) == {'blocked'}:
            break
        time.sleep(10)
    return outcome


def start(browser, profile, tag, extensions=True):
    command = BROWSERS[browser][0]
    if browser == 'firefox':
        # With extensions, rely on the pref install.sh wrote; the control turns the scope off.
        prefs = {} if extensions else {'extensions.enabledScopes': 1}
        if extensions and ARGS.xpi_dir:
            seeded = profile / 'extensions'
            seeded.mkdir(exist_ok=True)
            for path in Path(ARGS.xpi_dir).glob('*.xpi'):
                shutil.copy2(path, seeded / path.name)
            prefs = {'extensions.autoDisableScopes': 0}
        return Firefox(command, profile, tag, prefs)
    return Chromium(command, profile, tag, () if extensions else ('--disable-extensions',))


def main():
    browser = ARGS.browser
    expected = BROWSERS[browser][2]
    checks = {}

    def check(name, ok, detail=None):
        checks[name] = {'ok': bool(ok), 'detail': detail}
        print(('PASS ' if ok else 'FAIL ') + name, json.dumps(detail, default=str)[:300], flush=True)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    work = Path(tempfile.mkdtemp(prefix='browser-test-'))
    run = uuid.uuid4().hex[:8]
    profile = work / 'profile'
    profile.mkdir()
    driver = None
    tag = f'{browser}-{run}'
    try:
        began = time.monotonic()
        driver = start(browser, profile, tag)
        check('version', True, driver.version)
        check('startup_seconds', True, round(time.monotonic() - began, 1))
        who = identity(tag)
        check('native_no_proot', who and all(r['loader'] != 'unknown' and r['tracers'] == [0] and not r['proot_ancestor']
            for r in who.values()), who)
        # Recorded rather than judged: what protects a page from the rest of Termux.
        if browser == 'firefox':
            check('sandbox_state', True, driver.chrome(SANDBOX))
            check('extension_prefs', True, driver.chrome(EXTENSION_PREFS))
        else:
            driver.open('chrome://sandbox')
            time.sleep(2)
            check('sandbox_state', True, ' | '.join(driver.evaluate('document.body.innerText').split('\n'))[:600])

        def installed():
            found = {e['id']: e for e in driver.extensions()}
            return found if all(found.get(i, {}).get('enabled') for i in expected) else None
        try:
            found = wait_for(installed, 240, 'all extensions enabled')
            check('extensions_enabled', True, list(found.values()))
        except RuntimeError as error:
            found = {e['id']: e for e in driver.extensions()}
            check('extensions_enabled', False, {'error': str(error), 'found': list(found.values())})

        driver.open('https://example.com/')
        title = wait_for(lambda: driver.evaluate('document.title'), 60, 'https title')
        check('https_page', title == 'Example Domain', title)
        check('capabilities', True, driver.evaluate(CAPABILITIES))
        outcome = ad_probe(driver, base)
        check('ublock_blocks_ad_hosts', set(outcome['ads']) == {'blocked'} and outcome['control'] == 'loaded', outcome)

        for extension_id, label in expected.items():
            if not found.get(extension_id, {}).get('enabled'):
                check('ui_' + label, False, 'not enabled')
                continue
            path, version = popup_path(browser, extension_id)
            driver.open(driver.extension_url(found[extension_id], path))
            text = wait_for(lambda: (driver.evaluate('document.body ? document.body.innerText : ""') or '').strip(), 90, label + ' UI')
            time.sleep(4)
            text = (driver.evaluate('document.body.innerText') or '').strip()
            driver.screenshot(OUT / f'{browser}-{label.lower().replace(" ", "-")}.png')
            check('ui_' + label, bool(text), {'manifest_version': version, 'path': path, 'text': ' | '.join(text.split('\n'))[:200]})

        audio = audio_probe(driver, base)
        check('audio_reaches_sink', 'skipped' in audio or audio['peak'] > 100, audio)
        driver.open(base + '/blank.html')
        if not has_window_manager():
            check('native_file_dialog', True, 'skipped: this display has no window manager to focus it')
        else:
            try:
                check('native_file_dialog', True, file_dialog(browser, browser))
            except (RuntimeError, subprocess.CalledProcessError) as error:
                x11_screenshot(OUT / f'{browser}-file-dialog-failed.png')
                check('native_file_dialog', False, str(error))
        driver.open('https://example.com/')
        time.sleep(2)
        x11_screenshot(OUT / f'{browser}-window.png')
        window_class = subprocess.check_output(['xprop', '-id', browser_window(browser), 'WM_CLASS'], text=True).strip()
        check('window_class', True, window_class)

        driver.quit()
        survivors = stop(tag)
        check('clean_exit_no_orphans', not survivors, survivors)

        began = time.monotonic()
        driver = start(browser, profile, tag)
        check('restart_seconds', True, round(time.monotonic() - began, 1))
        persisted = {e['id']: e for e in driver.extensions()}
        check('extensions_persist_after_restart', all(persisted.get(i, {}).get('enabled') for i in expected),
            {label: persisted.get(i, {}).get('version') for i, label in expected.items()})
        driver.quit()
        check('second_exit_no_orphans', not stop(tag))

        # Control: the same probe without extensions shows the block came from uBlock.
        control_profile = work / 'control'
        control_profile.mkdir()
        driver = start(browser, control_profile, tag, extensions=False)
        check('control_has_no_extensions', not driver.extensions(), driver.extensions())
        outcome = ad_probe(driver, base, attempts=1)
        check('control_ad_hosts_load', set(outcome['ads']) == {'loaded'} and outcome['control'] == 'loaded', outcome)
        driver.quit()
        check('control_exit_no_orphans', not stop(tag))

        stop_profile = work / 'stop'
        stop_profile.mkdir()
        survivors = desktop_stop_reaches(browser, stop_profile, tag)
        if survivors is None:
            check('desktop_stop_reaches_browser', True, 'skipped: native desktop is not installed')
        else:
            check('desktop_stop_reaches_browser', not survivors, survivors)
    except Exception as error:
        check('harness', False, repr(error))
        raise
    finally:
        server.shutdown()
        stop(tag, grace=0)
        result = {'browser': browser, 'ok': all(c['ok'] for c in checks.values()), 'checks': checks}
        (OUT / f'{browser}.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
        shutil.rmtree(work, ignore_errors=True)
        print('RESULT', browser, 'PASS' if result['ok'] else 'FAIL', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('browser', choices=BROWSERS)
    parser.add_argument('--out', default=str(Path.home() / '.local/state/livecd-browsers/test'))
    parser.add_argument('--xpi-dir', help='Test these XPIs from the fresh profile, leaving the system directory alone')
    ARGS = parser.parse_args()
    OUT = Path(ARGS.out)
    OUT.mkdir(parents=True, exist_ok=True)
    main()
