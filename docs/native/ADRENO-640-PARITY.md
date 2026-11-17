# Note10+ GPU and hardware video parity investigation

Device: Galaxy Note10+ SM-N975U1, Snapdragon 855 / Adreno 640, Android 11.
Measurements started 2026-11-16. This is a dated device qualification record;
general driver capabilities belong to the [upstream sources](../../README.md#upstream-support-and-local-verification).
It does **not** establish complete feature parity.

The original Claude worker was `a25ae11189da88823`, “Note10+ SD855 capability
parity”, in session `bb1b5005-2d30-4906-b8de-c5b75fd81909`. It stopped at its
usage limit. Codex continued its uncommitted work in `/home/cs/wt-parity-note10`.
Local evidence is under `temp/parity-note10-20261116/`; its `resume/` directory
preserves the original changes and records continuation results.

## Changes qualified during continuation

Chrome selects the patched source-built glibc VA driver, already included in
`android-vaapi-glibc`, when a validated stack contains it. That driver uses
CPU-written dma-buf surfaces while Android MediaCodec executes the hardware
codec; Turnip still renders Chrome. The prebuilt glibc VA driver omitted cropping
for 16-aligned encoder surfaces. No per-phone setting is needed. Without the
source-built variant Adreno Chrome keeps encoding off. Explicit video overrides
still apply. Mali retains its existing driver and encoding policy.

Private launcher result: Chrome H.264 WebRTC, 288 pictures encoded and returned
by `OMX.qcom.video.encoder.avc`, correct 640x360 size and five sets of colour
checks including the last rows. Saved pictures were inspected. The prebuilt
driver control failed the size check. Original worker's HEVC, H.264 and fast
H.264 private fullscreen playback tests passed with the same driver.

CI and installed-launcher results will be added after package qualification.

## Remaining qualification

The capability baseline, 10-bit transport, VP8 bridge support, Firefox encoding,
MediaRecorder colour signalling and GPU extension differences are still being
investigated. Do not infer support from a codec's presence in MediaCodecInfo;
verify the selected component, negotiated output format and decoded pixels.

Reproduce a browser encoder test with synthetic input, its own display, daemon
socket and profile:

```sh
python tests/video-encode/test-browser-encode.py chrome --out ~/p/chrome-encode
```

Use a new short output path for every run. The test fails on wrong size,
colour, missing hardware sessions or GPU crash. Firefox experiments require
`--firefox-encode`; that switch does not change the installed default. Do not
run the hardware Chrome WebCodecs path repeatedly: its prebuilt binary's native
pixmap assertion remains unresolved ([details](handoff/encode-chrome.md)).
