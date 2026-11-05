# Camera session integration and PRoot assessment

The existing camera bridge works in its isolated test environment. The native
desktop still needs that bridge packaged and started. PRoot path translation
alone cannot supply the missing camera implementation.

**Selected approach:** native preloads plus PipeWire and the camera portal.
PRoot is excluded from implementation. The PRoot discussion and measurements
below remain as investigation evidence. Broad application compatibility through
ordinary installed launchers is the acceptance target.

## Running desktop audit

Checked the connected Note10+ under its Termux UID, using the environment
returned by `desktop.session_environment()` and the running processes' loaded
libraries. No camera capture or desktop restart was needed.

| Check | Observed |
| --- | --- |
| Desktop session preload | Resources compatibility and Termux exec; no camera preload |
| Installed `liblivecd-v4l2.so` / `camnode` | Absent from the normal install locations / command path |
| Camera producer process | Absent |
| Published `livecd-v4l2/dev/videoN` markers in desktop runtime | Absent |
| PipeWire socket in desktop's selected runtime | Absent |
| Existing PipeWire / WirePlumber | Audio-effects runtime, separate from the desktop runtime |
| Camera nodes in that PipeWire registry | None |
| `/dev/video0` and `/dev/video1`, opened from desktop environment | `EACCES` |

Source matches the device: [`desktop.py`](../src/native/desktop.py) installs the
resources preload and optional encoding preload, and starts PulseAudio, but
does not start `camnode` or add the V4L2 preload. The base
[`packages.txt`](../src/native/packages.txt) does not request PipeWire,
WirePlumber or a camera package. Camera sources and the two `pw-v4l2` patches
live under [`tests/camera`](../tests/camera/).

[`test-v4l2-preload.sh`](../tests/camera/test-v4l2-preload.sh) builds those
artifacts in a temporary directory, starts private D-Bus, PipeWire and
WirePlumber instances, and explicitly supplies the camera preload to each
client. It removes its artifacts and stops its services on exit. Its successful
results prove that prototype's capture path; they do not exercise the desktop's
installation, startup or application launchers. The video-encoding camera test
uses the same private-session arrangement.

Raw local audit: `temp/docs/evidence/camera-session/session-audit.txt`.

## What `/dev/videoN` must provide

