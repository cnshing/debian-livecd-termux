# Handoff: Chrome text input loses or rewinds the last character (Note10+)

State on 2026-11-18. User report, not yet reproduced. Shared rules and pass criteria:
[README.md](README.md).

## Symptom

On the Note10+ (Adreno 640), typing into an input box in Chrome (seen on chatgpt.com):
sometimes the character just typed

- is not drawn,
- is drawn and then disappears, or
- the blinking caret jumps back one position.

User answers (2026-11-18): Termux:X11 under Samsung DeX, 1920x1080 external display. It is
random, regardless of typing speed. Other sites and browsers are untested. Sometimes the
character leaves an **empty space**, as if it were still there but not drawn. That points at the
picture (cause 1), not at lost input: the text layout already holds the character.

## Candidate causes

1. **Stale presentation (picture only).** Chrome draws with ANGLE on Turnip/KGSL
   (`--use-gl=angle --use-angle=vulkan`, `src/native/acceleration.py`). If a presented frame
   is shown before rendering into it finishes, or a previous buffer is re-shown, the screen
   lags one frame behind: the newest glyph is missing until the next caret blink redraws the
   area, and the caret looks like it moves backwards. Partial redraws (damage rectangles)
   make this visible only around the caret. This may share a cause with
   [note10-gpu-rectangles.md](note10-gpu-rectangles.md).
2. **Input lost or reordered (text wrong).** X11 key events from Termux:X11 dropped, repeated,
   or delivered out of order, or an input-method (IBus/XIM) round trip racing with
   the page's JavaScript editor. chatgpt.com uses a contenteditable editor (ProseMirror) that
   rewrites the DOM on each key, so a late composition event can undo the last character.

## Next steps

1. Reproduce on a private display (never `:0`): drive `xdotool type` into a plain
   `<textarea>` test page and into a contenteditable page, then compare
   `document.activeElement.value`/`textContent` with what was typed. Wrong text → cause 2.
2. If the text is right, record the display with `x11grab` and step through frames around each
   key press. Then retry with `--disable-gpu-compositing`, with `--use-angle=gl`, and with
   `--disable-features=Vulkan`; a symptom that goes away points at the GPU present path.
3. Compare with Chromium (same flags, Bionic Mesa) and Firefox on the same page, to split
   Chrome's glibc driver (`android-vaapi-glibc`) from the shared path.
4. For cause 2, check the IME: rerun with `GTK_IM_MODULE`/`XMODIFIERS` unset, and log key
   events with `xev` alongside the page's `keydown`/`input` events.

## What counts as fixed

Several hundred typed characters on both test pages and on chatgpt.com with no missing,
vanishing or rewound character in the recording, and a negative control (the failing
configuration) that still shows it.
