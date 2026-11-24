# Handoff: S20 PanVK presentation over raw DRI3 instead of the software path

State on 2026-11-23. Cost measured; race qualification in progress. Raw DRI3 remains opt-in.
Shared rules: [README.md](README.md).

## Goal

On the Galaxy S20 (x1s, Mali-G77, kbase JM, Linux 4.19.87), Zenith PanVK presents every
X11 swapchain through Mesa's **software path**: the GPU renders, the image is read back into
CPU memory, and it reaches Termux:X11 through MIT-SHM. GNOME Shell (Zink), GTK GL apps and the
Ghostty DMA-BUF stack all go this way. The goal is the **raw DRI3** path instead: the X server
receives the rendered dma-buf directly, without the readback and copy.

Private measurements show a tradeoff: raw DRI3 drops fewer video frames, but costs more CPU
during video and reduces gears throughput. These are private-server results; Android scanout
and an installed desktop using raw DRI3 have not been qualified.

## Where things stand

| What | Where |
| --- | --- |
| Driver | `packages/mesa-vulkan-icd-panvk-kbase`: prebuilt release `panvk-desktop-26.3.1-1`, variant `combined-ahb`, Zenith `cf70e02`, patch level p0175, Mesa base `5a07217` (`source.lock.json`) |
| Driver build | `.github/workflows/panvk-driver.yml` (inputs `variant`, `abi`), `tools/panvk-probes/build-driver.sh`; the `combined-ahb` variant takes every patch under `tools/panvk-probes/platform-patches/` |
| Path selection | Zenith `src/panfrost/vulkan/panvk_wsi.c` (about lines 705–760): `.sw_device = uses_kbase && !kbase_dmabuf`. Raw DRI3 is on when `PANVK_KBASE_DRI3=raw` or `termux`, or when `WSI_X11_TERMUX` is set and non-zero |
| Who switches it off | `src/native/graphics.py` `apply_renderer` and `tools/ghostty-dmabuf/launcher.py` strip `PANVK_KBASE_DRI3`; nothing sets `WSI_X11_TERMUX`. `tests/native/test-graphics.py` asserts the strip |
| Earlier raw DRI3 tests | [PANVK-X1S-RESEARCH.md](../PANVK-X1S-RESEARCH.md): see the next section |
| Private desktop harness | `tests/native/panvk-desktop.py --mode raw` (private lorie only; Xvfb has no raw DRI3) |

## Earlier evidence (PANVK-X1S-RESEARCH.md)

- Raw DRI3 on a private lorie passed 20 window/fullscreen cycles (40 captures, maximum channel
  error 0) and 100 vkcube start/stop cycles, the same as MIT-SHM.
- A 30-minute raw DRI3 soak **failed**: the private session ended after about 16.5 minutes,
  and vkcube then hit SIGSEGV in the driver at display shutdown. Another private session was
  running at the time, so the cause was never attributed.
- A later patched driver failed presentation on both raw DRI3 and SHM
  (`zink: could not create swapchain`). That was never bisected; recheck it with the current
  `combined-ahb` driver.
- App-allocated AHB imports fail (no usable Samsung mapper metadata). The WSI's own buffers work
  over raw DRI3, so this does not block swapchains.

Those captures were taken once a frame had settled, so they would not catch the problem below.

## Hazard: presenting before the GPU finishes

On the Note10+ (2026-11-19, [note10-gpu-rectangles.md](note10-gpu-rectangles.md)), Mesa's X11
WSI presented over DRI3 without waiting for rendering. That caused split frames in Chrome (up to
657 of 900) and a cut-off ArcMenu in GNOME Shell. The S20 has every precondition for the same race
on raw DRI3:

- The 4.19 kernel has no `DMA_BUF_IOCTL_IMPORT_SYNC_FILE`, so the WSI cannot attach a fence to the
  dma-buf (`wsi_drm_init_swapchain_implicit_sync` creates no `dma_buf_semaphore`).
- kbase attaches no implicit fences to dma-bufs.
- DRI3/Present 1.4 explicit sync needs DRM syncobjs, which kbase does not have.
- In Zenith's `wsi_common_x11.c`, `x11_manage_present_queue` waits for the image fence only on
  the software path or in MAILBOX mode:

  ```c
  bool need_fence_wait =
        (chain->base.wsi->sw ||
         x11_needs_wait_for_fences(chain->base.wsi, wsi_conn, present_mode)) &&
        !chain->base.image_info.explicit_sync;
  ```

  So raw DRI3 in FIFO or IMMEDIATE mode presents with no wait.

