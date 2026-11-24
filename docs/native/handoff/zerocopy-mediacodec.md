# MediaCodec dma-buf work on Note10+ (2026-11-22)

Production surface transport is delivered on main (7e7e998, 2026-11-23).
A static review on 2026-11-24 found two bugs and three untested cases; the
fixes and their tests are in "Review follow-up (2026-11-24)" at the end. The
sections from "Main10 input limit" to "Remaining implementation and
acceptance" are the earlier prototype checkpoints, kept for history and
superseded by "Production transport candidate" onwards. Default enablement requires both Adreno client detection and the
daemon's actual startup pixel round trip. Main10 encoding retains its copy path.
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

## Remaining implementation and acceptance (superseded prototype plan)

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

Pending at the prototype stage, all since delivered or listed under the final limitations:

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

At the prototype stage the shared SSH key was also in use by webgpu-map. Both
lanes have finished; the key was removed and sshd stopped. Every private process started by the completed probes
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


### Startup qualification and final candidate

The follow-on implementation replaces opt-in discovery with a startup pixel
round trip: a separate fd is cloned into a real gralloc handle, sampled through
raw YUV into each encoder's input surface, decoded into an ImageReader surface,
then GPU-converted into linear NV12. Sixteen spatial Y/U/V sample triplets must
match the known pattern within six codes. A deliberate U/V import error fails
both qualifications and selects copy transport. No extension-only result can
enable it. `TVA_SURFACE=0` disables this probe/path; `TVA_ZEROCOPY=0` requests the
client copy transport. Main10/VP8 encoding and Mali retain their copy paths.

Surface handshake responses are deferred until codec/window/EGL setup succeeds.
An injected setup failure negotiates inline encoding or SHM decoding before any
input is submitted. The decoder's context is released by the configuring thread
and acquired by its output thread. A legacy inline client remains byte-compatible.
The default client requests fd transport, but the daemon grants it only after
startup qualification and successful session preflight. Only freedreno's NV12
allocations gain the matching padding; Mali allocation defaults are unchanged.

Private final-candidate transport: H.264/HEVC encode 120/120 at 66.27/67.92 fps,
minimum changing-picture plane PSNR42.11/44.38dB; swapped-chroma controls reject
every frame. H.264/HEVC decode120/120 bit-exact, separately timed without hashing
71.10/94.80fps after session initialization. These are still transport-only rates.
Production transport cropping1920x1080 from3840x2160 at(16,32), using a picture
varying in both axes, passes with plane minima66.31/60.29dB and exact keys 0/2.

`test-surface-fallback.py` passes qualified modes[2,2], opt-out[0,1], deliberately
bad import[0,1], session setup failure[0,1] and legacy-client[0,0], in encoder/
decoder order. It checks the startup proof log as well as negotiated modes.

CI 45178853855 failed before compilation because the Termux builder strips EGL
headers. The recipe now declares libglvnd as a **build-only** header dependency;
runtime graphics are explicitly loaded from stock Android, with no EGL/GLES
link dependency. CI 45179828877 predates the startup qualification and is VOID
for final installation. A replacement build follows the qualification commit.
No candidate deb has yet been installed at this checkpoint.


## Installed production checkpoint (2026-11-23)

The phone now has android-vaapi **22**, android-vaapi-glibc **17** and
termux-va **9**, delivered through CI debs and the local APT repository.
Mesa packages: CI **45189264023**, source b3d3086; daemon: CI **45186614640**,
source 58f0559. Desktop 49 and android-webgpu0.1.0-1 from the other lane remain
installed. The default daemon passes both AVC and HEVC startup pixel probes.
There is no private driver, socket or library-path override in these VA tests.

Revision 8 exposed a packaging/runtime mismatch: Termux's libandroid shim lacks
AHardwareBuffer_lockPlanes even though the stock library supplies it. Revision 9
resolves hardware-buffer/window operations from absolute stock libandroid;
EGL/GLES are also stock dispatch. A temporary library-path recovery for 8 was
removed by the default 9 desktop restart. No installed package binary was edited.

Patch0152 adds cache-synchronized CPU VAImage uploads into Adreno linear NV12
surfaces, real encoder-consumption fences and durable heap-owned feedback.
Without durable feedback, completing jobs older than the eight-slot ring could
lose their encoded length at async_depth 16. Source reuse now waits for the
corresponding encoded packet, while mapping the coded buffer still retires
feedback normally. TVA_CACHED_UPLOAD=0 isolates the old uploader;
TVA_ZEROCOPY=0 disables the new upload and fd request together.

### End-to-end measurements

All rates below include FFmpeg startup unless explicitly labeled warm. These
are moving testsrc2 pictures through the installed VA API, not private fd rates.

