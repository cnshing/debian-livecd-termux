"""Native Mali GLES bridge for qualified applications; no ANGLE or version overrides."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

PREFIX = Path('/data/data/com.termux/files/usr')
SERVER = PREFIX / 'bin/virgl_test_server_android'


def available():
    return os.access('/dev/mali0', os.R_OK | os.W_OK) and SERVER.is_file()


def run(command):
    if not available():
        raise RuntimeError('Native Mali GLES requires /dev/mali0 and virglrenderer-android')
    env = os.environ.copy()
    for key in ('LIBGL_ALWAYS_SOFTWARE', 'LIBGL_ALWAYS_INDIRECT',
                'MESA_LOADER_DRIVER_OVERRIDE', 'MESA_GL_VERSION_OVERRIDE',
                'MESA_GLES_VERSION_OVERRIDE', 'MESA_GLSL_VERSION_OVERRIDE',
                'VK_DRIVER_FILES', 'VK_ICD_FILENAMES'):
        env.pop(key, None)
    with tempfile.TemporaryDirectory(prefix='livecd-mali-', dir=env.get('TMPDIR')) as tmp:
        sock = Path(tmp) / 'renderer.sock'
        server_env = dict(env)
        server_env.pop('LD_PRELOAD', None)
        server_env['LD_LIBRARY_PATH'] = str(PREFIX / 'opt/virglrenderer-android/lib')
        with (Path(tmp) / 'renderer.log').open('w+') as log:
            server = subprocess.Popen([str(SERVER), '--socket-path', str(sock)],
                env=server_env, stdout=log, stderr=log, start_new_session=True)
            child = None
            try:
                deadline = time.monotonic() + 10
                while not sock.is_socket():
                    if server.poll() is not None or time.monotonic() > deadline:
                        log.flush()
                        raise RuntimeError('Mali renderer failed: ' + (Path(tmp) / 'renderer.log').read_text())
                    time.sleep(.05)
                env.update(GALLIUM_DRIVER='virpipe', VTEST_SOCKET_NAME=str(sock))
                child = subprocess.Popen(command, env=env)

                def forward(number, frame):
                    if child.poll() is None:
                        child.send_signal(number)

                for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                    signal.signal(number, forward)
                code = child.wait()
                return code if code >= 0 else 128 - code
            finally:
                if child and child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
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
    if len(sys.argv) < 2:
        raise SystemExit('Provide a native application command')
    raise SystemExit(run(sys.argv[1:]))
