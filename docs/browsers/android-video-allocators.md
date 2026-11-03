# Android video allocators and native FFmpeg investigation

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

Continued on the SM-N975U1, Android 11,
kernel 4.14.190, Adreno 640. Evidence (`temp/docs/evidence/browsers/native-gpu-video/`)
and [repeatable tests](../../tests/browsers/README-native-video.md) accompany this report.

The later [shared acceleration integration](../native/ACCELERATION.md) compiles
the ION fallback directly into a private Bionic VA driver and exposes separate
native/glibc application profiles. It was built and applied with tests disabled
at the user's request; these new native paths are configured and unverified.

**There is a working unprivileged allocation route on this phone.** Opening ION
read-only and allocating its system heap produces a usable dma-buf. A private
Chrome experiment using that allocation passes VP9 and HEVC pixel checks at both CDP and
GNOME compositor layers. The regular launcher defaults to software video for fresh
users. Following the user's explicit request to apply it, this phone now has the
tested adapter installed and a persistent hardware-video opt-in. The general
installer does not install the adapter. See [the current setup](native-gpu-and-video.md).

The later application follow-up (`temp/docs/evidence/browsers/native-gpu-video/`)
has an unresolved fullscreen frame-freshness failure, also reproduced with the
software control. It is not a clean test signoff, and the user's existing Chrome
process still needs a complete relaunch before live hardware decoding can be checked.

## Device results, rather than permission assumptions

The same native probe ran as the Termux app UID (`untrusted_app_27`) and ADB UID 2000
(`shell`), with SELinux enforcing:

| Operation | Termux | ADB shell |
| --- | --- | --- |
| Open `/dev/dma_heap/system` | ENOENT | ENOENT |
| Open `/dev/ion`, read-write | EACCES | EACCES |
| Open `/dev/ion`, read-only | Success | Success |
| Query ION heaps | Success, system heap ID 25 | Same |
| Allocate 1 MiB from ION system heap through that read-only FD | Success | Success |
| Map allocation read-write; dma-buf sync ioctl | Success | Success |
| `ASharedMemory_create` | Success; ashmem FD | Same |
| dma-buf sync on the shared-memory FD | ENOTTY | ENOTTY |
| `AHardwareBuffer_allocate`, BLOB and YUV420, CPU lock | Success | Success |

The probe only allocates the unprotected system heap. It records heap IDs/types
instead of assuming a mask or allocating from the secure heaps it enumerates.

