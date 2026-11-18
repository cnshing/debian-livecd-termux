# Note10+ codec parity: remaining implementation work

State from the 2026-11-16 investigation. [Measured baseline and client table](../ADRENO-640-PARITY.md).
General driver support remains documented by [upstream](../../../README.md#upstream-support-and-local-verification).
The local evidence directory is `temp/parity-note10-20261116/`.

## Preserved 10-bit decode and HDR

**Steps 1-6 are done (2026-11-18, termux-va 2, android-vaapi 15, -glibc 7, livecd-desktop 37):** see
"10-bit decoding" in [ADRENO-640-PARITY.md](../ADRENO-640-PARITY.md). Still open: step 7 (colour and HDR
metadata over the wire), Chromium/Chrome P010 presentation (their ANGLE/Vulkan import shows black, so
the launcher keeps them on software 10-bit) and 4K. HEVC Main10 encode is done (termux-va 4, android-vaapi 17). The history below is kept.

**A real ByteBuffer P010 route exists.** The committed
[`probe-bytebuffer.c`](../../../tests/native/codec-info/probe-bytebuffer.c)
feeds tiny synthetic Main10/profile-2 keyframes to the named Qualcomm decoders.
YUV420Flexible requests negotiate `0x7fa30c0a` linear Venus P010 on both.
The NV12 control produces 8-bit output and must fail. At 96x96 the reported
stride is **256 bytes**, not 256 pixels. Existing FFmpeg MediaCodec playback
of 10-bit fixtures returned format 21 / NV12 despite passing RGB comparisons.

Do not enable HEVC Main10 / VP9 profile 2 in the VA table alone. Required work
in the pinned source used by `packages/android-vaapi` and `-glibc`:

1. Negotiate distinct 10-bit sessions so an older daemon or client rejects
   the request instead of interpreting P010 as NV12. Appending decoder codec
   IDs is one option; update both copies of `tva_protocol.h` together and
   route codec-specific header/CSD handling through their base codec IDs.
2. Probe actual output at daemon startup and advertise only hardware paths
   that return a real P010 buffer. MediaCodecInfo's advertised colour-format
   list is insufficient: this phone's decoder list omits P010 even though
   negotiation succeeds. Do not infer this support on Mali.
3. Request flexible output for the new sessions and validate every format
   change. Reject 8-bit, tiled/UBWC or unknown formats for a P010 request.
   Account for byte pitch, slice height, visible crop, output-buffer bounds
   and P010 sample alignment; test nonzero crop origins and low sample bits.
4. Double shared-memory capacity for these sessions. `shm_slot_bytes()` in
   `daemon/termux-va.c` currently uses aligned width × height × 3/2 with an
   adaptive-playback ceiling. P010 needs three bytes per pixel, with actual
   byte strides and vendor padding checked. Keep the 8-bit allocation unchanged.
5. In `tva_bridge.c`, add gated `PIPE_VIDEO_PROFILE_HEVC_MAIN_10` and
   `PIPE_VIDEO_PROFILE_VP9_PROFILE2` support, and P010 format support only
   for the negotiated 10-bit decode path. Keep encoders separate.
6. `tva_create_contiguous_video_buffer()` rejects anything except NV12.
   Add correct P010 plane resources and export metadata. `tva_copy_frame()`
   already uses resource block sizes for row lengths but adds crop offsets
   as bytes; multiply horizontal sample offsets by the component size.
   Audit processing, image download and CPU/GPU resource mapping as well.
7. Carry colour range, primaries, transfer, matrix and HDR metadata through
   the wire, VA and presentation paths. A 10-bit buffer alone is not HDR.
   X11 compositor/display output is a further qualification boundary.

Accept first with FFmpeg raw P010 against a software 10-bit reference,
including lower-bit variation, padding/crop controls, inline/SHM, flush and
format changes. Then check GStreamer and each browser's actual decoder and
rendered output. Keep the 8-bit suites passing. Secure/DRM output is excluded.

## VP8 decode and encode

**Decode: done, on by default on Adreno** (android-vaapi 16, termux-va 3). Mesa
had no VP8 pipe format, so `0120-vp8-decode-encode.patch` adds
`PIPE_VIDEO_PROFILE_VP8` (`VAProfileVP8Version0_3`) for the bridge alone and
`picture_vp8.c`. VA clients submit the slice data from the first partition on,
so the bridge rebuilds the 3-byte frame tag and, on key frames, the start code
and size; the first partition's size is the slice data size minus the
coefficient partitions and their size table. VA-API has no `show_frame`, and
each VA picture must fill its surface, so every frame is sent as shown.
`termux-va` lists hardware VP8 decoders in `<socket>.decoders`; the driver
offers VP8 only when one is listed (`OMX.qcom.video.decoder.vp8` here). The
launcher hides it on Mali (`disabled_va_codecs` default), where it is untested.
FFmpeg VA decoded `chart-vp8` and `chart-vp8-altref` (three hidden alternate
reference frames, four token partitions) bit-exact against libvpx, 48/48 each;
with `TERMUX_VA_DISABLE_VP8=1` the same run fails.

**Encode: on by default on Adreno.** VP8 sessions use the new append-only
`CODEC_VP8_ENC` (14) and the VP9 encoder descriptor in the driver; the daemon
lists `OMX.qcom.video.encoder.vp8` in `<socket>.encoders`. The earlier
"invalid VP8" output had one cause: `AMediaCodec_getOutputBuffer` already
points at the buffer's range offset, and the daemon (like FFmpeg's
`vp8_mediacodec`) added `info.offset` again. The Qualcomm VP8 encoder reports
offset 12, so the first 12 bytes of every frame were lost. A Java `MediaCodec`
encode of the same frames (dex via `app_process`) showed offset 12 and valid
VP8. FFmpeg's `vp8_mediacodec` still has this bug; the stack-protector abort
seen before did not recur.

