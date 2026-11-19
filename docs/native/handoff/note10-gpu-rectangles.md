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
