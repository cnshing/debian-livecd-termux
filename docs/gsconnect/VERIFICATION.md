# Native GSConnect device verification

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

> Recorded before the repository restructure. Paths were updated, but build steps and
> install locations describe the earlier on-device flow.

Tested on the established rig: Galaxy Note10+
(SM-N975U1), Android 11, kernel 4.14.190, arm64, 5 GHz Wi-Fi. The Debian/PRoot GNOME desktop
stayed running throughout on the same Termux:X11 display, and `livecd status` still reported
it healthy afterwards.

| Component | Version | Source |
| --- | --- | --- |
| GSConnect | 62, Debian `62-1+deb13u1` (SHA-256 `628364c2…b235b9`) | Debian, patched by this port |
| CJS | 140.2 | Official Termux |
| SpiderMonkey | 140.17.0 | Official Termux |
| GLib, glib-networking (OpenSSL backend) | 2.90.1 | Official Termux |
| GTK 3 | 3.24.52 | Official Termux |
| Notifier | xfce4-notifyd 0.9.7-2 | Official Termux |

No package upgrade was needed; the dependency installs were checked with an APT simulation
first. **This is one phone on one network, tested for under an hour.** It does not establish
long-term reliability or behaviour on other phones or Android versions.

## Method

Two independent peers were used, both on a Debian PC on the same LAN:

- **[`test-peer.sh`](../../tests/gsconnect/test-peer.sh):** an unmodified Debian GSConnect 62 on GJS with GnuTLS, in
  a private bus and XDG directories. It shows that a real GSConnect interoperates.
- **[`test-protocol.py`](../../tests/gsconnect/test-protocol.py):** a scripted peer using Python's TLS. It asserts
  individual packets, sends deliberately invalid input, and avoids the PC's own X clipboard.

Unless noted, results below used the installed package and its controller, not the earlier
experiment. Screenshots are X-level captures of the phone's display.

## Results

**Packet-level checks:** 14 of 14 passed. Output (`temp/docs/evidence/gsconnect/protocol-checks.txt`)

- TLS 1.3 handshake through native OpenSSL, with protocol 8 identities exchanged inside TLS.
- An unpaired peer could not run a configured command.
- Pairing, battery level matching sysfs, Run Command through Termux's `sh`, clipboard in both
  directions, and remote pointer motion by the requested amount.
- A different certificate under an already-paired device ID was refused with
  `Authentication Failure`, could not run a command, and dropped the pairing as upstream intends.
- No new GLib or CJS criticals in the daemon log.

**With a real GSConnect:**

| Check | Result |
| --- | --- |
| TLS between OpenSSL (phone) and GnuTLS (PC) | Connected. Both sides independently showed the same verification key |
| Pair requested by the phone, accepted by CLI on the PC | Paired on both, certificate pinned in dconf |
| Pair requested by the PC, **Accept clicked in the phone's popup** | Paired on both. Popup (`temp/docs/evidence/gsconnect/pair-request.png`) |
| Daemon restart | Pairing kept; reconnected 9 s after `start` with no user action |
| 5 MB file with a non-ASCII name containing spaces, both directions | SHA-256 matched, name preserved (experimental stage) |
| 50 MB file, both directions | SHA-256 matched |
| 100 MiB file, PC to phone | SHA-256 matched; 3.5 s including polling, about 28 MiB/s |
| Ping and shared text | Ping popup shown (`temp/docs/evidence/gsconnect/ping-notification.png`). Text and link were accepted without a logged error; what the phone displayed for them was not captured |
| Find My Phone | Alert window opened (`temp/docs/evidence/gsconnect/find-my-phone.png`), silently; upstream's layout looks oversized here |
| Settings window | Runs natively (`temp/docs/evidence/gsconnect/settings-window.png`), listing the peer |

**Discovery** (`test-discovery.py`, a throwaway identity sent from the PC):

| Display state | Broadcast | Unicast |
| --- | --- | --- |
| Off (`Display Power: state=OFF`) | **No answer in 8 s**, while other peers answered | Answered in 0.14 s |
| After a wake key event | Answered in 0.10 s | Answered in 0.03 s |

The display state was not logged in the second row, but the changed broadcast result shows the
wake took effect. Broadcasts sent by the phone reached the PC, including with the display off.
`connect HOST:PORT` sent a unicast identity to the chosen port.

**Lifecycle:**

- `stop` ended the daemon, bus, dconf, notifier, xfconf and the AT-SPI services started by remote
  input, with no orphans, and closed the LAN port.
- A second `start` reports it is already running, and an invalid `--name` is refused.
- With the system bus address pointed at the private bus, which has no logind, the `login1` lookup
  failed, was logged, and did not stop the daemon. A completely absent system bus was not tested.
