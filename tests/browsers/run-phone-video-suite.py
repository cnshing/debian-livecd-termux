#!/usr/bin/env python3
"""Run a small private-display matrix over SSH, retaining pixels and passive ADB focus checks.

Prepare remote ROOT with browsers/, fixtures-v2/, and the candidate google-chrome
launcher. Optional chrome-experimental and ion-dma-heap.so enable the ION experiment.
No input or windows are sent to the Android display. Every unexpected failure fails
the suite, including a negative control that fails for the wrong reason.
"""
import argparse
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile


def focus(serial):
    text = subprocess.check_output(['adb', '-s', serial, 'shell', 'dumpsys', 'activity', 'activities'], text=True)
    lines = [line.strip() for line in text.splitlines() if 'mResumedActivity:' in line]
    if not lines:
        # The keyguard can cover every activity. WindowManager still records
        # input focus; compare it without unlocking or sending Android input.
        windows = subprocess.check_output(['adb', '-s', serial, 'shell', 'dumpsys', 'window', 'displays'], text=True)
        lines = [line.strip() for line in windows.splitlines()
                 if line.strip().startswith(('mCurrentFocus=', 'mFocusedApp='))]
        if not any(line.startswith('mCurrentFocus=') for line in lines):
            raise RuntimeError('ADB did not report Android activity or window focus')
    return lines


def pixel_negative_passes(result, exit_code):
    layers = [layer for case in result.get('cases', []) for sample in case.get('pixels', [])
              for layer in sample.get('layers', {}).values()]
    # An older, otherwise correct frame is a presentation failure, not evidence
    # that the separate-plane allocator still produces corrupt colors.
    corrupted = bool(layers) and all(not layer.get('ok') and (
        layer.get('error', '').startswith(('Invalid frame barcode cell', 'Frame barcode sync is wrong')) or
        ('error' not in layer and max(layer.get('color_errors', []), default=0) > 16))
        for layer in layers)
    return (exit_code != 0 and result.get('ok') is False and
            'Video pixels differ from reference' in result.get('error', '') and
            result.get('video_decoders') == ['VaapiVideoDecoder'] and corrupted)


def cogl_negative_passes(result, exit_code, library, shell_log):
    return (exit_code != 0 and result.get('shell_exit_before_cleanup') == -6 and
            library in result.get('shell_libraries', []) and
            any(sample['requested_fullscreen'] for case in result.get('cases', []) for sample in case['samples']) and
            'FULLSCREEN_INVALID_SHM_READ' in shell_log)


