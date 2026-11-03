#!/usr/bin/env python3
"""Plan CI builds and check patches for the recipes in packages/.

  recipes.py plan [--all] [NAME...]    Print the GitHub Actions build matrix as JSON.
  recipes.py changed BASE              Print the packages changed since the commit BASE.
  recipes.py check-patches [NAME...]   Apply each recipe's patches to its pinned source.
  recipes.py prepare CHECKOUT         Stage recipes in the pinned Termux checkout.
  recipes.py order NAME...            Print packages and local dependencies in build order.
  recipes.py config                   Print the builder revision and image for CI.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

PACKAGES = Path(__file__).resolve().parents[1] / 'packages'
BUILD_CONFIG = Path(__file__).with_name('termux-build.json')
CACHE = Path(os.environ.get('LIVECD_RECIPE_CACHE', str(Path.home() / '.cache/livecd-recipes')))
# Groups that need more disk than a runner has free by default, so CI clears some first.
LARGE = {'chromium', 'code-oss', 'easyeffects', 'livecd-mixtapes', 'livecd-mozjs-128', 'lsp-plugins-lv2', 'mission-center', 'nautilus', 'serein'}
# Recipes that take most of a job's time on their own. Each gets a job of its own, holding only the
# recipes it needs, so nothing that shares a dependency with it adds to its build time.
SEPARATE = {'chromium'}
# Minutes. GitHub stops any job on its own runners at 360; others stop sooner so the caches still save.
TIMEOUT, SEPARATE_TIMEOUT = 350, 360
# What termux-packages fills in when it applies a patch; the values only matter for applying.
PLACEHOLDERS = {'@TERMUX_PREFIX@': '/data/data/com.termux/files/usr', '@TERMUX_HOME@': '/data/data/com.termux/files/home'}
READ = '''set +u
source "$1" >/dev/null
printf '%s\\0' "$TERMUX_PKG_VERSION" "${TERMUX_PKG_SRCURL[*]}" "${TERMUX_PKG_SHA256[*]}" \
    "$TERMUX_PKG_DEPENDS" "$TERMUX_PKG_BUILD_DEPENDS" "$TERMUX_PKG_SKIP_SRC_EXTRACT"
'''
POST_GET_SOURCE = '''set -e
termux_download() {
    if test -f "$2" && printf '%s  %s\\n' "$3" "$2" | sha256sum --check --quiet 2>/dev/null; then return; fi
    curl -fsSL --retry 3 -o "$2" "$1"
    printf '%s  %s\\n' "$3" "$2" | sha256sum --check --quiet
}
source "$1/build.sh" >/dev/null
cd "$TERMUX_PKG_SRCDIR"
if declare -F termux_step_post_get_source >/dev/null; then termux_step_post_get_source; fi
'''


def read_recipe(name):
    output = subprocess.check_output(['bash', '-c', READ, 'read', str(PACKAGES / name / 'build.sh')], text=True)
    version, urls, hashes, depends, build_depends, skip = output.split('\0')[:6]
    return {'version': version, 'urls': urls.split(), 'hashes': hashes.split(), 'skip_extract': skip == 'true',
            'depends': {re.match(r'[^\s(]+', part.strip()).group()
                        for part in re.split(r'[,|]', depends + ',' + build_depends) if part.strip()}}


def all_names():
    return sorted(path.parent.name for path in PACKAGES.glob('*/build.sh'))


def checked(names):
    unknown = sorted(set(names) - set(all_names()))
    if unknown:
        raise SystemExit('Unknown package: ' + ', '.join(unknown))
    return names


def directory_hash(names):
    digest = hashlib.sha256()
    for name in sorted(names):
        for path in sorted((PACKAGES / name).rglob('*')):
            if path.is_file():
                digest.update(str(path.relative_to(PACKAGES)).encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()[:16]


def plan(names):
    """One job per dependent set: a job holds its targets and the recipes they need from here."""
    ours = set(all_names())
    needs = {name: read_recipe(name)['depends'] & ours for name in ours}
    selected, pending = set(), list(names)
    while pending:
        name = pending.pop()
        if name not in selected:
            selected.add(name)
            pending += needs[name]
    group = {name: {name} for name in selected}
    for name in sorted(selected):
        for dependency in needs[name]:
            if SEPARATE & {name, dependency}:
                continue
            merged = group[name] | group[dependency]
            for member in merged:
                group[member] = merged

    def closure(members):
        ordered = []

        def visit(package):
            if package not in ordered:
                for dependency in sorted(needs[package]):
                    visit(dependency)
                ordered.append(package)
        for member in sorted(members):
            visit(member)
        return ordered
    # A group that only supplies a separate recipe is already built in that recipe's job.
    covered = set().union(*(closure({name}) for name in selected & SEPARATE))
    include, seen = [], set()
    for name in sorted(selected):
        if name in seen:
            continue
        seen |= group[name]
        separate = bool(group[name] & SEPARATE)
        if not separate and group[name] <= covered:
            continue
        ordered = closure(group[name])
        include.append({'name': '_'.join(sorted(group[name])), 'packages': ' '.join(ordered),
                        'hash': directory_hash(ordered), 'large': bool(group[name] & LARGE),
                        'timeout': SEPARATE_TIMEOUT if separate else TIMEOUT})
    return {'include': include}


def changed(base):
    try:
        output = subprocess.check_output(['git', 'diff', '--name-only', base, 'HEAD'],
                                         cwd=PACKAGES.parent, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        # A new branch or a force push has no usable base.
        return all_names()
    paths = [Path(line) for line in output.splitlines()]
    if any(str(path) in ('tools/recipes.py', 'tools/termux-build.json', '.github/workflows/packages.yml')
           for path in paths):
        return all_names()
    selected = {path.parts[1] for path in paths if len(path.parts) > 1 and path.parts[0] == 'packages'}
    changed_paths = {PACKAGES.parent / path for path in paths}
    # Local source and shared helper links are part of their owning recipes.
    for name in all_names():
        if any(path.is_symlink() and path.resolve() in changed_paths
               for path in (PACKAGES / name).rglob('*')):
            selected.add(name)
    return sorted(selected & set(all_names()))


def build_order(names):
    return [name for group in plan(checked(names))['include'] for name in group['packages'].split()]


def prepare_builder(checkout):
    """Retain upstream source patches and helpers when overlaying a recipe."""
    checkout = Path(checkout).resolve()
    config = json.loads(BUILD_CONFIG.read_text())
    revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != config['revision']:
        raise RuntimeError('Termux checkout must be at ' + config['revision'])
    for name in all_names():
        metadata = PACKAGES / name / 'upstream.json'
        if metadata.is_file():
            upstream = json.loads(metadata.read_text())
            original = subprocess.check_output(['git', '-C', str(checkout), 'show', 'HEAD:' + upstream['path']])
            if upstream['revision'] != revision or hashlib.sha256(original).hexdigest() != upstream['sha256']:
                raise RuntimeError('Pinned upstream recipe changed: ' + name)
            for relative, expected in upstream.get('remove_files', {}).items():
                path = Path(relative)
                if path.is_absolute() or '..' in path.parts or (PACKAGES / name / path).exists():
                    raise RuntimeError('Invalid upstream removal: ' + relative)
                pinned = subprocess.check_output(['git', '-C', str(checkout), 'show',
                    'HEAD:x11-packages/' + name + '/' + relative])
                if hashlib.sha256(pinned).hexdigest() != expected:
                    raise RuntimeError('Pinned upstream removal changed: ' + relative)
                (checkout / 'x11-packages' / name / path).unlink(missing_ok=True)
        shutil.copytree(PACKAGES / name, checkout / 'x11-packages' / name, dirs_exist_ok=True)
    print('Staged', len(all_names()), 'recipes at', revision)


def install_output(directory, names):
    """Install completed package artifacts rather than copying over installed files."""
    names = list(names)
    for name in list(names):
        for subpackage in sorted((PACKAGES / name).glob('*.subpackage.sh')):
            subname = subpackage.name.removesuffix('.subpackage.sh')
            if subname not in names:
                names.append(subname)
    candidates = {}
    for path in Path(directory).resolve().glob('*.deb'):
        name = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package'], text=True).strip()
        if name in names and (name not in candidates or path.stat().st_mtime_ns > candidates[name].stat().st_mtime_ns):
            candidates[name] = path
    missing = set(names) - candidates.keys()
    if missing:
        raise RuntimeError('Missing output package(s): ' + ', '.join(sorted(missing)))
    subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends',
                    *[str(candidates[name]) for name in names]], check=True)


def fetch(url, expected):
    """Download into the cache, reusing an entry only while its hash still matches."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / url.rsplit('/', 1)[-1]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        subprocess.run(['curl', '-fsSL', '--retry', '3', '-o', str(path), url], check=True)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f'SHA-256 mismatch for {url}: {actual}')
    return path


