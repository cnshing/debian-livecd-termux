#!/data/data/com.termux/files/usr/bin/python
"""Run discovery on the native desktop's private system bus, in the foreground."""
import os
from pathlib import Path


def main():
    if not os.environ.get('LIVECD_NATIVE_SESSION') or not os.environ.get('DBUS_SYSTEM_BUS_ADDRESS'):
        raise SystemExit('Run through livecd-native exec inside the native desktop.')
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    config = runtime / 'avahi.conf'
    config.write_text('[server]\nhost-name=livecd-desktop\nenable-dbus=yes\n'
                      '[publish]\ndisable-publishing=yes\n')
    config.chmod(0o600)
    # exec preserves the desktop's ownership tag and lets session cleanup stop
    # the actual daemon. No Android system bus or root service is involved.
    os.execvp('avahi-daemon', ['avahi-daemon', '--no-drop-root', '--no-rlimits',
                             '--no-proc-title', '--file=' + str(config)])


if __name__ == '__main__':
    main()
