# Handoff: decoded-frame sync (stale frames, flicker, tearing)

State on 2026-11-14. This spans every browser. Shared rules and pass criteria:
[README.md](README.md).

## Status

Decoded pictures are correct when each surface is waited on: VP9, HEVC and H.264 decoded
frame-exact against software through FFmpeg (300 of 300 frames, 1080p30, Adreno). The problems
are in **when** a consumer sees a picture, not in the decoding.

| Symptom | Where | State |
| --- | --- | --- |
| Compositor shows an older frame than the browser captured | Chromium, Chrome | fixed by a bounded wait at `vaEndPicture` (500 ms limit), but **one of 13** runs still failed: Chromium HEVC, windowed, Adreno, frame 13 shown for 36, while another session's encoder tests were using MediaCodec. Three reruns passed |
| Firefox video "flickering back and forth" | user report, Adreno, early November | never reproduced |
| Chrome "black tearing" | user report, Adreno, early November | never reproduced |

## Why the wait was needed

The bridge copies each decoded MediaCodec picture into the VA surface with the CPU. It reported
the picture complete before that copy was visible to Chromium's implicit DRM synchronisation.
So the compositor could present the surface's previous content. `LIVECD_VA_DISABLE_COMPLETION=1`
removes the wait and reproduces the stale frames, which is the negative control.

## Candidate causes still open

Both are in `tva_bridge.c` (see [decode-h264.md](decode-h264.md) for where it is):

1. **`drop_on_fence_destroy` is set only for AV1.** It is the guard that drops a late
   MediaCodec frame instead of writing it into a surface the client has already reused. Without
   it on VP9, HEVC and H.264, a late frame can land in a recycled surface: an old picture shown
   again, which would look like flicker.
2. **The reader thread writes recycled dma-bufs without waiting for readers.** It CPU-writes the
   next picture into a buffer the GPU may still be sampling, and KGSL has no implicit sync for
   that. This would show as tearing.

Load matters: the one failure happened while MediaCodec was busy with encoding. That fits a
late frame (cause 1).

## Next steps

1. **Reproduce first.** Record the private display while a browser plays, at the display's
   frame rate, and look for repeated or torn frames. Run with and without a concurrent
   MediaCodec load, such as the native encode suite on the same phone. An `x11grab` recorder
   harness was written for this but is not in Git; it is a small wrapper around FFmpeg's
   `x11grab` on the private display.
2. Turn on `drop_on_fence_destroy` for every codec and repeat under load. Check that no frames go
   missing in the normal case.
3. For tearing, make the reader thread wait for the consumer's read before reusing a buffer, or
   rotate through more buffers.

## How to test

The browser harnesses in [decode-chromium.md](decode-chromium.md) and
[decode-firefox.md](decode-firefox.md) compare numbered frames at the browser and compositor
layers. They catch a stale frame only at the sampled moments; a recording catches it between
them.

## Where things are

| What | Where |
| --- | --- |
| Completion wait | native: `TERMUX_VA_SYNC_END_PICTURE` in `src/native/acceleration.py`; glibc: `overlays/Browser+Chromium/browsers/va-completion.c` |
| Bridge | `tva_bridge.c`, built by `packages/android-vaapi` |
| Earlier results | [native-acceleration-checks.md](../../browsers/native-acceleration-checks.md) |
