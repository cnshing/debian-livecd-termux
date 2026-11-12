#!/usr/bin/env python3
"""Plan CI builds and check patches for the recipes in packages/.

  recipes.py plan [--all] [NAME...]    Print the GitHub Actions build matrix as JSON.
  recipes.py unbuilt < MATRIX          Drop the sets an earlier run already built, for CI.
  recipes.py artifact NAME             Print the download URL of a set's packages from an earlier run.
  recipes.py check-patches [NAME...]   Apply each recipe's patches to its pinned source.
  recipes.py prepare CHECKOUT [NAME...]  Stage recipes in the pinned Termux checkout for building NAME.
  recipes.py order NAME...            Print packages and local dependencies in build order.
  recipes.py host-packages NAME...    Print the build-machine packages a cross build of NAME needs.
  recipes.py config                   Print the builder revision and image for CI.
  recipes.py pins CHECKOUT            Print every package name the recipes build, for install.sh's pin.
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
import urllib.parse
import urllib.request

PACKAGES = Path(__file__).resolve().parents[1] / 'packages'
BUILD_CONFIG = Path(__file__).with_name('termux-build.json')
CACHE = Path(os.environ.get('LIVECD_RECIPE_CACHE', str(Path.home() / '.cache/livecd-recipes')))
# Groups that may need more disk than a runner has free, so CI clears some first. ubuntu-26.04 runners
# had 78 GB free in November 2026, plenty for every other recipe, and clearing takes 3 to 7 minutes.
LARGE = {'chromium'}
# Recipes that take most of a job's time on their own. Each gets a job of its own, holding only the
# recipes it needs, so nothing that shares a dependency with it adds to its build time.
SEPARATE = {'chromium'}
# Minutes. GitHub stops any job on its own runners at 360; others stop sooner so the caches still save.
TIMEOUT, SEPARATE_TIMEOUT = 350, 360
# Termux's repository keeps only the newest version of each package, so CI takes whatever version it has
# rather than compiling the pinned builder's older one. These recipes still need the builder's exact
# versions: Chromium's host tools must match its source, and a newer release would break the build.
EXACT_DEPENDENCIES = {'chromium'}
# Overrides that change only how a package behaves, not the headers or libraries others build against:
# mesa only adds locking inside its VirGL vtest client. Recipes that depend on one build against
# Termux's own recipe of that name instead, so it gets a job of its own and Chromium's exact-version
# build does not compile it.
BEHAVIOUR_ONLY = {'mesa'}
# Build-machine libraries that a recipe's own tools link when it is cross-compiled. They are installed
# in the builder container before the build, since termux-packages refuses sudo inside a recipe.
HOST_PACKAGES = {'lsp-plugins-lv2': ['libcairo2-dev', 'libsndfile1-dev']}
# CI reuses a set's packages while everything it is built from stays the same: its recipes, the builder
# revision and the settings above. Bump this after changing how CI builds packages in some other way,
# so that every set is built again.
BUILD_EPOCH = 1
# What termux-packages fills in when it applies a patch; the values only matter for applying.
PLACEHOLDERS = {'@TERMUX_PREFIX@': '/data/data/com.termux/files/usr', '@TERMUX_HOME@': '/data/data/com.termux/files/home'}
READ = '''set +u
source "$1" >/dev/null
printf '%s\\0' "$TERMUX_PKG_VERSION" "${TERMUX_PKG_SRCURL[*]}" "${TERMUX_PKG_SHA256[*]}" \
    "$TERMUX_PKG_DEPENDS" "$TERMUX_PKG_BUILD_DEPENDS" "$TERMUX_PKG_SKIP_SRC_EXTRACT" "$TERMUX_PKG_ANTI_BUILD_DEPENDS"
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
    version, urls, hashes, depends, build_depends, skip, anti = output.split('\0')[:7]

    def names(text):
        return {re.match(r'[^\s(]+', part.strip()).group() for part in re.split(r'[,|]', text) if part.strip()}
    # The builder neither builds nor installs an anti-build dependency, so a set does not need it.
    return {'version': version, 'urls': urls.split(), 'hashes': hashes.split(), 'skip_extract': skip == 'true',
            'depends': names(depends + ',' + build_depends) - names(anti)}


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
            # Tests import some recipes' Python, and the bytecode they leave records when that happened.
            if path.is_file() and '__pycache__' not in path.parts:
                digest.update(str(path.relative_to(PACKAGES)).encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()[:16]


def plan(names):
    """One job per dependent set: a job holds its targets and the recipes they need from here."""
    revision = json.loads(BUILD_CONFIG.read_text())['revision']
    ours = set(all_names())
    needs = {name: read_recipe(name)['depends'] & (ours - BEHAVIOUR_ONLY) for name in ours}
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
        exact = bool(group[name] & EXACT_DEPENDENCIES)
        hosts = host_packages(ordered)
        inputs = json.dumps([BUILD_EPOCH, revision, exact, hosts, directory_hash(ordered)])
        members = sorted(group[name])
        label = '_'.join(members)
        # The cache keys include this name, and GitHub rejects keys over 512 characters.
        if len(label) > 100:
            label = '{}_and_{}_more'.format(members[0], len(members) - 1)
        include.append({'name': label, 'packages': ' '.join(ordered),
                        'hash': directory_hash(ordered), 'large': bool(group[name] & LARGE),
                        'timeout': SEPARATE_TIMEOUT if separate else TIMEOUT,
                        'exact': exact, 'host_packages': ' '.join(hosts),
                        # Names the set's packages after everything they are built from.
                        'artifact': 'debs-{}-{}'.format(sorted(group[name])[0],
                                                        hashlib.sha256(inputs.encode()).hexdigest()[:16])})
    return {'include': include}


def host_packages(names):
    return sorted({package for name in names for package in HOST_PACKAGES.get(name, [])})


def built_artifact(name):
    """The newest unexpired artifact NAME from this run or from the default branch of this repository.

    Runs from forks and other branches are left out, so a pull request cannot supply released packages.
    """
    url = '{}/repos/{}/actions/artifacts?name={}&per_page=100'.format(
        os.environ.get('GITHUB_API_URL', 'https://api.github.com'), os.environ['GITHUB_REPOSITORY'],
        urllib.parse.quote(name))
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                                                   'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request) as response:
        artifacts = json.load(response)['artifacts']
    for artifact in artifacts:
        run = artifact.get('workflow_run') or {}
        if artifact['expired'] or artifact['name'] != name:
            continue
        if str(run.get('id')) == os.environ.get('GITHUB_RUN_ID') or (
                run.get('head_branch') == os.environ['DEFAULT_BRANCH']
                and run.get('head_repository_id') == run.get('repository_id')):
            return artifact
    return None


def unbuilt(matrix):
    return {'include': [job for job in matrix['include'] if not built_artifact(job['artifact'])]}


def build_order(names):
    return [name for group in plan(checked(names))['include'] for name in group['packages'].split()]


def prepare_builder(checkout, packages=None):
    """Retain upstream source patches and helpers when overlaying a recipe.

    With PACKAGES, a behaviour-only recipe outside them keeps Termux's own recipe, restored from the
    checkout if an earlier staging replaced it."""
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
            if packages is not None and name in BEHAVIOUR_ONLY and name not in packages:
                shutil.rmtree(checkout / 'x11-packages' / name, ignore_errors=True)
                subprocess.check_call(['git', '-C', str(checkout), 'checkout', '-q', 'HEAD', '--',
                                       str(Path(upstream['path']).parent)])
                continue
            for relative, expected in upstream.get('remove_files', {}).items():
                path = Path(relative)
                if path.is_absolute() or '..' in path.parts or (PACKAGES / name / path).exists():
                    raise RuntimeError('Invalid upstream removal: ' + relative)
                pinned = subprocess.check_output(['git', '-C', str(checkout), 'show',
                    'HEAD:x11-packages/' + name + '/' + relative])
                if hashlib.sha256(pinned).hexdigest() != expected:
                    raise RuntimeError('Pinned upstream removal changed: ' + relative)
                (checkout / 'x11-packages' / name / path).unlink(missing_ok=True)
        # The builder rejects two recipes with one name. Ours replaces Termux's, wherever it lives,
        # as one in x11-packages already is: avahi, for example, is Termux's root-packages recipe.
        for repository in ('packages', 'root-packages'):
            shutil.rmtree(checkout / repository / name, ignore_errors=True)
        shutil.copytree(PACKAGES / name, checkout / 'x11-packages' / name, dirs_exist_ok=True)
    print('Staged', len(all_names()), 'recipes at', revision)


def pins(checkout):
    """Each recipe's package and subpackages, including those of Termux's x11-packages recipe that
    prepare_builder keeps beside ours, as code-oss keeps code-is-code-oss. Pinning these too keeps
    Termux's newer build of a subpackage from demanding its own newer main package."""
    names = []
    for name in all_names():
        metadata = PACKAGES / name / 'upstream.json'
        removed = set(json.loads(metadata.read_text()).get('remove_files', {})) if metadata.is_file() else set()
        upstream = {path.name for path in (Path(checkout) / 'x11-packages' / name).glob('*.subpackage.sh')} - removed
        subpackages = upstream | {path.name for path in (PACKAGES / name).glob('*.subpackage.sh')}
        names += [name] + sorted(subpackage[:-len('.subpackage.sh')] for subpackage in subpackages)
    return names


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
    commands.add_parser('unbuilt')
    commands.add_parser('artifact').add_argument('name')
    commands.add_parser('check-patches').add_argument('names', nargs='*')
    preparer = commands.add_parser('prepare')
    preparer.add_argument('checkout')
    preparer.add_argument('names', nargs='*')
    commands.add_parser('order').add_argument('names', nargs='+')
    commands.add_parser('host-packages').add_argument('names', nargs='+')
    commands.add_parser('config')
    commands.add_parser('pins').add_argument('checkout')
    installer = commands.add_parser('install-output')
    installer.add_argument('directory')
    installer.add_argument('names', nargs='+')
    args = parser.parse_args()
    if args.command == 'plan':
        print(json.dumps(plan(all_names() if args.all else checked(args.names))))
    elif args.command == 'unbuilt':
        print(json.dumps(unbuilt(json.load(sys.stdin))))
    elif args.command == 'artifact':
        artifact = built_artifact(args.name)
        if artifact:
            print(artifact['archive_download_url'])
    elif args.command == 'prepare':
        prepare_builder(args.checkout, args.names or None)
    elif args.command == 'order':
        print(' '.join(build_order(args.names)))
    elif args.command == 'host-packages':
        print(' '.join(host_packages(build_order(args.names))))
    elif args.command == 'config':
        config = json.loads(BUILD_CONFIG.read_text())
        print('revision=' + config['revision'])
        print('image=' + config['image'])
    elif args.command == 'pins':
        print('\n'.join(pins(args.checkout)))
    elif args.command == 'install-output':
        install_output(args.directory, checked(args.names))
    else:
        results = [check_patches(name) for name in (checked(args.names) or all_names())]
        sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