def presentation_negative_passes(result, exit_code):
    pixels = [sample for case in result.get('cases', []) for sample in case.get('pixels', [])]
    failures = [layer for sample in pixels for layer in sample.get('layers', {}).values()
                if not layer.get('ok')]
    return (exit_code != 0 and result.get('ok') is False and
            result.get('gpu_verified') is True and result.get('hardware_decode_verified') is True and
            result.get('video_decoders') == ['VaapiVideoDecoder'] and
            'Video pixels differ from reference' in result.get('error', '') and
            bool(failures) and all(layer.get('error', '').startswith('Wrong frame:') for layer in failures) and
            all(sample.get('layers', {}).get('browser', {}).get('ok') is True for sample in pixels))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ssh', default='termux')
    p.add_argument('--remote-root', required=True)
    p.add_argument('--adb-serial', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--ion-experiment', action='store_true')
    p.add_argument('--ion-shim', help='Remote path to an alternate experimental ION/VA trace preload')
    p.add_argument('--installed-chrome', help='Remote installed launcher; adds persistent hardware-video and override checks')
    p.add_argument('--installed-chromium', help='Remote VA-API-enabled Chromium launcher; adds strict hardware VP9/HEVC cases')
    p.add_argument('--installed-ungoogled-chromium', help='Remote ungoogled Chromium launcher; adds strict hardware VP9/HEVC cases')
    p.add_argument('--composited-fullscreen', action='store_true', help='Keep private fullscreen windows in stage captures')
    p.add_argument('--original-cogl', help='Remote original libmutter-cogl-16.so for the crash negative control')
    p.add_argument('--cogl-gi-preload', help='Remote GI search-path redirect preload; required for the Cogl control')
    p.add_argument('--only', action='append', help='Select a matrix entry by name')
    args = p.parse_args()
    if args.original_cogl and not args.cogl_gi_preload:
        p.error('--original-cogl requires --cogl-gi-preload to prevent loading two copies through introspection')
    args.out.mkdir(parents=True, exist_ok=False)
    root = args.remote_root.rstrip('/')
    boot = subprocess.check_output(['ssh', args.ssh, 'cat /proc/sys/kernel/random/boot_id'], text=True).strip()
    adb_boot = subprocess.check_output(['adb', '-s', args.adb_serial, 'shell', 'cat',
                                       '/proc/sys/kernel/random/boot_id'], text=True).strip()
    if not boot or boot != adb_boot:
        raise RuntimeError('SSH and ADB refer to different devices')
    cases = [(f'chrome-default-{codec}', 'chrome', {}, file, False, 'lorie', False)
             for codec, file in [('vp9', 'chart-vp9.webm'), ('h264', 'chart-h264.mp4'), ('hevc', 'chart-hevc.mp4')]]
    cases += [('chromium-gpu-vp9', 'chromium', {}, 'chart-vp9.webm', False, 'lorie', False),
              ('chrome-software-vp9', 'chrome', {'LIVECD_CHROME_GPU': '0'}, 'chart-vp9.webm', False, 'lorie', False),
              ('chrome-xvfb-vp9', 'chrome', {'LIVECD_CHROME_GPU': '0'}, 'chart-vp9.webm', False, 'xvfb', False),
              ('hardware-negative-vp9', 'chrome', {'LIVECD_CHROME_HARDWARE_VIDEO': '1'}, 'chart-vp9.webm', True, 'lorie', False)]
    if args.ion_experiment:
        trace = {'LIVECD_CHROME_HARDWARE_VIDEO': '1', 'TERMUX_VA_CONTIGUOUS_DMABUF': '1',
                 'LIVECD_TEST_EXTRA_PRELOAD': args.ion_shim or root + '/ion-dma-heap.so', 'LIVECD_TVA_TRACE_EXPORT': '1'}
        cases += [('ion-control-vp9', 'chrome', trace, 'chart-vp9.webm', True, 'lorie', True),
                  ('ion-candidate-vp9', 'chrome', {**trace, 'LIVECD_TVA_ION_FALLBACK': '1'},
                   'chart-vp9.webm', False, 'lorie', True),
                  ('ion-candidate-hevc', 'chrome', {**trace, 'LIVECD_TVA_ION_FALLBACK': '1'},
                   'chart-hevc.mp4', False, 'lorie', True)]
    if args.original_cogl:
        cases.append(('original-cogl-negative', 'chrome', {}, 'chart-vp9.webm', False, 'lorie', False))
    if args.installed_chrome:
        cases += [('installed-hardware-vp9', 'chrome', {}, 'chart-vp9.webm', False, 'lorie', False),
                  ('installed-hardware-hevc', 'chrome', {}, 'chart-hevc.mp4', False, 'lorie', False),
                  ('installed-software-override', 'chrome', {'LIVECD_CHROME_HARDWARE_VIDEO': '0'},
                   'chart-vp9.webm', False, 'lorie', False),
                  ('installed-color-negative', 'chrome', {'LIVECD_CHROME_HARDWARE_VIDEO': '1',
                    'LIVECD_TVA_ION_FALLBACK': '0'}, 'chart-vp9.webm', True, 'lorie', False)]
    if args.installed_chromium:
        cases += [('chromium-hardware-vp9', 'chromium', {'LIVECD_CHROMIUM_HARDWARE_VIDEO': '1'},
                   'chart-vp9.webm', False, 'lorie', False),
                  ('chromium-hardware-hevc', 'chromium', {'LIVECD_CHROMIUM_HARDWARE_VIDEO': '1'},
                   'chart-hevc.mp4', False, 'lorie', False)]
    if args.installed_ungoogled_chromium:
        cases += [('ungoogled-chromium-hardware-vp9', 'ungoogled-chromium',
                   {'LIVECD_UNGOOGLED_CHROMIUM_HARDWARE_VIDEO': '1'}, 'chart-vp9.webm', False, 'lorie', False),
                  ('ungoogled-chromium-hardware-hevc', 'ungoogled-chromium',
                   {'LIVECD_UNGOOGLED_CHROMIUM_HARDWARE_VIDEO': '1'}, 'chart-hevc.mp4', False, 'lorie', False)]
    for browser, launcher, variable in (
            ('chromium', args.installed_chromium, 'LIVECD_CHROMIUM_HARDWARE_VIDEO'),
            ('ungoogled-chromium', args.installed_ungoogled_chromium, 'LIVECD_UNGOOGLED_CHROMIUM_HARDWARE_VIDEO')):
        if launcher:
            cases += [(browser + '-completion-negative-vp9', browser,
                       {variable: '1', 'LIVECD_VA_DISABLE_COMPLETION': '1'}, 'chart-vp9.webm', False, 'lorie', False),
                      (browser + '-software-override-vp9', browser, {variable: '0'},
                       'chart-vp9.webm', False, 'lorie', False),
                      (browser + '-h264-fallback', browser, {variable: '1'},
                       'chart-h264.mp4', False, 'lorie', False)]
    selected = [c for c in cases if not args.only or c[0] in args.only]
    if not selected or (args.only and set(args.only) - {c[0] for c in cases}):
        p.error('Unknown or empty case selection')
    report = {'cases': []}
    for name, browser, env, fixture, negative, server, experimental in selected:
        destination = args.out / name
        destination.mkdir()
        remote = root + '/' + args.out.name + '-' + name
        flags = ['--require-gpu'] if env.get('LIVECD_CHROME_GPU') != '0' else []
        command = ['python', root + '/browsers/test-fullscreen.py', browser, '--x-server', server,
                   '--media-dir', root + '/fixtures-v2', '--fixture-manifest', root + '/fixtures-v2/manifest.json',
                   '--case', fixture, '--cycles', '6', '--dwell', '1', '--browser-flag=--window-size=1280,1100',
                   '--out', remote, *flags]
        if browser == 'chrome':
            command += ['--browser-command', args.installed_chrome if name.startswith('installed-') else
                        root + ('/chrome-experimental' if experimental else '/google-chrome')]
        if browser == 'chromium' and args.installed_chromium:
            command += ['--browser-command', args.installed_chromium]
        if browser == 'ungoogled-chromium' and args.installed_ungoogled_chromium:
            command += ['--browser-command', args.installed_ungoogled_chromium]
        presentation_negative = '-completion-negative-' in name
        if (env.get('LIVECD_CHROME_HARDWARE_VIDEO') == '1' or name.startswith('installed-hardware-')
                or name.startswith(('chromium-hardware-', 'ungoogled-chromium-hardware-')) or presentation_negative):
            command += ['--private-daemon', '--require-hardware-decode']
        elif name.endswith('-h264-fallback'):
            command += ['--private-daemon']
        if args.composited_fullscreen:
            command += ['--composited-fullscreen']
        if name == 'original-cogl-negative':
            command += ['--shell-preload', args.cogl_gi_preload, '--shell-lib-dir', str(Path(args.original_cogl).parent)]
        remote_command = shlex.join(['env', *(f'{k}={v}' for k, v in env.items()), *command])
        before = focus(args.adb_serial)
        print('RUN', name, flush=True)
        with (destination / 'run.log').open('w') as log:
            process = subprocess.run(['ssh', args.ssh, remote_command], stdout=log, stderr=log, timeout=300)
        after = focus(args.adb_serial)
        archive = subprocess.check_output(['ssh', args.ssh, shlex.join(['tar', '-C', remote,
            '--exclude=profile', '--exclude=config', '--exclude=data', '--exclude=cache',
            '--exclude=runtime', '--exclude=state', '-cf', '-', '.'])])
        with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
            contents.extractall(destination, filter='data')
        result = json.loads((destination / 'result.json').read_text())
        isolation = json.loads((destination / 'isolation.json').read_text())
        if presentation_negative:
            expected = presentation_negative_passes(result, process.returncode)
        else:
            expected = pixel_negative_passes(result, process.returncode) if negative else (
                        process.returncode == 0 and result.get('ok') is True)
        if name == 'installed-software-override' or '-software-override-' in name:
            expected = expected and result.get('video_decoders') == ['VpxVideoDecoder']
        if name.endswith('-h264-fallback'):
            expected = expected and result.get('video_decoders') == ['FFmpegVideoDecoder']
        # Chrome Linux has no software HEVC decoder. Preserve this as a capability
        # check, explicitly separate from tests that actually compare decoded pixels.
        unsupported = name == 'chrome-default-hevc'
        if unsupported:
            samples = [s['state']['video'] for case in result.get('cases', []) for s in case['samples']]
            expected = (process.returncode != 0 and not result.get('video_decoders') and bool(samples) and
                all(v and 'DEMUXER_ERROR_NO_SUPPORTED_STREAMS' in (v.get('error') or '') and
                    v['quality']['totalVideoFrames'] == 0 for v in samples))
        if name == 'original-cogl-negative':
            expected = cogl_negative_passes(result, process.returncode, args.original_cogl,
                                          (destination / 'shell.log').read_text())
        entry = {'name': name, 'command': remote_command, 'expected_pixel_failure': negative,
                 'expected_presentation_failure': presentation_negative,
                 'expected_unsupported': unsupported, 'expected_shell_crash': name == 'original-cogl-negative',
                 'exit_code': process.returncode, 'focus_before': before, 'focus_after': after,
                 'isolation_ok': isolation['ok'], 'ok': expected and isolation['ok'] and before == after,
                 'error': result.get('error'), 'decoders': result.get('video_decoders')}
        report['cases'].append(entry)
        print(name, ('EXPECTED_UNSUPPORTED' if unsupported else 'PASS') if entry['ok'] else 'FAIL',
              entry.get('error') or '', flush=True)
        report['ok'] = all(c['ok'] for c in report['cases'])
        (args.out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
