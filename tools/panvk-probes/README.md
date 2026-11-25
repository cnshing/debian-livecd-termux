# x1s PanVK research

This branch builds and tests the pinned Zenith kbase driver privately. It does
not install a driver, change the managed desktop, or publish a release.

`panvk-probes.yml` builds the basic probes, external-semaphore capability probe,
wider feature probes, and Android AHB probes. The glibc job also builds the X11
SHM round-trip probe. Inputs are Zenith
`cf70e02b918e1864cbcd746a7fefa57b96c673ce` and Vulkan-Headers `v1.4.363`.
Shader tools run inside a Debian sid container; their exact versions are in
`SHADER-TOOLS.txt`. Package checksums and compiler versions accompany artifacts.
The source is pinned; the distro dependency resolver is not a bit-reproducible
toolchain pin.

`panvk-driver.yml` reconstructs Mesa `5a07217f` plus the strict universal series
through p0175, then builds Android API 29 and arm64 glibc ICDs in CI. It retains
an unmodified baseline and a `patched/` variant. The variant uses Termux's X11
sonames and configures v9 per-vertex point sizes. glibc's variant RUNPATH is
postprocessed to `$ORIGIN`; this is recorded in `PATCHES.txt`. Each build job
reconstructs and asserts base tree `4a8e9a8cbb34b9fb91a9ad2040319aceb075b973`
before applying the local patch series.

`prepare-rc5-tree.sh` makes timestamped commits. Compare reconstructed Git
**tree** IDs, patch inputs, and runtime readbacks. The release's
`patchedTreeCommit=795ca7ff3e8` is a commit label, and the release does not supply
its content-tree hash. A new commit ID cannot establish byte equivalence with
that binary.

The scripts below expect the private phone layout from the handoff:

```text
~/gpu-x1s/panvk/android/{icd.json,lib/libvulkan_panfrost.so,xlibs/}
~/gpu-x1s/panvk/glibc/{icd/,lib/,probes/}
~/gpu-x1s/panvk/private-lorie/private-lorie
~/gpu-x1s/browser-tests/browsers/{test-fullscreen.py,video_oracle.py,...}
~/.local/lib/livecd-native/{desktop.py,graphics.py,capture.py,...}
```

Copy `tests/native/panvk-desktop.py` to the phone. Run from plain Termux, using
an unused output directory:

```sh
timeout -k 15 600 python ~/gpu-x1s/panvk-desktop.py \
  --mode raw --cycles 20 --out ~/gpu-x1s/panvk/desktop-raw-new
```

Use `--mode ahb` for the experimental Android AHB transport (patch 0004 plus
the `combined-ahb` metadata patch), `--mode shm` for the default transport, or
`--mode shm --server xvfb` for the Xvfb control. `--restart-cycles 100` adds normal vkcube start/stop cycles.
`--soak-seconds 1800` runs vkcube FIFO and glxgears concurrently with periodic
captures and process resource audits. This tests concurrent stability, not
individual-workload performance. Increase the outer timeout for a soak.
`--driver /absolute/path/libvulkan_panfrost.so` selects a private rebuilt ICD;
`--mesa-lib-dir /private/extraction/lib` selects a privately extracted Mesa.
`--no-xlibs` removes the private X11 soname symlink directory to check the
rebuilt Android driver's Termux sonames directly. Loading passed, but the
patched variant failed GTK swapchain creation; see the results report.
`check-x11-libraries.py /path/to/pinned/wsi_x11_dlopen.c` checks all nine
unversioned dlopen names and the source's required symbols from plain Termux.
Run with `LD_LIBRARY_PATH` and `LD_PRELOAD` unset; this checks loading, not
presentation or GPU correctness.

The harness takes the existing fullscreen-test lock, allocates a private
display, D-Bus and XDG paths, disables the private battery shell helper, and
compares shared desktop/daemon process start times and status before and after.
It terminates only its children and services carrying its exact test marker,
checking process start times before signaling escaped services. It also removes
the private lorie socket/lock. Internal workers refuse the live display.
The harness conservatively refuses other private displays and checks for new
ones during cycles and soaks. This supports attribution of failures and
resource measurements; another display alone does not invalidate correct
pixels. GTK commands are replaced atomically to avoid partial JSON reads.
`--allow-other-displays` records overlap without rejecting a short correctness
run; it cannot be used for a soak. Broad snapshot differences remain reported
as isolation failures, independently of the captured-pixel results.

Retrieve `result.json`, `isolation.json`, logs, and PNGs. On the host:

```sh
python3 tests/native/check-panvk-desktop.py /path/to/retrieved/output
```

The checker requires PanVK maps and Mali FDs in Shell and GTK4, correct window
and fullscreen geometry, and every quadrant interior pixel plus 100 distributed
color samples per captured GTK4 frame. It
rejects a deliberately stale color phase as a negative control. Shell,
Nautilus, and Settings captures also require visual inspection. Passing these
checks does not qualify all applications, codecs, browsers, or device families.

