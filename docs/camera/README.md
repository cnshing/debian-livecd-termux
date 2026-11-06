# Cameras

The desktop publishes the phone's front and rear cameras to Linux programs, by
default, from the `android-v4l2` package that the Camera overlay installs.

| Device | Name | Android camera |
| --- | --- | --- |
| `/dev/video0` | Front camera | The first front-facing camera Android lists with YUV output |
| `/dev/video1` | Rear camera | The first rear-facing camera Android lists with YUV output |

The assignment comes from Android's lens-facing characteristic, not from
camera IDs, so it is the same on any phone. On the Note10+ that is camera 1
(front) and camera 0 (rear); its other lenses and its depth camera, which
offers no YUV output, are not published. Each camera offers 1280×720 at 30 fps
in NV21, NV12, YUYV and I420, or the closest size and rate Android lists.

Neither camera is opened until a program streams from it, and each is closed
again 2 s after the last stream stops.

## How it works

```text
Android camera → NDK Camera2 + AImageReader (Termux UID) → camera-node, one per camera
  → the session's PipeWire ($XDG_RUNTIME_DIR/pipewire-0): Video/Source, media.role=Camera
      ├→ PipeWire programs
      └→ libandroid-v4l2.so → pw-v4l2 (patched, loaded privately) → V4L2 programs
         device files: $XDG_RUNTIME_DIR/android-v4l2/{dev,sys/class/video4linux,state}
```

- **`android-v4l2 run`** is started by the desktop for each session, before
  `gnome-session`, with the session's runtime directory and buses. It reads
  the cameras' characteristics through `camera-list` (opening none), then runs
  a PipeWire, WirePlumber's `policy` profile (which probes no hardware) and one
  `camera-node` per camera. It restarts a node that dies, after removing the
  device files it left, and starts everything over if PipeWire or WirePlumber
  exits. It stops with the session. Its programs run without
  `LD_LIBRARY_PATH`, which would load libandroid-stub's `libmediandk.so` in
  place of Android's. Logs: `~/.local/state/android-v4l2/`.
- **`camera-node`** publishes its device only once PipeWire has registered the
  node. When Android takes the camera away, the node keeps the same device and
  name and reopens that camera once no other camera of ours is open. Without
  that wait, two programs streaming at once would take the camera from each
  other forever. This phone runs one camera at a time.
