#!/usr/bin/env python3
"""Fetch pinned binaries and complete corresponding source, failing closed."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    lock = json.loads((HERE / 'lock.json').read_text())
    inputs, sources = args.destination / 'inputs', args.destination / 'sources'
    sources.mkdir(parents=True, exist_ok=True)
    for kind in ('driver', 'mesa', 'gtk'):
        item = lock[kind]
        subprocess.run(['gh', 'run', 'download', str(item['run']), '-R', lock['repository'],
                        '-n', item['artifact'], '-D', str(inputs / kind)], check=True)
    for item in lock['upstream_sources']:
        path = sources / item['file']
        subprocess.run(['curl', '-fL', '--retry', '3', '-o', str(path), item['url']], check=True)
        if hashlib.file_digest(path.open('rb'), 'sha256').hexdigest() != item['sha256']:
            raise RuntimeError('Source checksum mismatch: ' + str(path))
    snapshots = [(kind, lock['repository'], lock[kind]['revision']) for kind in ('driver', 'mesa', 'gtk')]
    snapshots += [('termux', 'termux/termux-packages', lock['termux_revision']),
                  ('zenith', 'zenithblue-oss/panvk-kbase-android', lock['zenith_revision'])]
    for kind, repo, revision in snapshots:
        with (sources / f'{kind}-recipes-{revision}.tar.gz').open('wb') as output:
            subprocess.run(['gh', 'api', f'repos/{repo}/tarball/{revision}'], stdout=output, check=True)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=HERE, text=True).strip()
    subprocess.run(['git', 'archive', '--format=tar.gz', '-o',
                    str((sources / f'packaging-recipes-{revision}.tar.gz').resolve()), 'HEAD'],
                   cwd=HERE, check=True)
    # All upstream source, exact recipe snapshots, compiler pins and build
    # workflows accompany the binary. No dependency on artifact retention to
    # obtain source after downloading this bundle.
    for name in ('lock.json', 'README.md', 'launcher.py', 'package.py', 'fetch.py', 'test.py'):
        shutil.copyfile(HERE / name, sources / name)
    (sources / 'SHA256SUMS').write_text(''.join(
        hashlib.file_digest(p.open('rb'), 'sha256').hexdigest() + '  ' + p.name + '\n'
        for p in sorted(sources.iterdir()) if p.is_file() and p.name != 'SHA256SUMS'))
    archive = args.destination / f"{lock['package']}_{lock['version']}_sources.tar.xz"
    with tarfile.open(archive, 'w:xz') as output:
        output.add(sources, arcname='sources')


if __name__ == '__main__':
    main()
