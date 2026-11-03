# Native Mixtapes device verification

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

> Tested with a binary built on the phone by an earlier script, since removed. This repository's
> [recipe](../../packages/livecd-mixtapes/build.sh) uses the same source and patches, but it cross-compiles and
> has not been built yet. Paths here were updated.

Tested on the established rig: Galaxy Note10+ (SM-N975U1),
Android 11, kernel 4.14.190, arm64, on Wi-Fi. The native GNOME desktop ran throughout with the Zink
renderer. **This is one phone, signed out, for a few hours**: it does not establish long-term
reliability, or behaviour on other phones or Android versions, or with an account.

| Component | Version | Source |
| --- | --- | --- |
| Mixtapes | Commit `618c24c3` (archive SHA-256 `a09276af…c2d37f`) | Upstream, patched by this port |
| Rust, Cargo | 1.99.1 | Official Termux |
| GTK, libadwaita, WebKitGTK | 4.24.1, 1.10.0, 2.54.1 | Official Termux |
| GStreamer and plugins, gst-libav | 1.28.8, 1.28.8-1 | Official Termux |
| yt-dlp, yt-dlp-ejs, Node.js, FFmpeg | 2026.10.26, 0.8.0, 24.22.1, 9.0.2 | Official Termux |
| glibc, openssl-glibc | 2.44, 3.6.3 | Termux glibc repository |
| rustypipe-botguard | 0.1.2 | Upstream's arm64 glibc binary |

Dependency installs were simulated first and added packages only, with no upgrades or removals. The
tested binary's SHA-256 starts `70a01ff8c026fab0`, and the installed copy was compared with the build's.

## Results

**Upstream's unit tests pass on Bionic: 367 passed, 0 failed, 43 ignored**
(results (`temp/docs/evidence/mixtapes/unit-tests.txt`)). The 43 are ones upstream marks `#[ignore]`, mostly live-network tests
and those needing captured fixtures, so they did not run. They ran on a private X display with
`cargo test --release --locked`.

The rest ran through [`test-mixtapes.py`](../../tests/mixtapes/test-mixtapes.py) on that binary, in scratch directories, unless
noted. Device checks (`temp/docs/evidence/mixtapes/device-checks.txt`), real use (`temp/docs/evidence/mixtapes/real-use.txt`).

| Check | Result |
| --- | --- |
| Identity | Bionic: interpreter `/system/bin/linker64`, links Termux's GTK, libadwaita, WebKitGTK and GStreamer. No tracer on the process tree |
| Refuses an untrusted certificate | 54 connections through a fake interception server, to 9 hosts: all 54 handshakes refused, no request reached it. A control client that trusted the test CA did reach it, so the rig can see requests |
| Trusted certificates | Log shows `Loaded 118 CA root certificates from the system`, and real requests succeed |
| Stream resolving | Player endpoint, itag 251 (opus), in 350 ms and 220 ms |
| First audio | 2.1 s after clicking a search result. 6.9 s from first poll in the demo-harness run, which includes its own delay |
| Signal | Sink-monitor RMS 2985 playing, 0.0 paused. Measured before Android's volume |
| **Audible output** | **The user heard the test song from the phone's speaker** during these runs. This is an observation, not a measurement |
| Seek | A 60 s MPRIS seek moved the position from 8.5 s to 72.8 s, with signal afterwards. `curlhttpsrc` reports seekable |
| MPRIS | Status and metadata read back. PlayPause both ways, Seek and Quit work |
| GNOME Shell media controls | Show the album art, title, artist and buttons. Screenshot (`temp/docs/evidence/mixtapes/shell-media-controls.png`) |
| Download | 213.6 s opus file, title and artist tags present, one row in `library.db` |
| PO token | Minted on glibc in 1.5 s cold, 0.07–0.09 s from its snapshot. With a token, the `web_music` client returned format 251 and served the first 2 MiB. Without one, the same client found no format |
| Synced lyrics | 58 synced lines from Apple Music and BetterLyrics. The chevron and the Lyrics button work with real clicks on the desktop at 720 px. Desktop (`temp/docs/evidence/mixtapes/lyrics-desktop.png`), phone layout on a private display (`temp/docs/evidence/mixtapes/lyrics-phone-layout.png`), with word-by-word highlighting |
| Menu entry | Opens the app, with its icon in the dock, and the window carries the desktop's session tag |
| Real input | Clicked search, typed, pressed Return and clicked a result through X. Screenshot (`temp/docs/evidence/mixtapes/search.png`) |
| Background playback | Closed the window: the position kept moving, with RMS 3023 |
| Second launch | Reopened the window, with one running copy |
| Sign-in page | Google's page renders in WebKit. Screenshot (`temp/docs/evidence/mixtapes/sign-in.png`). **Nothing was typed into it** |
| Plain Termux shell | Stayed up for 14 s with a private bus. No audio route, and the icon theme is not found |

