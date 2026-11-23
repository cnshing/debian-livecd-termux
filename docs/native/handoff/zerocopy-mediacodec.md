# MediaCodec dma-buf work on Note10+ (2026-11-22)

This work is **in progress**. No zero-copy transport is enabled in the shipped
bridge or daemon. The independent Main10 frame-limit fix is described below.
The original brief is `temp/parity-note10-20261116/handoffs/zerocopy.md`;
its coordination rules still apply. Worktree: `/home/cs/wt-zerocopy`, branch
`work/zerocopy`. Private evidence and probe sources:
`temp/parity-note10-20261116/zerocopy/`.

## Main10 input limit

`termux-va/0040-main10-4k-frame-cap.patch` and
`android-vaapi/0140-main10-4k-frame-cap.patch` allow 32 MiB raw frames **only
for Main10 sessions**. Packed 4096x2304 P010 requires 27 MiB. The daemon's
staging allocation, frame-length check and MediaCodec maximum input size use
the larger limit for that codec. The bridge's sender uses the same limit.
Both copies of `tva_protocol.h` gain the same constant; no wire IDs change.
The bridge also scales the direct-read byte offset and row width by the sample
size. The earlier direct-read path used sample counts as byte counts even for
P010, copying only half a row; the mapped fallback already used byte counts.
8-bit sessions retain their 16 MiB limit, allocation and configuration.
The existing Qualcomm Main10 startup probe still controls advertisement;
Mali has no new format, codec or transport enabled.

Private daemon results: 3840x2160 and 4096x2304, four changing P010 pictures
each, Main10 output, exact key-frame requests at pictures 0 and 2, PSNR
54.29–56.38 dB. Swapped-chroma controls fail (16.74–16.76 dB); the installed
revision-6 daemon explicitly rejects the large input. Existing daemon suite:
49 passed, 0 failed. Pictures from the initial 4K run were opened.
Reproduce with `tests/video-encode/test-main10-4k.py`; the script exercises a
private daemon, so it alone is not default-session acceptance.

CI run **45103922827 is void and cancelled; never install its debs** (it predates
the P010 row-width fix). Replacement run 45105056762 passed and built
android-vaapi 20, android-vaapi-glibc 15 and termux-va 7 from 14f1883. All three
were installed through the phone's existing local APT repo under the atomic
install lock, without downgrades; desktop restarted, `livecd validate` 30/30,
lock released. The original installed stack fails the same 4K encode.

`livecd exec -- python test-main10-4k.py --vaapi` now passes **3840x2160 and
4096x2160** through the default installed VA driver/shared daemon: four pictures
each, exact keyframes 0/2, minimum PSNR 54.29/55.64 dB, swapped-chroma controls
16.74–16.76 dB. Source and decoded 4K pictures were opened and compared. Installed regressions:
FFmpeg **46/46**, daemon **49/49**, H.264/HEVC/VP9/VP8 decode **48/48 bit-exact
each**, and Main10 4K P010 decode **4/4 bit-exact** against software.
WebRTC passes through the installed launchers in Chromium, Chrome and Firefox;
Chromium and Firefox WebCodecs each pass 60 hardware pictures. Firefox's first
desktop-wrapper attempt closed its automation connection before any encoder
session; a runtime/control run and a fresh desktop-wrapper retry both pass.
An earlier Firefox invocation used the package binary directly and bypassed the
managed runtime; that attempt is not default-install evidence. Chrome
WebCodecs remains skipped per the original brief.
4096x2304 remains a **private daemon** result: VA advertises a maximum height
of 2176 and FFmpeg refuses 2304 before sending a frame. Expanding that advertised
bound was not part of the 3840x2160 input-cap fix. No Main10 real-time rate is
claimed; this path still copies.

## A working GPU-to-encoder prototype

All probes ran as the ordinary Termux UID, with synthetic input and no live
display or camera. Clear LD_PRELOAD and LD_LIBRARY_PATH when running them:
Android's stock EGL/GLES must execute this part, rather than Termux Mesa.

