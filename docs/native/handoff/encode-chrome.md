# Handoff: Google Chrome hardware encoding

State on 2026-11-15. Chrome is Google's prebuilt glibc binary under Bionilux; it cannot be
patched. Shared rules and pass criteria: [README.md](README.md).

## Status

**Note10+ update, 2026-11-16:** Chrome now selects the source-built glibc VA driver
already shipped in `android-vaapi-glibc` under `mali/`, on Adreno too. Turnip
still renders the browser. `source_built_driver()` selects this path only from a
validated stack; older stacks without it retain their previous driver and keep
Adreno encoding off. No device-specific opt-in is needed.

The private launcher passed H.264 WebRTC at 640x360 with 288 input and output
pictures on `OMX.qcom.video.encoder.avc`. All five colour samples, including the
bottom rows, passed. The prebuilt-driver negative control failed the size check.
HEVC, H.264 and fast H.264 playback also passed the private fullscreen suite.
Evidence: `temp/parity-note10-20261116/{chrome-encode,chrome-srcdrv,resume}`;
runner: `tests/video-encode/test-browser-encode.py`. CI package installation and
installed-launcher verification are recorded in [the parity report](../ADRENO-640-PARITY.md).
The WebCodecs limitation below still applies.

The following records the earlier state and its diagnosis.

**On by default on Mali** since 2026-11-15, by the user's decision: the launcher adds
`AcceleratedVideoEncoder` for Chrome when the video device is `/dev/mali0` (livecd-desktop
0.2.0-20). WebRTC encodes on the Exynos encoders. WebCodecs hardware encoding still crashes the
GPU process, and that cannot be fixed outside Chrome (see "Consequence" below). Adreno stays off:
on the Note10+ (2026-11-16) WebRTC H.264 encoded in hardware, but Chrome there uses the prebuilt
glibc driver, which encodes the 16-aligned surface uncropped, so 640x360 arrived as 640x368 with a
green band at the bottom (received frame viewed). Switching Adreno Chrome to this project's glibc
driver build, as on Mali, is the likely fix.

Tested on the S20 (`x1s`), Chrome 157.0.8103.78, Bionilux 0.5.0-2 preload (CI 43665869060),
private display and private `termux-va`, 640x360 loopback:

| Use | Adreno | Mali (S20) |
| --- | --- | --- |
| WebRTC, software | **passes** (2026-11-16), received 640x360 | **passes** with Bionilux 0.5.0-2: 1+1 ICE candidates, connected, 278 frames, received picture right. With 0.5.0-1: 0 candidates, never connects |
| WebRTC H.264, with `AcceleratedVideoEncoder` | encodes on `OMX.qcom.video.encoder.avc` but at 640x368, green band (2026-11-16) | **passes**: `VaapiVideoEncodeAccelerator` in `kEncoding`, daemon session on `OMX.Exynos.AVC.Encoder`, 278 frames encoded and decoded, received frame viewed (hue field and white bar clean) |
| WebRTC VP9, with `AcceleratedVideoEncoder` | not run | **passes**: same, on `OMX.Exynos.VP9.Encoder`, 280 encoded, 279 decoded, frame viewed |
| WebCodecs `VideoEncoder` | not run | **crashes the GPU process** (exit code 5) as soon as frames arrive; the page gets `OperationError: Encoding error.` |

## Fixed: no network for WebRTC

Chrome's `AddressTrackerLinux` lists interfaces over its own `NETLINK_ROUTE` socket. Android's
SELinux refuses it three things from the Termux app: `bind()` with multicast groups, `bind()`
without groups, and the `RTM_GETLINK` dump (both with `EACCES`). Chrome gave up after the bind,
so WebRTC saw no interfaces. `packages/bionilux/0002-netlink-route.patch` (revision 2) makes the
preload report a refused netlink bind as success (the kernel binds on the first send) and answer a
refused `RTM_GETLINK` dump with `RTM_NEWLINK` messages built from `ioctl()`, queued for the next
`recv`. That is what Termux's own Chromium does in source (`1013-chromium-net-address-tracker.patch`).
Live network-change notifications stay unavailable, as in Termux's Chromium. The `RTM_GETADDR`
dump is allowed and untouched. Set `BIONILUX_DEBUG=1` to see the hooks act.

Not yet installed on the phone; the test used the CI build through `BIONILUX_PRELOAD`.

## Not fixable here: the WebCodecs crash

Same cause as Chromium revision 1 ([encode-chromium.md](encode-chromium.md)): on Linux
`VideoEncodeAcceleratorAdapter` always asks for GPU-memory-buffer input (NV12), and the GPU process
`CHECK`s that the buffer is a native pixmap. Here those buffers are shared memory. The choice is an
`#if BUILDFLAG(IS_LINUX)` in the adapter with no flag or feature to turn it off, so only a source
patch changes it (Chromium's `0100` + `0101`). WebRTC is not affected because it hands the encoder
I420 shared-memory frames.

Reassessed 2026-11-17 against Chromium 156's source: the choice is
`#if BUILDFLAG(IS_LINUX) || BUILDFLAG(IS_CHROMEOS)` in
`VideoEncodeAcceleratorAdapter::InitializeOnAcceleratorThread`, which turns `InputBufferKind::Any`
into `GpuMemBuf` and sets `StorageType::kGpuMemoryBuffer`; no switch, feature or field trial reads
around it. WebRTC uses `RTCVideoEncoder`, which never takes this path. Still no supported route.

A bridge-side fix would need Chrome to have real native pixmaps (GBM dma-bufs under Ozone/X11) and
the VA driver to import them. Neither exists for Termux, so this is not a bridge change.

**Consequence:** enabling `AcceleratedVideoEncoder` for Chrome gives WebRTC hardware encoding but
makes any page that uses WebCodecs with hardware allowed (the default `no-preference` included)
crash the GPU process; after repeated crashes Chrome disables GPU acceleration for the session.
The user chose WebRTC hardware encoding over this on 2026-11-15. To turn it off, remove
`AcceleratedVideoEncoder` from Chrome's branch in `command_line()`.

## Next steps

1. Keep the installed-launcher acceptance in the [Note10+ report](../ADRENO-640-PARITY.md)
   current when the glibc stack or Chrome changes.
2. MediaRecorder on Adreno recorded correct-colour software output, with no hardware
   session; investigate before claiming hardware recording support.
3. HEVC encoding is unqualified. The WebCodecs native-pixmap failure above still needs
   a different buffer integration or a patchable browser build.

## Where things are

| What | Where |
| --- | --- |
| Netlink fix | `packages/bionilux/0002-netlink-route.patch` |
| Chrome flags | `command_line()` in `src/native/acceleration.py` |
| Phone runners and results | `~/encode-chrome-test` on the S20 (`rt.sh`, `wc.sh`, `out-rtc-*`, `out-wc-avc`) |
