#!/usr/bin/env python3
"""Host regressions for the pixel oracle, launcher gates, and library exclusions."""
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from video_oracle import compare, sha256, write_png

ROOT = Path(__file__).resolve().parents[2]
BROWSERS = ROOT / 'overlays/Browser+Chromium/browsers'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PixelOracle(unittest.TestCase):
    def test_positive_and_corrupted_controls(self):
        chart = load('fixtures', Path(__file__).with_name('make-video-fixtures.py')).chart
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            images = [chart(320, 180, i) for i in range(2)]
            for i, data in enumerate(images):
                write_png(folder / f'{i:03d}.png', 320, 180, data)
            fixture = {'width': 320, 'height': 180, 'frames': 2, 'references': '.',
                       'reference_sha256': [sha256(folder / f'{i:03d}.png') for i in range(2)]}
            box = dict(left=0, top=0, width=320, height=180)
            result = compare(folder / '001.png', box, folder, fixture, folder / 'positive.png', 1)
            self.assertTrue(result['ok'], result)
            swapped = bytearray(images[1])
            for i in range(0, len(swapped), 3):
                swapped[i], swapped[i + 2] = swapped[i + 2], swapped[i]
            write_png(folder / 'swap.png', 320, 180, swapped)
            self.assertFalse(compare(folder / 'swap.png', box, folder, fixture, folder / 'bad.png', 1)['ok'])
            with self.assertRaisesRegex(ValueError, 'Wrong frame'):
                compare(folder / '000.png', box, folder, fixture, folder / 'repeat.png', 1)
            flipped = b''.join(images[1][y * 960:(y + 1) * 960] for y in reversed(range(180)))
            write_png(folder / 'flip.png', 320, 180, flipped)
            with self.assertRaises(ValueError):
                compare(folder / 'flip.png', box, folder, fixture, folder / 'flipped.png', 1)
            (folder / '001.png').write_bytes(b'planted reference')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                compare(folder / 'positive.png', box, folder, fixture, folder / 'tamper.png', 1)


