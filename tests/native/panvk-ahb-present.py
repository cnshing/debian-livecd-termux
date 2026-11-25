#!/usr/bin/env python3
"""Run the AHB import and DRI3 socket probe on an invisible private lorie."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--format', choices=('rgba', 'bgra'), default='rgba')
    parser.add_argument('--clear', choices=('red', 'green', 'blue'), default='green')
    parser.add_argument('--no-cpu-mapping', action='store_true')
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.driver = args.driver.resolve(strict=True)
    here = Path(__file__).resolve()
    desktop = load('panvk_desktop', here.with_name('panvk-desktop.py'))
    fullscreen = load('fullscreen', desktop.BROWSERS / 'test-fullscreen.py')
    probe = here.parents[2] / 'tools/panvk-probes/ahb-import.py'
    if not probe.is_file():
        parser.error('Copy tools/panvk-probes beside tests/ in the private phone tree')
    args.out.mkdir(parents=True, exist_ok=False)
    server = runtime = None
    code = 1
    with (Path(os.environ['TMPDIR']) / 'livecd-fullscreen-test.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before = fullscreen.live_state()
        if any(name != 'X0' for name in before['displays']):
            raise RuntimeError('Another private display is active')
        status = [str(Path.home() / '.local/bin/livecd'), 'status']
        status_before = desktop.run(status, capture_output=True, text=True).stdout
        env = os.environ.copy()
        for key in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'DISPLAY', 'XAUTHORITY',
                    'TERMUX_X11_FORCE_FLIP', 'VK_DRIVER_FILES', 'VK_ICD_FILENAMES',
                    'LIVECD_AHB_ANDROID_WINDOW'):
            env.pop(key, None)
        display = next(n for n in range(74, 100) if not any(p.exists() for p in
            (Path(os.environ['TMPDIR']) / f'.X11-unix/X{n}',
             Path(os.environ['TMPDIR']) / f'.X{n}-lock')))
        env.update(DISPLAY=f':{display}', LIVECD_FULLSCREEN_TEST=str(args.out), TERMUX_X11_DEBUG='1')
        try:
            runtime = Path(tempfile.mkdtemp(prefix='ahb-', dir=os.environ['TMPDIR']))
            env['XDG_RUNTIME_DIR'] = str(runtime)
            for name in ('config', 'data', 'cache', 'state'):
                directory = args.out / name
                directory.mkdir(mode=0o700)
                env['XDG_' + name.upper() + '_HOME'] = str(directory)
            with (args.out / 'server.log').open('w') as log:
                server = subprocess.Popen([str(desktop.BROWSERS / 'private-lorie/private-lorie'),
                    env['DISPLAY'], '-fakescreenfps', '60'], env=env, stdout=log, stderr=log)
            desktop.wait(lambda: subprocess.run(['xdpyinfo'], env=env, timeout=5,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)
            actual = dict(entry.split('=', 1) for entry in
                (Path('/proc') / str(server.pid) / 'environ').read_text().split('\0') if '=' in entry)
            if actual.get('TERMUX_X11_FORCE_FLIP'):
                raise RuntimeError('AHB probe must not force raw-fd flips')
            (args.out / 'server-environment.json').write_text(json.dumps({
                'pid': server.pid, 'display': env['DISPLAY'],
                'TERMUX_X11_FORCE_FLIP': actual.get('TERMUX_X11_FORCE_FLIP')}, indent=2) + '\n')
            env['LIVECD_AHB_SERVER_PID'] = str(server.pid)
            desktop.run(['xrandr', '--fb', '1920x1080'], env=env)
            with (args.out / 'probe.log').open('w') as log:
                code = subprocess.run([sys.executable, str(probe), '--driver', str(args.driver),
                    '--out', str(args.out / 'probe.json'), '--present-display', env['DISPLAY'], '--egl',
                    '--format', args.format, '--clear', args.clear,
                    *(['--no-cpu-mapping'] if args.no_cpu_mapping else [])],
                    env=env, stdout=log, stderr=log, timeout=60).returncode
            imported = 'DRI3: imported AHardwareBuffer, modifier 1255, 1920x1080' in (args.out / 'server.log').read_text()
            (args.out / 'server-verification.json').write_text(json.dumps({
                'ahb_import_logged': imported, 'server_exit_before_cleanup': server.poll()}, indent=2) + '\n')
            if not imported or server.poll() is not None:
                code = 1
        finally:
            desktop.stop(server)
            cleaned = desktop.cleanup_tagged(args.out)
            if runtime:
                shutil.rmtree(runtime)
            for path in (f'.X11-unix/X{display}', f'.X{display}-lock'):
                (Path(os.environ['TMPDIR']) / path).unlink(missing_ok=True)
            after = fullscreen.live_state()
            status_after = desktop.run(status, capture_output=True, text=True).stdout
            isolation = {'before': before, 'after': after, 'status_before': status_before,
                'status_after': status_after, 'cleaned_orphan_pids': cleaned,
                'ok': before == after and status_before == status_after}
            (args.out / 'isolation.json').write_text(json.dumps(isolation, indent=2) + '\n')
    return code if isolation['ok'] else 1


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    sys.exit(main())