| Resource use, 60 s | CPU, % of one core | PSS |
| --- | ---: | ---: |
| Idle on Home | 0.1 | 148 MB |
| Playing, window visible | 15.6 (12.1 in an earlier run) | 179 MB (196 MB in that run) |

The app's process tree only: this leaves out PulseAudio and the compositor.

## The header fix, measured

The first working build reached the app and played, but its log showed `visitor data not warmed`.
TLS was fine: the frames show `REQUEST_HEADER_FIELDS_TOO_LARGE`, because `music.youtube.com` sends
17,321 bytes of headers against the HTTP client's 16 KB limit. The same size came back to a PC. Each
play then fell back to `yt-dlp`.

| | Before | After |
| --- | --- | --- |
| How streams resolved | `yt-dlp`, after the player endpoint declined | Player endpoint |
| First audio, same harness | 23.3 s | 6.9 s |

The harness starts one track that then switches to its audio twin, so it resolves twice. Before and after
are one run each.

## How it was tested

**Everything ran on the phone**, built there with Termux's own Rust. `cargo check` passed for the whole
tree in 5 min 12 s. The final build's own time isn't meaningful, because it was paused for hours over the
battery. See the battery notes in the [README](README.md#building-on-the-phone).

The last lyrics and real-use runs came after another session installed gvfs and restarted the desktop with
[its icon fixes](../native/README.md#icons). They used the same binary, with the same results. The other
checks were not repeated after that, by the user's decision that those changes were not significant.

**Mistakes in the test harness, kept here because they looked like app bugs:**

- Placeholder icons on the skip, Library and Lyrics buttons came from the test's own scratch
  `XDG_DATA_HOME`, which hid the desktop's theme. A bare GTK window reproduced them with no Mixtapes code,
  and they went away once the theme stayed visible. See [Icons](../native/README.md#icons).
- Clicks landed 25 px off on the real desktop, because `xdotool mousemove --window` counts from the X
  window, which includes GTK's invisible shadow margins (`X=-25 Y=225`, `_GTK_FRAME_EXTENTS` 25). That made
  the chevron and Lyrics button look broken there while they worked on a private display, which has no
  margins. It also lost the first letters of the typed search: the click missed the search button, so
  typing opened search itself. The tests now add the margins.
- MPRIS reports `Playing` while a track is loading, so the first playback check tested too early. It now
  waits for the position to move.
- `pgrep -x mixtapes` reported no process while the app was running, so counts now use `/proc/*/exe`.
  Earlier "no leftover processes" lines were not reliable and were re-measured.

## Open issues

**Search failed once.** During one real-input run, the app showed `Search failed: HTTP error: error sending
request for url (https://music.youtube.com/youtub…`. Its underlying error was not logged in that run. That
screenshot also shows a demo-only label, "resolved by yt-dlp", in a window whose process had no demo
variables, which I can't explain. That run also had the misplaced clicks described above. A later run with
full logging, and the following real-input runs, did not reproduce it. **The cause is unknown**: it may have been a passing network failure.

**No account.** Nothing was signed in, so these remain untested: signing in itself, library, likes,
uploaded songs, playlist editing, history and scrobbling. PO tokens were tested on a public song, not
an uploaded one.

**Also untested:** artist, album and playlist pages, Explore, Discord presence, the `mixtapes://` link
scheme, long sessions, and playback with the screen off or Termux:X11 in the background.
