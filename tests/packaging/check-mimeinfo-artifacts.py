#!/usr/bin/env python3
"""Check that xdg-utils configures without CPAN and its packaged MIME helpers work.

Runs on the build host using only host Perl's core modules and the package's
private modules. No host CPAN/vendor modules, network, desktop or phone needed.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

PREFIX = Path('data/data/com.termux/files/usr')
PERL = '''BEGIN {
    @INC = (shift @ARGV, @Config::Config{qw(privlibexp archlibexp)});
}
my $script = shift @ARGV;
$0 = $script;
do $script;
die $@ if $@;
die "$script: $!" unless defined $INC{'File/MimeInfo.pm'};
'''


def field(package, name):
    return subprocess.check_output(['dpkg-deb', '-f', str(package), name], text=True).strip()


def check(directory):
    packages = {}
    for name in ('xdg-utils', 'libfile-mimeinfo-perl'):
        matches = [p for p in directory.glob(name + '_*.deb') if field(p, 'Package') == name]
        if len(matches) != 1:
            raise RuntimeError('Expected exactly one artifact for ' + name)
        packages[name] = matches[0]
    if 'libfile-mimeinfo-perl' not in field(packages['xdg-utils'], 'Depends'):
        raise RuntimeError('xdg-utils must depend on the packaged MIME helpers')
    with tempfile.TemporaryDirectory(prefix='mimeinfo-check-') as temporary:
        root = Path(temporary)
        for name, package in packages.items():
            controls = root / ('control-' + name)
            subprocess.run(['dpkg-deb', '-e', str(package), str(controls)], check=True)
            for script in ('preinst', 'postinst', 'prerm', 'postrm', 'config'):
                if (controls / script).exists():
                    # Neither of these packages needs maintainer scripts at all.
                    raise RuntimeError(name + ' unexpectedly includes ' + script)
            subprocess.run(['dpkg-deb', '-x', str(package), str(root)], check=True)
        prefix = root / PREFIX
        modules = prefix / 'libexec/file-mimeinfo/perl5'
        home = root / 'home'
        data, config = home / 'data', home / 'config'
        applications = data / 'applications'
        mime = data / 'mime'
        for folder in (applications, mime, config):
            folder.mkdir(parents=True, exist_ok=True)
        # Minimal shared-mime-info fixture: no host database is needed.
        (mime / 'globs').write_text('text/plain:*.txt\n')
        (mime / 'globs2').write_text('50:text/plain:*.txt\n')
        (mime / 'aliases').touch()
        (mime / 'subclasses').touch()
        (applications / 'mimeinfo.cache').write_text('[MIME Cache]\ntext/plain=fixture.desktop;\n')
        (config / 'mimeapps.list').write_text('[Default Applications]\ntext/plain=fixture.desktop;\n')
        opener = root / 'opener'
        opener.write_text('#!/bin/sh\nprintf "opened:%s\\n" "$1"\n')
        opener.chmod(0o755)
        (applications / 'fixture.desktop').write_text('[Desktop Entry]\nType=Application\n'
            f'Name=Offline fixture\nExec={opener} %f\nMimeType=text/plain;\n')
        fixture = root / 'hello.txt'
        fixture.write_text('Offline MIME fixture\n')
        env = {k: v for k, v in os.environ.items() if k not in
               ('PERL5LIB', 'PERLLIB', 'PERL5OPT', 'XDG_DATA_DIRS', 'XDG_CONFIG_DIRS')}
        env.update(HOME=str(home), XDG_DATA_HOME=str(data), XDG_CONFIG_HOME=str(config),
                   LC_ALL='C', PATH='/usr/bin:/bin')

        def perl(code, *args):
            return subprocess.check_output(['perl', '-MConfig', '-e', code, str(modules),
                                            *map(str, args)], env=env, text=True).strip()

        # Use only core Perl and packaged modules; verify all dependencies load.
        imports = PERL.split('my $script', 1)[0] + '''
use File::MimeInfo::Magic;
use File::MimeInfo::Applications;
use Encode::Locale;
use IPC::System::Simple;
use URI;
use MIME::Base32;
print join "\\n", File::BaseDir::xdg_data_dirs(), File::BaseDir::xdg_config_dirs();
'''
        expected = '/data/data/com.termux/files/usr/share\n/data/data/com.termux/files/usr/etc/xdg'
        if perl(imports) != expected:
            raise RuntimeError('MIME helpers must default to Termux data and configuration directories')
        for command, arguments, expected in (
                ('mimetype', ['--brief', fixture], 'text/plain'),
                ('mimeopen', ['--no-ask', fixture],
                 f'Opening "{fixture}" with Offline fixture  (text/plain)\nopened:{fixture}')):
            script = prefix / 'bin' / command
            content = script.read_text()
            old = "use lib '/data/data/com.termux/files/usr/libexec/file-mimeinfo/perl5';"
            if old not in content or not content.startswith('#!/data/data/com.termux/files/usr/bin/perl\n'):
                raise RuntimeError(command + ' must load its private packaged modules')
            # Rebase the private library path for this temporary host extraction.
            script.write_text(content.replace(old, "use lib '" + str(modules) + "';"))
            actual = perl(PERL, script, *arguments)
            if actual != expected:
                raise RuntimeError(command + ' failed its offline fixture: ' + repr(actual))
        print('PASS: packaged MIME modules, file detection and desktop opening; no CPAN setup')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    check(parser.parse_args().directory)
