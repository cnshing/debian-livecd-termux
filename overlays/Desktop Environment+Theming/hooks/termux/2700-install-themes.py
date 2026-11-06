#!/data/data/com.termux/files/usr/bin/python
"""Build the live CD's WhiteSur variants from the whitesur-gtk-theme package's installer.

The package supplies WhiteSur's prebuilt variants and Colloid comes from colloid-icon-theme. This
applies upstream's own choices on top: Monterey, the Nord scheme and solid opacity, in every accent,
with upstream's title bar buttons. Upstream's accent extensions then select among these variants.
"""
import ast
from pathlib import Path
import shutil
import subprocess
import tempfile

from desktop import CONFIG, DATA, PREFIX, environment
from prepare import CACHE

ACCENT_EXTENSIONS = ['accent-user-theme@brgvos', 'accent-gtk-theme@brgvos', 'accent-icons-theme@brgvos']


def main():
    overlay = Path(__file__).resolve().parents[2]
    version = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'whitesur-gtk-theme'], text=True).strip()
    marker = DATA / ('.whitesur-' + version)
    themes = DATA / 'themes'
    if not marker.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=CACHE) as temp:
            # install.sh writes temporary files beside itself, so run a copy.
            work = Path(temp) / 'whitesur'
            shutil.copytree(PREFIX / 'share/whitesur-gtk-theme', work, symlinks=True)
            themes.mkdir(parents=True, exist_ok=True)
            subprocess.run(['bash', str(work / 'install.sh'), '--dest', str(themes), '--monterey', '--scheme', 'nord',
                            '--opacity', 'solid', '--theme', 'all'],
                           cwd=work, env={**environment(), 'TERM': 'xterm'}, check=True)
        for path in themes.glob('WhiteSur-*/gtk-[34].0/gtk*.css'):
            kind = 'gtk3' if 'gtk-3.0' in str(path) else 'gtk4'
            custom = overlay / ('lb/hooks/normal/scripts/whitesur-titlebuttons-' + kind + '.css')
            with path.open('a') as output:
                output.write(custom.read_text())
        for old in DATA.glob('.whitesur-*'):
            old.unlink()
        marker.touch()
    # Earlier installations put Colloid and their own appearance extension here. The packaged copies
    # replace them, and these would otherwise take precedence.
    if (DATA / '.colloid-v2').exists() or (DATA / '.colloid-v1').exists():
        for directory in (DATA / 'icons').glob('Colloid*'):
            shutil.rmtree(directory)
        for old in DATA.glob('.colloid-v*'):
            old.unlink()
    shutil.rmtree(DATA / 'gnome-shell/extensions/livecd-appearance@local', ignore_errors=True)
    # Wherever the extension list became a user setting, it still names that extension instead of
    # its successors, and the dconf defaults no longer apply. Keep the user's other choices.
    env = environment()
    key = '/org/gnome/shell/enabled-extensions'
    value = subprocess.run(['dconf', 'read', key], env=env, capture_output=True, text=True).stdout.strip()
    if "'livecd-appearance@local'" in value:
        enabled = [uuid for uuid in ast.literal_eval(value) if uuid != 'livecd-appearance@local']
        enabled += [uuid for uuid in ACCENT_EXTENSIONS if uuid not in enabled]
        subprocess.run(['dbus-run-session', '--', 'dconf', 'write', key, repr(enabled)],
                       env={**env, 'GIO_USE_VFS': 'local'}, check=True)
    # That extension also linked GTK 4's user CSS to a file of its own. The accent GTK extension
    # leaves any link it did not make alone, so remove this one.
    owned = CONFIG / 'livecd/gtk4.css'
    css = CONFIG / 'gtk-4.0/gtk.css'
    if css.is_symlink() and css.readlink() == owned:
        css.unlink()
    owned.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
