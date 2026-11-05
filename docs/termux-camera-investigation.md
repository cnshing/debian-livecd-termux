# Native Termux camera: investigation

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](privacy.md).

Investigated and tested on the connected Galaxy Note10+, Android 11 /
SDK 30, ARM64, with Termux 0.118.3 (target SDK 28), Termux's PipeWire 1.4.9 and
`ndk-sysroot` 30. Raw results: `temp/docs/evidence/camera-investigation/`.

**Desktop integration is still missing.** The results below come from a private
test session that builds the producer and preload itself. The running desktop
has neither installed, loads no camera preload, and has no camera PipeWire
endpoint. See the [session audit and PRoot assessment](camera-session-and-proot.md)
for the device checks, path-translation benchmark and remaining integration work.
The selected implementation uses native preloads and PipeWire/portal access;
PRoot is excluded. The follow-up also records the backend's exact buffer and
ioctl coverage and the broad application acceptance target.

**Question:** can [termux-api#904]'s CameraVideo API, driven through Shizuku or
ADB, give the native desktop a live camera that any Linux program can use, with
latency and CPU cost fit for live video?

**Answer: yes, but not through that pull request or through Shizuku.** A native
Termux program opens the phone's cameras with Android's NDK Camera2 API under
Termux's own UID and publishes each as a PipeWire camera. A preload,
`liblivecd-v4l2.so`, then turns each into a V4L2 device, `/dev/video0` upward,
for every Bionic program that loads it. Programs see a character device in
`stat`, `/dev` listings and sysfs, and stream through PipeWire's `pw-v4l2`.
Termux's unmodified Chromium found both cameras by name and streamed through its
own V4L2 backend.

| Front camera, 1280×720 at 30 fps | Result |
| --- | --- |
| Frames delivered | 30.0 fps with no gap over 1.5 frames |
| Exposure start to a V4L2 program | Median 31–39 ms across runs (exposure itself 8 ms) |
| Exposure start to JavaScript in Chromium | Median 35.2 ms, 29.8 fps |
| Added by PipeWire and `pw-v4l2` | About 1 ms over direct NDK delivery |
| Added by the preload | Nothing measurable per frame; 0.3–1 µs per `stat`+`open`+`close` |
| CPU, camera node | 5–18% of one core, by pixel format and run |
| CPU, PipeWire daemon / V4L2 client | 0.1% / 1–2% |
| Colors | Correct through YUYV, NV12 and Chromium; a U/V-swap control fails |
| Android camera | Opens when a client streams, closes 2 s after the last stops |

ADB or Shizuku is needed once, to grant the `CAMERA` permission. The producer
must start a Binder thread pool, `pw-v4l2` needs two small patches, and the
preload must be safe to enter while the C library is still starting. What
remains is packaging, glibc programs, and the desktop's own PipeWire; see
[compatibility](#compatibility) and the [proposed design](#proposed-design).

```text
Android camera → NDK Camera2 + AImageReader (Termux UID) → camnode (one copy)
  → PipeWire node: Video/Source, media.role=Camera, object.path=v4l2:/dev/videoN
      ├→ PipeWire and portal clients
      └→ liblivecd-v4l2.so → pw-v4l2 (patched, loaded privately) → Bionic V4L2 programs
         generated folder: dev/videoN, sys/class/video4linux/videoN/
```

## Shizuku, Java and real-time video

Shizuku was suggested for its Java API access. On this phone it does not help:

- **Java and the NDK use the same camera path.** Java's `CameraManager` and the
  NDK's `ACameraManager` are both clients of the same camera service over
  Binder, with the same HAL behind them. The NDK route already delivers frames
  into the process that publishes them, with no JNI hop.
- **The latency is in the camera, not the client.** Measured from the start of
  exposure, the front camera delivers in 30 ms and the back in 79 ms. Exposure
  accounts for 8 ms and 33 ms of that (the back camera faced a dark surface).
  The remaining 22 ms and 46 ms is Samsung's image pipeline. Switching from the
  record to the preview template, and turning off noise reduction, edge
  enhancement and stabilization, changed none of these figures.
- **The camera HAL dominates CPU.** Samsung's camera provider process used
  80–96% of one core in every run, whichever camera or size. Our process used
  8.5–13% including two conversions and a pixel dump. The client API cannot
  change the HAL's share.
- **Shizuku's identity cannot stream on Android 11.** Shizuku runs as the shell
  UID. Android 11's Shell [holds `CAMERA`][shell11], but capture stops without a
  foreground activity, and Shell lacks the overlay permission ([added in
  12][shell12]) and a camera service type. scrcpy, which uses the same identity,
  therefore [refuses camera capture on Android 11][scrcpy-camera] ([#4213]).
- **Java is available without Shizuku anyway.** Termux can run `app_process`
  as its own UID, as its `am` command does, if a Java-only API is ever needed.

The one thing Java apps get for free is a Binder thread pool. A plain native
executable has none, so the camera service could never return image buffers
to the process. The first capture opened the camera and then stalled for 25 s
with `IProducerListener: binder call 'needsReleaseNotify' failed`. Calling
`ABinderProcess_startThreadPool` from the public `libbinder_ndk.so` fixed it.
Its header is not in the app NDK, so the probes look it up with `dlsym`.

The native APIs worth using next are elsewhere:

- **Hardware H.264 for live streaming.** The NDK's `AMediaCodec` can take the
  camera's output surface directly, so encoding needs no CPU copy. PipeWire and
  `pw-v4l2` both carry H.264 (`V4L2_PIX_FMT_H264`), so a node could offer it
  next to raw formats for streaming programs to remux without re-encoding.
  Not built or tested.
- **Zero-copy GPU buffers.** An image reader with GPU usage yields
  `AHardwareBuffer`s that could reach GPU consumers as DMA-BUFs. The CPU copy
  costs 0.3–1.5 ms per 720p frame, so this is a later optimization.

## What the pull request does

[termux-api#904] ("Add camera video recording (CameraVideo API)") was opened on
2026-08-16 and is still open, with no maintainer review. It adds a Termux:API
service that sends Camera2 frames into `MediaRecorder` and writes an MP4 file,
with microphone audio; [termux-api-package#241] adds the wrapper. It does not
fit a live camera: an MP4 from `MediaRecorder` is readable only after
recording stops, and using it means rebuilding Termux:API, signed with
Termux's key. Its Camera2 setup is only a Java reference.

## Opening the camera as the Termux UID

Termux:API [declares `CAMERA`][api-manifest] and shares Termux's UID, so one
grant covers every Termux process, as `RECORD_AUDIO` does for the
[microphone](mic/README.md):

```sh
adb shell pm grant com.termux.api android.permission.CAMERA     # from the PC
rish -c 'pm grant com.termux.api android.permission.CAMERA'      # in Termux, with Shizuku
```

**Expect revoking it to kill every Termux process.** Android normally stops an
app's processes when one of its runtime permissions is revoked, and here that
UID includes the desktop, its X server and sshd. This was not tried here.
Revoke only when the desktop can be restarted:

```sh
adb shell pm revoke com.termux.api android.permission.CAMERA
```

On this phone the grant is now in place. Without it the probe fails with
`ACAMERA_ERROR_PERMISSION_DENIED` (-10013); with it, the camera service log
shows the client accepted as `com.termux`. That matches Android 11's source: a
foreground service of an app targeting SDK 28 gets camera capability with no
declared service type ([`OomAdjuster`][oom11]), and the camera service
attributes NDK clients to the UID's first package ([`CameraService`][cs11]).
Termux's foreground service was running throughout. Android 11 shows no camera
indicator.

### Measurements

[`camcap.c`](../tests/camera/camcap.c) streamed 300 frames per run. Latency is
from the sensor's exposure-start timestamp (`CLOCK_BOOTTIME`) to the image
reader callback.

| Camera, size | Exposure start to delivery (avg) | Exposure | Copy, native NV21 / to YUYV | Process CPU | Open to first frame |
| --- | --- | --- | --- | --- | --- |
| Back, 1280×720 | 78.6 ms | 33.1 ms | 0.33 / 1.11 ms | 8.8% | 558 ms |
| Back, 1920×1080 | 80.9 ms | — | 0.57 / 2.48 ms | 13.3% | 530 ms |
| Front, 1280×720 | 29.8 ms | 8.3 ms | 0.30 / 1.12 ms | 8.5% | 449 ms |

Every run delivered 30.0 fps with no gap over 1.5 frames. The cameras deliver
`YUV_420_888` as contiguous NV21 (V before U), so the copy into NV21 or the
Y plane of any format is a straight `memcpy`. All five cameras are listed in
[`camlist.c`](../tests/camera/camlist.c)'s output; ID 4, likely the depth
sensor, offers no YUV output.

## Making it a Linux camera

### The camera node

[`camnode.c`](../tests/camera/camnode.c) publishes one camera per process as a
PipeWire stream with `media.class=Video/Source` and `media.role=Camera`. It
claims `/dev/videoN` with `object.path=v4l2:/dev/videoN`, the form PipeWire's
own V4L2 nodes use, and offers NV21, NV12, YUYV and I420 at a fixed size and
rate. It opens the Android camera when a client streams, keeps only the newest
image, and copies it once into the negotiated buffer. It closes the camera 2 s
after the last client stops. V4L2 clients stream once to negotiate a format and
again on `STREAMON`; without the delay the camera opened, closed and reopened,
taking 112–173 ms each time.

The first measurements, through `pw-v4l2` alone with a plain V4L2 client
([`v4l2-read.py`](../tests/camera/v4l2-read.py)):

| Front camera 720p30 | YUYV | NV12 |
| --- | --- | --- |
| Frames | 300 at 30.0 fps | 300 at 30.0 fps |
| Exposure start to application, median (min–max) | 32.1 ms (26.5–41.2) | 31.3 ms (26.6–46.0) |
| Producer copy per frame | 1.4 ms | 0.66 ms |
| CPU: camera node / PipeWire / client | 9.3% / 0.1% / 1.1% | 6.9% / 0.0% / 1.1% |

Received frames show the same warm wall as the direct capture (mean RGB 119,
107, 94 in YUYV against 114, 109, 95 direct). Reading the NV12 frame with its
chroma planes swapped gives 97, 112, 119, so the check can fail.

### The virtual device

There is no root, so no kernel `/dev/video` device of our own. Every kernel
route was checked from Termux on this phone's 4.14 kernel: `mknod` of a
character device fails with `EPERM`, `/dev/fuse` with `EACCES`, CUSE does not
exist, user namespaces (needed to mount a fake directory over `/dev`) fail with
`EINVAL`, and seccomp user notification (Linux 5.0) is unavailable. PRoot could
redirect paths, but a file in a fake directory cannot answer V4L2 ioctls. The
phone also has real `/dev/video0`–`video2`, `video32`–`video34`, `v4l-subdev*`
and `media*` nodes for its own hardware, which SELinux blocks for Termux.

So the device lives in the C library calls a program makes.
[`livecd-v4l2.c`](../tests/camera/livecd-v4l2.c) builds `liblivecd-v4l2.so`.
The camera node writes a generated folder, by default
`$XDG_RUNTIME_DIR/livecd-v4l2`: a `dev/videoN` marker, and
`sys/class/video4linux/videoN/` with `name`, `index`, `dev` and `uevent`. It
removes them on exit. For a published `/dev/videoN`, the preload:

- sends `open`, `ioctl`, `mmap`, `munmap`, `dup` and `close` to `pw-v4l2`,
  which it loads privately (`RTLD_LOCAL`), so no other call reaches `pw-v4l2`;
- reports a character device, major 81, to `stat`, `lstat`, `fstat`,
  `fstatat`, `statx`, `access` and `realpath`;
- adds `videoN` to listings of `/dev` and hides the phone's blocked nodes;
- serves `/sys/class/video4linux` from the generated folder;
- answers `libv4l2`'s direct `syscall()` calls for the same operations.

Everything else passes through. `pw-v4l2` needs
[the `realpath` fix](../tests/camera/pw-v4l2-bionic-realpath.patch) and
[a device-number claim](../tests/camera/pw-v4l2-device-path.patch). Without the
claim, each process gave `/dev/videoN` to the first camera node it saw, so
`/dev/video0` could open the back camera. The claim must use `object.path`,
because only a fixed set of node properties reaches other clients; an
`api.v4l2.path` property was invisible to `pw-v4l2`.

Three Bionic behaviors shaped the preload; the desktop's other preloads face the
same ones:

- **Bionic's futex waits call the exported `syscall()`.** A `syscall()` wrapper
  therefore runs inside every contended lock in every program. The first
  version initialized itself there and recursed until the stack overflowed. The
  wrapper now decides by call number and passes everything else to the kernel
  with the system call instruction.
- **The C library calls `open()` during its own start-up.** A one-time setup
  that formatted a string started the allocator, which called `mmap`, which
  waited on the same setup forever. Each wrapper now looks its target up with
  `dlsym` on first use and allocates nothing on paths that are not cameras.
- **`readdir` must leave `errno` alone at the end of a directory.** Checking
  for markers set `ENOENT`, and Python reported the listing as an error.

### Results

[`test-v4l2-preload.sh`](../tests/camera/test-v4l2-preload.sh) builds
everything on the phone, starts a private PipeWire, WirePlumber and D-Bus, and
publishes the front camera as `/dev/video0` and the back as `/dev/video1`.
Every check has a control that must fail: without the preload, or with no
camera published, or after the nodes stop. The final run had no unexpected
results. Raw output: `temp/docs/evidence/camera-investigation/v4l2-preload-7.txt`.

| Check | Without the preload | With the preload |
| --- | --- | --- |
| `stat /dev/video0` | `EACCES` from the phone's own node | `crw-rw---- 81:0` |
| Read and write access | Denied | Allowed |
| Listing `/dev` | 36 blocked `video`, `v4l-subdev` and `media` nodes | `video0 video1` |
| `/sys/class/video4linux` | `EACCES` | `video0 video1`, named "Phone camera 1" and "Phone camera 0" |
| `open` and `fstat` | `EACCES` | Character device |
| Plain V4L2 stream, `/dev/video0` | — | 300 frames at 30.0 fps, median 34–39 ms, front camera |
| `libv4l2` stream, `/dev/video1` | `v4l2_open`: `EACCES` | 150 frames at 29.9 fps, back camera; also offers `libv4l2`'s converted RGB3, BGR3 and YV12 |
| Termux's Chromium 156 | — | Lists both cameras by name; streams the front camera at 1280×720, 29.8 fps; median 35.2 ms to JavaScript |
| bash, Python (`json`, `sqlite3`, `ssl`, `subprocess`), clang | — | Run normally |
| After the nodes stop | — | `/dev/video0` is gone again |

Chromium was run headless with camera permission auto-accepted
([`run-chromium.py`](../tests/camera/run-chromium.py),
[`chromium-camera.html`](../tests/camera/chromium-camera.html)). It found the
cameras by listing `/dev`, negotiated I420, and read frames with
`MediaStreamTrackProcessor`. A headless `<video>` element without a GPU never
fires its frame callbacks. Its last frame shows the same scene with a warm wall
(mean RGB 117, 108, 95).

**Efficiency.** The same stream, alternating 300 frames through `pw-v4l2` alone
and through the preload, measured median 37.3 against 37.3 ms and 35.2 against
34.0 ms. Client CPU was 1.5 against 1.5% and 1.4 against 1.3%. A loop of
`stat`, `open` and `close` took 10.7–11.0 µs without the preload and
11.0–11.7 µs with it. The camera node's YUYV copy varied between test sessions,
1.4 ms per frame in one and 2.5–2.9 ms in another, with the phone at 35 °C and
not throttled. I420, which Chromium chose, cost 0.5 ms and 5.4% CPU. The
conversions are plain C loops; NEON would cut them.

**Two cameras at once.** When the back camera opened while the front was in its
close delay, Android disconnected the front camera; the node logged it and
reopened on the next stream. This phone does not stream both to an app at once.

### Compatibility

| Program | Status |
| --- | --- |
| Bionic programs using `open`, `ioctl`, `mmap` and `poll` | Works: Python client and Chromium tested |
| Programs that list `/dev` or check `stat` first (Chromium; GStreamer's `v4l2src`) | Works: listing and `stat` tested; Termux's GStreamer has no V4L2 plugin to try |
| `libv4l2` programs | Works: tested |
| Sysfs readers | Name, index, device number and uevent; no USB vendor or product IDs |
| PipeWire clients | Node published; the desktop needs a PipeWire and WirePlumber, and runs only PulseAudio |
| Portal clients (Snapshot, OBS's PipeWire source) | Untested; need `xdg-desktop-portal` (packaged by Termux, not installed), which lists `media.role=Camera` nodes ([source][portal]) |
| glibc programs (Google Chrome, ungoogled-chromium, anything run through the desktop's glibc runtime) | **Not covered**: a Bionic preload cannot load into them. Needs glibc builds of the preload and `pw-v4l2` |
| Programs started without the preload | Not covered until the desktop adds it to the session preload |
| Statically linked programs, or inline kernel system calls (some Go programs) | Outside preload coverage; need a compatible dynamic build or native PipeWire/portal path under the selected approach |
| `openat` relative to an open `/dev` directory | Not handled; none seen |

GNOME Shell builds with `-Dcamera_monitor=false`
([build.sh:19](../packages/gnome-48-shell/build.sh#L19)), which would
otherwise show an indicator while a `media.role=Camera` node runs
([source][shell-monitor]). Android 11 shows none of its own. Chromium no longer
needs a PipeWire rebuild for camera use; its V4L2 path works.

## Proposed design

- **`livecd-camera` package:** `camnode` as a per-camera service, NEON
  conversions, and a test-pattern mode; `liblivecd-v4l2.so` with the patched
  `libpw-v4l2.so` beside it.
- **Session integration:** the desktop adds `liblivecd-v4l2.so` to the session
  preload next to the resources preload, and starts a video-only PipeWire and
  WirePlumber beside PulseAudio.
- **glibc programs:** glibc builds of the preload and `pw-v4l2`, loaded by the
  desktop's glibc runtime.
- **Indicator:** enable GNOME Shell's camera monitor.
- **Later:** an H.264 format fed by the hardware encoder for streaming.

## Test plan for the package

`test-v4l2-preload.sh` already covers device checks, plain V4L2, `libv4l2`,
Chromium, the efficiency comparison and the negative controls. Still to add:

- **Pixels:** a test-pattern mode checked for exact values, with a
  U/V-swapped build that must fail. The warm-wall comparison stays as the
  real-camera check; open the pictures.
- **Lifecycle:** recovery after Samsung's Camera app takes the camera and
  releases it.
- **Session:** the same checks inside the running desktop, and for glibc
  programs once built. GUI checks on a private display only.

[termux-api#904]: https://github.com/termux/termux-api/pull/904
[termux-api-package#241]: https://github.com/termux/termux-api-package/pull/241
[#4213]: https://github.com/Genymobile/scrcpy/pull/4213
[scrcpy-camera]: https://github.com/Genymobile/scrcpy/blob/master/doc/camera.md
[shell11]: https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-11.0.0_r48/packages/Shell/AndroidManifest.xml
[shell12]: https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android12-release/packages/Shell/AndroidManifest.xml
[oom11]: https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-11.0.0_r48/services/core/java/com/android/server/am/OomAdjuster.java
[cs11]: https://android.googlesource.com/platform/frameworks/av/+/refs/tags/android-11.0.0_r48/services/camera/libcameraservice/CameraService.cpp
[api-manifest]: https://github.com/termux/termux-api/blob/master/app/src/main/AndroidManifest.xml
[portal]: https://github.com/flatpak/xdg-desktop-portal/blob/1.20.3/src/camera.c
[shell-monitor]: https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/48.0/src/shell-camera-monitor.c
