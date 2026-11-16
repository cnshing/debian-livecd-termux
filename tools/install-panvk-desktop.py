#!/usr/bin/env python3
"""Install the qualified Mali driver and controller from APT or pinned assets."""
from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src/native'))
from panvk_device import qualified


def cache_repository(downloads, prefix):
    root = prefix / 'var/lib/livecd-panvk-repo'
    root.mkdir(parents=True, exist_ok=True)
    for path in downloads:
        target = root / path.name
        shutil.copyfile(path, target.with_suffix('.new'))
        target.with_suffix('.new').replace(target)
    records = []
    for path in sorted(root.glob('*.deb')):
        control = subprocess.check_output(['dpkg-deb', '-f', str(path)], text=True).strip()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(control + f'\nFilename: ./{path.name}\nSize: {path.stat().st_size}\nSHA256: {sha}\n')
    data = ('\n'.join(records) + '\n').encode()
    (root / 'Packages.new').write_bytes(data)
    (root / 'Packages.new').replace(root / 'Packages')
    (root / 'Release.new').write_text('Origin: LiveCD-PanVK\nLabel: LiveCD-PanVK\n'
        'Suite: livecd-panvk\nCodename: livecd-panvk\nArchitectures: aarch64 all\n'
        + 'Date: ' + format_datetime(datetime.now(timezone.utc), usegmt=True) + '\n'
        + f'SHA256:\n {hashlib.sha256(data).hexdigest()} {len(data)} Packages\n')
    (root / 'Release.new').replace(root / 'Release')
    source = prefix / 'etc/apt/sources.list.d/livecd-panvk.list'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f'deb [trusted=yes] file://{root} ./\n')
    pin = prefix / 'etc/apt/preferences.d/livecd-panvk'
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text('Package: mesa-vulkan-icd-panvk-kbase livecd-desktop\n'
        'Pin: release n=livecd-panvk\nPin-Priority: 1001\n')
    return source


def ensure(packages, release, offline=False, prefix=None):
    pending, downloads = [], []
    with tempfile.TemporaryDirectory(prefix='livecd-panvk-') as folder:
        for item in packages:
            name, version = item['name'], item['version']
            current = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}\t${Version}', name],
                                     text=True, capture_output=True)
            if current.returncode == 0 and current.stdout.startswith('installed\t') and subprocess.run(
                    ['dpkg', '--compare-versions', current.stdout.split('\t', 1)[1].strip(), 'ge', version],
                    capture_output=True).returncode == 0:
                continue
            target = name + '=' + version
            available = subprocess.run(['apt-cache', 'show', target], capture_output=True, text=True)
            identities = [dict(line.split(': ', 1) for line in stanza.splitlines() if ': ' in line)
                          for stanza in available.stdout.split('\n\n')]
            if available.returncode == 0 and any(
                    fields.get('Package') == name and fields.get('Version') == version
                    for fields in identities):
                pending.append(target)
                continue
            if offline:
                raise RuntimeError('This offline repository lacks ' + target + '; use a newer offline tarball.')
            path = Path(folder) / item['file']
            subprocess.run(['curl', '--fail', '--location', '--retry', '3',
                            release + '/' + item['file'], '-o', str(path)], check=True)
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != item['sha256']:
                raise RuntimeError('Checksum mismatch for ' + name)
            metadata = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package', 'Version'], text=True)
            fields = dict(line.split(': ', 1) for line in metadata.splitlines() if ': ' in line)
            if fields != {'Package': name, 'Version': version}:
                raise RuntimeError('Unexpected package identity for ' + name)
            pending.append(str(path))
            downloads.append(path)
        if downloads:
            source = cache_repository(downloads, prefix or Path(os.environ['PREFIX']))
            subprocess.run(['apt-get', '-o', 'Dir::Etc::SourceList=' + str(source),
                '-o', 'Dir::Etc::SourceParts=-', '-o', 'APT::Get::List-Cleanup=0', 'update'], check=True)
        if pending:
            subprocess.run(['apt-get', '-y', '--allow-downgrades',
                            '-o', 'Dpkg::Options::=--force-confdef',
                            '-o', 'Dpkg::Options::=--force-confold',
                            'install', *pending], check=True)


def main():
    if not qualified():
        return
    lock = json.loads((REPO / 'packages/mesa-vulkan-icd-panvk-kbase/install.lock.json').read_text())
    ensure(lock['packages'], lock['release'], os.environ.get('LIVECD_OFFLINE') == '1')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print('Mali desktop setup: ' + str(error), file=sys.stderr)
        sys.exit(2)
