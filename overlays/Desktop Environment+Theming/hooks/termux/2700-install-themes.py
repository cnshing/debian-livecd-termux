#!/data/data/com.termux/files/usr/bin/python
"""Install the pinned WhiteSur and Colloid themes in the native data directory."""
from pathlib import Path
import os
import re
import subprocess
import tarfile
import tempfile

from desktop import DATA, environment
from prepare import CACHE, fetch


def drop_colored_symbolic_aliases(icons):
    """Colloid also names a few full-color icons -symbolic. GTK paints a symbolic icon in one color, which
    turns those into solid squares, as with elementary Code's menu button, so leave the name to Colloid's
    real symbolic icon. Runs on every install, as it also repairs themes installed before it existed."""
    removed = False
    for link in icons.glob('Colloid*/*/*/*-symbolic.svg'):
        if not link.is_symlink() or link.parent.name == 'symbolic':
            continue
        twin = link.parent.parent / 'symbolic' / link.name
        if twin.exists() and re.search(r'<image|<rect[^>]*fill="#', link.resolve().read_text()):
            link.unlink()
            removed = True
    if removed:
        for theme in sorted(icons.glob('Colloid*/index.theme')):
            subprocess.run(['gtk-update-icon-cache', '--quiet', '--force', str(theme.parent)], check=True)


def main():
    overlay = Path(__file__).resolve().parents[2]
    assets = {
        'whitesur': {'url': 'https://codeload.github.com/vinceliuice/WhiteSur-gtk-theme/tar.gz/d5782652d412137e26fb8ff55b55a5572e4c6995', 'sha256': '9d8be3dca76f7be36dfb6513aa2c301be1ff265a9c1c4c1006b5ed0f89df29f1'},
        'colloid': {'url': 'https://codeload.github.com/vinceliuice/Colloid-icon-theme/tar.gz/ceac6608ecd0e40025cbc2ebbd32bf0e0f4ebc6a', 'sha256': '3f731f9f13b1c1403893561ff92adec7b3ab07c5495f55c78c111b07a10a296e'},
    }
    # v2 of Colloid installs every accent color; v1 installed only the default and yellow.
    markers = {'whitesur': '.whitesur-v1', 'colloid': '.colloid-v2'}
    for name, asset in assets.items():
        archive = fetch(asset, name + '.tar.gz')
        marker = DATA / markers[name]
        if marker.exists():
            continue
        with tempfile.TemporaryDirectory(dir=CACHE) as temp:
            with tarfile.open(archive) as source:
                source.extractall(temp, filter='data')
            work = next(Path(temp).iterdir())
            if name == 'whitesur':
                for patch in sorted((overlay / 'patches/whitesur').glob('*.patch')):
                    subprocess.run(['patch', '--batch', '--silent', '-p1', '-d', str(work)], check=True, text=True,
                                   input=patch.read_text().replace('@TERMUX_PREFIX@', os.environ['PREFIX']))
            dest = DATA / ('themes' if name == 'whitesur' else 'icons')
            dest.mkdir(exist_ok=True)
            args = (['--monterey', '--scheme', 'nord', '--opacity', 'solid', '--theme', 'all']
                    if name == 'whitesur' else ['--theme', 'all'])
            subprocess.run(['bash', str(work / 'install.sh'), '--dest', str(dest), *args], cwd=work,
                           env={**environment(), 'TERM': 'xterm'}, check=True)
        if name == 'whitesur':
            for path in dest.glob('WhiteSur-*/gtk-[34].0/gtk*.css'):
                kind = 'gtk3' if 'gtk-3.0' in str(path) else 'gtk4'
                custom = overlay / ('lb/hooks/normal/scripts/whitesur-titlebuttons-' + kind + '.css')
                with path.open('a') as output:
                    output.write(custom.read_text())
        marker.touch()
    drop_colored_symbolic_aliases(DATA / 'icons')


if __name__ == '__main__':
    main()