| Installed path | H.264 fps | HEVC fps | Frames |
|---|---:|---:|---:|
| Original20/15/7 copy baseline |21.66|22.07|120|
|22/17/9 default FFmpeg queue depth 2 |37.99|40.43|120|
|22/17/9 async_depth 8 |51.01|56.30|240|
|22/17/9 async_depth 8, longer run |54.23|60.44|600|

Every picture in these runs passes PSNR/SSIM; exact IDRs are at multiples of 60.
Long-run minimum plane scores are H.264 Y37.32/U37.88/V36.26dB, HEVC
Y37.14/U37.71/V36.68dB; minimum SSIM0.982332/0.981512. The explicit 55 fps
acceptance check still fails H.264 54.23. Do not claim default queue 2 reaches60.
The raw surface transport separately achieves66.39/66.93fps with 120 alternating
independently owned buffers, all-frame PSNR/SSIM and wrong-chroma controls.
That number excludes the VA upload and is not an installed application rate.

Installed default H.264 decode (480 pictures, warmed) measured65.98fps versus
60.48fps with TVA_ZEROCOPY=0. H.264 and HEVC 4K120/120 pictures each are bit-exact
against software. The native isolated reference was approximately71fps; an
FFmpeg direct-MediaCodec CLI rerun measured50.11fps and is a different pipeline.
The decoder still GPU-copies into the VA destination surface. It eliminates
CPU socket-frame copies, not every GPU operation.

### Corrected validation findings

The original C crop harness aliased the upload source and encoder CurrPic
reconstruction surface. Mesa is allowed to replace the reconstruction storage;
this invalid test caused the black first picture. The corrected test uses one
input plus two reconstruction surfaces; crop(16,32),1920x1080 from4K passes all
four pictures, exact IDRs0/2, minimum plane PSNR 42.11 dB. Patch 0151 forwards the
upload producer fence as synchronization hardening; the invalid harness did
not establish that it fixed a production black-frame bug.

The FFmpeg sample oracle also needed matching format/range/matrix metadata on
both comparison inputs. The surface encoder announces BT.709, and the raw
reference has no matrix; automatic filter conversion otherwise changes samples
before PSNR (about 22 dB). Matching metadata without transforming sample values
restores about 40 dB. Separate colour-bar signalling and wrong-metadata controls
remain required; this correction must not mask a colour-signalling regression.

Current evidence on phone: pl-zerocopy/vaapi-cached22-default-r1,
vaapi-cached22-depth8-r1, vaapi-cached22-depth8-long, surface22-regress,
and surface22-final. Earlier checkpoints above describe superseded work.


### Browser qualification corrections and final delivery candidate

Installed 22/17/9 browser tests caught two real regressions before publication:

- Chromium WebCodecs full-range input:60/60 packets, but colour error 19 with
  nine frames above 16; TVA_ZEROCOPY=0 gives error 3 and no bad frames. Full-range
  encoding now negotiates copy input, because the startup proof is limited-range.
- Firefox WebCodecs untagged constrained-baseline:60/60 packets, colour error 22
  with 16 bad frames; copy gives error 4. An explicit native BT.601 default did
  not fix this and was discarded. Untagged constrained-baseline also negotiates
  copy. Do not infer range or matrix support merely from the stream metadata.
- Chrome's softpipe VA path crashed before a daemon encoder handshake. 0151
  forwards its upload fence, which softpipe represents as literal `(void *)1`.
  Reading bridge fence magic from that opaque handle caused the crash. 0153
  sends low native handles to the backend fence callback without dereferencing
  them. The changed bridge passes the Android compiler's syntax check.

Mesa 23/18 (9c2f5c1,CI 45325850863) and daemon 11 (21b170a, CI 45326738201) contain
these corrections. Daemon 10 CI 45325641016 passed but is superseded and must
not be installed. CI 45326120914 also produced revision 10: an immediate
after-push dispatch observed the preceding 9c2f5c1 ref. The artifact/version
guard caught it before installation. Replacement 45326738201 is confirmed
on 21b170a. Private daemon 11 passes all seven negotiation/proof controls,
including full-range and untagged baseline downgrade while decoder mode stays 2.
The packages are now installed through local APT, with a desktop restart and
validate 30/30. Final installed acceptance is recorded below.

On installed 22, copy-off 4K 120-picture controls pass at 20.98/21.59 fps with
identical quality minima to the fd path. Depth 16 completes 600 pictures without
the old assertion at 52.92/59.54 fps, with correct images and keys; H.264 still
fails the 55 fps throughput threshold. 854x480, depth 16, 120 pictures passes both
codecs. Final 22 VA crop also passes all 4, minimum Y43.1/U48.1/V42.1dB, keys 0/2.
The 22 browser WebRTC passes were Chromium 287 hardware packets and Firefox 255
across three sessions, but those results do not qualify the final corrections.


