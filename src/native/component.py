#!/data/data/com.termux/files/usr/bin/python
"""Join the existing optional component profiles without mixing CJS/GJS ABIs."""
import os
from pathlib import Path
import sys

PREFIX = Path('/data/data/com.termux/files/usr')


def component_environment(component, arguments=(), inherited=None):
    env = dict(os.environ if inherited is None else inherited)
    # Audio clients keep the desktop's bus/settings; controllers and GSConnect
    # use their existing native profiles and shared Termux libraries, which their
    # RUNPATH finds. Naming $PREFIX/lib in LD_LIBRARY_PATH would instead put
    # libandroid-stub's libOpenSLES.so and libmediandk.so ahead of Android's.
    if not (component == 'easyeffects-bridge' and list(arguments[:1]) == ['exec']):
        for key in ('GI_TYPELIB_PATH', 'GJS_PATH', 'GSETTINGS_SCHEMA_DIR', 'DCONF_PROFILE',
                    'GNOME_SHELL_DATADIR', 'GNOME_SHELL_LIBDIR'):
            env.pop(key, None)
        env.pop('LD_LIBRARY_PATH', None)
        for variable, directory in [('XDG_CONFIG_HOME', '.config'), ('XDG_DATA_HOME', '.local/share'),
                                    ('XDG_CACHE_HOME', '.cache'), ('XDG_STATE_HOME', '.local/state')]:
            env[variable] = str(Path.home() / directory)
    return env


def main():
    component, *arguments = sys.argv[1:]
    if component not in ('gsconnect', 'easyeffects-bridge', 'easyeffects-autoeq'):
        raise SystemExit('Unknown optional native component')
    command = str(PREFIX / 'bin' / component)
    os.execve(command, [command, *arguments], component_environment(component, arguments))


if __name__ == '__main__':
    main()
