#!/data/data/com.termux/files/usr/bin/python
"""Run one native Termux app on the privately staged x1s Mali drivers.

Preparation and device-specific limits: docs/native/X1S-GPU-VERIFICATION.md.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, default=Path.home() / 'gpu-x1s')
    parser.add_argument('--server-log', type=Path, help='retain rendering-server diagnostics')
    parser.add_argument('mode', choices=('vulkan', 'virgl'))
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error('provide a command to run')
    stage = args.stage.resolve()
    root = stage / 'root/data/data/com.termux/files/usr'
    env = dict(os.environ)
    for key in ('LIBGL_ALWAYS_SOFTWARE', 'LIBGL_ALWAYS_INDIRECT',
                'MESA_LOADER_DRIVER_OVERRIDE', 'GALLIUM_DRIVER',
                'VK_DRIVER_FILES', 'VK_ICD_FILENAMES', 'LD_PRELOAD',
                'LD_LIBRARY_PATH', 'MESA_GL_VERSION_OVERRIDE',
                'MESA_GLES_VERSION_OVERRIDE', 'MESA_GLSL_VERSION_OVERRIDE',
                'LIBGL_KOPPER_DISABLE', 'LIBGL_KOPPER_DRI2',
                'VTEST_SOCKET_NAME', 'GSK_RENDERER'):
        env.pop(key, None)
    env.setdefault('DISPLAY', ':0')
    env.setdefault('XDG_RUNTIME_DIR', env.get('TMPDIR', str(stage)))
    env['PATH'] = str(root / 'bin') + os.pathsep + env['PATH']
    if args.mode == 'vulkan':
        driver = root / 'lib/libvulkan_wrapper.so'
        if not driver.is_file():
            parser.error('private Vulkan wrapper is missing; see preparation guide')
        # The generic loader needs an ICD adapter, not the Android HAL itself.
        with tempfile.TemporaryDirectory(prefix='vk-', dir=stage) as tmp:
            icd = Path(tmp) / 'wrapper.json'
            icd.write_text(json.dumps({'file_format_version': '1.0.0', 'ICD': {
                'library_path': str(driver), 'api_version': '1.1.0'}}))
            env.update(VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd))
            return subprocess.call(args.command, env=env)

    server_bin = root / 'bin/virgl_test_server_android'
    server_lib = root / 'opt/virglrenderer-android/lib'
    if not server_bin.is_file() or not (server_lib / 'libvirglrenderer.so').is_file():
        parser.error('private Android VirGL server is missing; see preparation guide')
    with tempfile.TemporaryDirectory(prefix='vgl-', dir=stage) as tmp:
        sock = Path(tmp) / 'socket'
        log_path = args.server_log or Path(tmp) / 'server.log'
        with log_path.open('w') as log:
            server_env = dict(env, LD_LIBRARY_PATH=str(server_lib))
            server = subprocess.Popen([str(server_bin), '--socket-path', str(sock)],
                env=server_env,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 10
                while not sock.exists():
                    if server.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('VirGL server failed: ' + log_path.read_text())
                    time.sleep(0.05)
                env.update(GALLIUM_DRIVER='virpipe', VTEST_SOCKET_NAME=str(sock),
                           GSK_RENDERER='gl')
                return subprocess.call(args.command, env=env)
            finally:
                # The server forks rendering clients; clean up only this run's group.
                try:
                    os.killpg(server.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    server.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait()


if __name__ == '__main__':
    raise SystemExit(main())
