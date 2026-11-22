# mpv audio timing on the Note10+

On 2026-11-21, native mpv on the Snapdragon Note10+ dropped video frames when
playing through the desktop's PulseAudio OpenSL ES sink. Direct Android AAudio
output eliminated the drops in the tested H.264 and HEVC clips. AAudio is the
temporary mpv default and has been applied to the device. The goal is to repair
the PulseAudio path and restore it as mpv's default.

As of 2026-11-22, the timestamped PulseAudio AAudio sink revision 103 has passed
private synthetic playback, desktop stream controls, three suspend/resume cycles,
30 module reloads and clean server exit. It also repairs a debugger-confirmed
Android close/callback deadlock discovered during qualification. Real 4K private
software-rendering tests still have occasional output drops, including the
direct-AAudio control. The candidate has **not** replaced the installed package
or the desktop server; `ao=aaudio,pulse` remains on the device. Physical A/V,
desktop hardware rendering and Android disconnect/route recovery remain open.

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

The Video Player overlay's default `mpv.conf` now prefers `ao=aaudio,pulse`. The running
device's `~/.config/livecd-native/mpv/mpv.conf` has the same preference, effective on
the next player launch. Rendering and decoding settings are unchanged. The
previous device file is saved as `~/mpv-pacing/mpv.conf.before-aaudio`.
The second output in the preference list allows PulseAudio to initialize when
AAudio is unavailable; this fallback retains the timing issue on this device.

The overlay uses `home-defaults`, so changing the repository default does not
migrate an existing user's configuration. This device was updated explicitly.
Revert `ao=aaudio,pulse` to `ao=pulse` on the device and in the overlay after the
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

## Source and runtime findings

The failure is in the playback clock exposed by the OpenSL ES sink and consumed
by mpv's default PulseAudio timing calculation. A private Xvfb display and a
synthetic 640x360, 24 fps MPEG-4/AAC fixture reproduce it with software decoding
and `vo=x11`. This removes SMB, the original MKVs, hardware decode, and the GPU
renderer from the reproduction.

| Controlled synthetic test | Result |
| --- | --- |
| Desktop PulseAudio OpenSL ES sink, normal mpv timing | 40 output drops in 22 seconds |
| Same sink, native PulseAudio timing | 21 drops in the short synthetic run; not a complete repair |
| Private PulseAudio server with AAudio sink, normal mpv timing | 0 drops in 22 seconds |
| Same private AAudio sink, native timing | 0 drops in 22 seconds |

A temporary preload probe observed libpulse timing calls without changing their
return values. In the steady interval from 3 to 19 seconds, the OpenSL ES case
had 113 inferred audio-clock forward discontinuities larger than one 24 fps
frame, with a largest step error of about 116 ms. The private PulseAudio AAudio
case had none. Its video-drop control stayed at zero. The probe increases
sampling overhead, but the uninstrumented and lightweight Lua measurements also
reproduce the original failure.

The source chain is specific:

1. Termux's `module-sles-sink.c` defaults to a 125 ms render block. It hands each
   rendered block to OpenSL ES and replenishes it in a buffer-completion callback.
   Its latency handler substitutes the configured fixed latency for actual
   playback latency; it does not track the hardware playback position.
2. The module creates its sink with flags zero, omitting `PA_SINK_LATENCY`.
   PulseAudio 17's `pa_sink_get_latency_within_thread()` consequently returns zero
   before calling that latency handler. The configured 125 ms fixed latency
   influences buffer negotiation but is not an actual remaining-hardware-buffer
   measurement in the client timing reply.
3. The native protocol sends the stream's read/write positions and remaining
   PulseAudio render-queue delay. The trace shows read-position increments of
   about 125 and 40 ms, while the reported sink delay moves between about 0.23 and
   121 ms as software queues are filled and handed off. Audio already queued in
   OpenSL ES is not accounted for by a live hardware-position measurement.
4. mpv 0.41's `get_delay_hackfixed()` synchronously requests this raw timing and
   calculates queued delay from write minus read position, transport delay and
   sink delay. The resulting inferred played position jumps as those queues
   transfer. The default audio-master video scheduler then drops frames to catch
   up to that clock. A 125 ms block spans three 24 fps frames.
5. `pulse-latency-hacks=no` instead enables libpulse's interpolated, automatically
   updated timing and calls `pa_stream_get_latency()`. It masks much of the
   discontinuity in the real-file tests, but the synthetic run still dropped
   frames, so it is not accepted as the complete repair.

