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

The native desktop now calls the existing microphone controllers on startup when installed:
it tries Bluetooth with `on --default`, then the ordinary microphone if Bluetooth is unavailable.
See [session integration settings](../native/README.md#session-integrations) to disable either hook.
Outside that lifecycle, the setting lasts until PulseAudio stops, so run `on` again after restarting it.
Android's recorder stays closed until something records. Anything with a level meter counts as recording, such
as `pavucontrol` on its Input Devices tab, so close it when finished.

## Android-managed Bluetooth audio devices

`android-pulseaudio-bluetooth` requests Android's Bluetooth call-audio connection through the existing
authorized Shizuku/rish export. Termux, Termux:API and Linux applications need no APK changes.
Linux applications see a named PulseAudio output and microphone, such as **WI-C310 Headphones**
and **WI-C310 Microphone**. Android manages pairing, connections and the active headset.
The microphone uses native OpenSL capture; the output uses a PulseAudio pipe sink and a small
native OpenSL voice player. Linux applications do not need Bluetooth APIs or BlueZ.
See the [Bluetooth investigation and device results](BLUETOOTH.md) for the permission checks,
tested headset and limitations.

With Shizuku running, Termux authorized, and `rish` exported into `~/.local/lib/shizuku`:

```sh
android-pulseaudio-bluetooth devices
android-pulseaudio-mic off
android-pulseaudio-bluetooth on               # publish the devices; existing desktop defaults stay selected
android-pulseaudio-bluetooth status
# Select the named Headphones and Microphone in the application's audio settings or pavucontrol.
android-pulseaudio-bluetooth off              # remove the devices and release SCO; leave Bluetooth connected

# Make both devices the desktop defaults instead:
android-pulseaudio-bluetooth on --default
# Or scope the default devices to a foreground session/application:
android-pulseaudio-bluetooth call -- YOUR_CALL_APPLICATION
```

Connect the headset in Android first, with **Calls** enabled. `--device ID` selects an ID from
`devices`; IDs can change after reconnecting. `ANDROID_PULSEAUDIO_RISH` selects another `rish` export.
`on` keeps the devices available after the command exits, until `off`, route loss or a controller
error. The microphone suspends while no application records. `call` holds the same devices in the
foreground, makes them defaults for its duration, and ends on application exit or Ctrl-C.
Defaults are restored on cleanup unless the user changed them in the meantime.

An application can also select the stable PulseAudio names `android_bluetooth_output` and
`android_bluetooth_input`, including through `PULSE_SINK` and `PULSE_SOURCE` in a desktop terminal.
Applications need the desktop's usual `PULSE_SERVER`, just as with other native audio.

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
| `test-bluetooth.py` | Host checks for session failure, ownership and capture cleanup |
| `test-mic.sh` | The command against a private PulseAudio |
| `test-serein.sh` | Serein's source selection, with stand-in microphones |
| `test-real-mic.sh` | Block sizes, recorder state and Serein's engine on the real microphone |
| `test-desktop.sh` | Detection inside the running desktop session |
| `test-acoustic.sh` | Vibration pulses; [inconclusive on this phone](VERIFICATION.md#limits) |
| `serein-probe/` | Builds Serein's unmodified audio engine for Bionic from a pinned release |