1. Stock EGL initializes; AHardwareBuffer allocation and handle export work.
   It lacks `EGL_EXT_image_dma_buf_import`. An arbitrary dma-buf cannot simply
   be passed to the usual Linux EGL import call.
2. The device exports `AHardwareBuffer_getNativeHandle` and
   `AHardwareBuffer_createFromHandle` from `libnativewindow.so`. These are
   VNDK interfaces, not a portable public-NDK arbitrary-fd import API.
3. Allocate an AHB descriptor as a **layout/metadata template**, clone its
   native handle with the pixel fd replaced by a separate ION allocation,
   then call createFromHandle with method CLONE (3). This succeeds on this
   device. CLONE duplicates the handles: a later test releases the original
   allocation before rendering two imported buffers and still passes. Retain
   each imported AHB while its EGL image is in use; do not mutate or close
   handles owned by the original AHB.
4. Import the resulting AHB as an EGLImage, bind as an external texture, and
   sample with `GL_EXT_YUV_target`'s `__samplerExternal2DY2YEXT`.
5. Choose an **EGL YUV window config**, and write `layout(yuv)` fragment
   output directly to MediaCodec's input surface. Requiring
   `EGL_RECORDABLE_ANDROID=true` filters out the working YUV config on this
   phone; removing that requirement succeeds. RGB configs work but clip
   saturated input through the YUV→RGB→YUV round trip.

The working `ion-yuv2.c` prototype uses the installed
`livecd_dma_heap_alloc("system", size, O_RDWR|O_CLOEXEC)` through a private
dlopen. It writes the synthetic ION source once; every submitted picture then
travels through the GPU to MediaCodec without a CPU frame copy. It is **not**
yet connected to a VA surface or a cross-process fd sender.

Measured H.264: 120/120 at 64.91 fps, stock Qualcomm Adreno 640 renderer and
OMX.qcom.video.encoder.avc. The first decoded NV12 picture is byte-for-byte
identical to the source. HEVC returns 120/120 at 71.70 fps. All 120 pictures
were decoded and compared for both codecs: minimum PSNR 83.30 dB (H.264),
64.18 dB (HEVC). Disabling the shader's U/V correction fails at 16.78 dB.
The decoded gradient was opened.

A second probe alternates **two independent ION buffers**, releasing their AHB
allocation template before rendering. It returns 120/120 pictures at 66.42 fps
(H.264) / 70.32 fps (HEVC). Every decoded picture matches the correct alternating
reference at minimum PSNR 49.91 / 57.98 dB; a one-picture reference shift fails at ≤9.00 dB.
A crop probe selects 1920x1080 at source origin **(16,32)** from a 3840x2160
YUV pattern with changes in both axes: 120/120, minimum PSNR 84.01 dB; picture
opened. These tests establish those cases for the standalone renderer, not the
VA-API transport or arbitrary imported resource layouts.

Raw MediaCodec output lacks reliable demuxer frame timing (the H.264 parser
reports a default average 25 fps for this output). Force both comparison inputs
to the same frame rate when checking the alternating references; a mismatched
clock otherwise produces false order failures.

Critical details from the experiments:

- **Swap interval 1 is required.** Interval 0 dropped pictures (54/120).
  Counting submissions alone would have produced a false throughput pass.
- Flexible AHB format 35 is **NV21**, not NV12, on this phone. At 3840x2160:
  Y stride 3840; Cr starts at 8355840; Cb at 8355841; both chroma pixel
  strides are 2. The luma allocation has 2176 rows (32-row alignment).
  The standalone NV12 source deliberately uses that memory layout with U/V
  reversed relative to the handle, and the raw-YUV shader uses `.rbg` to
  restore Y/U/V. Do not pass it through the ordinary RGB external sampler.
- AHB allocation is 12533760 bytes, with two fds and 22 ints in its Qualcomm
  handle. Vendor format requests 0x109 and 0x7fa30c04 are refused (-EINVAL).
  Do not treat these handle counts as a portable ABI or synthesize the ints.