## Final installed acceptance (2026-11-23)

APT owns android-vaapi 27.0.0~devel20261029-23,
android-vaapi-glibc 27.0.0~devel20261025-18 and termux-va 2026.10.30-11.
The desktop restarted with its default daemon and startup AVC/HEVC pixel proofs
passing. Desktop 49 and webgpu0.1.0-1 remain installed; validate 30/30 passes and
the install lock is released. CI run 45325850863 is the Mesa source 9c2f5c1;
run 45326738201 is daemon source 21b170a. Their package SHA256 values are:

- android-vaapi:616d57462268488dc5bbe0cb00a7a7671f5a38ec17e84cf26a9bbddb60f71143
- android-vaapi-glibc:6a13369e4180b8e7b99ff906032d8646b5688042be51c1ddc86030e92880a321
- termux-va:d57bb4cbb84588c7de68aca811b228d56d6d97742609ee52964a411a0340ed33

All required installed browser checks pass with the managed launchers and
private displays/profiles. Saved pictures were opened:

| Browser / mode | Hardware encoder pictures | Result |
|---|---:|---|
| Chromium WebRTC |286|Correct 640x360 and colours; fd encoder and decoder|
| Chrome WebRTC |288|Correct 640x360 and colours; existing inline/SHM softpipe route|
| Firefox WebRTC |263 across 3 sessions|Correct 640x360 and colours; copy encoder, fd decoder|
| Chromium WebCodecs |60/60|Software decode 60/60, maximum colour error 3, no frame above 16|
| Firefox WebCodecs |60/60|Software decode 60/60, maximum colour error 4, no frame above 16|

Chromium HEVC and Chrome WebCodecs remain skipped by the user's instruction.
No live-desktop input, cameras, Bluetooth or Android settings were used.

The full installed codec regression passes FFmpeg 46/46 and daemon 49/49,
including profiles, exact IDRs, bitrate, colour signalling and negative controls.
Main10 at 4096x2160 passes 4/4, keys 0/2, PSNR 55.64–56.38dB; wrong chroma scores
16.74–16.76dB. H.264/HEVC/VP9/VP8 decode matches software 48/48 each.

Remaining limitations: H.264's measured 54.2 fps still falls just below the 55 fps
threshold; default FFmpeg queue 2 is 38 fps. Surface colour fidelity for full-range
and untagged baseline input needs separate qualification before enabling those
cases. Main10/VP8 encoding and Chrome softpipe stay on copy transport; Mali is
unqualified and unchanged. mpv uses a separate FFmpeg MediaCodec route, so its
default is unaffected. The final decoder destination GPU copy is retained;
no new direct consumer export or GStreamer integration was added.


Final 23 follow-up checks: both 4K decoders match software 120/120 each, and
all seven installed-daemon negotiation controls pass. The 120-picture 4K
encoder smoke run at queue 8 passes every picture and exact IDRs 0/60;
46.62/52.01fps AVC/HEVC includes startup and is not the longer throughput run.
4K P010 has one recorded startup timeout after SHM negotiation with zero input
units. A fresh default run with tracing, a copy-override control and three
additional ordinary default processes all decode 4/4 bit-exact in under a
second each. The timeout was not reproduced or attributed to a root cause;
it remains a startup reliability follow-up, not a corrected pixel bug.
Final `livecd validate` is 30/30. Installed encode/decode and browser PNGs were
opened, including the nonzero-origin crop.

Evidence: `temp/parity-note10-20261116/zerocopy/production-evidence.tar.gz`
(15,512,391 bytes; SHA256
`8f6167a5fec50f8617ae11878f301316da2bd2f85019a8f01c81c0f5b8fc9bc3`).
It includes logs, packet/frame comparisons, metrics, pictures, colour failure
controls and the original P010 timeout, without private browser profiles.
Phone evidence roots are `~/pl-zerocopy/surface23-browser`,
`surface23-regress`, `fallback-installed11`, `vaapi-final23`,
`decode-surface23-4k` and `p010-final23-reruns`.

## Review follow-up (2026-11-24)

A host-only review of 7e7e998 confirmed the commits, CI runs, deb hashes and
evidence tarball. Its findings and the fixes, on branch `fix/review-followups`
(android-vaapi 24, android-vaapi-glibc 19, termux-va 12):

