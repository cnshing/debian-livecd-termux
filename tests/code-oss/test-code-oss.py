#!/data/data/com.termux/files/usr/bin/python
"""Drive Code OSS on a private display, with scratch data, through its debugging protocol.

Run in native Termux after applying the "Text Editor+Code OSS" overlay. Nothing here uses the
live desktop, or signs in to a service. Results come from what happened, such as a file a
terminal wrote or a secret read back after a restart, rather than from what the window says.

With --ssh-host it also works on that machine over SSH, using a scratch folder given by
--ssh-path. Open Remote - SSH is then only taken as far as installing its server, from a URL
that cannot answer, so that no server is downloaded. --server-url names a real server, which
is then downloaded and run on that machine, and tests the remote extension host. It must be
built from this editor's commit: validation stays strict. Everything on that machine stops,
and the scratch folder goes, however the test ends.

To run this while the installed liblivecd-proc.so still aborts Node.js programs (see
docs/code-oss/VERIFICATION.md), set LIVECD_RESOURCES_COMPAT=0.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.parse
import urllib.request

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src/native'))
from desktop import BASE, DATA, PREFIX, RUNTIME, environment

OVERLAY = REPO / 'overlays/Text Editor+Code OSS/filesystem/termux/home-defaults'
PROBE = Path(__file__).resolve().parent / 'secret-probe'
EXTENSIONS = Path.home() / '.vscode-oss/extensions'
MAIN = 'lib/electron43/electron ' + str(PREFIX / 'lib/code-oss/code.mjs')
EXPECTED = {'github.vscode-pull-request-github', 'github.vscode-github-actions', 'eamodio.gitlens',
    'mhutchie.git-graph', 'jeanp413.open-remote-ssh', 'kelvin.vscode-sshfs'}
SETTINGS = {'workbench.startupEditor': 'none', 'security.workspace.trust.enabled': False,
    'git.useEditorAsCommitInput': False, 'git.enableSmartCommit': True, 'extensions.autoUpdate': False}
KEYRING_PASSWORD = 'scratch-keyring-password'
NO_SERVER = 'http://127.0.0.1:9/no-server.tar.gz'


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


class Workbench:
    """One editor window over a small RFC 6455 socket. Input goes through DevTools, not X11."""

    def __init__(self, port):
        self.port = port
        self.next_id = 0
        page = wait_for(self.page, 120, 'a workbench page')
        path = urllib.parse.urlparse(page['webSocketDebuggerUrl']).path
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=180)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n'
            f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        reply = b''
        while b'\r\n\r\n' not in reply:
            reply += self.sock.recv(1)
        if b' 101 ' not in reply.split(b'\r\n', 1)[0]:
            raise RuntimeError('WebSocket refused: ' + reply.decode(errors='replace'))

    def page(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json/list', timeout=20) as response:
            pages = [t for t in json.load(response) if t['type'] == 'page' and t['url'].endswith('workbench.html')]
        return pages[0] if pages else None

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

    def title(self):
        return self.evaluate('document.title')

    def screenshot(self, path):
        path.write_bytes(base64.b64decode(self.call('Page.captureScreenshot', format='png')['data']))

    def key(self, key, code, virtual, text=None):
        down = {'text': text} if text else {}
        self.call('Input.dispatchKeyEvent', type='keyDown' if text else 'rawKeyDown', key=key, code=code,
            windowsVirtualKeyCode=virtual, nativeVirtualKeyCode=virtual, **down)
        self.call('Input.dispatchKeyEvent', type='keyUp', key=key, code=code,
            windowsVirtualKeyCode=virtual, nativeVirtualKeyCode=virtual)

    def type(self, text):
        self.call('Input.insertText', text=text)

    def enter(self):
        self.key('Enter', 'Enter', 13, '\r')

    def choose(self, label, timeout=30):
        """Click the quick-input row with this label, never whichever row sorts first."""
        def row():
            found = self.evaluate("""(wanted => {
                const rows = [...document.querySelectorAll('.quick-input-list .monaco-list-row')];
                const text = r => (r.querySelector('.label-name') || r).innerText.trim();
                const hit = rows.find(r => text(r) === wanted) || rows.find(r => text(r).startsWith(wanted));
                if (!hit) return null;
                const box = hit.getBoundingClientRect();
                return {x: box.x + box.width / 2, y: box.y + box.height / 2}; })(%s)""" % json.dumps(label))
            return found
        place = wait_for(row, timeout, f'quick-input row {label!r}')
        for kind, extra in (('mouseMoved', {}), ('mousePressed', {'button': 'left', 'clickCount': 1}),
                            ('mouseReleased', {'button': 'left', 'clickCount': 1})):
            self.call('Input.dispatchMouseEvent', type=kind, x=place['x'], y=place['y'], **extra)

    def rows(self):
        return self.evaluate("[...document.querySelectorAll('.quick-input-list .monaco-list-row')].map(r => r.innerText)")

    def command(self, label):
        for attempt in range(4):
            self.key('Escape', 'Escape', 27)
            time.sleep(0.3)
            self.key('F1', 'F1', 112)
            time.sleep(0.8)
            self.type(label)
            time.sleep(1)
            try:
                self.choose(label, timeout=8)
                # A window that takes focus can lose the click, or close the palette during typing.
                wait_for(lambda: self.palette_moved_on(label), 4, f'{label!r} to run')
                return
            except RuntimeError:
                if attempt == 3:
                    raise

    def palette_moved_on(self, label):
        """It closed, or the command opened its own list, so the row really was accepted."""
        return self.evaluate("""(wanted => {
            const widget = document.querySelector('.quick-input-widget');
            if (!widget || getComputedStyle(widget).display === 'none') return true;
            return widget.querySelector('input').value !== '>' + wanted; })(%s)""" % json.dumps(label))

    def settle_first_run(self):
        """GitLens opens a tab some seconds into a new profile, taking focus from whatever has it."""
        for _ in range(40):
            if self.evaluate("!!document.querySelector('.tab[aria-label*=\"Welcome\"]')"):
                time.sleep(3)
                return True
            time.sleep(0.5)
        return False

    def open_from_explorer(self, name):
        place = wait_for(lambda: self.evaluate("""(wanted => {
            const row = [...document.querySelectorAll('.explorer-folders-view .monaco-list-row')].find(r => r.innerText.trim() === wanted);
            if (!row) return null;
            const box = row.getBoundingClientRect();
            return {x: box.x + box.width / 2, y: box.y + box.height / 2}; })(%s)""" % json.dumps(name)), 30, 'the file in the Explorer')
        for kind, extra in (('mouseMoved', {}), ('mousePressed', {'button': 'left', 'clickCount': 1}),
                            ('mouseReleased', {'button': 'left', 'clickCount': 1})):
            self.call('Input.dispatchMouseEvent', type=kind, x=place['x'], y=place['y'], **extra)

    def explorer(self):
        return self.evaluate("[...document.querySelectorAll('.explorer-folders-view .monaco-list-row')].map(r => r.innerText)")

    def views(self):
        return self.evaluate("[...document.querySelectorAll('.activitybar .action-label')].map(a => a.getAttribute('aria-label')).filter(Boolean)")


class Fixture:
    """A private X display and session bus, and an editor with a scratch home on them."""

    def __init__(self, scratch):
        self.scratch = scratch
        self.home = scratch / 'home'
        self.children = []
        self.editor_log = None
        self.driver = None
        self.brokers = set()
        self.launcher_crashes = []
        self.display = next(n for n in range(60, 200) if not (Path(os.environ['TMPDIR']) / f'.X11-unix/X{n}').exists())
        for name in ('.vscode-oss', 'config/Code - OSS/User', 'data', 'state', 'cache'):
            (self.home / name).mkdir(parents=True)
        # As long as a real session's. An editor that only ever saw a short one exits on the real desktop.
        self.runtime = RUNTIME / 'native' / uuid.uuid4().hex
        self.runtime.mkdir(mode=0o700, parents=True)
        shutil.copy2(OVERLAY / '.vscode-oss/argv.json', self.home / '.vscode-oss/argv.json')
        settings = json.loads((OVERLAY / '.config/livecd-native/Code - OSS/User/settings.json').read_text())
        self.settings_path = self.home / 'config/Code - OSS/User/settings.json'
        self.settings_path.write_text(json.dumps({**settings, **SETTINGS}))
        # The desktop's own environment, so that its private library path and data are in effect.
        self.env = {**environment(), 'DISPLAY': f':{self.display}', 'HOME': str(self.home),
            'XDG_CONFIG_HOME': str(self.home / 'config'), 'XDG_DATA_HOME': str(self.home / 'data'),
            'XDG_STATE_HOME': str(self.home / 'state'), 'XDG_CACHE_HOME': str(self.home / 'cache'),
            'XDG_RUNTIME_DIR': str(self.runtime), 'SECRET_PROBE_OUT': str(scratch / 'secret.out'),
            'SECRET_PROBE_VALUE': 'value-' + os.urandom(6).hex()}
        self.start(['Xvfb', f':{self.display}', '-screen', '0', '1500x950x24', '-nolisten', 'tcp'])
        wait_for((Path(os.environ['TMPDIR']) / f'.X11-unix/X{self.display}').exists, 20, 'Xvfb')
        self.start_bus()
        self.start(['openbox'])

    def start(self, command, **extra):
        process = subprocess.Popen(command, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, **extra)
        self.children.append(process)
        return process

    def start_bus(self):
        """A new bus stands in for a new desktop session: services it activated end with it."""
        self.bus = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--print-address=1'], env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        self.env['DBUS_SESSION_BUS_ADDRESS'] = self.bus.stdout.readline().strip()

    def stop_bus(self):
        self.bus.terminate()
        self.bus.wait(20)
        self.bus.stdout.close()

    def editor_pids(self):
        """Every process of this run's editor, found by what `livecd stop` looks for."""
        marker = f'XDG_CONFIG_HOME={self.env["XDG_CONFIG_HOME"]}'.encode()
        found = {}
        for proc in Path('/proc').glob('[0-9]*'):
            try:
                if marker in (proc / 'environ').read_bytes().split(b'\0'):
                    command = (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
                    if 'electron' in command or '/proc/self/exe' in command:
                        found[int(proc.name)] = command
            except OSError:
                pass
        return found

    def session_pids(self):
        """Services the bus activated, which inherit its environment. Xvfb and openbox are this test's."""
        marker = f'XDG_CONFIG_HOME={self.env["XDG_CONFIG_HOME"]}'.encode()
        ours = {process.pid for process in self.children}
        found = {}
        for proc in Path('/proc').glob('[0-9]*'):
            try:
                if int(proc.name) not in ours and int(proc.name) != self.bus.pid and marker in (proc / 'environ').read_bytes().split(b'\0'):
                    command = (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')[:240]
                    # The resource preload starts its long-lived broker, which is not the session's.
                    if 'livecd-resources/broker' in command:
                        self.brokers.add(int(proc.name))
                    else:
                        found[int(proc.name)] = command
            except OSError:
                pass
        return found

    def launch(self, *arguments, secret_probe=True):
        self.port = free_port()
        self.editor_log = open(self.scratch / 'editor.log', 'a')
        development = [f'--extensionDevelopmentPath={PROBE}'] if secret_probe else []
        # Opening the editor sometimes fails, which a person would answer by opening it again: the
        # launcher dies with SIGTRAP, or exits cleanly with no editor left running. Both are counted
        # and reported in the results, not hidden: see docs/code-oss/VERIFICATION.md.
        for _ in range(4):
            launcher = subprocess.Popen(['code-oss', '--extensions-dir', str(EXTENSIONS), *development,
                f'--remote-debugging-port={self.port}', *arguments], env=self.env, stdin=subprocess.DEVNULL,
                stdout=self.editor_log, stderr=self.editor_log, start_new_session=True)
            try:
                if launcher.wait(20) != 0:
                    self.launcher_crashes.append(launcher.returncode)
                    continue
            except subprocess.TimeoutExpired:
                break
            # Attach as soon as there is a window: a keyring prompt soon stops DevTools answering.
            for _ in range(16):
                if self.editor_answers():
                    break
                time.sleep(0.5)
            if self.editor_answers() or self.editor_pids():
                break
            self.launcher_crashes.append('no editor')
        self.driver = Workbench(self.port)
        return self.driver

    def editor_answers(self):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json/list', timeout=2) as response:
                return any(t['type'] == 'page' and t['url'].endswith('workbench.html') for t in json.load(response))
        except OSError:
            return False

    def quit(self):
        for pid in self.editor_pids():
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        try:
            wait_for(lambda: not self.editor_pids(), 20, 'the editor to exit')
        except RuntimeError:
            for pid in self.editor_pids():
                os.kill(pid, 9)
        if self.editor_log:
            self.editor_log.close()
            self.editor_log = None

    def log(self, name):
        latest = sorted((self.home / 'config/Code - OSS/logs').glob('*'))[-1]
        found = list(latest.rglob(name))
        return found[0].read_text(errors='replace') if found else ''

    def capture_failure(self, evidence):
        """While the window is still open: nothing can be captured after cleanup."""
        if not self.driver:
            return
        print('editor processes', len(self.editor_pids()), 'windows',
            [self.xdotool('getwindowname', w)[:50] for w in self.xdotool('search', '--onlyvisible', '--name', '.*').split()], flush=True)
        logs = self.home / 'config/Code - OSS/logs'
        if logs.exists():
            shutil.copytree(logs, evidence / 'stopped-logs', ignore=shutil.ignore_patterns('output_logging_*'), dirs_exist_ok=True)
        try:
            self.driver.screenshot(evidence / 'stopped.png')
            print('rows', self.driver.rows()[:6], flush=True)
            print('renderer', self.log('renderer.log')[-1200:], flush=True)
            print('host', self.log('exthost.log')[-900:], flush=True)
        except (OSError, RuntimeError, IndexError) as detail:
            print('no failure capture:', detail, flush=True)
        self.driver = None

    def xdotool(self, *arguments):
        return subprocess.run(['xdotool', *arguments], env=self.env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=30).stdout.strip()

    def answer_keyring(self, confirm):
        """Answer gcr-prompter, which is a real window, on this private display, if it is open."""
        windows = self.xdotool('search', '--onlyvisible', '--class', 'gcr-prompter').split()
        if not windows:
            return False
        window = windows[0]
        self.xdotool('windowactivate', '--sync', window)
        time.sleep(0.5)
        self.xdotool('type', '--delay', '30', KEYRING_PASSWORD)
        if confirm:
            self.xdotool('key', 'Tab')
            self.xdotool('type', '--delay', '30', KEYRING_PASSWORD)
        self.xdotool('key', 'Return')
        return True

    def close(self):
        self.quit()
        self.stop_bus()
        for process in self.children:
            process.terminate()
        time.sleep(1)
        shutil.rmtree(self.runtime, ignore_errors=True)


def probe_secret(driver, fixture, command):
    out = Path(fixture.env['SECRET_PROBE_OUT'])
    out.unlink(missing_ok=True)
    # GitLens can take focus just as a palette row is clicked, losing the click. Both commands
    # can safely repeat, and storage that really hangs still fails after every attempt.
    for attempt in range(5):
        driver.command(command)
        try:
            wait_for(out.exists, 15, 'the secret probe')
            return json.loads(out.read_text())
        except RuntimeError:
            if attempt == 4:
                raise


def stored_secret(fixture):
    """What is on disk for the probe's secret, which must not be the secret itself."""
    database = fixture.home / 'config/Code - OSS/User/globalStorage/state.vscdb'
    with sqlite3.connect(database) as connection:
        for key, value in connection.execute("select key, value from ItemTable where key like 'secret://%'"):
            if 'secret-probe' in key:
                return bytes(json.loads(value)['data'])
    return None


def session_processes(fixture):
    """The editor's processes as Android sees them, for the native and shutdown checks."""
    pids = fixture.editor_pids()
    main = [pid for pid, command in pids.items() if MAIN in command]
    linker = bool(main) and 'bionic/libc.so' in Path(f'/proc/{main[0]}/maps').read_text()
    tracer = [int(re.search(r'TracerPid:\s*(\d+)', Path(f'/proc/{pid}/status').read_text()).group(1)) for pid in main]
    return {'count': len(pids), 'main': main, 'bionic_linker': linker, 'tracers': tracer}


def local_checks(fixture, check, evidence):
    entries = {name: (DATA / 'applications' / name) for name in ('code-oss.desktop', 'code-oss-url-handler.desktop')}
    for name, path in entries.items():
        valid = subprocess.run(['desktop-file-validate', str(path)], capture_output=True, text=True)
        check('entry_valid_' + name, valid.returncode == 0 and '@@' not in path.read_text(), valid.stdout.strip())
        commands = re.findall(r'^Exec=(\S+)', path.read_text(), re.M)
        check('entry_uses_launcher_' + name, set(commands) == {str(BASE / 'bin/code-oss')}, commands)
    cache = (DATA / 'applications/mimeinfo.cache').read_text()
    check('url_handler_registered', re.search(r'^x-scheme-handler/code-oss=.*code-oss-url-handler\.desktop', cache, re.M))
    listed = subprocess.run(['code-oss', '--extensions-dir', str(EXTENSIONS), '--list-extensions', '--show-versions'],
        env=fixture.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120).stdout.split()
    check('extensions_installed', EXPECTED <= {e.split('@')[0].lower() for e in listed}, listed)

    work = fixture.scratch / 'work'
    (work / '.vscode').mkdir(parents=True)
    results = fixture.scratch / 'results'
    results.mkdir()
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(work)], check=True)
    for key, value in (('user.email', 'test@example.invalid'), ('user.name', 'test')):
        subprocess.run(['git', '-C', str(work), 'config', key, value], check=True)
    hook = work / '.git/hooks/pre-commit'
    hook.write_text('#!/usr/bin/env bash\n{ echo ran; echo "$LD_PRELOAD"; } > ' + str(results / 'hook') + '\n')
    hook.chmod(0o755)
    (work / '.vscode/tasks.json').write_text(json.dumps({'version': '2.0.0', 'tasks': [{'label': 'local-task', 'type': 'shell',
        'command': f'(uname -sm; command -v git) > {results}/task', 'problemMatcher': []}]}))
    (work / 'a.txt').write_text('fixture\n')

    began = time.monotonic()
    driver = fixture.launch(str(work))
    wait_for(lambda: re.search(r'\bwork\b', driver.title() or ''), 90, 'the folder to open')
    check.note('startup_seconds', round(time.monotonic() - began, 1))
    check('no_first_run_modal', not driver.evaluate(
        "[...document.querySelectorAll('a,button,.monaco-button')].some(e => /Continue without Signing In/.test(e.innerText || ''))"))
    sockets = [p.name for p in fixture.runtime.glob('vscode-*')]
    check('sockets_in_session_runtime_dir', any(name.endswith('-main.sock') for name in sockets), sockets)
    who = session_processes(fixture)
    check('native_bionic_no_proot', who['bionic_linker'] and who['tracers'] == [0], who)
    window = wait_for(lambda: fixture.xdotool('search', '--onlyvisible', '--class', 'code-oss').split()[:1], 20, 'the window')[0]
    wm_class = subprocess.run(['xprop', '-id', window, 'WM_CLASS'], env=fixture.env, capture_output=True, text=True).stdout.strip()
    declared = re.search(r'^StartupWMClass=(.*)$', entries['code-oss.desktop'].read_text(), re.M).group(1)
    check('window_class_matches_entry', f'"{declared}"' in wm_class, wm_class)
    driver.screenshot(evidence / 'first-launch.png')

    # The first lookup of a secret creates the keyring, and Android has no login to unlock one with.
    began = time.monotonic()
    check('keyring_asks_for_a_password', wait_for(lambda: fixture.answer_keyring(True), 60, 'the keyring prompt'),
        round(time.monotonic() - began, 1))

    # Extensions that need proposed APIs say so in this log when refused.
    wait_for(lambda: '_doActivateExtension GitHub.vscode-pull-request-github' in fixture.log('exthost.log'), 60, 'the PR extension to activate')
    host = fixture.log('exthost.log')
    check('pr_extension_activated', '_doActivateExtension GitHub.vscode-pull-request-github' in host)
    renderer = fixture.log('renderer.log')
    refused = [line[:200] for line in renderer.splitlines() if 'proposed' in line.lower() and 'error' in line.lower()]
    check('no_proposed_api_refusals', not refused, refused)
    check('remote_view_contributed', 'Remote Explorer' in driver.views(), driver.views())
    driver.settle_first_run()

    stored = probe_secret(driver, fixture, 'Secret Probe: Store')
    check('secret_stored', stored.get('stored'), stored)
    check('keyring_in_private_data', list((fixture.home / 'data/keyrings').glob('*.keyring')))

    driver.command('Terminal: Create New Terminal')
    time.sleep(6)
    driver.type(f'echo "$LD_PRELOAD" > {results}/terminal; git --version >> {results}/terminal')
    driver.enter()
    terminal = wait_for(lambda: (results / 'terminal').exists() and (results / 'terminal').read_text().count('\n') >= 2 and
        (results / 'terminal').read_text(), 30, 'the terminal command')
    check('terminal_runs_native_tools', 'termux-exec' in terminal and 'git version' in terminal, terminal)
    driver.screenshot(evidence / 'terminal.png')

    driver.command('Tasks: Run Task')
    time.sleep(3)
    driver.choose('local-task')
    time.sleep(2)
    if driver.rows():
        driver.enter()
    task = wait_for(lambda: (results / 'task').exists() and (results / 'task').read_text(), 40, 'the task')
    check('task_runs_native_tools', str(PREFIX / 'bin/git') in task and 'aarch64' in task, task)

    driver.command('Git: Commit All')
    time.sleep(2)
    driver.type('commit from the editor')
    driver.enter()
    wait_for(lambda: (results / 'hook').exists(), 30, 'the hook')
    subject = lambda: subprocess.run(['git', '-C', str(work), 'log', '-1', '--format=%s'], capture_output=True, text=True).stdout.strip()
    check('git_commit_from_editor', wait_for(lambda: subject() == 'commit from the editor' and subject(), 30, 'the commit'), subject())
    check('git_hook_env_shebang', 'termux-exec' in (results / 'hook').read_text(), (results / 'hook').read_text())
    driver.screenshot(evidence / 'local.png')

    # Through the repaired entry, as a browser would: gio finds it by scheme and it runs --open-url.
    applications = fixture.home / 'data/applications'
    applications.mkdir(exist_ok=True)
    for path in entries.values():
        shutil.copy2(path, applications / path.name)
    subprocess.run(['update-desktop-database', str(applications)], env=fixture.env, check=True)
    subprocess.run(['gio', 'open', f'code-oss://file{work}/a.txt'], env=fixture.env, stdin=subprocess.DEVNULL,
        capture_output=True, timeout=60)
    # The editor asks before an outside application opens a local file, in a native dialog of its own.
    # Its appearance shows that the URL arrived. It is refused here, and that prompt should stay.
    prompt = wait_for(lambda: fixture.xdotool('search', '--onlyvisible', '--name', '^Code - OSS$').split()[:1], 30, 'the URL to arrive')
    check('url_reaches_editor', prompt)
    fixture.xdotool('windowclose', prompt[0])

    # A restart must find the secret in the running keyring, then a new session must ask for it.
    fixture.quit()
    raw = stored_secret(fixture)
    value = fixture.env['SECRET_PROBE_VALUE'].encode()
    check('secret_encrypted_on_disk', raw and raw.startswith(b'v11') and value not in raw, raw[:3].decode() if raw else None)
    driver = fixture.launch(str(work))
    wait_for(lambda: re.search(r'\bwork\b', driver.title() or ''), 90, 'the folder to reopen')
    time.sleep(4)
    again = probe_secret(driver, fixture, 'Secret Probe: Read')
    check('secret_survives_editor_restart', again.get('value') == fixture.env['SECRET_PROBE_VALUE'], list(again))

    fixture.quit()
    fixture.stop_bus()
    wait_for(lambda: not fixture.session_pids(), 20, 'the keyring to end with its session')
    check('keyring_ends_with_session', True)
    fixture.start_bus()
    driver = fixture.launch(str(work))
    wait_for(lambda: re.search(r'\bwork\b', driver.title() or ''), 90, 'the folder to reopen')
    check('new_session_asks_to_unlock', wait_for(lambda: fixture.answer_keyring(False), 60, 'the unlock prompt'))
    time.sleep(4)
    locked = probe_secret(driver, fixture, 'Secret Probe: Read')
    check('secret_survives_new_session_after_unlock', locked.get('value') == fixture.env['SECRET_PROBE_VALUE'], list(locked))
    fixture.quit()


