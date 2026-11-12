#!/data/data/com.termux/files/usr/bin/python
"""Investigate fullscreen crashes in an isolated native GNOME/Xvfb session.

Run directly from Termux, without livecd-native exec. Each invocation allocates
an unused display, private D-Bus, settings, and browser profile. It never starts
or stops the managed desktop. See docs/browsers/fullscreen-investigation.md.
"""
import argparse
import functools
import fcntl
import http.server
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zlib
import urllib.request
import re

from video_oracle import compare, contact_sheet, sha256


# Expected six-bar diagnostic clip colors, left to right.
COLOR_BARS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0), (128, 128, 128))


def png_pixels(path):
    """Decode an 8-bit RGB or RGBA PNG, without needing an imaging library."""
    data = Path(path).read_bytes()
    position, idat = 8, b''
    while position < len(data):
        length = int.from_bytes(data[position:position + 4], 'big')
        kind = data[position + 4:position + 8]
        chunk = data[position + 8:position + 8 + length]
        if kind == b'IHDR':
            width, height = int.from_bytes(chunk[:4], 'big'), int.from_bytes(chunk[4:8], 'big')
            channels = {2: 3, 6: 4}[chunk[9]]
        elif kind == b'IDAT':
            idat += chunk
        position += 12 + length
    raw = zlib.decompress(idat)
    stride = width * channels
    rows, previous = [], bytearray(stride)
    for y in range(height):
        kind = raw[y * (stride + 1)]
        row = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            left = row[x - channels] if x >= channels else 0
            up = previous[x]
            corner = previous[x - channels] if x >= channels else 0
            if kind == 1:
                row[x] = (row[x] + left) & 255
            elif kind == 2:
                row[x] = (row[x] + up) & 255
            elif kind == 3:
                row[x] = (row[x] + (left + up) // 2) & 255
            elif kind == 4:
                guess = left + up - corner
                best = min((left, up, corner), key=lambda v: abs(guess - v))
                row[x] = (row[x] + best) & 255
        rows.append(row)
        previous = row
    return lambda x, y: tuple(rows[y][x * channels:x * channels + 3])


def wait_for(probe, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(0.2)
    raise RuntimeError('Timed out waiting for private display/session')


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def live_state():
    """Identity, including start time, of shared desktop and codec processes."""
    processes = {}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            command = (proc / 'cmdline').read_bytes().split(b'\0')
            executable = Path(command[0].decode()).name if command and command[0] else ''
            env = (proc / 'environ').read_bytes().split(b'\0')
            if any(v.startswith(b'LIVECD_FULLSCREEN_TEST=') for v in env):
                continue
            if executable in ('gnome-shell', 'termux-va', 'termux-x11') or (command and
                    command[0].startswith(b'termux-x11 ')):
                fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
                processes[proc.name] = {'start': fields[19], 'command': [v.decode(errors='replace') for v in command if v]}
        except (OSError, ValueError, IndexError):
            continue
    return {'processes': processes, 'displays': sorted(p.name for p in
        (Path(os.environ['TMPDIR']) / '.X11-unix').glob('X*'))}


def compositor_origin(box, frame_extents):
    """Use X11 client shadow extents when Chrome includes them in outer size."""
    if frame_extents is None:
        return
    left, right, top, bottom = frame_extents
    box['rootX'] = box['screenX'] + left / box['dpr']
    box['rootY'] = box['screenY'] + box['outerHeight'] - box['innerHeight'] - bottom / box['dpr']


def active_frame_extents():
    window = subprocess.run(['xdotool', 'getactivewindow'], capture_output=True, text=True, check=True).stdout.strip()
    value = subprocess.run(['xprop', '-id', window, '_GTK_FRAME_EXTENTS'],
                           capture_output=True, text=True, check=True).stdout
    match = re.search(r'= (\d+), (\d+), (\d+), (\d+)', value)
    return tuple(map(int, match.groups())) if match else None


def worker(args):
    spec = importlib.util.spec_from_file_location('browser_probe', Path(__file__).with_name('test-browsers.py'))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    probe.OUT = args.out
    root = Path.home() / '.local/opt/livecd-native/gnome-48'
    result = {'browser': args.browser, 'renderer': args.renderer,
              'display': os.environ['DISPLAY'], 'mit_shm': not args.disable_shm,
              'cycles_requested': args.cycles, 'cases': [],
              'browser_command': str(args.browser_command) if args.browser_command else None,
              'browser_flags': args.browser_flag, 'require_gpu': args.require_gpu}
    result['composited_fullscreen'] = args.composited_fullscreen
    result['pixel_failures'] = []
    result['command'] = sys.argv
    result['environment'] = {k: v for k, v in os.environ.items() if k.startswith((
        'LIVECD_', 'BIONILUX_', 'TERMUX_VA_', 'LIBVA_', 'VK_', 'MESA_', 'TURNIP_', 'LD_', 'XDG_', 'COGL_', 'GALLIUM_'))
        or k in ('DISPLAY', 'TMPDIR', 'GI_TYPELIB_PATH')}
    fixture_manifest = json.loads(args.fixture_manifest.read_text()) if args.fixture_manifest else None
    sheet = []
    os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = os.environ['DBUS_SESSION_BUS_ADDRESS']
    tag = 'fullscreen-' + args.out.name
    def browser_wait(check, timeout, what):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            pid = probe.SESSIONS.get(tag)
            if pid:
                try:
                    state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
                except FileNotFoundError:
                    state = 'Z'
                if state == 'Z':
                    raise RuntimeError('Browser launcher exited while waiting for ' + what)
            try:
                value = check()
                if value:
                    return value
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                last = error
            time.sleep(0.5)
        raise RuntimeError(f'Timed out waiting for {what}: {last}')

    probe.wait_for = browser_wait
    shell = browser = server = None
    failed = False
    shell_log = (args.out / 'shell.log').open('w')
    try:
        shell_env = os.environ.copy()
        if args.composited_fullscreen:
            # Fullscreen X11 unredirection bypasses GNOME's stage. A stage
            # screenshot can then contain an older frame even though the browser
            # presents correctly. Keep this explicitly scoped to capture tests.
            extension = Path(os.environ['XDG_DATA_HOME']) / 'gnome-shell/extensions/native-video-capture@livecd'
            extension.mkdir(parents=True)
            (extension / 'metadata.json').write_text(json.dumps({'uuid': 'native-video-capture@livecd',
                'name': 'Private video capture', 'description': 'Keep test fullscreen windows composited',
                'shell-version': ['48']}))
            (extension / 'extension.js').write_text("""import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
export default class Capture extends Extension {
enable() { global.compositor.disable_unredirect(); console.log('LIVECD_PRIVATE_FULLSCREEN_REDIRECTED'); }
disable() { global.compositor.enable_unredirect(); }
}
""")
            subprocess.run(['gsettings', 'set', 'org.gnome.shell', 'disable-user-extensions', 'false'], check=True)
            subprocess.run(['gsettings', 'set', 'org.gnome.shell', 'enabled-extensions',
                            "['native-video-capture@livecd']"], check=True)
        if args.shell_preload:
            shell_env['LD_PRELOAD'] = str(args.shell_preload)
        if args.shell_lib_dir:
            shell_env['LD_LIBRARY_PATH'] = str(args.shell_lib_dir) + ':' + shell_env['LD_LIBRARY_PATH']
            shell_env['GI_TYPELIB_PATH'] = str(args.shell_lib_dir) + ':' + shell_env['GI_TYPELIB_PATH']
            shell_env['LIVECD_FULLSCREEN_GI_DIR'] = str(args.shell_lib_dir)
        result['runtime'] = str(root.resolve())
        result['shell_lib_dir'] = str(args.shell_lib_dir) if args.shell_lib_dir else None
        shell = subprocess.Popen([str(root / 'bin/gnome-shell'), '--x11', '--sm-disable'],
                                 env=shell_env, stdout=shell_log, stderr=shell_log)
        result['shell_pid'] = shell.pid

        def ready():
            if shell.poll() is not None:
                raise RuntimeError(f'GNOME Shell exited: {shell.returncode}')
            return '_NET_SUPPORTING_WM_CHECK(WINDOW)' in subprocess.run(
                ['xprop', '-root', '_NET_SUPPORTING_WM_CHECK'], capture_output=True, text=True).stdout

        wait_for(ready, 60)
        result['shell_libraries'] = sorted({line.split()[-1] for line in
            Path(f'/proc/{shell.pid}/maps').read_text().splitlines()
            if any(name in line for name in ('libmutter-cogl', 'libvulkan_freedreno', 'swrast_dri', 'zink_dri'))})
        time.sleep(3)
        if args.composited_fullscreen:
            wait_for(lambda: 'LIVECD_PRIVATE_FULLSCREEN_REDIRECTED' in
                     (args.out / 'shell.log').read_text(), 20)
        if shell.poll() is not None:
            raise RuntimeError(f'GNOME Shell exited during startup: {shell.returncode}')
        subprocess.run(['xdotool', 'key', 'Escape'], check=True)
        browser = probe.Chromium(args.browser_command or probe.BROWSERS[args.browser][0], args.out / 'profile', tag,
            (*([] if args.allow_extensions else ['--disable-extensions']), '--enable-logging=stderr', '--vmodule=*media*=1',
             '--disable-session-crashed-bubble', '--ozone-platform=x11',
             '--password-store=basic', '--disable-background-networking', *args.browser_flag))
        result['version'] = browser.version
        browser.sock.settimeout(20)
        result['media_events'] = []
        receive = browser.receive

        def receive_media():
            reply = receive()
            if reply.get('method', '').startswith('Media.'):
                result['media_events'].append(reply)
            return reply

        browser.receive = receive_media
        browser.call('Media.enable')
        result['webgl_probe'] = browser.evaluate("""(() => {
const result={};for(const name of ['webgl','webgl2']) {
const canvas=document.createElement('canvas');canvas.width=canvas.height=16;
const gl=canvas.getContext(name,{antialias:false});
if(!gl){result[name]={available:false};continue;}
const debug=gl.getExtension('WEBGL_debug_renderer_info');
gl.clearColor(1,0,0,1);gl.clear(gl.COLOR_BUFFER_BIT);
const pixel=new Uint8Array(4);gl.readPixels(0,0,1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);
result[name]={available:true,version:gl.getParameter(gl.VERSION),
renderer:debug?gl.getParameter(debug.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER),
pixel:Array.from(pixel),error:gl.getError(),lost:gl.isContextLost()};
}return result;})()""")
        # SystemInfo belongs to the browser target, not the page target.
        page_socket = browser.sock
        browser.sock = None
        try:
            browser.connect(browser.http('/json/version')['webSocketDebuggerUrl'])
            result['gpu'] = browser.call('SystemInfo.getInfo')
        finally:
            if browser.sock:
                browser.sock.close()
            browser.sock = page_socket

        class Pages(http.server.SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/probe.html':
                    body = b'''<!doctype html><title>Fullscreen compositor probe</title>
<style>html,body{width:100%;height:100%;margin:0;overflow:hidden;background:#234;color:white}
canvas,video{display:block;width:100%;height:100%;object-fit:contain}</style>
<canvas id=c width=640 height=360></canvas><script>
let ctx=c.getContext('2d');function draw(t){ctx.fillStyle=`hsl(${t/20%360} 70% 40%)`;
ctx.fillRect(0,0,640,360);ctx.fillStyle='white';ctx.font='32px sans-serif';
ctx.fillText('Canvas: no video decoder '+Math.round(t),20,100);requestAnimationFrame(draw)};
requestAnimationFrame(draw);</script>'''
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif Path(self.path.split('?', 1)[0]).suffix in ('.webm', '.mp4'):
                    path = Path(self.translate_path(self.path))
                    if not path.is_file():
                        self.send_error(404)
                        return
                    size = path.stat().st_size
                    start, end = 0, size - 1
                    request_range = self.headers.get('Range')
                    if request_range:
                        match = re.fullmatch(r'bytes=(\d+)-(\d*)', request_range)
                        if not match or int(match[1]) >= size:
                            self.send_error(416)
                            return
                        start = int(match[1])
                        end = min(int(match[2]) if match[2] else end, end)
                        if end < start:
                            self.send_error(416)
                            return
                    self.send_response(206 if request_range else 200)
                    self.send_header('Content-Type', self.guess_type(str(path)))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Content-Length', str(end - start + 1))
                    if request_range:
                        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    with path.open('rb') as stream:
                        stream.seek(start)
                        self.wfile.write(stream.read(end - start + 1))
                else:
                    super().do_GET()

            def log_message(self, *unused):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
            functools.partial(Pages, directory=str(args.media_dir or args.out)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        cases = [('canvas', base + '/probe.html', None)]
        if args.media_dir:
            cases += [(p.name, base + '/probe.html', base + '/' + p.name)
                      for p in sorted(args.media_dir.iterdir()) if p.suffix in ('.webm', '.mp4')]
        if args.youtube:
            cases.append(('youtube', args.youtube, None))
        if args.case:
            cases = [case for case in cases if case[0] in args.case]
        if not cases:
            raise RuntimeError('No cases selected')

        def close_other_tabs():
            # A fresh profile opens each extension's welcome tab, once, whenever it finishes
            # installing. A new tab takes the window out of fullscreen, as it would for anyone.
            current = browser.evaluate('location.href')
            pages = [t for t in browser.http('/json/list') if t['type'] == 'page']
            ours = next((t['id'] for t in pages if t['url'] == current), None)
            others = [t for t in pages if t['id'] != ours]
            for target in others:
                urllib.request.urlopen(f'http://127.0.0.1:{browser.port}/json/close/{target["id"]}', timeout=20).read()
            if others:
                result.setdefault('closed_tabs', []).extend(t['url'] for t in others)
                browser.call('Page.bringToFront')

        if args.allow_extensions:
            time.sleep(25)
            close_other_tabs()

        for name, url, media in cases:
            case = {'name': name, 'samples': []}
            result['cases'].append(case)
            print('CASE', name, flush=True)
            print('NAVIGATE', url, flush=True)
            browser.open(url)
            print('LOADED', name, flush=True)
            browser.call('Page.bringToFront')
            if media:
                browser.evaluate("document.querySelector('canvas').remove();"
                    "document.body.innerHTML='<video autoplay muted loop controls></video>';"
                    f"document.querySelector('video').src={json.dumps(media)}")
                if args.fixture_manifest:
                    browser.evaluate("let style=document.createElement('style');style.textContent=" +
                        json.dumps('video::-webkit-media-controls,video::-webkit-media-controls-enclosure{display:none!important}') +
                        ";document.head.append(style)")
            if name == 'youtube':
                # No sign-in, cookies, extensions, or existing browser profile.
                time.sleep(12)
                case['page'] = browser.evaluate('({title:document.title,text:document.body.innerText.slice(0,1500)})')
                case['av1_offered'] = browser.evaluate('''MediaSource.isTypeSupported('video/webm; codecs="av01.0.05M.08"')''')
                browser.evaluate("document.querySelector('video')?.play().catch(()=>{})")
            time.sleep(3)
            # GNOME may finish its startup overview after our first Escape, especially
            # while a hardware decoder is being initialized. Establish window focus
            # before the test transitions; do not dismiss overview during the test.
            subprocess.run(['xdotool', 'key', 'Escape'], check=True)
            browser.call('Page.bringToFront')
            case['active_window_before_cycles'] = subprocess.check_output(
                ['xprop', '-root', '_NET_ACTIVE_WINDOW'], text=True).strip()
            for cycle in range(args.cycles):
                for fullscreen in (True, False):
                    if shell.poll() is not None:
                        raise RuntimeError(f'GNOME Shell exited: {shell.returncode}')
                    if args.allow_extensions:
                        close_other_tabs()
                    expression = ("(document.querySelector('video')||document.querySelector('canvas')||document.documentElement)"
                                  ".requestFullscreen().then(()=>true,e=>String(e))" if fullscreen else
                                  "document.fullscreenElement?document.exitFullscreen().then(()=>true):false")
                    print('TRANSITION', name, cycle, fullscreen, flush=True)
                    reply = browser.call('Runtime.evaluate', expression=expression,
                                         userGesture=True, awaitPromise=True, returnByValue=True)
                    time.sleep(args.dwell)
                    sample = browser.evaluate('''(() => {let v=document.querySelector('video'),q=v?.getVideoPlaybackQuality();
return {fullscreen:!!document.fullscreenElement,video:v?{time:v.currentTime,paused:v.paused,
ready:v.readyState,width:v.videoWidth,height:v.videoHeight,error:v.error?.message,
quality:{totalVideoFrames:q.totalVideoFrames,droppedVideoFrames:q.droppedVideoFrames}}:null}})()''')
                    case['samples'].append({'cycle': cycle, 'requested_fullscreen': fullscreen,
                                            'reply': reply, 'state': sample, 'shell_exit': shell.poll()})
                    print(json.dumps({'case': name, **case['samples'][-1]}), flush=True)
                    if sample['fullscreen'] != fullscreen:
                        raise RuntimeError('Browser did not reach requested fullscreen state')
                    if shell.poll() is not None:
                        raise RuntimeError(f'GNOME Shell exited: {shell.returncode}')
            if media or name == 'youtube':
                videos = [s['state']['video'] for s in case['samples'] if s['state']['video']]
                if (not videos or any(v.get('error') for v in videos)
                        or len({v['quality']['totalVideoFrames'] for v in videos}) < 2):
                    raise RuntimeError('Decoded frames did not advance; playback was not tested')
            case['completed'] = True
            browser.screenshot(args.out / (name + '.png'))
            sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
            from capture import screenshot
            screenshot(args.out / (name + '-shell.png'))
            if args.fixture_manifest and media:
                fixture = next(f for f in fixture_manifest['fixtures'] if f['name'] == name)
                fixture_dir = args.fixture_manifest.parent
                if sha256(args.media_dir / name) != fixture['sha256']:
                    raise RuntimeError('Fixture hash mismatch: ' + name)
                case['pixels'] = []
                # Remove native controls before creating the fullscreen UI. Otherwise
                # Xvfb's software path can retain its controls over a paused frame.
                browser.evaluate("document.querySelector('video').controls=false")
                for index, number in enumerate((fixture['frames'] // 4, fixture['frames'] * 3 // 4)):
                    # Capture a known, paused frame in both window states. The barcode
                    # must independently confirm that the requested seek was presented.
                    browser.evaluate("document.querySelector('video').play().then(()=>true)")
                    expression = ("document.querySelector('video').requestFullscreen()" if index == 0 else
                                  "document.fullscreenElement?document.exitFullscreen():Promise.resolve()")
                    browser.call('Runtime.evaluate', expression=expression, userGesture=True, awaitPromise=True)
                    # Present the resized viewport before pausing for a reference
                    # frame. Otherwise Chrome can retain the old video-layer
                    # transform in the X11 compositor while CDP has the new layout.
                    browser.evaluate("""new Promise((resolve,reject)=>{
document.querySelector('video').requestVideoFrameCallback(()=>
requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))));
setTimeout(()=>reject(Error('No frame after fullscreen layout')),10000)})""")
                    seek = browser.evaluate("""(async () => {let v=document.querySelector('video');v.pause();v.controls=false;
let presented=new Promise((resolve,reject)=>{v.requestVideoFrameCallback((now,m)=>resolve(m));
setTimeout(()=>reject(Error('No frame presented after seek')),10000)});
await new Promise((resolve,reject)=>{v.addEventListener('seeked',resolve,{once:true});
v.addEventListener('error',()=>reject(Error('seek failed')),{once:true});v.currentTime=""" +
                        str((number + .25) / fixture_manifest['fps']) + ";});" +
                        "let metadata=await presented;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));" +
                        "return {metadata,time:v.currentTime,duration:v.duration}})()")
                    # Chrome's fullscreen notification is browser UI, outside CDP's
                    # screenshot but inside the compositor capture. Let it expire.
                    time.sleep(3.5 if index == 0 else .5)
                    box_expression = '''(() => {let v=document.querySelector('video'),r=v.getBoundingClientRect(),
s=Math.min(r.width/v.videoWidth,r.height/v.videoHeight),w=v.videoWidth*s,h=v.videoHeight*s,
b=(outerWidth-innerWidth)/2;return {left:r.left+(r.width-w)/2,top:r.top+(r.height-h)/2,
width:w,height:h,dpr:devicePixelRatio,rootX:screenX+b,rootY:screenY+outerHeight-innerHeight-b,
innerWidth,innerHeight,outerWidth,outerHeight,screenX,screenY}})()'''
                    box = browser.evaluate(box_expression)
                    extents = active_frame_extents()
                    compositor_origin(box, extents)
                    paths = {}
                    record = {'requested_frame': number, 'fullscreen': index == 0, 'seek': seek,
                              'layout_before_capture': box, 'gtk_frame_extents': extents, 'layers': {}}
                    case['pixels'].append(record)
                    # Read actual presentation first. DevTools screenshotting may
                    # temporarily resize/repaint the browser's compositor surface.
                    for layer in ('shell', 'browser'):
                        crop = {key: box[key] * box['dpr'] for key in ('left', 'top', 'width', 'height')}
                        if layer == 'shell':
                            crop['left'] += box['rootX'] * box['dpr']
                            crop['top'] += box['rootY'] * box['dpr']
                        attempts = []
                        for attempt in range(4 if layer == 'shell' else 1):
                            suffix = '' if attempt == 0 else f'-attempt{attempt + 1}'
                            path = args.out / f'{name}-frame{number}-{layer}{suffix}.png'
                            (browser.screenshot if layer == 'browser' else screenshot)(path)
                            record['layout_after_' + layer] = browser.evaluate(box_expression)
                            normalized = path.with_stem(path.stem + '-video')
                            try:
                                outcome = compare(path, crop, fixture_dir, fixture, normalized, number)
                            except (ValueError, subprocess.CalledProcessError) as error:
                                outcome = {'ok': False, 'error': str(error), 'capture': str(path)}
                            attempts.append(outcome)
                            # The browser frame callback precedes GNOME's asynchronous
                            # stage capture. Bound the wait for that exact frame; never
                            # accept a different frame or retry away a pixel mismatch.
                            if 'error' not in outcome:
                                break
                            time.sleep(.25)
                        record['layers'][layer] = {**outcome, 'attempts': attempts}
                        if normalized.exists():
                            paths[layer] = normalized
                    reference = fixture_dir / fixture['references'] / f'{number:03d}.png'
                    sheet.extend([reference, *(paths[k] for k in ('browser', 'shell') if k in paths)])
                if not all(layer['ok'] for record in case['pixels'] for layer in record['layers'].values()):
                    result['pixel_failures'].append(name)
            if args.check_colors and media:
                # Frame counts and decoder names pass even when a picture is wrong. Compare
                # what was composited with what the clip contains.
                box = browser.evaluate('''(() => {let v=document.querySelector('video'),r=v.getBoundingClientRect(),
s=Math.min(r.width/v.videoWidth,r.height/v.videoHeight),w=v.videoWidth*s,h=v.videoHeight*s;
return {left:r.left+(r.width-w)/2,top:r.top+(r.height-h)/2,width:w,height:h,dpr:devicePixelRatio}})()''')
                pixel = png_pixels(args.out / (name + '.png'))
                case['colors'] = []
                for index, want in enumerate(COLOR_BARS):
                    x = int((box['left'] + box['width'] * (index + .5) / len(COLOR_BARS)) * box['dpr'])
                    y = int((box['top'] + box['height'] / 2) * box['dpr'])
                    case['colors'].append({'expected': want, 'seen': pixel(x, y)})
                wrong = [c for c in case['colors'] if max(abs(a - b) for a, b in zip(c['expected'], c['seen'])) > 48]
                if wrong:
                    raise RuntimeError(f'Video colors are wrong: {wrong}')
            if shell.poll() is not None:
                raise RuntimeError(f'GNOME Shell exited: {shell.returncode}')
        if args.require_gpu:
            # GPU initialization may still be in progress when DevTools first opens.
            # Probe after rendering content, rather than accepting startup state.
            page_socket = browser.sock
            browser.sock = None
            try:
                browser.connect(browser.http('/json/version')['webSocketDebuggerUrl'])
                result['gpu_after_playback'] = browser.call('SystemInfo.getInfo')
            finally:
                if browser.sock:
                    browser.sock.close()
                browser.sock = page_socket
            gpu = result['gpu_after_playback']['gpu']
            renderer = gpu.get('auxAttributes', {}).get('glRenderer', '')
            if (not any(name in renderer.lower() for name in ('turnip', 'freedreno')) or
                    gpu.get('featureStatus', {}).get('gpu_compositing') != 'enabled'):
                raise RuntimeError('Adreno GPU compositing was not enabled: ' + renderer)
            # The browser's own report can outlive a GPU process that fell back. Require
            # a process that actually holds the GPU device with the driver mapped.
            result['gpu_processes'] = []
            for pid in probe.tagged(tag):
                proc = Path(f'/proc/{pid}')
                try:
                    # Chrome's mappings can have names that are not valid UTF-8.
                    drivers = {line.split()[-1] for line in (proc / 'maps').read_text(errors='replace').splitlines()
                               if 'libvulkan_freedreno.so' in line or 'libgallium' in line}
                    devices = []
                    for path in (proc / 'fd').iterdir():
                        try:
                            if os.readlink(path) == '/dev/kgsl-3d0':
                                devices.append(int(path.name))
                        except OSError:
                            pass
                except OSError:
                    continue  # It exited, or is mid-exec and briefly unreadable.
                if drivers and devices:
                    result['gpu_processes'].append({'pid': pid, 'drivers': sorted(drivers), 'kgsl_fds': devices,
                        'command': (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')[:200]})
            if not result['gpu_processes']:
                raise RuntimeError('No browser process holds /dev/kgsl-3d0 with a GPU driver mapped')
            result['gpu_verified'] = True
        if args.require_hardware_decode:
            decoders = {item['value'] for event in result['media_events'] if event.get('method') == 'Media.playerPropertiesChanged'
                        for item in event['params']['properties'] if item['name'] == 'kVideoDecoderName'}
            result['video_decoders'] = sorted(decoders)
            if decoders != {'VaapiVideoDecoder'}:
                raise RuntimeError(f'Video was not decoded only in hardware: {sorted(decoders)}')
            result['hardware_decode_verified'] = True
        if result['pixel_failures']:
            raise RuntimeError('Video pixels differ from reference: ' + ', '.join(result['pixel_failures']))
        result['ok'] = True
    except Exception as error:
        traceback.print_exc()
        result['error'] = repr(error)
        result['ok'] = False
        failed = True
        print('FAIL', repr(error), flush=True)
    finally:
        result['video_decoders'] = sorted({item['value'] for event in result.get('media_events', [])
            if event.get('method') == 'Media.playerPropertiesChanged'
            for item in event['params']['properties'] if item['name'] == 'kVideoDecoderName'})
        result['browser_processes'] = []
        for pid in probe.tagged(tag):
            try:
                command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                proc = Path(f'/proc/{pid}')
                drivers = sorted({line.split()[-1] for line in (proc / 'maps').read_text(errors='replace').splitlines()
                    if any(name in line.lower() for name in ('vulkan', 'mali', 'angle', 'libegl', 'libgles',
                                                            'libgallium', 'termuxva', 'libva.'))})
                devices = {}
                for fd in (proc / 'fd').iterdir():
                    try:
                        target = os.readlink(fd)
                        if target.startswith(('/dev/mali', '/dev/kgsl', '/dev/dri')):
                            devices[fd.name] = target
                    except OSError:
                        pass
                result['browser_processes'].append({'pid': pid,
                    'command': [c.decode(errors='replace') for c in command if c],
                    'driver_libraries': drivers, 'gpu_device_fds': devices})
            except OSError:
                pass
        result['shell_exit_before_cleanup'] = shell.poll() if shell else None
        if browser:
            try:
                browser.quit()
            except Exception:
                pass
        probe.stop(tag, grace=0)
        if shell:
            stop(shell)
        if server:
            server.shutdown()
        shell_log.close()
        try:
            contact_sheet(sheet, args.out / 'contact-sheet.png')
        except Exception as error:
            result['contact_sheet_error'] = repr(error)
            result['ok'] = False
            failed = True
        (args.out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print('RESULT', args.out, 'FAIL' if failed else 'PASS', flush=True)
    return int(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('browser', choices=('chrome', 'chromium', 'ungoogled-chromium'))
    parser.add_argument('--renderer', choices=('software', 'zink'), default='zink')
    parser.add_argument('--disable-shm', action='store_true')
    parser.add_argument('--x-server', choices=('xvfb', 'lorie'), default='xvfb',
                        help="lorie privately runs Termux:X11's server, which has the DRI3 that Xvfb lacks")
    parser.add_argument('--x-server-flag', action='append', default=[],
                        help='Extra private X server argument (recorded in the command)')
    parser.add_argument('--cycles', type=int, default=6)
    parser.add_argument('--dwell', type=float, default=1)
    parser.add_argument('--media-dir', type=lambda p: Path(p).resolve())
    parser.add_argument('--fixture-manifest', type=lambda p: Path(p).resolve(),
                        help='Compare numbered frames at browser and compositor layers against pinned references')
    parser.add_argument('--private-daemon', action='store_true',
                        help='Own a private termux-va process; never call its global start/stop scripts')
    parser.add_argument('--composited-fullscreen', action='store_true',
                        help='Disable unredirection only in the private shell so stage captures include current fullscreen frames')
    parser.add_argument('--youtube', help='Optional public YouTube watch URL')
    parser.add_argument('--browser-flag', action='append', default=[])
    parser.add_argument('--allow-extensions', action='store_true',
                        help='Keep extensions from the browser\'s system directory enabled')
    parser.add_argument('--browser-command', type=lambda p: Path(p).resolve(),
                        help='Use an alternate browser launcher, preserving the isolated test profile')
    parser.add_argument('--require-gpu', action='store_true',
                        help='Fail unless final browser status reports enabled Adreno GPU compositing')
    parser.add_argument('--check-colors', action='store_true',
                        help='Fail unless a color bar clip is composited with the right colors')
    parser.add_argument('--require-hardware-decode', action='store_true',
                        help='Fail unless every video used the VA-API decoder')
    parser.add_argument('--shell-preload', type=lambda p: Path(p).resolve(),
                        help='Optional diagnostic library, applied only to the private shell')
    parser.add_argument('--shell-lib-dir', type=lambda p: Path(p).resolve(),
                        help='Optional experimental library directory, applied only to the private shell')
    parser.add_argument('--case', action='append', help='Run only a named case (canvas, youtube, or media filename)')
    parser.add_argument('--out', type=lambda p: Path(p).resolve())
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args)
    if args.browser in ('chromium', 'ungoogled-chromium') and args.require_hardware_decode:
        receipt = Path('/data/data/com.termux/files/usr/opt/livecd-browsers') / args.browser / 'livecd-vaapi.json'
        if not receipt.is_file() and args.browser == 'chromium':
            receipt = Path('/data/data/com.termux/files/usr/share/doc/chromium/livecd-vaapi.json')
        try:
            build = json.loads(receipt.read_text())
        except (OSError, ValueError):
            parser.error('Hardware browser checks require the installed VA-API-enabled build receipt')
        if build.get('format') != 1 or build.get('vaapi') is not True:
            parser.error('Installed Chromium does not have the required VA-API build receipt')
    if args.cycles < 1 or args.dwell <= 0:
        parser.error('cycles and dwell must be positive')
    if args.fixture_manifest and not args.media_dir:
        parser.error('--fixture-manifest requires --media-dir')
    if args.fixture_manifest and not args.fixture_manifest.is_file():
        parser.error('Fixture manifest does not exist')
    if args.shell_lib_dir and not args.shell_preload:
        parser.error('--shell-lib-dir requires --shell-preload to redirect the introspection search path')
    if args.disable_shm and args.x_server == 'lorie':
        parser.error('--disable-shm applies only to Xvfb')
    if args.out is None:
        args.out = Path(tempfile.mkdtemp(prefix='fullscreen-', dir=os.environ['TMPDIR']))
    else:
        args.out.mkdir(parents=True, exist_ok=False)
    print('OUTPUT', args.out, flush=True)
    # Keep display allocation and before/after process snapshots exclusive.
    # Separate invocations otherwise race on X sockets and count each other's
    # private desktops as changes to shared state. The parent owns this lock.
    session_lock = (Path(os.environ['TMPDIR']) / 'livecd-fullscreen-test.lock').open('a')
    fcntl.flock(session_lock, fcntl.LOCK_EX)
    before = live_state()
    sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
    from desktop import environment
    env = environment(args.renderer)
    env.pop('LIVECD_NATIVE_SESSION', None)
    env.pop('XAUTHORITY', None)
    for name in ('config', 'data', 'cache', 'runtime', 'state'):
        directory = args.out / name
        directory.mkdir(mode=0o700)
        env['XDG_' + name.upper() + ('_DIR' if name == 'runtime' else '_HOME')] = str(directory)
    dconf = args.out / 'dconf-profile'
    dconf.write_text('user-db:user\n')
    env.update(DCONF_PROFILE=str(dconf), MUTTER_SYNC='1',
               LIVECD_FULLSCREEN_TEST=str(args.out))
    # Always supply an endpoint, even in software tests, to prevent accidental use of
    # the global start helper. A missing private daemon is a deliberate absent endpoint.
    endpoint = tempfile.TemporaryDirectory(prefix='video-va-', dir=os.environ['TMPDIR'])
    env['TERMUX_VA_SOCKET'] = str(Path(endpoint.name) / 'va.sock')
    # Keep this process, its D-Bus services and browser children off display :0.
    display = next(n for n in range(71, 100) if not any(p.exists() for p in
        (Path(os.environ['TMPDIR']) / f'.X11-unix/X{n}', Path(os.environ['TMPDIR']) / f'.X{n}-lock')))
    env['DISPLAY'] = ':' + str(display)
    with (args.out / 'xvfb.log').open('w') as log:
        server_env = env.copy()
        from graphics import apply_renderer
        apply_renderer(server_env, 'software')
        xvfb = subprocess.Popen([str(Path(__file__).resolve().with_name('private-lorie') / 'private-lorie'), env['DISPLAY'],
                                *args.x_server_flag]
            if args.x_server == 'lorie' else ['Xvfb', env['DISPLAY'], '-screen', '0', '1280x720x24',
            '-nolisten', 'tcp', *(['-extension', 'MIT-SHM'] if args.disable_shm else []), *args.x_server_flag],
            env=server_env, stdout=log, stderr=log)
        session = daemon = None
        daemon_log = None
        try:
            def ready():
                if xvfb.poll() is not None:
                    raise RuntimeError('Private X server failed; see xvfb.log')
                return subprocess.run(['xdpyinfo'], env=env, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL).returncode == 0
            wait_for(ready)
            if args.private_daemon:
                daemon_log = (args.out / 'daemon.log').open('w')
                daemon = subprocess.Popen(['termux-va'], env={**os.environ,
                    'TERMUX_VA_SOCKET': env['TERMUX_VA_SOCKET'], 'LIVECD_FULLSCREEN_TEST': str(args.out)},
                    stdout=daemon_log, stderr=daemon_log)
                def daemon_ready():
                    if daemon.poll() is not None:
                        raise RuntimeError('Private daemon exited; see daemon.log')
                    return Path(env['TERMUX_VA_SOCKET']).is_socket()
                wait_for(daemon_ready)
            command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:],
                       '--out', str(args.out), '--worker']
            session = subprocess.Popen(['dbus-run-session', '--', *command], env=env, start_new_session=True)
            code = session.wait()
        finally:
            if session:
                try:
                    os.killpg(session.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            stop(xvfb)
            if daemon:
                stop(daemon)
            if daemon_log:
                daemon_log.close()
            endpoint.cleanup()
            if args.x_server == 'lorie':
                # Unlike Xvfb, this server leaves its display behind when it is signalled.
                for path in (f'.X11-unix/X{display}', f'.X{display}-lock'):
                    (Path(os.environ['TMPDIR']) / path).unlink(missing_ok=True)
            after = live_state()
            isolation = {'before': before, 'after': after, 'ok': before == after,
                         'android_focus': 'Check externally using adb; app UID cannot query it'}
            (args.out / 'isolation.json').write_text(json.dumps(isolation, indent=2) + '\n')
        return code if before == after else 1


if __name__ == '__main__':
    sys.exit(main())
