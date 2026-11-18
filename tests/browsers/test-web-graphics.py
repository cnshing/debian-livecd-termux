#!/data/data/com.termux/files/usr/bin/python
"""Check WebGL 1, WebGL 2 and WebGPU in a browser started the way the installed launcher starts it.

The browser runs on a private Termux:X11 display with its own D-Bus session and profile, and a
video socket nobody listens on: nothing touches the live desktop or the shared video daemon.
web-graphics-page.html renders reference pictures and runs compute work whose results are
checked exactly on the CPU (see the page). This script additionally requires:

  - the compositor's screenshot of the page to show each reference canvas (presentation);
  - with --expect hardware (the default), a browser process mapping the GPU driver and holding
    the GPU device, a WebGL renderer naming the GPU, and a WebGPU adapter that is not a fallback;
    with --expect software, no WebGL renderer or WebGPU adapter naming the GPU (negative control:
    run it with LIVECD_<BROWSER>_GPU=0);
  - each page comparison's own control, against a deliberately wrong reference, to have failed.

Pictures are saved as PNG next to result.json: open them, a metric alone is not a pass.

Usage: test-web-graphics.py chromium|chrome|firefox --out NEW_DIRECTORY [--cases webgl1,webgl2,webgpu]
       [--expect hardware|software] [--flag BROWSER_FLAG]... [--pref NAME=JSON]...
"""
import argparse
import base64
import http.server
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

PREFIX = Path('/data/data/com.termux/files/usr')
HERE = Path(__file__).resolve().parent
PAGE = (HERE / 'web-graphics-page.html').read_bytes()
GPU_NAMES = ('adreno', 'turnip', 'mali', 'panvk', 'qualcomm')
SOFTWARE_NAMES = ('swiftshader', 'llvmpipe', 'softpipe', 'lavapipe', 'software')

LAUNCHER = '''#!{python}
import json, os, sys
sys.path.insert(0, {modules!r})
import acceleration
argv, env = acceleration.prepare({profile!r}, [{binary!r}, *sys.argv[1:]], {abi!r}, 'auto')
open({record!r}, 'w').write(json.dumps({{'argv': argv, 'env': {{k: v for k, v in env.items()
    if k.startswith(('VK_', 'TU_', 'MESA', 'LD_', 'BIONILUX', 'GALLIUM', 'MOZ_', '__EGL'))}}}}, indent=1))
os.execve(argv[0], argv, env)
'''


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def wait(check, seconds, what):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError('Timed out waiting for ' + what)


