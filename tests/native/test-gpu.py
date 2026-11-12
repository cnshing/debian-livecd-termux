#!/data/data/com.termux/files/usr/bin/python
"""Exercise native GL/Vulkan windows, GPU video, Ghostty and compositor frames."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
from capture import screenshot
from desktop import STATE, request, bus_call
from graphics import GPU, process_gpu, zink_driver
from gi.repository import GLib


def wait(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError('GPU application timed out')


def window(pid):
    result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(pid)],
                            capture_output=True, text=True, timeout=5)
    return result.stdout.splitlines()[-1] if result.stdout.strip() else None


def activate(wid):
    subprocess.run(['xdotool', 'windowactivate', '--sync', wid], check=True, timeout=10)
    time.sleep(2)


def named_window(name):
    result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', name],
                            capture_output=True, text=True, timeout=5)
    # Mutter's frame windows copy the title. Current vkcube's own window does not match a
    # name search, but takes the focus when it maps.
    clients = [wid for wid in result.stdout.split() if 'mutter-x11-frames' not in
               subprocess.run(['xprop', '-id', wid, 'WM_CLASS'], capture_output=True, text=True).stdout]
    if clients:
        return clients[-1]
    if result.stdout.strip():
        active = subprocess.run(['xdotool', 'getactivewindow'], capture_output=True, text=True).stdout.strip()
        title = subprocess.run(['xdotool', 'getwindowname', active], capture_output=True, text=True).stdout.strip()
        if active and re.search(name, title):
            return active
    return None


def gpu_process(pid):
    result = process_gpu(pid)
    assert result['driver'] == zink_driver(), result
    assert result['libraries'] and result['devices'], result
    return result


def usage(pid):
    stat = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
    status = (Path('/proc') / str(pid) / 'status').read_text()
    return {'cpu_seconds': (int(stat[11]) + int(stat[12])) / os.sysconf('SC_CLK_TCK'),
            'rss_kib': int(re.search(r'VmRSS:\s+(\d+)', status).group(1))}


def main():
    status = request('status')
    assert status['renderer'] == 'zink'
    result = {'status': status, 'shell': gpu_process(status['shell'])}
    driver = zink_driver()
    tools = GPU / 'bin' if driver == 'turnip' else Path(shutil.which('vulkaninfo') or '/missing/vulkaninfo').parent
    result['vulkan'] = subprocess.check_output([str(tools / 'vulkaninfo'), '--summary'], text=True, timeout=20)
    expected = 'Mali' if driver == 'panvk' else 'Turnip Adreno'
    assert expected in result['vulkan']
    result['opengl'] = subprocess.check_output(['glxinfo', '-B'], text=True, timeout=20)
    assert 'Accelerated: yes' in result['opengl'] and 'zink' in result['opengl'] and expected in result['opengl']
    children, logs = [], []

    def launch(name, arguments):
        log = (STATE / ('gpu-' + name + '.log')).open('w')
        logs.append(log)
        child = subprocess.Popen(arguments, stdout=log, stderr=subprocess.STDOUT)
        children.append(child)
        return child

    try:
        fixtures = Path.home() / 'Documents/livecd-native-validation'
        folder = fixtures / f'gpu-folder-{os.getpid()}'
        folder.mkdir()
        for name, arguments, title in [
            ('nautilus', ['nautilus', '--new-window', str(folder)], folder.name),
        ]:
            launch(name, arguments)
            wid = wait(lambda: named_window(title))
            activate(wid)
            time.sleep(3)
            pid = int(subprocess.check_output(['xdotool', 'getwindowpid', wid], text=True))
            result[name] = gpu_process(pid)
            screenshot(STATE / ('gpu-' + name + '.png'))
            subprocess.run(['xdotool', 'windowquit', wid], check=True)
        print('GTK_GPU_PASS', flush=True)

        terminal = request('terminal', cwd=str(Path.home()), emulator='ghostty')
        wid = wait(lambda: window(terminal['pid']))
        activate(wid)
        marker = STATE / 'gpu-terminal-identity.json'
        marker.unlink(missing_ok=True)
        code = 'import json,os,pathlib;pathlib.Path(' + repr(str(marker)) + ').write_text(json.dumps({"uid":os.getuid(),"cwd":os.getcwd()}))'
        subprocess.run(['xdotool', 'type', '--clearmodifiers', 'python -c ' + shlex.quote(code)], check=True)
        subprocess.run(['xdotool', 'key', 'Return'], check=True)
        wait(marker.exists)
        identity = json.loads(marker.read_text())
        assert identity == {'uid': os.getuid(), 'cwd': str(Path.home())}, identity
        result['ghostty'] = dict(gpu_process(terminal['pid']), identity=identity)
        screenshot(STATE / 'gpu-ghostty.png')
        subprocess.run(['xdotool', 'type', '--clearmodifiers', 'exit'], check=True)
        subprocess.run(['xdotool', 'key', 'Return'], check=True)
        wait(lambda: not window(terminal['pid']))
        print('GHOSTTY_GPU_PASS', flush=True)

        video = Path.home() / 'Documents/livecd-native-validation/video.mp4'
        assert video.is_file(), 'Run test-media.py to create the video fixture first'
        player = launch('mpv', ['mpv', '--title=Native GPU Video', '--loop-file=inf',
            '--vo=gpu-next', '--gpu-api=vulkan', '--gpu-context=x11vk', '--hwdec=no',
            '--ao=pulse', '--msg-level=vo/gpu-next=v', str(video)])
        wid = wait(lambda: window(player.pid))
        activate(wid)
        time.sleep(4)
        assert player.poll() is None
        result['video'] = gpu_process(player.pid)
        screenshot(STATE / 'gpu-video.png')
        player.terminate()
        player.wait(timeout=5)
        result['video']['log'] = (STATE / 'gpu-mpv.log').read_text()
        assert 'AO: [pulse]' in result['video']['log']
        print('VIDEO_GPU_PASS', flush=True)

        cube = launch('cube', [str(tools / 'vkcube'), '--wsi', 'xcb', '--width', '300', '--height', '300'])
        # These upstream demos do not reliably publish _NET_WM_PID.
        activate(wait(lambda: named_window('^Vkcube X11$')))
        result['cube'] = gpu_process(cube.pid)
        screenshot(STATE / 'gpu-cube.png')
        gears = launch('gears', ['stdbuf', '-oL', 'glxgears', '-info', '-geometry', '300x300'])
        activate(wait(lambda: named_window('^glxgears$')))
        result['gears'] = gpu_process(gears.pid)
        screenshot(STATE / 'gpu-gears.png')
        first = {str(pid): usage(pid) for pid in [status['shell'], cube.pid, gears.pid]}
        started = time.monotonic()
        for index in range(60):
            assert cube.poll() is None and gears.poll() is None
            if index < 10:
                bus_call(os.environ, 'org.gnome.Shell', '/org/gnome/Shell',
                    'org.freedesktop.DBus.Properties', 'Set', '(ssv)',
                    ('org.gnome.Shell', 'OverviewActive', GLib.Variant('b', index % 2 == 0)))
            time.sleep(1)
        elapsed = time.monotonic() - started
        final = {pid: usage(int(pid)) for pid in first}
        result['sustained'] = {'seconds': elapsed, 'before': first, 'after': final,
            'cpu_percent_one_core': {pid: (final[pid]['cpu_seconds'] - first[pid]['cpu_seconds']) / elapsed * 100 for pid in first}}
        result['gears']['frames'] = re.findall(r'\d+ frames in [\d.]+ seconds = [\d.]+ FPS', (STATE / 'gpu-gears.log').read_text())
        assert result['gears']['frames'], 'No completed GLX animation intervals'
        assert request('status')['shell'] == status['shell']
        screenshot(STATE / 'gpu-sustained.png')
        result['ok'] = True
        (STATE / 'gpu-validation.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2), flush=True)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
