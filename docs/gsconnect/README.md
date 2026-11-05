# Native GSConnect on Termux

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

This is an **opt-in Android/Bionic port** of the GSConnect the live CD ships: version 62,
built from the upstream source used by Debian's `62-1+deb13u1`, with Debian's security cherry-pick retained. It runs
in native Termux with no PRoot or root, independent of the Debian/PRoot desktop and of the
proposed native GNOME migration. It pairs with GSConnect and uses the KDE Connect protocol.

This port was tested without a native GNOME Shell, so the Shell extension itself has not run
natively. The daemon, the settings window, pairing and the plugins listed below have. Packaging,
device results and limits are in [the verification report](VERIFICATION.md).

```text
peer on the LAN ⇄ TLS, TCP/UDP 1716 ⇄ GSConnect daemon (cjs) on a private D-Bus session
                                        ├── settings window and popups on Termux:X11
                                        └── dconf, X clipboard, Android battery from sysfs
```

## Why this runs on CJS

GSConnect is GJS JavaScript, and official Termux publishes no `gjs` package. It does publish
`cjs`, Cinnamon's maintained GJS fork, built against the same `spidermonkey` 140. GSConnect
62 runs on it with [the Termux source patch](../../packages/gnome-shell-extension-gsconnect/0001-termux.patch). The recipe now builds the verified upstream source archive with Meson and retains Debian's identity-validation fix. No native
GJS is built by this GSConnect recipe. The separate native desktop packages use their own GJS 1.84.2;
GSConnect remains on CJS to preserve its independently tested runtime.

## Build and install

[The recipe](../../packages/gnome-shell-extension-gsconnect/build.sh) downloads the hash-verified upstream source archive,
applies Debian's security fix and the Termux patch, and builds the resources with Meson. GitHub Actions builds it with the other packages.
To install it from the local apt repository, run this in native Termux:

```sh
python src/apply-overlays.py "Desktop Environment+Phone Sync"
```

## Run

It needs an X server. The running Termux desktop's Termux:X11 display works, or
start `termux-x11 :0` first. `DISPLAY` defaults to `:0`.

```sh
gsconnect start                # also: start --name 'My phone'
gsconnect status
gsconnect ui                   # settings window; starts the daemon if needed
gsconnect pair DEVICE_ID       # request pairing, or accept a pending request
gsconnect unpair DEVICE_ID
gsconnect connect HOST[:PORT]  # contact a peer without relying on broadcasts
gsconnect exec -- COMMAND ...  # run on the private bus, such as the daemon's own CLI
gsconnect stop
```