- The bridge currently aligns visible buffer dimensions to 16, pitch to 64
  and UV offset to a page. Its layout is not generally the AHB layout. An
  importer must explicitly compare pitch, UV offset, allocation size and
  dimensions before using a handle template. Four-k parity of one offset is
  not proof that 854x480 or nonzero crop origins work.
- `ffmpeg psnr` may insert a colour-space conversion if one input is tagged
  BT.709 and the raw reference is untagged. Convert both to yuv420p and set
  matching range/matrix first, or compare decoded NV12 bytes directly. The
  mismatched-tag comparison reported 33.46 dB for byte-identical samples.

## Decoder feasibility probe

A private 4K H.264 keyframe can decode to an ImageReader surface. After EOS
(the clip uses reordering), AImageReader returns a hardware buffer with two fds,
22 ints, 3840x2160, stride 3840, format **0x7fa30c06** (Qualcomm UBWC), pixel
allocation 12599296 bytes. A CPU-read + GPU-sampling consumer request did not
force linear NV12. `AHardwareBuffer_lockPlanes` returns one plane with zero
row/pixel strides; AImage reports three planes but chroma data length 1 and
zero strides. Those values are not usable plane descriptors. Do not infer
bit-exact output or attempt CPU reads using them. The initial unguarded private
probe exited while reading the invalid plane metadata; its guarded source
fails explicitly instead. No desktop process was involved.

Next options: request a proven linear decoder output, import the actual
compressed modifier correctly, or perform a raw-YUV GPU blit from this AHB
into a linear shared buffer. Returning this fd as `DRM_FORMAT_MOD_LINEAR`
would be incorrect. No decoder throughput or correctness result is claimed.

## Remaining implementation and acceptance

The next step is a robust negotiated fd transport and ownership scheme,
retaining source resources until the encoder has consumed them. Coordinate
`tva_protocol.h`, `tva_client.c`, `tva_bridge.c` and daemon changes with the
webgpu-map lane; claim append-only values before using them. Producer GPU
fences must complete before stock EGL samples the source; the existing encoder
input-fence fix must remain effective. Stock EGL symbols must be loaded
explicitly so a desktop's Mesa libraries cannot intercept calls.

A startup qualification must prove the actual import and encode path with
known pixels, not just the presence of ION or EGL extensions. Keep a copy-path
negative control and safe fallback for unsupported layouts and failed probes.
Do not change Mali defaults without equivalent-device evidence.

Pending, not qualified:

- Default installed 4K60 H.264/HEVC via the VA bridge, dynamic pictures,
  SSIM/PSNR, frame ordering, exact keyframes and nonzero-origin crop tests.
- Decoder ImageReader/AHB output and dma-buf surface ownership. ByteBuffer
  output still copies; no decode throughput gain is claimed.
- Browser and mpv integration. Browsers consume the VA path, whereas mpv
  defaults to FFmpeg's separate MediaCodec path; neither benefits merely
  because this standalone encoder probe runs quickly.
- Those checks must be repeated for the eventual zero-copy transport. The
  independent Main10 cap/P010 fix has completed CI → local APT → installed
  session verification and the regression checks above.

Shared SSH is in use by webgpu-map. Do not remove its key or stop sshd while
that lane is active. Every private process started by the completed probes
has exited; test assets remain in `~/pl-zerocopy/` for reproduction.

