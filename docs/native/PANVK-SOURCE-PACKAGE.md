# Source-built PanVK qualification package

`mesa-vulkan-icd-panvk-kbase-source` installs an unmodified source-built p0175
PanVK driver for both Bionic and glibc under `$PREFIX/lib/panvk-kbase-source`.
It carries its source and binary identities in
`$PREFIX/share/doc/mesa-vulkan-icd-panvk-kbase-source/SOURCE.json`.
The normal package continues to use `$PREFIX/lib/panvk-kbase`; launchers and
overlays select that stack. Installing the candidate therefore permits explicit
qualification without switching a running desktop to a new driver.

## Source and build identity

The candidate pins [baseline build 43542985775](https://github.com/cnshing/debian-livecd-termux/actions/runs/43542985775)
and the durable [qualification assets](https://github.com/cnshing/debian-livecd-termux/releases/tag/panvk-source-26.3.1-1).
The prerelease includes both binaries, the complete prepared source archive,
reconstruction history and build provenance. Its tag does not change the
installer's latest normal release.

- Zenith source: `cf70e02b918e1864cbcd746a7fefa57b96c673ce`.
- Reconstructed Mesa content tree: `4a8e9a8cbb34b9fb91a9ad2040319aceb075b973`.
- Local driver patches: none. The glibc binary has its CI RUNPATH removed after
  stripping; no shader or synchronization code changes.
- Binary and source-archive SHA-256 pins: the recipe's `source.lock.json`.
- Compiler, NDK and downloaded build-dependency hashes: `build-provenance.tar.gz`.
- Packaged runtime X11/Wayland libraries: the shared release recipe's
  `libraries.lock.json`. The candidate's package-cache identity includes those
  shared inputs.

The reconstructed commits contain timestamps. Use the content-tree identity
when checking reconstructed source, rather than requiring its commit ID to be
identical. This establishes the source that was built; it does not establish
byte equality with Zenith's release binaries.

## Building and checking

Driver builds run in Actions:

```sh
gh workflow run panvk-driver.yml --ref main -f variant=baseline
gh workflow run packages.yml --ref main -f packages=mesa-vulkan-icd-panvk-kbase-source
```

The first builds both ABIs and records provenance; it does not replace the
candidate's pinned assets. A new pair needs a new immutable prerelease asset set,
updated hashes and a package revision. Keep previous asset sets available.
The second packages the already pinned pair with the usual Termux builder.
`tests/packaging/check-panvk-artifact.py` checks the package's binary hashes,
source manifest, ARM64 architecture, libc ABI, Vulkan entry points, ICD paths
and absence of absolute CI RUNPATHs. The unchanged Bionic binary retains only
`$ORIGIN/../../android_stub`, its relative toolchain stub path; packaging that
stub directory or any other search override is rejected. The glibc driver has
no RUNPATH. A candidate that writes into the release stack is
rejected.

Other driver build variants are `point-size`, `x11`, `workgroups` and `research`.
The first two apply just their named patch to the baseline. `workgroups` applies
only the experimental workgroup series. `research` retains the previous combined
X11/point-size series for reproducing its GTK failure. Each variant also retains
an unpatched binary as its control. None updates the package lock automatically.

For private phone qualification, extract the package and pass the extracted
Bionic `libvulkan_panfrost.so` to `tests/native/panvk-desktop.py --driver`.
Keep its standard filename so the harness records its process mappings.
Keep the Bionic X11 soname links until the isolated X11 patch passes qualification.
The candidate ICDs describe Vulkan 1.3.363; its G77 compute limit remains 512 and
Zink continues to report OpenGL 4.2 and GLES 3.1.

The [candidate package run 43544618382](https://github.com/cnshing/debian-livecd-termux/actions/runs/43544618382)
passed the Termux build, package audit and repository assembly. Package artifact:
`debs-mesa-vulkan-icd-panvk-kbase-source-1ce508849e7c2981`.
The retrieved package also passed the host audit, and a deliberately corrupted
driver was rejected by the pinned-hash check.

## Baseline device evidence, 2026-11-13

The exact pinned binary pair was staged privately on x1s. Bionic and glibc each
passed seven basic processes: enumeration, compute, three triangle paths,
synchronization and the external-fence capability probe. The last probe still
reports SYNC_FD as unavailable; its successful exit confirms that expected
baseline result, rather than new fence support.

The pinned Bionic driver also passed 20 private desktop resize/fullscreen
cycles: 40 captures checked independently, maximum colour-channel error 0,
and stale-frame rejection. GNOME Shell and GTK map the exact staged PanVK
library and hold Mali device descriptors. Nautilus and Settings windows were
found, the Nautilus capture was inspected, and the isolation check passed.
The original managed session remained owner 23548 / Shell 23741, tag
`a1637792cc534a218c937b68ef8e6c75`; private displays were removed.

Host evidence is local under `temp/panvk-version-bump/evidence/` in the original
checkout: `desktop-package-baseline-20/`, `android-basic/` and `glibc-basic/`.
An earlier source-build control also passed 40 captures in
`desktop-baseline-20b/`. These are separate runs with different build identities.

## Promotion gate

The source candidate must pass installed desktop validation (30/30) before the
normal driver recipe is repinned to it. Private GTK capture checks and basic
Vulkan probes are useful evidence, but do not replace that installed-session
check. Stop only private test processes that belong to the test. Follow
[VIDEO-ENCODING-HANDOFF.md](VIDEO-ENCODING-HANDOFF.md) for device coordination.

Feature patches then need their own qualification as described in
[PANVK-VERSION-BUMP-HANDOFF.md](PANVK-VERSION-BUMP-HANDOFF.md).