def run_ssh(config, host, *command, **extra):
    return subprocess.run(['ssh', '-F', str(config), host, *command], capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=60, **extra)


def stop_server(config, host, root):
    """Through stdin: on a command line this pattern would match the shell running it."""
    pattern = shlex.quote(root + '/.server')
    return subprocess.run(['ssh', '-F', str(config), host, 'sh -s'], text=True, capture_output=True, timeout=60,
        input=f'pkill -f {pattern}\nsleep 2\npkill -9 -f {pattern}\nsleep 1\npgrep -fc {pattern}\n').stdout.strip()


def ssh_fs_checks(fixture, check, evidence, args, machine, read):
    host, root = args.ssh_host, args.ssh_path
    driver = fixture.launch('--folder-uri', f'ssh://{host}{root}')
    rows = wait_for(lambda: [r for r in driver.explorer() if 'README' in r] and driver.explorer(), 60, 'the remote folder')
    check('sshfs_lists_remote_files', 'README.md' in rows, rows)
    # SSH FS has no search provider, so Go to File and Search are empty there.
    check.note('sshfs_no_search_provider', 'No search provider registered for scheme: ssh' in fixture.log('renderer.log'))
    driver.open_from_explorer('README.md')
    wait_for(lambda: 'README' in str(driver.evaluate("document.querySelector('.tab.active')?.getAttribute('aria-label')")), 30, 'the file to open')
    time.sleep(2)
    driver.evaluate("document.querySelector('.editor-instance .native-edit-context, .editor-instance textarea')?.focus()")
    driver.type('edited ')
    driver.command('File: Save')
    wait_for(lambda: 'edited' in read('README.md'), 30, 'the save to reach the remote file')
    check('sshfs_edit_reaches_remote', True, read('README.md'))
    driver.command('SSH FS: Open remote SSH terminal')
    time.sleep(3)
    if driver.rows():
        driver.choose(host)
    time.sleep(6)
    driver.type('(hostname; uname -m) > ssh-term.out')
    driver.enter()
    terminal = wait_for(lambda: read('ssh-term.out'), 30, 'the remote terminal').split()
    check('sshfs_terminal_runs_remotely', terminal == machine, terminal)
    driver.command('Tasks: Run Task')
    time.sleep(4)
    driver.choose('remote-task')
    time.sleep(2)
    if driver.rows():
        driver.enter()
    task = wait_for(lambda: read('ssh-task.out'), 40, 'the remote task').split()
    check('sshfs_task_runs_remotely', task == machine, task)
    driver.screenshot(evidence / 'ssh-fs.png')
    fixture.quit()


