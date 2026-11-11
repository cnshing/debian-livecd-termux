#!/usr/bin/env python3
"""Choose the Termux mirror CI downloads from, and print its main and x11 URLs for $GITHUB_OUTPUT.

Usage: termux-mirror.py [default | fastest | NAME]
  default  packages-cf.termux.dev, Termux's Cloudflare cache of its primary host.
  fastest  Every mirror pkg knows, tried at once: each whose main and x11 indexes are no more than
           LAG behind the primary's is timed downloading the main index, and the quickest wins.
           Mirrors that stopped syncing, which Termux's own picker has handed out, are left out.
  NAME     A mirror file of termux-tools, such as mirror.fcix.net or europe/mirror.fcix.net.
The mirrors are pkg's own list, from the termux-tools release the pinned termux-packages builds,
checked against that recipe's SHA-256. The glibc repository has no mirrors and stays on its host.
"""
import concurrent.futures
import email.utils
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import time
import urllib.request

PIN = json.loads(Path(__file__).with_name('termux-build.json').read_text())['revision']
PRIMARY = 'https://packages.termux.dev/apt/'
DEFAULT = {'main': 'https://packages-cf.termux.dev/apt/termux-main', 'x11': 'https://packages-cf.termux.dev/apt/termux-x11'}
INRELEASE = {'main': '/dists/stable/InRelease', 'x11': '/dists/x11/InRelease'}
TIMED = '/dists/stable/main/binary-aarch64/Packages'
LAG = 6 * 3600


def get(url, timeout=30):
    request = urllib.request.Request(url, headers={'User-Agent': 'livecd-termux-ci'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def mirrors():
    """{'region/name': {'main': URL, 'x11': URL}} from the pinned termux-tools source."""
    recipe = get(f'https://raw.githubusercontent.com/termux/termux-packages/{PIN}/packages/termux-tools/build.sh').decode()
    url = re.search(r'^TERMUX_PKG_SRCURL=(\S+)', recipe, re.M).group(1)
    sha256 = re.search(r'^TERMUX_PKG_SHA256=(\S+)', recipe, re.M).group(1)
    source = get(url)
    if hashlib.sha256(source).hexdigest() != sha256:
        raise SystemExit('termux-tools source does not match its recipe: ' + url)
    found = {}
    with tarfile.open(fileobj=io.BytesIO(source)) as archive:
        for member in archive.getmembers():
            parts = member.name.split('/')
            if member.isfile() and len(parts) == 4 and parts[1] == 'mirrors':
                text = archive.extractfile(member).read().decode()
                urls = dict(re.findall(r'^(MAIN|X11)="?([^"\s]+)"?', text, re.M))
                if 'MAIN' in urls and 'X11' in urls:
                    found['/'.join(parts[2:])] = {'main': urls['MAIN'].rstrip('/'), 'x11': urls['X11'].rstrip('/')}
    return found


def published(inrelease):
    """When a repository's index was generated, in seconds since the epoch."""
    date = re.search(rb'^Date: (.+)$', inrelease, re.M).group(1).decode()
    return email.utils.parsedate_to_datetime(date).timestamp()


def timed(urls, reference):
    """Seconds to fetch the main index, or None for a mirror that is unreachable or out of date."""
    try:
        for repo, path in INRELEASE.items():
            if published(get(urls[repo] + path, timeout=10)) < reference[repo] - LAG:
                return None
        start = time.monotonic()
        get(urls['main'] + TIMED, timeout=30)
        return time.monotonic() - start
    except Exception:
        return None


def main():
    choice = (sys.argv[1:] or ['default'])[0] or 'default'
    if choice == 'default':
        chosen, name = DEFAULT, 'default'
    else:
        known = mirrors()
        if choice == 'fastest':
            reference = {repo: published(get(PRIMARY + 'termux-' + repo + path)) for repo, path in INRELEASE.items()}
            candidates = {'default': DEFAULT, **known}
            with concurrent.futures.ThreadPoolExecutor(32) as pool:
                times = dict(zip(candidates, pool.map(lambda urls: timed(urls, reference), candidates.values())))
            ranked = sorted((seconds, name) for name, seconds in times.items() if seconds is not None)
            for seconds, name in ranked[:5]:
                print(f'{name}: {seconds:.2f}s', file=sys.stderr)
            print(f'{len(ranked)} of {len(candidates)} mirrors are reachable and up to date.', file=sys.stderr)
            name = ranked[0][1] if ranked else 'default'
            chosen = candidates[name]
        else:
            matches = [key for key in known if key == choice or key.split('/', 1)[1] == choice]
            if not matches:
                raise SystemExit(f'Unknown mirror {choice}. termux-tools knows: ' + ' '.join(sorted(known)))
            name = matches[0]
            chosen = known[name]
    print(f'Termux mirror: {name}', file=sys.stderr)
    print(f'mirror_main={chosen["main"]}\nmirror_x11={chosen["x11"]}')


if __name__ == '__main__':
    main()