The important distinction is **one dma-buf for both planes**, not physically
contiguous RAM. A system ION allocation can provide that object even when its pages
are scattered. Android's migration guide describes ION and DMA-BUF heaps as
exporters accepted by the same importing drivers, with `libdmabufheap` offering
ION fallback. This device predates that allocator transition; a missing node is
not a file permission that an app grant can fix.
[AOSP allocator documentation](https://source.android.com/docs/core/architecture/kernel/dma-buf-heaps),
[Linux ION UAPI](https://android.googlesource.com/kernel/common/+/3feec8968211/drivers/staging/android/uapi/ion.h).

## Shizuku

Shizuku's ADB mode runs code as shell UID 2000, with shell's UID, capabilities and
SELinux context. A `UserService` can run native code via JNI. It cannot add an absent
kernel allocator or grant a Linux device access that shell itself lacks. Root mode
is a separate privilege level.
[Shizuku developer guide](https://github.com/RikkaApps/Shizuku-API#differents-of-the-privilege-betweent-adb-and-root).

Our ADB measurements exercise that shell identity without installing or starting
Shizuku. They show no allocation advantage over Termux here. On another device,
where shell can open a heap but an app cannot, a service could potentially allocate
and transfer an FD, subject to the receiver's FD-use/import policy. That is a
device-specific broker design, not a universal `/dev/dma_heap` permission switch.
It is unnecessary for the working ION path measured here.

## MemoryFile, shared memory and NDK buffers

The public NDK shared-memory API is `ASharedMemory`, declared in
`android/sharedmem.h` since API 26. `MemoryFile` is a Java API backed by shared
memory; there is no public NDK allocator named `AMemoryFile` in this API family.
The returned shared-memory FD can be transferred between processes and mapped on
the CPU. That does not make it a dma-buf that KGSL/Vulkan can import as a video
surface. On this phone its target is ashmem and the dma-buf ioctl returns ENOTTY.
[NDK memory API](https://developer.android.com/ndk/reference/group/memory),
[Java MemoryFile](https://developer.android.com/reference/android/os/MemoryFile).

`AHardwareBuffer` is the relevant NDK hardware allocator: API 26, graphic buffer
sharing, EGL/Vulkan interop, and public Unix-socket handle transfer. Both BLOB and
YUV420 allocations worked without Shizuku. The probe observed two dma-buf FDs in
each transported Qualcomm handle. Their roles/layout are vendor-specific; picking
the first FD is not a portable NV12 export implementation. BLOB means a one-row
byte buffer, and flexible YUV420 does not promise linear NV12.
[NDK hardware buffer API](https://developer.android.com/ndk/reference/group/a-hardware-buffer).

For a future surface-based decoder, `AMediaCodec` can output to an `ANativeWindow`;
an `AImageReader` supplies a window and exposes acquired images as hardware buffers.
That needs buffer lifetime, layout, synchronization and import integration. It does
not let glibc Chrome call Bionic NDK libraries directly. The pinned Termux:VA daemon
already uses NDK MediaCodec, but its tested transport is decoded byte buffers over
shared memory, followed by Mesa copying into GPU-importable video surfaces.
[NDK media API](https://developer.android.com/ndk/reference/group/media),
[pinned daemon source](https://github.com/lfdevs/termux-va/blob/ae14813d77dbf107273b410a32f4ade34ba56313/daemon/termux-va.c).

## Native Termux FFmpeg is useful now

The linked maintainer comment says native FFmpeg can use MediaCodec directly,
without Termux:VA, and separately describes limitations of native browser VA-API
support. Those are different integrations.
[Termux:VA issue and maintainer response](https://github.com/lfdevs/termux-va/issues/1#issuecomment-6488523619).

The installed FFmpeg exposes `h264_mediacodec`, `hevc_mediacodec` and
`vp9_mediacodec`; its `ndk_codec` option avoids requiring a Java VM. The tests
explicitly select that decoder before the input:

```sh
ffmpeg -loglevel verbose -c:v h264_mediacodec -ndk_codec 1 -i input.mp4 -an -f null -
```

All three codecs decoded all 48 numbered frames in order. Logs identify Qualcomm
hardware components `OMX.qcom.video.decoder.avc`, `.hevc`, and `.vp9`. First,
middle and final decoded RGB frames pass the PC reference comparisons. These are
actual decoding/pixel checks, not just a list of compiled capabilities.
[Termux FFmpeg build](https://github.com/termux/termux-packages/blob/master/packages/ffmpeg/build.sh),
[FFmpeg MediaCodec decoder and options](https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/mediacodecdec.c).

This provides a native player/transcoding route and an independent oracle for the
Android codecs. It also narrows the Chrome bug to the bridge/import path for the
tested clips. Chrome does not invoke the `ffmpeg` command for web playback, and its
Linux FFmpeg decoder does not automatically select Android's MediaCodec wrapper.
Replacing its library with Termux's Bionic build would cross incompatible ABIs;
browser integration still needs a bridge or a browser media-backend change.

## ION experiment and the wrong-color diagnosis

The existing Mesa allocator opens only `/dev/dma_heap/system` for a shared NV12
object. Its fallback allocates the two planes separately. Mesa's source documents
the Chromium Vulkan importer's single-object expectation.
[Mesa bridge source](https://github.com/lfdevs/mesa-for-android-container/blob/dev/adreno-main/src/gallium/frontends/va/tva_bridge.c).

The test preload adapts that missing heap to ION's queried system heap, using the
FD-returning ION allocation ABI, cached memory, and the requested close-on-exec
flag. It does not emulate a dma-buf using an ordinary memory file. Both paired
runs use the same preload/trace, private daemon, fixtures, launcher and contiguous
allocation option. The allocation flag is the only difference.

The traced `vaExportSurfaceHandle` results for 640x360 NV12 are:

| | Control | ION-enabled |
| --- | --- | --- |
| Exported objects | 2, distinct dma-bufs | 1 dma-buf |
| Y plane | Object 0, offset 0, pitch 640 | Object 0, offset 0, pitch 640 |
| UV plane | Object 1, offset 0, pitch 640 | Object 0, offset 237568, pitch 640 |
| Picture | Green/purple; pixel checks reject | VP9 and HEVC pixels pass both capture layers |

This measures what VA exports to Chrome and the resulting pictures. It does not
instrument every internal Vulkan import operation. Together with the controlled
allocation change it strongly supports the shared-object diagnosis.

The final browser matrix passed all 11 expected outcomes: seven pixel-positive
cases, two wrong-color negatives, the original Cogl fullscreen crash negative,
and the explicitly unsupported software HEVC capability check. Each run kept the
live server/shell/shared-daemon identities and display sockets unchanged, with
identical Android focus before and after. All 12 browser/native-decoder contact
sheets were opened and reviewed. Five host test groups also pass, including 90
controlled launcher combinations and regular-file/dangling-symlink exclusions.
These counts describe this suite, not the entire project's test collection.

The adapter is confined to glibc browser children. Its trace wrapper needs
a mandatory tail call for unrelated `dlsym` lookups to preserve `RTLD_NEXT` caller
semantics; an earlier trace build accidentally bypassed allocation interposition
and correctly failed the pixel check. The final paired runs retain both traces.

The sensible production change is an ION fallback in Mesa's allocator, using a
queried unprotected system heap or an allocator abstraction, rather than a permanent
global preload. The tested adapter was subsequently applied to this phone at the
user's request; fresh installs retain the software default. The handoff's
Android-display check, broader codec/metadata/size and fault matrix, performance
measurements, soak and user review remain required. The H.264 bridge stall is
separate open work; direct FFmpeg succeeding does not prove that bridge fixed.
