# Android-managed Bluetooth devices for Linux applications

## Result

The Note10+ / Android 11 rig captured and played audio through a connected
Sony WI-C310 headset using named PulseAudio devices. A small Java helper, launched as shell by
the existing authorized Shizuku export, requested the HFP audio connection. The headset remains
paired and connected when the audio route is released; pairing and Bluetooth connections stay
under Android's control.
Neither Termux nor Termux:API was rebuilt, reinstalled or granted new permissions.

The Linux-visible endpoints are:

| PulseAudio name | Application-visible description | Backing path |
| --- | --- | --- |
| `android_bluetooth_input` | WI-C310 Microphone | Native OpenSL recorder, 48 kHz mono |
| `android_bluetooth_output` | WI-C310 Headphones | PulseAudio FIFO → native OpenSL voice player, 16 kHz mono |

These are ordinary PulseAudio devices. Applications select them through their normal audio
settings, `pavucontrol`, or `PULSE_SOURCE`/`PULSE_SINK`; they do not access a Linux Bluetooth adapter.

AudioFlinger's active recording thread reported:

```text
Input device: 0x80000008 (AUDIO_DEVICE_IN_BLUETOOTH_SCO_HEADSET|AUDIO_DEVICE_IN_ALL_SCO)
Audio source: 6 (AUDIO_SOURCE_VOICE_RECOGNITION)
Sample rate: 48000 Hz
Channel count: 1
Standby: no
```

The initial native `android_microphone` delivered 576,000 samples in a 12-second capture. The test retained
only levels, not audio. Android reported `SCO_STATE_ACTIVE_EXTERNAL` during the capture and
`SCO_STATE_INACTIVE` afterwards. PulseAudio returned to `android_no_microphone`; the helper and
its staged DEX directory exited/removed themselves.

The later named-device test captured 288,000 samples from `android_bluetooth_input` while
`pacat` played a generated tone through `android_bluetooth_output`. AudioFlinger simultaneously
reported `AUDIO_DEVICE_IN_BLUETOOTH_SCO_HEADSET` and
`AUDIO_DEVICE_OUT_BLUETOOTH_SCO_HEADSET`. The user confirmed hearing the repeated tone in the
headset. The native player selects `SL_ANDROID_STREAM_VOICE`; desktop media playback is not used
as a substitute for the voice output.

The application-facing PCM rates do not establish the headset codec's actual bandwidth or
speech quality. A real voice call was not tested.

The built `android-pulseaudio-mic` **0.1.0-1** package was then installed through APT on the rig. Its installed
commands passed three additional checks: an invalid device was rejected without opening capture;
a four-second native capture delivered 192,000 samples and cleaned up on child exit; SIGTERM
returned the microphone to silence and released SCO. The final Android mode was normal. Host
checks passed all ten original session/protocol tests and nine packaging tests. The later
**0.1.0-2** package adds the native voice player, named endpoints and background device controller;
the expanded host suite has thirteen tests covering session cleanup, defaults and partial startup.
Installed-package checks passed for named device descriptions, default preservation, idempotent
background `on`, upgrading an active session to `--default`, normal `off` restoration and SIGTERM.
An additional test force-killed only its own idle controller, then verified that explicit `off`
removed the orphaned endpoints and released the native output. The devices were left enabled
after acceptance, with the previous desktop defaults preserved.

## What the linked PR supplies

