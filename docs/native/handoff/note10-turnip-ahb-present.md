# Handoff: Note10+ Turnip presentation with Android hardware buffers

State on 2026-11-25 UTC. **Steps 1–5 done on the Note10+; the done criteria are met. Promoted
at the owner's request: the default install now presents the Adreno desktop session through
AHBs** (`mesa-vulkan-icd-freedreno-android` 26.3.1-1 and `livecd-desktop` 0.2.0-52; see
Promotion below; not yet installed on the phone or rechecked with `--mode installed`). The Bionic Turnip presents over **raw DRI3** today,
and Termux:X11 copies every frame on the CPU (X server 61–65% of one core). A CI-built
Android+X11 Turnip from the S20's Zenith tree with the shared AHB WSI and an opt-in
`TU_KGSL_DRI3=ahb` presents through AHBs instead, and the server **flips every Shell frame**
(counted with Present events). Against the same driver on raw DRI3, in both run orders and
repeated on the final build: **gears total CPU −13% at twice the frame rate (59 vs 30 FPS),
30 FPS video −16%, equal-output 10 FPS video −15 to −19%**, zero drops everywhere. Race
(2 × 300 frames, zero split), 50 restarts and a 30-minute soak pass; 199 of 200 AHB
colour/resize captures are exact (one late fullscreen frame, not reproduced, below).
The S20 work it builds on: [s20-panvk-ahb-present.md](s20-panvk-ahb-present.md).
Shared rules: [README.md](README.md).

## Why

On the S20, presenting Vulkan swapchain images to Termux:X11 as Android hardware buffers (AHBs)
instead of MIT-SHM readback cut total CPU by 28% for gears and by 11–17% for video at equal
output, in both run orders, with correctness, race and soak checks passing. It is the S20
desktop's default from `mesa-vulkan-icd-panvk-kbase` 26.3.1-2 and `livecd-desktop` 0.2.0-51.

The saving comes from Termux:X11 (`termux/termux-x11` at `a00942e`,
`lorie/src/main/cpp/lorie/InitOutput.c` and `renderer.cpp`):

- An AHB arrives through modifier 1255 (`AHARDWAREBUFFER_SOCKET_FD`) and can be **flipped**:
  the Android activity samples it on the GPU through `EGL_NATIVE_BUFFER_ANDROID`, no CPU copy.
- A raw dma-buf (`DRM_FORMAT_MOD_LINEAR`/`INVALID`) is `mmap`ed and treated as CPU memory.
  `loriePresentFlip` **refuses to flip it** unless `TERMUX_X11_FORCE_FLIP=1`, with the comment
  "For some reason it does not work fine with turnip", so every frame is copied by the CPU.
- MIT-SHM readback copies on the application side instead (what the S20 replaced).

The Note10+ uses the raw fd path (below); its copy costs the X server 61–65% of one core.

## How the Note10+ presents today: raw DRI3

The Note10+ (SM-N975U1, Snapdragon 855, Adreno 640, Android 11, kernel 4.14) has two Turnips:

| Turnip | Used by | Source | Present path |
| --- | --- | --- | --- |
| Bionic, Termux `mesa-vulkan-icd-freedreno` 26.2.6-108, staged by `prebuilt/turnip/gpu-setup.py` into `~/.local/opt/livecd-native/gpu` | mutter (Zink/Kopper), GTK, Chromium, Firefox | `packages/mesa`, `-Dplatforms=x11,wayland`, `-Dfreedreno-kmds=msm,kgsl` | **raw DRI3**: linear dma-buf, modifier 0, mapped and copied by the X server |
| glibc, `android-vaapi-glibc` (lfdevs Mesa) | Chrome | `packages/android-vaapi-glibc` | DRI3 with shared dma-bufs; present waits for the fence since revision 14 ([note10-chrome-typing.md](note10-chrome-typing.md)) |

Settled on the phone (runs `path-default`, `path-sw`): the private server logs
`DRI3: imported raw fd, modifier 0, 1920x1080 stride 7680` for every swapchain image of the
Shell and of gears, and each holds three exported dma-bufs. The `MESA_VK_WSI_DEBUG=sw` control
logs no import and holds no dma-buf. Why: Termux:X11's DRI3 has no `open` hook, so
`wsi_dri3_open` returns −1 and `wsi_x11_check_dri3_compatible` treats the server as the same GPU;
Turnip then renders straight into linear exportable images. The earlier "no DRI3 on KGSL"
reading in [note10-gpu-rectangles.md](note10-gpu-rectangles.md) was wrong about the transport;
its fix (the CPU fence wait, `packages/mesa` 0028) is exactly what this path needs.
Termux:X11 runs **without** `-legacy-drawing` on Turnip, so its root is AHB-backed and the
server's copy goes from the uncached dma-buf into that root.

