#!/usr/bin/env python3
"""Add every Termux package an installation can need to an apt repository, for offline installs.

Usage: offline-repo.py [--main URL] [--x11 URL] [--cache DIR] REPO TERMUX-PACKAGES
REPO is the directory make-apt-repo.sh built, holding this project's packages as suite livecd.
TERMUX-PACKAGES is a checkout of termux-packages at the pinned revision: its keyring verifies the
mirrors, and its bootstrap script names what a fresh Termux starts with. --main and --x11 pick a
mirror, as tools/termux-mirror.py prints. --cache keeps the downloads: apt fetches only what the
directory lacks, and afterwards it holds exactly the chosen packages, ready to cache for next time.

This host's apt resolves dependencies against Termux's current main, x11 and glibc repositories,
from an empty dpkg database, so nothing is assumed installed. It resolves:
  - one transaction like install.sh's: the bootstrap and Essential packages, which its full-upgrade
    replaces, src/native/packages.txt, x11-repo, and the default overlays with their hooks' packages;
  - then each opt-in overlay, and each package of this project's, alone, with Recommends, as
    `pkg install NAME` would.
What that downloads becomes suite termux, beside livecd. install.sh switches to these two suites
alone when it finds dists/termux. A failure in the first transaction fails; one in the rest warns.
"""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
MIRROR = 'https://packages-cf.termux.dev/apt'
# Only main and x11 have mirrors. glibc-repo's own source line.
GLIBC = f'{MIRROR}/termux-glibc glibc stable'
# Hooks call apt-get themselves. These are the files that do, read for the names they install.
HOOK_SCRIPTS = ['hooks/termux/*', 'browsers/install.sh']


def listed(path):
    """The same simple YAML list reader as src/apply-overlays.py."""
    return re.findall(r'^- (.+?)\s*$', path.read_text(), flags=re.M) if path.is_file() else []


def hook_packages(overlay):
    """Package names in an overlay's apt-get install lines and packages="..." lists."""
    names = []
    for pattern in HOOK_SCRIPTS:
        for script in sorted(overlay.glob(pattern)):
            if not script.is_file():
                continue
            text = script.read_text(errors='replace')
            words = re.findall(r'packages="([^"]*)"', text)
            words += re.findall(r'apt-get\b[^\n]*?\binstall\b([^\n|;&]*)', text)
            words += re.findall(r'"\$\{apt\[@\]\}" install([^\n|;&]*)', text)
            names += [w for chunk in words for w in chunk.split() if re.fullmatch(r'[a-z0-9][a-z0-9+.-]+', w)]
    return names


def bootstrap(termux):
    """What generate-bootstraps.sh puts in a fresh Termux."""
    script = (termux / 'scripts/generate-bootstraps.sh').read_text()
    # Literal names only: the package manager, apt, is Essential, and proot is for Android 10's variant.
    names = set(re.findall(r'^\s*pull_package ([a-z0-9][a-z0-9+.-]+)\s*$', script, flags=re.M)) - {'proot'}
    if len(names) < 20:
        raise SystemExit('generate-bootstraps.sh no longer lists its packages as pull_package NAME.')
    return sorted(names)


def ours():
    """The names install.sh pins to suite livecd."""
    names = []
    for recipe in sorted((ROOT / 'packages').iterdir()):
        if recipe.is_dir():
            names += [recipe.name] + [s.name[:-len('.subpackage.sh')] for s in recipe.glob('*.subpackage.sh')]
    return names


