# Handoff: S20 PanVK presentation with Android hardware buffers

State on 2026-11-25 UTC. Experimental `PANVK_KBASE_DRI3=ahb` builds in CI and passes
private colour/resize checks and two changing quadrant images in a tagged Android window.
Patch 0005 (CI 45577255552, driver `2567638e…`) stops the per-submission cache clean of
AHB swapchain imports. Against same-driver SHM in both run orders, **gears total CPU falls
28%** and **video at an equal 10 FPS output falls 11–17%**, with zero drops in either mode.
At the full 30 FPS source rate AHB shows about 740 of 900 frames against SHM's 400–490,
so its raw total CPU is 9–27% *higher* while CPU per frame shown is about 29% lower.
**The owner chose equal work as the video gate (2026-11-25), so the performance gate
passes**; see [the patch 0005 qualification](#patch-0005-qualification). Colour/resize,
100 restarts, the 300-frame race and a 30-minute soak pass on the new driver, so the
done criteria below are met. **Promoted on 2026-11-25:** `mesa-vulkan-icd-panvk-kbase`
26.3.1-2 and `livecd-desktop` 0.2.0-51 make AHB the S20 desktop session's default and are
installed on the S20; see [promotion](#promotion-to-default). GPU-only AHB import still
fails; CPU-usable allocations pass.
Follows [s20-panvk-raw-dri3.md](s20-panvk-raw-dri3.md).
Shared rules: [README.md](README.md).

## Why

The goal of [s20-panvk-raw-dri3.md](s20-panvk-raw-dri3.md) was to stop the CPU copying every
frame. Raw DRI3 did not do that. It moved the copy from the app into the X server, where it reads
uncached ION memory: X server CPU rose from about 14% to 71% during 1080p video, and total CPU
rose by 23–52% ([results](s20-panvk-raw-dri3-results.json)).

The cause is in Termux:X11 (`termux/termux-x11` at `a00942e`, file
`lorie/src/main/cpp/lorie/InitOutput.c`):

- `loriePixmapFromFds`: a raw fd (`DRM_FORMAT_MOD_LINEAR`, `INVALID` or the private
  `RAW_MMAPPABLE_FD` = 1274, which PanVK sends) is wrapped with
  `LorieBuffer_wrapFileDescriptor`, which `mmap`s it. The server then treats it as CPU memory.
- `lorieExa`: `PrepareSolid`, `PrepareCopy` and `PrepareComposite` are `FalseNoop`, so every
  copy and composite in the X server runs on the CPU (fb), through `loriePrepareAccess` →
  `LorieBuffer_lock`.
- `loriePresentFlip` refuses imported fd buffers unless `TERMUX_X11_FORCE_FLIP=1` ("does not
  work fine with turnip"). So even a fullscreen raw-DRI3 frame is copied, not flipped.
- `lorieDri3Info.fds_from_pixmap` is `FalseNoop`: a compositor cannot get a window's pixmap back
  as a GPU buffer.

Termux:X11 also accepts **AHardwareBuffers**: modifier `AHARDWAREBUFFER_SOCKET_FD` = 1255
(`…_FLIPPED_SOCKET_FD` = 1256 for bottom-up images). The fd is a Unix socket; the server writes
one byte and receives the buffer with `AHardwareBuffer_recvHandleFromUnixSocket`
(`lorieReceiveSocketBuffer`). Allowed formats: `R8G8B8X8_UNORM`, `R8G8B8A8_UNORM`,
`B8G8R8A8_UNORM`. Such a buffer **can** be flipped: the Android activity samples it on the GPU
through `EGL_NATIVE_BUFFER_ANDROID` (`renderer.cpp`), with no CPU copy.
Both the Android EGL sampler and a separately tagged Android activity have now displayed
a rendered AHB correctly. Ordinary private-lorie measurements have no Android window, so
their CPU numbers exclude the activity's sampling cost.

Forcing a **raw-fd** flip still leaves a pixel upload in the activity:
`Renderer::draw` calls `uploadDamagedRows` for `LORIEBUFFER_FD`, which calls
`LorieBuffer_uploadRows` → `glTexSubImage2D` (`buffer.c`). An AHB instead becomes an EGL image
bound to a texture. The forced-flip experiment below measures the X-server copy's cost, not
the entire saving possible with AHB. The private server does not exercise either activity path.

## What AHBs can and cannot save

| Frame | Raw fd today | With AHB |
| --- | --- | --- |
| GNOME Shell's own fullscreen output (root-sized present) | CPU copy into root | flip, no copy (if the flip is accepted) |
| Unredirected fullscreen app (game, fullscreen video) | CPU copy | flip, no copy |
| Windowed app under GNOME Shell | CPU copy into the window pixmap | still a CPU copy: `PrepareCopy` is a no-op and `fds_from_pixmap` is missing |

So the target is GNOME Shell's output and fullscreen apps. Removing the copy for ordinary windows
would need GPU compositing in Termux:X11 (EXA hooks plus `fds_from_pixmap`); that is a separate
and much larger change, out of scope here.

## Where things stand

| What | Where |
| --- | --- |
| Driver | `packages/mesa-vulkan-icd-panvk-kbase`, Zenith `cf70e02`, `combined-ahb`; present-wait patch `tools/panvk-probes/platform-patches/0003-*` (989e419) |
| Path selection | Zenith `src/panfrost/vulkan/panvk_wsi.c` `panvk_wsi_init`: `PANVK_KBASE_DRI3=raw`/`termux` sets `kbase_raw_dri3`, which disables modifiers and sends `RAW_MMAPPABLE_FD`. `PANVK_KBASE_DRI3=ahb` is implemented in patch `0004-wsi-x11-termux-ahb.patch`, colour/resize/race/restarts pass; paired video CPU gate fails |
| WSI image allocation | The new opt-in mode allocates AHBs with usage `0x333`, imports dedicated Vulkan image memory and transports the public AHB handle through modifier 1255. Default and raw modes retain their allocation paths |
| Earlier AHB result | [PANVK-X1S-RESEARCH.md](../PANVK-X1S-RESEARCH.md) records the old metadata failure. It was subsequently fixed for linear RGBA by the `combined-ahb` legacy Mali metadata patch; see [the November 15 qualification](../PANVK-VERSION-BUMP-HANDOFF.md#ahb-focused-investigation-2026-11-15). Do not treat the old failure as the current driver's result |
| Current AHB result | 1920×1080 RGBA with `GPU_COLOR_OUTPUT \| GPU_SAMPLED_IMAGE` fails `vkAllocateMemory` with `VK_ERROR_INVALID_EXTERNAL_HANDLE` (`-1000072003`). Adding `CPU_READ_OFTEN \| CPU_WRITE_OFTEN` passes import, bind, full-image GPU clear/readback and CPU↔GPU pattern checks |
| Socket/Present | Modifier 1255 import logged by the installed private server; 180/180 completion events report `FLIP`, with the expected pixels across the entire root image. Force-flip was not enabled |
| Benchmark | `tests/native/panvk-desktop.py --integrated --benchmark-only`; `--force-flip` sets the flag only on the private server and verifies `/proc/<server>/environ`. Control runs clear an inherited flag. Records CPU per process, gears FPS, mpv drops |

## AHB swapchain measurements

CI [45565008308](https://github.com/cnshing/debian-livecd-termux/actions/runs/45565008308)
builds source commit `49ac244` on `work/s20-ahb-present`, variant `combined-ahb`, Android ABI.
Use `out/patched/libvulkan_panfrost.so`, SHA-256
`77185ee4407ecd599c4c04851d963f5adfd8fa89502574f021f42e1b7be6f3f2`,
Mesa content tree `bcff3960b99fba38bf0e663f941cbf923ba1f057`.
It is staged only in `~/s20-ahb-present/driver-ahb/`.

Run order: SHM, AHB, AHB, SHM. All runs use this same ICD, private 1920×1080 lorie,
fake refresh 60/s, five-second warmups and 30-second measurement intervals. The video is the
same software-decoded 1080p30 fixture, audio off; `MUTTER_SYNC` and force-flip are unset.
Percentages are of one CPU core. Totals include Shell, X server and application; Android
activity CPU is excluded. Every run completes with unchanged shared state, the same fixture
hash, and wall/monotonic agreement within six microseconds.

| Pair | Mode | Workload | Shell CPU | X server CPU | App CPU | Total CPU | mpv drops |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | SHM | gears | 92.7% | 21.7% | 38.3% | 152.7% | — |
| 1 | AHB | gears | 83.7% | 17.0% | 23.9% | 124.6% | — |
| 1 | SHM | video | 44.2% | 15.6% | 89.2% | 149.0% | 422 |
| 1 | AHB | video | 43.4% | 14.3% | 101.4% | 159.0% | 349 |
| 2 | AHB | gears | 83.8% | 16.7% | 22.8% | 123.3% | — |
| 2 | SHM | gears | 96.4% | 22.4% | 41.5% | 160.3% | — |
| 2 | AHB | video | 42.9% | 14.2% | 101.6% | 158.6% | 355 |
| 2 | SHM | video | 43.8% | 15.5% | 92.7% | 152.0% | 423 |

Gears remains about 60 FPS in both modes (all reported intervals 58.8–60.5 FPS).
Video has zero decoder drops in every run. AHB reduces presentation drops by 16–17%, but
mpv CPU rises enough to outweigh the modest server saving. This is a repeatable tradeoff,
not acceptance under this handoff's total-CPU criterion. Benchmark captures were opened and
show the expected gears and video fixture. The numbers do not establish end-to-end power
savings or include the Android activity; thermal-zone readings remain unavailable.

### Why video CPU rises: cache-clean investigation

Ten focused video runs use the same CI ICD and fixture. The added harness options
`--benchmark-video-only --benchmark-video-profile` record mpv's render passes, GPU context
and per-thread user/system CPU at the measurement boundaries. These fresh-session video-only
runs have a different preceding warmup from the idle/gears/video sequence above; compare
within each experiment, rather than mixing their totals.

The ordinary 30 FPS source reproduces the component change. SHM spends 15.2% of one core in
mpv's WSI present thread and 6.4% in kernel time in `mpv:zfq0`; AHB spends 0.6% in the present
thread but **30.1% in submission thread kernel time**. Decoding threads total 41.6% and 43.7%,
respectively. Both use `gpu` / `x11egl`, map the private PanVK driver with a Mali FD, and report
the same render-pass sequence. This does not indicate a software rendering fallback.

The pinned source explains the costly path:

- `src/panfrost/lib/kmod/kbase_kmod.c:kbase_kmod_import_dmabuf()` places noncoherent,
  CPU-mapped imports on `nc_bos` by default on v9. The backend makes a CPU mapping even for
  allocations the Vulkan application never maps for CPU access.
- `src/panfrost/vulkan/jm/panvk_vX_gpu_queue.c:panvk_per_arch(gpu_queue_submit)` calls
  `kbase_kmod_jm_clean_imports()` for each submission containing command buffers.
- That function walks **every listed import** and issues `DMA_BUF_IOCTL_SYNC` with
  `END | WRITE` for the whole buffer, independently of whether this submission uses that
  image or whether its contents were CPU-written. AHB swapchain imports add large buffers
  to that work. The existing `PANVK_KBASE_IMPORT_SYNC=0` diagnostic prevents their listing.

An experiment with the same output rate adds `--benchmark-video-fps 10`, which applies `--vf=fps=10`
while decoding the same 30 FPS input. All seven filtered runs report 10 FPS and **zero VO or
decoder drops** throughout the measured intervals. Two default runs per mode and two diagnostic
AHB runs separate the cache-clean cost from the cost of displaying more frames:

| Mode / cache-clean policy | mpv CPU | Submission thread kernel CPU | WSI present thread CPU | Total CPU |
| --- | ---: | ---: | ---: | ---: |
| SHM, default | 76.9–78.7% | 5.2–5.3% | 9.4–9.5% | 122.0–124.4% |
| AHB, default | 87.2–87.7% | 18.3–18.4% | 0.6% | 122.4–122.8% |
| AHB, cache-clean diagnostic off | 76.2–76.8% | 5.6–6.0% | 0.6% | 110.0–110.8% |
| SHM, diagnostic off control | 77.1% | 5.3% | 9.3% | 122.0% |

The AHB repeats reduce total CPU by 9.5–10.4% when that cache clean is disabled, at the same
output rate and with unchanged drop counts. SHM's control is essentially unchanged. This
isolates the imported-buffer cleaning as a substantial avoidable cost in this workload.

There is also an effect from the workload rate. On the ordinary source, the diagnostic AHB run cuts
VO drops from 335 to 151 in 30 seconds and mpv CPU from 100.7% to 87.6%. Shell/server CPU
then rises as more updates get through, taking total CPU from 160.2% to 167.4%. Raw CPU
percentages alone therefore conflate per-frame cost with how much video is actually presented;
retain both drop counters and matched-rate comparisons in subsequent qualification.

The diagnostic run passes four exact changing-colour captures and rejects the stale-phase
negative control. A separate `cache-off-interop-1` passes public CPU→GPU and GPU→CPU patterns,
Android EGL sampling, 180/180 flips and exact root pixels. Captures were opened and inspected.
All ten video runs and the interop run preserve shared state. The flag is confined to private
test processes; no driver code, installed environment or default was changed.

A production change must retain coherency for imports written through Vulkan CPU mappings.
The focused fix is to distinguish those mappings from AHB swapchain memory used only by the
GPU in this process, and maintain the external CPU-access/ownership contract. The global
switch also removes the guard for genuinely CPU-written imports, so it remains a diagnostic.
Cache coherency and GPU completion are separate requirements in the
[kernel dma-buf API](https://www.kernel.org/doc/html/latest/driver-api/dma-buf.html#cpu-access-to-dma-buffer-objects);
this test retains patch 0003's render-completion fence wait and Present idle fences.

Evidence runs are `video-profile-{shm,ahb}-1`, `video-10fps-{shm,ahb}-{1,2}`,
`video-nosync-ahb-1`, `video-10fps-nosync-ahb-{1,2}` and
`video-10fps-nosync-shm-1` under the existing private evidence tree. `nosync` in these names
means the import-cache diagnostic only. mpv's
[VO pass timings](https://mpv.io/manual/stable/#property-list) describe GPU passes; the CPU
attribution above comes from `/proc/<pid>/task/<tid>/stat`, matching thread start times.
Android `simpleperf` was blocked by `security.perf_harden=1`; that setting was preserved.

`ahb-colour-smoke` passes four alternating-colour captures with maximum channel error zero,
including odd-sized window resizes and 1920×1080 fullscreen transitions. Its stale-phase
negative control is rejected. Shell and GTK map the requested ICD and retain Mali FDs;
modifier-1255 imports are logged, force-flip is absent and isolation passes. Shell, Files,
Settings and fullscreen captures were opened and inspected.

`android-window-gtk-1` loads the new private ICD in a GTK GLArea using Zink, on a separately
tagged Android activity with its actual 608×783 framebuffer. The physical red/green/blue/white
quadrants match, then the top-left quadrant changes to yellow and matches again. All 781,184
checked interior pixels across the two phases equal their ICC-transformed expected RGB
values exactly; a 16-pixel inset excludes rounded corners, the quadrant boundary and cursor.
Both crops were opened and inspected. This verifies channel order, orientation and changed
contents through the new WSI into Android's sampler, at this window size. The original Settings
task returned, shared state was unchanged and full-screen images were deleted after cropping.
The headless 1080p checks and this small attached-window check have distinct scopes.

## Raw forced-flip comparison and standalone AHB evidence

The raw experiments below use the same Bionic `combined-ahb` build with present-wait used for the earlier raw
qualification: SHA-256 `b40b4d712a33cf6f5962eee1e1fa60d97db7adb9596521e52949f4440dd189be`.
Nothing was installed. Tests use a private 1920×1080 lorie with `-fakescreenfps 60`, five-second
warmups, 30-second measurement intervals and the earlier local 1080p30 fixture with software
decode and no audio. `MUTTER_SYNC` is unset for benchmarks.

The raw run order was control, force, force, control. Percentages are of one CPU core;
total is shell + X server + application. These are private-server measurements, without the
Android activity's texture upload or sampling cost.

| Pair | Raw route | Workload | Shell CPU | X server CPU | App CPU | Total CPU |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 1 | control | gears | 93.0% | 71.1% | 10.7% | 174.8% |
| 1 | force flip | gears | 94.2% | 62.7% | 10.1% | 167.0% |
| 1 | control | video | 47.2% | 67.7% | 75.8% | 190.7% |
| 1 | force flip | video | 53.6% | 39.2% | 74.6% | 167.4% |
| 2 | force flip | gears | 69.3% | 66.3% | 15.5% | 151.2% |
| 2 | control | gears | 68.8% | 66.6% | 12.2% | 147.7% |
| 2 | force flip | video | 59.3% | 40.2% | 87.5% | 187.1% |
| 2 | control | video | 55.9% | 64.8% | 83.9% | 204.5% |

Video X-server CPU falls by 38–42%, and total video CPU by 9–12%. Gears does not show a
consistent gain. The first same-driver SHM control used 43.4% shell + 15.5% server + 89.8%
mpv = 148.7% total during video, below either forced raw run. This justifies testing AHB;
it does not qualify forced raw DRI3 as a replacement for SHM. Thermal-zone readings remain
unavailable, and run-to-run variation remains substantial.

The new [AHB probe](../../../tools/panvk-probes/ahb-import.py) tests two separate allocations.
The GPU-only usage `0x300` reports stride 1920 and size 8,491,008 bytes, but fails Vulkan
memory import. Usage `0x333` adds CPU read/write and reports stride 1920, size 8,359,936 bytes,
and one public CPU plane with pixel stride 4 and row stride 7,680. With the latter:

- CPU-written RGBA quadrants match every pixel of a GPU image-to-buffer readback.
- A GPU clear to opaque green matches every pixel of a second GPU readback and of Android's
  public CPU mapping. The two patterns differ, so stale pre-clear contents cannot pass.
- Dedicated import and binding use the driver's queried memory properties. The probe does not
  infer a dma-buf layout from `AHardwareBuffer_describe` or read a private native handle.

The existing CI-built 64×64 `ahb_render` triangle probe also passes with the same driver in a
clean library environment. This matches the earlier `combined-ahb` qualification; it is not a
new metadata fix. The GPU-only 1080p failure remains distinct from the passing CPU-usable case.

[The private presentation harness](../../../tests/native/panvk-ahb-present.py) runs the same
GPU clear and sends the passing AHB through [the socket client](../../../tools/panvk-probes/ahb-x11.py).
`ahb-socket-1` logs `DRI3: imported AHardwareBuffer, modifier 1255, 1920x1080 stride 1920`.
Its 180 Present requests, paced at 60/s over 3.000 seconds, all complete in mode 1 (`FLIP`).
The entire root image is green afterward and isolation passes. Re-presenting one completed,
unchanging buffer tests transport and flip acceptance, not swapchain reuse or render/present races.
No Android activity was attached to this run.

`ahb-socket-egl-2` repeats the RGBA test with the Android EGL sampler: all 180 flips,
full CPU↔GPU pattern checks and every sampled EGL pixel pass. Server CPU is 4.00% of one
core during the three-second paced interval. `bgra-red-socket-egl` checks opaque red with
BGRA storage: 180 flips, exact root and Android EGL pixels, 3.67% server CPU. Both preserve
shared state. The BGRA public CPU-plane API reports zero pixel/row strides, and
`AHardwareBuffer_lockAndGetInfo` returns `-38`; the strict probe rejects those mappings.
`--no-cpu-mapping` explicitly selects GPU staging, EGL and X11 checks for BGRA. It does not
claim a CPU-plane round trip.

`android-window-red-3` uses a separately tagged Termux:X11 activity and its actual 608×783
framebuffer, rather than attaching to the live `:0`. It completes 600/600 flips in 10.001 seconds
with 4.30% server CPU, exact root pixels and exact offscreen EGL pixels. A physical 720×1600
capture was taken only after the tagged activity's focus was verified. Its embedded ICC profile
uses sRGB transfer with Display-P3 primaries: LittleCMS transforms sRGB red `(255,0,0)` to
encoded `(234,51,35)`, matching 99.89% of the owned 608×782 window crop exactly. Rounded
corners and the X cursor account for the remainder. The crop was opened and inspected; the
full-screen image was deleted. The tagged activity closed and the original Settings task
returned, with X0, shared daemon state and desktop status unchanged. This proves the static
AHB sampler route at the attached window's size; it does not qualify a dynamic 1080p swapchain.

Evidence is on the S20 under `~/s20-ahb-present/` and retrieved under the host's ignored
`temp/s20-ahb-present/evidence/s20-ahb-present/`. All five completed benchmarks report
completion and unchanged shared state. Wall and monotonic intervals agree within 10 microseconds;
the fixture SHA-256 is `d574c3cbf096854f82f8678c2aeb23c5a4d4c12c30ef8a06214e3bbdd651519c`
in every run. The raw video drop counts are 118 and 91 (control), 139 and 146 (forced);
SHM reports 413, with zero decoder drops in every case. Captures of both workloads were opened
and inspected. A second old-driver SHM run did not start.

`force-correctness-1` passes four full quadrant captures with maximum channel error zero,
rejects a stale-phase negative control and records 300 valid race frames with zero split frames
(142 red, 158 blue). First/middle/last race images were opened and inspected. This bounded
result applies to forced raw presentation, separately from the new AHB swapchain.

The [results summary](s20-panvk-ahb-present-results.json) records the measurements and gates.
Final cleanup found no owned processes and only X0. The test wake lock was released, the
managed desktop remained stopped as found, and the original termux-va and sshd processes
were preserved. The S20 claim is available again.
The first AHB WSI CI attempt
[45563502941](https://github.com/cnshing/debian-livecd-termux/actions/runs/45563502941)
compiled the source but failed its final link because Mesa's build-only Android stub lacked
`AHardwareBuffer_sendHandleToUnixSocket`. The stub was added in `49ac244`; the retry above
passed. Builds use the workspace `.env` GitHub token without printing it.

## Reproduce the probes

Run from plain Termux with the repository's `tests/` and `tools/` directory layout preserved.
The private-lorie wrapper and dex must be available under `tests/browsers/private-lorie/`.
Use fresh output paths, and claim the phone first.

```sh
env -u LD_PRELOAD -u LD_LIBRARY_PATH python tools/panvk-probes/ahb-import.py \
  --driver "$HOME/s20-raw-dri3/driver-wait/libvulkan_panfrost.so" \
  --out "$HOME/s20-ahb-present/import-new.json"
python tests/native/panvk-ahb-present.py \
  --driver "$HOME/s20-raw-dri3/driver-wait/libvulkan_panfrost.so" \
  --out "$HOME/s20-ahb-present/socket-new"
python tests/native/panvk-desktop.py --integrated --mode ahb \
  --driver "$HOME/s20-ahb-present/driver-ahb/libvulkan_panfrost.so" \
  --screen-size 1920x1080 --screen-fps 60 --present-mode fifo --cycles 20 \
  --out "$HOME/s20-ahb-present/ahb-colour-new"
python tests/native/panvk-desktop.py --integrated --mode raw --force-flip \
  --driver "$HOME/s20-raw-dri3/driver-wait/libvulkan_panfrost.so" \
  --screen-size 1920x1080 --screen-fps 60 --benchmark-seconds 30 --benchmark-only \
  --benchmark-video "$HOME/s20-raw-dri3/video-long-1080p30.mp4" \
  --out "$HOME/s20-ahb-present/force-new"
```

For the focused video experiment, use fresh output paths for each mode and policy:

```sh
python tests/native/panvk-desktop.py --integrated --mode ahb \
  --driver "$HOME/s20-ahb-present/driver-ahb/libvulkan_panfrost.so" \
  --screen-size 1920x1080 --screen-fps 60 --benchmark-seconds 30 --benchmark-only \
  --benchmark-video-only --benchmark-video-profile --benchmark-video-fps 10 \
  --benchmark-video "$HOME/s20-raw-dri3/video-long-1080p30.mp4" \
  --out "$HOME/s20-ahb-present/video-profile-new"
```

Repeat with `--mode shm`. The diagnostic comparison prefixes just this test command with
`PANVK_KBASE_IMPORT_SYNC=0`; it leaves the global environment and render/idle fence waits
unchanged. Omit `--benchmark-video-fps` to measure the original output workload.

The standalone probe exits zero if at least one usage passes all requested checks; its JSON
retains the GPU-only failure separately. The private presentation harness additionally requires
the server's AHB import log, `FLIP` completions, exact root pixels and unchanged shared state.
Its optional Android EGL check samples through `EGL_NATIVE_BUFFER_ANDROID` in a pbuffer; it
does not open an Android window or qualify scanout.

## Implementation and remaining gates

Patch `0005-wsi-ahb-gpu-only-import.patch` implements the scoped cache-clean change;
CI [45577255552](https://github.com/cnshing/debian-livecd-termux/actions/runs/45577255552)
builds source commit `df753f7`; its runtime results are in
[the patch 0005 qualification](#patch-0005-qualification).
The AHB WSI allocator marks its internal memory as never CPU-mapped by Vulkan. PanVK forwards
that marker through AHB→fd import and requests `PAN_KMOD_BO_FLAG_NO_MMAP` only on kbase
when the selected memory type is not HOST_VISIBLE. kbase keeps the GPU VA reservation but
omits its separate CPU dma-buf alias. Its existing `cpu_ptr` condition consequently excludes
these buffers from the noncoherent import-clean list. All ordinary imports and host-visible
memory allocations keep the earlier path. The global cache-clean option remains enabled;
render/idle fence handling is unchanged. The AHB allocation still uses CPU-capable `0x333`,
so the `0x300` image-import failure remains a separate issue.

The new `imported-host-coherent.py` regression probe imports a public AHB BLOB into a
HOST_VISIBLE|HOST_COHERENT VkBuffer allocation. It keeps the Vulkan mapping alive across
eight 4 MiB writes, uses no explicit flush calls, copies on the GPU and verifies every byte.
The earlier ICD passes all eight iterations. Its deliberate `PANVK_KBASE_IMPORT_SYNC=0`
control fails GPU readback, demonstrating that the probe catches lost CPU-write coherence.

### Patch 0005 qualification

CI 45577255552 selects `0005-wsi-ahb-gpu-only-import.patch` (listed in `PATCHES.txt`).
Use its `out/patched/libvulkan_panfrost.so`, SHA-256
`2567638e3600c5e1495a20abe40ff7843e04f2fb7956fb99f665ae87228b9e54`, staged only in
`~/s20-ahb-present/driver-ahb-0005/`. Every run below uses this one ICD for both SHM and
AHB, the same private 1920×1080 lorie at fake 60/s, the same fixture
(`d574c3cb…`), five-second warmups and 30-second intervals; every process except the X server
maps the staged ICD, isolation passes in all runs, and wall/monotonic intervals agree within
ten microseconds. Android activity CPU is excluded, as before.

Probes: `imported-host-coherent.py` passes all eight persistent HOST_COHERENT write/readback
iterations, and its `PANVK_KBASE_IMPORT_SYNC=0` control still fails, so ordinary CPU-written
imports keep their cache clean. `ahb-import.py` passes the CPU-usable `0x333` checks; `0x300`
still fails as before.

Full benchmark, run order SHM, AHB, AHB, SHM (percent of one core; total = Shell + X server +
app):

| Run | Mode | Gears total | Video (30 FPS source) total | VO drops / 900 | CPU ms per frame shown |
| --- | --- | ---: | ---: | ---: | ---: |
| `q0005-bench-shm-1` | SHM | 160.5% | 154.7% | 418 | 95.9 |
| `q0005-bench-ahb-1` | AHB | 114.9% | 168.1% | 163 | 68.4 |
| `q0005-bench-ahb-2` | AHB | 114.9% | 168.5% | 163 | 68.7 |
| `q0005-bench-shm-2` | SHM | 160.4% | 132.3% | 497 | 98.5 |

Gears reports 59.3–60.8 FPS in every interval. Decoder drops are zero throughout. Per-frame
CPU assumes each undropped source frame was shown once (30 × 30 s − VO drops).
At source rate AHB's Shell (58.5–59.2% vs 36.4–44.9%) and server (20.8–21.0% vs
13.9–15.8%) rise because more frames reach them; mpv stays within SHM's range
(88.5–88.6% vs 81.9–94.0%) while presenting more frames. One profiled pair at source rate repeats this: AHB 167.6% with 158 drops,
SHM 152.7% with 413 drops, and mpv's submission thread kernel time 10.1% vs 6.5%.

Equal-output video (`--benchmark-video-fps 10`, all runs report 10 FPS and zero VO/decoder
drops), run order SHM, AHB, AHB, SHM, plus the first single AHB check:

| Run | Mode | Shell | X server | mpv | Total | mpv submit thread kernel | WSI present thread |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `q0005-v10-shm-1` | SHM | 33.2% | 11.2% | 72.2% | 116.6% | 5.5% | 8.4% |
| `q0005-v10-ahb-2` | AHB | 21.6% | 11.9% | 68.8% | 102.3% | 5.7% | 0.6% |
| `q0005-v10-ahb-3` | AHB | 21.2% | 12.1% | 70.8% | 104.1% | 5.9% | 0.5% |
| `q0005-v10-shm-2` | SHM | 33.8% | 11.6% | 78.3% | 123.8% | 5.2% | 9.7% |
| `q0005-video-10fps-ahb-1` | AHB | 21.4% | 11.9% | 75.3% | 108.6% | 5.4% | 0.5% |

The old AHB driver spent 18.3–18.4% in that submission thread at this rate; patch 0005 brings
it to SHM's level, and total CPU to or below the earlier `PANVK_KBASE_IMPORT_SYNC=0`
diagnostic (110.0–110.8%) without disabling the clean for any CPU-written import.

**Gate reading.** Gears passes clearly in both orders. Equal-work video passes in both orders.
Source-rate video fails on raw totals because AHB does about 50% more presentation work; per
frame shown it is cheaper. The handoff's criterion was written before this tradeoff was known.
On 2026-11-25 the owner chose CPU for equal work as the gate, so AHB passes; the source-rate
totals stay recorded as the cost of showing more frames.

`q0005-correctness-1` repeats the correctness suite on this ICD: 20 colour/resize cycles,
all 40 captures maximum channel error zero, stale-phase control rejected
(`check-panvk-desktop.py`); Nautilus and Settings windows found; Shell and GTK map the ICD
with Mali FDs and the same Shell survives; 100/100 vkcube starts return zero; the
300-frame race contains 149 solid red and 151 solid blue frames, zero split and zero invalid.
First/middle/last race frames, a resized GTK capture, the Shell capture and the benchmark
gears/video captures were opened and inspected.

`q0005-soak-30m` runs the 20-cycle colour suite (40 captures, maximum error zero, stale
control rejected), then vkcube FIFO and glxgears together for 1800.0 seconds on the AHB path.
`check-panvk-soak.py` passes: 60 samples, the same Shell, vkcube and gears processes
throughout, gears 57.9–60.4 FPS, MemAvailable 5.26–5.36 GB, no stall, isolation preserved.
The first, middle and last soak captures were opened: the cube and gears keep moving, with no
corruption. This is a stability check, not a benchmark.

Evidence: `~/s20-ahb-present/q0005-*` on the phone, retrieved to the ignored
`temp/s20-ahb-present/q0005/` in this worktree.

Patch `0004-wsi-x11-termux-ahb.patch` adds Android-only `PANVK_KBASE_DRI3=ahb` for kbase.
It advertises BGRA UNORM/SRGB X11 formats, allocates CPU-usable AHBs, validates the public
descriptor and queried Vulkan memory properties, and imports dedicated image memory. It does
not infer a private layout from the descriptor or wrap an existing dma-buf. The existing
`combined-ahb` patch still validates the legacy Mali allocation metadata and rejects unknown
or compressed layouts. GPU-only usage remains a failing control.

The new X11 path sends a socket fd with modifier 1255, waits for the server's one-byte request,
then sends the AHB using the public Android API. Socket reads/writes have three-second timeouts;
XCB import errors propagate to swapchain creation. AHB image references are released at image
destruction. Present retains patch 0003's CPU wait for render completion because the transport
carries no render fence; Present idle fences still govern reuse. No force-flip flag is needed.
Non-Android builds reject this opt-in mode. Default transport and package pins are unchanged.

`ahb-correctness-1` passes 20 colour/resize cycles: all 40 captures have maximum channel
error zero, and a stale-phase negative control is rejected. All 100 vkcube starts/teardowns
return zero, with the same compositor surviving. The 300-frame 1080p race recording contains
149 solid red frames and 151 solid blue frames, zero invalid frames and zero split frames.
First/middle/last recording images were opened and inspected. Isolation passes. This is a
bounded check, not a long race or soak; patch 0005's repeat and 30-minute soak are above.
The earlier raw soak and static single-buffer flips do not substitute for AHB qualification.

Next work, in order:

1. Done: patch 0005 scopes the clean (CI 45577255552) and is qualified above.
2. Done: the owner chose equal-work CPU as the video gate; AHB passes it.
3. Done: promoted to default on the S20 (below).
4. Still open: measure the attached Android activity's sampling cost with the live desktop,
   and longer AHB race/menu checks. The Note10+ port (Turnip, `TU_KGSL_DRI3=ahb`) is in
   [note10-turnip-ahb-present.md](note10-turnip-ahb-present.md).

### Promotion to default

The owner asked for the promotion on 2026-11-25. CI
[45600751232](https://github.com/cnshing/debian-livecd-termux/actions/runs/45600751232)
builds both ABIs from `feat/s20-ahb-present` with the seventeen-patch `combined-ahb` series;
both report Mesa tree `7c6284194b4a6a5df1575848aeeb7ec771fc82f7`, the same tree as the
qualified CI 45577255552 build. The prerelease
[panvk-desktop-26.3.1-2](https://github.com/cnshing/debian-livecd-termux/releases/tag/panvk-desktop-26.3.1-2)
carries both drivers (Bionic `0d83ff81…`, glibc `0251cd64…`), the prepared source, provenance,
and the packages built by CI
[45603195349](https://github.com/cnshing/debian-livecd-termux/actions/runs/45603195349).
`install.lock.json` pins them for the installer.

`livecd-desktop` 0.2.0-51 (`src/native/graphics.py`) treats the new tree as a qualified
desktop stack, keeping the G77 workgroup defaults, and `session_presentation` sets
`PANVK_KBASE_DRI3=ahb` only for the desktop session on Termux:X11 (`desktop.environment` and
renderer-specific terminals). `use_panvk` clears the variable, so browsers keep MIT-SHM and
the glibc build, which refuses the mode, never sees it. Other X servers such as Xvfb never
get it either; that matters because the AHB WSI has no fallback when the server lacks the
socket import. `"panvk_presentation": "shm"` in `~/.local/lib/livecd/config.json` opts out.
Termux:X11 keeps `-legacy-drawing`: its renderer still samples a flipped AHB through EGL and
uploads only an fd-backed root (`renderer.cpp`).

Installed on the S20 through the installer helper's local PanVK repository: `android-webgpu`
0.1.0-2 (new dependency of controller 51, from the v0.12.0 repository tarball, checksum
verified), then `mesa-vulkan-icd-panvk-kbase` 26.3.1-2 and `livecd-desktop` 0.2.0-51 from the
release with pinned checksums. No other package changed. The installed controller reports the
AHB tree, `PANVK_KBASE_DRI3=ahb` and `PANVK_G77_LWG=1`/`NESTED=1` for the session, and no AHB
variable for a glibc process; installed driver hashes match the release.

Private checks of the installed stack (new harness mode `--mode installed` keeps the
controller's own choice and records it; every AHB run recorded `ahb`; isolation passed in all):

| Check | SHM | Installed AHB |
| --- | ---: | ---: |
| Gears total CPU | 160.1%, 216.2% (outlier) | 114.9%, 114.9% |
| Video at 10 FPS total CPU, zero drops | 123.9%, 124.2% | 110.4%, 110.2% |
| Video at 30 FPS total CPU (VO drops) | 149.9% (424), 149.7% (421) | 165.5% (151), 161.0% (161) |

`inst-correctness-2`: 40 captures maximum error zero, stale control rejected, Nautilus and
Settings found, 50/50 restarts with the same Shell, 300 race frames (146 red, 154 blue),
zero split or invalid. GTK, Nautilus, video and race images were opened. The live desktop
was stopped before the install and was not started; it uses AHB on its next start.

## Gotchas

- `graphics.apply_renderer` strips `PANVK_KBASE_DRI3`, `VK_DRIVER_FILES` and `VK_ICD_FILENAMES`;
  set overrides after it and check `/proc/<pid>/environ` and the mapped `libvulkan_panfrost.so`.
- Flips need a root-sized pixmap (`pvfb->root.width/height`). A resolution change or a non-fullscreen
  shell frame falls back to the copy.
- Use the platform `/system/lib64/libnativewindow.so` for public AHB functions. On this phone
  the library resolved by `libandroid.so` lacks `AHardwareBuffer_lockPlanes`; the platform
  library exposes it. Do not add `$PREFIX/lib` to `LD_LIBRARY_PATH`: it can shadow Android
  dependencies needed by the driver and gralloc.
- Video decode is separate. The benchmark decodes in software on purpose. Hardware decode goes
  through MediaCodec; making decoded frames reach the screen without a copy is the zero-copy work,
  not this page.
- Never drive the live `:0`; use a private lorie. Claim the phone in `temp/PHONE-STATUS`.

## What counts as done

- With AHB presentation, total CPU (shell + X server + app) during the 1080p video and gears
  phases is clearly below MIT-SHM, in both run orders. Video is compared at equal output
  (owner decision, 2026-11-25). **Met with patch 0005.**
- No split or cut frames in the race tests; the soak completes. **Met with patch 0005.**
- Recordings opened and looked at. **Met.**
