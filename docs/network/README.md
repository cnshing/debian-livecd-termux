# Native file sharing and discovery

The `gvfs` recipe enables SMB and DNS-SD using Samba's client library and the
`livecd-avahi` recipe. SFTP, FTP, WebDAV and local/trash backends stay enabled.
FUSE and UDisks2 stay disabled. Remote resources are GIO locations, not ordinary
filesystem mounts for shell programs.

Build only this package set with the existing Packages workflow:

```sh
gh workflow run packages.yml --ref YOUR_BRANCH -f packages=gvfs -f rebuild=true
```

The planner produces one build job containing `livecd-avahi gvfs`; unrelated
recipes are not built. Main-repository dependencies, including Samba, come from
Termux's package repository. A successful Actions build establishes cross-build
and packaging compatibility, not Android runtime or remote-share behavior.

The File Manager overlay starts `livecd-network-discovery` through the native
session's autostart directory. It uses the existing private system D-Bus and
inherits the session ownership tag, so normal desktop cleanup stops it. Its
configuration disables publishing host services. To start it in an already
running session after installation:

```sh
livecd-native exec -- livecd-network-discovery
```

Open `smb://HOST/SHARE` using Nautilus's Ctrl+L. For advertised services, open
Network or `dns-sd://local/`. Configure credentials through Nautilus; do not put
passwords in URIs, shell arguments or committed fixtures.

## Upstream limitations

The original [Termux GVfs PR](https://github.com/termux/termux-packages/pull/13972)
shipped with SMB and DNS-SD disabled, without documenting a specific reason.
DNS-SD needs Avahi: its daemon was later moved to the root repository because
Android can reject its route-netlink interface monitor. See
[the maintainer discussion](https://github.com/termux/termux-packages/issues/17061)
and [the move](https://github.com/termux/termux-packages/pull/17079).

This project carries Termux's Android memory-header, daemon identity/path and
configure-path patches from builder revision
`538685c906074926fd19650e38c6dad91379eb0f`. It builds only the discovery components
needed here, with a separate package name conflicting with the upstream Avahi
package. This does not remove newer Android netlink restrictions. Rootless
operation must be validated on each device; a failed discovery daemon must not
be treated as evidence that direct SMB access is unavailable.

The optional WSD backend is disabled because it requires an external `wsdd`
helper. mDNS/DNS-SD discovery and unicast LAN DNS are separate mechanisms. This
package does not rewrite DNS settings or install a global `.local` resolver.

## Verification

Runtime results are recorded after testing the Actions artifacts. Host, share,
user and volume names belong in local environment variables or ignored evidence,
not source or reports. A test against one server cannot establish compatibility
with every SMB server or Android release.
