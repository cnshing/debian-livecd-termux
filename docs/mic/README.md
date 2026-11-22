# Native Termux microphone

An **opt-in Android microphone** for the native desktop's PulseAudio, with a silent source that
keeps recording apps away from the speakers while it is off. Tested on the established Note10+ /
Android 11 rig; see [device results](VERIFICATION.md).

```text
Android microphone → OpenSL ES → module-sles-source → PulseAudio → desktop applications
```

## Why a silent source is always loaded

With no microphone, PulseAudio's default source is the speaker monitor. An application that records
"the default microphone" then captures whatever the phone is playing, and in a call it would send
that to the other people. If a microphone disappears, the default falls back the same way, with no
warning. The [native desktop](../../src/native/desktop.py) therefore starts PulseAudio with a silent
`android_no_microphone` source, which takes that fallback role. `android-pulseaudio-mic` also loads it if needed.

## Set up

Termux does not declare `RECORD_AUDIO`. Termux:API does and shares Termux's Android UID, so its
permission applies to Termux's processes.

1. Install the Termux:API app from the same source as Termux. Android rejects a differently signed
   build. The `termux-api` package alone does not supply the app.
2. Run `install.sh`. The Microphone overlay is a default, and setup grants the permission through
   Shizuku. Without Shizuku, grant it from a PC:

```sh
adb shell pm grant com.termux.api android.permission.RECORD_AUDIO
```

**The permission then applies to every Termux process, not just one application.** Android 11 shows
no microphone indicator. To withdraw it:

```sh
adb shell pm revoke com.termux.api android.permission.RECORD_AUDIO
```

## Use

```sh
android-pulseaudio-mic on       # load the microphone and make it the default source
android-pulseaudio-mic status
android-pulseaudio-mic test     # report the default source's level; the audio is discarded
android-pulseaudio-mic off      # unload it; the silent source becomes the default
```

