#!/usr/bin/env python3
"""Host checks for Adreno upkeep at desktop start (src/native/adreno.py): OpenCL only on KGSL,
and the private Turnip copy re-staged after a Mesa upgrade."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src/native'))
import adreno  # noqa: E402


class Upkeep(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.gpu = self.home / 'opt/gpu'
        patches = [mock.patch.object(adreno, 'GPU', self.gpu),
                   mock.patch.object(adreno, 'OPENCL_DONE', self.home / 'state/opencl-installed')]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def stage(self, version):
        directory = self.gpu.with_name('gpu-' + version)
        directory.mkdir(parents=True)
        (directory / 'sources.lock.json').write_text(json.dumps({'mesa_version': version}))
        self.gpu.unlink(missing_ok=True)
        self.gpu.symlink_to(directory.name)

    def test_mali_and_no_gpu_are_left_alone(self):
        for kgsl, mali in ((False, False), (False, True), (True, True)):
            with mock.patch.object(adreno, 'KGSL', Path('/') if kgsl else self.home / 'none'), \
                 mock.patch('os.access', return_value=mali), \
                 mock.patch.object(adreno, 'refresh_turnip') as turnip, \
                 mock.patch.object(adreno, 'install_opencl') as opencl:
                adreno.refresh()
            turnip.assert_not_called()
            opencl.assert_not_called()

    def test_adreno_runs_both_and_survives_failures(self):
        with mock.patch.object(adreno, 'KGSL', Path('/')), mock.patch('os.access', return_value=False), \
             mock.patch.object(adreno, 'refresh_turnip', side_effect=RuntimeError('offline')) as turnip, \
             mock.patch.object(adreno, 'install_opencl') as opencl:
            adreno.refresh()
        turnip.assert_called_once()
        opencl.assert_called_once()

    def test_turnip_restaged_only_when_mesa_is_newer(self):
        self.stage('26.2.6-106')
        for installed, expected in (('26.2.6-107', True), ('26.2.6-106', False), ('26.2.6-105', False)):
            with mock.patch.object(adreno, 'installed_version', return_value=installed), \
                 mock.patch.object(adreno, 'stage_turnip', return_value=(None, None)) as stage:
                adreno.refresh_turnip()
            self.assertEqual(stage.called, expected, installed)
            if expected:
                stage.assert_called_once_with(installed)

    def test_turnip_never_staged_without_install_sh_copy(self):
        with mock.patch.object(adreno, 'installed_version', return_value='26.2.6-107'), \
             mock.patch.object(adreno, 'stage_turnip') as stage:
            adreno.refresh_turnip()
        stage.assert_not_called()

    def test_stage_switches_selector_and_keeps_old_copy(self):
        self.stage('26.2.6-106')

        def download(command, cwd=None, **_):
            if 'vulkan-tools' in command:
                return mock.Mock(returncode=0)
            self.assertIn('mesa-vulkan-icd-freedreno=26.2.6-107', command)
            (Path(cwd) / 'turnip.deb').write_bytes(b'deb')
            return mock.Mock(returncode=0)

        def extract(command, check=None):
            prefix = Path(command[-1]) / str(adreno.PREFIX).lstrip('/')
            icd = prefix / 'share/vulkan/icd.d/freedreno_icd.aarch64.json'
            icd.parent.mkdir(parents=True)
            icd.write_text(json.dumps({'ICD': {'library_path': 'x'}}))

        with mock.patch('subprocess.run', side_effect=lambda c, **k: extract(c) if c[0] == 'dpkg-deb' else download(c, **k)), \
             mock.patch('subprocess.check_output', return_value='Package: mesa-vulkan-icd-freedreno\nVersion: 26.2.6-107\n'):
            adreno.stage_turnip('26.2.6-107')
        self.assertEqual(os.readlink(self.gpu), 'gpu-26.2.6-107')
        self.assertEqual(adreno.staged_mesa(), '26.2.6-107')
        self.assertTrue(self.gpu.with_name('gpu-26.2.6-106').is_dir())
        icd = json.loads((self.gpu / 'share/vulkan/icd.d/freedreno_icd.aarch64.json').read_text())
        self.assertEqual(icd['ICD']['library_path'], str(self.gpu.with_name('gpu-26.2.6-107') / 'lib/libvulkan_freedreno.so'))

    def test_stage_survives_missing_vulkan_tools(self):
        """An installed vulkan-tools that no source offers any more must not block Turnip."""
        self.stage('26.2.6-107')
        old_bin = self.gpu.with_name('gpu-26.2.6-107') / 'bin'
        old_bin.mkdir()
        (old_bin / 'vulkaninfo').write_text('old tool')
        commands = []

        def run(command, cwd=None, check=None, **_):
            commands.append(command)
            if command[0] == 'dpkg-deb':
                prefix = Path(command[-1]) / str(adreno.PREFIX).lstrip('/')
                icd = prefix / 'share/vulkan/icd.d/freedreno_icd.aarch64.json'
                icd.parent.mkdir(parents=True)
                icd.write_text(json.dumps({'ICD': {'library_path': 'x'}}))
                return mock.Mock(returncode=0)
            if 'vulkan-tools' in command:
                return mock.Mock(returncode=100)
            (Path(cwd) / 'turnip.deb').write_bytes(b'deb')
            return mock.Mock(returncode=0)

        with mock.patch('subprocess.run', side_effect=run), \
             mock.patch('subprocess.check_output', return_value='Package: mesa-vulkan-icd-freedreno\nVersion: 26.2.6-108\n'):
            adreno.stage_turnip('26.2.6-108')
        downloads = [c for c in commands if c[:2] == ['apt-get', 'download']]
        self.assertEqual(downloads, [['apt-get', 'download', 'mesa-vulkan-icd-freedreno=26.2.6-108'],
                                     ['apt-get', 'download', 'vulkan-tools']])
        self.assertEqual(os.readlink(self.gpu), 'gpu-26.2.6-108')
        self.assertEqual((self.gpu / 'bin/vulkaninfo').read_text(), 'old tool')
        lock = json.loads((self.gpu / 'sources.lock.json').read_text())
        self.assertEqual(lock['carried_over'], ['vulkan-tools'])

    def test_opencl_installed_once_with_the_lock_marked(self):
        with mock.patch.object(adreno, 'installed_version', return_value=None), \
             mock.patch('subprocess.run', return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(adreno.install_opencl())
            self.assertFalse(adreno.install_opencl())  # removed by hand later: not again
        run.assert_called_once()
        command, options = run.call_args
        self.assertEqual(command[0][-3:], adreno.OPENCL)
        self.assertEqual(options['env']['LIVECD_SETUP_LOCKED'], '1')

    def test_opencl_failure_retries_next_start(self):
        with mock.patch.object(adreno, 'installed_version', return_value=None), \
             mock.patch('subprocess.run', return_value=mock.Mock(returncode=100)):
            with self.assertRaises(RuntimeError):
                adreno.install_opencl()
        self.assertFalse(adreno.OPENCL_DONE.exists())


class Packaging(unittest.TestCase):
    def test_opencl_is_adreno_only(self):
        recipe = (REPO / 'packages/livecd-desktop/build.sh').read_text()
        self.assertNotRegex(recipe, r'(?m)^TERMUX_PKG_(RECOMMENDS|DEPENDS)=.*\bclvk\b')
        self.assertTrue((REPO / 'packages/livecd-desktop/native/adreno.py').resolve() == REPO / 'src/native/adreno.py')
        install = (REPO / 'install.sh').read_text()
        self.assertRegex(install, r'test -e /dev/kgsl-3d0; then\n\s+packages\+=\(ocl-icd clvk clinfo\)')
        offline = (REPO / 'tools/offline-repo.py').read_text()
        self.assertEqual(re.search(r"ADRENO = \[(.*)\]", offline).group(1).replace("'", '').split(', '), adreno.OPENCL)


if __name__ == '__main__':
    unittest.main()
