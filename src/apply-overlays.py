#!/data/data/com.termux/files/usr/bin/python
"""Apply overlays on top of the installed Termux packages.

Usage: apply-overlays.py [--default] [OVERLAY...]
--default adds the overlays listed in overlays/termux.yaml.

An overlay keeps upstream's shape, and what Termux reads from it is:
  packages/termux.yaml              Termux package names to install.
  filesystem/termux/home/           Copied to $HOME, replacing what is there.
  filesystem/termux/home-defaults/  Copied to $HOME only where nothing exists yet.
  filesystem/termux/prefix/         Copied to $PREFIX.
  hooks/termux/NNNN-*               Run last, in name order across every overlay.
plus the upstream files listed in UPSTREAM_TARGETS. A file named *.overlay.tmpl has
@TERMUX_PREFIX@ and @TERMUX_HOME@ filled in and loses that suffix.
"""
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE / 'native'))
from desktop import BASE, DATA, PREFIX

OVERLAYS = REPO / 'overlays'
SUFFIX = '.overlay.tmpl'
TERMUX_TARGETS = {'home': Path.home(), 'prefix': PREFIX}
# Upstream's files, used as they are, and where each belongs in the private profile.
UPSTREAM_TARGETS = {
    'filesystem/live_installed/etc/dconf/db/desktop.d': BASE / 'dconf.d',
    'filesystem/live_installed/usr/share/backgrounds': DATA / 'backgrounds',
    'filesystem/live_installed/etc/skel/.config/ghostty/config.ghostty': BASE / 'appearance.ghostty',
}


def listed(path):
    """Read a simple YAML list, as the Debian guest's setup does."""
    return re.findall(r'^- (.+?)\s*$', path.read_text(), flags=re.M) if path.is_file() else []


def install(source, destination, keep_existing=False):
    if source.name.endswith(SUFFIX):
        destination = destination.with_name(destination.name[:-len(SUFFIX)])
    if keep_existing and (destination.exists() or destination.is_symlink()):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Replace a link rather than writing through it to somewhere else.
    if destination.is_symlink():
        destination.unlink()
    if source.name.endswith(SUFFIX):
        destination.write_text(source.read_text().replace('@TERMUX_PREFIX@', str(PREFIX))
                               .replace('@TERMUX_HOME@', str(Path.home())))
        shutil.copymode(source, destination)
    else:
        shutil.copy2(source, destination)


def install_tree(source, destination, keep_existing=False):
    if source.is_file():
        install(source, destination, keep_existing)
    elif source.is_dir():
        for path in sorted(source.rglob('*')):
            if path.is_file():
                install(path, destination / path.relative_to(source), keep_existing)


def main():
    names = sys.argv[1:]
    if names[:1] == ['--default']:
        names = listed(OVERLAYS / 'termux.yaml') + names[1:]
    if not names:
        raise SystemExit(__doc__)
    unknown = [name for name in names if not (OVERLAYS / name).is_dir()]
    if unknown:
        raise SystemExit('Unknown overlay: ' + ', '.join(unknown))
    lock = None
    if not os.environ.get('LIVECD_SETUP_LOCKED'):
        state = Path.home() / '.local/state/livecd'
        state.mkdir(parents=True, exist_ok=True)
        lock = (state / 'session.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Stop the running desktop before applying overlays.')
    overlays = [OVERLAYS / name for name in dict.fromkeys(names)]
    packages = [package for overlay in overlays for package in listed(overlay / 'packages/termux.yaml')]
    if packages:
        subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends', '-o', 'Dpkg::Options::=--force-confdef',
                        '-o', 'Dpkg::Options::=--force-confold', *packages],
                       env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'}, check=True)
    for overlay in overlays:
        for relative, target in UPSTREAM_TARGETS.items():
            install_tree(overlay / relative, target)
        for name, target in TERMUX_TARGETS.items():
            install_tree(overlay / 'filesystem/termux' / name, target)
        install_tree(overlay / 'filesystem/termux/home-defaults', Path.home(), keep_existing=True)
    hooks = sorted((path for overlay in overlays for path in (overlay / 'hooks/termux').glob('*')), key=lambda p: p.name)
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(HERE / 'native'), str(REPO / 'prebuilt/gnome-runtime')])}
    for hook in hooks:
        print('Running', hook.relative_to(REPO), flush=True)
        interpreter = sys.executable if hook.suffix == '.py' else 'bash'
        subprocess.run([interpreter, str(hook)], cwd=hook.parents[2], env=env, check=True)
    if lock:
        lock.close()


if __name__ == '__main__':
    main()
