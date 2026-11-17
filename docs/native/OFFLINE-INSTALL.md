# Offline package installation

Updated 2026-11-16. The offline tarball supplies the supported Termux bootstrap,
this project's packages, their dependencies, and the default/optional overlay
package sets. Browser downloads remain an intentional exception: Chrome and
ungoogled Chromium may download when internet access is available and are left
out when the browser hook's connectivity check fails.

## CPAN-free MIME setup

Termux's upstream `xdg-utils` 1.2.1-1 runs `cpan -Ti File::MimeInfo` in its
post-install script. The fresh X1S and Note10 installation logs both show
successful requests for CPAN indexes, archives and checksums. APT's
`--download-only` resolution cannot discover dependencies installed by CPAN.

This project overrides `xdg-utils` as 1.2.1-2, preserving the pinned upstream
patches and the `xdg-utils-xdg-open` command name. Its declared dependency on
`libfile-mimeinfo-perl` replaces the CPAN post-install script. Both names enter
the existing repository pin list, and the offline resolver follows their APT
dependencies.

`libfile-mimeinfo-perl` packages these source distributions, locked by SHA-256
in its recipe:

| Distribution | Version |
| --- | --- |
| File-MimeInfo | 0.37 |
| Encode-Locale | 1.05 |
| File-BaseDir | 0.09 |
| File-DesktopEntry | 0.23 |
| IPC-System-Simple | 1.30 |
| URI | 5.40 |
| MIME-Base32 | 1.303 |

These are the complete non-core runtime requirements declared by the inspected
source metadata. Their source archives contain no XS files. Build/test-only
File-Which, Test-Needs and Test-Warnings, also fetched by the old CPAN setup,
are not required on the phone.

The modules live privately in `$PREFIX/libexec/file-mimeinfo/perl5`.
`mimetype` and `mimeopen` explicitly load that directory, so Perl version
upgrades do not lose the modules and unrelated Perl programs keep their usual
module search paths. File::BaseDir's fallback data/configuration directories
point to Termux; explicit XDG environment settings still take precedence.
Source notices are retained in the package documentation.

Older offline tarballs still contain the CPAN-dependent package. The installer
checks the selected xdg-utils candidate after loading the local APT index and
rejects those tarballs before any upgrade/configuration transaction. Rebuild
and transfer a new offline tarball to obtain the fix. Suppressing CPAN errors
or deleting the old post-install script alone would leave MIME helpers missing.

## Optional applications without mirror probes

The initial offline installation already calls `apt-get` with isolated local
sources, lists and cache. Subsequent `pkg` invocations can separately probe
Termux mirrors, even when APT_CONFIG selects the local repository. The Note10
optional-package log shows a USTC availability check and dependency downloads.

Use APT directly for optional applications from the offline repository:

```sh
APT_CONFIG="$HOME/.local/state/livecd-native/apt-offline/apt.conf" apt-get install mixtapes serein
```

The installer's final hint uses this form. Existing online Termux source files
remain available for ordinary online `pkg` use. The repository directory and
extracted package pool must stay in place while the offline configuration is
used.

## Validation and scope

`tests/packaging/check-mimeinfo-artifacts.py` runs during repository assembly.
It rejects an xdg-utils without the packaged MIME dependency and either package
if it includes maintainer scripts. It extracts the actual artifacts and uses
host Perl with only core and packaged modules to test dependency imports,
Termux fallback paths, MIME detection and desktop-entry execution against local
fixtures. A regression check also exercises rejection of old offline tarballs.

Local validation used the real MIME recipe installation hook with the verified
source archives and a locally staged xdg-utils fixture based on the known
upstream payload. Full Termux builds and fresh-phone acceptance are separate
checks; host fixtures are not release artifacts.

The investigation also screened control scripts from 534 cached Termux debs.
xdg-utils was the only direct downloader found; other URL matches were comments
or diagnostics. This static screen cannot rule out indirect calls or changes
in future packages. For release acceptance, start with a supported fresh Termux
bootstrap and empty CPAN cache, transfer the checkout and complete tarball
locally, block external networking, and exercise initial and optional package
installation. Check `dpkg --audit`, MIME detection, desktop opening, and both GPU
setup branches. Use network syscall tracing to distinguish failed network
attempts from no attempts; browser attempts are an accepted exception.

Termux:X11 and any optional Android integration APKs must be available before
setup. Arbitrary extra packages already installed on a phone are outside the
resolver's modeled bootstrap/default/optional package sets.

Investigation evidence stays in the Git-ignored
`temp/fresh-x1s-20261116/` and `temp/fresh-note10-20261116/` logs, and the
pre-existing `~/.cache/livecd-offline-test/cache/` package cache. This work did
not reset or modify a phone.