| Finding | Fix | Test |
|---|---|---|
| Double free: when the encoder session fails with a picture in flight, `tva_codec_get_feedback` frees that picture's feedback, and `tva_codec_destroy` frees it again (patch 0152). Scudo aborts the browser GPU process or FFmpeg. | Patch 0154: `get_feedback` detaches the feedback from its job under `pend_mutex`; completion publishes `ready` under the lock and wakes waiters, so a concurrent completion cannot be freed under it. | `tests/video-encode/test-encoder-failure.py` kills a private daemon mid-encode; FFmpeg must exit without a signal. Against android-vaapi 23 it is expected to abort. |
| Decoder sessions abort when the visible picture is under 96 pixels or odd: dma-buf is approved from the coded size, then the daemon rejects H.264 160x90. | Patch 0060: the daemon draws such pictures into an even buffer of at least 96x96, picture at the origin, like a hardware decoder's padded output. For odd sizes it draws the pair's second decoded pixel, so the last chroma column comes from the decoder. | `test-surface-gaps.py --only decode`: H.264 160x90, VP9 161x97 and VP8 161x95, plus an unchanged 640x360 control, bit-exact against FFmpeg's software decoder. |
| VP8/VP9 decoders got dma-buf from the AVC/HEVC proofs. | The startup proof is split; VP8 and VP9 decoders each decode an embedded 128x128 key frame of the qualify pattern (libvpx, exact in FFmpeg). H.264 and HEVC decoders now use their own codec's proof instead of requiring both. A new log line reports `VP8=… VP9=…`. | `test-surface-fallback.py`: qualified VP8/VP9 get mode 2; `TVA_TEST_SURFACE_BAD_DECODE` swaps chroma in every decode proof and must drop all decoders to SHM. |
| Untagged Main/High H.264 and HEVC surface colour was never tested. | Measured on the Note10+: untagged surface input is wrong for every encoder, not only Baseline (RGB error 24 against 1 for copy). termux-va 13 keeps every untagged encoder session on copy input; only BT.709 limited-range sessions use dma-buf. `TVA_TEST_SURFACE_ANY_COLOUR` (test only) lifts the colour exclusions. | `test-surface-gaps.py --only colour`: every surface encoder × untagged/BT.709 limited/BT.709 full, copy vs surface, decoded to RGB as signalled. The control must catch the known-bad full-range or untagged Baseline sessions. |

Also fixed: dead `< 0` checks on the unsigned `winsys_handle.handle` (it now
uses `UINT_MAX` as "none"), a skipped `DMA_BUF_SYNC_END` when the encoder's CPU
upload fallback failed to allocate, and a shadowed variable. Not changed: the
per-frame gralloc allocations in the daemon, which likely contribute to the
H.264 shortfall, and the shared `pipe_context` use in `fence_wait`, which
predates this work.

Evidence notes: the warm H.264 decode figure (66.0 fps against 60.5 fps copy)
comes from the candidate-21 line in `COORDINATION.md`, not from the
production evidence tarball. The 48/48 VP8/VP9 decode results did not record
which transport they used.

Host checks: both patch series apply to the pinned upstream tarballs and
reproduce the reviewed trees; the patched daemon and bridge pass
`gcc -fsyntax-only -Wall -Wextra -Wshadow` apart from pre-existing AV1
type-limit warnings; packaging, ten-bit, daemon-upgrade and session-decode
host tests pass. Phone results follow.

### Note10+ results (2026-11-24)

Controls on the old stack (android-vaapi 23, termux-va 11), private daemons:
the small and odd decoder sessions failed and the 640x360 control was
bit-exact; FFmpeg aborted in 4 of 4 daemon-kill runs, with logcat showing
Scudo "invalid chunk state when deallocating" in libgallium.

Installed android-vaapi 24, android-vaapi-glibc 19, termux-va 12,
android-webgpu 0.1.0-2 and livecd-desktop 50 from CI 45333014924:

- `test-surface-fallback.py`: 8/8.
- Padded decode: H.264 160x90 and VP8 161x95 bit-exact through dma-buf.
- `test-encoder-failure.py`: 6/6, FFmpeg exits with an error and no signal.
- Colour: the control caught the known-bad sessions, and it showed that
  untagged H.264 default, Main and High and HEVC Main are as wrong as Baseline.
  termux-va 13 (CI 45341136101) therefore puts every untagged encoder on copy.

Trade-off: untagged encoders, such as FFmpeg without colour options, lose the
zero-copy input speedup. Chromium WebRTC and WebCodecs tag BT.709 limited range
and keep the dma-buf path.

Hardware limit: the Snapdragon 855 VP9 decoder rejects pictures under 96 lines
(MediaCodec error -10000), on copy as well as dma-buf. The odd-size VP9 case is
therefore 161x97, and the gap test checks that VP9 161x95 gives the same frame
count through both transports instead of requiring frames.

