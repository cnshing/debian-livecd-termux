# Serein package verification

Raw build logs and device
captures remain in local caches and the Git-ignored `temp/serein/` directory.

## Inputs

| Input | Version |
| --- | --- |
| Serein source | `v1.0.0-nightly.20261028.68` |
| Source archive SHA-256 | `98914d0b782bccf547dea11185626658a8686e819babd22b9f7cb880ff3f834a` |
| Termux builder | `538685c906074926fd19650e38c6dad91379eb0f` |
| Cross compiler | Rust 1.98.1; the project's pinned NDK r30 / API 24 builder |
| Native compiler | Rust 1.99.1; Clang/LLD 21.1.8 |
| Device | Samsung Note10+, aarch64, Android 11 |

The release archive declares Cargo workspace version `0.1.0`; the APT package
version identifies the nightly tag. The package enables the full voice engine
and `demo`, disables development data, and uses thin LTO with 16 codegen units.

The host build uses the pinned Termux builder with `-I -w`: official binary
dependencies available from the current mirrors, without requiring their exact
versions to match the builder's recipe snapshot. The ordinary helper's stricter
default may rebuild dependencies whose pinned versions are unavailable.

## Checks

| Check | Result |
| --- | --- |
| Source archive and application patch | SHA-256 verified; `recipes.py check-patches serein` passed |
| Clean preparation | 1,450 Rust/manifest files matched the prepared build tree; dependency versions, sources and package checksums stayed within the upstream lockfile |
| Host packaging checks | Existing packaging suite: 9 passed |
| TLS on the phone | The client's compiled reqwest/TLS dependencies accepted GitHub's certificate using Termux's CA roots and rejected a self-signed local server certificate with `UnknownIssuer` |
| Exclusive file publication on the phone | The API-24 compatibility wrapper published a new file and rejected replacement of an existing file or symlink with `EEXIST`; original contents remained intact |
| Cross-built APT package | Passed; Termux's symbol checks accepted the Android/aarch64 executable |
| Packaged GUI, OpenGL | Passed on private Xvfb: rendered demo, resized from 1120×760 to 1024×760, Ctrl+Q exited with status 0 |
| Packaged GUI, Vulkan | Passed the same checks on private Xvfb |
| Managed GNOME session | Packaged demo opened a visible window and stayed running; reported Turnip Adreno 640 / Vulkan; the test then stopped its own client |
| Separate on-device source build | Dependencies compiled; redundant final optimization was stopped after the cross-built package passed device checks. A native-built executable was not produced |

The TLS test uses [`tls-probe.rs`](../../tests/serein/tls-probe.rs), linked against
the actual client's compiled libraries, and
[`check-tls.py`](../../tests/serein/check-tls.py). The fixture generates a private,
temporary server key and certificate and listens only on loopback. It does not
use an account or any saved credentials.

## Port fixes

The package selects desktop integrations while keeping Android's real Rust
target and syscall crates. It carries the earlier cpal queue fix, fixes the
bundled Opus build script's missing Android host case and CMake system selection,
and supplies the missing `managed` field in four upstream demo role fixtures.

Android's libc does not expose `renameat2` at the API-24 baseline. A small C
wrapper uses the kernel syscall, preserving the original `RENAME_NOREPLACE`
operation. [`test-rename.py`](../../tests/serein/test-rename.py) exercises the
wrapper against real files on the phone.

The packaged GUI checks use [`test-desktop.py`](../../tests/serein/test-desktop.py).
Screenshots of the synthetic workspace were reviewed. OpenGL used Zink over
llvmpipe; Vulkan used llvmpipe. These private-display results establish software
rendering. The managed-session check establishes startup with the phone's normal
environment and its reported Vulkan adapter; it is not a hardware-performance
measurement. Test clients, displays and private session launchers were stopped.

## Local artifact

`temp/serein/artifacts/serein_1.0.0~nightly.20261028.68_aarch64.deb`
is **46,293,240 bytes**. Its SHA-256 is:

```text
2de0fd6dbfb4e085f72afd463668f02758149fa64d4034f91c0d944b4c029716
```

The executable is an Android PIE using `/system/bin/linker64`. The package also
contains its application-menu entry, SVG icon, upstream licenses and third-party
notices. The artifact and checksum sidecar are local and excluded from Git; no
public release or APT installation on the phone was performed. Device tests ran
the executable extracted from this exact package.

The native LLD 21 linker intermittently aborted with a Scudo allocator error.
Native recipe builds limit LLD to one worker thread, including links of Rust
build scripts. This does not change the running desktop's compiler installation.

## Limits

No account sign-in, real Discord session, message, voice call or microphone use
is part of this verification. Camera capture, screen sharing, physical playback,
global shortcuts and real notification delivery remain unverified. The
[earlier microphone results](../mic/VERIFICATION.md) cover the audio engine only.

The port builds X11 windows. Other architectures, Android versions, Wayland
windows and a public package release are not established by these results.
