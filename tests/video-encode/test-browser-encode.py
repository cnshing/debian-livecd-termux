#!/data/data/com.termux/files/usr/bin/python
"""Check a browser's video encoder the way the installed launcher starts it.

The browser runs on a private Termux:X11 display with its own D-Bus session, profile and
termux-va daemon. Nothing touches the live desktop, its browser profiles or the shared daemon.

  webrtc         a canvas goes through an RTCPeerConnection loopback; the received picture must
                 have the sent size (a 640x360 call that arrives as 640x368 fails) and the sent
                 colours down to its last rows.
  mediarecorder  the canvas is recorded for three seconds; the file must decode in software to
                 pictures of the sent size and colours.

With --expect hardware (the default) the private daemon must also have run an encoder session
on a hardware component with pictures in and out. With --expect software it must have run none.
The received picture is saved as PNG: open it, a metric alone is not a pass.

Usage: test-browser-encode.py chromium|chrome|firefox --out NEW_DIRECTORY [--mode webrtc]
       [--codec h264] [--expect hardware|software]
"""
import argparse
import base64
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

PREFIX = Path('/data/data/com.termux/files/usr')
HERE = Path(__file__).resolve().parent
BROWSERS = HERE.parent / 'browsers'

PAGE = '''<!doctype html><title>encode probe</title><body><script>
const W = %(width)d, H = %(height)d, sleep = ms => new Promise(r => setTimeout(r, ms));
const c = document.createElement('canvas'); c.width = W; c.height = H;
const g = c.getContext('2d'); let n = 0;
// A hue field with a moving white bar: every row carries the same colour, so a band of
// padding at the bottom of a received picture shows as a different colour there.
setInterval(() => { g.fillStyle = `hsl(${(n * 7) %% 360} 70%% 45%%)`; g.fillRect(0, 0, W, H);
  g.fillStyle = 'white'; g.fillRect((n * 8) %% W, 0, 48, H); n++; }, 33);
const stream = c.captureStream(30);
function sample(source, width, height) {
  const k = document.createElement('canvas'); k.width = width; k.height = height;
  const kg = k.getContext('2d'); kg.drawImage(source, 0, 0, width, height);
  const row = kg.getImageData(0, height >> 1, width, 1).data; let best = 0, bar = 0;
  for (let x = 0; x < width; x++) { const s = row[x * 4] + row[x * 4 + 1] + row[x * 4 + 2]; if (s > best) { best = s; bar = x; } }
  const x = (bar + (width >> 1)) %% width, out = [];
  for (const y of [2, height >> 1, height - 2]) {
    const p = kg.getImageData(x, y, 1, 1).data, r = p[0] / 255, gg = p[1] / 255, b = p[2] / 255;
    const mx = Math.max(r, gg, b), mn = Math.min(r, gg, b), l = (mx + mn) / 2;
    out.push({y, rgb: [p[0], p[1], p[2]], s: +(mx === mn ? 0 : (mx - mn) / (1 - Math.abs(2 * l - 1))).toFixed(2), l: +l.toFixed(2)});
  }
  return {samples: out, png: k.toDataURL('image/png')};
}
const good = q => Math.abs(q.s - 0.7) < 0.12 && Math.abs(q.l - 0.45) < 0.08;
async function webrtc(codec) {
  const pc1 = new RTCPeerConnection(), pc2 = new RTCPeerConnection(); let c1 = 0, c2 = 0;
  pc1.onicecandidate = e => { if (e.candidate) { c1++; pc2.addIceCandidate(e.candidate); } };
  pc2.onicecandidate = e => { if (e.candidate) { c2++; pc1.addIceCandidate(e.candidate); } };
  const tr = pc1.addTransceiver(stream.getVideoTracks()[0], {direction: 'sendonly'});
  const caps = RTCRtpSender.getCapabilities('video').codecs.filter(x => x.mimeType.toLowerCase() === 'video/' + codec);
  if (!caps.length) return {codec, error: 'codec not offered'};
  tr.setCodecPreferences(caps);
  const o = await pc1.createOffer(); await pc1.setLocalDescription(o); await pc2.setRemoteDescription(o);
  const a = await pc2.createAnswer(); await pc2.setLocalDescription(a); await pc1.setRemoteDescription(a);
  const v = document.createElement('video'); v.muted = true; v.autoplay = true; document.body.append(v);
  pc2.getReceivers().forEach(r => { v.srcObject = new MediaStream([r.track]); });
  await sleep(8000);
  const shots = []; let png = null;
  for (let t = 0; t < 5; t++) { const s = sample(v, v.videoWidth || W, v.videoHeight || H); shots.push(s.samples); png = s.png; await sleep(300); }
  const out = {codec, candidates: [c1, c2], ice: pc1.iceConnectionState, received: [v.videoWidth, v.videoHeight], samples: shots, png};
  out.picture_ok = v.videoWidth === W && v.videoHeight === H && shots.every(s => s.every(good));
  (await pc1.getStats()).forEach(s => { if (s.type === 'outbound-rtp' && s.kind === 'video')
    Object.assign(out, {encoder: s.encoderImplementation, powerEfficientEncoder: s.powerEfficientEncoder,
      framesEncoded: s.framesEncoded, frameWidth: s.frameWidth, frameHeight: s.frameHeight}); });
  (await pc2.getStats()).forEach(s => { if (s.type === 'inbound-rtp' && s.kind === 'video')
    Object.assign(out, {decoder: s.decoderImplementation, framesDecoded: s.framesDecoded}); });
  pc1.close(); pc2.close(); v.remove();
  return out;
}
async function mediarecorder(codec) {
  const types = {h264: ['video/mp4;codecs=avc1.42E01E', 'video/x-matroska;codecs=avc1', 'video/webm;codecs=h264'],
    vp8: ['video/webm;codecs=vp8'], vp9: ['video/webm;codecs=vp9'], hevc: ['video/mp4;codecs=hvc1.1.6.L93.B0']}[codec] || [];
  const type = types.find(t => MediaRecorder.isTypeSupported(t));
  if (!type) return {codec, error: 'no recordable type'};
  const recorder = new MediaRecorder(stream, {mimeType: type, videoBitsPerSecond: 2000000}), parts = [];
  recorder.ondataavailable = e => parts.push(e.data);
  const stopped = new Promise(r => recorder.onstop = r);
  recorder.start(); await sleep(3000); recorder.stop(); await stopped;
  const bytes = new Uint8Array(await new Blob(parts).arrayBuffer()); let text = '';
  for (let i = 0; i < bytes.length; i += 32768) text += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
  return {codec, type, size: bytes.length, recording: btoa(text)};
}
(async () => { const q = new URLSearchParams(location.search), r = [];
  for (const k of q.get('codecs').split(',')) {
    try { r.push(await (q.get('mode') === 'mediarecorder' ? mediarecorder(k) : webrtc(k))); }
    catch (e) { r.push({codec: k, error: String(e)}); } }
  window.RESULT = r; })();
</script>'''

