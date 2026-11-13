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

Use `--mode shm` for the default transport, or `--mode shm --server xvfb` for
the Xvfb control. `--restart-cycles 100` adds normal vkcube start/stop cycles.
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

Keep builds in CI. Do not run the reference `build-glibc.sh` on an x86 host: its
fallback dispatches to a rooted phone chroot. Do not run Firefox workloads or
select ANGLE under this research scope.

See [the continuation results](../../docs/native/PANVK-X1S-RESEARCH.md) for
validated short runs, the failed partial soak, and remaining acceptance.
