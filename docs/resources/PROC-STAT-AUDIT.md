# Proc-stat handoff integration and audit

Audited on the established Android 11 / arm64 phone over SSH.
This follows `CLAUDE-HANDOFF-PROC-STAT.md`; that handoff remains historical.

## Applied to the package flow

The working fix is `-fno-emulated-tls` when compiling `proc-compat.c`. The
`livecd-resources` recipe already had that flag. Its revision is now `1.0.0-1`,
so APT can upgrade the older `1.0.0` build, and packaging fails unless the
resulting library contains an ELF TLS segment. The check deliberately allows
the harmless `__emutls_unregister_key` symbol mentioned in the handoff.

`livecd-desktop` requires the corrected resource package and uses its
`$PREFIX/lib/liblivecd-proc.so` and packaged `top` launcher. The session builder
compatibility command now invokes the standard Termux package builder and APT.
It no longer compiles a second copy under the user's home directory.

The controller's Node.js compatibility probe, timeout, failure handling and
Python fallback are unchanged, verified by comparing their Python syntax trees.
It retains the Termux exec preload, removes a stale inherited copy of the
resource preload, and supports `LIVECD_RESOURCES_COMPAT=0`. A host integration
test covers accepting the packaged library, rejecting it and explicitly
disabling it, including the corresponding `PATH` selection.

## Observed on the running phone

- The session owner uses the isolated fixed library and its `top` launcher.
  The installed `$PREFIX/lib/liblivecd-proc.so` is still the earlier build.
- The fixed library has a `PT_TLS` segment; the old one does not. The exact
  package check accepts the fixed library and rejects the old one.
- The phone's C source and header match this checkout byte for byte.
  `proc-compat.c` SHA-256:
  `03678da6c3bdcb0cfdb27e86c0eb0b3515c3b82954dae6975430482190fe8549`.
- Node.js launched through `livecd-native exec` reads `/proc/stat` and obtains
  advancing CPU counters after 300 ms, without a special launcher or shim.
- `livecd-native exec -- top -b -n 1` succeeds and reports 766 processes.
- GNOME Shell, the session manager and five running Electron processes have
  the fixed library mapped.

These checks opened no windows and replaced no installed phone files. The
existing session was not restarted. Its working isolated copy remains intact
for rollback; installing the new package flow will select the package-owned
library on the next desktop start.

## Limits

The observed flag fixes the Node.js abort; the exact failure mechanism remains
unproven. ELF TLS requires [Android API 29 or later](https://android.git.googlesource.com/platform/bionic/+/HEAD/android-changes-for-ndk-developers.md#elf-tls-available-for-api-level-29).

The newly revised `.deb` and the complete GNOME package flow have not been
built or installed on this phone. These live checks use the already working
isolated artifact. Ghostty was not running, and no terminal window was opened.
The editor's real-profile `code-oss --status`, its previously suspect CPU/memory
columns, GPU behavior and a full browser regression run were not retested.
Earlier Code OSS results remain in its existing device verification report.
