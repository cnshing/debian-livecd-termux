"""Keep Ghostty usable when the selected GPU lacks its OpenGL 4.3 context."""
import os
import re
import subprocess
import sys

from graphics import PREFIX, apply_renderer


def environment(source):
    env = dict(source)
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
    binary = str(PREFIX / 'bin/ghostty')
    os.execve(binary, [binary, *sys.argv[1:]], environment(os.environ))


if __name__ == '__main__':
    main()
