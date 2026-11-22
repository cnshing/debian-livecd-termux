# mpv audio timing on the Note10+

On 2026-11-21, native mpv on the Snapdragon Note10+ dropped video frames when
playing through the desktop's PulseAudio OpenSL ES sink. Direct Android AAudio
output eliminated the drops in the tested H.264 and HEVC clips. AAudio is the
temporary mpv default and has been applied to the device. The goal is to repair
the PulseAudio path and restore it as mpv's default.

## Reproduction and measurements

The device runs Android 11, `mpv-x 0.41.0-7`, `pulseaudio 17.0-5` and
`ffmpeg 9.0.2-102`, with the native Zink desktop and mpv's Vulkan `gpu-next`
renderer. Hardware decoding was `mediacodec-copy`. The display reports about
59.96 Hz. Tests used real SMB MKVs and local segments remuxed without re-encoding.

| Playback case | Output drops | Decoder drops |
| --- | --- | --- |
| 1080p H.264, 23.976 fps, normal PulseAudio | 70 in 35 seconds | 0 |
| Same segment, AAudio | 0 in 30 seconds | 0 |
| 4K HEVC, 24 fps, normal PulseAudio | 72 in 30 seconds | 0 |
| Same HEVC segment, AAudio | 0 in 30 seconds | 0 |
| H.264 with audio disabled | 0 in 35 seconds | 0 |
| H.264 with null audio output | 0 in 35 seconds | 0 |
| H.264 over SMB, PulseAudio with `pulse-latency-hacks=no` | 7 near startup; none after 15 seconds through the 50-second run | 0 |

A separate 45-second comparison reported 78 output drops over SMB and 83 from
its local segment. Neither run paused for cache. SMB retained over 100 seconds
of buffered media. The H.264 packet timestamps advance regularly by 41 or 42 ms,
consistent with its 23.976 fps rate. Disabling hardware decoding, simplifying GPU
scaling, and using `vo=x11` did not remove the drops. `video-sync=display-resample`
made timing worse on this display path, so it is not the workaround.

The first probe polled IPC properties each second. A subsequent in-process Lua
timer with fewer properties reproduced the drops and the AAudio/null/no-audio
controls. The finding therefore survives the instrumentation change. Counts are
mpv's output-drop counters; they are not an external measurement of physical
screen presentation. Ordinary 24 fps on a 60 Hz display can still show cadence
judder after the extra drops are eliminated.

Raw logs, scripts, timestamps and summaries are ignored local evidence in
`temp/mpv-pacing/` on the host and `~/mpv-pacing/` on the phone. Private media
names, server addresses and credentials must stay out of tracked reports.

## Temporary change and rollback

The Video Player overlay's default `mpv.conf` now selects `ao=aaudio`. The running
device's `~/.config/livecd-native/mpv/mpv.conf` has the same change, effective on
the next player launch. Rendering and decoding settings are unchanged. The
previous device file is saved as `~/mpv-pacing/mpv.conf.before-aaudio`.

The overlay uses `home-defaults`, so changing the repository default does not
migrate an existing user's configuration. This device was updated explicitly.
Revert `ao=aaudio` to `ao=pulse` on the device and in the overlay after the
acceptance checks below pass. Do not remove the desktop's PulseAudio server.

## Why PulseAudio exists and what AAudio bypasses

The desktop starts a private PulseAudio server with `module-sles-sink` and a
Unix protocol socket in `src/native/desktop.py`. This gives ordinary Linux audio
clients an API they already support and forwards their mixed output to Android.
It also supplies desktop stream controls, sink routing, monitor sources, and the
project's microphone and Bluetooth integration. Linux clients do not need direct
access to Android audio APIs or ALSA devices.

mpv is unusual here because its native Android build also supports AAudio.
`ao=aaudio` sends this application's output directly to Android instead of
creating a PulseAudio playback stream. mpv's own volume and Android's output
policy remain relevant, but PulseAudio per-stream controls, effects, routing and
sink-monitor capture do not govern or see that direct stream. In particular,
recording the desktop PulseAudio monitor will omit mpv's direct AAudio output.
Bluetooth route changes, call interactions, and reconnect behavior require
separate runtime checks; a short playback pass does not establish those cases.
Neither output choice alone establishes lower end-to-end latency or lower power
use: those require measurements.

AAudio can also serve as the *backend of PulseAudio*. A working
`mpv -> PulseAudio -> module-aaudio-sink -> Android` path could retain desktop
integration while replacing only the Android sink. It must be compared with
fixing OpenSL ES timing and with mpv's native PulseAudio timing option.

## Investigation status and next steps

The experiments isolate the problem to the audio timing path used by normal
PulseAudio playback. They do not yet prove a particular server or client source
line is defective. `pulse-latency-hacks=no` is a strong clue: it changes mpv's
latency calculation while retaining PulseAudio, OpenSL ES, decoding and rendering.

1. Trace mpv's `ao_pulse.c` timing calculations and Termux's OpenSL ES sink latency
   reporting. Record stream read/write indices, sink latency, underrun state and
   reported playback delay against monotonic time. Identify discontinuities that
   correlate with output drops.
2. Compare default and native PulseAudio timing on the same clip. Test the
   PulseAudio AAudio sink on a private server/socket without restarting or
   replacing the user's desktop audio server.
3. Validate any candidate repair with both codecs over local storage and SMB,
   including startup, pause/resume, seeking and longer playback. Use the same
   audio route and retain a default PulseAudio negative control.
4. Verify desktop per-stream volume/mute, monitor capture, multiple clients,
   microphone coexistence and Bluetooth route/reconnect behavior. Keep recording
   fixtures synthetic and avoid capturing the user.
5. Restore `ao=pulse` only when the repaired path holds stable A/V sync and has no
   continuing drops after startup, with desktop integration checks passing.

Primary references: [mpv PulseAudio output implementation](https://github.com/mpv-player/mpv/blob/v0.41.0/audio/out/ao_pulse.c),
[mpv audio output options](https://mpv.io/manual/stable/#audio-output-drivers),
[Termux PulseAudio recipe](https://github.com/termux/termux-packages/tree/master/packages/pulseaudio),
and [Android AAudio](https://developer.android.com/ndk/guides/audio/aaudio/aaudio).