def check_patches(name):
    """Follow termux-packages' source and patch steps, so a stale patch fails before any build."""
    recipe = read_recipe(name)
    patches = sorted((PACKAGES / name).glob('*.patch')) + sorted((PACKAGES / name).glob('*.patch64'))
    if (PACKAGES / name / 'upstream.json').is_file() and not patches:
        print(f'ok   {name}: recipe override; pinned upstream patches checked when staging')
        return True
    if name == 'chromium' and not patches:
        # This recipe changes build options, inheriting assets and platform
        # patches from the pinned termux-packages checkout. Its post-get-source
        # step requires that checkout and host-tools; the package builder runs
        # the version guard and verifies the source archive there.
        print('ok   chromium: no local source patches; upstream preparation runs in the package builder')
        return True
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / 'src'
        source.mkdir()
        if not recipe['skip_extract']:
            for index, (url, expected) in enumerate(zip(recipe['urls'], recipe['hashes'])):
                subprocess.run(['tar', 'xf', str(fetch(url, expected)), '-C', str(source),
                                '--strip-components=' + ('0' if index else '1')], check=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(['bash', '-c', POST_GET_SOURCE, 'post', str(PACKAGES / name)], check=True,
                       env={**os.environ, 'TERMUX_PKG_BUILDER_DIR': str(PACKAGES / name),
                            'TERMUX_PKG_SRCDIR': str(source), 'TERMUX_PKG_CACHEDIR': str(CACHE)})
        for patch in patches:
            text = patch.read_text()
            for placeholder, value in PLACEHOLDERS.items():
                text = text.replace(placeholder, value)
            result = subprocess.run(['patch', '--batch', '--silent', '-p1'], cwd=source, input=text, text=True,
                                    capture_output=True)
            if result.returncode:
                print(f'FAIL {name}: {patch.name}\n{result.stdout}{result.stderr}', file=sys.stderr)
                return False
    print(f'ok   {name}: {recipe["version"]}, {len(patches)} patch(es)')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    planner = commands.add_parser('plan')
    planner.add_argument('--all', action='store_true')
    planner.add_argument('names', nargs='*')
    commands.add_parser('changed').add_argument('base')
    commands.add_parser('check-patches').add_argument('names', nargs='*')
    commands.add_parser('prepare').add_argument('checkout')
    commands.add_parser('order').add_argument('names', nargs='+')
    commands.add_parser('config')
    installer = commands.add_parser('install-output')
    installer.add_argument('directory')
    installer.add_argument('names', nargs='+')
    args = parser.parse_args()
    if args.command == 'plan':
        print(json.dumps(plan(all_names() if args.all else checked(args.names))))
    elif args.command == 'changed':
        print(' '.join(changed(args.base)))
    elif args.command == 'prepare':
        prepare_builder(args.checkout)
    elif args.command == 'order':
        print(' '.join(build_order(args.names)))
    elif args.command == 'config':
        config = json.loads(BUILD_CONFIG.read_text())
        print('revision=' + config['revision'])
        print('image=' + config['image'])
    elif args.command == 'install-output':
        install_output(args.directory, checked(args.names))
    else:
        results = [check_patches(name) for name in (checked(args.names) or all_names())]
        sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
