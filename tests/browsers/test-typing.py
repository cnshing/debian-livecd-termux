#!/data/data/com.termux/files/usr/bin/python
"""Type into a browser with real X11 key events and check, after every key, both the page's
text and the picture the X server shows (docs/native/handoff/note10-chrome-typing.md).

The browser runs on a private Termux:X11 display, started the way the installed launcher starts
it, with its own profile, D-Bus session and an unused video socket: nothing touches :0.

Every typed character is an "I", drawn red in a large monospace font with no caret, so the
glyphs on screen are separate red bars. After each key and a short random wait, the X server's
picture is grabbed and the bars are counted:

  - text wrong   (page value != typed)      -> input lost or reordered (cause 2)
  - picture wrong (bars != characters in the page) -> stale presentation (cause 1)

Each check is retried after --settle seconds, to tell a late picture from a wrong one. Two
fields: a <textarea>, and a contenteditable whose input handler rewrites its DOM on every key
(as ProseMirror does). The first frames of every line are saved as PNG: open them.

Usage: test-typing.py chrome|chromium --out NEW_DIRECTORY [--keys 120] [--flag FLAG]...
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
import uuid

PREFIX = Path('/data/data/com.termux/files/usr')
HERE = Path(__file__).resolve().parent
PER_LINE = 24

PAGE = b'''<!doctype html><meta charset="utf-8"><title>typing</title>
<style>
html,body{margin:0;background:#fff}
#t,#e{display:block;box-sizing:border-box;width:1150px;height:90px;margin:10px;padding:10px;border:0;
  outline:none;resize:none;overflow:hidden;background:#fff;color:#f00;caret-color:transparent;
  font:56px/70px monospace;white-space:pre}
#e p{margin:0}
</style>
<textarea id="t" spellcheck="false" autocomplete="off"></textarea>
<div id="e" contenteditable="true" spellcheck="false"><p><br></p></div>
<script>
// Rewrite the editable's DOM on every input and put the caret back at the end, as rich
// editors such as ProseMirror do.
const e = document.getElementById('e');
e.addEventListener('input', () => {
  const text = e.textContent;
  e.innerHTML = '';
  const p = document.createElement('p');
  p.textContent = text;
  if (!text) p.appendChild(document.createElement('br'));
  e.appendChild(p);
  const range = document.createRange();
  range.selectNodeContents(p);
  range.collapse(false);
  const selection = getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
});
window.LOG = [];
for (const kind of ['keydown', 'keyup', 'input', 'compositionstart', 'compositionend'])
  document.addEventListener(kind, ev => LOG.push([kind, ev.key || ev.data || '', performance.now()]), true);
</script>'''


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
        time.sleep(0.3)
    raise RuntimeError('Timed out waiting for ' + what)


def grab(size, top, height):
    """The X server's picture of rows top..top+height, as RGB bytes."""
    width = size[0]
    data = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab',
        '-video_size', f'{width}x{height}', '-grab_x', '0', '-grab_y', str(top), '-i', os.environ['DISPLAY'],
        '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], check=True, capture_output=True).stdout
    return width, height, data


def bars(picture):
    """The largest number of separate red runs on any row: the glyphs drawn."""
    width, height, data = picture
    best = 0
    for y in range(height):
        row = data[y * width * 3:(y + 1) * width * 3]
        runs, inside = 0, False
        for x in range(width):
            r, g, b = row[3 * x], row[3 * x + 1], row[3 * x + 2]
            red = r > 180 and g < 110 and b < 110
            runs += red and not inside
            inside = red
        best = max(best, runs)
    return best


