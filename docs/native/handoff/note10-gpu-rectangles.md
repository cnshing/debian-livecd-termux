# Handoff: flickering rectangles, black or showing what is behind the window (Note10+)

State on 2026-11-18. User report, not yet reproduced. Shared rules and pass criteria:
[README.md](README.md).

## Symptom

On the Note10+ (Adreno 640), in Chrome and during video playback (possibly in other
programs too): rectangles flash up at random. Sometimes a rectangle is black; sometimes it shows
whatever lies underneath the window, as if that part of the window were not there.

User answers (2026-11-18): Termux:X11 under Samsung DeX, 1920x1080 external display. Size,
position and frequency look random. Other programs and memory pressure are untested. No
recording yet.

## What this points at

"Shows the window underneath" means the compositor (mutter on Termux:X11) composited a region of
the window from a buffer that had no valid content, or that the client had not finished drawing:
undefined or transparent pixels. Black is the same thing with cleared memory. Rectangular
regions suggest tiles or damage regions rather than video frames.

Candidates, most likely first:

1. **Missing synchronisation between the GPU and the compositor.** KGSL has no implicit sync on
   dma-bufs. If the client's rendering (ANGLE/Vulkan on Turnip, or a VA surface written by the
   bridge's CPU copy) is still in flight when mutter samples the buffer, the unwritten tiles show
   through. Video makes it worse: see cause 2 in [decode-frame-sync.md](decode-frame-sync.md)
   (the reader thread reuses dma-bufs without waiting for readers).
2. **Alpha in an opaque window.** A buffer with an alpha channel that should be opaque, left
   at alpha 0 in some tiles, lets the compositor show the desktop behind. That would explain the
   "underlying window" case directly.
3. **Chrome GPU raster tiles** evicted or lost under memory pressure and drawn as checkerboard
   (black) until re-rastered.

## Questions to settle while reproducing

- Does it happen outside browsers and video (GNOME apps, Ghostty, a GL demo)? Inside one
  program only → that program's path; everywhere → mutter / Termux:X11 present path.
- Does it happen with Chrome's GPU compositing off (`--disable-gpu-compositing`), and with
  hardware video off (`hardware_video: false` in `acceleration.json`)?
- Windowed, maximised or fullscreen? Fullscreen unredirects the window and skips mutter.
- Does it follow memory pressure (`MemAvailable`) or other GPU load?

## Source analysis (2026-11-19, confirmed on the phone, see below)

Candidate 1 has a concrete mechanism in Mesa 26.2.6's Vulkan X11 WSI, which both Chrome
(ANGLE → Turnip) and mutter (Zink/Kopper → Turnip) present through:

- Termux:X11 offers DRI3 and Present, so the WSI hands the swapchain dma-buf straight to the
  X server (`wsi_common_x11.c`), with no software copy.
- It then counts on implicit sync. Explicit sync needs DRI3/Present 1.4 drm syncobjs (none on
  KGSL); the dma-buf semaphore path needs `DMA_BUF_IOCTL_IMPORT/EXPORT_SYNC_FILE`, which the
  Note10+'s 4.14 kernel lacks, so `wsi_drm_init_swapchain_implicit_sync()` creates nothing.
  The image is flagged `implicit_sync`, which Turnip honours only on msm and virtio, not KGSL
  (`tu_knl_kgsl.cc` has no implicit-sync handling).
- `x11_needs_wait_for_fences()` makes the CPU wait for the render fence before presenting only
  in MAILBOX mode. In FIFO and IMMEDIATE, `xcb_present_pixmap` goes out while the GPU may still
  be writing.

So the X server or compositor can sample a buffer whose Adreno GMEM bins have not been resolved
yet. Bins are rectangles, which matches the symptom. Unresolved bins hold old content or zeros. In
an ARGB window (Chrome uses a 32-bit visual under a compositing manager) zero is fully
transparent, which shows what is behind the window; otherwise it shows as black. Video adds GPU
load, so the GPU finishes later and the race is lost more often.

Mutter's Zink patches 0021–0024 cover dma-bufs that Zink exports and imports, not presents
through the Vulkan WSI, so they do not close this gap.

Cheap checks, in order:

