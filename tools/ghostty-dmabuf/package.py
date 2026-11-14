#!/usr/bin/env python3
"""Assemble immutable CI binaries under one private prefix; never rebuild them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
PREFIX = Path('data/data/com.termux/files/usr')
ALIASES = {'libX11-xcb.so.1': 'libX11-xcb.so', 'libxcb.so.1': 'libxcb.so',
           'libxcb-dri3.so.0': 'libxcb-dri3.so', 'libxcb-present.so.0': 'libxcb-present.so',
           'libxcb-randr.so.0': 'libxcb-randr.so', 'libxcb-shm.so.0': 'libxcb-shm.so',
           'libxcb-sync.so.1': 'libxcb-sync.so', 'libxcb-xfixes.so.0': 'libxcb-xfixes.so',
           'libxshmfence.so.1': 'libxshmfence.so'}


def sha(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def unique(root, name):
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise RuntimeError(f'Expected one {name} in {root}, got {len(matches)}')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path, help='driver/, mesa/, gtk/ downloaded Actions artifacts')
    parser.add_argument('output', type=Path)
    parser.add_argument('--sources', type=Path, required=True, help='Complete companion source directory')
    args = parser.parse_args()
    lock = json.loads((HERE / 'lock.json').read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    stage = args.output / 'stage'
    if stage.exists():
        raise RuntimeError('Refusing to reuse an existing package stage')
    root = stage / PREFIX / 'lib' / lock['package']
    doc = stage / PREFIX / 'share/doc' / lock['package']
    doc.mkdir(parents=True)
    root.mkdir(parents=True)
    # Upstream copyright texts are included in both the binary and source bundle.
    with tarfile.open(args.sources / 'gtk-4.24.1.tar.xz') as archive:
        for name in ('COPYING',):
            member = next(m for m in archive.getmembers() if m.name == 'gtk-4.24.1/' + name)
            (doc / ('GTK-' + name)).write_bytes(archive.extractfile(member).read())
    shutil.copyfile(HERE.parents[1] / 'packages/mesa-vulkan-icd-panvk-kbase-sync-fd/UPSTREAM-LICENSE', doc / 'PanVK-LICENSE')
    with tarfile.open(args.sources / 'mesa-26.2.6.tar.xz') as archive:
        member = archive.getmember('mesa-26.2.6/docs/license.rst')
        (doc / 'Mesa-LICENSE.rst').write_bytes(archive.extractfile(member).read())
    dependencies = {'python', 'ghostty (>= 1.4.0)', 'gtk4 (>= 4.24.1)'}
    for kind in ('gtk', 'mesa'):
        deb = unique(args.inputs / kind, lock[kind]['file'])
        if sha(deb) != lock[kind]['sha256']:
            raise RuntimeError('Input checksum mismatch: ' + str(deb))
        dependencies.update(subprocess.check_output(['dpkg-deb', '-f', str(deb), 'Depends'], text=True).strip().split(', '))
        extracted = args.output / ('unpacked-' + kind)
        subprocess.run(['dpkg-deb', '-x', str(deb), str(extracted)], check=True)
        lib = extracted / PREFIX / 'lib'
        if kind == 'gtk':
            (root / kind).mkdir()
            shutil.copyfile(lib / 'libgtk-4.so.1', root / kind / 'libgtk-4.so.1')
            checked = root / kind / 'libgtk-4.so.1'
        else:
            shutil.copytree(lib, root / kind, symlinks=True, ignore=shutil.ignore_patterns('pkgconfig'))
            checked = root / kind / 'libgallium-26.2.6.so'
        if sha(checked) != lock[kind]['library_sha256']:
            raise RuntimeError('Runtime checksum mismatch: ' + str(checked))
    # The input also contains the unpatched control: select patched/ explicitly.
    driver = unique(args.inputs / 'driver', 'PATCHES.txt').parent / lock['driver']['file']
    if sha(driver) != lock['driver']['sha256']:
        raise RuntimeError('Driver checksum mismatch')
    (root / 'driver/bionic').mkdir(parents=True)
    shutil.copyfile(driver, root / 'driver/bionic' / driver.name)
    for name in ('PATCHES.txt', 'DYNAMIC.txt', 'SHA256SUMS'):
        shutil.copyfile(driver.parent / name, doc / ('driver-' + name))
    for name in ('BUILD.txt', 'DEPENDENCIES.sha256', 'VERSIONS.txt'):
        shutil.copyfile(driver.parent.parent / name, doc / ('driver-' + name))
    (root / 'x11').mkdir()
    for alias, target in ALIASES.items():
        (root / 'x11' / alias).symlink_to('/' + str(PREFIX / 'lib' / target))
    (root / 'icd.json').write_text(json.dumps({'file_format_version': '1.0.0', 'ICD': {
        'library_path': './driver/bionic/libvulkan_panfrost.so', 'api_version': '1.3.363'}}) + '\n')
    (root / 'egl-vendor.json').write_text(json.dumps({'file_format_version': '1.0.0', 'ICD': {
        'library_path': 'libEGL_mesa.so.0'}}) + '\n')
    shutil.copyfile(HERE / 'lock.json', root / 'SOURCE.json')
    shutil.copyfile(HERE / 'README.md', doc / 'README.md')
    binary = stage / PREFIX / 'bin' / lock['package']
    binary.parent.mkdir()
    shutil.copyfile(HERE / 'launcher.py', binary)
    binary.chmod(0o755)
    manifest = {'version': lock['version'], 'files': {}, 'links': {}}
    for path in sorted(root.rglob('*')):
        name = str(path.relative_to(root))
        if path.is_symlink():
            manifest['links'][name] = os.readlink(path)
        elif path.is_file():
            manifest['files'][name] = sha(path)
    (root / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    control = stage / 'DEBIAN'
    control.mkdir()
    (control / 'control').write_text(
        f"Package: {lock['package']}\nVersion: {lock['version']}\nArchitecture: aarch64\n"
        'Maintainer: cnshing\n'
        'Homepage: https://github.com/cnshing/debian-livecd-termux\n'
        'Description: Opt-in tested Ghostty GTK GL DMA-BUF stack for x1s\n'
        ' Private GTK, Mesa and PanVK libraries; use ghostty-panvk-dmabuf explicitly.\n'
        ' Experimental G77 workgroups, SYNC_FD and synchronous dma-buf fallback.\n'
        f"Installed-Size: {sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()) // 1024}\n"
        'Depends: ' + ', '.join(sorted(dependencies)) + '\n')
    epoch = lock['source_date_epoch']
    for path in sorted(stage.rglob('*'), reverse=True):
        os.utime(path, (epoch, epoch), follow_symlinks=False)
    os.utime(stage, (epoch, epoch))
    out = args.output / f"{lock['package']}_{lock['version']}_aarch64.deb"
    subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '-z6', '--build', str(stage), str(out)],
                   check=True, env={**os.environ, 'SOURCE_DATE_EPOCH': str(epoch)})
    (args.output / 'SHA256SUMS').write_text(sha(out) + '  ' + out.name + '\n')
    print(out)


if __name__ == '__main__':
    main()
