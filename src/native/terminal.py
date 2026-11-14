"""Keep Ghostty usable when the selected GPU lacks its OpenGL 4.3 context."""
import os
import re
import subprocess
import sys

from graphics import PREFIX, apply_renderer


def dmabuf_available(source):
    """The installed launcher's guard verifies both the device ABI and payload."""
    binary = PREFIX / 'bin/ghostty-panvk-dmabuf'
    if source.get('LIVECD_GHOSTTY_DMABUF') == '0' or not binary.is_file():
        return False
    try:
        result = subprocess.run([str(binary), '--check'], env=dict(source),
                                capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def command(arguments, source=None):
    source = os.environ if source is None else source
    name = 'ghostty-panvk-dmabuf' if dmabuf_available(source) else 'ghostty'
    return [str(PREFIX / 'bin' / name), *arguments]


def environment(source):
    env = dict(source)
    if dmabuf_available(source):
        # The dedicated launcher sets its complete private GL environment.
        return env
    if env.get('LIVECD_NATIVE_VULKAN_DRIVER') == 'panvk':
        try:
            info = subprocess.run(['glxinfo', '-B'], env=env, capture_output=True,
                                  text=True, timeout=10)
            version = re.search(r'OpenGL core profile version string: (\d+)\.(\d+)', info.stdout)
            supported = info.returncode == 0 and version and tuple(map(int, version.groups())) >= (4, 3)
        except (OSError, subprocess.TimeoutExpired):
            supported = False
        if not supported:
            apply_renderer(env, 'software')
    # GTK and Ghostty must not contend for the same GL context on Zink.
    env['GSK_RENDERER'] = 'cairo'
    return env


def main():
    argv = command(sys.argv[1:])
    os.execve(argv[0], argv, environment(os.environ))


if __name__ == '__main__':
    main()
