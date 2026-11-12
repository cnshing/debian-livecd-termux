#!/usr/bin/env python3
"""Bounded wider probe run; retain failures and raw per-test output."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument('--abi', choices=('android', 'glibc'), required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--driver', type=Path)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=False)
home = Path.home()
pan = home / 'gpu-x1s/panvk'
features = pan / 'wider' / a.abi / 'features'
driver = a.driver or pan / ('android/lib' if a.abi == 'android' else 'glibc/icd') / 'libvulkan_panfrost.so'
env = os.environ.copy()
for name in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'VK_DRIVER_FILES', 'VK_ICD_FILENAMES',
             'GALLIUM_DRIVER', 'MESA_LOADER_DRIVER_OVERRIDE', 'BIONILUX_EXTRA_PRELOAD'):
    env.pop(name, None)
env['LD_LIBRARY_PATH'] = str(pan / 'android/xlibs')
if a.abi == 'glibc':
    env['BIONILUX_LIBRARY_PATH'] = str(pan / 'glibc/lib') + ':' + os.environ['PREFIX'] + '/opt/google/chrome/lib'
tests = [(name, []) for name in ('sync-features', 'compute-features', 'graphics-features', 'texture-features', 'bc-format-probe')]
tests += [('phase7-api', [case]) for case in ('maintenance8', 'maintenance9', 'internal-queues', 'unified', 'copy-indirect', 'maintenance7')]
tests += [('phase7-compute', [case]) for case in ('quads', 'linear', 'fma', 'relaxed', 'untyped', 'constant-data', 'user-type')]
if a.abi == 'android':
    tests += [(name, []) for name in ('ahb', 'ahb_linear', 'ahb_render', 'ahb_vendor', 'ahb_vendor_linear', 'fdimport', 'fdimport_mtk')]
    tests += [('ahb_linear', ['read'])]
results = {'abi': a.abi, 'driver': str(driver), 'tests': []}
for name, args in tests:
    label = '-'.join([name, *args])
    binary = features / name
    command = ['timeout', '-k', '5', '45']
    if a.abi == 'glibc':
        command.append('bionilux')
    command += [str(binary), str(driver), *args]
    start = time.monotonic()
    completed = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=55)
    log = completed.stdout.decode(errors='replace')
    (a.out / (label + '.txt')).write_text(log)
    results['tests'].append({'name': label, 'code': completed.returncode,
        'seconds': time.monotonic() - start, 'log': label + '.txt',
        'timeout': completed.returncode in (124, 137)})
    (a.out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(label, 'exit', completed.returncode, flush=True)
print('COMPLETE', len(tests), 'processes;', sum(t['code'] == 0 for t in results['tests']), 'exit zero', flush=True)
