#!/usr/bin/env python3
"""Bounded, isolated CTS subsets on Termux; stop after the first bad test."""
import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import xml.etree.ElementTree as ET

ACCEPTED = {'Pass', 'NotSupported', 'QualityWarning', 'CompatibilityWarning'}


def qpa_results(text):
    results = []
    for match in re.finditer(r'<TestCaseResult\b.*?</TestCaseResult>', text, re.S):
        root = ET.fromstring(match[0])
        result = root.find('Result')
        if result is None or not root.get('CasePath'):
            continue
        results.append({'case': root.get('CasePath'), 'status': result.get('StatusCode'),
                        'detail': ''.join(result.itertext()).strip()})
    return results


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def memory_available():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1])
    raise RuntimeError('Cannot establish available memory')


def stop(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)


def main():
    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('vk', 'gles31'), required=True)
    parser.add_argument('--cts', type=Path, required=True, help='Extracted CTS out directory')
    parser.add_argument('--driver', type=Path, required=True)
    parser.add_argument('--pattern', action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--large-workgroups', action='store_true')
    parser.add_argument('--nested', action='store_true')
    parser.add_argument('--unmerged-compute', action='store_true',
                        help='Opt in to the experimental G77 unmerged compute mode')
    parser.add_argument('--uncached-host-memory', action='store_true',
                        help='Disable the optional write-back host-memory type for diagnosis')
    parser.add_argument('--trace-loader', type=Path,
                        help='Diagnostic forwarding loader; records setup and mapped readback')
    parser.add_argument('--case-timeout', type=int, default=45)
    parser.add_argument('--max-seconds', type=int, default=600)
    parser.add_argument('--max-cases', type=int, default=0, help='0 means all selected cases')
    parser.add_argument('--resume-from', type=Path)
    args = parser.parse_args()
    if args.nested and not args.large_workgroups:
        parser.error('--nested requires --large-workgroups')
    if args.trace_loader and args.suite != 'vk':
        parser.error('--trace-loader is only for the Vulkan suite')
    if min(args.case_timeout, args.max_seconds) < 1 or args.max_cases < 0:
        parser.error('Invalid run bounds')
    prefix = Path(os.environ['PREFIX'])
    cts, driver = args.cts.resolve(strict=True), args.driver.resolve(strict=True)
    executable = cts / ('deqp-vk' if args.suite == 'vk' else 'deqp-gles31')
    identity = {'suite': args.suite, 'cts_sha256': digest(executable),
                'driver_sha256': digest(driver), 'patterns': args.pattern,
                'large_workgroups': args.large_workgroups, 'nested': args.nested,
                'unmerged_compute': args.unmerged_compute,
                'uncached_host_memory': args.uncached_host_memory}
    if args.trace_loader:
        args.trace_loader = args.trace_loader.resolve(strict=True)
        identity['trace_loader_sha256'] = digest(args.trace_loader)
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    with (Path(os.environ['TMPDIR']) / 'livecd-panvk-cts.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run(args, prefix, cts, driver, executable, identity)


def run(args, prefix, cts, driver, executable, identity):
    icd = args.out / 'icd.json'
    icd.write_text(json.dumps({'file_format_version': '1.0.1', 'ICD': {
        'library_path': str(driver), 'api_version': '1.3.363'}}))
    env = os.environ.copy()
    for name in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'VK_DRIVER_FILES', 'VK_ICD_FILENAMES',
                 'MESA_GL_VERSION_OVERRIDE', 'MESA_GLSL_VERSION_OVERRIDE', 'BIONILUX_LIBRARY_PATH',
                 'MESA_SHADER_CACHE_DIR', '__EGL_VENDOR_LIBRARY_FILENAMES',
                 'LIBGL_ALWAYS_SOFTWARE', 'LIBGL_ALWAYS_INDIRECT', 'ZINK_DEBUG',
                 'MESA_VK_DEVICE_SELECT', 'DRI_PRIME', 'PANVK_KBASE_DRI3', 'PANVK_DEBUG',
                 'PANVK_TRACE_LOADER', 'PANVK_TRACE_SPIRV_DIR'):
        env.pop(name, None)
    if args.uncached_host_memory:
        env['PANVK_DEBUG'] = 'no_wb_mmap'
    env.update(LD_LIBRARY_PATH=str(prefix / 'lib/panvk-kbase/bionic/x11'),
               VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd),
               EGL_PLATFORM='surfaceless', GALLIUM_DRIVER='zink', MESA_LOADER_DRIVER_OVERRIDE='zink',
               PANVK_G77_LWG='1' if args.large_workgroups else '0',
               PANVK_G77_NESTED='1' if args.nested else '0', MESA_SHADER_CACHE_DISABLE='false',
               PANVK_G77_NO_MERGE='1' if args.unmerged_compute else '0',
               XDG_CACHE_HOME=str(args.out / 'cache'), XDG_CONFIG_HOME=str(args.out / 'config'))
    command = [str(executable), '--deqp-archive-dir=' + str(cts / 'data'),
               '--deqp-log-images=disable', '--deqp-log-shader-sources=disable',
               '--deqp-shadercache=disable', '--deqp-surface-type=pbuffer',
               '--deqp-surface-width=64', '--deqp-surface-height=64']
    if args.suite == 'vk':
        loader = prefix / 'lib/libvulkan.so'
        if args.trace_loader:
            spirv = args.out / 'spirv'
            spirv.mkdir()
            env.update(PANVK_TRACE_LOADER=str(loader), PANVK_TRACE_SPIRV_DIR=str(spirv))
        command.append('--deqp-vk-library-path=' + str(args.trace_loader or loader))
    selected = []
    for index, pattern in enumerate(args.pattern):
        listing = args.out / f'cases-{index}.txt'
        completed = subprocess.run([*command, '--deqp-case=' + pattern,
            '--deqp-runmode=txt-caselist', '--deqp-caselist-export-file=' + str(listing)],
            env=env, cwd=args.out, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        (args.out / f'listing-{index}.log').write_bytes(completed.stdout)
        if completed.returncode or not listing.exists():
            raise RuntimeError('CTS case listing failed; inspect listing log')
        for line in listing.read_text().splitlines():
            name = line.removeprefix('TEST: ').strip()
            if name.startswith('dEQP-') and name not in selected:
                selected.append(name)
    if not selected:
        raise RuntimeError('No tests matched; refusing an empty qualification run')
    (args.out / 'selected.txt').write_text('\n'.join(selected) + '\n')
    report = {'identity': identity, 'driver': str(driver), 'selected': len(selected),
              'results': [], 'complete': False, 'ok': False}
    for filename in ('BUILD.txt', 'PLATFORM.patch'):
        metadata = cts / filename
        if metadata.is_file():
            report[filename] = metadata.read_text()
    if args.resume_from:
        previous = json.loads((args.resume_from / 'results.json').read_text())
        previous['identity'].setdefault('unmerged_compute', False)
        previous['identity'].setdefault('uncached_host_memory', False)
        if previous['identity'] != identity:
            raise RuntimeError('Resume identities differ')
        if any(r['status'] not in ACCEPTED for r in previous['results']):
            raise RuntimeError('Prior run failed; diagnose it before retrying')
        report['resumed_from'] = str(args.resume_from.resolve())
        report['results'] = [{**r, 'origin': r.get('origin', str(args.resume_from.resolve()))}
                             for r in previous['results']]
    finished = {r['case'] for r in report['results']}
    started, ran = time.monotonic(), 0
    def save():
        report['counts'] = dict(Counter(r['status'] for r in report['results']))
        report['seconds'] = time.monotonic() - started
        (args.out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    for index, case in enumerate(selected):
        if case in finished:
            continue
        if time.monotonic() - started >= args.max_seconds or (args.max_cases and ran >= args.max_cases):
            report['stopped'] = 'run_bound'
            break
        if memory_available() < 3_000_000:
            report['stopped'] = 'memory_below_3GB'
            break
        qpa = args.out / f'{index:06d}.qpa'
        log = args.out / f'{index:06d}.log'
        case_started = time.monotonic()
        maps, timed_out = set(), False
        with log.open('wb') as output:
            proc = subprocess.Popen([*command, '--deqp-case=' + case,
                '--deqp-log-filename=' + str(qpa), '--deqp-watchdog=enable',
                '--deqp-watchdog-total-time-limit=' + str(args.case_timeout),
                '--deqp-watchdog-interval-time-limit=' + str(args.case_timeout)],
                cwd=args.out, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while proc.poll() is None:
                    try:
                        for line in (Path('/proc') / str(proc.pid) / 'maps').read_text().splitlines():
                            if any(part in line for part in ('panfrost', 'gallium', '/libEGL', '/libGLES', '/libvulkan')):
                                maps.add(line.split()[-1])
                    except OSError:
                        pass
                    if time.monotonic() - case_started > args.case_timeout + 5:
                        timed_out = True
                        break
                    time.sleep(.02)
            finally:
                stop(proc)
        parsed = qpa_results(qpa.read_text(errors='replace')) if qpa.exists() else []
        status = ('Timeout' if timed_out else 'Crash' if proc.returncode < 0 else 'Incomplete')
        detail = ''
        if not timed_out and len(parsed) == 1 and parsed[0]['case'] == case:
            status, detail = parsed[0]['status'], parsed[0]['detail']
            if proc.returncode and status in ACCEPTED:
                status = 'ProcessFailure'
        result = {'case': case, 'status': status, 'detail': detail, 'returncode': proc.returncode,
                  'seconds': time.monotonic() - case_started, 'qpa': qpa.name, 'log': log.name,
                  'libraries': sorted(maps), 'origin': str(args.out)}
        report['results'].append(result)
        ran += 1
        save()
        print(index + 1, '/', len(selected), case, status, flush=True)
        if status not in ACCEPTED:
            report['stopped'] = 'first_failure'
            break
    report['complete'] = len(report['results']) == len(selected)
    report['ok'] = report['complete'] and any(r['status'] == 'Pass' for r in report['results']) and all(
        r['status'] in ACCEPTED for r in report['results'])
    save()
    print(json.dumps({k: report[k] for k in ('complete', 'ok', 'counts')}, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