[Termux:API PR #857](https://github.com/termux/termux-api/pull/857) adds a standalone `AudioSco`
API and automatic SCO activation for its own MediaRecorder's `VOICE_COMMUNICATION` source.
Its [companion shell-package PR #236](https://github.com/termux/termux-api-package/pull/236)
provides `termux-audio-sco`. Both were open and unmerged when checked. Inspected heads:

- APK: `1ec0903aec7de7f0192bb833d7af7217f743e22c`
- Shell package: `d5d9bc3af2f21bf2205d1b9c5f36b1cad71a502b`

Our microphone uses PulseAudio's OpenSL module, so changing the file recorder alone would not
affect Linux applications. The standalone routing idea applies, but the installed F-Droid
Termux:API 0.53.0 does not implement `AudioSco`: a bounded read-only request timed out after
eight seconds. A separately signed PR APK also cannot replace a differently signed Termux
shared-UID add-on. The integration therefore uses the existing Shizuku shell identity instead.

## Android permission boundary

Shell privilege does not imply every Android permission. On this phone, `com.android.shell`
does not declare `MODIFY_AUDIO_SETTINGS`. Both `AudioManager.setMode()` and
`startBluetoothSco()` returned without an exception while AudioService logged permission denial.
The helper now checks that permission before choosing a backend.

On Android versions below 12 without that permission, it obtains
`BluetoothProfile.HEADSET` through `BluetoothAdapter.getProfileProxy()`, then calls
`BluetoothHeadset.startVoiceRecognition()` for the single connected headset. Android's Bluetooth
service establishes SCO and AudioService applies the recording route. This uses the shell's
existing Bluetooth permission. It does not invoke a speech recognizer or save a recording.

Where shell has `MODIFY_AUDIO_SETTINGS`, the helper uses `AudioManager`: communication mode
and `setCommunicationDevice()` on Android 12+, or legacy SCO on older Android. The newer
branch includes BLE headsets and route/mode listeners, but has not been exercised on a device.
Android 12+ builds without the audio-settings permission fail explicitly.

Relevant primary sources:

- [BluetoothHeadset.startVoiceRecognition](https://developer.android.com/reference/android/bluetooth/BluetoothHeadset#startVoiceRecognition(android.bluetooth.BluetoothDevice))
- [Android 11 BluetoothHeadset profile binding](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android11-release/core/java/android/bluetooth/BluetoothHeadset.java)
- [Android 11 BtHelper: external SCO events](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android11-release/services/core/java/com/android/server/audio/BtHelper.java)
- [Android 11 audio permission enforcement](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android11-release/services/core/java/com/android/server/audio/AudioService.java)
- [AudioManager communication-device selection and request lifetime](https://developer.android.com/reference/android/media/AudioManager#setCommunicationDevice(android.media.AudioDeviceInfo))

## Native integration and lifecycle

```text
android-pulseaudio-bluetooth (Termux Python controller)
  ├─ Shizuku/rish → shell app_process → Bluetooth/AudioManager routing only
  ├─ Android microphone → module-sles-source → named input → Linux applications
  └─ Linux applications → named pipe sink → native OpenSL voice player → Android output
```

The package builds a native C voice player and compiles its readable Java source into a small
DEX at build time. Each routing invocation
stages it into a shell-owned temporary directory, verifies its checksum and marks it read-only
before loading it. No Android SDK or JDK is needed on the phone. No PCM crosses the privileged
helper's control connection, and no new APK or permanent privileged daemon is installed. Playback
PCM stays in the Termux UID, in a FIFO under a private temporary directory and a four-buffer
native OpenSL queue. The output player uses 20 ms blocks at 16 kHz mono; PulseAudio handles
application format conversion.

SELinux on the rig denied a shell-to-Termux Unix socket connection, so the controller uses an
ephemeral IPv4 loopback listener and a random one-use authentication token. The helper connects
out to the native controller. It processes one route request, then waits for session termination.
The Shizuku client and helper Java processes remain alive only during that invocation.

`devices` queries Android without enabling capture. `on` starts a background native controller;
the paired audio endpoints remain available after the command exits. It takes a per-Termux session lock,
requires the existing microphone to be off, and refuses an active Android audio call/SCO route.
It only publishes the native microphone and output after the helper reports the requested route.
An existing `module-suspend-on-idle` is reused; otherwise the session owns one with a one-second
timeout. The microphone recorder closes while unused. With multiple
Android 12+ devices, an explicit device ID is required; legacy profile routing requires exactly one
connected headset. IDs are temporary Android port IDs, not persistent device identifiers.

`on` preserves the previous PulseAudio defaults; `on --default` selects both headset endpoints.
`call` holds the same endpoints in the foreground and makes them defaults for its duration.
Per-application selection works regardless of the default choice. `status` and `off` communicate
with the native controller through a private local control socket, without starting another
Shizuku helper. `off` removes only the owned endpoints and restores defaults when they still
point to the headset. A user's intervening default-device changes are preserved.

On `off`, child exit, Ctrl-C, SIGTERM or SIGHUP, capture is disabled before the route is released.
A socket EOF makes the helper release its own requested route. Older Android has no suitable
AudioManager route callback for this shell process, so the helper checks SCO/mode every 250 ms
only while the session is active. Newer Android uses listeners.

## Limits and remaining acceptance

- Only the Android 11 legacy headset-profile backend has device acceptance so far.
- The existing OpenSL source follows Android's routing policy. It is not pinned to a headset
  input, so Android can fall back before the controller detects loss and switches to silence.
- SIGKILL cannot run the controller's endpoint cleanup. A later explicit `off` also removes orphaned
  endpoints and closes their playback pipe. A killed route helper may also leave
  legacy voice-recognition SCO active because that API has no per-client Binder ownership.
  Recover with `android-pulseaudio-bluetooth off` and disconnect/reconnect the headset if needed.
- Output is currently a mono 16 kHz voice stream, even if the headset also supports higher-quality
  A2DP or LE Audio. High-fidelity Bluetooth media profiles are outside this call-audio bridge.
- No acoustic speech-quality comparison, controlled headset disconnect, real incoming phone call,
  screen-off run, long call, or Android 12+ device test has been accepted yet.
- Headsets that reject voice-recognition SCO fail without enabling the PulseAudio microphone.

Local raw evidence is under the Git-ignored `temp/mic-bluetooth/`, including PR snapshots,
`shizuku-devices.txt`, `device-test.txt`, `profile-during-audio.txt`,
`profile-during-flinger.txt`, `profile-after-audio.txt` and the package build log.
`installed-device-tests.txt` and `package-install.txt` record installed-package acceptance.
See [privacy notes](../privacy.md) before sharing captures.

The named-device captures are separately under `temp/mic-devices/`: `duplex-result.txt`,
`duplex-flinger.txt`, `duplex-audio.txt`, the current package build/install logs and device tests.
`recovery-and-final-on.txt` and `final-pulse-state.jsonl` capture recovery and the final enabled pair.
The audible output acceptance was supplied directly by the user in this session.

Recheck the installed package with `python tests/mic/test-bluetooth-device.py` in Termux, with
the desktop running, microphone off, and a connected headset. This explicitly exercises capture,
an invalid device request, normal exit, SIGTERM cleanup, background `on`/`off`, named device
descriptions and default preservation/restoration. Host lifecycle checks run with
`python3 tests/mic/test-bluetooth.py` and are also included in package CI.