- With no X server, `start` must fail rather than report success. See [Defects](#defects-found-and-fixed).

**Idle cost**, over 60 s with the display off, paired and connected, using the migration report's
`measure-group.py` (`temp/docs/evidence/migration/measure-group.py`):

| Process | CPU, % of one core | PSS |
| --- | ---: | ---: |
| `cjs` (GSConnect daemon) | 0.5 | 59.8 MB |
| `xfce4-notifyd` | 0.0 | 22.5 MB |
| Python controller | 0.1 | 12.7 MB |
| dconf, xfconf, D-Bus | 0.0 | 5.6 MB |
| **Total** | **0.6** | **about 100 MB** |

This is one sample with no traffic. The guest's own `dconf-service` is excluded from the total.

## Reported by the user

During the run, the user reported a notification from "x11 termux" on the PC hosting the test
session. It is the only observation here made by a person. Its text and time were not captured,
and **the path it took is not established**, so it is not counted as a passing test:

- The test peer could not have shown it through its own bus. It logged `unable to send notifications
  through org.freedesktop.Notifications`, because nothing on that private bus provides them.
- The PC's own GSConnect connected to the phone but was never paired with it, and its code ignores
  notification packets from unpaired devices.
- That instance's "Discovery Disabled" notice (see [Side effects](#side-effects-of-testing)) would
  have appeared during these tests, but nothing links it to this report. It does not name Termux.
- No `termux` or `x11` application is registered in the PC's GNOME notification settings.

Phone-to-PC notification display therefore remains unconfirmed.

## Defects found and fixed

| Defect | Symptom | Fix |
| --- | --- | --- |
| GLib's default network monitor | `network_available` false, so `broadcast()` silently did nothing | `GIO_USE_NETWORK_MONITOR=netlink` |
| `GIRepository` 2.0 requested | Daemon failed at import | Patched to 3.0 |
| `HAVE_GNOME` false outside GNOME | Would spawn the absent `wl-paste`; found by reading the source | `GNOME_SETUP_DISPLAY` |
| Default device name `localhost`, and names that peers reject | Peers rejected the test name containing parentheses | Validated `--name`; default built from the model |
| CJS typelib signature ([details](README.md#termux-changes-to-gsconnect)) | `g_atomic_ref_count_dec` critical on every notification; a fatal-criticals backtrace located it | Listener and MPRIS export not started; 0 new criticals since |
| Controller set its environment after starting the bus | Stale dconf reads, device shown unpaired, notifier had no display | Environment now set before the bus starts |
| Controller reported ready too early | With no X server, printed "ready" and then died | Readiness now waits for GActions, which exist only after GTK opens the display |

The last fix was re-tested on the final package: see [Final package](#final-package).

## Not tested

- The **KDE Connect Android app** or an iOS peer. Neither is installed on the rig. SMS, contacts,
  telephony and media control therefore have no result.
- Native GNOME Shell: the extension's panel UI has not run natively. No native Shell existed during
  these tests. A separate port ([`docs/native/`](../native)) has since started one on the phone;
  the daemon's private bus would need joining to its session.
- The menu entry that port adds for `gsconnect ui`.
- Mouse clicks and key injection. Only pointer motion was tried, to avoid typing into a focused window.
- Android's own clipboard, as distinct from the X clipboard; whether Termux:X11 bridges them.
- Long sessions, Doze, reboot, network changes, battery cost, and Android 12+ process limits.
- SFTP, which is unsupported rather than merely untested: `sshfs` is absent from Termux.
- Upstream's GJS. The port ran only on Termux's CJS.

## Side effects of testing

**The PC's real GSConnect had discovery switched off by these tests.** Test identities took it past
upstream's limit on unpaired devices; `discoverable` went to `false` and was saved, and upstream
raises a "Discovery Disabled" notification when that happens. It was found by inspection and set
back to `true` after testing. Its existing pairings were not changed and no test device stayed in its
list. The prior `true` is inferred: the instance had just accepted a new unpaired device, which it
does only when discoverable. Other KDE Connect peers on the same network may also have seen test
devices unpaired.

The phone's GSConnect identity and settings were reset after testing, so its first `start`
generates a new certificate. Termux gained `cjs`, `spidermonkey`, `gobject-introspection`,
`glib-networking`, `dconf`, `gsettings-desktop-schemas`, `xfce4-notifyd` and their dependencies.

## Final package

The final `gsconnect` `62-1+deb13u1+termux1` was built from an empty cache, so Debian's
package was downloaded again and its checksum verified, then installed with APT.

| Check | Result |
| --- | --- |
| `DISPLAY=:77 gsconnect start`, no X server there | Exit 1 after 2 s with a clear message; no process left behind |
| Normal `start` | Exit 0 after 1 s; a second `start` reports it is already running |
| `test-protocol.py` | 14 of 14 passed; 0 criticals in the whole session log |
| `stop` | No process left behind; TCP 1716 refused from the PC |
| `apt remove` (on the build just before) | Controller and schema removed |

**The real-GSConnect table, discovery results, screenshots and idle cost came from the previous
build.** The patch to GSConnect is identical. The controller since changed only in how it detects
readiness and handles a failed start. Those tests were not repeated on the final build, to avoid
putting more unpaired identities on the LAN. A readiness check tried in between never succeeded on
a healthy daemon, because `gapplication list-actions` printed nothing; the final check uses
`org.gtk.Actions.List`, compared against both a healthy and a no-X daemon first.

`gsconnect` is left installed and **stopped** on the phone, so nothing is listening. Nothing
starts it automatically. Nothing is committed.

**One later change is not in the installed package.** `ui` now starts the daemon if needed, for
native desktop menu entries. A separate session was installing native GNOME dependencies by then,
and holding the dpkg lock could have failed its APT runs, so the package was not rebuilt. Only the
failure path of the new code ran on the phone, directly from the checkout with no X server; `start`
and `ui` were each tested before it, but the combined success path was not. Rebuild to pick it up,
along with later README changes, whose installed copy is also behind.
