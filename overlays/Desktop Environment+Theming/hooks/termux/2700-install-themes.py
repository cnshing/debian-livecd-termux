#!/data/data/com.termux/files/usr/bin/python
"""Install the pinned WhiteSur and Colloid themes in the native data directory."""
from pathlib import Path
import os
import subprocess
import tarfile
import tempfile

from desktop import DATA, environment
from prepare import CACHE, fetch


def main():
    overlay = Path(__file__).resolve().parents[2]
    assets = {
        'whitesur': {'url': 'https://codeload.github.com/vinceliuice/WhiteSur-gtk-theme/tar.gz/d5782652d412137e26fb8ff55b55a5572e4c6995', 'sha256': '9d8be3dca76f7be36dfb6513aa2c301be1ff265a9c1c4c1006b5ed0f89df29f1'},
        'colloid': {'url': 'https://codeload.github.com/vinceliuice/Colloid-icon-theme/tar.gz/ceac6608ecd0e40025cbc2ebbd32bf0e0f4ebc6a', 'sha256': '3f731f9f13b1c1403893561ff92adec7b3ab07c5495f55c78c111b07a10a296e'},
    }
    for name, asset in assets.items():
        archive = fetch(asset, name + '.tar.gz')
        marker = DATA / ('.' + name + '-v1')
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
                    if name == 'whitesur' else ['--theme', 'default', 'yellow'])
            subprocess.run(['bash', str(work / 'install.sh'), '--dest', str(dest), *args], cwd=work,
                           env={**environment(), 'TERM': 'xterm'}, check=True)
        if name == 'whitesur':
            for path in dest.glob('WhiteSur-*/gtk-[34].0/gtk*.css'):
                kind = 'gtk3' if 'gtk-3.0' in str(path) else 'gtk4'
                custom = overlay / ('lb/hooks/normal/scripts/whitesur-titlebuttons-' + kind + '.css')
                with path.open('a') as output:
                    output.write(custom.read_text())
        marker.touch()


if __name__ == '__main__':
    main()