class LauncherGates(unittest.TestCase):
    def test_chrome_receipt_override_and_socket_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'bin').mkdir()
            chrome = folder / 'opt/google/chrome'
            (chrome / 'gpu').mkdir(parents=True)
            (chrome / 'gpu/freedreno_icd.json').write_text('{}')
            adapter = folder / 'libexec/livecd-browser/liblivecd_tva_ion-bf39f8bd.so'
            adapter.parent.mkdir(parents=True)
            adapter.touch()
            report = folder / 'report.json'
            recorder = '#!' + sys.executable + '\nimport json,os,sys\nfrom pathlib import Path\n' + \
                'Path(os.environ["VIDEO_TOOL_REPORT"]).write_text(json.dumps({"args":sys.argv,' + \
                '"env":dict(item.split("=",1) for item in Path("/proc/self/environ").read_bytes().decode().split("\\0") if "=" in item)}))\n'
            (chrome / 'chrome').write_text(recorder)
            (chrome / 'chrome').chmod(0o755)
            (folder / 'bin/bionilux').write_text('#!/bin/sh\nexec "$@"\n')
            (folder / 'bin/bionilux').chmod(0o755)
            (folder / 'bin/termux-va-start').write_text('#!/bin/sh\ntouch "$VIDEO_TOOL_STARTED"\n')
            (folder / 'bin/termux-va-start').chmod(0o755)
            source = (BROWSERS / 'google-chrome').read_text().replace(
                'prefix=/data/data/com.termux/files/usr', 'prefix=' + str(folder)).replace(
                '$HOME/.local/opt/livecd-native/gnome-48/share/doc/mutter/build-source.json', str(folder / 'receipt')).replace(
                '$HOME/.config/livecd-native/chrome-hardware-video', str(folder / 'hardware-video'))
            launcher = folder / 'google-chrome'
            launcher.write_text(source)
            for receipt in (None, False, True):
                if receipt is None:
                    (folder / 'receipt').unlink(missing_ok=True)
                else:
                    (folder / 'receipt').write_text('0010-clip-pixmap-damage' if receipt else '{}')
                for override in (None, '0', '1'):
                    for hardware in (None, '0', '1'):
                        for private in (None, 'socket', 'directory'):
                            with self.subTest(receipt=receipt, override=override, hardware=hardware, private=private):
                                env = {k: v for k, v in os.environ.items() if not k.startswith((
                                    'LIVECD_CHROME_', 'TERMUX_VA_', 'BIONILUX_'))}
                                started = folder / 'started'
                                started.unlink(missing_ok=True)
                                env.update(VIDEO_TOOL_REPORT=str(report), VIDEO_TOOL_STARTED=str(started))
                                if hardware is not None:
                                    env['LIVECD_CHROME_HARDWARE_VIDEO'] = hardware
                                if override is not None:
                                    env['LIVECD_CHROME_GPU'] = override
                                if private == 'socket':
                                    env['TERMUX_VA_SOCKET'] = '/private/va.sock'
                                elif private == 'directory':
                                    env['TERMUX_VA_SOCKET_DIR'] = '/private'
                                subprocess.run(['bash', str(launcher)], env=env, check=True)
                                observed = json.loads(report.read_text())
                                gpu = override == '1' or (override is None and bool(receipt))
                                self.assertEqual('--use-angle=vulkan' in observed['args'], gpu)
                                self.assertEqual('--disable-gpu' in observed['args'], not gpu)
                                self.assertEqual('LIBVA_DRIVER_NAME' in observed['env'], gpu and hardware == '1')
                                if gpu and hardware == '1':
                                    self.assertEqual(observed['env']['LIVECD_TVA_ION_FALLBACK'], '1')
                                    self.assertEqual(observed['env']['TERMUX_VA_CONTIGUOUS_DMABUF'], '1')
                                    self.assertTrue(observed['env']['BIONILUX_EXTRA_PRELOAD'].endswith(':' + str(adapter)))
                                if private and gpu and hardware == '1':
                                    self.assertEqual(observed['env']['TERMUX_VA_SOCKET'],
                                                     '/private/va.sock' if private == 'socket' else '/private/termux-va.sock')
                                    self.assertFalse(started.exists(), 'Private endpoint invoked global start helper')
            # The user's persistent opt-in must work with an unset environment,
            # while explicit 0 wins. Missing adapter must fail closed to software.
            for enabled, override, present in (('1', None, True), ('1', '0', True),
                                               ('0', None, True), ('invalid', None, True),
                                               ('1', '1', False)):
                with self.subTest(config=enabled, override=override, adapter=present):
                    (folder / 'hardware-video').write_text(enabled + '\n')
                    if not present:
                        adapter.unlink()
                    env = {k: v for k, v in os.environ.items() if not k.startswith((
                        'LIVECD_CHROME_', 'LIVECD_TVA_', 'TERMUX_VA_', 'BIONILUX_'))}
                    env.update(VIDEO_TOOL_REPORT=str(report), LIVECD_CHROME_GPU='1', TERMUX_VA_SOCKET='/private/va.sock')
                    if override is not None:
                        env['LIVECD_CHROME_HARDWARE_VIDEO'] = override
                    subprocess.run(['bash', str(launcher)], env=env, check=True)
                    observed = json.loads(report.read_text())
                    self.assertEqual('LIBVA_DRIVER_NAME' in observed['env'],
                                     present and (override == '1' or (override is None and enabled == '1')))

    def test_chromium_receipt_override_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'icd.json').write_text('{}')
            source = (BROWSERS / 'chromium-gpu.conf').read_text().replace(
                '$HOME/.local/opt/livecd-native/gpu/share/vulkan/icd.d/freedreno_icd.aarch64.json', str(folder / 'icd.json')).replace(
                '$HOME/.local/opt/livecd-native/gnome-48/share/doc/mutter/build-source.json', str(folder / 'receipt'))
            config = folder / 'config'
            config.write_text(source)
            for receipt in (None, False, True):
                if receipt is None:
                    (folder / 'receipt').unlink(missing_ok=True)
                else:
                    (folder / 'receipt').write_text('0010-clip-pixmap-damage' if receipt else '{}')
                for override in (None, '0', '1'):
                    env = {k: v for k, v in os.environ.items() if k != 'LIVECD_CHROMIUM_GPU'}
                    if override is not None:
                        env['LIVECD_CHROMIUM_GPU'] = override
                    result = subprocess.check_output(['bash', '-c', '. "$1"; printf "%s" "$CHROMIUM_FLAGS"', '_', str(config)],
                        env=env, text=True)
                    self.assertEqual('--use-angle=vulkan' in result, override == '1' or (override is None and bool(receipt)))