def save_png(picture, path):
    width, height, data = picture
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                    '-video_size', f'{width}x{height}', '-i', '-', '-y', str(path)], input=data, check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('browser', choices=('chromium', 'chrome'))
    p.add_argument('--out', type=lambda value: Path(value).resolve(), required=True)
    p.add_argument('--keys', type=int, default=120, help='keys typed into each field')
    p.add_argument('--settle', type=float, default=1.2)
    p.add_argument('--flag', action='append', default=[], help='extra browser flag (experiments)')
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--modules', default=str(Path.home() / '.local/lib/livecd-native'))
    args = p.parse_args()
    if os.environ.get('LIVECD_TYPING_TEST_BUS') != '1':
        sys.path.insert(0, args.modules)
        import acceleration  # noqa: F401
        from desktop import environment
        os.environ['ANDROID_PROCFS_COMPAT'] = '0'
        env = environment('zink')
        for key in ('LIVECD_NATIVE_SESSION', 'XAUTHORITY', 'PULSE_SERVER'):
            env.pop(key, None)
        env['LIVECD_TYPING_TEST_BUS'] = '1'
        os.execvpe('dbus-run-session', ['dbus-run-session', '--', sys.executable, *sys.argv], env)
    graphics = module('typing_graphics', HERE / 'test-web-graphics.py')
    out = args.out
    out.mkdir(parents=True)
    for name in ('config', 'cache', 'data', 'state', 'runtime'):
        (out / name).mkdir(mode=0o700)
    os.environ.update(XDG_CONFIG_HOME=str(out / 'config'), XDG_CACHE_HOME=str(out / 'cache'),
                      XDG_DATA_HOME=str(out / 'data'), XDG_STATE_HOME=str(out / 'state'),
                      XDG_RUNTIME_DIR=str(out / 'runtime'), TERMUX_VA_SOCKET=str(out / 'runtime/no-va.sock'))
    for key in ('GTK_IM_MODULE', 'XMODIFIERS', 'QT_IM_MODULE'):
        os.environ.pop(key, None)
    os.environ.setdefault('PREFIX', str(PREFIX))
    probe = module('typing_probe', HERE / 'test-browsers.py')
    probe.OUT = out
    probe.wait_for = lambda check, timeout, what: wait(check, timeout, what)
    tag = 'typing-test-' + uuid.uuid4().hex
    display = next(n for n in range(80, 99) if not (PREFIX / f'tmp/.X11-unix/X{n}').exists()
                   and not (PREFIX / f'tmp/.X{n}-lock').exists())
    os.environ['DISPLAY'] = f':{display}'
    rng = random.Random(args.seed)
    children, browser = [], None
    result = {'browser': args.browser, 'flags': args.flag, 'display': display, 'fields': {}}
    try:
        with (out / 'x-server.log').open('w') as log:
            children.append(subprocess.Popen([str(HERE / 'private-lorie/private-lorie'), f':{display}'],
                                             stdout=log, stderr=log, start_new_session=True))
        wait(lambda: subprocess.run(['xdpyinfo'], capture_output=True).returncode == 0, 60, 'the X server')
        size = tuple(map(int, subprocess.check_output(['xdpyinfo'], text=True).split('dimensions:')[1].split()[0].split('x')))
        binary = {'chromium': PREFIX / 'lib/chromium/chrome', 'chrome': PREFIX / 'opt/google/chrome/chrome'}[args.browser]
        command = out / 'launcher.py'
        command.write_text(graphics.LAUNCHER.format(python=sys.executable, modules=args.modules, profile=args.browser,
            binary=str(binary), abi='glibc' if args.browser == 'chrome' else 'bionic', record=str(out / 'argv.json')))
        command.chmod(0o700)
        page = out / 'page.html'
        page.write_bytes(PAGE)
        browser = probe.Chromium(command, out / 'profile', tag, ('--enable-logging=stderr', '--ozone-platform=x11',
            '--disable-extensions', '--password-store=basic', '--disable-breakpad', '--disable-crash-reporter',
            '--force-device-scale-factor=1', '--window-position=0,0', *args.flag))
        result['version'] = browser.version
        browser.open(page.as_uri())
        wait(lambda: browser.evaluate('document.readyState') == 'complete', 30, 'the page')
        for field in ('t', 'e'):
            rect = browser.evaluate(f"(r => [r.top, r.height])(document.getElementById('{field}').getBoundingClientRect())")
            chrome_top = browser.evaluate('window.outerHeight - window.innerHeight')
            top, height = int(chrome_top + rect[0]), int(rect[1])
            value = f"document.getElementById('{field}')." + ('value' if field == 't' else 'textContent')
            # A real click: with no window manager, Chrome takes the X input focus itself.
            probe.xdotool('mousemove', 300, top + height // 2, 'click', 1)
            time.sleep(0.3)
            probe.xdotool('mousemove', size[0] - 5, size[1] - 5)
            time.sleep(0.5)
            empty = bars(grab(size, top, height))
            typed, events = '', []
            (out / field).mkdir()
            for index in range(args.keys):
                if index and index % PER_LINE == 0:
                    probe.xdotool('key', 'ctrl+a', 'BackSpace')
                    time.sleep(0.4)
                    typed = ''
                probe.xdotool('key', 'I')
                typed += 'I'
                delay = rng.uniform(0.03, 0.35)
                time.sleep(delay)
                picture = grab(size, top, height)
                text = browser.evaluate(value)
                seen = bars(picture) - empty
                event = {'i': index, 'delay': round(delay, 3), 'typed': len(typed), 'text': len(text), 'bars': seen}
                if seen != len(text) or text != typed:
                    save_png(picture, out / field / f'{index:04d}-bad.png')
                    time.sleep(args.settle)
                    later = grab(size, top, height)
                    event['bars_later'] = bars(later) - empty
                    event['text_later'] = len(browser.evaluate(value))
                    save_png(later, out / field / f'{index:04d}-later.png')
                elif index % PER_LINE < 3:
                    save_png(picture, out / field / f'{index:04d}.png')
                events.append(event)
            wrong_text = [e for e in events if e['text'] != e['typed']]
            stale = [e for e in events if e['bars'] != e['text']]
            result['fields'][field] = {'events': events, 'empty_bars': empty, 'wrong_text': len(wrong_text),
                                       'stale_picture': len(stale),
                                       'stale_recovered': sum(e.get('bars_later') == e.get('text_later') for e in stale)}
            result['fields'][field]['log_tail'] = browser.evaluate('LOG.slice(-12)')
        browser.quit()
        browser = None
    except Exception as error:
        result['error'] = repr(error)
    finally:
        if browser is not None:
            try:
                browser.quit()
            except Exception:
                pass
        probe.stop(tag)
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
        for path in (PREFIX / f'tmp/.X11-unix/X{display}', PREFIX / f'tmp/.X{display}-lock'):
            path.unlink(missing_ok=True)
    (out / 'result.json').write_text(json.dumps(result, indent=1) + '\n')
    print(json.dumps({k: ({f: {kk: vv for kk, vv in v.items() if kk != 'events'} for f, v in val.items()}
                          if k == 'fields' else val) for k, val in result.items()}, indent=1))
    fields = result['fields'].values()
    return 0 if fields and 'error' not in result and not any(f['wrong_text'] or f['stale_picture'] for f in fields) else 1


if __name__ == '__main__':
    sys.exit(main())