def no_server_checks(fixture, check, args):
    root, host = args.ssh_path, args.ssh_host
    fixture.launch('--folder-uri', f'vscode-remote://ssh-remote+{host}{root}')
    log = lambda: fixture.log('1-Remote - SSH.log')
    wait_for(lambda: 'Error resolving authority' in log(), 90, 'the resolver to reach its server step')
    text = log()
    check('resolver_api_active', 'Resolving ssh remote authority' in text, None)
    check('resolver_authenticated_over_ssh', 'Trying publickey authentication' in text and 'Server install command' in text, None)
    check('resolver_stopped_at_server', "Couldn't install vscode server" in text, None)
    check.note('remote_extension_host', 'NOT TESTED: needs --server-url')
    fixture.quit()


def server_checks(fixture, check, evidence, args, machine, read):
    config, host, root = args.ssh_config, args.ssh_host, args.ssh_path
    # A normal window: no extension under development, as a person would open it.
    driver = fixture.launch('--folder-uri', f'vscode-remote://ssh-remote+{host}{root}', secret_probe=False)
    status = lambda: str(driver.evaluate("[...document.querySelectorAll('.statusbar-item')].map(n => n.getAttribute('aria-label')).join(' ')"))
    wait_for(lambda: f'SSH: {host}' in status(), 240, 'the remote connection')
    rows = wait_for(lambda: [r for r in driver.explorer() if 'README' in r] and driver.explorer(), 90, 'the remote extension host')
    check('remote_extension_host_lists_files', 'README.md' in rows, rows)
    editor = json.loads((PREFIX / 'lib/code-oss/resources/app/product.json').read_text())['commit']
    found = run_ssh(config, host, 'cat', f'{root}/.server/bin/{editor}/product.json')
    check('server_commit_is_the_editors', found.returncode == 0 and json.loads(found.stdout)['commit'] == editor, editor)
    check('strict_validation_in_use', json.loads(fixture.settings_path.read_text())['remote.SSH.serverValidation'] == 'strict')

    driver.command('Server Probe: Run')
    probe = json.loads(wait_for(lambda: read('server-probe.json'), 60, 'the workspace extension to run remotely'))
    expected_arch = {'x86_64': 'x64', 'aarch64': 'arm64'}[machine[1]]
    check('workspace_extension_runs_remotely', probe['hostname'] == machine[0] and probe['platform'] == 'linux'
        and probe['arch'] == expected_arch and probe['remoteName'] == 'ssh-remote', probe)
    check('remote_file_search', 'README.md' in probe['files'], probe['files'])
    driver.screenshot(evidence / 'remote-extension-host.png')

    driver.command('Terminal: Create New Terminal')
    time.sleep(8)
    driver.type('(hostname; uname -m) > remote-term.out')
    driver.enter()
    terminal = wait_for(lambda: read('remote-term.out'), 30, 'the terminal').split()
    check('remote_terminal_runs_remotely', terminal == machine, terminal)
    driver.command('Tasks: Run Task')
    time.sleep(4)
    driver.choose('server-task')
    time.sleep(2)
    if driver.rows():
        driver.enter()
    task = wait_for(lambda: read('remote-task.out'), 40, 'the server task').split()
    check('remote_task_runs_remotely', task == machine, task)

    # A real extension from Open VSX, installed by the server, running there, drawn here.
    installed = run_ssh(config, host, 'ls', f'{root}/.server/extensions').stdout.split()
    check('open_vsx_extension_installed_on_server', any(name.startswith('mhutchie.git-graph') for name in installed), installed)
    driver.command('Git Graph: View Git Graph (git log)')
    wait_for(lambda: 'Git Graph' in str(driver.evaluate("document.querySelector('.tab.active')?.getAttribute('aria-label')")), 40, 'the Git Graph tab')
    time.sleep(5)
    logs = run_ssh(config, host, f'find {shlex.quote(root)}/.server -name remoteexthost.log -exec cat {{}} +').stdout
    (evidence / 'remoteexthost.log').write_text(logs)
    check('git_graph_activated_on_server', '_doActivateExtension mhutchie.git-graph' in logs)
    check('built_in_git_activated_on_server', '_doActivateExtension vscode.git,' in logs)
    driver.screenshot(evidence / 'git-graph.png')
    notices = driver.evaluate("[...document.querySelectorAll('.notification-list-item-message')].map(n => n.innerText.slice(0, 200))")
    check('no_warnings_in_server_window', not notices, notices)
    fixture.quit()