The native desktop publishes a connected Bluetooth headset microphone in on-demand mode
at startup, falling back to the phone microphone if no headset is available. The Bluetooth
mic is enumerated while idle without opening Android capture or call routing. See
[session integration settings](../native/README.md#session-integrations) to disable either hook.
Outside that lifecycle, the setting lasts until PulseAudio stops, so run `on` again after restarting it.
Android's recorder stays closed until something records. Anything with a level meter counts as recording, such
as `pavucontrol` on its Input Devices tab, so close it when finished.

## Android-managed Bluetooth audio devices

`android-pulseaudio-bluetooth` requests Android's Bluetooth call-audio connection through the existing
authorized Shizuku/rish export. Termux, Termux:API and Linux applications need no APK changes.
Linux applications see a persistent microphone such as **WI-C310 Microphone**.
A temporary **WI-C310 Headphones** call output appears while recording. Android manages pairing, connections and the active headset.
The microphone uses native OpenSL capture; the output uses a PulseAudio pipe sink and a small
native OpenSL voice player. Linux applications do not need Bluetooth APIs or BlueZ.
See the [Bluetooth investigation and device results](BLUETOOTH.md) for the permission checks,
tested headset and limitations.

With Shizuku running, Termux authorized, and `rish` exported into `~/.local/lib/shizuku`:

```sh
android-pulseaudio-bluetooth devices
android-pulseaudio-mic off
android-pulseaudio-bluetooth auto --default   # publish the mic as default; keep media playback while idle
android-pulseaudio-bluetooth status
# Select the named Microphone in an application's settings, or use the default input.
android-pulseaudio-bluetooth off              # remove the mic and release any owned call route

# For applications selecting their own mic, preserve the existing input default:
android-pulseaudio-bluetooth auto

# Explicitly hold call routing open, including when no application records:
android-pulseaudio-bluetooth off              # stop auto mode before switching modes
android-pulseaudio-bluetooth on --default
# Or hold it for a foreground application:
android-pulseaudio-bluetooth off
android-pulseaudio-bluetooth call -- YOUR_CALL_APPLICATION
```

Connect the headset in Android first, with **Calls** enabled. `--device ID` selects an ID from
`devices`; IDs can change after reconnecting. `ANDROID_PULSEAUDIO_RISH` selects another `rish` export.
`auto` keeps `android_bluetooth_input` available until `off` or controller shutdown.
Its `--default` option changes only the input default. An uncorked recording stream
activates Android call routing, then native capture; there can be a delay of several seconds
before the first samples arrive. Playback on the current default sink moves to the call
output for that recording session, and surviving streams return to their media sink afterward.
Other explicitly selected sinks are preserved, as are intervening user changes to defaults.
The last recorder closing or corking closes native capture before releasing SCO.
Level meters count as recorders; application mute alone does not close an active recording stream.
On route failure the source stays enumerated without opening a substitute phone recorder;
`status` exposes `route_error`, and the controller retries after five seconds while capture
is still requested. There is no headset pairing/connect watcher.

The older `on` and `call` commands still hold SCO open throughout their session, even when
capture is idle. `on --default` selects both voice endpoints; `call` does so for the foreground
session and ends on application exit or Ctrl-C. Run `off` after using either held mode to
allow normal media playback again. Use `off` before switching between held and automatic modes.
Defaults are restored on cleanup unless the user changed them in the meantime.

Applications can select the persistent PulseAudio name `android_bluetooth_input`, including
through `PULSE_SOURCE`. Leave playback on the ordinary desktop output in auto mode;
`android_bluetooth_output` exists only while the call route is active. Applications need the
desktop's usual `PULSE_SERVER`, just as with other native audio.

Input and output were exercised together on the Android 11 rig, and the user confirmed hearing
the playback tone in the headset. The output currently uses mono 16 kHz call audio, with PulseAudio
resampling application streams. Real calls, speech quality, latency and other Android versions
still need testing. Android can fall back to the phone mic between a headset disconnect and
detection; force-killing the controller skips its cleanup. This experimental path does not
guarantee headset-only capture during failures.

## Serein and other cpal applications

These notes come from running Serein's audio engine on Bionic with
[`serein-probe`](../../tests/mic/serein-probe). They cover only the audio engine;
the separate [full-client package](../serein/README.md) records its own build and runtime status.

- **Block size:** cpal 0.18.2 limits a record stream's queue to one fragment, and Serein asks for
  20 ms. PulseAudio discards larger blocks, so `play()` waits forever and neither the microphone nor
  the speakers start, with no error. A sink monitor and `module-sles-source`'s default 125 ms blocks
  both trigger this, so `android-pulseaudio-mic` loads the microphone with 20 ms blocks.
- **Vendored cpal:** [`cpal-record-queue.patch`](../../tests/mic/serein-probe/cpal-record-queue.patch) removes the
  stall for every source. A port should carry it, and must keep the silent source too: with the
  stall gone, a monitor default sends speaker audio into the call.
- **Device list:** Serein also offers `Monitor of OpenSL ES Output`. Selecting it sends speaker audio.
- **Environment:** run applications with the desktop's `PULSE_SERVER`. Without it, cpal selects ALSA,
  which has no device here.

## Files

| File | Purpose |
| --- | --- |
| `mic.py` | The `android-pulseaudio-mic` command |
| `bluetooth.py`, `java/org/livecd/mic/AudioRoute.java`, `sco-output.c` | Named Linux audio devices, Shizuku routing and native voice playback |
| `test-bluetooth.py` | Host checks for held-session failure, ownership and capture cleanup |
| `test-auto-bluetooth.py` | Real isolated PulseAudio checks for enumeration, multiple clients, cork/resume, playback migration and route failure |
| `test-bluetooth-auto-device.py`, `cork-recorder.py` | Installed phone acceptance; counts and discards samples, checks SCO and media restoration |
| `test-mic.sh` | The command against a private PulseAudio |
| `test-serein.sh` | Serein's source selection, with stand-in microphones |
| `test-real-mic.sh` | Block sizes, recorder state and Serein's engine on the real microphone |
| `test-desktop.sh` | Detection inside the running desktop session |
| `test-acoustic.sh` | Vibration pulses; [inconclusive on this phone](VERIFICATION.md#limits) |
| `serein-probe/` | Builds Serein's unmodified audio engine for Bionic from a pinned release |