## Step 1: baseline (installed Turnip 26.2.6-108)

Private lorie 1920×1080 at fake 60/s, five-second warmups, 30-second intervals, the S20's
1080p30 fixture (`d574c3cb…`) in software decode without audio, `$PREFIX/bin/mpv`. Percent of
one core; total = Shell + X server + application; Android activity excluded. Run order raw,
SHM, SHM, raw; every run kept isolation.

| Path | Workload | Shell | X server | App | Total | Output |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| raw DRI3 (default) | gears | 79.8–80.0% | 65.1% | 9.6% | 154.6–154.7% | 45–49 FPS |
| raw DRI3 | video 30 FPS | 54.9–61.1% | 61.3–64.0% | 29.2–30.0% | 145.3–155.2% | 0 drops |
| raw DRI3 | video at 10 FPS | 23.4–24.2% | 36.0–37.4% | 23.0–23.2% | 83.2–84.0% | 0 drops |
| SHM (`MESA_VK_WSI_DEBUG=sw`) | gears | 74.5–79.0% | 71.8–74.0% | 50.7–56.4% | 196.9–209.4% | 75–83 FPS |
| SHM | video 30 FPS | 61.6–62.1% | 61.8–61.9% | 45.2–46.2% | 168.6–170.1% | 0 drops |
| SHM | video at 10 FPS | 28.5–28.6% | 33.4–34.5% | 31.0–32.2% | 93.9–94.2% | 0 drops |

**Decision: go.** On today's raw path the X server's copy is about 40% of total CPU.
Captures of both paths were opened: gears and the moving fixture render correctly.

## The Turnip build

`panvk-driver.yml` variant **`turnip-ahb`** (Android ABI only) builds Turnip from the same
Zenith `cf70e02` tree as the S20's PanVK (content tree `4a8e9a8c…`), through Zenith's
`build-android.sh` with `-Dvulkan-drivers=freedreno -Dfreedreno-kmds=msm,kgsl` (`msm` keeps a
static libdrm and with it the DRI3 path). Patches, from `tools/panvk-probes/`:

- `platform-patches/0003` (render-completion wait) and `0004` (AHB X11 WSI), shared with PanVK.
- `turnip-patches/0101`: `TU_KGSL_DRI3=ahb` on KGSL sets `wsi_device.x11.ahb` and turns
  modifiers off; non-Android builds refuse it.
- `turnip-patches/0102`: Turnip imports an AHB into a dedicated image through
  `vk_android_get_ahb_layout`. No gralloc mapper is reachable from an app namespace on
  Android 11 (the Qualcomm `u_gralloc` backend needs the gralloc0 module; Zenith's mapper loader
  guesses `mediatek`), so every import failed with `VK_ERROR_INVALID_EXTERNAL_HANDLE` (CI
  45612838287). The WSI now marks the AHB it just allocated as owned around the import, so
  Zenith's linear-layout proof (cookies written through the dma-buf, read back through
  `AHardwareBuffer_lock`) may test it; the proof accepts B8G8R8A8 and its cookies depend only
  on the pixel, because GTK's first swapchain is 1×1. Every 1080p buffer reads back `LINEAR`, 9/9.

Builds: CI 45612838287 (0101 only, import fails), 45615059345 (`80ba24ce…`, benchmarks below),
45617186801 (`d297b4df…`, Mesa tree `432f482a…`, the 1×1 fix; correctness and soak). Staged
only in `~/pl-tahb/driver-ahb*` with an `x11/` directory of versioned soname links, as in the
PanVK package. Its non-AHB mode is the raw DRI3 control. The driver is Mesa 26.3-devel, slower
than the installed 26.2.6 on raw DRI3 (gears 30 against 45–49 FPS), so compare AHB only against
the same build.

## Step 5: paired benchmark, same driver (CI 45615059345)

Same conditions as the baseline; run order raw, AHB, AHB, raw. Zero VO and decoder drops in
every video run; isolation kept in all.