LAUNCHER = '''#!{python}
import json, os, sys
sys.path.insert(0, {modules!r})
import acceleration
argv, env = acceleration.prepare({profile!r}, [{binary!r}, *sys.argv[1:]], {abi!r}, 'auto')
open({record!r}, 'w').write(json.dumps({{'argv': argv, 'env': {{k: v for k, v in env.items()
    if k.startswith(('VK_', 'TERMUX_VA', 'LIBVA', 'LD_', 'BIONILUX', 'GALLIUM', 'MOZ_'))}}}}, indent=1))
os.execve(argv[0], argv, env)
'''


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


def decoded_recording(path, width, height):
    """Software-decode a recording: frame count, size, and the hue field's colour in the middle
    and the last rows of a late frame."""
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries',
                            'stream=codec_name,width,height,nb_read_frames', '-of', 'json', str(path)],
                           capture_output=True, text=True, timeout=120)
    stream = (json.loads(probe.stdout or '{}').get('streams') or [{}])[0]
    info = {'codec': stream.get('codec_name'), 'size': [stream.get('width'), stream.get('height')],
            'frames': int(stream.get('nb_read_frames') or 0)}
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-vf', 'select=eq(n\\,20)',
                          '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                         capture_output=True, timeout=120).stdout
    samples = []
    if len(raw) == width * height * 3:
        middle = raw[(height // 2) * width * 3:(height // 2 + 1) * width * 3]
        bar = max(range(width), key=lambda x: sum(middle[x * 3:x * 3 + 3]))
        x = (bar + width // 2) % width
        for y in (2, height // 2, height - 2):
            r, g, b = (value / 255 for value in raw[(y * width + x) * 3:(y * width + x) * 3 + 3])
            high, low = max(r, g, b), min(r, g, b)
            light = (high + low) / 2
            samples.append({'y': y, 's': round(0 if high == low else (high - low) / (1 - abs(2 * light - 1)), 2),
                            'l': round(light, 2)})
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(path), '-vf', 'select=eq(n\\,20)',
                        '-frames:v', '1', str(path.with_suffix('.png'))], timeout=120, check=False)
    info['samples'] = samples
    info['picture_ok'] = (info['size'] == [width, height] and info['frames'] >= 30 and len(samples) == 3 and
                          all(abs(q['s'] - 0.7) < 0.12 and abs(q['l'] - 0.45) < 0.08 for q in samples))
    return info


def encoder_sessions(log):
    """Hardware encoder sessions in a termux-va log: (component, pictures in, packets out)."""
    names, sessions = {}, []
    for line in log.splitlines():
        match = re.search(r'\[(\d+)\] selected encoder: (\S+)', line)
        if match:
            names[match[1]] = match[2]
        match = re.search(r'\[(\d+)\] encoder session end: (\d+) units in, (\d+) packets out', line)
        if match:
            sessions.append((names.get(match[1], '?'), int(match[2]), int(match[3])))
    return sessions


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('browser', choices=('chromium', 'chrome', 'firefox'))
    p.add_argument('--out', type=lambda value: Path(value).resolve(), required=True)
    p.add_argument('--mode', choices=('webrtc', 'mediarecorder'), default='webrtc')
    p.add_argument('--codec', action='append', help='h264 (default), vp8, vp9 or hevc; repeatable')
    p.add_argument('--expect', choices=('hardware', 'software'), default='hardware')
    p.add_argument('--size', default='640x360')
    p.add_argument('--firefox-encode', action='store_true',
                   help='experiment with Firefox encoding without changing the installed default')
    p.add_argument('--modules', default=str(Path.home() / '.local/lib/livecd-native'),
                   help='directory of the launcher modules (acceleration.py) to test')
    p.add_argument('--browser-command', type=lambda value: Path(value).resolve(),
                   help='start the browser with this command instead of the launcher')
    args = p.parse_args()
    if os.environ.get('LIVECD_ENCODE_TEST_BUS') != '1':
        # Start from the environment the desktop gives its programs (its preloads present the
        # GPU as /dev/dri/renderD128, which Firefox's encoder opens), on a bus of its own.
        # The tested acceleration module is imported first: desktop.py imports it by name.
        sys.path.insert(0, args.modules)
        import acceleration  # noqa: F401
        from desktop import environment
        os.environ['ANDROID_PROCFS_COMPAT'] = '0'
        env = environment('zink')
        for key in ('LIVECD_NATIVE_SESSION', 'XAUTHORITY', 'PULSE_SERVER'):
            env.pop(key, None)
        env['LIVECD_ENCODE_TEST_BUS'] = '1'
        os.execvpe('dbus-run-session', ['dbus-run-session', '--', sys.executable, *sys.argv], env)
    codecs = args.codec or ['h264']
    width, height = (int(value) for value in args.size.split('x'))
    out = args.out
    out.mkdir(parents=True)
    for name in ('config', 'cache', 'data', 'state', 'runtime'):
        (out / name).mkdir(mode=0o700)
    # The browser's crash dumps and caches stay out of the user's profile.
    os.environ.update(XDG_CONFIG_HOME=str(out / 'config'), XDG_CACHE_HOME=str(out / 'cache'),
                      XDG_DATA_HOME=str(out / 'data'), XDG_STATE_HOME=str(out / 'state'),
                      XDG_RUNTIME_DIR=str(out / 'runtime'))
    spec = importlib.util.spec_from_file_location('probe', BROWSERS / 'test-browsers.py')
    os.environ.setdefault('PREFIX', str(PREFIX))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    probe.OUT = out
    tag = 'encode-test-' + uuid.uuid4().hex
    # Stop at the first GPU-process crash: a browser left to restart it in a loop has brought
    # Android's low-memory killer down on the whole desktop before.
    launch = probe.launch

    def guarded(command, name):
        process = launch(command, name)

        def monitor():
            while process.poll() is None:
                log = out / (name + '.log')
                text = log.read_text(errors='replace') if log.exists() else ''
                if any(marker in text for marker in ('Check failed:', 'GPU process exited unexpectedly', 'FATAL:')):
                    (out / 'crash-stop.txt').write_text('Stopped at the first GPU crash or fatal log line\n')
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
    children, socket_dir = [], None
    result = {'browser': args.browser, 'mode': args.mode, 'expect': args.expect, 'display': display}
    try:
        with (out / 'x-server.log').open('w') as log:
            children.append(subprocess.Popen([str(BROWSERS / 'private-lorie/private-lorie'), f':{display}'],
                                             stdout=log, stderr=log, start_new_session=True))
        wait(lambda: subprocess.run(['xdpyinfo'], capture_output=True).returncode == 0, 60, 'the X server')
        # A short path: a Unix socket's path is limited to 107 bytes.
        socket_dir = Path(subprocess.run(['mktemp', '-d', str(PREFIX / 'tmp/enc-XXXXXX')], capture_output=True,
                                         text=True, check=True).stdout.strip())
        os.environ['TERMUX_VA_SOCKET'] = str(socket_dir / 'va.sock')
        daemon_env = {k: v for k, v in os.environ.items() if k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH')}
        with (out / 'termux-va.log').open('w') as log:
            children.append(subprocess.Popen([os.environ.get('TERMUX_VA_DAEMON', str(PREFIX / 'bin/termux-va')), '-t'],
                                             env=daemon_env, stdout=log, stderr=log, start_new_session=True))
        wait(lambda: (socket_dir / 'va.sock').is_socket(), 20, 'the termux-va socket')
        command = args.browser_command
        binary = {'chromium': PREFIX / 'lib/chromium/chrome', 'chrome': PREFIX / 'opt/google/chrome/chrome',
                  'firefox': PREFIX / 'bin/firefox'}[args.browser]
        if command is None:
            command = out / 'launcher.py'
            command.write_text(LAUNCHER.format(python=sys.executable, modules=args.modules, profile=args.browser,
                                               binary=str(binary), abi='glibc' if args.browser == 'chrome' else 'bionic',
                                               record=str(out / 'argv.json')))
            command.chmod(0o700)
        page = (PAGE % {'width': width, 'height': height}).encode()

        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(page)

            def log_message(self, *unused):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Page)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        probe.wait_for = lambda check, timeout, what: wait(check, timeout, what)
        profile = out / 'profile'
        if args.browser == 'firefox':
            profile.mkdir()
            os.environ.update(MOZ_LOG='FFmpegVideo:4,PlatformEncoderModule:4', MOZ_LOG_FILE=str(out / 'mozilla.log'))
            # The launcher manages preferences only in its own profile, so apply its decisions
            # to this disposable one the same way.
            sys.path.insert(0, args.modules)
            import acceleration
            from graphics import mali_usable
            encode = args.firefox_encode or (mali_usable() and acceleration.firefox_encode_ready())
            result['launcher_firefox_encode'] = encode
            result['experimental_firefox_encode'] = args.firefox_encode
            acceleration.firefox_preferences(profile, True, True, encode=encode)
            browser = probe.Firefox(command, profile, tag, prefs=(
                ('extensions.enabledScopes', 1), ('extensions.autoDisableScopes', 15),
                ('media.navigator.permission.disabled', True), ('media.navigator.streams.fake', False)),
                preserve_prefs=True)
        else:
            browser = probe.Chromium(command, profile, tag, (
                '--enable-logging=stderr', '--vmodule=*vaapi*=2,*video_encode*=2', '--ozone-platform=x11',
                '--disable-extensions', '--password-store=basic', '--disable-breakpad', '--disable-crash-reporter'))
        result['version'] = browser.version
        browser.open(f'http://127.0.0.1:{server.server_address[1]}/?mode={args.mode}&codecs=' + ','.join(codecs))
        cases = wait(lambda: browser.evaluate('window.RESULT'), 240, 'the page')
        browser.quit()
        for case in cases:
            if case.get('png'):
                (out / f'received-{case["codec"]}.png').write_bytes(base64.b64decode(case.pop('png').split(',', 1)[1]))
            if case.get('recording'):
                suffix = '.mp4' if 'mp4' in case['type'] else '.mkv' if 'matroska' in case['type'] else '.webm'
                recording = out / f'recording-{case["codec"]}{suffix}'
                recording.write_bytes(base64.b64decode(case.pop('recording')))
                case.update(decoded_recording(recording, width, height))
        result['cases'] = cases
    except Exception as error:
        result['error'] = str(error)
    finally:
        if hasattr(probe, 'stop'):
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
        if socket_dir:
            shutil.rmtree(socket_dir, ignore_errors=True)
        log = out / 'termux-va.log'
        sessions = encoder_sessions(log.read_text(errors='replace')) if log.exists() else []
        result['encoder_sessions'] = sessions
        hardware = [s for s in sessions if s[1] >= 30 and s[2] >= 30
                    and not s[0].startswith(('OMX.google.', 'c2.android.'))]
        result['crashed'] = (out / 'crash-stop.txt').exists()
        pictures = bool(result.get('cases')) and all(case.get('picture_ok') for case in result['cases'])
        result['ok'] = (pictures and not result['crashed'] and
                        (len(hardware) >= len(codecs) if args.expect == 'hardware' else not sessions))
        (out / 'result.json').write_text(json.dumps(result, indent=1) + '\n')
        print(json.dumps(result, indent=1))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
