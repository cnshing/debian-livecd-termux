# Fullscreen playback crash investigation

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

> **Update:** this is now Mutter patch 0010 in the source port, and a tool installs it into an
> existing runtime. The crash also reproduces on Termux:X11's server with GPU rendering. See
> [GPU rendering and hardware video](native-gpu-and-video.md#results).

Investigated on the connected Note10+ (SM-N975U1), Android 11,
using the installed source-built GNOME Shell/Mutter 48.8 runtime. The crash is
reproducible without a video decoder: an animated HTML canvas can trigger it.

**The confirmed failure is an out-of-bounds window-pixmap read in Cogl's X11
compositor fallback.** The original library also crashes on a playing YouTube
video. A private library with damage clipped to the pixmap bounds survives the
same transitions. The installed runtime and launchers have not been changed.

## Evidence

The diagnostic wrapper logs the drawable's actual geometry immediately before
calling the original `XShmGetImage`. On Chrome's first exit from canvas fullscreen:

```text
FULLSCREEN_INVALID_SHM_READ drawable=0x40001f pixmap=1280x688 depth=32 request=0,0 1280x720 depth=32 caller=.../libmutter-cogl-16.so+0x8a3a4
The error was 'BadMatch (invalid parameter attributes)'.
(Details: serial 3430 error_code 8 request_code 130 (MIT-SHM) minor_code 4)
```

The source drawable is 32 pixels shorter than the requested rectangle, with
matching depth. GNOME Shell exits with SIGABRT (`-6`). Xvfb and the browser remain
alive until the harness cleans them up. The older managed desktop log contains
three errors with the same MIT-SHM request/minor code.

The original library fails on the first exit from fullscreen while playing
YouTube's **Big Buck Bunny**, with decoded frames advancing beforehand; see
YouTube baseline (`temp/docs/evidence/browsers/fullscreen/chrome-youtube-baseline/result.json`)
and its shell trace (`temp/docs/evidence/browsers/fullscreen/chrome-youtube-baseline/shell.log`).
This supplies a direct reproduction of the reported browser/video symptom.

[`XShmGetImage`](https://xorg.freedesktop.org/archive/X11R7.5/doc/Xext/mit-shm.html)
reads pixels from an X drawable. This is the compositor copying window pixels,
after the browser has decoded its content.

## Cause and candidate correction

In Mutter 48.8's `cogl/cogl/winsys/cogl-texture-pixmap-x11.c`,
`cogl_texture_pixmap_x11_update_area()` unions incoming damage into
`tex_pixmap->damage_rect`. `_cogl_texture_pixmap_x11_update_image_texture()`
passes that rectangle to `XShmGetImage` without intersecting it with the texture's
fixed pixmap dimensions. Fullscreen transitions can leave damage describing a
larger area than the current pixmap. The trace confirms this size mismatch;
the precise ordering of the contributing XDamage/Configure events was not traced.

The [candidate patch](../../packages/livecd-mutter/0010-clip-pixmap-damage.patch) intersects accumulated
damage with `(0, 0, texture_width, texture_height)` before any fallback read or
upload. Empty intersections clear the pending damage and return. It addresses
the read bounds rather than suppressing X errors.

Only a copy of that source file was patched. It was compiled with the existing
build's recorded compiler arguments, then relinked with the other existing
objects into `~/.cache/livecd-fullscreen-investigation/candidate-lib/`.
The build receipt (`temp/docs/evidence/browsers/fullscreen/build-candidate.json`) records
the compiler/linker commands and hashes. An unmodified relink's `.text` hash
matches the installed library's `.text` hash:

```text
99cf234cb00215a3ddfb249fc2a87bb4966c7d29bbf883ef6c5dccdd3a17c82d
```

The installed library's complete SHA-256 remained:

```text
ea7e7e38db93e81aa9c0d32af884319f8268515d747c956be0b5f04c8717540b
```

## Results

Each cycle enters and leaves DOM fullscreen, with one second in each state.
The shell uses Zink/Turnip 26.2.6. Chrome is 156.0.8078.79; Chromium is
156.0.8078.47. Chrome's normal launcher already passes `--disable-gpu`.

| Browser and library | Case | Result |
| --- | --- | --- |
| Chrome, original | Animated canvas | SIGABRT on first fullscreen exit |
| Chrome, original, MIT-SHM disabled on Xvfb | Animated canvas | SIGSEGV on first fullscreen exit |
| Chrome, original | YouTube playback | SIGABRT on first fullscreen exit |
| Chromium, original, default GPU flags | Animated canvas | Survived 3 cycles; a limited control |
| Chromium, original, `--disable-gpu` | Animated canvas | Same MIT-SHM SIGABRT on third exit |
| Chrome, candidate | Canvas, AV1, H.264, VP9, YouTube | All 5 cases passed 6 cycles each; 60 transitions |
| Chromium, candidate, `--disable-gpu` | Canvas, AV1, H.264, VP9, YouTube | All 5 cases passed 6 cycles each; 60 transitions |
| Chrome, candidate, MIT-SHM disabled on Xvfb | Animated canvas | Survived 3 cycles |

The Chrome candidate result (`temp/docs/evidence/browsers/fullscreen/chrome-patched/result.json`)
records fullscreen state, frame counts, media events and the loaded Cogl/Turnip
paths. The shell was alive before cleanup and no invalid SHM read was logged.
The local clips were 640×360 at 24 fps; YouTube selected 854×480. Media telemetry
reported software decoders: `Dav1dVideoDecoder` for AV1 and YouTube,
`FFmpegVideoDecoder` for H.264, and `VpxVideoDecoder` for VP9. Frames advanced
through repeated transitions. Some frames were dropped; these are crash tests,
not playback performance measurements.

The compositor screenshot after the YouTube cycles (`temp/docs/evidence/browsers/fullscreen/chrome-patched/youtube-shell.png`)
also confirms that GNOME painted the restored browser window.
The Chromium candidate result (`temp/docs/evidence/browsers/fullscreen/chromium-patched/result.json`)
records another 60 successful transitions, including the same software decoder
names, with only the candidate Cogl mapped into the shell.
The non-SHM candidate control (`temp/docs/evidence/browsers/fullscreen/chrome-patched-no-shm/result.json`)
also survived, covering the alternate XImage path that crashed without the patch.

## Repeat safely

Run from an ordinary native Termux shell, **without `livecd-native exec`**:

```sh
python tests/browsers/test-fullscreen.py chrome --cycles 6
python tests/browsers/test-fullscreen.py chromium --browser-flag=--disable-gpu --cycles 6
python tests/browsers/test-fullscreen.py chrome --case youtube --cycles 6 \
  --youtube 'https://www.youtube.com/watch?v=aqz-KE-bpKQ'
```

The harness allocates a free Xvfb display from `:71` through `:99` at 1280×720,
uses private D-Bus, runtime/settings/data/cache directories and browser profiles,
and starts GNOME Shell directly. User extensions and the managed desktop
controller are absent. `--renderer software` selects the compositor's software
profile; it does not select the browser's decoder. `--disable-shm` disables
MIT-SHM on this private X server, and was **not** a successful workaround.

`--media-dir DIR` adds each `.mp4`/`.webm` file in a directory. The fixture
commands used on the PC were:

```sh
mkdir -p /tmp/livecd-fullscreen-fixtures
ffmpeg -f lavfi -i testsrc2=size=640x360:rate=24 -t 6 -an \
  -c:v libx264 -preset veryfast -pix_fmt yuv420p /tmp/livecd-fullscreen-fixtures/h264.mp4
ffmpeg -f lavfi -i testsrc2=size=640x360:rate=24 -t 6 -an \
  -c:v libvpx-vp9 -deadline realtime -cpu-used 8 -b:v 600k /tmp/livecd-fullscreen-fixtures/vp9.webm
ffmpeg -f lavfi -i testsrc2=size=640x360:rate=24 -t 6 -an \
  -c:v libaom-av1 -cpu-used 8 -crf 38 -row-mt 1 /tmp/livecd-fullscreen-fixtures/av1.webm
```

The trace library builds in Termux with:

```sh
cc -shared -fPIC tests/browsers/fullscreen-xshm-trace.c \
  -o "$TMPDIR/fullscreen-xshm-trace.so" -lX11 -ldl
python tests/browsers/test-fullscreen.py chrome \
  --shell-preload "$TMPDIR/fullscreen-xshm-trace.so"
```

For the candidate run, `--shell-lib-dir` points at the private Cogl directory
and `--shell-preload` points at the diagnostic library. A private `Cogl-16.typelib`
was compiled from the installed GIR with its `shared-library` set to the candidate's
absolute path. The diagnostic library redirects Shell's compiled-in Mutter
introspection search path only when `LIVECD_FULLSCREEN_GI_DIR` is set by this
option. This prevents loading both the installed and candidate Cogl and registering
duplicate GTypes. Simply adding the candidate to `LD_LIBRARY_PATH` is insufficient.

## Scope

All reproductions used a separate Xvfb instance (`:71`); existing displays were
left alone. No browser's existing profile was opened, no desktop settings were
changed, and no installed libraries or source-port files were replaced.
The patch remains a reviewable candidate under `docs/browsers/`.
The final state check (`temp/docs/evidence/browsers/fullscreen/final-state.json`) found
no surviving test processes, no `:71` socket and the original installed-library
checksum.

This establishes a compositor crash that explains the observed symptom; it
does not establish that every playback failure has this cause. Termux:X11's
Android presentation path, user extensions, high-resolution playback and the
older prebuilt Mutter 48.1 runtime still need separate validation before a
production fix is claimed.