def remote_checks(fixture, check, evidence, args):
    config, host, root = args.ssh_config, args.ssh_host, args.ssh_path
    if run_ssh(config, host, 'test', '!', '-e', root).returncode != 0:
        raise RuntimeError(f'{root} already exists on {host}, and this test deletes the folder it uses')
    try:
        (fixture.scratch / 'remote-tasks.json').write_text(json.dumps({'version': '2.0.0', 'tasks': [
            {'label': 'remote-task', 'type': 'ssh-shell', 'host': host, 'command': '(hostname; uname -m) > ssh-task.out', 'problemMatcher': []},
            {'label': 'server-task', 'type': 'shell', 'command': '(hostname; uname -m) > remote-task.out', 'problemMatcher': []}]}))
        subprocess.run(['ssh', '-F', str(config), host,
            f'mkdir -p {root}/.vscode && cd {root} && echo fixture > README.md && cat > .vscode/tasks.json && git init -q -b main '
            '&& git add README.md && git -c user.email=test@example.invalid -c user.name=test commit -q -m "fixture commit" '
            '&& printf ".server\\n*.out\\nserver-probe.json\\n" >> .git/info/exclude'],
            input=(fixture.scratch / 'remote-tasks.json').read_text(), text=True, timeout=60, check=True)
        machine = run_ssh(config, host, 'hostname; uname -m').stdout.split()
        check('remote_machine', len(machine) == 2, machine)
        options = dict(line.split(' ', 1) for line in subprocess.run(['ssh', '-F', str(config), '-G', host],
            capture_output=True, text=True, check=True).stdout.splitlines() if ' ' in line)
        settings = json.loads(fixture.settings_path.read_text())
        settings['sshfs.configs'] = [{'name': host, 'host': options['hostname'], 'port': int(options['port']), 'username': options['user'],
            'privateKeyPath': os.path.expanduser(options['identityfile']), 'root': root}]
        settings['remote.SSH.configFile'] = str(config)
        settings['remote.SSH.serverInstallPath'] = {host: root + '/.server'}
        settings['remote.SSH.serverValidation'] = 'strict'
        settings['remote.SSH.serverDownloadUrlTemplate'] = args.server_url or NO_SERVER
        if args.server_url:
            settings['remote.SSH.defaultExtensions'] = ['mhutchie.git-graph']
        fixture.settings_path.write_text(json.dumps(settings))
        read = lambda name: run_ssh(config, host, 'cat', f'{root}/{name}').stdout
        if args.server_url:
            extension_dir = root + '/.server/extensions/livecd-test.server-probe-0.0.1'
            run_ssh(config, host, 'mkdir', '-p', shlex.quote(extension_dir), check=True)
            for source in (REPO / 'tests/code-oss/server-probe').iterdir():
                subprocess.run(['ssh', '-F', str(config), host, 'cat > ' + shlex.quote(extension_dir + '/' + source.name)],
                    input=source.read_text(), text=True, check=True, timeout=30)

        if not args.server_only:
            ssh_fs_checks(fixture, check, evidence, args, machine, read)
        if args.server_url:
            # Only SSH FS provides ssh-shell, so a server window would report that task as an error.
            subprocess.run(['ssh', '-F', str(config), host, f'cat > {root}/.vscode/tasks.json'], text=True, timeout=30, check=True,
                input=json.dumps({'version': '2.0.0', 'tasks': [t for t in json.loads((fixture.scratch / 'remote-tasks.json').read_text())['tasks']
                    if t['type'] == 'shell']}))
            server_checks(fixture, check, evidence, args, machine, read)
        else:
            no_server_checks(fixture, check, args)
    except Exception:
        fixture.capture_failure(evidence)
        raise
    finally:
        fixture.quit()
        logs = run_ssh(config, host, f'find {shlex.quote(root)}/.server -maxdepth 1 -name ".*.log" -exec tail -40 {{}} +').stdout
        if logs:
            (evidence / 'server-install.log').write_text(logs)
        left = stop_server(config, host, root)
        check('server_stopped_on_remote', left == '0', left)
        run_ssh(config, host, 'rm', '-rf', root)
        check('scratch_folder_removed', run_ssh(config, host, 'test', '!', '-e', root).returncode == 0, root)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--evidence', type=Path, default=Path.home() / '.local/state/livecd-native/code-oss')
    parser.add_argument('--ssh-config', type=Path)
    parser.add_argument('--ssh-host')
    parser.add_argument('--ssh-path')
    parser.add_argument('--server-url')
    parser.add_argument('--remote-only', action='store_true', help='Only run the SSH checks, using a private editor profile')
    parser.add_argument('--server-only', action='store_true', help='Like --remote-only, without the SSH FS checks')
    args = parser.parse_args()
    args.remote_only = args.remote_only or args.server_only
    if args.server_only and not args.server_url:
        parser.error('--server-only needs --server-url')
    if args.remote_only and not args.ssh_host:
        parser.error('--remote-only needs --ssh-host, --ssh-config and --ssh-path')
    if args.ssh_host and not (args.ssh_config and args.ssh_path):
        parser.error('--ssh-host needs --ssh-config and --ssh-path')
    args.evidence.mkdir(parents=True, exist_ok=True)
    checks = {}
    notes = {}

    def check(name, ok, detail=None):
        checks[name] = {'ok': bool(ok), 'detail': detail}
        print(('PASS ' if ok else 'FAIL ') + name, json.dumps(detail, default=str)[:300], flush=True)

    def note(name, detail):
        """Something measured, or not tested, which is neither a pass nor a failure."""
        notes[name] = detail
        print('NOTE ' + name, json.dumps(detail, default=str)[:300], flush=True)

    check.note = note

    scratch = Path(tempfile.mkdtemp(prefix='code-oss-test-', dir=Path.home() / '.cache'))
    fixture = None
    failure = None
    try:
        fixture = Fixture(scratch)
        note('preload', fixture.env.get('LD_PRELOAD'))
        if not args.remote_only:
            local_checks(fixture, check, args.evidence)
        else:
            # SSH FS reads secret storage even with an explicit private key.
            # The normal local checks create this scratch keyring first.
            driver = fixture.launch(str(scratch))
            check('remote_profile_keyring_created', wait_for(lambda: fixture.answer_keyring(True), 60, 'the scratch keyring prompt'))
            driver.settle_first_run()
            fixture.quit()
        if args.ssh_host:
            remote_checks(fixture, check, args.evidence, args)
    except Exception as error:
        failure = f'{type(error).__name__}: {error}'
        print('STOPPED', failure, flush=True)
        if fixture:
            fixture.capture_failure(args.evidence)
    finally:
        if fixture:
            note('launcher_crashes', fixture.launcher_crashes)
            fixture.close()
            # Extension helpers, such as GitLens's gk hook, can take a few seconds to exit.
            deadline = time.monotonic() + 10
            left = fixture.session_pids()
            while left and time.monotonic() < deadline:
                time.sleep(0.5)
                left = fixture.session_pids()
            check('nothing_left_running', not left, left)
            for pid in {*left, *fixture.brokers}:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
        if (scratch / 'editor.log').exists():
            shutil.copy2(scratch / 'editor.log', args.evidence / 'editor.log')
        shutil.rmtree(scratch, ignore_errors=True)
    (args.evidence / 'result.json').write_text(json.dumps({'checks': checks, 'notes': notes, 'stopped': failure}, indent=1, default=str))
    failed = sorted(name for name, result in checks.items() if not result['ok'])
    print(f'{len(checks) - len(failed)} of {len(checks)} passed' + (f'; failed: {failed}' if failed else '') + (f'; stopped: {failure}' if failure else ''))
    return 1 if failed or failure else 0


if __name__ == '__main__':
    sys.exit(main())