1. Negative control and possible workaround: `MESA_VK_WSI_DEBUG=sw` on Chrome only. This forces
   the software WSI, which waits for the fence and copies through SHM. If the rectangles go
   away, the cause is confirmed. Watch CPU cost at 1920x1080.
2. Proper fix, a Mesa patch: make `x11_needs_wait_for_fences()` return true (or wait on
   `chain->base.fences[image_index]` in the present thread) whenever the swapchain has neither
   explicit sync nor a `dma_buf_semaphore`. This costs about one frame of latency, not a copy.
   It covers Chrome, Firefox and mutter on any KGSL or no-sync-file kernel, including the S20.
3. Repeat the test with mutter alone (a GL demo, no browser) to see whether mutter's own Kopper
   output is affected too.

## Phone result (2026-11-19): the present does not wait for the GPU

Test: Chrome 157 started through the installed launcher on a private Termux:X11 display (no
window manager, nothing on `:0`). A WebGL page clears the whole window to red or blue on
alternate frames, with a heavy fragment shader so each frame takes the GPU a while. The X server's
picture was recorded with `x11grab` at 30 fps and every frame was checked for both colours at
once. Script: `~/pl-rect/test-rect.py` and `an.py` on the Note10+ (not in Git).

| Run | Frames | Frames with both colours |
| --- | --- | --- |
| default (run 1) | 600 | 11 |
| default (run 2) | 900 | 200 |
| `MESA_VK_WSI_PRESENT_MODE=mailbox` (same DRI3 path, CPU waits for the fence first) | 900 | 0 |
| `MESA_VK_WSI_DEBUG=sw` (fence wait + SHM copy) | 900 | 0 |

The bad frames are split horizontally: the next frame on top, the old one below, with small
steps on the boundary row. That is Adreno's binned rendering caught partway through (bins are
filled row by row). Mailbox mode changes nothing on this path except adding the fence wait, and
it removes the problem entirely, so the missing wait is the cause. The page ran at 30 fps in
every mode.

This is the X-server-level form of the bug. Under mutter, the same unfinished buffer turns into
the rectangles the user sees. Not yet done: a recording under mutter on the real session
setup, and video.

Fix, option 2 below, implemented as `packages/mesa/0028-wsi-x11-wait-for-fences-without-implicit-sync.patch`
(mesa 26.2.6-108), for the Bionic Turnip: mutter's Zink/Kopper output, Chromium, Firefox and
native Vulkan programs. It waits only when the swapchain has neither explicit sync nor a dma-buf
semaphore, so drivers with working implicit sync are unaffected. Chrome uses the glibc Turnip from
`android-vaapi-glibc`, which got the same wait in revision 14 (656cca0,
[note10-chrome-typing.md](note10-chrome-typing.md), same root cause).
Still to do: install both on the Note10+, rerun the default case here (expect 0 split frames) and
record under mutter with video playing.

Options considered:

1. Quick workaround: set `MESA_VK_WSI_PRESENT_MODE=mailbox` for Vulkan clients on KGSL in the
   launcher. Side effects: no vsync throttling (mailbox drops frames instead of blocking) and
   possibly one more swapchain image.
2. Proper fix: patch `x11_needs_wait_for_fences()` in `packages/mesa` to return true when the
   swapchain has neither explicit sync nor a `dma_buf_semaphore`. That keeps FIFO pacing and
   also covers mutter's Kopper output.

## Next steps

1. Reproduce on a private display with an `x11grab` recording (see
   [decode-frame-sync.md](decode-frame-sync.md)), in Chrome on a busy page and while playing
   video; then in Chromium, Firefox and a native program, to find which layers are affected.
2. Bisect the switches above. For video, also try `LIVECD_VA_DISABLE_COMPLETION=1` as a
   negative control for the bridge's completion wait.
3. If GPU sync is implicated, add an explicit fence wait (sync_file export from Turnip before
   present, or the bridge waiting for consumers before reusing a buffer) and recheck.
4. Check the alpha path: grab the window's pixmap (`xwd -id`) and look for alpha 0 in the bad
   regions.

## What counts as fixed

No rectangles in recordings of Chrome and of video playback at least as long as the runs that
showed them, with a negative control that still shows them. Open the recordings and look.