A directory entry is the discovery surface. Once opened, a Linux camera must
answer capability and format ioctls, allocate and map buffers, queue and dequeue
them, signal readiness, and start and stop capture. The
[V4L2 capture specification](https://docs.kernel.org/userspace-api/media/v4l/dev-capture.html)
and [streaming API](https://docs.kernel.org/userspace-api/media/v4l/mmap.html)
describe these operations. Renaming a regular file, FIFO or socket does not
give it this interface. A device number also requires an accessible kernel
driver behind it; path translation does not grant Android camera permissions
or bypass SELinux.

For example, Firefox's upstream
[`DeviceInfoV4l2::NumberOfDevices`](https://github.com/mozilla/gecko-dev/blob/master/third_party/libwebrtc/modules/video_capture/linux/device_info_v4l2.cc)
opens `/dev/video0` through `/dev/video63` and calls `VIDIOC_QUERYCAP` before
counting a device. Even enumeration therefore needs working V4L2 operations.
This source check does not establish which backend the installed Firefox build
selects, or that its capture process loads our preload.

The prototype already provides these operations through `pw-v4l2`, with
discovery and device metadata supplied by `liblivecd-v4l2.so`. These are
process-local virtual devices. PipeWire and portal applications can instead
consume the published camera node without using a `/dev/videoN` shim.

Discovery is necessary but does not establish full streaming compatibility.
The [PipeWire 1.4.9 backend used by the prototype](https://github.com/PipeWire/pipewire/blob/1.4.9/pipewire-v4l2/src/pipewire-v4l2.c)
accepts `V4L2_BUF_TYPE_VIDEO_CAPTURE` with `V4L2_MEMORY_MMAP` in `vidioc_reqbufs`;
other buffer types and memory modes return `EINVAL`. Unimplemented ioctls
return `ENOTTY`. Our two patches address Bionic recursion and device-number
selection; they do not extend those supported streaming modes. As with a
hardware camera, applications must negotiate the capabilities actually offered.

The compatibility target is broad application support through ordinary installed
launchers. Retain the existing synthetic `/dev` listing, character-device
metadata and sysfs support, and cover relative paths, udev-based discovery and
device-change notifications. Supply matching libraries for each supported ABI
and a working PipeWire camera portal for applications using that interface.
Acceptance must check discovery, negotiation and actual frame delivery in
Firefox/Chromium, representative GNOME camera applications, and available
GStreamer, FFmpeg and OpenCV camera backends. These are coverage targets, not
claims that these applications have passed. A syscall-level fallback for static
or inline-syscall clients is outside the selected native approach. Such clients
need a compatible dynamic build or a working native PipeWire/portal backend.

Both front and rear cameras must enumerate as distinct, clearly named devices
in V4L2 and PipeWire/portal clients, with stable device assignments across
service and desktop restarts. Identify lens direction from Android camera
characteristics (`ACAMERA_LENS_FACING`), rather than assuming camera ID 0 or 1
has the same meaning on every phone. The existing test publishes this phone's
front camera (Android ID 1) as `/dev/video0` and rear camera (ID 0) as
`/dev/video1`; these are prototype assignments, not installed desktop devices.

Acceptance must exercise each camera individually and switching in both
directions, verify that labels match the frames' source, and confirm that idle
enumeration does not open either sensor. Both devices should remain discoverable
while idle. Previous capture tests on this phone observed Android disconnecting
one camera when the other opened; simultaneous capture is therefore not an
accepted capability. Handle that contention explicitly and recover the affected
stream without mislabeling or silently substituting the other camera.

### Exact backend coverage

Buffer modes describe who supplies frame memory and how an application receives
it. They are independent of pixel formats such as YUYV, NV12 or I420.

| Transfer method | Meaning | Prototype backend |
| --- | --- | --- |
| `V4L2_MEMORY_MMAP` | Map backend-provided frame buffers into application memory | Implemented; used by the successful streaming tests |
| `V4L2_MEMORY_USERPTR` | Application allocates memory and supplies its addresses | Rejected by buffer allocation/queue operations |
| `V4L2_MEMORY_DMABUF` | Application supplies DMA-BUF descriptors for shared device/GPU buffers | Rejected by buffer allocation/queue operations |
| Plain `read()` capture | Receive image bytes through the ordinary file-read API | No camera read wrapper; `V4L2_CAP_READWRITE` is not advertised |

The kernel's [I/O overview](https://docs.kernel.org/userspace-api/media/v4l/io.html),
[user-pointer API](https://docs.kernel.org/userspace-api/media/v4l/userp.html)
and [DMA-BUF API](https://docs.kernel.org/userspace-api/media/v4l/dmabuf.html)
describe those methods. `libv4l2` may adapt some client operations separately;
the table describes the underlying bridge, not every library's possible
fallback behavior.

The separate multi-planar API (`V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE`) is also
rejected. This API addresses image planes separately; NV12 and I420 remain
supported by the producer as contiguous single-buffer formats. See the
[kernel's planar API distinction](https://docs.kernel.org/userspace-api/media/v4l/planar-apis.html).

Source audit of the exact 1.4.9 backend's ioctl dispatch found these relevant
omissions. Unhandled requests fall through to `ENOTTY`; this list focuses on
capture applications rather than analog TV, radio and output-device APIs.

| Operation | Missing behavior |
| --- | --- |
| `VIDIOC_ENUM_FRAMEINTERVALS` | Enumerate supported frame rates for a format and size |
| `VIDIOC_QUERY_EXT_CTRL`, `VIDIOC_QUERYMENU`, `VIDIOC_G_EXT_CTRLS`, `VIDIOC_S_EXT_CTRLS`, `VIDIOC_TRY_EXT_CTRLS` | Extended control discovery, menu items and batched control operations |
| `VIDIOC_CROPCAP`, `VIDIOC_G_CROP`, `VIDIOC_S_CROP`, `VIDIOC_G_SELECTION`, `VIDIOC_S_SELECTION` | Crop/selection queries and changes |
| `VIDIOC_EXPBUF` | Export a mapped frame buffer as a DMA-BUF descriptor |
| `VIDIOC_CREATE_BUFS`, `VIDIOC_PREPARE_BUF` | Additional buffer creation/preparation interfaces |
| `VIDIOC_SUBSCRIBE_EVENT`, `VIDIOC_UNSUBSCRIBE_EVENT`, `VIDIOC_DQEVENT` | V4L2 event subscriptions and delivery |

`VIDIOC_S_PARM` has a dispatch entry, but its handler logs that setting
parameters is unimplemented, calls `VIDIOC_G_PARM` and returns success. It does
not change the frame rate. Basic `QUERYCTRL`, `G_CTRL` and `S_CTRL` handlers
exist; their presence does not establish Android control support, since that
also needs properties exposed and handled by `camnode`.

These are source-level coverage findings, not new live-device acceptance
results. V4L2 drivers need not support every optional mode. Prioritize correct
capability reporting, standard discovery/negotiation and the transfer paths
required by the application matrix. Add read/user-pointer support where needed;
DMA-BUF sharing requires real compatible buffers, not ordinary file descriptors
presented as DMA-BUFs.

## Checking the proposed PRoot advice

The [PRoot manual](https://github.com/termux/proot/blob/v5.1.107.102/doc/proot/man.1)
confirms that the root defaults to `/` and that `-b host:guest` can relocate
individual files or directories. A separate distribution and `-0` are
unnecessary. Omitting `-r` simplifies configuration; it does not disable tracing
or inherently remove its overhead. Explicit `-r /` selects the same root.

Mapping an entire mock directory onto `/dev` replaces the process's view of
that directory. It does not merge entries with the original `/dev`. Devices
such as `/dev/null`, `/dev/urandom`, `/dev/ashmem` and `/dev/kgsl-3d0` can then
disappear. Symlinking a mock entry back to the same `/dev/...` path can resolve
through the replacement again. For a path experiment, preserve `/dev` and bind
only the marker:

```sh
mkdir -p "$HOME/mock-dev"
printf 'path translation probe\n' > "$HOME/mock-dev/video0"
proot -b "$HOME/mock-dev/video0:/dev/video0!" "$PREFIX/bin/sh"
```

The `!` prevents dereferencing the guest destination when registering the bind.
This example exposes a regular file at a camera-shaped path; it still needs a
V4L2 backend to be a camera. A second phone control bound a marker onto the
previously missing `/dev/livecd-camera-path-probe`: reading the path succeeded,
but `os.listdir('/dev')` omitted it. A single-file bind therefore also needs
directory-listing support for clients that discover cameras by listing `/dev`.
Raw local control: `temp/docs/evidence/camera-session/proot-listing-control.json`.

The quoted statements about traced descendants, unchanged kernel VFS lookup,
and avoiding a userspace copy of every I/O payload are correct. A process
already running outside the trace tree, including a D-Bus activated service,
does not inherit the mapping merely because a traced client asks it to act.

The overhead description needs qualification. With seccomp acceleration,
PRoot can let unselected syscall numbers run without a ptrace stop. The tested
Termux version's [filter table](https://github.com/termux/proot/blob/v5.1.107.102/src/syscall/seccomp.c)
includes `ioctl` on Android and several socket and descriptor operations, as
well as pathname calls. It therefore does more than inspect initial camera
enumeration. Classic seccomp filters select syscall numbers and scalar
arguments; they cannot dereference a pathname pointer to identify `/dev` before
stopping the process.

## Performance experiment

[`benchmark-proot.py`](../tests/camera/benchmark-proot.py) compares native
execution, a single PRoot file bind, and the same bind with
`PROOT_NO_SECCOMP=1`. It checks marker contents and confirms that
`VIDIOC_QUERYCAP` still fails. It times metadata operations, a real kernel
`FIONREAD` ioctl, a ready pipe poll, and a copy into an existing anonymous
mapping of one 1280×720 I420-sized frame. This uses no camera images.

The phone used Termux PRoot 5.1.107.102, downloaded and unpacked into a temporary
directory without installing a package or distribution. A verbose probe
confirmed that seccomp acceleration was active in the default mode.

Medians of three runs, each with 10,000 metadata/ioctl/poll iterations and
1,000 frame copies; times per operation in microseconds:

| Operation | Native | PRoot, seccomp active | PRoot, seccomp disabled |
| --- | ---: | ---: | ---: |
| `stat` + `open` + `close` | 11.2 | 826.8 | 3,194.7 |
| Kernel `FIONREAD` ioctl | 1.36 | 356.8 | 947.7 |
| Poll an already readable pipe | 1.57 | 7.28 | 973.7 |
| Copy a mapped 720p I420-sized frame | 92.3 | 99.6 | 118.9 |

All nine marker reads succeeded, and all nine `VIDIOC_QUERYCAP` controls failed
with `EACCES`. The mapping worked while Android still rejected the regular
file's unsupported camera ioctl. Native whole-process time was 0.38 s, versus
12.93 s with accelerated PRoot and 53.88 s with acceleration disabled.

For scale, extrapolating two kernel ioctls per frame from the accelerated result
gives about 0.71 ms added per frame, against a 33.3 ms budget at 30 fps. This is
an illustrative estimate, not measured camera latency or a bound on jitter.
`pw-v4l2` handles V4L2 ioctls inside userspace, so those calls do not themselves
make this measured kernel round trip; its actual socket and synchronization
operations would need measuring. Tracing an entire browser also adds other
threads and processes competing for the tracer. Average operation times do
not predict the resulting frame gaps.

These are Python-level microbenchmarks, including loop and wrapper overhead.
The copy has no pacing, producer, consumer, IPC or rendering. The whole-process
time includes interpreter startup and all benchmark loops; it is not camera
startup latency. These measurements cannot establish Firefox frame rate,
end-to-end video latency or a universal PRoot slowdown percentage.

The [earlier live-camera results](termux-camera-investigation.md#results)
already measured approximately 30 fps and 31–39 ms sensor-to-V4L2 latency, with
about 1 ms added by PipeWire and `pw-v4l2`, and no measurable per-frame cost from
the discovery preload. Those are historical prototype measurements, not a new
desktop acceptance run or a comparison against PRoot.

Reproduce in Termux with PRoot installed:

```sh
python tests/camera/benchmark-proot.py --proot "$PREFIX/bin/proot"
```

The default uses 2,000 iterations for a shorter check. Add `--iterations 10000`
to repeat the measurements above.

For an unpacked Termux package, also set `PROOT_LOADER` to its extracted
`libexec/proot/loader`. Raw local results:
`temp/docs/evidence/camera-session/proot-benchmark.json` and
`temp/docs/evidence/camera-session/proot-acceleration.txt`.

## Implementation direction

First package `camnode`, the Bionic discovery preload and patched `pw-v4l2`.
Have the session own the camera services' startup, readiness, crash reporting
and shutdown. All clients and producers must agree on the PipeWire socket and
marker directory. The separate audio-effects PipeWire does not automatically
make camera nodes available to desktop clients; choose an explicit shared
endpoint or a session-owned video service, and verify operation with audio
effects both enabled and disabled.

Add the camera preload to the Bionic session environment before launching apps.
Then test the actual installed Firefox capture process and each GNOME camera
application through its selected backend. Portal clients additionally need a
working camera portal. GNOME Shell's `camera_monitor=false` build option
disables its usage indicator; it does not implement or disable the producer.
Enable and test the indicator when camera support ships.

The glibc browser launch path deliberately removes Bionic `LD_PRELOAD` and
library paths in [`acceleration.py`](../src/native/acceleration.py). It needs
glibc-compatible camera libraries and launcher wiring, or a tested native
PipeWire/portal route. A Bionic library cannot cover that ABI. The existing
preload also has documented gaps for relative `openat`, inline syscalls and
static programs; filling those gaps is a separate compatibility task.

Proceed with native Bionic/glibc preloads and PipeWire/portal access. PRoot and
a PRoot-derived compatibility layer are excluded. Record any remaining
static/inline-syscall client limitations explicitly; exposing a filename alone
does not establish compatibility with those clients.

Desktop acceptance should launch ordinary apps through their installed
launchers, without creating a test-only PipeWire or manually injecting a
preload. Check discovery, actual frames, permissions, camera release, service
restart, desktop restart and coexistence with the session's other preloads.