The wider runner is `tests/native/run-panvk-features.py`. Place the compiled
`features/` directories under `~/gpu-x1s/panvk/wider/{android,glibc}/`, then use
`--abi android` or `--abi glibc` with a fresh output directory. Each process has
its own kill timeout. Exit zero is recorded separately from rendered-pixel
acceptance; unsupported extensions and missing DMA heaps are not successes.
`--driver /absolute/path/libvulkan_panfrost.so` selects a rebuilt ICD.
`--basic` runs enumerate, compute, three triangle readbacks, sync, and sync-fd
from `panvk/probes/` (Android) or `panvk/glibc/probes/` instead of the wider suite.
`graphics-software-control` deliberately selects a CPU device and must never
be counted as hardware evidence. The original graphics test's thresholds stay
unchanged, and `FEATURE_DUMP=/path/file.rgba` enables its 64x64 RGBA dump.

`ahb_render2` is excluded because its debug read unconditionally scans 69632
bytes without checking the actual allocation size. AHB import remains separate
from WSI-owned buffers; successful presentation does not qualify app AHB import.

`ahb-import.py --driver /absolute/path/libvulkan_panfrost.so --out fresh.json`
checks public 1920×1080 RGBA AHB allocations with GPU-only usage (`0x300`) and
CPU read/write added (`0x333`). It imports dedicated image memory, reads a CPU
quadrant pattern with the GPU, clears with the GPU, and checks every readback
pixel through both a Vulkan staging buffer and the public Android CPU mapping.
The GPU-only case can fail while the CPU-usable fallback passes; the JSON keeps
both results and the driver hash. No dma-buf layout is inferred from a public
stride. Run from plain 64-bit Termux with `LD_LIBRARY_PATH` and `LD_PRELOAD` unset.
Add `--egl` to sample the result through Android EGL/GLES in an offscreen pbuffer.
`--format bgra --clear red --no-cpu-mapping` checks BGRA channel order with GPU,
EGL and optional X11 readback; it explicitly omits CPU-plane checks, which reject
the zero strides reported for BGRA on the S20. `--clear` also accepts green/blue.

`tests/native/panvk-ahb-present.py --driver /absolute/path/libvulkan_panfrost.so
--out fresh-directory` runs that probe on an owned private lorie, with modifier
1255 transport and Present completion-mode checks (`ahb-x11.py`). Copy the
`tests/` and `tools/` layout, including all three `ahb-*.py` helpers, to the phone.
It also requests the offscreen Android EGL check (`ahb-egl.py`). The server must
log the AHB import, all 180 paced presents must report `FLIP`, and every root
pixel must match. It records the server CPU during those three seconds. This
reuses one completed buffer, so it is not a swapchain race or physical scanout
test. The harness checks shared process state and cleans only its own display.
`python3 tools/panvk-probes/test-ahb-import.py` checks plane bounds and rejects
the live display without loading Android or XCB libraries.

The probes follow the public [NDK AHardwareBuffer API](https://developer.android.com/ndk/reference/group/a-hardware-buffer)
and [Vulkan AHB import rules](https://docs.vulkan.org/spec/latest/chapters/memory.html#memory-external-android-hardware-buffer).
They acquire/release imported images through `VK_QUEUE_FAMILY_FOREIGN_EXT` as
specified by [external queue ownership](https://docs.vulkan.org/spec/latest/chapters/synchronization.html#synchronization-queue-transfers).
Current measurements and remaining gates are in the
[AHB presentation handoff](../../docs/native/handoff/s20-panvk-ahb-present.md).

Keep builds in CI. Do not run the reference `build-glibc.sh` on an x86 host: its
fallback dispatches to a rooted phone chroot. Do not run Firefox workloads or
select ANGLE under this research scope.

See [the continuation results](../../docs/native/PANVK-X1S-RESEARCH.md) for
validated short runs, the failed partial soak, and remaining acceptance.

The `combined` variant selects the seven workgroup patches plus point size,
process budget, ION CPU cache mode and import coherence (eleven patches).
`combined-platform` adds the Termux hybrid ICD private-extension correction
and measured noncoherent ION placed-map capability restriction, the X11
render-completion wait and experimental AHB WSI (fifteen patches).
`combined-ahb` adds the legacy Mali AHB metadata import patch (sixteen patches).
It requires independent qualification and does not change package pins. See the current version-bump handoff for exact hashes and CTS results.

The desktop harness creates its private XDG runtime directory under Termux's
short `$TMPDIR` path. Evidence directories can be too deep for Unix sockets
created by GVfs. The chosen runtime path and its removal after owned-process
cleanup are recorded in `runtime-directory.json`; screenshots and logs remain
under the requested evidence directory.

For fix iterations, `cts/run.py --case <exact-name>` bypasses CTS listing and
runs only explicitly named cases. Repeat `--case` for a nearby control; use
`--pattern` when expanding coverage after the fix passes. Keep broad regressions
for the stable candidate. The driver workflow's `abi` input selects `android`,
`glibc`, or `both`. `combined-ahb-trace` is an Android AHB stage-logging variant
for focused diagnostics, with no allocation or advertised-feature changes.
