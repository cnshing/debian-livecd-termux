#!/data/data/com.termux/files/usr/bin/python
"""Shared, ABI-aware application GPU/video configuration and daemon startup.

The native desktop keeps its existing GL driver. VA-API clients get a private
Bionic libva; glibc programs get their own Mesa through Bionilux. No glibc
libraries or video preloads are added to the desktop's global environment.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time

from graphics import apply_renderer, preferred_renderer

PREFIX = Path('/data/data/com.termux/files/usr')
ROOT = Path.home() / '.local/opt/livecd-native/acceleration'
# The android-vaapi packages. A stack selected under ROOT, such as a development build, comes first.
PACKAGED = {'bionic': PREFIX / 'lib/android-vaapi', 'glibc': PREFIX / 'lib/android-vaapi-glibc'}
CONFIG = Path.home() / '.config/livecd-native/acceleration.json'
RECEIPT = Path.home() / '.local/opt/livecd-native/gnome-48/share/doc/mutter/build-source.json'


def settings():
    config = json.loads(CONFIG.read_text()) if CONFIG.is_file() else {}
    if not isinstance(config, dict) or config.get('format', 1) != 1:
        raise ValueError('Unsupported acceleration configuration format')
    return config


def prebuilt_browser(profile):
    root = (PREFIX / 'opt/livecd-browsers' / profile).resolve()
    try:
        receipt = json.loads((root / 'livecd-vaapi.json').read_text())
        if (receipt.get('format') != 1 or receipt.get('abi') != 'glibc' or
                receipt.get('browser') != profile or receipt.get('vaapi') is not True or
                receipt.get('binary') not in ('chrome', 'chromium') or
                not (root / receipt['binary']).is_file()):
            return None
        return root, receipt
    except (OSError, ValueError, AttributeError):
        return None


def chromium_has_vaapi(profile='chromium', abi='bionic'):
    if abi == 'glibc':
        return prebuilt_browser(profile) is not None
    try:
        receipt = json.loads((PREFIX / 'share/doc/chromium/livecd-vaapi.json').read_text())
        return receipt.get('format') == 1 and receipt.get('vaapi') is True
    except (OSError, ValueError, AttributeError):
        return False


def stack(abi):
    for candidate in (ROOT / abi, PACKAGED[abi]):
        selected = checked_stack(candidate.resolve(), abi)
        if selected:
            return selected
    return None


def checked_stack(root, abi):
    try:
        manifest = json.loads((root / 'manifest.json').read_text())
        if manifest['format'] != 1 or manifest['abi'] != abi:
            raise ValueError('Wrong stack ABI')
        for value in [*manifest['libraries'], *manifest['preloads'], manifest['driver_directory']]:
            path = root / value
            if not path.exists() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Missing or external stack path: ' + str(path))
        if not (root / manifest['driver_directory'] / 'termuxva_drv_video.so').is_file():
            raise ValueError('Missing Termux:VA driver')
        return root, manifest
    except (OSError, ValueError, KeyError, TypeError):
        return None


def enabled(profile, config):
    # Existing explicit browser controls remain authoritative, including 0.
    key = {'chrome': 'LIVECD_CHROME_HARDWARE_VIDEO',
           'chromium': 'LIVECD_CHROMIUM_HARDWARE_VIDEO',
           'ungoogled-chromium': 'LIVECD_UNGOOGLED_CHROMIUM_HARDWARE_VIDEO',
           'firefox': 'LIVECD_FIREFOX_HARDWARE_VIDEO'}.get(profile)
    for variable in (key, 'LIVECD_HARDWARE_VIDEO'):
        if variable and variable in os.environ:
            return os.environ[variable] == '1'
    legacy = Path.home() / '.config/livecd-native/chrome-hardware-video'
    if profile == 'chrome' and legacy.is_file():
        return legacy.read_text().strip() == '1'
    # Hardware video is on unless turned off.
    return config.get('hardware_video', True) is not False


def gpu_enabled(profile):
    key = 'LIVECD_' + profile.upper().replace('-', '_') + '_GPU'
    if os.environ.get(key) in ('0', '1'):
        return os.environ[key] == '1'
    renderer = os.environ.get('LIVECD_NATIVE_RENDERER') or preferred_renderer()
    return renderer == 'zink' and RECEIPT.is_file() and '0010-clip-pixmap-damage' in RECEIPT.read_text()


def ensure_daemon(env):
    # A supplied endpoint is caller-owned. Never use the upstream lifecycle
    # helper: it may kill other termux-va instances when a health check fails.
    if env.get('TERMUX_VA_SOCKET') or env.get('TERMUX_VA_SOCKET_DIR'):
        env['TERMUX_VA_SOCKET'] = env.get('TERMUX_VA_SOCKET') or str(
            Path(env['TERMUX_VA_SOCKET_DIR']) / 'termux-va.sock')
        return
    directory = Path(env.get('TMPDIR', str(PREFIX / 'tmp'))) / 'termux-va'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    endpoint = directory / 'termux-va.sock'
    env['TERMUX_VA_SOCKET'] = str(endpoint)
    with (directory / 'livecd-start.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(1)
            try:
                client.connect(str(endpoint))
                return
            except (FileNotFoundError, ConnectionRefusedError):
                pass
        daemon = (ROOT / 'service/bin/termux-va').resolve()
        if not daemon.is_file():
            daemon = PREFIX / 'bin/termux-va'
        if not daemon.is_file():
            raise RuntimeError('Install the shared Termux:VA daemon first')
        clean = {k: v for k, v in env.items() if k not in (
            'LD_PRELOAD', 'LD_LIBRARY_PATH', 'BIONILUX_EXTRA_PRELOAD', 'BIONILUX_LIBRARY_PATH',
            'LIVECD_NATIVE_SESSION', 'LIVECD_BROWSER_TEST', 'LIVECD_FULLSCREEN_TEST', 'LIVECD_SETUP_LOCKED')}
        with (directory / 'termux-va.log').open('a') as log:
            process = subprocess.Popen([str(daemon)], env=clean, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, start_new_session=True)
        # Only wait for the new socket. No decode probe or process-wide stop.
        for unused in range(50):
            if process.poll() is not None:
                raise RuntimeError('Termux:VA exited; see ' + str(directory / 'termux-va.log'))
            if endpoint.is_socket():
                return
            time.sleep(.1)
        raise RuntimeError('Termux:VA did not create its endpoint')


def video_environment(env, selected, abi, config):
    root, manifest = selected
    libraries = ':'.join(str(root / p) for p in manifest['libraries'])
    preloads = ':'.join(str(root / p) for p in manifest['preloads'])
    if abi == 'glibc':
        env['BIONILUX_LIBRARY_PATH'] = libraries
        env['BIONILUX_EXTRA_PRELOAD'] = preloads
    else:
        env['LD_LIBRARY_PATH'] = ':'.join(filter(None, [libraries, env.get('LD_LIBRARY_PATH')]))
        env['LD_PRELOAD'] = ':'.join(filter(None, [preloads, env.get('LD_PRELOAD')]))
    env.update(LIBVA_DRIVERS_PATH=str(root / manifest['driver_directory']),
               LIBVA_DRIVER_NAME='termuxva', TERMUX_VA_BRIDGE='1',
               TERMUX_VA_GPU_BACKEND='kgsl', TERMUX_VA_X11_DRI3='1',
               TERMUX_VA_CONTIGUOUS_DMABUF='1')
    if manifest.get('ion_fallback') == 'preload':
        env.setdefault('LIVECD_TVA_ION_FALLBACK', '1')
    for codec in config.get('disabled_va_codecs', ['h264', 'av1']):
        env.setdefault('TERMUX_VA_DISABLE_' + codec.upper(), '1')
    ensure_daemon(env)


def firefox_preferences(profile, gpu, video):
    # Preserve user.js outside our marked block. Only the managed desktop
    # profile is edited; caller-supplied profiles retain their own preferences.
    profile.mkdir(parents=True, exist_ok=True)
    path = profile / 'user.js'
    start, end = '// livecd acceleration begin', '// livecd acceleration end'
    with (profile / '.livecd-acceleration.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = path.read_text() if path.is_file() else ''
        previous = re.sub(re.escape(start) + r'.*?' + re.escape(end) + r'\n?', '', previous, flags=re.S)
        values = {'gfx.webrender.all': gpu, 'layers.acceleration.force-enabled': gpu,
                  'media.ffmpeg.vaapi.enabled': video,
                  'media.hardware-video-decoding.force-enabled': video,
                  'widget.dmabuf.force-enabled': video}
        block = '\n'.join(f'user_pref({json.dumps(key)}, {json.dumps(value)});' for key, value in values.items())
        temporary = path.with_name('user.js.livecd-next')
        temporary.write_text(previous.rstrip() + '\n' + start + '\n' + block + '\n' + end + '\n')
        temporary.chmod(0o600)
        temporary.replace(path)


def firefox_video_runtime():
    """Select a complete probe/decoder pair matching the currently installed Firefox."""
    packaged = PREFIX / 'lib/android-firefox-video'
    reason = 'install android-firefox-video for the installed Firefox version'
    for port, ffmpeg in ((ROOT / 'firefox', ROOT / 'firefox-ffmpeg'),
                         (packaged, packaged / 'ffmpeg')):
        try:
            receipt = json.loads((port / 'manifest.json').read_text())
            decoder = json.loads((ffmpeg / 'manifest.json').read_text())
            if any(not isinstance(data, dict) or data.get('format') != 1 or data.get('abi') != 'bionic'
                   for data in (receipt, decoder)):
                reason = 'incompatible Firefox video metadata'
                continue
            if not all(path.is_file() for path in (
                    port / 'application/firefox', port / 'application/gfxtest',
                    ffmpeg / 'lib/libavcodec.so.63', ffmpeg / 'lib/libavutil.so.61')):
                reason = 'incomplete Firefox video package'
                continue
            installed = (PREFIX / 'bin/firefox').resolve()
            inputs = receipt['inputs']
            if (hashlib.sha256(installed.read_bytes()).hexdigest() != inputs['binary'] or
                    hashlib.sha256((installed.parent / 'application.ini').read_bytes()).hexdigest() !=
                    inputs['application_ini']):
                reason = 'Firefox changed; update android-firefox-video to match it'
                continue
            return (port.resolve(), ffmpeg.resolve()), None
        except FileNotFoundError:
            continue
        except (OSError, ValueError, KeyError, TypeError):
            reason = 'invalid Firefox video package metadata'
    return None, reason


def command_line(profile, command, abi, video, gpu):
    flags = []
    if profile in ('chrome', 'chromium', 'ungoogled-chromium'):
        flags = (['--use-gl=angle', '--use-angle=vulkan', '--ignore-gpu-blocklist',
                  '--enable-features=Vulkan,VulkanFromANGLE,DefaultANGLEVulkan'] if gpu else ['--disable-gpu'])
        if video:
            flags = ['--use-gl=angle', '--use-angle=vulkan', '--ignore-gpu-blocklist',
                '--enable-zero-copy', '--enable-native-gpu-memory-buffers',
                '--hardware-video-device-path=/dev/kgsl-3d0',
                '--enable-features=Vulkan,VulkanFromANGLE,DefaultANGLEVulkan,VaapiVideoDecoder,VaapiVideoDecodeLinux,PlatformHEVCDecoderSupport,AcceleratedVideoDecoder,AcceleratedVideoDecodeLinuxGL,VaapiIgnoreDriverChecks',
                '--disable-features=VaapiVideoMinResolutionForPerformance']
        if abi == 'glibc':
            flags[:0] = ['--no-sandbox', '--disable-dev-shm-usage']
        if profile in ('chromium', 'ungoogled-chromium') and abi == 'glibc' and not any(
                arg == '--user-data-dir' or arg.startswith('--user-data-dir=') for arg in command[1:]):
            name = 'chromium-vaapi' if profile == 'chromium' else profile
            flags.append('--user-data-dir=' + str(Path.home() / '.config/livecd-native' / name))
    elif profile == 'firefox' and not any(arg in ('--profile', '-profile', '-P') or arg.startswith('--profile=') for arg in command[1:]):
        owned = Path.home() / '.config/livecd-native/firefox'
        firefox_preferences(owned, gpu, video)
        flags = ['--profile', str(owned)]
    elif profile == 'mpv':
        flags = (['--vo=gpu-next', '--gpu-api=vulkan', '--gpu-context=x11vk'] if gpu else ['--vo=x11'])
        flags += (['--hwdec=mediacodec-copy', '--vd-lavc-o=ndk_codec=1'] if video else ['--hwdec=no'])
    return [command[0], *flags, *command[1:]]


def prepare(profile, command, abi, video_override):
    config = settings()
    env = os.environ.copy()
    if video_override != 'auto':
        value = '1' if video_override == 'on' else '0'
        env['LIVECD_HARDWARE_VIDEO'] = value
        for key in tuple(env):
            if key.startswith('LIVECD_') and key.endswith('_HARDWARE_VIDEO'):
                env[key] = value
    selected = stack(abi)
    gpu = gpu_enabled(profile)
    requested = enabled(profile, config) if video_override == 'auto' else video_override == 'on'
    # Stock Termux Chromium compiles VA-API out. Both the source-built Bionic
    # package and the prebuilt glibc route require their own build provenance.
    video = requested and gpu and (profile == 'mpv' or selected is not None)
    if profile in ('chromium', 'ungoogled-chromium') and not chromium_has_vaapi(profile, abi):
        video = False
    firefox = None
    if profile == 'firefox' and video:
        firefox, reason = firefox_video_runtime()
        if firefox is None:
            video = False
            print('Firefox hardware video unavailable: ' + reason + '; using software decoding.', file=sys.stderr)
    if abi == 'glibc':
        for key in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'BIONILUX_EXTRA_PRELOAD', 'BIONILUX_LIBRARY_PATH',
                    'GALLIUM_DRIVER', 'COGL_DRIVER', 'GSK_RENDERER', 'LIBGL_ALWAYS_SOFTWARE'):
            env.pop(key, None)
        if selected:
            root, manifest = selected
            env['BIONILUX_LIBRARY_PATH'] = ':'.join(str(root / p) for p in manifest['libraries'])
            if gpu:
                icd = root / manifest['vulkan_icd']
                mesa = root / manifest['mesa_library_directory']
                env.update(VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd),
                    LIBGL_DRIVERS_PATH=str(mesa / 'dri'), GBM_BACKENDS_PATH=str(mesa / 'gbm'),
                    MESA_LOADER_DRIVER_OVERRIDE='kgsl', TURNIP_KMD='kgsl', TU_DEBUG='noconform')
                vendors = mesa.parents[1] / 'share/glvnd/egl_vendor.d/50_mesa.json'
                if vendors.is_file():
                    env['__EGL_VENDOR_LIBRARY_FILENAMES'] = str(vendors)
        elif gpu:
            raise RuntimeError('Install the shared glibc acceleration stack first')
    else:
        apply_renderer(env, 'zink' if gpu else 'software')
    for key in tuple(env):
        if key.startswith(('LIBVA_', 'TERMUX_VA_')):
            env.pop(key, None)
    # Keep a caller's private endpoint, including the absence of a listening daemon.
    for key, value in os.environ.items():
        if key in ('TERMUX_VA_SOCKET', 'TERMUX_VA_SOCKET_DIR') or key.startswith('TERMUX_VA_DISABLE_'):
            env[key] = value
    if video and profile != 'mpv':
        video_environment(env, selected, abi, config)
        if abi == 'bionic' and profile in ('chromium', 'ungoogled-chromium'):
            # ANGLE consumes exported surfaces through implicit DRM sync. The
            # MediaCodec/CPU producer needs an explicit completion boundary.
            env['TERMUX_VA_SYNC_END_PICTURE'] = (
                '0' if os.environ.get('LIVECD_VA_DISABLE_COMPLETION') == '1' else '1')
        if profile == 'firefox':
            env.setdefault('MOZ_DRM_DEVICE', '/dev/kgsl-3d0')
            port, ffmpeg = firefox
            command = [str(port / 'application/firefox'), *command[1:]]
            env['LD_LIBRARY_PATH'] = ':'.join(filter(None,
                [str(ffmpeg / 'lib'), str(port / 'lib'), env.get('LD_LIBRARY_PATH')]))
    if profile in ('chrome', 'chromium', 'ungoogled-chromium') and abi == 'glibc':
        wrapper = {'chrome': 'google-chrome', 'chromium': 'chromium-vaapi',
                   'ungoogled-chromium': 'ungoogled-chromium'}[profile]
        env.update(CHROME_WRAPPER=str(PREFIX / 'bin' / wrapper), CHROME_VERSION_EXTRA='stable',
                   FONTCONFIG_FILE=str(PREFIX / 'etc/fonts/fonts.conf'),
                   XKB_CONFIG_ROOT=str(PREFIX / 'share/X11/xkb'), XLOCALEDIR=str(PREFIX / 'share/X11/locale'))
        if env.get('DISPLAY', '').startswith(':'):
            env['DISPLAY'] = str(PREFIX / 'tmp/.X11-unix') + '/X' + env['DISPLAY'][1:].split('.')[0]
        if profile == 'chrome':
            # Chrome's own Debian libraries, which a packaged stack does not carry.
            env['BIONILUX_LIBRARY_PATH'] = ':'.join(filter(None,
                [env.get('BIONILUX_LIBRARY_PATH'), str(PREFIX / 'opt/google/chrome/lib')]))
        if profile == 'chrome' and video:
            compat = (ROOT / 'glibc-compat').resolve()
            completion = compat / 'liblivecd-va-completion.so'
            fortify = compat / 'liblivecd-bionilux-fortify.so'
            if not (completion.is_file() and fortify.is_file()) and 'completion_preload' in selected[1]:
                completion = selected[0] / selected[1]['completion_preload']
                fortify = PREFIX / 'glibc/lib/libbionilux-fortify.so'
            if completion.is_file() and fortify.is_file():
                env['BIONILUX_EXTRA_PRELOAD'] = ':'.join(filter(None,
                    [str(completion), env.get('BIONILUX_EXTRA_PRELOAD'), str(fortify)]))
        if profile != 'chrome':
            installed = prebuilt_browser(profile)
            if not installed:
                raise RuntimeError('Install the pinned prebuilt ' + profile + ' first')
            root, receipt = installed
            command = [str(root / receipt['binary']), *command[1:]]
            env['BIONILUX_LIBRARY_PATH'] = ':'.join(filter(None,
                [env.get('BIONILUX_LIBRARY_PATH'), str(root / 'lib'), str(root)]))
            compat = root / 'lib/liblivecd-bionilux-fortify.so'
            if compat.is_file():
                env['BIONILUX_EXTRA_PRELOAD'] = ':'.join(filter(None,
                    [env.get('BIONILUX_EXTRA_PRELOAD'), str(compat)]))
            completion = root / 'lib/liblivecd-va-completion.so'
            if video and completion.is_file():
                env['BIONILUX_EXTRA_PRELOAD'] = ':'.join(filter(None,
                    [str(completion), env.get('BIONILUX_EXTRA_PRELOAD')]))
    argv = command_line(profile, command, abi, video, gpu)
    if abi == 'glibc':
        argv.insert(0, str(PREFIX / 'bin/bionilux'))
    return argv, env


def gio_bridge(arguments):
    # GVfs FUSE is unavailable, so GIO hands mpv raw smb:// URIs that neither
    # mpv nor Termux FFmpeg can open. Serve them from the session's GIO mount
    # over loopback HTTP with Range support; the random token keeps other apps out.
    if not any(argument.startswith('smb://') for argument in arguments):
        return arguments
    import secrets
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import quote
    from gi.repository import Gio, GLib

    def info(file):
        attributes = 'standard::size,standard::content-type'
        try:
            return file.query_info(attributes, Gio.FileQueryInfoFlags.NONE, None)
        except GLib.Error as error:
            if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_MOUNTED):
                raise
        loop, errors = GLib.MainLoop(), []
        def mounted(source, result):
            try:
                source.mount_enclosing_volume_finish(result)
            except GLib.Error as error:
                errors.append(error)
            loop.quit()
        file.mount_enclosing_volume(Gio.MountMountFlags.NONE, None, None, mounted)
        loop.run()
        if errors:
            raise errors[0]
        return file.query_info(attributes, Gio.FileQueryInfoFlags.NONE, None)

    token, files, result = secrets.token_urlsafe(16), {}, []
    for argument in arguments:
        if argument.startswith('smb://'):
            file = Gio.File.new_for_uri(argument)
            try:
                details = info(file)
            except GLib.Error as error:
                print('livecd-accelerate: ' + argument + ': ' + error.message, file=sys.stderr)
            else:
                key = str(len(files))
                files[key] = (file, details.get_size(), details.get_content_type() or 'application/octet-stream')
                result.append(f'/{token}/{key}/{quote(file.get_basename())}')
                continue
        result.append(argument)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_HEAD(self):
            self.serve(False)

        def do_GET(self):
            self.serve(True)

        def serve(self, body):
            parts = self.path.split('/')
            if len(parts) < 3 or parts[1] != token or parts[2] not in files:
                self.send_error(404)
                return
            file, size, kind = files[parts[2]]
            start, end = 0, size - 1
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers.get('Range', ''))
            if match and match[1]:
                start = int(match[1])
                end = min(int(match[2]), end) if match[2] else end
            elif match and match[2]:
                start = max(size - int(match[2]), 0)
            if match and start >= size:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return
            self.send_response(206 if match else 200)
            self.send_header('Content-Type', kind)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            if match:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if not body:
                return
            stream = file.read(None)
            try:
                stream.seek(start, GLib.SeekType.SET, None)
                left = end - start + 1
                while left > 0:
                    data = stream.read_bytes(min(left, 1 << 20), None).get_data()
                    if not data:
                        break
                    self.wfile.write(data)
                    left -= len(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # mpv drops the connection whenever it seeks.
            finally:
                stream.close(None)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    server.handle_error = lambda *args: None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_address[1]}'
    return [origin + argument if argument.startswith(f'/{token}/') else argument for argument in result]


def launch(profile, command, abi, video_override):
    if profile == 'mpv':
        command = [command[0], *gio_bridge(command[1:])]
    argv, env = prepare(profile, command, abi, video_override)
    process = subprocess.Popen(argv, env=env)
    def forward(number, frame):
        if process.poll() is None:
            process.send_signal(number)
    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, forward)
    code = process.wait()
    return code if code >= 0 else 128 - code


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    sub.add_parser('status', help='Read installation/configuration metadata without launching anything')
    sub.add_parser('chromium-env', help='Emit quoted shell exports for the Termux Chromium launcher')
    run = sub.add_parser('run')
    run.add_argument('--abi', choices=('bionic', 'glibc'), default='bionic')
    run.add_argument('--profile', choices=('generic', 'chrome', 'chromium', 'ungoogled-chromium', 'firefox', 'mpv'), default='generic')
    run.add_argument('--video', choices=('auto', 'on', 'off'), default='auto')
    run.add_argument('command', nargs=argparse.REMAINDER)
    args = p.parse_args()
    if args.action == 'status':
        print(json.dumps({'configuration': settings(), 'stacks': {abi: stack(abi) is not None
            for abi in ('bionic', 'glibc')}, 'chromium_vaapi_build':
            chromium_has_vaapi(),
            'prebuilt_browsers': {name: prebuilt_browser(name) is not None
                for name in ('chromium', 'ungoogled-chromium')},
            'runtime_verified': False}, indent=2))
        return 0
    if args.action == 'chromium-env':
        argv, env = prepare('chromium', [str(PREFIX / 'lib/chromium/chrome')], 'bionic', 'auto')
        flags = ' '.join(argv[1:])
        env['CHROMIUM_FLAGS'] = (os.environ.get('CHROMIUM_FLAGS', '') + ' ' + flags).strip()
        for key in sorted(set(os.environ) - set(env)):
            print('unset ' + key)
        for key, value in sorted(env.items()):
            if os.environ.get(key) != value:
                print('export ' + key + '=' + shlex.quote(value))
        return 0
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        p.error('run requires a command after --')
    programs = {'chrome': ('google-chrome', PREFIX / 'opt/google/chrome/chrome'),
                'chromium': ('chromium-browser', PREFIX / 'lib/chromium/chrome'),
                'firefox': ('firefox', PREFIX / 'bin/firefox'), 'mpv': ('mpv', PREFIX / 'bin/mpv')}
    abi = 'glibc' if args.profile in ('chrome', 'ungoogled-chromium') else args.abi
    if args.profile in ('chromium', 'ungoogled-chromium') and abi == 'glibc':
        installed = prebuilt_browser(args.profile)
        if installed:
            root, receipt = installed
            programs[args.profile] = (args.profile, root / receipt['binary'])
    target = programs.get(args.profile)
    resolved = str(target[1]) if target and command[0] == target[0] else shutil.which(command[0])
    if resolved and not Path(resolved).is_file():
        resolved = None
    if not resolved:
        p.error('Command not found: ' + command[0])
    command[0] = resolved
    return launch(args.profile, command, abi, args.video)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError) as error:
        sys.exit('livecd-accelerate: ' + str(error))