| Workload | Mode | Shell | X server | App | Total | Output |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| gears | raw DRI3 | 85.0% | 61.5–61.8% | 6.9–7.0% | 153.4–153.7% | 30–33 FPS |
| gears | AHB | 86.4% | 32.5–32.9% | 14.6% | 133.5–133.9% | 59.1–59.4 FPS |
| video 30 FPS | raw DRI3 | 48.9% | 60.8–61.1% | 30.7–30.8% | 140.5–140.7% | 0 drops |
| video 30 FPS | AHB | 55.7–56.1% | 26.4–26.7% | 35.5–35.7% | 118.0–118.1% | 0 drops |
| video at 10 FPS | raw DRI3 | 21.4–23.0% | 38.0–38.2% | 22.4–22.6% | 81.8–83.9% | 0 drops |
| video at 10 FPS | AHB | 25.8–27.4% | 15.6–16.0% | 25.8–26.5% | 67.6–69.5% | 0 drops |

AHB is below raw DRI3 in every workload and both orders: gears −13% while doing twice the
frames, video −16% at source rate and −15 to −19% at equal output. The X server's share
halves or better; Shell and mpv rise a little (each frame now goes through the WSI's CPU fence
wait and AHB import). The smoke run logged `imported AHardwareBuffer, modifier 1255,
1920x1080 stride 1920`; captures were opened.

## Flips

`tests/native/present-watch.py` (harness `--present-watch`) selects Present `CompleteNotify` on
every window and counts completion modes over each 15-second phase (CI 45617186801,
`pw4-*`):

| Mode | Phase | Shell window (`0x200004`) | Application window |
| --- | --- | --- | --- |
| AHB | gears | **479 flip** | 890 copy |
| AHB | video | **441 flip** | 450 copy |
| raw DRI3 | gears | 444 copy | 451 copy |
| raw DRI3 | video | 440 copy | 450 copy |

Every Shell frame flips on AHB and is copied on raw DRI3. Application windows are redirected,
so their presents are copies on both paths (from an AHB or from a raw dma-buf); those copies
are the X server's remaining 25–31% on AHB. As on the S20, removing them needs GPU compositing
in Termux:X11.

## Correctness and stability

- **Race**, `--present-race-trials 1 --present-race-frames 300` (WebGL in Chromium on Turnip,
  composited by the Shell): CI 45615059345 153 red / 147 blue, CI 45617186801 154 red /
  146 blue, **zero split or invalid**. Consecutive frames were opened; they alternate.
- **Restarts:** 50/50 vkcube starts return zero with the same Shell (CI 45617186801).
- **Soak** (`q3-soak-ahb`, CI 45617186801): 20 colour cycles (40/40 exact, stale control
  rejected), then vkcube FIFO and glxgears for 1800.0 s; `check-panvk-soak.py` passes:
  60 samples, the same Shell, vkcube and gears throughout, gears 57.6–59.9 FPS, MemAvailable
  4.8–5.1 GB. First, middle and last captures opened: both keep moving, no corruption.
- **Colour/resize** (`check-panvk-desktop.py`, 20 cycles, 40 captures each): CI 45615059345
  failed at GTK's first 1×1 swapchain (fixed in 0102). CI 45617186801:

  | Run | Mode | Settle | Exact |
  | --- | --- | ---: | ---: |
  | `q3-correct-ahb` | AHB | 0.35 s | 39/40 |
  | `q3-soak-ahb` | AHB | 0.35 s | 40/40 |
  | `c-ahb-1`, `c-ahb-2` | AHB | 0.35 s | 40/40, 40/40 |
  | `c-raw-1`, `c-raw-2` | raw DRI3 | 0.35 s | 40/40, 40/40 |
  | `c-ahb-settle` | AHB | 1.5 s | 40/40 |

  The one miss, `q3-correct-ahb/gtk-04-full`, shows the previous frame: the phase-10 colours
  at the old 641×359 size in the bottom-left of a white fullscreen surface, 0.35 s after the
  app had rendered frame 21 at 1920×1080. It did not recur in the next 160 AHB captures, so
  it is not shown to be AHB-specific; a likely cause is the slower swapchain recreation on AHB
  (four new 8 MB AHBs, each with the linear proof and a socket handshake) on a fullscreen
  resize. The stale-phase negative control was rejected in every run. Samples opened.
- Confirmation benchmark on CI 45617186801 (order AHB, raw): gears 133.0% vs 155.1%, video
  118.0% vs 141.1%, 10 FPS video 70.8% vs 85.0%, zero drops — the same as CI 45615059345.

Evidence: phone `~/pl-tahb/` (`base-*`, `v10-*`, `q-*`, `q3-*`, `c-*`, `pw4-*`); retrieved
summaries and captures in the ignored `temp/note10-turnip-ahb/evidence/`.

