# Handoff: Chromium hardware encoding

State on 2026-11-14. Chromium is this project's source build (`packages/chromium`). Shared
rules and pass criteria: [README.md](README.md).

## Status

**Off by default.** No launcher passes `--enable-features=AcceleratedVideoEncoder`.

| Use | Adreno | Mali (S20) |
| --- | --- | --- |
| WebRTC, H.264 and VP9 | not run | **works behind the flag**: loopback, about 284 frames per codec, hardware encoder and decoder, received colours exact, no GPU crash |
| WebCodecs `VideoEncoder` | not run | **crashes the GPU process** with the flag on; revision 2 patch being built |
| MediaRecorder | not run | not run |

## Why the flag stays off

The same flag turns on both WebRTC and WebCodecs hardware encoding. WebCodecs crashes:

- On Linux, `VideoEncodeAcceleratorAdapter` always asks for `kGpuMemoryBuffer` input frames
  (`media/video/video_encode_accelerator_adapter.cc`). The GPU process then calls
  `CreateGpuMemoryBufferHandle()`, which does `CHECK_EQ(handle.type, gfx::NATIVE_PIXMAP)`
  (`media/gpu/chromeos/platform_video_frame_utils.cc`). Here GPU memory buffers are plain shared
  memory, so the check aborts (SIGTRAP).
- Chromium restarts the GPU process three times and then turns GPU acceleration off for the
  session. Any page using WebCodecs with `prefer-hardware` would do this.

WebRTC works because it sends ordinary shared memory (I420) and the driver uploads it with
`vaDeriveImage`/`vaPutImage`. **Never add `--video-capture-use-gpu-memory-buffer`**: it switches
WebRTC to the crashing path.

## The fix in progress: Chromium revision 2

[`0100-termux-webcodecs-shmem.patch`](https://github.com/cnshing/debian-livecd-termux/blob/fix/chromium-webcodecs-shmem/packages/chromium/0100-termux-webcodecs-shmem.patch),
on the CI branch `fix/chromium-webcodecs-shmem` only. It makes the adapter use `kShmem` input
and CPU frame preparation. Its Chromium regression test covers ordinary CPU frames and mappable
shared-image frames, but has never been compiled or run.

The build is a two-job chain, because Chromium alone nearly fills a six-hour CI job:

1. A dependency bootstrap builds and uploads Chromium's dependency packages, then dispatches the
   browser build. The artifact is named by the `packages/chromium` recipe's hash. **Do not change
   `packages/chromium` while the chain runs**, or the browser job will not find its
   dependencies.
2. The browser build. Run [43579240070](https://github.com/cnshing/debian-livecd-termux/actions/runs/43579240070)
   started 2026-11-14 09:10 UTC and was still running at 12:05 UTC.

The chain first failed at upload: an artifact refuses the colon in an epoch file name
(`ca-certificates-java_1:…`). The workflow now leaves the epoch out (on main as `52e7224`).

## Next steps

1. When 43579240070 finishes, stage the package privately on the S20 (extract it; do not
   install). Run WebCodecs with `bitrateMode: "constant"` (Chromium refuses variable bitrate on
   VA-API outside ChromeOS, and WebCodecs defaults to variable), save the chunks, and decode them
   in software to check pixels. Then H.264 and VP9 WebRTC. **Stop at the first GPU-process
   crash**; never let it loop.
2. If both pass, add `AcceleratedVideoEncoder` to Chromium's features in `command_line()` in
   `src/native/acceleration.py`, on Mali. Gate it on the installed package version read from
   dpkg (revision 2 or later): the receipt `share/doc/chromium/livecd-vaapi.json` has no revision
   field, and adding one costs another six-hour build. The host test
   `test_glibc_mali_driver_precedes_the_prebuilt_mesa` in
   `tests/packaging/test-mali-acceleration.py` asserts the flag is absent today; update it.
3. A software fallback that works is not a pass. Require confirmed hardware frames in the daemon
   log, a clean flush, correct software-decoded pixels, and a WebRTC loopback with no GPU crash.
4. Run the same on the Note10+, which has never had a browser encode test.
5. Merge the branch's packages to main once accepted.

Also open: the Exynos encoders refuse MediaCodec's `low-latency` key, so call latency is
unmeasured.

## How to test

On the S20, private display and private daemon. The probes are in Git on the CI branch:
[`tests/video-encode/webcodecs.html`](https://github.com/cnshing/debian-livecd-termux/blob/fix/chromium-webcodecs-shmem/tests/video-encode/webcodecs.html)
takes `codec=avc1.42001f` or `vp09.00.10.08` and `input=canvas` or `bt709` in its query string,
and `save=1` posts the chunks to `/chunks` for software decoding. Serve it on localhost, run the
browser on a private display with its own `XDG_CONFIG_HOME`, and read `window.RESULT`. The
canvas input is the acceptance case; `bt709` is a control. The earlier WebRTC loopback page and
runner are not in Git.

## Where things are

| What | Where |
| --- | --- |
| Patch | `packages/chromium/0100-termux-webcodecs-shmem.patch` (CI branch) |
| Bootstrap and reuse | `.github/workflows/packages.yml` (CI branch) |
| Browser flags | `command_line()` in `src/native/acceleration.py` |
| History | [VIDEO-ENCODING-HANDOFF.md](../VIDEO-ENCODING-HANDOFF.md) |