API references:
[public AHardwareBuffer API](https://developer.android.com/ndk/reference/group/a-hardware-buffer),
[Media NDK](https://developer.android.com/ndk/reference/group/media),
[VNDK handle wrapper](https://android.googlesource.com/platform/frameworks/native/+/refs/heads/main/libs/nativewindow/include/vndk/hardware_buffer.h).

## Production transport candidate (2026-11-23)

Branch `work/zerocopy`, implementation `dae45d5`, adds the shared negotiated
transport in patches 0050 (daemon) and 0150 (both Mesa builds). Reserved package
revisions are android-vaapi 21, android-vaapi-glibc 16 and termux-va 8.
CI **45178853855** is the candidate; **45178009861 is VOID/cancelled**.
At this checkpoint these debs have not been installed. The normal desktop still
uses the previously qualified copy transport.

Explicit opt-in: `TVA_SURFACE=1` in the daemon environment and
`TVA_ZEROCOPY=1` in the VA client environment. Setting either to `0` preserves
the copy route. H.264/HEVC 8-bit encoder sessions and 8-bit decoder sessions can
negotiate the new path; Main10 and VP8 encoding keep their existing paths.
No Mali default is changed. Startup pixel/codec qualification and enabling this
by default remain outstanding; symbol/configuration discovery is not that proof.

Append-only protocol reservations: `XFER_DMABUF=2`, encoder length-word bit 29
`ENC_UNIT_DMABUF`, decoder sentinel `0xFFFFFFFD`. Existing protocol versions,
inline/SHM framing and color bits retain their values. One marker byte carries
exactly one CLOEXEC SCM_RIGHTS fd, followed by eight big-endian words:
NV12 fourcc, allocation width/height, pitch, UV offset, allocation size, crop x/y.
The decoder header carries its input-unit index before the marker. Missing,
extra and truncated rights fail without leaking received descriptors.

The encoder validates native layout against a fresh gralloc allocation before
cloning a handle. Mismatching valid linear layouts take a CPU upload fallback;
invalid bounds fail. Source GPU fences remain mandatory. Source Gallium
resources stay referenced until the corresponding encoded packet is completed
on the application thread. The stock EGL/GLES libraries are loaded explicitly;
contexts belong to session threads and the EGL display is process-wide.

Decoder UBWC buffers are sampled with `GL_EXT_YUV_target` into linear gralloc
buffers, with U/V arranged as NV12 in physical memory. AImage ownership extends
through GPU completion. The exported pixel fd retains storage independently of
the released gralloc wrapper. The Mesa reader transfers fd ownership to its
pending picture; the application thread imports/copies both planes and waits
for completion before closing the fd. Screens that cannot import use a visible
row staging fallback. No UBWC fd is labeled linear.

Private actual-daemon acceptance (not yet installed VA acceptance):

- 120/120 encoded packets per codec: H.264 **63.75 fps**, HEVC **63.79 fps**.
  The separate changing-picture test has exact keys 0/2 and minimum per-plane
  PSNR **42.27 / 48.34 dB**. Reference and decoded metadata/timing are normalized
  for comparison. Encoded gradient and decoded test chart PNGs were opened.
- H.264 and HEVC decoder output: **120/120 bit-exact each**, indexed by input
  picture rather than output order. Separate no-hash transport runs measured
  **70.36 / 69.48 fps**; these omit the final Gallium destination copy.
- An initial fixture sent an SPS/PPS plus IDR in one unit at the second GOP.
  The existing protocol classifies a leading parameter set as CSD, so that
  fixture lost a picture. Splitting parameter sets into separate units, as the
  VA bridge does, passes both complete clips. This was a fixture error.
- The shared fd helper's host test passes identity, CLOEXEC, missing/extra/
  truncated rights, wrong marker, EOF and descriptor leak checks. Both changed
  Mesa C files pass syntax checks with the Android cross compiler; the daemon
  builds with warnings enabled.

Reproduction: `tests/video-encode/prepare-surface-fixtures.py` prepares synthetic
H.264/HEVC clips and per-input-picture references. On Android run
`test-surface-transport.py --daemon PATH --out NEW_DIRECTORY --decoder-assets
DIRECTORY`. It starts only its own private daemon. Compile
`test-dmabuf-fd.c` against the patched common header for host descriptor checks.
Evidence on the phone: `~/pl-zerocopy/transport-acceptance-r1/`; earlier focused
runs are `protocol-surface-r2`, `protocol-surface-r3` and
`protocol-surface-decode-r3`. Host source/build scratch is
`/home/cs/zerocopy-src/`; `update-patches.py` regenerates candidate patches from
`tva-base`/`mesa-base` and the corresponding modified source trees.

Still required: CI → local APT → installed VA encode/decode, dynamic 4K pixel
and crop/ordering tests, copy negative controls, browser/mpv integration checks,
regressions and startup proof before default enablement. Private transport
throughput must not be reported as end-to-end installed VA throughput.
