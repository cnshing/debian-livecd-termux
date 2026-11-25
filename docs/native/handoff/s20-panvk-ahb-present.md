# Handoff: S20 PanVK presentation with Android hardware buffers

State on 2026-11-25 UTC. Experimental `PANVK_KBASE_DRI3=ahb` builds in CI and passes
private colour/resize checks and two changing quadrant images in a tagged Android window.
**The performance gate fails:** gears CPU falls 18–23%, but video CPU rises 4–7% against
same-driver SHM in both run orders. Keep SHM as default; nothing is installed or promoted.
GPU-only AHB import still fails; CPU-usable allocations pass.
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

The standalone probe exits zero if at least one usage passes all requested checks; its JSON
retains the GPU-only failure separately. The private presentation harness additionally requires
the server's AHB import log, `FLIP` completions, exact root pixels and unchanged shared state.
Its optional Android EGL check samples through `EGL_NATIVE_BUFFER_ANDROID` in a pbuffer; it
does not open an Android window or qualify scanout.

## Implementation and remaining gates

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
bounded check, not a long race or soak. The performance gate fails; no 30-minute AHB soak
has been run.
The earlier raw soak and static single-buffer flips do not substitute for AHB qualification.

Next work, in order:

1. Profile mpv's application CPU with the same fixture and comparable rendered-frame counts.
   Determine whether extra work from fewer drops explains the increase or whether AHB/linear
   swapchain handling adds avoidable work. Separate the remaining window-pixmap CPU copy from
   Shell's root flip; the current server has no GPU window compositing.
2. Repeat paired total-CPU, FPS and drop measurements after any focused change. Keep the
   failing result and same-driver SHM controls. Do not promote on X-server CPU alone.
3. Once total CPU passes both workloads in both orders, complete longer AHB race/menu checks
   and a 30-minute soak, inspect recordings and separately measure the attached activity.

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
  phases is clearly below MIT-SHM, in both run orders.
- No split or cut frames in the race tests; the soak completes.
- Recordings opened and looked at.