class LibraryClosure(unittest.TestCase):
    def test_planted_files_and_dangling_links(self):
        # Modules resolve PREFIX at import; no installation or network calls are made.
        original = os.environ.get('PREFIX')
        os.environ['PREFIX'] = '/nonexistent-video-test-prefix'
        try:
            module = load('native_video', BROWSERS / 'install-native-video.py')
        finally:
            if original is None:
                os.environ.pop('PREFIX')
            else:
                os.environ['PREFIX'] = original
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            module.check_forbidden_libraries(folder)
            for name in module.FORBIDDEN:
                path = folder / name
                for link in (False, True):
                    with self.subTest(name=name, dangling=link):
                        path.symlink_to('missing-library') if link else path.touch()
                        with self.assertRaisesRegex(RuntimeError, 'must not be'):
                            module.check_forbidden_libraries(folder)
                        path.unlink()


class PrebuiltBrowsers(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'A C compiler is required for the VA synchronization regression')
    def test_va_completion_tracks_contexts_and_propagates_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            # A fake provider exercises context lifetime and failure handling
            # without a device, libva installation or codec daemon.
            (folder / 'provider.c').write_text('''#include <stdio.h>
#include <stdint.h>
int vaBeginPicture(void *d,unsigned c,unsigned s) { (void)d;(void)c;(void)s;return 0; }
int vaEndPicture(void *d,unsigned c) { (void)d;return c==13 ? 27 : 0; }
int vaDestroyContext(void *d,unsigned c) { (void)d;(void)c;return 0; }
int vaSyncSurface2(void *d,unsigned s,uint64_t timeout) {
    (void)d; if(timeout!=500000000ull) return 99;
    printf("sync=%u\\n",s);return s==999 ? 31 : 0;
}
''')
            (folder / 'check.c').write_text('''#include <dlfcn.h>
#include <stdio.h>
int main(int argc,char **argv) {
    if(argc!=2) return 2;
    void *h=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);if(!h) return 3;
    int (*begin)(void *,unsigned,unsigned)=dlsym(h,"vaBeginPicture");
    int (*end)(void *,unsigned)=dlsym(h,"vaEndPicture");
    int (*destroy)(void *,unsigned)=dlsym(h,"vaDestroyContext");
    if(!begin||!end||!destroy) return 4;
    begin((void *)1,65535,101);begin((void *)2,65535,202);
    printf("end2=%d\\n",end((void *)2,65535));
    printf("end1=%d\\n",end((void *)1,65535));
    destroy((void *)1,65535);
    printf("destroyed=%d\\n",end((void *)1,65535));
    begin((void *)1,3,999);printf("failed_sync=%d\\n",end((void *)1,3));
    begin((void *)1,13,404);printf("failed_end=%d\\n",end((void *)1,13));
    destroy((void *)2,65535);destroy((void *)1,3);destroy((void *)1,13);
    return 0;
}
''')
            for name, source in (('compat.so', BROWSERS / 'va-completion.c'),
                                 ('provider.so', folder / 'provider.c')):
                subprocess.run(['cc', '-O2', '-shared', '-fPIC', '-I' + str(folder), str(source),
                    '-o', str(folder / name), '-ldl', '-pthread'], check=True)
            subprocess.run(['cc', str(folder / 'check.c'), '-o', str(folder / 'check'), '-ldl'], check=True)
            env = {**os.environ, 'LD_PRELOAD': str(folder / 'compat.so')}
            command = [str(folder / 'check'), str(folder / 'provider.so')]
            observed = subprocess.check_output(command, env=env, text=True, stderr=subprocess.DEVNULL)
            self.assertEqual(observed.splitlines(), ['sync=202', 'end2=0', 'sync=101', 'end1=0',
                'destroyed=5', 'sync=999', 'failed_sync=31', 'failed_end=27'])
            disabled = subprocess.check_output(command, env={**env, 'LIVECD_VA_DISABLE_COMPLETION': '1'}, text=True)
            self.assertEqual(disabled.splitlines(), ['end2=0', 'end1=0', 'destroyed=0', 'failed_sync=0', 'failed_end=27'])

    @unittest.skipUnless(shutil.which('cc'), 'A C compiler is required for the glibc hook regression')
    def test_fortified_readlink_uses_interposition_and_preserves_bounds(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / 'provider.c').write_text('''#include <unistd.h>
#include <string.h>
ssize_t readlink(const char *p, char *b, size_t n) {
    (void)p; const char *v="interposed-target"; size_t len=strlen(v);
    if (len>n) len=n; memcpy(b,v,len); return len;
}
ssize_t readlinkat(int fd, const char *p, char *b, size_t n) {
    (void)fd; return readlink(p,b,n);
}
''')
            (folder / 'check.c').write_text('''#include <unistd.h>
#include <stdio.h>
extern ssize_t __readlink_chk(const char *,char *,size_t,size_t);
extern ssize_t __readlinkat_chk(int,const char *,char *,size_t,size_t);
int main(int argc,char **argv) {
    (void)argv; char b[128];
    ssize_t n=__readlink_chk("/proc/self/exe",b,64,argc>1 ? 1 : sizeof(b));
    b[n]=0; puts(b);
    n=__readlinkat_chk(-100,"/proc/self/exe",b,64,sizeof(b));
    b[n]=0; puts(b); return 0;
}
''')
            for name, source in (('compat.so', BROWSERS / 'bionilux-fortify.c'),
                                 ('provider.so', folder / 'provider.c')):
                subprocess.run(['cc', '-shared', '-fPIC', str(source), '-o', str(folder / name)], check=True)
            subprocess.run(['cc', str(folder / 'check.c'), '-o', str(folder / 'check')], check=True)
            env = {**os.environ, 'LD_PRELOAD': str(folder / 'compat.so') + ':' + str(folder / 'provider.so')}
            observed = subprocess.check_output([str(folder / 'check')], env=env, text=True)
            self.assertEqual(observed.splitlines(), ['interposed-target', 'interposed-target'])
            overflow = subprocess.run([str(folder / 'check'), 'overflow'], env=env,
                capture_output=True, preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
            self.assertNotEqual(overflow.returncode, 0, 'The glibc bounds check was bypassed')

    def test_glibc_profiles_keep_bionic_environment_out(self):
        sys.path.insert(0, str(ROOT / 'src/native'))
        try:
            module = load('acceleration', ROOT / 'src/native/acceleration.py')
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            module.PREFIX = prefix
            driver = prefix / 'drivers'
            driver.mkdir()
            manifest = {'libraries': ['mesa', 'support'], 'preloads': ['ion.so'],
                'driver_directory': 'mesa/dri', 'mesa_library_directory': 'mesa',
                'vulkan_icd': 'icd.json', 'ion_fallback': 'preload'}
            for profile in ('chromium', 'ungoogled-chromium'):
                root = prefix / 'opt/livecd-browsers' / profile
                (root / 'lib').mkdir(parents=True)
                (root / 'chrome').touch()
                (root / 'lib/liblivecd-bionilux-fortify.so').touch()
                (root / 'lib/liblivecd-va-completion.so').touch()
                (root / 'livecd-vaapi.json').write_text(json.dumps({'format': 1, 'abi': 'glibc',
                    'browser': profile, 'binary': 'chrome', 'vaapi': True}))
                env = {'LD_PRELOAD': '/bionic/preload.so', 'LD_LIBRARY_PATH': '/bionic/lib',
                    'GALLIUM_DRIVER': 'virpipe', 'DISPLAY': ':71',
                    'TERMUX_VA_SOCKET': '/private/va.sock',
                    'LIVECD_' + profile.upper().replace('-', '_') + '_GPU': '1'}
                for video in ('on', 'off'):
                    with self.subTest(profile=profile, video=video), patch.dict(os.environ, env, clear=True), \
                            patch.object(module, 'settings', return_value={}), \
                            patch.object(module, 'stack', return_value=(driver, manifest)), \
                            patch.object(module, 'ensure_daemon') as daemon:
                        argv, observed = module.prepare(profile, ['unused', '--user-data-dir=/private/profile'], 'glibc', video)
                        self.assertEqual(argv[0], str(prefix / 'bin/bionilux'))
                        self.assertEqual(argv[1], str(root / 'chrome'))
                        self.assertIn('--user-data-dir=/private/profile', argv)
                        self.assertIn('--no-sandbox', argv)
                        self.assertNotIn('LD_PRELOAD', observed)
                        self.assertNotIn('LD_LIBRARY_PATH', observed)
                        self.assertNotIn('/bionic', observed['BIONILUX_LIBRARY_PATH'])
                        self.assertIn(str(root / 'lib'), observed['BIONILUX_LIBRARY_PATH'])
                        self.assertEqual(observed['DISPLAY'], str(prefix / 'tmp/.X11-unix/X71'))
                        self.assertEqual(observed['TERMUX_VA_SOCKET'], '/private/va.sock')
                        self.assertEqual(observed.get('LIBVA_DRIVER_NAME'), 'termuxva' if video == 'on' else None)
                        self.assertEqual(daemon.called, video == 'on')
                        if video == 'on':
                            self.assertTrue(observed['BIONILUX_EXTRA_PRELOAD'].startswith(
                                str(root / 'lib/liblivecd-va-completion.so') + ':'))
                        else:
                            self.assertNotIn('va-completion', observed.get('BIONILUX_EXTRA_PRELOAD', ''))
                receipt = root / 'livecd-vaapi.json'
                receipt.write_text('{"format":1,"abi":"bionic","vaapi":true}')
                self.assertFalse(module.chromium_has_vaapi(profile, 'glibc'))

    def test_keyguard_focus_is_compared_without_android_input(self):
        module = load('focus_suite', Path(__file__).with_name('run-phone-video-suite.py'))
        resumed = 'mResumedActivity: ActivityRecord{test}'
        with patch.object(module.subprocess, 'check_output', return_value=resumed) as command:
            self.assertEqual(module.focus('device'), [resumed])
            self.assertEqual(command.call_count, 1)
        locked = 'mCurrentFocus=Window{keyguard}\n mFocusedApp=ActivityRecord{desktop}'
        with patch.object(module.subprocess, 'check_output', side_effect=['no resumed activities', locked]):
            self.assertEqual(module.focus('device'), locked.splitlines()[0:1] + [locked.splitlines()[1].strip()])
        with patch.object(module.subprocess, 'check_output', side_effect=['', '']):
            with self.assertRaisesRegex(RuntimeError, 'focus'):
                module.focus('device')


class NegativeControls(unittest.TestCase):
    def test_only_the_intended_failure_counts(self):
        suite = load('phone_suite', Path(__file__).with_name('run-phone-video-suite.py'))
        wrong_pixels = {'ok': False, 'error': 'Video pixels differ from reference',
                        'video_decoders': ['VaapiVideoDecoder'], 'cases': [{'pixels': [{'layers': {
                            'browser': {'ok': False, 'error': 'Invalid frame barcode cell 0: [228, 139]'},
                            'shell': {'ok': False, 'error': 'Invalid frame barcode cell 0: [228, 139]'}}}]}]}
        self.assertTrue(suite.pixel_negative_passes(wrong_pixels, 1))
        self.assertFalse(suite.pixel_negative_passes({**wrong_pixels, 'cases': []}, 1))
        stale = {**wrong_pixels, 'cases': [{'pixels': [{'layers': {
            'browser': {'ok': True}, 'shell': {'ok': False, 'error': 'Wrong frame: expected 12, saw 3'}}}]}]}
        self.assertFalse(suite.pixel_negative_passes(stale, 1))
        self.assertFalse(suite.pixel_negative_passes({**wrong_pixels, 'error': 'Daemon failed'}, 1))
        self.assertFalse(suite.pixel_negative_passes({**wrong_pixels, 'video_decoders': ['VpxVideoDecoder']}, 1))
        self.assertFalse(suite.pixel_negative_passes(wrong_pixels, 0))
        stale_hardware = {**stale, 'gpu_verified': True, 'hardware_decode_verified': True}
        self.assertTrue(suite.presentation_negative_passes(stale_hardware, 1))
        self.assertFalse(suite.presentation_negative_passes({**stale_hardware, 'gpu_verified': False}, 1))
        self.assertFalse(suite.presentation_negative_passes({**stale_hardware, 'cases': []}, 1))
        self.assertFalse(suite.presentation_negative_passes({**stale_hardware, 'error': 'Unrelated error'}, 1))
        self.assertFalse(suite.presentation_negative_passes(stale_hardware, 0))
        crashed = {'shell_exit_before_cleanup': -6, 'shell_libraries': ['/original.so'], 'cases': []}
        self.assertFalse(suite.cogl_negative_passes(crashed, 1, '/original.so', ''))
        after_fullscreen = {**crashed, 'cases': [{'samples': [{'requested_fullscreen': True}]}]}
        self.assertTrue(suite.cogl_negative_passes(after_fullscreen, 1, '/original.so', 'FULLSCREEN_INVALID_SHM_READ'))
        self.assertFalse(suite.cogl_negative_passes(after_fullscreen, 1, '/original.so', 'unrelated crash'))


if __name__ == '__main__':
    unittest.main()
