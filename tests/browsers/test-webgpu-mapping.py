#!/usr/bin/env python3
"""Host mmap integration checks; device GPU acceptance uses test-web-graphics.py."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/native'))
import acceleration
DRIVER = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc > 3) assert(setenv("LIVECD_WEBGPU_MAP", "1", 1) == 0);
    const size_t page = (size_t)sysconf(_SC_PAGESIZE), reservation = (((argc > 5 ? 8UL : 128UL) + 4) << 30) - page;
    void *base = mmap((void *)(128UL << 30), reservation, PROT_NONE,
                     MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    assert(base == (void *)(128UL << 30));
    uintptr_t end = (uintptr_t)base + reservation;
    uintptr_t hint = 640UL << 30;
    int fragmented = argc > 4;
    if (fragmented) {
        const size_t tail = (1UL << 39) - end;
        void *occupied = mmap((void *)end, tail, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        assert(occupied == (void *)end);
        assert(munmap((void *)(end + (64UL << 20)), 16UL << 20) == 0);
    }
    int matching = argv[1][0] == 'm', shared = argv[2][0] == 's';
    int fd = memfd_create(matching ? "shared-memory-region" : "unrelated", MFD_CLOEXEC);
    assert(fd >= 0 && ftruncate(fd, page) == 0);
    void *mapped = mmap((void *)hint, page, PROT_READ | PROT_WRITE,
                        shared ? MAP_SHARED : MAP_PRIVATE, fd, 0);
    assert(mapped != MAP_FAILED);
    // A build without WEBGPU_MAP_TEST probes the real kernel: on a host with
    // more than 39 address bits it must stay inert and keep every hint.
    int native = getenv("EXPECT_NATIVE") != NULL;
    if (!native && matching && shared && getenv("LIVECD_WEBGPU_MAP")[0] == '1') {
        assert((uintptr_t)mapped >= end && (uintptr_t)mapped + page < (1UL << 39));
        if (fragmented) assert((uintptr_t)mapped >= end + (64UL << 20) &&
                               (uintptr_t)mapped + page <= end + (80UL << 20));
    } else {
        assert((uintptr_t)mapped == hint);
    }
    *(volatile int *)mapped = 42;
    // A fixed mapping replaces only the page this test already owns.
    void *fixed = mmap(mapped, page, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_FIXED, fd, 0);
    assert(fixed == mapped);
    assert(munmap(mapped, page) == 0 && munmap(base, reservation) == 0);
    if (fragmented) assert(munmap((void *)end, (1UL << 39) - end) == 0);
    close(fd);
    return 0;
}
'''


class Mapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.scratch.cleanup)
        root = Path(cls.scratch.name)
        cls.library, cls.driver = root / 'mapping.so', root / 'driver'
        cls.native = root / 'native.so'
        (root / 'driver.c').write_text(DRIVER)
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-DWEBGPU_MAP_TEST', '-nostdlib',
                        str(ROOT / 'packages/android-webgpu/webgpu-map.c'),
                        '-o', str(cls.library)], check=True)
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-nostdlib',
                        str(ROOT / 'packages/android-webgpu/webgpu-map.c'),
                        '-o', str(cls.native)], check=True)
        subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', str(root / 'driver.c'),
                        '-o', str(cls.driver)], check=True)

    def check_mapping(self, name, mode, enabled='1'):
        subprocess.run([str(self.driver), name, mode], check=True,
                       env={**os.environ, 'LD_PRELOAD': str(self.library), 'LIVECD_WEBGPU_MAP': enabled})

    def test_shared_transfer_mapping_is_accessible(self):
        self.check_mapping('matching', 'shared')

    def test_unrelated_and_private_mappings_keep_their_hints(self):
        self.check_mapping('unrelated', 'shared')
        self.check_mapping('matching', 'private')

    def test_opt_out_preserves_original_mapping(self):
        self.check_mapping('matching', 'shared', '0')

    def test_environment_available_only_after_constructors(self):
        subprocess.run([str(self.driver), 'matching', 'shared', 'late'], check=True,
                       env={**os.environ, 'LD_PRELOAD': str(self.library), 'LIVECD_WEBGPU_MAP': '0'})

    def test_fragmented_tail_uses_a_real_free_gap(self):
        subprocess.run([str(self.driver), 'matching', 'shared', 'late', 'fragmented'], check=True,
                       env={**os.environ, 'LD_PRELOAD': str(self.library), 'LIVECD_WEBGPU_MAP': '1'})

    def test_small_partial_reservation_with_fragmented_tail(self):
        subprocess.run([str(self.driver), 'matching', 'shared', 'late', 'fragmented', 'small'], check=True,
                       env={**os.environ, 'LD_PRELOAD': str(self.library), 'LIVECD_WEBGPU_MAP': '1'})

    def test_wide_address_kernel_keeps_native_mapping(self):
        with open('/proc/self/maps') as maps:
            highest = max(int(line.split('-')[1].split()[0], 16) for line in maps)
        if highest < 1 << 39:
            self.skipTest('host address space is not wider than 39 bits')
        subprocess.run([str(self.driver), 'matching', 'shared', 'late', 'fragmented'], check=True,
                       env={**os.environ, 'LD_PRELOAD': str(self.native), 'LIVECD_WEBGPU_MAP': '1',
                            'EXPECT_NATIVE': '1'})

    def test_library_has_no_libc_dependency(self):
        result = subprocess.run(['readelf', '-d', str(self.library)], check=True, capture_output=True, text=True)
        self.assertNotIn('(NEEDED)', result.stdout)


class Launcher(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.paths = mock.patch('pathlib.Path.is_file', return_value=True)
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def prepare(self, abi='bionic', profile='chromium', gpu=True):
        env = {'LD_PRELOAD': '/bionic/keep.so', 'BIONILUX_EXTRA_PRELOAD': '/glibc/keep.so'}
        acceleration.webgpu_environment(env, profile, abi, gpu)
        return env

    def test_browser_abi_routing_preserves_other_preloads(self):
        env = self.prepare()
        self.assertTrue(env['LD_PRELOAD'].endswith('libwebgpu-map.so:/bionic/keep.so'))
        self.assertEqual(env['BIONILUX_EXTRA_PRELOAD'], '/glibc/keep.so')
        env = self.prepare(abi='glibc', profile='chrome')
        self.assertTrue(env['BIONILUX_EXTRA_PRELOAD'].endswith('libwebgpu-map.so:/glibc/keep.so'))
        self.assertEqual(env['LD_PRELOAD'], '/bionic/keep.so')
        self.assertEqual(env['LIVECD_WEBGPU_MAP'], '1')

    def test_every_gpu_vendor_browser_gets_the_preload(self):
        # Adreno and Mali share the 39-bit kernel limit; the library probes it.
        for profile in ('chromium', 'chrome', 'ungoogled-chromium'):
            with self.subTest(profile=profile):
                self.assertEqual(self.prepare(abi='glibc', profile=profile)['LIVECD_WEBGPU_MAP'], '1')

    def test_software_and_other_apps_unchanged(self):
        for options in ({'gpu': False}, {'profile': 'firefox'}, {'profile': 'mpv'}):
            with self.subTest(options=options):
                self.assertNotIn('LIVECD_WEBGPU_MAP', self.prepare(**options))

    def test_missing_library_and_opt_out_unchanged(self):
        with mock.patch('pathlib.Path.is_file', return_value=False):
            self.assertNotIn('LIVECD_WEBGPU_MAP', self.prepare())
        for value in ('0', 'false', 'off', 'no', ' OFF '):
            with self.subTest(value=value):
                os.environ['LIVECD_WEBGPU_MAP'] = value
                self.assertNotIn('LIVECD_WEBGPU_MAP', self.prepare())


if __name__ == '__main__':
    unittest.main()
