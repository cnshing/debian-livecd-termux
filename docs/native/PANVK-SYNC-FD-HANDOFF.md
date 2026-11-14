# Handoff: SYNC_FD semaphores in the packaged PanVK driver

State on 2026-11-13, Galaxy S20 (`x1s`, Mali-G77, kbase job manager uAPI 11.35, Linux 4.19.87).
For whoever ports sync-file support into the driver we package. Paths under `temp/` are local
files that Git ignores.

## Port in progress (2026-11-13)

The package still uses the upstream release. The independent port is
`tools/panvk-probes/sync-fd-patches/0001-jm-sync-file.patch`, built for Bionic
and arm64 glibc by `panvk-sync-fd.yml` directly on the reconstructed p0175
baseline. It excludes the two patches that regressed GTK presentation.
[Driver build 43543360366](https://github.com/cnshing/debian-livecd-termux/actions/runs/43543360366)
and [Mesa build 43543486396](https://github.com/cnshing/debian-livecd-termux/actions/runs/43543486396)
are the first qualification builds; runtime results belong here when available.

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

**Neither the driver port nor Ghostty DMA-BUF presentation is accepted yet.**
The desktop, browsers, kernel-ioctl fallback and stale-frame controls must pass
with the built binaries before package promotion. The separate large-workgroup
and GTK renderer limitations below still apply. All phone runs so far used
private files with no changes to the managed desktop.

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

Also temper the expectation of zero-copy: in the accepted Ghostty run GTK used its Cairo
renderer, which maps the dma-buf and copies it on the CPU. That still removes Ghostty's
`glReadPixels` and its allocation. GTK's GL renderer, which would import the buffer, failed
with `failed to make EGL context current err=error.BadAccess`
([GHOSTTY-PANVK-HANDOFF.md](GHOSTTY-PANVK-HANDOFF.md)); nobody has found out why.

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

Carry it as a patch in `tools/panvk-probes/driver-patches/`, applied to the reconstructed
p0175 tree, with JimVulkan's copyright line in what is copied (both projects are MIT). Do not
copy the whole file: JimVulkan's submission is asynchronous with its own event thread, the
packaged driver's is not, and swapping that model is a far larger change than this needs.

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

The package installs upstream's release binaries, so it cannot carry a patch today.
`.github/workflows/panvk-driver.yml` already reconstructs the release's source and builds the
Bionic and glibc drivers in CI, with a `patched/` variant from `driver-patches/`
(`tools/panvk-probes/prepare-driver.sh`, `build-driver.sh`). Two things stand between that
and a package:

- **The existing `patched/` variant breaks GTK presentation** (`zink: could not create
  swapchain`), from one of its two patches or their combination; never bisected
  ([PANVK-X1S-RESEARCH.md](PANVK-X1S-RESEARCH.md)). Build this port as its own variant on the
  unmodified baseline, as the workgroup experiment did.
- **The recipe has to take a built driver.** Either `mesa-vulkan-icd-panvk-kbase` builds the
  reconstructed tree itself, or it pins a CI artifact by hash as it pins the release now. The
  version-bump handoff needs the same step; do it once.

Builds run in GitHub CI, not on the host or the phone.

## Tests, in order

1. **Extend `tools/panvk-probes/sync-fd.c`.** Today it reads the capability and creates a
   semaphore. Add: submit real work that signals an exportable semaphore, export the fd,
   `poll` it with a deadline and require it to signal; export from an already signalled
   semaphore and accept -1; import a sync file that never signals and require a timeout,
   not a hang; import a signalled one. Run it against JimVulkan's release first: that
   settles whether the kernel half works before any porting.
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