Installed check (2026-11-18: android-vaapi 16, termux-va 3, ffmpeg 102, through
the session's VA environment):
- FFmpeg VA decode is bit-exact 48/48 for `chart-vp8` and `chart-vp8-altref`, and
  H.264/HEVC/VP9 are unchanged at 48/48. GStreamer `vavp8dec` is bit-exact.
- `vp8_vaapi` and `vavp8enc` produce 90/90 frames that libvpx decodes (SSIM
  0.998), and `vp8_mediacodec` is fixed (SSIM 0.998).
- `test-daemon.py` passes 49/49; its 12-byte-cut control fails as it should.
- Browsers: see ADRENO-640-PARITY.md. Mali keeps VP8 off (livecd-desktop 39).

## Encoding quality and application boundaries

- Firefox's experimental WebRTC and WebCodecs H.264 picture checks pass on
  the installed patched pair. Five frame-rate/bitrate cases pass, but a 2 Mb/s
  to 500 kb/s change produces 1.151 Mb/s over the next 60 pictures. The daemon
  log proves the correct new target reached `AMediaCodec_setParameters`.
  Record per-packet size/PTS over a longer run to distinguish firmware
  convergence from ignored updates, then qualify real congestion control.
  Keep the default off meanwhile ([details](encode-firefox.md)).
- Chromium MediaRecorder's hardware H.264 output has wrong colour signalling.
  Inspect frame colour space and range through `VideoTrackRecorder`,
  `H264VaapiVideoEncoderDelegate::UpdateSPS`, packed SPS handling and the
  daemon's MediaCodec colour keys. Existing transport carries no such keys.
  Correcting RGB conversion only in the test would hide the bug. Compare
  full/limited BT.601/709 controls, WebCodecs and WebRTC before shipping a fix.
- Chrome WebCodecs requests native pixmaps and crashes on shared-memory
  input. A launcher flag cannot replace Chromium's source patches. See
  [Chrome handoff](encode-chrome.md). The newly qualified default is WebRTC.
- HEVC Main10 encode: done 2026-11-18 (see ADRENO-640-PARITY.md). HDR10 static metadata is not passed.
  Previously: HEVC Main10 HDR10 encode is registered, but the bridge's encoder input is
  NV12 only. It needs a separately negotiated P010/surface input path and
  colour/HDR metadata; the decode work alone does not enable it.

## Other gaps

Measure 4K/8K throughput and frame correctness rather than assuming registry
maxima are achievable through the copied bridge path. Preserve the known
Chrome compositor/frame-sync failure in acceptance results. The session's
ION warning still needs a scoped allocator solution; globally preloading
the dma-heap emulation can change Turnip/PanVK allocation policy and is not
an accepted fix. OpenCL and WebGPU remain unqualified; stock-only Android
buffer/protected graphics and Qualcomm extension gaps are in the report.