The fix also waits when `chain->base.dma_buf_semaphore == VK_NULL_HANDLE`.
The original `packages/mesa/0028-wsi-x11-wait-for-fences-without-implicit-sync.patch`
failed to apply to Zenith's reworked file in CI run 44496426162. Commit `989e419`
rebased it as `tools/panvk-probes/platform-patches/0003-wsi-x11-wait-for-fences-without-implicit-sync.patch`,
keeping the existing `sw ||` term. [CI run 44501187850](https://github.com/cnshing/debian-livecd-termux/actions/runs/44501187850)
passed for both ABIs, with `combined-ahb`. The patched libraries are in each
artifact's **`out/patched/`** directory; `out/` itself contains the baseline build.
The patched Bionic library also completes the private benchmark below. Race, resize, teardown
and soak qualification are still required before publishing it.

## Measurements and current evidence

The completed `normal-shm-1` and `normal-raw-wait-1` runs used a private lorie at
1920×1080/60, five-second warmups and 30-second measurement intervals. Both passed
`isolation.json`, all workloads completed, and wall-clock and monotonic durations
agreed. `MUTTER_SYNC` was unset, matching normal desktop behavior. Earlier runs
inherited synchronous X11 debugging from the correctness harness; do not mix those
numbers with this table.

CPU percentages are percentages of one CPU core. Gears FPS is the mean of its
reported intervals. Video is the same local 1080p30 fixture, software decoded,
with audio disabled; drops are mpv counter deltas after warmup.

| Route | Workload | Shell CPU | X server CPU | App CPU | Gears FPS | Video drops / 30 s |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Installed ICD, MIT-SHM | idle | 1.3% | 2.5% | — | — | — |
| CI ICD with wait, raw DRI3 | idle | 1.2% | 2.5% | — | — | — |
| Installed ICD, MIT-SHM | gears | 101.9% | 25.5% | 68.1% | 51.8 | — |
| CI ICD with wait, raw DRI3 | gears | 91.7% | 75.5% | 13.5% | 35.0 | — |
| Installed ICD, MIT-SHM | video | 40.2% | 13.8% | 83.1% | — | 489 |
| CI ICD with wait, raw DRI3 | video | 53.0% | 71.7% | 83.6% | — | 118 |

Neither route reported decoder drops. Raw DRI3 reduced reported video drops by
about 76%, but total measured video CPU rose from 137.1% to 208.3% of a core.
Gears throughput fell by about 32%. This justifies further investigation of
smoothness; it does not establish a general performance or power win. Repeat the
normal comparison in reverse order before making the default decision. Thermal
zones were unreadable, so temperature effects have not been excluded. The
soak logger can also read battery temperature through `termux-battery-status`;
this is a battery sensor, not a CPU/GPU thermal-zone reading.

The installed packages during these measurements were `mesa-vulkan-icd-panvk-kbase
26.3.1-1`, `mesa 26.2.6-106`, and `livecd-desktop 0.2.0-22`. The private patched
Bionic library's SHA-256 is
`b40b4d712a33cf6f5962eee1e1fa60d97db7adb9596521e52949f4440dd189be`.
Its hash matches CI's `out/patched/libvulkan_panfrost.so`.

Race evidence so far:

- Unpatched raw DRI3, default present mode: **0 split frames in 10 × 900 captured
  frames**. All captures were valid. This does not supply the required nonzero
  hardware negative control.
- Unpatched ArcMenu pilot: **0 cut frames in 248 captured frames**, with both
  fully open and closed frames present. The menu background was sampled as
  `(37, 41, 50)` at text-free strips near its top and bottom.
- Unpatched FIFO ArcMenu: **0 cuts in 2,294 captured frames**, across ten trials
  and 600 clicks. All trials contained fully open and closed frames and passed
  the open/closed calibration checks.
- Synthetic checker controls detect a red/blue split and an intentionally cut
  menu frame, while accepting the solid-color and fully open/closed controls.
  These validate the analyzers, not the hardware race.
- Patched race trials, the new 20-cycle colour check, 100 vkcube restarts and the
  isolated 30-minute soak remain pending. Nothing was installed or enabled.

Evidence is on the S20 under `~/s20-raw-dri3/`, named as above, with `result.json`,
`environment.json`, `benchmark.json` and `isolation.json`. Race clips and recording
metadata are under each run's `race/`. Host copies and analyzer JSON are under
`temp/s20-raw-dri3/evidence/`; older logs are in `temp/s20-raw-dri3/recovered/`.
The flip checker now inspects every native-resolution pixel inside an eight-pixel
border and flags any red/blue mix, including a single pixel. Its regression tests
cover a one-pixel split, an invalid black capture, and a cut menu with an invalid
calibration control. The full-window recordings target 30 fps, but the first trial took about 50 s for
900 captured frames and later trials about 32 s. Do not count FFmpeg's duplicated
constant-rate output frames as additional observations; the checker uses
`-fps_mode passthrough`.

## Reproducible cost measurement

`tests/native/panvk-desktop.py` now has an optional benchmark before its correctness
checks. Copy `tests/native/panvk-desktop.py` and `tests/browsers/` together, retaining
their directory layout. It uses the installed controller and private lorie, with
overrides applied after `desktop.environment`. It no longer needs the old
`~/gpu-x1s` browser/server copies for an integrated benchmark.

The S20's saved desktop mode is 1920×1080 at approximately 60 Hz. The private server
defaults to 1280×1024 at 30 Hz, so set both explicitly:

```sh
# Hold a wake lock for the test and release only the lock acquired for this work.
termux-wake-lock
python tests/native/panvk-desktop.py --integrated --mode shm \
  --screen-size 1920x1080 --screen-fps 60 --out "$HOME/s20-raw-dri3/shm-run" \
  --benchmark-seconds 30 --benchmark-only --benchmark-video /path/to/video.mp4
# Repeat with --mode raw and a new output directory, then reverse the order.
termux-wake-unlock
```

Each phase gets a five-second warmup: idle GNOME Shell, fullscreen `glxgears`,
then fullscreen mpv if a fixture was supplied. Use the same local fixture in both
modes, longer than the warmup plus measurement interval to avoid counter resets
on looping. Runs reject a substantial wall/monotonic duration mismatch (suspend
or clock change). The benchmark disables the Android procfs compatibility broker
to read real process counters. mpv uses software decoding and no audio to isolate presentation.
This is a transport benchmark, not hardware-codec qualification.

`benchmark.json` records CPU time for the shell, X server and workload (percent of
one CPU core), per-second samples, glxgears FPS, mpv frame/drop properties over IPC,
memory and readable thermal zones. Unreadable thermal zones produce an empty map.
Workload process maps and `result.json`'s GL identity show which driver was used.
`isolation.json` must pass, and all phases must complete. The benchmark takes no
screenshots during its measured intervals. FPS from glxgears measures application
throughput, not the number of complete frames seen on the display.

## Next steps

1. **Confirm the cost tradeoff.** The first normal comparison is complete (table above).
   Repeat in reverse order. On a private lorie, with the installed driver, measure
   GNOME Shell and a GL demo (glxgears, vkcube) at the desktop resolution: frame rate, CPU time of
   gnome-shell and the X server, and dropped frames while playing video. Then repeat with
   `PANVK_KBASE_DRI3=raw` set after the launcher's environment step (see Gotchas). If raw DRI3 is
   not better, write that down and stop.
2. **Race check without the wait.** With raw DRI3 and the unpatched driver, run the two Note10+
   tests (described below). Expect split or cut frames; that is the negative control, and it
   proves the tests can fail. If none show up after about 10 trials, record that, but still add
   the wait (the preconditions are there).
3. **Qualify the wait.** The rebased patch and both CI builds are ready (see above). Use the rebuilt ICDs
   privately (`VK_DRIVER_FILES`/`VK_ICD_FILENAMES` set after the launcher step). Rerun step 2:
   expect 0. Rerun the 20-cycle window/fullscreen colour check
   (`tests/native/panvk-desktop.py --mode raw`) and vkcube start/stop.
4. **Soak.** 30 minutes of raw DRI3 on a private display with nothing else running on the phone:
   resource and thermal samples, and crash logs that can be attributed. The earlier failure (session
   ended at 16.5 minutes, vkcube SIGSEGV at shutdown) must not recur.
5. **Turn it on.** Only after steps 3–4 pass:
   - Publish the driver as a new release. Update `source.lock.json` and the SHA-256 values in
     `packages/mesa-vulkan-icd-panvk-kbase/build.sh`, then bump its revision.
   - In `src/native/graphics.py`, set `PANVK_KBASE_DRI3=raw` for the automatic x1s PanVK profile
     instead of stripping it, and update `tests/native/test-graphics.py`. Decide separately for
     `tools/ghostty-dmabuf/launcher.py`.
   - Bump `livecd-desktop`. Requalify on the installed desktop per
     [PANVK-CTS-AND-DAILY-DESKTOP-HANDOFF.md](../PANVK-CTS-AND-DAILY-DESKTOP-HANDOFF.md)
     (validate, Settings, Ghostty, browsers).
   - Update [PANVK-DESKTOP.md](../PANVK-DESKTOP.md) ("Presentation stays on the accepted
     MIT-SHM transport") and [MALI-GPU-STATUS.md](../MALI-GPU-STATUS.md).

## Tests that catch the race

`tests/native/panvk-present-race.py` implements both probes, invoked by the private
desktop harness. Both target 30 fps with FFmpeg `x11grab` and save lossless FFV1.
The correctness/race harness retains `MUTTER_SYNC=1`; benchmarks unset it.

- **Full-window flip.** A WebGL page clears the whole window to red, then blue, on alternate
  frames, with a heavy fragment shader (a 200-iteration loop) so each frame keeps the GPU busy.
  Any recorded frame with both colours is an unfinished buffer. 900 frames per run.
- **ArcMenu clicks.** A second gnome-shell on a private display, with the user's dconf copied into
  its `XDG_CONFIG_HOME` so the panel and ArcMenu match. Each trial is 60 clicks on the menu button
  with random 0.1–0.3 s gaps, recorded losslessly (FFV1). Flag any frame where the menu
  background is present at the top but missing at the bottom (sample its colour first; it was
  (37, 41, 50) on the Note10+).


Examples, run only when no other private display is active:

```sh
python tests/native/panvk-desktop.py --integrated --mode raw \
  --screen-size 1920x1080 --screen-fps 60 --present-mode fifo \
  --present-race-trials 10 --present-race-only --out "$HOME/s20-raw-dri3/flip-fifo"
python tests/native/panvk-desktop.py --integrated --mode raw \
  --screen-size 1920x1080 --screen-fps 60 --present-mode fifo \
  --present-race-trials 10 --present-race-only --menu-race-button 24,1056 \
  --shell-profile "$HOME/.config/livecd-native/dconf/user" \
  --out "$HOME/s20-raw-dri3/menu-fifo"
# Add --driver /absolute/path/libvulkan_panfrost.so for a private patched run.
```

The menu probe copies the livecd user dconf database, uses the installed read-only
defaults, and enables ArcMenu, dash-to-panel and the shell theme in the private
profile. It records 60 clicks per trial with seeded 0.1–0.3 s gaps. Inspect
`menu-open.png` and `menu-closed.png` before choosing text-free sample strips.
For the current S20 layout the calibration JSON is:

```json
{"strips": [620, 480, 980, 16, 16], "color": [37, 41, 50]}
```

Here `strips` means x, top y, bottom y, width, height. Host analysis commands:

```sh
python tests/native/panvk-present-race.py --check /path/to/flip-*.mkv
python tests/native/panvk-present-race.py --menu-calibration calibration.json \
  --check /path/to/menu-*.mkv
```

Menu analysis requires matching open/closed reference PNGs beside the clips and
rejects calibration that cannot distinguish them. Reports contain counts and
frame indices; a successful analyzer exit alone does not mean zero defects.
Use `python tests/native/check-panvk-desktop.py /path/to/run` to validate the
window/fullscreen captures, GPU identities and isolation. It checks every interior
pixel and requires a stale-phase negative control to fail.

For restart/soak tests, `--vkcube /absolute/path/vkcube` avoids the old private
`~/gpu-x1s/root/` dependency. Termux's `vulkan-tools 1.4.369` package was unpacked
privately under `~/s20-raw-dri3/vulkan-tools/root/`; it was not installed.

## Gotchas

- `graphics.apply_renderer` (via `desktop.environment`) strips `PANVK_KBASE_DRI3`,
  `MESA_VK_WSI_*`, `VK_DRIVER_FILES` and `VK_ICD_FILENAMES`. Set test overrides after it, and
  check `/proc/<pid>/environ` or the process's mapped `libvulkan_panfrost.so`. On the Note10+, two
  runs silently used the installed driver this way.
- The software path's fence wait is a Zenith change (series patch 106) and is not upstream.
  Keep it when rebasing.
- `WSI_X11_TERMUX` is the proprietary Termux:X11 layer's process-wide switch. If anything starts
  setting it, PanVK changes path too.

## What counts as done

- Raw DRI3 is measurably better than MIT-SHM in step 1.
- 0 split or cut frames with the wait, against a nonzero count without it.
- The colour check and vkcube cycles pass, and the 30-minute soak completes.
- The installed desktop validates and the qualification checks pass with raw DRI3 as the default.
  Open the recordings and look at them.