def index_field(packages_file, field, value=None):
    """Package names in an apt index, optionally only those whose FIELD is VALUE."""
    names = []
    for stanza in packages_file.read_text().split('\n\n'):
        fields = dict(re.findall(r'^([\w-]+): (.*)$', stanza, flags=re.M))
        if 'Package' in fields and (value is None or fields.get(field) == value):
            names.append(fields['Package'])
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--main', default=f'{MIRROR}/termux-main')
    parser.add_argument('--x11', default=f'{MIRROR}/termux-x11')
    parser.add_argument('--cache', type=Path)
    parser.add_argument('repo', type=Path)
    parser.add_argument('termux', type=Path)
    args = parser.parse_args()
    repo, termux = args.repo.resolve(), args.termux.resolve()
    work = Path(tempfile.mkdtemp(prefix='offline-repo-'))
    debs = args.cache.resolve() if args.cache else work / 'archives'
    etc = work / 'etc/apt'
    for path in (etc / 'preferences.d', etc / 'trusted.gpg.d', work / 'lists/partial', debs / 'partial'):
        path.mkdir(parents=True, exist_ok=True)
    for key in (termux / 'packages/termux-keyring').glob('*.gpg'):
        shutil.copy(key, etc / 'trusted.gpg.d')
    (etc / 'sources.list').write_text(f'deb [trusted=yes] file:{repo} livecd main\n'
                                      f'deb {args.main} stable main\ndeb {args.x11} x11 main\ndeb {GLIBC}\n')
    (etc / 'preferences.d/livecd').write_text(f'Package: {" ".join(ours())}\nPin: release n=livecd\nPin-Priority: 1001\n')
    (work / 'status').touch()
    apt = ['apt-get', '-q', '-y', '-o', f'Dir={work}/', '-o', f'Dir::State::status={work}/status',
           '-o', f'Dir::State::Lists={work}/lists', '-o', f'Dir::Cache::Archives={debs}',
           '-o', 'Dir::Etc::Trusted=/nonexistent', '-o', 'APT::Architecture=aarch64',
           '-o', 'APT::Architectures::=aarch64', '-o', 'Debug::NoLocking=1', '-o', 'Acquire::Languages=none']
    subprocess.run(apt + ['update'], check=True)
    chosen = set()

    def resolve(names, *options):
        """Download what installing NAMES needs; False if apt finds no solution."""
        simulated = subprocess.run(apt + ['install', '-s', *options, *names], capture_output=True, text=True)
        if simulated.returncode:
            print(simulated.stdout + simulated.stderr, flush=True)
            return False
        chosen.update(re.findall(r'^Inst (\S+) \((\S+) ', simulated.stdout, flags=re.M))
        subprocess.run(apt + ['install', '--download-only', *options, *names], check=True)
        return True

    lists = work / 'lists'
    essential = [name for index in sorted(lists.glob('*termux-main*_Packages'))
                 for name in index_field(index, 'Essential', 'yes')]
    livecd = index_field(next(lists.glob('*_dists_livecd_main_binary-aarch64_Packages')), 'Package')
    overlays = ROOT / 'overlays'
    default = listed(overlays / 'termux.yaml')
    first = [*bootstrap(termux), *essential, 'x11-repo', *(ROOT / 'src/native/packages.txt').read_text().split()]
    for name in default:
        first += listed(overlays / name / 'packages/termux.yaml') + hook_packages(overlays / name)
    first = list(dict.fromkeys(first))
    print('Resolving the default installation:', ' '.join(first), flush=True)
    if not resolve(first, '--no-install-recommends'):
        raise SystemExit('The default installation cannot be resolved from the current Termux repositories.')

    extras = []
    for overlay in sorted(p for p in overlays.iterdir() if p.is_dir() and p.name not in default):
        names = listed(overlay / 'packages/termux.yaml') + hook_packages(overlay)
        if names:
            extras.append((overlay.name, names))
    extras += [(name, [name]) for name in livecd if name not in first]
    failed = []
    for label, names in extras:
        print(f'Resolving {label}: {" ".join(names)}', flush=True)
        if not resolve(names):
            failed.append(label)
    for label in failed:
        print(f'::warning::{label} cannot be installed from the current Termux repositories; '
              'the offline repository leaves it out.')

    # Packages from the file: source stay where they are, so the downloads are only Termux's. A cached
    # download that nothing chose this time is dropped, from the cache as well as from the repository.
    count = size = 0
    for deb in debs.glob('*.deb'):
        name, version = (urllib.parse.unquote(part) for part in deb.name.split('_')[:2])
        if (name, version) in chosen:
            count, size = count + 1, size + deb.stat().st_size
        else:
            deb.unlink()
    subprocess.run([ROOT / 'tools/make-apt-repo.sh', debs, repo, 'termux'], check=True)
    shutil.rmtree(work)
    print(f'Added {count} Termux packages, {size / 2**20:.0f} MiB, as suite termux.')


if __name__ == '__main__':
    main()