Termux's PulseAudio AAudio sink uses shorter callbacks; its normal client timing
had no frame-sized clock discontinuities in the controlled test. However, it
also creates a sink without `PA_SINK_LATENCY`, and estimates its fixed latency
from the AAudio buffer size. Replacing the backend alone therefore does not
establish accurate hardware latency or physical lip sync. Direct mpv AAudio
uses `AAudioStream_getTimestamp()` and frame counters in its output callback;
that is a different implementation from the PulseAudio AAudio module.

A private second OpenSL ES sink could not initialize: `slCreateEngine` returned
OpenSL ES error 12 while the desktop's existing sink remained active. The player
then ran without audio and returned an error. Its zero-drop count is invalid as
an audio comparison and is excluded. Smaller OpenSL ES block sizes remain to be
tested during an explicitly controlled audio-server restart.

Host evidence is in `temp/mpv-audio-rootcause/`: source snapshots, the timing
preload source, `timing-summary.json`, trace CSVs and synthetic probe scripts.
Phone evidence is in `~/mpv-audio-rootcause/`. Generated capture bytes came only
from the private server's synthetic playback monitor, never a microphone.

## PulseAudio and direct AAudio tradeoffs

| Capability | mpv directly using AAudio | mpv using PulseAudio |
| --- | --- | --- |
| Linux application compatibility | Requires an application with a native AAudio backend, such as this mpv build | Ordinary PulseAudio clients work through the Android sink |
| Per-app desktop volume and mute | mpv and Android controls apply; there is no PulseAudio playback stream to control | PulseAudio stream volume/mute remain available |
| Desktop monitor recording | Direct stream is absent from PulseAudio sink monitors | Playback can be captured from the selected sink monitor |
| Stream routing and server effects | Bypasses PulseAudio routing and processing | Server can route/process the playback stream |
| Multiple clients | Android mixes the native streams | PulseAudio mixes Linux clients, then Android receives the sink output |
| Playback timing on this Note10+ | No drops in the two real clips tested | OpenSL ES path drops; private AAudio sink passed the synthetic comparison |
| Bluetooth and calls | Android policy and mpv's stream-reload handling apply; route changes need device testing | Desktop integration can manage PulseAudio streams, but Android backend and route changes still need testing |
| Power and end-to-end latency | Not measured | Not measured; the extra server is not by itself a measured latency or power penalty |

The private PulseAudio AAudio server retained the important desktop services.
A synthetic monitor test measured RMS about 2894 at full volume, 361 at 50 percent
PulseAudio volume, and zero when the playback stream was muted. Two concurrent
mpv clients appeared as separate sink inputs. Both exited successfully.
Pause/resume and an absolute seek to 30 seconds succeeded; the player advanced
to about 32.96 seconds after the seek. These are private-server integration
checks, not validation of GNOME's UI, microphone coexistence or Bluetooth.

PulseAudio is still the intended compatibility layer. The desktop's server,
microphone bridge and other applications keep using it while mpv temporarily
bypasses it. Restoring `ao=pulse` does not require restoring OpenSL ES as the
server's Android backend: an accurately implemented AAudio sink can preserve the
same Linux client protocol and desktop controls.

## Timestamped sink candidate built on 2026-11-22