- **`libandroid-v4l2.so`** is in the session's `LD_PRELOAD` for every program
  the desktop starts, after the other preloads, once a test program starts
  with it. For `/dev/videoN` it serves `stat`, `/dev` listings and
  `/sys/class/video4linux`, and it passes `open`, `ioctl` and `mmap` to
  `pw-v4l2`. Other paths pass through unchanged. How it stays safe inside
  Bionic's own start-up is described in the
  [investigation](../termux-camera-investigation.md#the-virtual-device).

The audio-effects PipeWire is a separate instance with its own runtime
directory, and the desktop's PulseAudio is not replaced.

## Status and control

`livecd status` reports the cameras under `integrations.features.camera`:

```json
{"status": "ready", "devices": [{"device": "/dev/video0", "name": "Front camera", "state": "idle"},
                                {"device": "/dev/video1", "name": "Rear camera", "state": "idle"}]}
```

A device's `state` is `idle`, `open`, or `waiting REASON` while a program
streams without a camera: `in-use` when another app or our other camera holds
it, and `permission-denied` without the `CAMERA` permission. A refusal also
puts the grant command in `detail`.

- `android-v4l2 list` shows Android's cameras and the choice, without opening any.
- `"camera": false` in `~/.config/livecd-native/integrations.json` turns the
  integration off from the next desktop start.

### Permission

Termux has no `CAMERA` permission of its own. Termux:API shares its user ID, so
`install.sh` grants the permission to Termux:API through Shizuku, as it does for
the microphone, and that grant covers every Termux process. By hand:

```sh
adb shell pm grant com.termux.api android.permission.CAMERA
```

Revoking the permission kills every Termux process, including the desktop.
Android 11 shows no camera indicator for Termux. GNOME Shell's own camera
indicator is built out (`-Dcamera_monitor=false`).

## Coverage

| Programs | Path | State |
| --- | --- | --- |
| Bionic programs using V4L2 directly or through `libv4l2` | Preload | Stream each camera, switch and share in the installed desktop (see [Results](#results)) |
| Termux's Chromium (Bionic) | Preload, its V4L2 backend | Streamed in the prototype; not installed on the test phone now |
| PipeWire clients | The session's PipeWire | Nodes registered with names and device paths |
| Firefox (Termux, Bionic) | Preload | Lists and streams both cameras in the installed desktop, started by its launcher |
| FFmpeg `-f v4l2` | Preload | Streams both cameras in the installed desktop |
| glibc programs, including the glibc browsers | — | Not covered: their launchers drop Bionic preloads, and no glibc build of the preload exists |
| Camera portal clients (Flatpak-style, Snapshot) | — | Not covered: no `xdg-desktop-portal` in the desktop |
| Static programs, inline system calls, `openat` relative to an open `/dev` | — | Not covered by a preload |
| GStreamer `v4l2src`/`pipewiresrc` | — | Termux's build lacks these plugins |

The V4L2 back end offers memory-mapped capture only. The
[backend audit](../camera-session-and-proot.md#exact-backend-coverage) lists the
ioctls and buffer modes it lacks; `VIDIOC_S_PARM` does not change the rate.

## Tests

| Test | Runs | Covers |
| --- | --- | --- |
| [`test-camera-controller.py`](../../tests/camera/test-camera-controller.py) | Host, CI | Camera choice, helper environment, desktop preload and status, permission notice, and the supervisor's start, restart and cleanup against stand-in programs |
| [`test-desktop-camera.py`](../../tests/camera/test-desktop-camera.py) | Inside the installed desktop: `livecd-native exec python …` | The desktop's preload in its own processes, status, discovery, PipeWire nodes and idle state; with `--stream`, each camera, switching both ways, release and both at once. It starts nothing of its own, so a missing integration fails it |
| [`test-v4l2-preload.sh`](../../tests/camera/test-v4l2-preload.sh) | Phone, private session | The installed binaries with negative controls, `libv4l2`, Chromium if present, and the preload's per-call cost |

Camera tests record whoever is in front of the phone. They report frames only
as rates, latency and luma levels, and keep no picture.

### Results

On the Note10+ (Android 11), with `android-v4l2` 0.1.0 installed and the
`CAMERA` permission not granted, in a private session:

- `android-v4l2 list` chose front = camera 1 and rear = camera 0, and skipped
  camera 4 (depth, no YUV) and the two extra lenses.
- Both devices passed all seven device checks: character device 81:N, access,
  `/dev` listing with the phone's own blocked nodes hidden, entry type, sysfs
  name, `realpath`, and `open`/`fstat`.
- PipeWire listed `Front camera v4l2:/dev/video0` and `Rear camera v4l2:/dev/video1`.
- A stream negotiated YUYV 1280×720, received no frames, and the front device
  reported `waiting permission-denied`. The camera node retried every 2 s while
  the stream lasted and returned to `idle` after.
- On stop, the supervisor's PipeWire, WirePlumber and nodes exited and the
  device files were removed, while the audio-effects PipeWire kept running.

In the installed desktop on the same phone, upgraded from v0.12.0 with
`install.sh`, `CAMERA` granted, started by `livecd start`:

- `livecd-native status` reported the camera `ready` with `/dev/video0` Front
  camera and `/dev/video1` Rear camera, both `idle`.
- `test-desktop-camera.py --stream` passed 15 of 15. Front YUYV 150 frames at
  29.4 fps, rear NV12 at 28.5 fps, front again at 29.2 fps, both released.
  Asked for at once, the newer rear stream took its camera at 28.8 fps and the
  older front stream resumed the same camera afterwards.
- Firefox, started by the desktop's launcher, listed "Front camera" and "Rear
  camera" and streamed each at 1280×720, 27.6 and 27.8 fps.
- `ffmpeg -f v4l2 -video_size 1280x720` read 60 frames from each device at
  29 and 30 fps.
- `livecd validate` passed all 29 checks.

Two fixes outside this package were needed. Closing a camera deadlocked under
the session's `libandroid-procfs.so` preload, whose `close()` held its lock
while pw-v4l2 waited for threads that close files too; the runs above used the
fixed preload. Startup on the upgraded install also timed out on a leftover
`livecd-appearance@local` in the enabled extensions. Both were fixed in
`android-procfs` 1.0.0-4 and `livecd-desktop` revision 7.