The controller owns the daemon and its private session bus, which is separate from the PRoot
desktop's. `stop` ends all of it. **While it runs, the phone listens on TCP and UDP 1716 on
the LAN**. The [native desktop](../native/README.md#session-integrations) starts this controller
automatically when installed, and stops its owned instance with the desktop. That hook can be
disabled independently. Logs are in `~/.local/state/gsconnect/session.log`.

Compare the **verification key** on both devices before accepting a pair request. Files arrive
in `~/Downloads`; a per-device setting can change that, for example to `~/storage/downloads`
after `termux-setup-storage`. Run Command defaults come from upstream and name `systemctl`
and similar tools that Android lacks, so replace them with commands that work here.

## What works and what does not

| Feature | State |
| --- | --- |
| Discovery, TLS, pairing, reconnect after restart | Works. Popup Accept button and CLI both tested |
| File sharing; ping; Find My Phone alert | Works. The alert is silent: `gsound` is not a dependency |
| Shared text and links | Accepted without error. What the phone then shows or opens was not checked |
| Clipboard sync | Works with the **X clipboard**. Android's own clipboard was not tested |
| Battery report to the peer | Works, read from Android sysfs. Enable it per device, as upstream |
| Run Command | Works, using Termux's `sh` |
| Remote pointer | Pointer motion works through AT-SPI. Clicks and keys were not tested |
| Shell panel menu and Nautilus integration | **Not available here**: tested without a native Shell or Nautilus, and the daemon's bus is private |
| Native desktop menu entry | The separate [native desktop port](../native) launches `gsconnect ui` from its menu. Not tested here |
| Forwarding desktop notifications to the peer | **Disabled**; see the patch table |
| Exposing a peer's media players locally | **Disabled**; see the patch table |
| Volume control | **Unavailable**: needs GNOME Shell's private `Gvc` library |
| Browsing a peer's files (SFTP) | **Unsupported**: no `sshfs` or FUSE in Termux |
| SMS, contacts, telephony | Not tested: these need the KDE Connect Android app as the peer |

## Android behaviour to expect

- **With the screen off the phone did not hear UDP broadcasts**; unicast still worked. Existing
  connections and paired-device reconnects are unaffected. To find a new peer, wake the screen,
  or start from the phone, whose broadcasts still go out, or use `connect HOST`.
- **Discovery can switch itself off.** Upstream GSConnect disables discovery when a fourth
  unpaired device appears, and saves that. Paired devices keep working. Re-enable it in the
  settings window. Other GSConnect instances on your LAN apply the same rule to this phone.
- **Every KDE Connect device on the LAN can see this one**, as an unpaired device, while it runs.
  Anyone on the LAN can send a pair request, but only an accepted one gains access.
- The phone reports itself as a `desktop`, because it runs a desktop session.

## Termux changes to GSConnect

[`gsconnect-termux.patch`](../../packages/gnome-shell-extension-gsconnect/0001-termux.patch) is the complete list:

| Change | Reason |
| --- | --- |
| Paths in `config.js` and the D-Bus service; `cjs -m` shebangs | Termux's prefix and interpreter |
| `GIRepository` 3.0 instead of 2.0 in the daemon | CJS links `libgirepository-2.0`, whose typelib is 3.0 |
| Run Command uses Termux's `sh` | `/bin/sh` is Android's shell, not Termux's |
| Battery component reads sysfs | Android has no UPower |
| Notification listener not started; MPRIS objects not exported | **Memory safety**, below |

**Why two features are disabled.** Termux's `cjs` 140.2 typelib has the wrong
`handle-method-call` signature for `GjsPrivate.DBusImplementation`: `transfer full` sits on
the wrong argument. Each method call reaching a JS handler then calls `g_variant_unref()` on
what is really a `GDBusMethodInvocation`, logged as `g_atomic_ref_count_dec` criticals and
reproduced outside GSConnect (`temp/docs/evidence/gsconnect/cjs-handle-method-call.txt`). Only those two features can receive such calls.
On this private bus nothing would use them, since no other application shares it, but a native
desktop on a shared bus would want them back after the package is fixed. That package also
passes these arguments in a different order from GJS, which restoring them must handle.

The controller also sets three environment values before the bus starts, so activated services
inherit them: `GIO_USE_NETWORK_MONITOR=netlink`, because GLib's default monitor reports no
network here, which silently stops discovery; `GNOME_SETUP_DISPLAY`, which selects X11
clipboard access over `wl-paste`; and a private `XDG_RUNTIME_DIR`.

## Tests

With the daemon running, from a PC on the same LAN:

```sh
python3 tests/gsconnect/test-protocol.py PHONE_IP              # packet-level checks
python3 tests/gsconnect/test-discovery.py unicast PHONE_IP
bash tests/gsconnect/test-peer.sh start                        # a real, isolated GSConnect
bash tests/gsconnect/test-peer.sh cli --list-all
bash tests/gsconnect/test-peer.sh stop
```

**These put new unpaired identities on your LAN.** The test peer and broadcast mode can trip
the discovery limit on other GSConnect instances, including the PC's own, and leave it off.
Afterwards, run `gsettings get org.gnome.Shell.Extensions.GSConnect discoverable` on the PC.
Do not assume these runs are invisible on the PC either: a notification from the phone was
[reported there during testing](VERIFICATION.md#reported-by-the-user), by a path not identified.

## Remove

```sh
gsconnect stop
apt remove gnome-shell-extension-gsconnect
```

The certificate in `~/.config/gsconnect`, settings in `~/.config/dconf`, received files, logs
and the build cache are kept. Removing the package does not unpair it from peers.