The `packages/pulseaudio` recipe on main now contains the opt-in sink repair,
PulseAudio `17.0-103`, carrying Termux's pinned PulseAudio 17 build patches and
Android modules. Development history is on branch
[fix/pulse-aaudio-timestamps](https://github.com/cnshing/debian-livecd-termux/tree/fix/pulse-aaudio-timestamps).
The recipe and desktop launcher still select OpenSL ES by default; adding this
recipe does not switch the desktop backend. Its AAudio sink
now advertises `PA_SINK_LATENCY` and calculates remaining output frames using
`AAudioStream_getTimestamp(CLOCK_MONOTONIC)`, extrapolated to the query time.
It includes the callback being rendered before Android increments its written
frame counter. Stream reopen resets that accounting. While hardware timestamps
are unavailable during startup, a logged consumed-frame estimate is used.

The arithmetic regression covers ordinary queue delay, timestamp extrapolation,
the pending-callback handoff, future presentation timestamps, empty or exhausted
queues and 44.1 kHz output. It passes with undefined-behavior checks enabled.
The existing packaging and network-discovery tests also pass.

[CI run 45002726568](https://github.com/cnshing/debian-livecd-termux/actions/runs/45002726568)
built both `pulseaudio_17.0-100_aarch64.deb` and its GLib companion successfully.
The built module imports the timestamp, written-frame and read-frame APIs.
The package is a separate behavior-only build job, so client applications do
not need to rebuild against it.

The candidate has not been installed or selected by the desktop. Tests use the
candidate server and its matching modules and libraries together: the stock
package reports `17.0-dirty`, while the release-archive candidate reports `17.0`,
and PulseAudio checks module versions.

### Device qualification on 2026-11-22

The initial revision 100 ran on its own server and private Xvfb display. It
reported `PA_SINK_LATENCY`, activated Android hardware presentation timestamps
at startup and after suspend/resume, and reported about 234 ms of remaining
playback latency in one running sample (configured buffer latency about 20 ms).
Those are different quantities; the earlier fixed buffer estimate did not
measure the hardware presentation delay.

The synthetic playback test measured RMS 2883 at full stream volume, 361 at
50 percent and zero when muted. Concurrent clients, pause/resume, seek and
active sink suspend/resume succeeded. Four output drops occurred around the
intentional state changes; the interval from 40 to 123 seconds had no additional
output drops and no decoder drops. These counters do not measure physical lip
sync or screen presentation.

A separate 90-second 1080p H.264 SMB run with revision 100 completed with zero
output or decoder drops and no cache pauses, using `ao=pulse`, hardware decode
and a private `vo=x11` display. The last mpv A/V estimate was about 11 ms; this
is an internal estimate, not a physical alignment measurement.

The overall synthetic test **failed** when unloading the idle module: a following load
request timed out, and the private server required forced cleanup. The upstream
module closes AAudio from its sink IO thread, while Android's callback waits
synchronously for that same thread to render. `AAudioStream_close()` can join
that callback, creating a circular wait. A passing short playback run had
missed this lifecycle defect.

Revision 101 moved close to main after detaching the handle through an IO
message. That avoids blocking rendering, but qualification still found an
intermittent Android close deadlock. A repeat passed suspend/resume and all
three reloads, then hung during graceful server shutdown. A debugger attached
to this private process found:

- Main: `AAudioStream_close -> safeReleaseClose -> AudioStreamTrack::close_l ->
  AudioTrack::~AudioTrack -> Thread::requestExitAndWait`.
- AudioTrack callback: `processCallbackCommon -> systemStopFromCallback ->
  mutex::lock`.
- The PulseAudio sink IO thread was idle in `pa_rtpoll_run`, so this second hang
  was inside Android's close-versus-callback state transition, rather than an
  unserviced PulseAudio render message.

Revision 103 explicitly requests stop while rendering remains available and
waits for the STOPPING state to complete. It then detaches the handle through
IO before main closes it. A late callback fills silence and returns CONTINUE,
leaving the state transition to the explicit stop/close owner. It cannot query
a detached stream or initiate a competing STOP transition. Revision 102 only
added tracing to the unsuccessful revision 101 and is not a rollout candidate.

[CI run 45005563174](https://github.com/cnshing/debian-livecd-termux/actions/runs/45005563174)
built revision 103 from `14b94b6`. The main package SHA-256 is
`0560b0cfb744a8b53964f4c10c90b7df69eb60c4a357c932d27d18f6692c041d`.
Runtime qualification includes clean server exit as well as suspend/resume and
repeated module reloads; shorter playback checks missed these failures.

The first uninstrumented revision 103 run passed: stream volume/mute and monitor
capture, two concurrent clients, pause/resume, seek, active suspend/resume,
three module unload/reload cycles and a normal server exit (status 0). Hardware
timestamps activated initially and after reopen. Three output drops occurred
around deliberate state changes; the final 59-second window had zero additional
output drops, with no decoder drops or cache pauses. The final mpv A/V estimate
was about 1.3 ms. Running sink-latency samples ranged from about 68 to 236 ms;
median about 226 ms. This remains an internal timing check.

A second uninstrumented revision 103 run passed three active suspend/resume
cycles, 30 module unload/reload cycles and normal server exit. Hardware
timestamps activated four times. It recorded ten output drops around intentional
state changes and zero additional drops in the final 54-second steady window;
no decoder drops. Volume/mute and concurrent-client checks passed again. The
final mpv A/V estimate was about 0.45 ms. These repeated lifecycle checks support
the stop/detach/close repair on this device, without establishing Android route
or call handling on other devices.

A traced 90-second 4K HEVC SMB run on revision 103 did **not** pass the
zero-drop acceptance criterion: three output drops, all after 40 seconds,
zero decoder drops and no cache pauses. It used `mediacodec-copy` and private
`vo=x11` software scaling. Over 12,376 raw timing samples after the first five
seconds, no forward or backward audio-clock step error exceeded one 24 fps
frame; maximum absolute step error was about 34.8 ms and the 99th percentile
about 12.0 ms. This differs markedly from the original OpenSL ES trace but is
not proof that every remaining video drop is fixed. An untraced repeat also
recorded three output drops in 90 seconds, with zero decoder drops and no cache
pauses. Tracing overhead alone therefore does not explain this remaining issue.
Direct-AAudio and native/interpolated PulseAudio-timing controls on the same
private renderer are the next comparison.

A 90-second direct-AAudio control on the same private `vo=x11` display also
recorded one output drop (zero decoder drops, no cache pauses). Thus this
private 4K rendering setup has occasional drops independently of PulseAudio.
The repaired PulseAudio run's three drops versus this control's one drop do not
establish equivalence, and both fail the strict zero-drop criterion. Keep the
real desktop's hardware-rendering comparison in the remaining acceptance work.

An untraced 90-second 1080p H.264 SMB repeat on revision 103 passed with zero
output or decoder drops and no cache pauses; the final mpv A/V estimate was
about 2.5 ms. This repeats the revision 100 result with the shutdown repair.

A 90-second revision 103 HEVC repeat with `pulse-latency-hacks=no` also recorded
three total output drops (two in its measured steady window), zero decoder drops
and no cache pauses. Its final mpv A/V estimate was about 0.03 ms. Interpolated
PulseAudio timing therefore does not by itself satisfy the remaining 4K
zero-drop criterion in this setup. Do not change the managed mpv timing option
or restore `ao=pulse` based on these results alone.

The device still has the stock `pulseaudio 17.0-5`, executable managed mpv
launcher and `ao=aaudio,pulse` preference. All candidate runs used extracted
packages and private processes. No desktop/audio-server restart was performed.
Host evidence, the debugger backtrace and real-media probe scripts are ignored
under `temp/pulse-timestamps/`; phone logs are under `~/pulse-timestamps/`.
The latest extracted package is retained in `~/pulse-timestamps/stage103/` for
follow-up qualification. Private media names and addresses remain untracked.

The reusable `tests/audio/test-aaudio-device.py` covers measured sink latency,
hardware timestamp activation, playback stability, volume/mute, private monitor
capture, two clients, pause/resume, seeking, suspend/resume and repeated module
unload/reload. Real-file playback, physical A/V alignment, GNOME controls,
microphone coexistence, Bluetooth routes and call interruptions remain separate
acceptance checks. Review the inherited `error_callback()` before route tests:
it calls `pa_sink_suspend()` directly from Android's error callback thread
instead of posting recovery to the PulseAudio main loop. The successful stop
and reload tests do not exercise this disconnect-recovery path. All captured audio in these tests comes from a generated
private tone, never a microphone or the live desktop monitor.

## Repair and acceptance plan

1. Prefer fixing Android sink latency reporting, using played-frame position and
   monotonic timestamps to account for queued but unheard audio. Advertise
   `PA_SINK_LATENCY` only after the module implements that contract. Adding the
   flag with an always-125-ms answer is insufficient: remaining latency must
   decrease while the device plays. Evaluate both repairing OpenSL ES and giving
   the existing PulseAudio AAudio sink accurate timestamp-based accounting.
2. During a controlled desktop-audio restart, compare smaller OpenSL ES blocks
   with the 125 ms negative control. Check underruns, scheduling overhead and
   actual audio continuity; a smaller block may hide clock quantization without
   correcting the latency contract.
3. Validate the candidate with `ao=pulse` and normal mpv timing for both real
   codecs, local storage and SMB, startup, pause/resume, seeking and long runs.
   Retain a failing OpenSL ES control and a direct AAudio control. Check clock
   continuity as well as output-drop counters. Measure physical A/V offset with
   a synthetic flash/click fixture and a suitable loopback/capture setup; mpv's
   reported A/V difference alone cannot establish physical lip sync.
4. Repeat desktop stream volume/mute, monitor capture and concurrent-client
   checks, then qualify GNOME controls, microphone coexistence, Bluetooth route
   changes, reconnects and call interruptions. Use synthetic sources for capture.
5. Restore `ao=pulse` on the device and in the overlay when the repaired backend
   passes those checks. Keep AAudio explicit as a fallback until other supported
   devices and Android versions are qualified.

Primary references: [mpv 0.41 PulseAudio output](https://github.com/mpv-player/mpv/blob/v0.41.0/audio/out/ao_pulse.c),
[mpv 0.41 direct AAudio output](https://github.com/mpv-player/mpv/blob/v0.41.0/audio/out/ao_aaudio.c),
[Termux OpenSL ES sink](https://github.com/termux/termux-packages/blob/master/packages/pulseaudio/module-sles-sink.c),
[Termux AAudio sink](https://github.com/termux/termux-packages/blob/master/packages/pulseaudio/module-aaudio-sink.c),
[PulseAudio 17 sink latency implementation](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/pulsecore/sink.c),
[PulseAudio 17 native timing replies](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/pulsecore/protocol-native.c),
and [Android AAudio](https://developer.android.com/ndk/guides/audio/aaudio/aaudio).
