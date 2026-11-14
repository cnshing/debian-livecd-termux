# Handoff: SYNC_FD semaphores in the packaged PanVK driver

State on 2026-11-13, Galaxy S20 (`x1s`, Mali-G77, kbase job manager uAPI 11.35, Linux 4.19.87).
For whoever ports sync-file support into the driver we package. Paths under `temp/` are local
files that Git ignores.

## Port in progress (2026-11-13)

The normal package still uses the upstream release. The independent port is
`tools/panvk-probes/sync-fd-patches/0001-jm-sync-file.patch`, built for Bionic
and arm64 glibc by `panvk-sync-fd.yml` directly on the reconstructed p0175
baseline. It excludes the two patches that regressed GTK presentation.
[Driver build 43543360366](https://github.com/cnshing/debian-livecd-termux/actions/runs/43543360366)
and [Mesa build 43543486396](https://github.com/cnshing/debian-livecd-termux/actions/runs/43543486396)
are passing builds. The initial driver tree is
`82cfe30d18230650c9d38135353462092601e97d`.

The stronger probe is implemented. CI
[43543662112](https://github.com/cnshing/debian-livecd-termux/actions/runs/43543662112)
built it for both ABIs. Against JimVulkan v1.6.0 on x1s:

- 300 real GPU buffer fills passed, checking all 1,024 words after exporting
  and polling a SYNC_FD, then importing and consuming its signalled payload.
  292 exports returned real FDs; the others returned the permitted `-1`.
- The process FD count was 11 after the first iteration and 11 after the last.
- Export after completion and import of `-1` passed.
- A kernel software-event fixture held a real sync file unsignalled. Import
  returned without hanging, a Vulkan CPU wait returned `VK_TIMEOUT`, and the
  imported semaphore's re-exported payload timed out in `poll` at 100 ms.
  Releasing the fixture's event signalled the file cleanly. No GPU job is
  blocked by this fixture. Its exact uAPI/layout restrictions are in the
  [series README](../../tools/panvk-probes/sync-fd-patches/README.md).
- The packaged driver remains the negative control: exercise mode returns 77
  for unsupported SYNC_FD, which is a skip rather than an acceptance pass.

The additional Zink wait is implemented as
`packages/mesa/0024-zink-wait-for-unattached-dmabuf-fences.patch`, Mesa revision
104. It fixes the attach helper's boolean result, accepts an already-signalled
`-1` without an ioctl, and waits on the submitted batch's Vulkan timeline if
any plane cannot attach its fence. It does so before notifying flush
completion, covering the normal synchronous export flush. The unsupported
EXPORT_SYNC_FILE ioctl no longer asserts. Patches 0021–0023 remain.

### Results on the port

The independent port passed the following on x1s, with privately staged files:

| Check | Result |
| --- | --- |
| Bionic SYNC_FD exercise | 300/300 GPU fills, 299 real exported FDs, FD count 11 → 11; empty first submit exports `-1`; completed export and import of `-1` pass |
| glibc SYNC_FD exercise under Bionilux | same 300/300 and 299 real FDs; FD count 9 → 9 |
| Pending fixture, both ABIs | Vulkan CPU wait returns `VK_TIMEOUT`; imported/re-exported semaphore stays unsignalled for 100 ms; release control signals cleanly |
| Basic Android probes | 7/7 exit zero; compute 10/10, binary/fence/idle sync controls pass |
| Triangle, vertex-buffer triangle, constant triangle | all readbacks match the baseline byte for byte, SHA-256 `fa9117cf…80d0c2` |
| GNOME/GTK4, SHM, 20 cycles, Mesa 104 | checker passes 40 captures, max pixel error 0, stale-frame negative control rejected; isolation passes; no semaphore/SYNC_FD errors in Shell log; Shell, Files and Settings captures visually inspected |
| EGL native fences | `eglinfo` reports `EGL_ANDROID_native_fence_sync` on Zink |
| Firefox 159.0.1, VP9 and HEVC | hardware decoding and GPU output pass; 67 VA-API frames each, about 48.1 dB / 0.971 SSIM; isolation and cleanup pass |
| Chromium, VP9, two fullscreen cycles | passes browser and compositor pixel checks; `VaapiVideoDecoder`, PanVK ANGLE renderer with GPU compositing enabled, patched Bionic ICD mapped and Mali FDs held |
| Chrome, VP9, two fullscreen cycles | hardware decoding and GPU output run with the patched glibc ICD, but compositor frame 36 misses SSIM (0.898662 vs 0.9); **unpatched source control gives identical metrics and byte-identical normalized captures**. This remains a failed acceptance check, not a SYNC_FD regression |

Browser launchers used the installed `acceleration.prepare()` code with a private
`graphics.PANVK` root, preserving its normal flags and video stack. Firefox also
prepended the private Mesa 104 libraries. The managed desktop and installed
packages were unchanged. Runs serialized on the phone's fullscreen-test lock.

Artifacts from driver CI 43543360366, `out/patched/libvulkan_panfrost.so`:

- Bionic SHA-256 `9110264db9e497b4eeaa80fe9763537bc21d514b24796be690e41da34cd5b428`.
- glibc SHA-256 `1576ba28e48be9c09d716838cfeeb2d67c9fd9553ceecc554606ba7dcc51c90f`.
- Mesa `mesa_26.2.6-104_aarch64.deb`, CI artifact `debs-mesa-a5e834489f2ae549`
  (ID 14092634222), SHA-256
  `d329c6c508e619b7c9c3c2b8b7dc308c4da6f2ad8d05834f92858a91c5989260`.
- Its `libgallium-26.2.6.so` SHA-256
  `3e066bca3e51aacab7014d2ed031ba893fb0d4f42656ea849edba78dee70ccd8`.

Host evidence: `/home/cs/debian-livecd-termux-sync-fd/temp/sync-fd/`; phone:
`~/gpu-x1s/sync-fd-port/`. The stronger probe is from CI 43544161945, adding
an empty submission before any GPU work to the earlier CPU-deadline probe.

### Direct dma-buf control and the GTK gate

`tools/panvk-probes/dmabuf-readback.py` bypasses GTK. It clears a GLES3 RGBA8
texture, exports a real dma-buf, maps it with DMA_BUF_IOCTL_SYNC START/END,
and checks every pixel without `glFinish` or `glReadPixels`. With the independent
SYNC_FD ICD and Mesa 104, **30/30 frames and 7,864,320 pixel checks pass**, also
on a repeat run. With exactly the same ICD, both Mesa 102 and the installed
Mesa 103 fail at frame 0, row 0. These are the without-wait controls: the
semaphore port alone does not make exported pixels safe. This constant-color
probe accepts one plane with linear or implicit modifier and does not qualify
all layouts or consumers.

The combined workgroup variant also passed
[CI 43544398129](https://github.com/cnshing/debian-livecd-termux/actions/runs/43544398129).
Its Android SHA-256 is
`4df8da7f3d387d0c1c36970cb95a348d6b35e8bb0742ab290767280a5bdde718`,
content tree `0978323390ae641ba0a79405ba2cb4414153ff4a`. This build includes the
original four workgroup patches at commit 5934638, rather than the subsequent
partial-workgroup/cache follow-up. Caching was disabled and `PANVK_G77_LWG=1`
was explicit. Ghostty and GTK each pass four fresh terminal/color captures,
stale-frame rejection, isolation and normal exit. **Ghostty still uses CPU
readback presentation.** Its log first advertises native fences and GL 4.6,
then says:

```text
failed to build dmabuf err=dmabuf support disabled at compile-time.
failed to import dmabuf, asking renderer for CPU presentation
```

The error originates in GTK's `gdk_dmabuf_texture_new_from_builder`, not in
Ghostty's export code. Termux's pinned
[`gtk4/meson.build.patch`](https://github.com/termux/termux-packages/blob/538685c906074926fd19650e38c6dad91379eb0f/x11-packages/gtk4/meson.build.patch)
explicitly sets `HAVE_DMABUF` and `HAVE_UDMABUF` to false. GTK's Cairo rendering
therefore does **not** establish an accepted mapped dma-buf path here.
`check-ghostty-panvk.py` now reports the CPU fallback and its optional
`--reject-cpu-fallback` correctly rejects this run. Absence of that warning by
itself would still not establish successful DMA-BUF presentation.

The next Ghostty gate is a privately built GTK with DMA-BUF support, first
through Cairo/mmap, then the separately failing GL renderer. Keep udmabuf and
global launcher defaults unchanged while testing it. The direct EGL control
above already establishes why Mesa patch 0024 is necessary on this kernel.

### GTK DMA-BUF experiment

`.github/workflows/gtk-dmabuf.yml` builds the pinned Termux GTK 4.24.1
recipe with `HAVE_DMABUF` header detection restored. UDMABUF remains disabled,
and the existing X11 EGL workaround remains in place. Debug diagnostics are
retained; revision 101 also logs the two positive path markers unconditionally. This workflow produces a qualification artifact
only; it does not add GTK to the normal repository or change launcher defaults.
Extract its `libgtk-4.so.1` privately and prepend that directory only for Ghostty.
The checked-in `tools/panvk-probes/ghostty-gtk-dmabuf.py` launcher does this
when copied beside `gtk-dmabuf/lib/` and passed as `--ghostty-launcher` to the
desktop probe. `PANVK_GTK_LIB_DIR` can select another private directory.

[GTK CI 43558508034](https://github.com/cnshing/debian-livecd-termux/actions/runs/43558508034)
passes, including the generated configuration audit: `#define HAVE_DMABUF` and
`#undef HAVE_UDMABUF`. Earlier builds compiled and packaged successfully but
failed an overly strict post-build check expecting a numeric boolean define.

The first private device run, `ghostty-gtk-dmabuf-1`, loads the staged GTK
library (confirmed in `/proc` mappings). It passes four fresh Ghostty captures,
normal exit and isolation, but **still uses CPU fallback**: GTK rejects
`Unsupported dmabuf format: AB24:0xffffffffffffff`. The compile-time gate is
cleared; the modifier gate remains. Ghostty replaces `GDK_DEBUG` during startup,
so the private revision 101 build adds unconditional positive import/download
messages, without changing acceptance checks or synchronization.

GTK's mmap importer advertises and accepts only `DRM_FORMAT_MOD_LINEAR`.
The implicit modifier must not simply be relabelled for unknown layouts.
`dmabuf-readback.py --spatial` passes 30 frames and 7,864,320 pixel checks with
Mesa 104, using four distinct quadrants on each changing frame. Its additional
`--require-linear` check rejects Mesa 104, matching GTK's rejection.

Mesa revision 105 adds
`0025-zink-export-linear-image-modifier.patch`: report LINEAR only when Zink's
resource records that the image was created with `VK_IMAGE_TILING_LINEAR` and
its modifier was otherwise INVALID. The existing Vulkan subresource offset and
row pitch are retained. Unknown/optimal layouts keep their existing modifier.
This follows the [Vulkan linear-tiling definition](https://docs.vulkan.org/refpages/latest/refpages/source/VkImageTiling.html)
and [DRM linear-layout contract](https://www.kernel.org/doc/html/latest/userspace-api/dma-buf-alloc-exchange.html).
Runtime qualification of revision 105 is pending its CI build.

`check-ghostty-panvk.py --require-dmabuf` requires positive GTK texture-import
and mmap-download diagnostics at least once per fresh capture, in addition to
all pixel, GPU identity, normal-exit and isolation checks. It rejects the saved
CPU-fallback run. `panvk-desktop.py` now records GTK library mappings to prove
which library the process loaded. A passing Cairo/mmap test would establish
DMA-BUF transport with a CPU download inside GTK; it would not establish a
GPU-only presentation path.

### Package candidate

`mesa-vulkan-icd-panvk-kbase-sync-fd` reuses the shared source-package support
and installs the **independent** tested pair under `$PREFIX/lib/panvk-kbase-sync-fd`.
No overlay or launcher selects it automatically. The recipe pins the
[qualification prerelease](https://github.com/cnshing/debian-livecd-termux/releases/tag/panvk-sync-fd-26.3.1-1)
and installs `SOURCE.json`. That asset set contains both binaries, the
unmodified p0175 source archive, the exact port patch, its upstream MIT license,
and both ABI build records. Apply the listed patch to the archive to obtain
content tree `82cfe30d…`. The glibc `$ORIGIN` RUNPATH is recorded; CI absolute
search paths are rejected by the package audit.

[Package CI 43546461791](https://github.com/cnshing/debian-livecd-termux/actions/runs/43546461791)
passed the candidate build and ABI/provenance audit. The retrieved package also
passed the host audit; deliberately corrupting its Bionic ICD was rejected by
the pinned-hash check.

- Artifact `debs-mesa-vulkan-icd-panvk-kbase-sync-fd-f8477a1c80efa833`,
  ID 14094670041.
- `mesa-vulkan-icd-panvk-kbase-sync-fd_26.3.1_aarch64.deb`, SHA-256
  `4cf0242faa11426c80bf7b27d722de70aa167cbe9357f5df312a7e4df7433bf6`.

**Ghostty DMA-BUF presentation and normal-package promotion remain pending.**
The Chrome oracle failure and installed desktop qualification must remain
visible when deciding promotion. All phone processes started by this work
were cleaned; only `X0` and the original managed owner 23548 / Shell 23741
remained. Package building and audit require no further phone access.

## The job

The packaged driver (`mesa-vulkan-icd-panvk-kbase`, Zenith's port, release 26.3.1) cannot
create, import or export a SYNC_FD semaphore on this phone.
[JimVulkan/mali-panvk](https://github.com/JimVulkan/mali-panvk) can, on the same phone and
kernel. Port its mechanism into the packaged driver's source.

```text
~/gpu-x1s/panvk/probes/sync-fd <driver>
packaged:   SYNC_FD: importable=0 exportable=0 compatible=0x0  create_exportable=-1000072003
JimVulkan:  SYNC_FD: importable=1 exportable=1 compatible=0x11 create_exportable=0
```

## What it buys, and what it does not

| Gain | Status |
| --- | --- |
| Zink reports native fences (`EGL_ANDROID_native_fence_sync`) | follows directly |
| Mesa patches 0021 to 0023 stop doing anything | follows directly; see below |
| Ghostty presents its frame as a DMA-BUF instead of reading it back | **needs two more things**, below |

The three Zink patches (`packages/mesa/0021`, `0022`, `0023`) each test for the missing
capability, so with a working driver 0021 passes the query, 0022 no longer refuses export and
0023's bound is never reached. **Keep them in the recipe**: an older driver package, or another
driver without SYNC_FD, still needs them.

**DMA-BUF presentation for Ghostty needs more than the semaphores:**

1. **This kernel cannot attach a fence to a dma-buf.** Zink hands a frame's fence to the next
   user of an exported buffer with `DMA_BUF_IOCTL_IMPORT_SYNC_FILE`, and waits for other
   users with `DMA_BUF_IOCTL_EXPORT_SYNC_FILE` (`zink_screen_import_dmabuf_semaphore`,
   `zink_screen_export_dmabuf_semaphore` in `zink_screen.c`). Both arrived in Linux 6.0. On
   the S20 both return `ENOTTY` on an ION dma-buf, while `DMA_BUF_IOCTL_SYNC` works (output
   in `temp/gpu-x1s/jim-eval/dmabuf-sync-file-ioctl.txt`). So with SYNC_FD working, Zink
   creates the semaphore, the attach fails quietly, and GTK can read the buffer before the
   GPU has finished it. Ghostty's export (`src/renderer/opengl/Target.zig`, `exportDmabuf`)
   blits and exports; it does not wait.
   The missing piece is a wait in Zink: when the attach fails with `ENOTTY`, finish the batch
   before the flush that exported the buffer returns. That is a fourth small patch, and the
   existing stale-frame control is its test.
2. **Ghostty needs OpenGL 4.3 before any of this matters.** With the packaged driver it runs
   on llvmpipe. See [PANVK-VERSION-BUMP-HANDOFF.md](PANVK-VERSION-BUMP-HANDOFF.md).

The installed GTK build is another independent gate: Termux compiles DMA-BUF
support out, so even Cairo uses Ghostty's CPU-readback fallback. The direct EGL
probe above validates the producer wait without GTK. Rebuild and qualify GTK's
DMA-BUF consumer before claiming Ghostty DMA-BUF presentation. GTK's GL renderer
also has the earlier `error.BadAccess` failure recorded in
[GHOSTTY-PANVK-HANDOFF.md](GHOSTTY-PANVK-HANDOFF.md).

## Why the packaged driver has no SYNC_FD here

Its source (pinned at `cf70e02b`, reference copy in
`temp/gpu-x1s/references/panvk-kbase-android`):

- `patches/kbase-common/004-physical-device-kbase.patch` adds a sync type that lives in the
  process (`kbase_cpu_sync`). It imports a sync file by waiting on it. Its first export went
  through `/dev/sw_sync`, which this phone does not have.
- `patches/csf-v11/075-export-kbase-sync-file-fences-through-a-kcpu-queue.patch` replaced
  that with a kbase KCPU queue (a CQS wait followed by a fence signal). KCPU queues exist only
  on the command-stream kernels, so the same patch turns export off below architecture 10:

  ```c
  if (pan_arch(device->kmod.dev->props.gpu_id) < 10)
     device->drm_syncobj_type.export_sync_file = NULL;
  ```

- The G77 is architecture 9 on the job manager. Mesa's common code reports a handle type as
  unsupported unless the sync type can both import and export it, which is the probe's
  `importable=0 exportable=0`.

## How JimVulkan does it on the job manager

All in `src/panfrost/lib/kmod/kbase_kmod.c` at tag `v1.6.0` (commit `58f2c55`, MIT). Read the
two comment blocks "sync objects" and "asynchronous submission" first.

- **A fence-trigger soft atom.** Every submission gets one extra atom with
  `core_req = BASE_JD_REQ_SOFT_FENCE_TRIGGER` (`0x202`), ordered after the submission's last
  atoms. Its `jc` points at a `{int fd; int stream_fd}` pair set to -1. The kernel
  (`mali_kbase_softjobs.c`) writes a sync file's fd into it during `KBASE_IOCTL_JOB_SUBMIT`,
  and that sync file signals when the GPU work is done.
- **The object keeps the fd.** A sync object signalled by a submission is `SUBMITTED` and
  holds that fd. `ks_export_sync_file` returns a `dup` of it, or -1 when the object has
  already signalled, which Vulkan allows for SYNC_FD.
- **Import** keeps a copy of the incoming sync file and polls it; an already signalled one
  signals the object at once (`ks_import_sync_file`).
- **Several objects, one fd:** `SYNC_IOC_MERGE` (`pan_kmod_kbase_sync_merged_fd`).
- The kernel runs soft atoms from a worker, later than the GPU atom they follow. JimVulkan
  keeps the fence atom out of its own completion tracking for that reason: a submission is
  complete on its last GPU atom.

## The port

The packaged driver already has the pieces to hang this on:

| Piece | Where in the packaged source | Change |
| --- | --- | --- |
| Atom submission and the atom table | `kbase_kmod.c`, from `patches/jm-v9/001` and `022` | append a fence-trigger atom to the batch's last submission, in the layout the device probed (this phone: stride 56), and read the fd back |
| The sync object | `kbase_cpu_sync` in `panvk_physical_device.c`, from `kbase-common/004` | hold the fd while pending; close it on reset, signal and finish |
| Export | `kbase_cpu_sync_export_sync_file`, as `csf-v11/075` left it | on the job manager: `dup` the held fd, -1 if signalled; stop setting it to NULL below architecture 10 |
| Import | `kbase_cpu_sync_import_sync_file` | already there; check it against a fence that never signals |
| Queue submit | the v9 backend, `jm-v9/002` | pass the batch's signal syncs down so the fd lands on them |

The port is carried separately in `tools/panvk-probes/sync-fd-patches/` and applies to
the reconstructed p0175 tree. Its source attribution and JimVulkan's MIT license are
preserved. It adapts the fence-trigger mechanism to the existing atom allocator rather
than replacing the whole file or adopting JimVulkan's event-thread submission model.

Watch for:

- **Atom numbers.** There are 255, and the fence atom takes one per submission until its own
  event arrives. The packaged driver's table must free it, without waiting on it.
- **A submission with no GPU work** (a present that only signals). There is no atom to follow;
  signal on the CPU and export -1.
- **Whether this kernel has the soft job at all.** JimVulkan's driver creating an exportable
  semaphore here says yes, but the probe stops at creation. See the first test.
- **The glibc build.** Chrome uses the same driver built for glibc; the patch must not pull in
  Android headers.

## Building and packaging

`.github/workflows/panvk-sync-fd.yml` reconstructs the pinned p0175 tree and builds
both ABIs, retaining the unmodified baseline and the independent `patched/` variant.
The optional `workgroups=true` workflow input combines the two experimental series
for private Ghostty tests. It does not change the candidate recipe's pinned pair.

The earlier X11/point-size `driver-patches/` variant regressed GTK presentation.
Neither of those patches is included in this port or its candidate package. The
workgroup experiment also remains separate from the ordinary SYNC_FD candidate.

The source-package prerequisite is implemented once in the shared
`mesa-vulkan-icd-panvk-kbase` recipe support; `-source` pins the baseline and
`-sync-fd` pins this independent port. Each installs beside the normal release,
with its own `SOURCE.json` and hash-checked binary assets. The new candidate adds
the port's MIT attribution to the inherited copyright bundle. Updating a candidate
requires a new immutable asset set and reviewed hash/provenance lock, followed by
`packages.yml` and `check-panvk-artifact.py`. Keep the existing normal package
selected until its installed-desktop and consumer promotion gates are met.

Builds run in GitHub CI, not on the host or the phone.

## Tests, in order

1. **Run `tools/panvk-probes/sync-fd.c` with `--exercise`**, then run
   `jm-pending-fence.py` against the same ICD. These are implemented and the JimVulkan
   reference control passed (above). The independent port still needs both controls.
   Use the latest probe CI artifact; normal invocation only reports capabilities.
2. Zenith's probes (`~/gpu-x1s/panvk/probes`: `compute`, `sync`, `triangle`) on the patched
   driver, pictures identical to the baseline's.
3. **The desktop**, because Mutter starts using native fences the moment Zink reports them,
   the path patch 0021 switched off: `tests/native/panvk-desktop.py --mode shm --cycles 20
   --driver <patched>`, checked with `tests/native/check-panvk-desktop.py`. No semaphore
   errors in the Shell log, stale-frame control rejected.
4. **Firefox video** (`tests/browsers/test-acceleration.py firefox`, VP9 and HEVC). It
   imports dma-bufs, so Zink now creates a semaphore per plane and tries both ioctls. A Mesa
   built with assertions aborts there (`assert(!"how did this fail?")`); the package is not,
   but check.
5. Chromium and Chrome playback through the installed wrappers, for the glibc driver.
6. **Ghostty** on the large-workgroup driver with the extra Zink wait:
   `panvk-desktop.py --ghostty-probe` and `tests/native/check-ghostty-panvk.py`. Its
   colour-phase control is what catches a frame presented before the GPU finished. Run it
   without the wait once, to see the control fail.

Phone rules are in [VIDEO-ENCODING-HANDOFF.md](VIDEO-ENCODING-HANDOFF.md): private displays
only, mark `temp/PHONE-STATUS`, check memory between runs.

## Where things are

| What | Where |
| --- | --- |
| Capability probe | `tools/panvk-probes/sync-fd.c`, built by `.github/workflows/panvk-probes.yml`; on the phone `~/gpu-x1s/panvk/probes/sync-fd` |
| JimVulkan's driver, staged | phone `~/gpu-x1s/jim/android/lib/libvulkan_panfrost.so` (v1.6.0, SHA-256 `80acd461…c7ac0d`) |
| Comparison of the two drivers | [MALI-GPU-STATUS.md](MALI-GPU-STATUS.md); raw output `temp/gpu-x1s/jim-eval/` |
| Zink's dma-buf fence code | Mesa 26.2.6 `src/gallium/drivers/zink/zink_screen.c`, `zink_batch.c` (`submit_queue`) |
| The three Zink patches | `packages/mesa/0021` to `0023` |
| Driver rebuild in CI | `.github/workflows/panvk-driver.yml`, `tools/panvk-probes/` |
| Ghostty experiment | [GHOSTTY-PANVK-HANDOFF.md](GHOSTTY-PANVK-HANDOFF.md), `tools/panvk-probes/workgroups/` |
