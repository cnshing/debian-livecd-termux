# LAN hostname resolution

## Project package follow-up

The project's `gvfs` and `livecd-avahi` package set now enables SMB and DNS-SD.
The Actions-built packages passed direct share browsing, discovery of the same
server, opening its discovered address, and Network enumeration on the Android
11 rig. The discovery daemon runs rootless on the desktop's private system bus;
stop/start testing confirmed session cleanup and automatic startup. See
[network package setup and verification](../network/README.md).

This leaves Android's DNS configuration unchanged. The stock-package failures
below describe the baseline before installing the project's replacement.

## Stock package device check

With Private DNS **Off**, the Android 11 Note10+ receives its router's DNS
address and DHCP search domain. Both the NAS's short name and its fully qualified
LAN DNS name resolve from Python's `socket.getaddrinfo()` inside
`livecd-native exec`. A TCP connection to the NAS's SMB port 445 also succeeds.
This establishes that native desktop DNS and SMB transport reachability work in
that configuration.

The NAS answers a direct multicast DNS query for `_smb._tcp.local`, advertising
an SMB service and a `.local` hostname. However, ordinary `getaddrinfo()` on
this phone fails for that `.local` hostname. Unicast LAN DNS, multicast service
discovery and `.local` hostname resolution are separate checks.

The stock Termux GVfs 1.62.0 had neither `smb` nor `dnssd` support. Its
[upstream recipe](https://github.com/termux/termux-packages/blob/master/x11-packages/gvfs/build.sh)
sets `-Dsmb=false` and `-Ddnssd=false`. The desktop's GIO URI scheme list includes
`network` and `wsdd`, but excludes `smb`. Querying an SMB URI by either the
working LAN DNS name or the server's IP produces **The specified location is not
supported**. `gio list network:///` returns no entries on this rig. Changing DNS
cannot supply these missing backends; a `network` or `wsdd` scheme alone does
not establish working SMB access or discovery.

Termux's `$PREFIX/etc/resolv.conf` separately contains Google's public DNS
servers. This file can prevent LAN DNS lookups in programs that read it directly,
including the separately configured glibc environment. It is not evidence that
native Bionic/GIO programs bypass Android's working resolver. The baseline check
did not change resolver configuration or connect to an authenticated share.

Local evidence: `temp/storage-dns/results.json`,
`temp/storage-dns/discover.py`, and `temp/connectivity-storage-dns.txt`.
Private server names, endpoints and raw network configuration remain local.

## Why upstream omits these backends

The [initial GVfs addition, PR #13972](https://github.com/termux/termux-packages/pull/13972)
already disabled SMB and DNS-SD, alongside many other optional backends. Its
description and discussion do not explain those two choices. SFTP was subsequently
enabled in [PR #15173](https://github.com/termux/termux-packages/pull/15173).
There is no established SMB-specific incompatibility in those discussions.

There is a documented dependency obstacle for DNS-SD. In
[Avahi issue #17061](https://github.com/termux/termux-packages/issues/17061),
Android rejected Avahi's route-netlink bind with `Permission denied`; its
interface monitor then aborted. Maintainer xtkoba described the fix as requiring
considerable work, agreed to moving Avahi to the root repository, and explained
that main/X11 packages could then no longer depend on it. The move was merged in
[PR #17079](https://github.com/termux/termux-packages/pull/17079), after
[removing Avahi dependencies](https://github.com/termux/termux-packages/pull/17064).
This later restriction explains a current dependency obstacle, not the original
GVfs author's undocumented intent.

[GVfs's build definition](https://github.com/GNOME/gvfs/blob/1.62.0/meson.build)
requires `smbclient` for `-Dsmb=true`, and `avahi-client` plus `avahi-glib` for
`-Ddnssd=true`. SMB therefore has a plausible separate path through Termux's
Samba package. DNS-SD also needs a functioning Avahi daemon and its D-Bus
integration; the Termux Avahi configuration disables D-Bus by default.
Successful direct mDNS packets do not prove that Avahi's interface monitoring
can run. WSD discovery is another option, but GVfs's `wsdd` backend launches an
external `wsdd` executable, absent on the tested phone. A compiled backend alone
does not supply that helper.

## Earlier Private DNS diagnosis

Android's configured public Private DNS provider may resolve Internet names while
failing to resolve names known only to the local network's DNS server. A reachable
LAN address and a failed hostname lookup indicate different network operations.

Changing the terminal or choosing software rendering versus Zink does not change
Android's DNS configuration. The desktop controller's
[`graphics.py`](../../src/native/graphics.py) selects graphics libraries through
environment variables; it creates no network namespace or DNS configuration.

## Diagnose the resolver path

Compare hostname resolution with direct IP connectivity using addresses from your
own network settings. Check whether the network's DNS server has the hostname
record, and whether Android instead uses an explicit public Private DNS provider.
A successful direct mDNS query does not by itself establish that ordinary
`getaddrinfo()` resolves `.local` names on the installed Android resolver.

Termux's `ping` wrapper uses Android's system binary and resolver. Editing
`$PREFIX/etc/resolv.conf` alone does not redirect that native resolver.
Google's [Android DNS explanation](https://security.googleblog.com/2022/07/dns-over-http3-in-android.html)
describes how an explicitly configured central resolver overrides DHCP DNS.

## Configure for the current network

Android's **Automatic** Private DNS setting uses network-provided DNS and attempts
encrypted DNS when supported. This can make local DNS records available when the
network's server provides them. See Google's
[Android Private DNS instructions](https://developers.google.com/speed/public-dns/docs/using#android).

Applications that read `$PREFIX/etc/resolv.conf` directly need their own resolver
configuration using the current network's DNS server and search domain. The
[glibc Chrome setup](../../overlays/Browser+Chromium/browsers/install-chrome.py)
uses this file separately from native Android applications. Review that
configuration when switching networks.

Support for transparent `.local` resolution depends on the installed Android
resolver module. See AOSP's [mDNS resolution documentation](https://source.android.com/docs/core/ota/modular-system/dns-resolver#mdns-local-resolution).