## Promotion

- [Release `turnip-ahb-26.3.1-1`](https://github.com/cnshing/debian-livecd-termux/releases/tag/turnip-ahb-26.3.1-1)
  pins the qualified driver (CI 45617186801 from d3534c2, sha256 `d297b4df…`, Mesa tree
  `432f482a…`) with its `SOURCE.json` and build provenance.
- `packages/mesa-vulkan-icd-freedreno-android` installs it at `$PREFIX/lib/freedreno-android`
  with a private `freedreno_icd.json` (not in `share/vulkan/icd.d`) and the `x11/` soname
  links; `tests/packaging/check-turnip-ahb-artifact.py` checks the built package in CI.
- `install.sh` adds it on `/dev/kgsl-3d0`, when the repository has it (older tarballs keep raw
  DRI3).
- `graphics.session_presentation` (livecd-desktop 0.2.0-52) points the Termux:X11 desktop
  session at that ICD with `TU_KGSL_DRI3=ahb` and drops `$PREFIX/lib` from its library path,
  as for PanVK. Only a qualified tree (`QUALIFIED_TURNIP_TREES`) is selected.
  `apply_renderer` clears the switch, so browsers and mpv reselect the Termux Turnip on raw
  DRI3, and Chrome's glibc Turnip is untouched. `"turnip_presentation": "raw"` in
  `~/.local/lib/livecd/config.json` opts out.

## Next steps, in order

1. Install on the Note10+ through the refreshed release (or the package from CI), then
   recheck with `tests/native/panvk-desktop.py --integrated --mode installed` and
   `livecd validate`.
2. Measure the attached Android activity's sampling cost on the live desktop, and watch for
   the late fullscreen frame on resize (repeat the colour suite at 0.35 s settle a few more
   times).
3. The CI Turnip is Mesa 26.3-devel and slower than the installed 26.2.6 on raw DRI3 (gears
   30 vs 45–49 FPS). AHB at 59 FPS / 133% already beats the installed raw path's
   47 FPS / 155%; compare the installed session against that baseline too.
4. Foreign AHB import (`tools/panvk-probes/ahb-import.py`, which allocates its own buffer)
   fails on this Turnip by design: only driver-owned buffers may be probed. The swapchain
   does not need it; a Qualcomm handle parser would.

## Gotchas

- The phone's display is shared with the user, often under DeX. Never drive the live `:0`;
  claim the phone in `temp/PHONE-STATUS`; never stop processes you did not start.
- The launcher overwrites `TU_DEBUG` and strips `MESA_VK_WSI_*`, `VK_DRIVER_FILES` and
  `VK_ICD_FILENAMES`; set experiment variables after `acceleration.prepare` or
  `apply_renderer`, then verify the process environment and mapped `libvulkan_freedreno.so`.
- KGSL has no implicit sync; any present path without a CPU fence wait shows partly rendered
  bins (rectangles, horizontal splits). Keep the wait.
- Raw CPU totals at the source rate reward dropping frames; compare at equal output and keep
  drop counters (see the S20 page).
- `gpu-setup.py` matches Turnip to the installed `mesa` version; a private Turnip must not
  replace the staged one in `~/.local/opt/livecd-native/gpu`.
- `mpv` on the session's PATH is the livecd wrapper, which adds its own `--gpu-context` and
  `--hwdec`; benchmarks call `$PREFIX/bin/mpv` (the wrapper made mpv fail "Suspected software
  renderer").
- Zenith-built drivers dlopen versioned X11 sonames (`libxcb.so.1`, …); stage them with an
  `x11/` directory of links, which the harness puts on `LD_LIBRARY_PATH`.
- The driver explains AHB import failures only in Android's log (`logcat`, tag `MESA`), for
  example `u_gralloc_get_buffer_basic_info failed` and the `cpu-linear-probe` result.
- Stale `.X11-unix/X*` sockets of dead servers make the harness refuse to start; remove one
  only after `xdpyinfo` fails on it and its lock file's pid is gone.

## What counts as done

- The baseline is measured and the Bionic present path is identified, with evidence. **Met:**
  raw DRI3.
- Either a recorded no-go, or an AHB Turnip whose total CPU for gears and equal-output video is
  clearly below the current path in both run orders, with no split frames in the race test, a
  completed soak, and captures opened and looked at. **Met** with CI 45615059345/45617186801;
  promoted at the owner's request.
