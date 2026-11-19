# Handoff: Chrome text input loses or rewinds the last character (Note10+)

State on 2026-11-19. Root cause found and reproduced; fixed by `android-vaapi-glibc` 14 (CI run
44478328410), installed on the Note10+ with mesa 26.2.6-108 (validate 30/30) and verified there. Shared rules: [README.md](README.md).

## Symptom

On the Note10+ (Adreno 640, Termux:X11 under DeX), typing in Chrome: the character just typed
is sometimes not drawn, drawn then gone, leaves an empty space, or the caret seems to jump back.

## Cause: the screen shows the previous frame (picture, not input)

Chrome's Vulkan compositor presents through the glibc Turnip in `android-vaapi-glibc` (lfdevs'
Mesa). On KGSL that Turnip presents over DRI3 with shared buffers, and Mesa's X11 WSI skips the
fence wait in FIFO mode (`x11_needs_wait_for_fences`), relying on implicit sync. KGSL buffers have
none, so Termux:X11 reads the image before the GPU finishes it and shows the older contents until
the next present. Chromium's Bionic Turnip (Mesa 26.2.6) does not use DRI3 on KGSL and is clean.

## Evidence

`tests/browsers/test-typing.py` types real X11 keys (xdotool) on a private Termux:X11 display into a
`<textarea>` and a contenteditable that rewrites its DOM each key (as ProseMirror does). Each glyph is
a red `I`; after each key the X server's picture is grabbed and the bars counted, and the page text read.

| Chrome, installed `android-vaapi-glibc` 13 | wrong text | stale picture (textarea / editable) |
| --- | --- | --- |
| default, 240 keys per field | 0 | 161 / 47 (all caught up within 1.2 s) |
| invalid `MESA_VK_WSI_PRESENT_MODE` (control: Mesa warns) | 0 | 21 / 7 of 30 |
| `MESA_VK_WSI_DEBUG=sw` (CPU copy after the fence) | 0 | 0 / 0 |
| `MESA_VK_WSI_PRESENT_MODE=mailbox` (DRI3 + fence wait) | 0 | 0 / 0 |
| `--disable-gpu-compositing` or `--use-angle=gl` | 0 | 0 / 0 |
| `TU_DEBUG=syncdraw` / `flushall` | 0 | still stale (not GPU timing) |
| Chromium, default | 0 | 0 / 0 |
| **Chrome, revision 14 Turnip** (private ICD, same 240 keys and seed) | 0 | **0 / 0** |
| **Chrome, revision 14 installed**, stock launcher, same keys | 0 | **0 / 0** |

Gotcha: `graphics.apply_renderer` (via `desktop.environment`) strips `MESA_VK_WSI_*` and the launcher
overwrites `TU_DEBUG`; experiments must add them back after `acceleration.prepare` (a private copy of
the modules was used, passing `TYPING_ENV_*` through).

## Fix

`packages/android-vaapi-glibc/turnip/kgsl-x11-present-wait.patch`: wait for each image's fence
before every non-sw X11 present. Revision 14.

## Next steps

Performance, 2026-11-19 (private display, canvas animation plus 1080p VP9 video for 15 s, two runs
each): rev 13 and rev 14 both ran at the display's 30 fps cap, frame time p95 and max 33.5 ms, and
dropped 11-13 of about 260 video frames. No regression is visible, though the private display's
30 Hz cap hides any loss of headroom above it.
2. The same cause explained [note10-gpu-rectangles.md](note10-gpu-rectangles.md) (that lane: rev 14 0/900).
