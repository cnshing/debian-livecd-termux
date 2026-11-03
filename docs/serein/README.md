# Serein on native Termux

[`packages/serein`](../../packages/serein) builds the complete
[Serein client](https://github.com/ViceVerse-cz/Serein), including its GUI, WebKitGTK
login window, voice engine and media support, for Android/Bionic with Termux:X11.
This is separate from the earlier [audio-engine probe](../mic/VERIFICATION.md).

The aarch64 package has been built and its offline GUI tested on the phone with
OpenGL and Vulkan, including startup in the managed GNOME session. Account
sign-in and live Discord calls remain untested. See [verification](VERIFICATION.md).

The source is pinned to `v1.0.0-nightly.20261028.68`, the release used by that probe.
The recipe verifies the source archive's SHA-256. It vendors the upstream Cargo
lockfile before applying Android changes, resolves the adjusted graph offline,
and rejects any dependency version, source or package checksum outside that lock.

## Build and install

Use the project's ordinary package builder on a Linux host with Docker/Podman:

```sh
bash tools/build-packages.sh serein
```

Or, with the managed desktop stopped, build and install in native Termux:

```sh
bash tools/build-packages.sh --install serein
```

The first port targets **aarch64**. The build needs substantial disk space for
Rust dependencies and artifacts. The recipe uses thin LTO and two build jobs by
default through the project's helper; `JOBS` can override the job count.
See [the shared build instructions](../structure.md#building-packages).

The package installs `serein`, an application-menu entry, its icon and license
notices. It is optional and is not added to the default desktop installation.
Updates belong to APT; the client cannot replace itself with an upstream Linux
binary. No public package release is implied by the local recipe.

## Run

Launch **Serein** from the desktop's application menu, or use its environment:

```sh
~/.local/bin/livecd-native exec serein
```

An offline fixture UI is included for validation without signing in:

```sh
~/.local/bin/livecd-native exec serein --demo
```

The desktop supplies `DISPLAY`, its D-Bus session and `PULSE_SERVER`. Voice uses
PulseAudio, rather than Android's Activity/AAudio integration. Enable the real
microphone separately using the [microphone setup](../mic/README.md); the desktop
keeps a silent default source while it is off. Selecting a speaker monitor in
Serein records speaker output.

## Port changes

- Select the Linux desktop implementations in Serein and the specific window,
  clipboard, audio, accessibility, font and TLS dependencies that otherwise expect
  an Android APK. Keep Android's real Rust target, libc and syscall dependencies.
- Build X11 window support. Wayland window support is disabled for this port.
- Use Termux's temporary paths and library names where desktop crates hardcode
  Linux paths or versioned SONAMEs.
- Use the Unix TLS verifier and Termux's CA bundle without requiring a JVM.
- Carry the [tested cpal recording-queue fix](../../packages/serein/cpal-record-queue.vendor.diff)
  so fixed-size PulseAudio input blocks do not stall the engine.
- Supply Android's missing case in the bundled Opus build script and use Termux's
  Bionic compiler wrappers for its CMake build.
- Keep exclusive attachment saves available at Android API 24 through a
  `renameat2` syscall wrapper; existing destinations remain protected.
- Compile the packaged data configuration, with offline demo fixtures available
  only when explicitly requested with `--demo`.

See [build and runtime verification](VERIFICATION.md) for current results and
limits. The earlier microphone results establish audio-engine behavior only.

## Offline GUI check

The device test uses a private Xvfb display, scratch data directories and a private
D-Bus session. It checks rendered pixels, window resizing and keyboard quit:

```sh
python tests/serein/test-desktop.py --binary serein --out /path/to/new/results
```

It needs Xvfb, xdotool, dbus-run-session and Python GI with GTK3. Add
`--backend vulkan` to test Vulkan instead of OpenGL. It never signs in or opens
the microphone, and stops its private processes after success or failure.
