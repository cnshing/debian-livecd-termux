#!/usr/bin/env python3
"""Record WebGL flips or ArcMenu clicks on an isolated PanVK or Turnip GNOME display.

Invoked by panvk-desktop.py, never against the user's display. Analyze recordings
on the host with --check FILE. A frame containing both red and blue is unfinished.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback

PAGE = '''<!doctype html><meta charset="utf-8"><title>PanVK flip</title>
<style>html,body{margin:0;overflow:hidden;background:black}canvas{display:block}</style>
<canvas id="c"></canvas><script>
const canvas=document.getElementById('c');
canvas.width=innerWidth; canvas.height=innerHeight;
const gl=canvas.getContext('webgl', {antialias:false, alpha:false});
if(!gl) throw Error('no WebGL');
function shader(type, source) {
 const s=gl.createShader(type); gl.shaderSource(s,source); gl.compileShader(s);
 if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(s));
 return s;
}
const program=gl.createProgram();
gl.attachShader(program,shader(gl.VERTEX_SHADER,
 'attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}'));
gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`
 precision highp float; uniform float phase;
 void main(){
  float v=gl_FragCoord.x*.0001+gl_FragCoord.y*.0002+phase;
  for(int i=0;i<200;i++) v=sin(v*1.0001+float(i));
  gl_FragColor=vec4(phase+v*.00001,0.,1.-phase+v*.00001,1.);
 }`));
gl.linkProgram(program);
if(!gl.getProgramParameter(program,gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
gl.useProgram(program);
const buffer=gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
const p=gl.getAttribLocation(program,'p'); gl.enableVertexAttribArray(p);
gl.vertexAttribPointer(p,2,gl.FLOAT,false,0,0);
const phase=gl.getUniformLocation(program,'phase');
const debug=gl.getExtension('WEBGL_debug_renderer_info');
window.flip={frames:0,width:canvas.width,height:canvas.height,
 renderer:debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)};
function draw(){
 gl.uniform1f(phase,flip.frames%2); gl.drawArrays(gl.TRIANGLES,0,3);
 flip.frames++; requestAnimationFrame(draw);
}
draw();
</script>'''


def classify(data):
    # Byte masks and integer bit operations run in C, so checking every native
    # pixel is practical without a NumPy dependency. Each matching byte is 1.
    high = bytes(value > 180 for value in range(256))
    low = bytes(value < 70 for value in range(256))
    r, g, b = data[0::3], data[1::3], data[2::3]
    green_low = int.from_bytes(g.translate(low), 'little')
    red = (int.from_bytes(r.translate(high), 'little') & green_low &
           int.from_bytes(b.translate(low), 'little')).bit_count()
    blue = (int.from_bytes(b.translate(high), 'little') & green_low &
            int.from_bytes(r.translate(low), 'little')).bit_count()
    count = len(data) // 3
    return {'red': red, 'blue': blue, 'split': red > 0 and blue > 0,
            'valid': red + blue >= count * .98}


def check(path):
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error',
        '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
        '-of', 'json', str(path)], text=True))['streams'][0]
    width, height = info['width'] - 16, info['height'] - 16
    if width <= 0 or height <= 0:
        raise RuntimeError('Capture is too small for the border inset')
    size = width * height * 3
    command = ['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(path),
        '-vf', 'crop=iw-16:ih-16:8:8',
        '-threads', '1', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    proc = subprocess.Popen(command, stdout=subprocess.PIPE)
    split, invalid, total, red_frames, blue_frames = [], [], 0, 0, 0
    try:
        while True:
            data = proc.stdout.read(size)
            if not data:
                break
            if len(data) != size:
                raise RuntimeError('Truncated decoded frame')
            frame = classify(data)
            if frame['split']:
                split.append(total)
            if not frame['valid']:
                invalid.append(total)
            red_frames += frame['blue'] == 0 and frame['red'] >= width * height * .98
            blue_frames += frame['red'] == 0 and frame['blue'] >= width * height * .98
            total += 1
        if proc.wait(timeout=10):
            raise RuntimeError('Could not decode recording')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
    if not total or invalid:
        raise RuntimeError(f'Invalid capture: {total} frames, {len(invalid)} without a fullscreen flip')
    return {'path': str(path), 'frames': total, 'split_frames': split,
            'split_count': len(split), 'invalid_frames': invalid,
            'pixels_per_frame': width * height, 'native_resolution': True,
            'solid_red_frames': red_frames, 'solid_blue_frames': blue_frames}


def record(args):
    display = os.environ.get('DISPLAY', '')
    if not display.startswith(':') or not 74 <= int(display[1:]) < 100:
        raise RuntimeError('Requires a private harness display in :74–:99')
    if not os.environ.get('LIVECD_FULLSCREEN_TEST'):
        raise RuntimeError('Requires the private harness ownership marker')
    args.out.mkdir()
    if args.menu_button:
        return record_menu(args, display)
    here = Path(__file__).resolve().parents[1] / 'browsers'
    spec = importlib.util.spec_from_file_location('race_browser', here / 'test-browsers.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    probe.OUT = args.out
    page = args.out / 'flip.html'
    page.write_text(PAGE)
    browser = None
    tag = 'panvk-flip-' + str(os.getpid())
    result = {'trials': [], 'complete': False}
    try:
        binary = Path(os.environ['PREFIX']) / 'lib/chromium/chrome'
        browser = probe.Chromium(binary, args.out / 'profile', tag, (
            '--no-sandbox', '--ozone-platform=x11', '--use-gl=angle', '--use-angle=gl',
            '--ignore-gpu-blocklist', '--disable-extensions', '--disable-breakpad',
            '--disable-crash-reporter', '--disable-background-networking', '--password-store=basic',
            '--kiosk', '--force-device-scale-factor=1'))
        window = browser.call('Browser.getWindowForTarget')['windowId']
        browser.call('Browser.setWindowBounds', windowId=window, bounds={'windowState': 'fullscreen'})
        time.sleep(1)
        browser.open(page.as_uri())
        probe.wait_for(lambda: browser.evaluate('window.flip && flip.frames > 5'), 60, 'WebGL flips')
        identity = browser.evaluate('flip')
        result['webgl'] = identity
        if (not any(gpu in identity['renderer'] for gpu in ('Mali-G77', 'Adreno'))
                or 'SwiftShader' in identity['renderer']):
            raise RuntimeError('WebGL is not running on the phone GPU: ' + str(identity))
        size = f"{identity['width']}x{identity['height']}"
        dimensions = subprocess.check_output(['xdpyinfo'], text=True).split('dimensions:')[1].split()[0]
        if size != dimensions:
            raise RuntimeError('Browser is not fullscreen: ' + size + ' != ' + dimensions)
        result['processes'] = probe.identity(tag)
        icd = Path(os.environ['VK_DRIVER_FILES'])
        expected = Path(json.loads(icd.read_text())['ICD']['library_path'])
        if not expected.is_absolute():
            expected = icd.parent / expected
        result['gpu_driver_mappings'] = []
        mapped = set()
        for pid in probe.tagged(tag):
            try:
                libraries = sorted({line.split()[-1] for line in
                    Path(f'/proc/{pid}/maps').read_text().splitlines()
                    if 'libvulkan_panfrost.so' in line or 'libvulkan_freedreno.so' in line})
            except OSError:
                continue
            if libraries:
                result['gpu_driver_mappings'].append({'pid': pid, 'libraries': libraries})
                mapped.update(Path(library).resolve() for library in libraries)
        if mapped != {expected.resolve()}:
            raise RuntimeError('Browser driver mappings do not match the requested ICD: ' + str(mapped))
        result['version'] = browser.version
        for trial in range(args.trials):
            start = browser.evaluate('flip.frames')
            path = args.out / f'flip-{trial:02d}.mkv'
            command = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y',
                '-f', 'x11grab', '-draw_mouse', '0', '-framerate', '30',
                '-video_size', size, '-i', display, '-frames:v', str(args.frames),
                '-c:v', 'ffv1', '-threads', '2', str(path)]
            begin = time.monotonic()
            subprocess.run(command, check=True, timeout=args.frames / 30 + 45)
            end = browser.evaluate('flip.frames')
            if end <= start:
                raise RuntimeError('WebGL stopped rendering')
            result['trials'].append({'path': path.name, 'start_frame': start,
                                     'end_frame': end, 'seconds': time.monotonic() - begin})
            (args.out / 'record.json').write_text(json.dumps(result, indent=2) + '\n')
            print('FLIP_TRIAL', trial + 1, 'OF', args.trials, flush=True)
        result['complete'] = True
    except BaseException:
        result['error'] = traceback.format_exc()
        raise
    finally:
        if browser:
            try:
                browser.quit()
            except Exception:
                pass
        try:
            probe.stop(tag, grace=2)
        finally:
            (args.out / 'record.json').write_text(json.dumps(result, indent=2) + '\n')


def record_menu(args, display):
    sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
    from capture import screenshot
    x, y = map(int, args.menu_button.split(','))
    dimensions = subprocess.check_output(['xdpyinfo'], text=True).split('dimensions:')[1].split()[0]
    width, height = map(int, dimensions.split('x'))
    if not 0 <= x < width or not 0 <= y < height:
        raise RuntimeError('Menu button is outside the private display')
    result = {'kind': 'menu', 'button': [x, y], 'dimensions': dimensions,
              'clicks_per_trial': 60, 'trials': [], 'complete': False, 'seed': 20261122}
    rng = random.Random(result['seed'])

    def click():
        subprocess.run(['xdotool', 'mousemove', str(x), str(y), 'click', '1'],
                       check=True, timeout=5)

    try:
        subprocess.run(['xdotool', 'key', 'Escape'], check=True, timeout=5)
        time.sleep(1)
        screenshot(args.out / 'menu-closed.png')
        click()
        time.sleep(1)
        screenshot(args.out / 'menu-open.png')
        click()
        time.sleep(1)
        for trial in range(args.trials):
            path = args.out / f'menu-{trial:02d}.mkv'
            proc = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y',
                '-f', 'x11grab', '-draw_mouse', '0', '-framerate', '30',
                '-video_size', dimensions, '-i', display, '-c:v', 'ffv1', '-threads', '2', str(path)],
                stdin=subprocess.PIPE)
            gaps = [rng.uniform(.1, .3) for _ in range(60)]
            try:
                time.sleep(1)
                for gap in gaps:
                    if proc.poll() is not None:
                        raise RuntimeError('Menu recorder exited early')
                    click()
                    time.sleep(gap)
                time.sleep(1)
                proc.communicate(b'q\n', timeout=15)
                if proc.returncode:
                    raise RuntimeError('Menu recording failed')
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            result['trials'].append({'path': path.name, 'gaps_seconds': gaps})
            (args.out / 'record.json').write_text(json.dumps(result, indent=2) + '\n')
            print('MENU_TRIAL', trial + 1, 'OF', args.trials, flush=True)
        result['complete'] = True
    except BaseException:
        result['error'] = traceback.format_exc()
        raise
    finally:
        (args.out / 'record.json').write_text(json.dumps(result, indent=2) + '\n')


def check_menu(path, calibration):
    """Calibrate small, text-free strips against open and closed reference PNGs."""
    x, top, bottom, width, height = calibration['strips']
    color = calibration['color']
    filters = (f'[0:v]split[a][b];[a]crop={width}:{height}:{x}:{top}[t];'
               f'[b]crop={width}:{height}:{x}:{bottom}[b2];[t][b2]vstack')
    size = width * height * 3

    def coverage(data):
        return sum(all(abs(a-b) <= 8 for a, b in zip(pixel, color))
                   for pixel in zip(data[::3], data[1::3], data[2::3])) / (width * height)

    def frames(source):
        proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(source),
            '-filter_complex', filters, '-threads', '1', '-fps_mode', 'passthrough',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
            stdout=subprocess.PIPE)
        try:
            while True:
                data = proc.stdout.read(size * 2)
                if not data:
                    break
                if len(data) != size * 2:
                    raise RuntimeError('Truncated menu frame')
                yield coverage(data[:size]), coverage(data[size:])
            if proc.wait(timeout=10):
                raise RuntimeError('Could not decode menu capture')
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()

    opened = list(frames(path.parent / 'menu-open.png'))
    closed = list(frames(path.parent / 'menu-closed.png'))
    if len(opened) != 1 or min(opened[0]) < .9 or len(closed) != 1 or max(closed[0]) > .1:
        raise RuntimeError('Menu calibration does not distinguish open and closed references')
    cut, total, full, absent = [], 0, 0, 0
    for top_coverage, bottom_coverage in frames(path):
        if top_coverage >= .9 and bottom_coverage < .9:
            cut.append(total)
        full += min(top_coverage, bottom_coverage) >= .9
        absent += max(top_coverage, bottom_coverage) < .1
        total += 1
    if not total or not full or not absent:
        raise RuntimeError('Menu recording must contain both fully open and closed frames')
    return {'path': str(path), 'frames': total, 'cut_frames': cut, 'cut_count': len(cut),
            'fully_open_frames': full, 'closed_frames': absent, 'calibration': calibration}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--trials', type=int, default=1)
    parser.add_argument('--frames', type=int, default=900)
    parser.add_argument('--check', type=Path, nargs='+')
    parser.add_argument('--menu-button', help='Record 60 ArcMenu clicks per trial at private X,Y')
    parser.add_argument('--menu-calibration', type=Path,
                        help='Analyze menus using JSON strips [x,top,bottom,width,height] and color [r,g,b]')
    args = parser.parse_args()
    if args.check:
        # Deliberately mixed pixels must be rejected; solid red must pass.
        assert classify(bytes((255, 0, 0)) * 100)['valid']
        assert not classify(bytes((255, 0, 0)) * 100)['split']
        assert classify(bytes((255, 0, 0)) * 50 + bytes((0, 0, 255)) * 50)['split']
        for path in args.check:
            result = check_menu(path, json.loads(args.menu_calibration.read_text())) if args.menu_calibration else check(path)
            path.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result))
    elif not args.out or args.trials < 1 or args.frames < 1:
        parser.error('recording requires --out and positive trials/frames')
    else:
        record(args)
