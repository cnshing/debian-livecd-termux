# Shared native acceleration setup

`setup.py` installs the common application launcher, saves an optional video
preference, and selects immutable ABI-specific driver directories. It does not
start applications, restart the desktop, or run playback checks.

The MediaCodec daemon is built independently of Chrome from `daemon.lock.json`
and installed under its own immutable service directory. Activating it does not
stop or replace the currently running shared daemon.

On native aarch64 Termux, build and install the Bionic VA-API stack:

```sh
python prebuilt/native-video/setup.py --build-native --enable --jobs 2
```

GPU rendering follows the existing native renderer selection. This command builds
the video layer; installing/selecting the Turnip/Zink GPU profile remains the
separate flow documented in [the native desktop guide](../../docs/native/README.md).

The build needs Clang/LLVM tools, Ninja, pkg-config, Bison, Flex, patchelf, and
the native development files supplied by libandroid-shmem, libdrm, libwayland,
libwayland-protocols, libx11, libxcb, libxext, libxfixes, libxshmfence, zlib and
Vulkan headers. Python build dependencies are installed into a private venv.
Missing build dependencies are reported; the script does not upgrade APT packages.

Archives and versions are pinned in `sources.lock.json`. The Mesa port patches
come from Termux's pinned `538685c906074926fd19650e38c6dad91379eb0f` checkout, with
the header-detection hunk adapted to this fork. The separate `tva_ion.h` implements
the unprotected ION allocation route already measured on the Note10+. The daemon
protocol header in this Mesa pin matches the installed `ae14813` daemon.

The build uses a cross file with `needs_exe_wrapper=true`, disables Mesa tests,
and never executes a built target binary. It stages its own libva and Mesa;
it does not replace the running desktop's Mesa. Only the VA client directory is
added to a native application's library path, preserving its existing GL/EGL/GBM.
The ION fallback is compiled into the new VA driver, so native applications do not
load the experimental glibc ION preload.

For the already applied glibc Chrome stack on this phone:

```sh
python prebuilt/native-video/setup.py --migrate-glibc --enable
```

This copies the existing Mesa, support libraries and exact pinned ION adapter to
a shared immutable glibc directory and rewrites its Vulkan manifest. The original
Chrome files remain available to running processes. This migration requires the
previously installed adapter; it does not manufacture a glibc driver from Bionic
libraries or claim to bootstrap a fresh glibc installation.

To activate a build already produced by `build-native.py`, use
`--native-stack /absolute/path/to/acceleration/bionic-BUILD`. Both ABI options can
be supplied to the same setup invocation. Installation receipts and backups are
under `~/.local/state/livecd-native/`.

## Hardware encoding for every program

The same stack encodes H.264 (Constrained Baseline, Main, High) and HEVC Main
through Android's hardware encoders, for any program that uses VA-API: GStreamer's
`vah264enc`/`vah265enc` (Serein's camera and screen share), FFmpeg's
`h264_vaapi`/`hevc_vaapi` (the `ffmpeg` command, OBS's VAAPI encoder), and others.
Programs find the encoder the way they do on Linux, as `/dev/dri/renderD128`, with
no per-program device, driver or flag:

- `livecd-render-node.c`, built into the stack as `liblivecd-render-node.so`,
  presents KGSL as that render node. The phone's own `/dev/dri` nodes belong to
  the display controller and SELinux denies them to apps. It answers the DRM
  name query with `kgsl`, so libva loads `kgsl_drv_video.so` from the stack.
- `mesa-patches/0100-livecd-termux-va-encode.patch` adds per-picture key frames
  and bitrate changes, advertises only the encoders the daemon backs with
  hardware, applies the bridge's KGSL settings without `TERMUX_VA_*`
  variables, and adds `TERMUX_VA_DECODE=0`, which hides the decoders.
- `daemon-patches/0001-livecd-encoder.patch` makes the Snapdragon 855's OMX
  encoders configure at all, by retrying without the Android 11 `low-latency`
  key that they reject. It also honors those per-picture requests, repeats
  parameter sets on key frames, and lists the hardware encoders beside its socket.

```sh
python prebuilt/native-video/setup.py --build-native --native-encode on --jobs 2
```

From the next desktop session, `desktop.py` adds the preload to the session's
preloads, after the same start-up probe the resources preload passes. It points
libva at the stack's driver directory, sets `TERMUX_VA_DECODE=0` unless
`native_decode` is true in `acceleration.json`, and starts the daemon if none is
listening. Hardware decoding therefore stays opt-in, through the launchers above.
The setup never stops a running daemon; one started before the setup keeps
serving, unpatched, until the desktop restarts.

Programs need VA-API builds: Termux's `libva`, and FFmpeg, GStreamer's `va` plugin
or OBS built with their standard VA-API options. Termux builds them without.
Test builds of FFmpeg 9.0.2 and gst-plugins-bad 1.28.8 needed only build settings:
GStreamer skips its `va` plugin when Meson reports the host as `android`, and
FFmpeg's libv4l2 input needs `-Wno-error=incompatible-function-pointer-types`
with Bionic's `ioctl`. Results and the test suite are in
[the encoding report](../../docs/native/ENCODING.md).

The Chromium recipe in `packages/chromium` enables VA-API and uses the new
`packages/libva` headers. It must be built with the pinned termux-packages builder;
stock installed Chromium remains on software video until that build is installed.
See [application configuration](../../docs/native/ACCELERATION.md).

Firefox's native Linux backend needs two additional compatibility pieces on KGSL:

```sh
python prebuilt/native-video/setup.py --firefox-kgsl --firefox-ffmpeg --enable --jobs 2
```

`--firefox-kgsl` builds Mozilla's pinned, standalone graphics probe with a narrow
KGSL port. When the GL renderer is Zink/Turnip Adreno and the selected KGSL node can
be opened, the probe reports that hardware renderer and node instead of the X11
platform's misleading software-device classification. Its VA-API probe still
queries the actual driver and supported codecs. The installed Firefox package is
copied to an immutable private directory with this probe; package files are not
edited. Two private library aliases supply the desktop sonames for native GBM/DRM.
The launcher rejects a private copy after the installed Firefox version changes;
rerun setup to refresh it.

`--firefox-ffmpeg` builds pinned FFmpeg decoder libraries with VA-API, preserving
the internal software decoders as fallbacks. Firefox already includes FFVPX for
VP9, but HEVC needs these system-style FFmpeg interfaces. The existing Termux
FFmpeg command and its Android MediaCodec backend remain available. The new
libraries are selected only for Firefox's hardware-video profile; neither mpv nor
the desktop inherits them. These private sources are pinned and updated through
this repository's lock files.

For off-device packages, `tools/build-packages.sh` detects Docker or Podman, or
accepts `LIVECD_CONTAINER_ENGINE=podman`. The Podman entry point uses the same
pinned Termux image and checkout, maps the image's builder account to the current
user, and retains build state under `~/.cache/livecd-podman-build/`. It supplies
FUSE inside the rootless container for Termux's build overlay. Build jobs default
to two; set `JOBS` to change that limit.
