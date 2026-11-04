#!/usr/bin/env python3
"""Host checks for package ownership, build ordering and profile migration."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


recipes = module('recipes', 'tools/recipes.py')
runtime = module('runtime', 'src/native/runtime.py')
sys.path.insert(0, str(REPO / 'src/native'))
desktop = module('packaged_desktop', 'src/native/desktop.py')


class Packaging(unittest.TestCase):
    def test_runtime_dependencies_are_built_before_consumers(self):
        order = recipes.build_order(['livecd-desktop'])
        for dependency, consumer in [('livecd-mozjs-128', 'livecd-gjs'),
                                     ('livecd-gjs', 'livecd-gnome-shell'),
                                     ('livecd-mutter', 'livecd-gnome-shell'),
                                     ('livecd-upower', 'livecd-gnome-shell'),
                                     ('livecd-gnome-shell', 'livecd-gnome-runtime'),
                                     ('livecd-resources', 'livecd-desktop'),
                                     ('livecd-gnome-runtime', 'livecd-desktop')]:
            self.assertLess(order.index(dependency), order.index(consumer))
        self.assertEqual(len(order), len(set(order)))
        self.assertNotIn('livecd-gi-paths', order)
        self.assertNotIn('mutter-x11-frames', order)

    def test_chromium_builds_alone_with_its_dependencies_and_longest_timeout(self):
        jobs = {job['name']: job for job in recipes.plan(recipes.all_names())['include']}
        self.assertEqual(jobs['chromium']['packages'], 'libva chromium')
        self.assertEqual(jobs['chromium']['timeout'], 360)
        self.assertTrue(jobs['chromium']['exact'])
        self.assertEqual(jobs['libva_livecd-gst-va']['packages'], 'libva livecd-gst-va')
        self.assertEqual(jobs['libva_livecd-gst-va']['timeout'], 350)
        self.assertFalse(jobs['libva_livecd-gst-va']['exact'])
        self.assertEqual(jobs['easyeffects_livecd-audio_lsp-plugins-lv2']['host_packages'],
                         'libcairo2-dev libsndfile1-dev')
        self.assertEqual(jobs['chromium']['host_packages'], '')
        built = [package for job in jobs.values() for package in job['packages'].split()]
        self.assertEqual(sorted(set(built)), recipes.all_names())
        alone = recipes.plan(['chromium'])['include']
        self.assertEqual([job['name'] for job in alone], ['chromium'])

    def test_session_preload_uses_package_files_and_preserves_termux_exec(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            library = prefix / 'lib/liblivecd-proc.so'
            library.parent.mkdir()
            library.touch()
            commands = prefix / 'libexec/livecd-resources/bin'
            termux_exec = str(prefix / 'lib/libtermux-exec-ld-preload.so')
            isolated = '/old/session-preload/liblivecd-proc.so'
            for accepted, disabled in [(True, False), (False, False), (True, True)]:
                with self.subTest(accepted=accepted, disabled=disabled), \
                        mock.patch.multiple(desktop, PREFIX=prefix, RESOURCE_PRELOAD=library,
                                            RESOURCE_COMMANDS=commands), \
                        mock.patch.dict(os.environ, {'LD_PRELOAD': isolated + ':' + termux_exec,
                                                     'LIVECD_RESOURCES_COMPAT': '0' if disabled else '1'}, clear=True), \
                        mock.patch.object(desktop, 'probe_preload', return_value=accepted) as probe, \
                        mock.patch.object(desktop, 'apply_renderer', side_effect=lambda env, renderer: env), \
                        contextlib.redirect_stderr(io.StringIO()):
                    env = desktop.environment()
                enabled = accepted and not disabled
                expected = [str(library), termux_exec] if enabled else [termux_exec]
                self.assertEqual(env['LD_PRELOAD'].split(':'), expected)
                self.assertEqual(str(commands) in env['PATH'].split(':'), enabled)
                if disabled:
                    probe.assert_not_called()
                else:
                    probe.assert_called_once_with(str(library) + ':' + termux_exec)

    def test_build_inputs_name_the_reused_packages(self):
        def artifact():
            return recipes.plan(['lsp-plugins-lv2'])['include'][0]['artifact']
        first = artifact()
        self.assertTrue(first.startswith('debs-lsp-plugins-lv2-'))
        self.assertEqual(first, artifact())
        with mock.patch.object(recipes, 'BUILD_EPOCH', recipes.BUILD_EPOCH + 1):
            self.assertNotEqual(first, artifact())
        with mock.patch.object(recipes, 'HOST_PACKAGES', {}):
            self.assertNotEqual(first, artifact())
        # The plan job's tests import recipes' Python first, which writes bytecode into them.
        bytecode = recipes.PACKAGES / 'lsp-plugins-lv2/__pycache__/probe.pyc'
        bytecode.parent.mkdir(exist_ok=True)
        try:
            bytecode.write_bytes(os.urandom(16))
            self.assertEqual(first, artifact())
        finally:
            bytecode.unlink()
            bytecode.parent.rmdir()

    def test_reused_packages_come_only_from_this_run_or_the_default_branch(self):
        def candidate(id, branch, run, fork=False, expired=False):
            return {'id': id, 'name': 'debs-x', 'expired': expired,
                    'workflow_run': {'id': run, 'head_branch': branch, 'repository_id': 1,
                                     'head_repository_id': 2 if fork else 1}}
        def found(artifacts, run_id='99'):
            response = mock.MagicMock()
            response.__enter__.return_value = io.StringIO(json.dumps({'artifacts': artifacts}))
            env = {'GITHUB_REPOSITORY': 'o/r', 'GH_TOKEN': 't', 'DEFAULT_BRANCH': 'main', 'GITHUB_RUN_ID': run_id}
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(recipes.urllib.request, 'urlopen', return_value=response):
                artifact = recipes.built_artifact('debs-x')
            return artifact and artifact['id']
        self.assertEqual(found([candidate(1, 'feature', 5), candidate(2, 'main', 6, fork=True),
                                candidate(3, 'main', 7, expired=True), candidate(4, 'main', 8)]), 4)
        self.assertEqual(found([candidate(1, 'feature', 99), candidate(4, 'main', 8)]), 1)
        self.assertIsNone(found([candidate(1, 'feature', 5), candidate(2, 'main', 6, fork=True)]))

    def test_source_changes_invalidate_the_package_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packages = root / 'packages'
            (packages / 'example').mkdir(parents=True)
            source = root / 'source.py'
            source.write_text('first\n')
            (packages / 'example/source.py').symlink_to(source)
            with mock.patch.object(recipes, 'PACKAGES', packages):
                before = recipes.directory_hash(['example'])
                source.write_text('second\n')
                self.assertNotEqual(before, recipes.directory_hash(['example']))

    def test_staging_keeps_upstream_patches_and_materializes_local_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / 'termux-packages'
            upstream = checkout / 'x11-packages/example'
            upstream.mkdir(parents=True)
            original = 'TERMUX_PKG_VERSION=1\n'
            (upstream / 'build.sh').write_text(original)
            (upstream / 'original.patch').write_text('retained upstream patch\n')
            subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
            subprocess.run(['git', '-C', str(checkout), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Packaging Test',
                            '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
            packages = root / 'packages'
            package = packages / 'example'
            package.mkdir(parents=True)
            (package / 'build.sh').write_text(original + 'TERMUX_PKG_REVISION=1\n')
            (package / 'upstream.json').write_text(json.dumps({
                'revision': revision, 'path': 'x11-packages/example/build.sh',
                'sha256': hashlib.sha256(original.encode()).hexdigest()}))
            source = root / 'source.py'
            source.write_text('source input\n')
            (package / 'helper.py').symlink_to(source)
            config = root / 'config.json'
            config.write_text(json.dumps({'revision': revision}))
            with mock.patch.object(recipes, 'PACKAGES', packages), \
                    mock.patch.object(recipes, 'BUILD_CONFIG', config), contextlib.redirect_stdout(io.StringIO()):
                recipes.prepare_builder(checkout)
                recipes.prepare_builder(checkout)
                self.assertEqual((upstream / 'original.patch').read_text(), 'retained upstream patch\n')
                self.assertFalse((upstream / 'helper.py').is_symlink())
                self.assertEqual((upstream / 'helper.py').read_text(), source.read_text())
                metadata = json.loads((package / 'upstream.json').read_text())
                metadata['remove_files'] = {'original.patch': hashlib.sha256(
                    b'retained upstream patch\n').hexdigest()}
                (package / 'upstream.json').write_text(json.dumps(metadata))
                recipes.prepare_builder(checkout)
                recipes.prepare_builder(checkout)
                self.assertFalse((upstream / 'original.patch').exists())
                metadata['remove_files']['original.patch'] = '0' * 64
                (package / 'upstream.json').write_text(json.dumps(metadata))
                with self.assertRaisesRegex(RuntimeError, 'removal changed'):
                    recipes.prepare_builder(checkout)
                config.write_text(json.dumps({'revision': '0' * 40}))
                with self.assertRaisesRegex(RuntimeError, 'checkout must be'):
                    recipes.prepare_builder(checkout)

    def test_code_oss_menu_entries_have_valid_identity_and_url_scheme(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = root / 'product.json'
            product.write_text(json.dumps({'urlProtocol': 'code-oss'}))
            entry = '[Desktop Entry]\nType=Application\nName=Code - OSS\nExec=code-oss %U\nStartupWMClass=@@DESKTOP_NAME@@\n'
            (root / 'code-oss.desktop').write_text(entry)
            (root / 'code-oss-url-handler.desktop').write_text(entry + 'MimeType=x-scheme-handler/@@URLPROTOCOL@@;\n')
            subprocess.run([sys.executable, str(REPO / 'packages/code-oss/desktop.py'),
                            str(root), str(product)], check=True)
            self.assertIn('StartupWMClass=code-oss', (root / 'code-oss.desktop').read_text())
            self.assertIn('MimeType=x-scheme-handler/code-oss;', (root / 'code-oss-url-handler.desktop').read_text())
            self.assertNotIn('@@', (root / 'code-oss-url-handler.desktop').read_text())

    def test_native_install_includes_subpackages_and_excludes_unrelated_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / 'packages/example'
            package.mkdir(parents=True)
            (package / 'example-data.subpackage.sh').touch()
            output = root / 'output'
            output.mkdir()
            for name in ('example', 'example-data', 'unrelated'):
                (output / (name + '.deb')).touch()
            def package_name(command, **kwargs):
                return Path(command[-2]).stem + '\n'
            with mock.patch.object(recipes, 'PACKAGES', root / 'packages'), \
                    mock.patch.object(recipes.subprocess, 'check_output', side_effect=package_name), \
                    mock.patch.object(recipes.subprocess, 'run') as install:
                recipes.install_output(output, ['example'])
            command = install.call_args.args[0]
            self.assertIn(str(output / 'example.deb'), command)
            self.assertIn(str(output / 'example-data.deb'), command)
            self.assertNotIn(str(output / 'unrelated.deb'), command)

    def test_missing_output_cannot_install_a_partial_package_set(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(recipes.subprocess, 'run') as install:
            with self.assertRaisesRegex(RuntimeError, 'Missing output'):
                recipes.install_output(temporary, ['livecd-desktop'])
            install.assert_not_called()

    def test_profile_migration_preserves_the_old_runtime_and_custom_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'
            home.mkdir()
            prefix = Path(temporary) / 'prefix'
            packaged = prefix / 'opt/gnome-48'
            (packaged / 'bin').mkdir(parents=True)
            (packaged / 'bin/gnome-shell').touch()
            for name in ('fonts/TestFont', 'icons/Adwaita', 'gnome-shell/extensions/packaged@local'):
                (prefix / 'share/livecd-native' / name).mkdir(parents=True)
            (prefix / 'libexec/livecd-native').mkdir(parents=True)
            (prefix / 'libexec/livecd-native/desktop.py').write_text('packaged controller\n')
            root = home / '.local/opt/livecd-native/gnome-48'
            root.parent.mkdir(parents=True)
            old = root.with_name('gnome-48-source')
            old.mkdir()
            (old / 'preserved').write_text('old runtime\n')
            root.symlink_to(old.name)
            data = home / '.local/share/livecd-native'
            custom = data / 'gnome-shell/extensions/custom@local'
            custom.mkdir(parents=True)
            (custom / 'settings').write_text('user data\n')
            state = home / '.local/state/livecd-native'
            with mock.patch.multiple(runtime, PREFIX=prefix, ROOT=root, DATA=data, STATE=state), \
                    mock.patch.dict(os.environ, {'HOME': str(home), 'PREFIX': str(prefix)}), \
                    mock.patch.object(runtime.subprocess, 'run'), contextlib.redirect_stdout(io.StringIO()):
                runtime.main()
                runtime.main()
            self.assertEqual(root.resolve(), packaged)
            self.assertEqual((old / 'preserved').read_text(), 'old runtime\n')
            self.assertEqual((custom / 'settings').read_text(), 'user data\n')
            self.assertTrue((data / 'gnome-shell/extensions/packaged@local').is_symlink())
            self.assertTrue((home / '.local/lib/livecd-native/desktop.py').is_symlink())
            backups = list((state / 'runtime-backups').glob('*/.local/opt/livecd-native/gnome-48'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].resolve(), old)


if __name__ == '__main__':
    unittest.main()
