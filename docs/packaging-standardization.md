# Termux packaging standardization

Implementation and host verification results. Browser/video files are
handled in a separate session and were excluded from this change.

## Package ownership

- `livecd-mozjs-128`, `livecd-gjs`, `livecd-mutter` and
  `livecd-gnome-shell` build the GNOME source port's versions and patches with
  Termux's toolchain and package lifecycle. Their matching libraries stay under
  `$PREFIX/opt/gnome-48`. Meson can use bundled subprojects from the verified
  source archive, but cannot download additional wraps.
- `livecd-gnome-runtime` installs the native session and extra schemas.
  `livecd-gnome-data` packages portable extension/font/cursor assets; Noto fonts
  have a separate subpackage. Every input's attribution is retained, and the
  data installer rejects ELF files.
- `livecd-desktop` owns controller code and the `livecd`/`livecd-native`
  commands. Setup connects the existing per-user paths to package files and
  preserves replaced paths in `~/.local/state/livecd-native/runtime-backups`.
  The default installer does not fetch or rewrite a GNOME executable. Missing
  backend selections now fall back to native; explicit Debian selections remain.
- `livecd-gsconnect` builds its verified source archive using Meson, retaining
  Debian's identity-validation security fix and the native CJS changes.
- The Code OSS recipe resolves its menu-entry tokens during packaging. Its
  overlay only selects the desktop profile wrapper and extensions. Staging
  validates the pinned upstream recipe and retains upstream patches/helpers.

The old GNOME bootstrap is historical; its standalone download helper is still
imported by profile-specific asset hooks.

## One builder

`tools/termux-build.json` pins the builder revision and matching container image.
CI, the local helper and the remote Code OSS server's Termux patches use that
configuration. `tools/recipes.py prepare` stages recipes in the pinned tree;
local-source links affect both CI selection and cache hashes.

```sh
bash tools/build-packages.sh PACKAGE
# On native Termux, with the managed desktop stopped:
bash tools/build-packages.sh --install PACKAGE
```

The compatibility `build-on-device.sh` scripts now use this same builder and
install generated packages with APT, including declared subpackages. They do not
copy over installed package files or add APT holds. An old UPower hold is removed
when replacing it with `livecd-upower`. The shared helper assumes a configured
Termux build environment; Linux hosts use Docker. Native builds default to two
jobs and take the normal desktop session lock.

Python helpers remain valid build inputs for resource generation, metadata and
data preparation. The recipe declares dependencies and verified sources, applies
patches and produces the package; those boundaries matter independently of the
language used inside a build step.

## Verification

- Nine host integration tests cover dependency ordering, source changes and
  cache invalidation, preservation of upstream patches when staging, Code OSS
  menu metadata, complete artifact installation, runtime/profile migration and
  safe session preload selection.
- Source patches apply for all new GNOME recipes and source-based GSConnect.
- The portable data installer succeeds, preserves all input attributions and
  rejects ELF payloads. Its schemas compile with the runtime's generated
  schemas using `glib-compile-schemas --strict`.
- GSConnect configures, builds resources/translations and installs with host
  Meson/Ninja. Its 63 installed runtime JavaScript files, excluding the generated
  configuration, match the earlier patched Debian payload byte for byte.
- Python/shell syntax, workflow YAML, the shared revision and the existing
  AutoEq tests pass.

Full Android compilation of the new GNOME/Code OSS packages, installation of
the resulting release, and device acceptance have not run. The host lacks
Docker; no phone deployment or release publication was performed. The source
port's earlier native acceptance does not substitute for these package checks.

## Deliberate exceptions

The architecture-independent font/extension archives retain their tested data
payloads rather than rebuilding every asset from original source releases.
Theme variants and add-on choices remain overlays. The remote Code OSS server
builder targets Linux machines, and the optional Mixtapes token helper remains
upstream's glibc binary. The legacy PRoot profile has been removed.
Specialized browser/video standardization belongs to the separate session.
The proc-stat handoff's fixed session preload is now integrated with the
`livecd-resources` package and desktop dependency. Its old isolated device copy
remains available for rollback; see [the audit](resources/PROC-STAT-AUDIT.md).
