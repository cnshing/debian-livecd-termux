#!/usr/bin/env python3
"""Exercise ICU ABI drift with real ELF and Debian package fixtures."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('audit', Path(__file__).with_name('check-nautilus-artifact.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class NautilusICU(unittest.TestCase):
    def package(self, root, name, depends=''):
        control = root / 'DEBIAN/control'
        control.parent.mkdir()
        control.write_text(f'Package: {name}\nVersion: 1\nArchitecture: aarch64\n'
                           'Maintainer: Test <test@example.invalid>\nDescription: ABI fixture\n'
                           + (f'Depends: {depends}\n' if depends else ''))
        output = root.with_suffix('.deb')
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(root), str(output)],
                       check=True, stdout=subprocess.DEVNULL)
        return output

    def test_real_elf_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            libdir = root / 'icu' / audit.PREFIX / 'lib'
            libdir.mkdir(parents=True)
            library = libdir / 'libicuuc.so.79'
            subprocess.run(['cc', '-shared', '-x', 'c', '-', '-Wl,-soname,libicuuc.so.79', '-o', str(library)],
                           input='int fixture(void) { return 0; }', text=True, check=True)
            libicu = self.package(root / 'icu', 'libicu')
            binary = root / 'app' / audit.PREFIX / 'bin/nautilus'
            binary.parent.mkdir(parents=True)
            subprocess.run(['cc', '-x', 'c', '-', '-x', 'none', str(library), '-o', str(binary)],
                           input='int fixture(void); int main(void) { return fixture(); }', text=True, check=True)
            for depends, error in [('libicu (>= 79), libicu (<< 80)', None),
                                   ('libicu', 'must declare'),
                                   ('libicu (>= 78), libicu (<< 79)', 'must declare')]:
                with self.subTest(depends=depends), tempfile.TemporaryDirectory() as extracted:
                    control = root / 'app/DEBIAN'
                    if control.exists():
                        (control / 'control').unlink()
                        control.rmdir()
                    nautilus = self.package(root / 'app', 'nautilus', depends)
                    if error:
                        with self.assertRaisesRegex(RuntimeError, error):
                            audit.check(nautilus, libicu, Path(extracted))
                    else:
                        with contextlib.redirect_stdout(io.StringIO()):
                            audit.check(nautilus, libicu, Path(extracted))
            # The same artifact must fail when the mirror drops its required ABI.
            library.rename(libdir / 'libicuuc.so.80')
            (root / 'icu/DEBIAN/control').unlink()
            (root / 'icu/DEBIAN').rmdir()
            libicu = self.package(root / 'icu', 'libicu')
            with tempfile.TemporaryDirectory() as extracted, self.assertRaisesRegex(RuntimeError, 'absent from the mirror'):
                audit.check(nautilus, libicu, Path(extracted))

    def test_recipe_records_the_installed_icu_major(self):
        for version in ('78.3', '79.1', '80.1'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                script = '''
source "$1/packages/nautilus/build.sh"
termux_setup_gir() { :; }
termux_setup_glib_cross_pkg_config_wrapper() { :; }
termux_error_exit() { echo "$*" >&2; exit 1; }
mock_pkg_config() { echo "$ICU_FIXTURE_VERSION"; }
PKG_CONFIG=mock_pkg_config
TERMUX_PREFIX=$2
termux_step_pre_configure
printf '%s' "$TERMUX_PKG_DEPENDS"
'''
                depends = subprocess.check_output(['bash', '-e', '-c', 'ICU_FIXTURE_VERSION=$3\n' + script,
                                                   'test', str(REPO), temporary, version], text=True)
                major = int(version.split('.')[0])
                self.assertIn(f'libicu (>= {major}), libicu (<< {major + 1})', depends)


if __name__ == '__main__':
    unittest.main()
