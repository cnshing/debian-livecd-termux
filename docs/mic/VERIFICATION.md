# Native Termux microphone verification

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

> Recorded before the repository restructure. Paths were updated, but build steps and
> install locations describe the earlier on-device flow.

Tested on the established Samsung Note10+ SM-N975U1,
Android 11, kernel 4.14. Termux 0.118.3 and Termux:API 0.53.0, both F-Droid signed, with PulseAudio
17.0. Serein's audio engine comes from release `v1.0.0-nightly.20261028.68`.

**Result: the microphone opens, delivers audio and is detected by the desktop and by Serein's engine.
A controlled sound through the air, a real Discord call and the full Serein application were not
tested.** Scripts report levels only and keep no audio.

For subsequent full-client build and GUI checks, see
[Serein package verification](../serein/VERIFICATION.md).

The later [Bluetooth investigation](BLUETOOTH.md) separately verifies named Linux
headset input/output devices, Shizuku routing, and native OpenSL capture/playback. The historical limits below
describe this original run.

## Accepted checks

| Check | Result | Evidence |
| --- | --- | --- |
| Without the permission | Android refuses: `Request requires android.permission.RECORD_AUDIO`. PulseAudio stays up | baseline (`temp/docs/evidence/mic/baseline-no-permission.txt`), controller (`temp/docs/evidence/mic/controller-no-permission.txt`) |
| After installing Termux:API and granting | `com.termux` reports `granted=true` through the shared UID. Nothing was killed: `com.termux` and `sshd` kept their uptimes of over a day | run (`temp/docs/evidence/mic/real-mic.txt`) |
| Capture rate | 144,000 samples in 3.03 s, with Termux:X11 in the foreground. Android logs `rec start … src:VOICE_RECOGNITION pack:com.termux` | run (`temp/docs/evidence/mic/real-mic.txt`) |
| Desktop default source | `livecd_no_microphone` in the started session | session (`temp/docs/evidence/mic/desktop-session.txt`) |
| X11 mixer, microphone on | `pavucontrol` lists `Microphone`, marked default, and `No microphone` | screenshot (`temp/docs/evidence/mic/desktop-2-on.png`) |
| X11 mixer, while recording | Recording tab shows `cpal-pulseaudio-27567 … from Microphone` | screenshot (`temp/docs/evidence/mic/desktop-4-recording-tab.png`) |
| X11 mixer, microphone off | Only `No microphone` remains, marked default | screenshot (`temp/docs/evidence/mic/desktop-5-off-again.png`) |
| Serein's device list in the session | Default input `Microphone`; also lists `No microphone` and the monitor. Records as s16le, mono, 48 kHz | session (`temp/docs/evidence/mic/desktop-session.txt`) |
| Android's recorder | Closed when idle (`Standby: yes`), open while recording. Without `module-suspend-on-idle` it stays open (`Standby: no`) | run (`temp/docs/evidence/mic/real-mic.txt`) |
| Suspended sink | Resumes repeatedly, with the same monitor level as an unsuspended sink | run (`temp/docs/evidence/mic/speaker-muted-bursts.txt`) |

## Serein's engine

`serein-probe` compiles Serein's own `audio.rs`, `audio/echo.rs`, `activity.rs` and `diagnostics.rs`
for Bionic. The only source changes are the `target_os` substitution in `audio.rs` and the build
target of cpal. It uses `Audio::preview`, the same open path as a call, without connecting to Discord.
The profile bypasses echo cancellation and denoising, so tones stay measurable.

Start-up with the real microphone. `ready` is the engine's own readiness:

| `module-sles-source` block | Stock cpal | With [the patch](../../tests/mic/serein-probe/cpal-record-queue.patch) |
| --- | --- | --- |
| Default, 125 ms | **Never ready** | Ready |
| `latency=20` | Ready | Ready |
| `latency=10` | Ready | Ready |

Source selection, with a -30 dBFS tone playing through the sink:

| Arrangement | Stock cpal | With the patch |
| --- | --- | --- |
| Monitor is the only source, as the desktop was | Selects the monitor and **stalls: no input or output, no error** | Selects the monitor and **hears the tone at -34 dB** |
| Silent source added | -100 dB | -100 dB |
| Stand-in microphone removed mid-call, monitor remaining | Stalled from the start | **Switches to the monitor, -34 dB, `microphone_unavailable=false`** |
| Same, silent source present | Reaches the silent source, -100 dB | Reaches the silent source, -100 dB |
| Real microphone turned off mid-call with `livecd-mic off` | Not run | -100 dB within two seconds |

Evidence: stock (`temp/docs/evidence/mic/serein-scenes-stock-cpal.txt`), patched (`temp/docs/evidence/mic/serein-scenes-patched-cpal.txt`),
real microphone (`temp/docs/evidence/mic/real-mic.txt`).

The cause was narrowed in steps. The stall is at `play()`, which waits for the first bytes
(stages (`temp/docs/evidence/mic/record-stages.txt`)). Format differences do not cause it
(matrix (`temp/docs/evidence/mic/record-format-matrix.txt`)). It follows queue size, and widening `max_length` 8×
removes it without changing the source (sizes (`temp/docs/evidence/mic/record-queue-sizes.txt`)).

## Limits

- **Sound through the air is not proven under control.** The phone was in silent mode with media
  volume 0, so speaker tones were inaudible, and the volume was not changed. Vibration pulses fired
  but made no measurable difference, on this path or on Termux:API's recorder
  (run (`temp/docs/evidence/mic/vibration-inconclusive.txt`)). The signal looks live: a varying floor near -60 dB,
  never digital zero, with uncontrolled peaks up to 23441 of 32767. Termux:API's separate recorder
  found a similar floor (run (`temp/docs/evidence/mic/termux-api-recorder.txt`)). The user chose to rely on Termux:API's
  documented support and to verify detection instead.
- **Speech level and quality are unmeasured.** `VOICE_RECOGNITION` may capture quietly, and
  Samsung's processing of that preset was not examined.
- **Full Serein is untested.** Neither the GUI, its sign-in nor a Discord call was run, and its echo
  cancellation and denoising were not exercised on the real microphone.
- **No in-use indicator was seen.** Android 11 has none, and no microphone icon was visible in the
  desktop's panel during recording, though the Shell's indicator was not investigated further.
- **A level meter keeps the microphone open**, as `pavucontrol`'s Input Devices tab did.
- Screen-off capture, reboot, Bluetooth or USB microphones, long sessions and other Android versions
  were not tested. The Debian/PRoot backend does not have the silent source.
