#!/usr/bin/env python3
"""Check continuous private desktop soak evidence; this is not a benchmark."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def check(folder, minimum=1800):
    result = json.loads((folder / 'result.json').read_text())
    assert result.get('completed'), result.get('error', 'run incomplete')
    assert not result.get('unexpected_process_exit'), 'workload exited'
    assert json.loads((folder / 'isolation.json').read_text())['ok'], 'isolation failed'
    soak = result['soak']
    requested, completed = soak['seconds_requested'], soak['seconds_completed']
    assert math.isfinite(completed) and completed >= requested >= minimum, 'short soak'
    samples = soak['samples']
    assert len(samples) >= 2, 'missing samples'
    elapsed = [s['elapsed'] for s in samples]
    assert all(math.isfinite(t) for t in elapsed), 'invalid sample time'
    assert 0 <= elapsed[0] <= 60, 'missing initial sample'
    assert all(0 < b - a <= 90 for a, b in zip(elapsed, elapsed[1:])), 'sample gap'
    assert 0 <= completed - elapsed[-1] <= 60, 'missing final sample'
    driver = [p for p in result['shell']['libraries'] if p.endswith('/libvulkan_panfrost.so')]
    assert len(driver) == 1, 'ambiguous driver'
    identities, metrics = {}, {}
    for processes in [*(s['processes'] for s in samples), soak['final']]:
        assert set(processes) == {'shell', 'cube', 'gears'}, 'missing workload'
        for name, process in processes.items():
            pid = identities.setdefault(name, process['pid'])
            assert pid == process['pid'], name + ' restarted'
            assert [p for p in process['libraries'] if p.endswith('/libvulkan_panfrost.so')] == driver, name + ' driver changed'
            assert not any('angle' in p.lower() for p in process['libraries']), name + ' loaded ANGLE'
            assert any(d['target'] == '/dev/mali0' for d in process['devices']), name + ' lost Mali'
            status = dict(line.split(':', 1) for line in process['status'].splitlines() if ':' in line)
            assert status['State'].strip()[0] not in 'ZTX', name + ' stopped'
            rss = int(status['VmRSS'].split()[0])
            metric = metrics.setdefault(name, {'rss_kib_first': rss, 'rss_kib_max': rss,
                                               'fds_first': process['fd_count']})
            metric.update(rss_kib_last=rss, rss_kib_max=max(rss, metric['rss_kib_max']),
                          fds_last=process['fd_count'])
    assert identities['shell'] == result['shell']['pid'], 'different compositor'
    images = set()
    for sample in samples:
        name = sample['capture']
        assert Path(name).name == name, 'invalid capture path'
        png = (folder / name).read_bytes()
        assert png.startswith(b'\x89PNG\r\n\x1a\n') and len(png) > 24, 'invalid capture'
        images.add(hashlib.sha256(png).hexdigest())
    assert len(images) > 1, 'all soak captures identical'
    intervals = re.findall(r'(\d+) frames in ([\d.]+) seconds = ([\d.]+) FPS',
                           (folder / 'soak-gears.log').read_text())
    assert intervals and all(int(frames) > 0 and float(fps) > 0 for frames, _, fps in intervals), 'no GL progress'
    reported = sum(float(seconds) for _, seconds, _ in intervals)
    assert reported >= minimum - 90, 'GL progress does not cover the soak'
    checked = {'ok': True, 'seconds_completed': completed, 'samples': len(samples),
               'unique_captures': len(images), 'driver': driver[0], 'pids': identities,
               'gl_progress_seconds': reported, 'process_metrics': metrics,
               'scope': 'process stability and isolation; GTK/Ghostty pixels checked separately'}
    (folder / 'soak-results.json').write_text(json.dumps(checked, indent=2) + '\n')
    return checked


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--minimum-seconds', type=int, default=1800)
    args = parser.parse_args()
    if args.minimum_seconds < 1:
        parser.error('minimum must be positive')
    checked = check(args.folder, args.minimum_seconds)
    print(args.folder.name, 'PASS', round(checked['seconds_completed'], 2), 'seconds;',
          checked['samples'], 'samples; stable GPU processes and preserved isolation')