def presented(pixel, left, top, xor=True):
    """Compare the screenshot's canvas region with the page's reference picture."""
    bad, worst = 0, 0
    for y in range(4, 256, 9):
        for x in range(4, 256, 9):
            want = (x, 255 - y, (x ^ y) & 255 if xor else (x + y) & 255)
            got = pixel(left + x, top + y)
            difference = max(abs(a - b) for a, b in zip(got, want))
            worst = max(worst, difference)
            bad += difference > 3
    return {'bad': bad, 'worst': worst, 'ok': bad == 0}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('browser', choices=('chromium', 'chrome', 'firefox'))
    p.add_argument('--out', type=lambda value: Path(value).resolve(), required=True)
    p.add_argument('--cases', default='webgl1,webgl2,webgpu')
    p.add_argument('--expect', choices=('hardware', 'software'), default='hardware')
    p.add_argument('--flag', action='append', default=[], help='extra browser flag (experiments)')
    p.add_argument('--pref', action='append', default=[], help='extra Firefox preference NAME=JSON (experiments)')
    p.add_argument('--url', help='open this page instead of the probe, screenshot it after --dwell seconds')
    p.add_argument('--dwell', type=float, default=20)
    p.add_argument('--text', help='with --url: also record the value of this JavaScript expression')
    p.add_argument('--modules', default=str(Path.home() / '.local/lib/livecd-native'),
                   help='directory of the launcher modules (acceleration.py) to test')
    args = p.parse_args()
    if os.environ.get('LIVECD_WEBGFX_TEST_BUS') != '1':
        # The environment the desktop gives its programs, on a bus of its own. The tested
        # acceleration module is imported first: desktop.py imports it by name.
        sys.path.insert(0, args.modules)
        import acceleration  # noqa: F401
        from desktop import environment
        os.environ['ANDROID_PROCFS_COMPAT'] = '0'
        env = environment('zink')
        for key in ('LIVECD_NATIVE_SESSION', 'XAUTHORITY', 'PULSE_SERVER'):
            env.pop(key, None)
        env['LIVECD_WEBGFX_TEST_BUS'] = '1'
        os.execvpe('dbus-run-session', ['dbus-run-session', '--', sys.executable, *sys.argv], env)
    sys.path.insert(0, args.modules)
    from graphics import process_gpu
    out = args.out
    out.mkdir(parents=True)
    for name in ('config', 'cache', 'data', 'state', 'runtime'):
        (out / name).mkdir(mode=0o700)
    os.environ.update(XDG_CONFIG_HOME=str(out / 'config'), XDG_CACHE_HOME=str(out / 'cache'),
                      XDG_DATA_HOME=str(out / 'data'), XDG_STATE_HOME=str(out / 'state'),
                      XDG_RUNTIME_DIR=str(out / 'runtime'),
                      # A private endpoint with no daemon: the launcher must not start or use the shared one.
                      TERMUX_VA_SOCKET=str(out / 'runtime/no-va.sock'))
    os.environ.setdefault('PREFIX', str(PREFIX))
    probe = module('webgfx_probe', HERE / 'test-browsers.py')
    probe.OUT = out
    probe.wait_for = lambda check, timeout, what: wait(check, timeout, what)
    pixels = module('webgfx_png', HERE / 'test-fullscreen.py').png_pixels
    tag = 'webgfx-test-' + uuid.uuid4().hex
    launch = probe.launch
    crashed = threading.Event()

    def guarded(command, name):
        # Stop at the first GPU-process crash: a browser left restarting it in a loop has
        # brought Android's low-memory killer down on the whole desktop before.
        process = launch(command, name)

        def monitor():
            while process.poll() is None:
                log = out / (name + '.log')
                text = log.read_text(errors='replace') if log.exists() else ''
                if any(m in text for m in ('Check failed:', 'GPU process exited unexpectedly', 'FATAL:')):
                    crashed.set()
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    return
                time.sleep(0.25)
        threading.Thread(target=monitor, daemon=True).start()
        return process
    probe.launch = guarded
    display = next(n for n in range(80, 99) if not (PREFIX / f'tmp/.X11-unix/X{n}').exists()
                   and not (PREFIX / f'tmp/.X{n}-lock').exists())
    os.environ['DISPLAY'] = f':{display}'
    children = []
    result = {'browser': args.browser, 'expect': args.expect, 'display': display, 'flags': args.flag,
              'prefs': args.pref}
    browser = None
    try:
        with (out / 'x-server.log').open('w') as log:
            children.append(subprocess.Popen([str(HERE / 'private-lorie/private-lorie'), f':{display}'],
                                             stdout=log, stderr=log, start_new_session=True))
        wait(lambda: subprocess.run(['xdpyinfo'], capture_output=True).returncode == 0, 60, 'the X server')
        binary = {'chromium': PREFIX / 'lib/chromium/chrome', 'chrome': PREFIX / 'opt/google/chrome/chrome',
                  'firefox': PREFIX / 'bin/firefox'}[args.browser]
        command = out / 'launcher.py'
        command.write_text(LAUNCHER.format(python=sys.executable, modules=args.modules, profile=args.browser,
                                           binary=str(binary), abi='glibc' if args.browser == 'chrome' else 'bionic',
                                           record=str(out / 'argv.json')))
        command.chmod(0o700)

        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(PAGE)

            def log_message(self, *unused):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Page)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        profile = out / 'profile'
        if args.browser == 'firefox':
            profile.mkdir()
            # The launcher manages preferences only in its own profile: apply its decisions here.
            import acceleration
            gpu = acceleration.gpu_enabled('firefox')
            acceleration.firefox_preferences(profile, gpu, False)
            prefs = [tuple((name, json.loads(value))) for name, value in
                     (item.split('=', 1) for item in args.pref)]
            browser = probe.Firefox(command, profile, tag, prefs=prefs, preserve_prefs=True)
        else:
            browser = probe.Chromium(command, profile, tag, ('--enable-logging=stderr', '--ozone-platform=x11',
                '--disable-extensions', '--password-store=basic', '--disable-breakpad', '--disable-crash-reporter',
                '--force-device-scale-factor=1', *args.flag))
        result['version'] = browser.version
        if args.url:
            browser.open(args.url)
            time.sleep(args.dwell)
            browser.screenshot(out / 'page.png')
            result['title'] = browser.evaluate('document.title')
            if args.text:
                (out / 'page.txt').write_text(str(browser.evaluate(args.text)))
            if args.browser != 'firefox':
                result['console_errors'] = browser.evaluate(
                    "[...document.querySelectorAll('pre, .error, #error')].map(e => e.textContent.slice(0, 400))")
        else:
            browser.open(f'http://127.0.0.1:{server.server_address[1]}/?cases=' + args.cases)
            page = wait(lambda: browser.evaluate('window.RESULT'), 240, 'the page')
            time.sleep(1)
            browser.screenshot(out / 'screenshot.png')
            result['page'] = page
        # Which processes really use the GPU, from the kernel.
        records = []
        for pid in probe.tagged(tag):
            try:
                records.append(process_gpu(pid))
            except (OSError, ValueError):
                # Gone, or maps that are not text (Chrome names some mappings in binary).
                pass
        result['gpu_processes'] = [record for record in records if record['driver']]
        browser.quit()
        browser = None
    except Exception as error:
        result['error'] = str(error)
    finally:
        if browser is not None:
            try:
                browser.quit()
            except Exception:
                pass
        probe.stop(tag)
        for child in reversed(children):
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for child in children:
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
        for path in (PREFIX / f'tmp/.X11-unix/X{display}', PREFIX / f'tmp/.X{display}-lock'):
            path.unlink(missing_ok=True)
    result['crashed'] = crashed.is_set()
    page = result.get('page') or {}
    checks = {}
    screenshot = out / 'screenshot.png'
    pixel = pixels(screenshot) if screenshot.exists() and page else None
    for left, name, xor in ((0, 'webgl1', False), (272, 'webgl2', True), (544, 'webgpu', True)):
        case = page.get(name)
        if name not in args.cases.split(',') or case is None:
            continue
        if case.get('png'):
            (out / f'{name}.png').write_bytes(base64.b64decode(case.pop('png').split(',', 1)[1]))
        if name == 'webgpu':
            adapter = json.dumps(case.get('adapter', {})).lower()
            named = any(n in adapter for n in GPU_NAMES)
            if args.browser == 'firefox' and not case.get('adapter', {}).get('description'):
                # Firefox withholds adapter names; rely on its GPU process using the driver instead.
                named = bool(result.get('gpu_processes'))
            software = case.get('adapter', {}).get('fallback') or any(n in adapter for n in SOFTWARE_NAMES)
        else:
            renderer = (str(case.get('renderer')) + ' ' + str(case.get('vendor'))).lower()
            named = any(n in renderer for n in GPU_NAMES)
            software = any(n in renderer for n in SOFTWARE_NAMES)
        hardware = bool(case.get('available') is True and named and not software)
        shown = presented(pixel, left, 0, xor) if pixel and case.get('available') is True else None
        if args.expect == 'hardware':
            ok = bool(case.get('ok')) and hardware and bool(shown and shown['ok'])
        else:
            ok = not hardware
        checks[name] = {'page_ok': case.get('ok'), 'hardware': hardware, 'presented': shown, 'ok': ok}
    result['checks'] = checks
    if args.url:
        result['ok'] = (out / 'page.png').exists() and not result['crashed'] and 'error' not in result
    else:
        gpu_ok = bool(result.get('gpu_processes')) if args.expect == 'hardware' else True
        result['ok'] = (bool(checks) and all(c['ok'] for c in checks.values()) and gpu_ok
                        and not result['crashed'] and 'error' not in result)
    (out / 'result.json').write_text(json.dumps(result, indent=1) + '\n')
    summary = {k: v for k, v in result.items() if k != 'page'}
    summary['cases'] = {k: {kk: vv for kk, vv in v.items() if kk not in ('extensions', 'features')}
                        for k, v in page.items() if isinstance(v, dict)}
    print(json.dumps(summary, indent=1))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
