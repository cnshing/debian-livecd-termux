# Handoff: S20 PanVK presentation over raw DRI3 instead of the software path

State on 2026-11-19. Not started. Shared rules: [README.md](README.md).

## Goal

On the Galaxy S20 (x1s, Mali-G77, kbase JM, Linux 4.19.87), Zenith PanVK presents every
X11 swapchain through Mesa's **software path**: the GPU renders, the image is read back into
CPU memory, and it reaches Termux:X11 through MIT-SHM. GNOME Shell (Zink), GTK GL apps and the
Ghostty DMA-BUF stack all go this way. The goal is the **raw DRI3** path instead: the X server
receives the rendered dma-buf directly, without the readback and copy.

Nobody has measured the cost of the software path on the S20. Measure it first (step 1): if
raw DRI3 is not clearly cheaper or smoother, stop there.

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

The fix is the one in `packages/mesa/0028-wsi-x11-wait-for-fences-without-implicit-sync.patch`:
also wait when `chain->base.dma_buf_semaphore == VK_NULL_HANDLE`. That patch does **not** apply
to Zenith's reworked file as it stands (`git apply` failed in CI run 44496426162). Rebase it on
the prepared tree: that run's `panvk-prepared-source` artifact holds
`work/mesa/src/vulkan/wsi/wsi_common_x11.c`. Keep the existing `sw ||` term.

## Next steps

1. **Baseline cost, software path.** On a private lorie, with the installed driver, measure
   GNOME Shell and a GL demo (glxgears, vkcube) at the desktop resolution: frame rate, CPU time of
   gnome-shell and the X server, and dropped frames while playing video. Then repeat with
   `PANVK_KBASE_DRI3=raw` set after the launcher's environment step (see Gotchas). If raw DRI3 is
   not better, write that down and stop.
2. **Race check without the wait.** With raw DRI3 and the unpatched driver, run the two Note10+
   tests (described below). Expect split or cut frames; that is the negative control, and it
   proves the tests can fail. If none show up after about 10 trials, record that, but still add
   the wait (the preconditions are there).
3. **Add the wait.** Put the rebased patch in `tools/panvk-probes/platform-patches/` (next free
   number) and run `panvk-driver.yml` with `variant=combined-ahb abi=both`. Use the rebuilt ICDs
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

Neither is in Git: they lived on the Note10+ under `~/pl-rect` (copy them to the S20 or rewrite
them). Both record the private display with FFmpeg's `x11grab` at 30 fps.

- **Full-window flip.** A WebGL page clears the whole window to red, then blue, on alternate
  frames, with a heavy fragment shader (a 200-iteration loop) so each frame keeps the GPU busy.
  Any recorded frame with both colours is an unfinished buffer. 900 frames per run.
- **ArcMenu clicks.** A second gnome-shell on a private display, with the user's dconf copied into
  its `XDG_CONFIG_HOME` so the panel and ArcMenu match. Each trial is 60 clicks on the menu button
  with random 0.1–0.3 s gaps, recorded losslessly (FFV1). Flag any frame where the menu
  background is present at the top but missing at the bottom (sample its colour first; it was
  (37, 41, 50) on the Note10+).

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
