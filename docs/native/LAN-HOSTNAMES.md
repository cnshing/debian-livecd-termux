# LAN hostname resolution

## Project package follow-up

The project's `gvfs` and `avahi` package set now enables SMB and DNS-SD.
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

## Chrome resolver failure reproduced (2026-11-21)

The Note10+ still has a separate LAN DNS failure in Google Chrome's glibc
environment. The earlier native resolver and SMB discovery checks did not fix
this path. With Android Private DNS Off, Android's system `ping` and native
Termux Python resolved a private `home.arpa` test name. Native Python fetched
HTTP 200 using either the hostname or its address. The desktop session was
stopped during these checks; the installed Chrome launcher was tested headless.

Both `$PREFIX/etc/resolv.conf` and glibc's symlink to it still selected Google's
public DNS servers. Direct queries to both public servers returned NXDOMAIN;
the network-provided DNS server returned an A record. With preload and library
environment variables removed, glibc `getent ahostsv4` exited 2. Chrome's NetLog
recorded a DNS error and its headless stderr reported
`net::ERR_NAME_NOT_RESOLVED`.

Temporarily replacing only glibc's resolver symlink with a file selecting the
current network's DNS server made `getent` exit 0 and Chrome's NetLog report the
correct A record. The original symlink was restored after testing; the shared
Termux resolver file and Android settings were unchanged. This establishes the
DNS cause, but does not establish a successful Chrome page load: after DNS
succeeded, headless Chrome reported `net::ERR_BLOCKED_BY_CLIENT`, which needs a
separate browser investigation.

The installer currently links resolver files; it does not synchronize glibc DNS
with Android when networks change. The immediate configuration remedy is to use
the current network's DNS server in glibc's resolver file, with its search domain
when short names are needed. A durable fix must follow network changes or bridge
glibc queries to Android's resolver. Hard-coding a private hostname, address, or
router into the package would not provide that behavior. Avahi service discovery
does not repair unicast `home.arpa` DNS.

Raw Chrome logs and private test inputs are intentionally excluded from tracked
documentation.

Follow-up checks using the controller's software-renderer desktop environment
also passed native Python resolution and a native `curl` HTTP request (200).
Chromium's NetLog showed its system resolver returning the correct LAN address
with the original DNS configuration untouched. A separate Firefox headless
profile also used native DNS and obtained a cached record for the test name;
that control disabled DNS-over-HTTPS explicitly. These checks narrow the
reproduced DNS failure to Chrome's glibc path rather than a general desktop
network failure. Chromium also reported `ERR_BLOCKED_BY_CLIENT` during page
loading, independently of its successful hostname lookup.

## Shared resolver fix verified (2026-11-21)

The `bionilux` 0.5.0-3 recipe now supplies the Android NSS module described below.
A local package was installed on the Note10+, retaining the installed unchanged
Bionilux launcher/preloads and adding the newly cross-compiled NSS module and
package configuration scripts. No browser launcher or application binary was
changed. The shared Termux `resolv.conf` remains unchanged.

With that package installed, glibc `getent` passed the private hostname, public
IPv4/IPv6, localhost and reverse lookup checks; a nonexistent `.invalid` name
correctly exited 2. Chrome's NetLog showed successful system resolver lookups
for the private name. A fresh Chrome profile loaded the actual application via
DevTools after disabling `HttpsFirstBalancedModeAutoEnable` for that headless
test process only. This resolves the earlier page-load uncertainty: HTTPS-first
handling of the HTTP navigation caused the headless `ERR_BLOCKED_BY_CLIENT`.
No persistent browser security setting was changed. Native `curl` still returned
HTTP 200.

The host regression suite is `python3 tests/browsers/test-android-dns.py` (12
tests): fragmented protocol replies, IPv4/IPv6, canonical names, scope IDs,
reverse lookup, negative/transient errors, small/unaligned buffers, malformed
replies, concurrent calls, configuration migration and removal. The packaging
suite also passed. Live network/VPN switching was not exercised; each request
uses network ID zero rather than saving a network ID or DNS server address.

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

The shared glibc resolver integration in `bionilux` 0.5.0-3 installs
`libnss_android.so.2` and selects `hosts: files android` in glibc's
`nsswitch.conf`. It asks Android's existing `/dev/socket/dnsproxyd` service for
hostname lookups using the calling UID's default network. It does not copy DNS
server addresses, bind a local DNS port, start a daemon, or require app-specific
preloads. Network selection, search domains, VPN routing, Private DNS and DNS
caching remain with Android. A configured public Private DNS provider can still
lack private LAN records, just as for native Android apps.

Chrome checks NSS configuration and uses its system resolver when it encounters
an unsupported service such as `android`; this is how the shared module can cover
Chrome without adding hostname mappings or browser-specific DNS flags. The
[AOSP service implementation](https://android.googlesource.com/platform/packages/modules/DnsResolver/+/refs/heads/android11-release/DnsProxyListener.cpp)
and [Chromium NSS compatibility check](https://chromium.googlesource.com/chromium/src/+/HEAD/net/dns/dns_config_service_linux.cc)
are the protocol and behavior references. The module currently relies on
Android's internal socket protocol, so testing new Android versions remains
necessary. It exports forward IPv4/IPv6 and reverse host lookup NSS entry points;
it does not provide arbitrary DNS record queries.

Package installation migrates only the standard `hosts: files dns` configuration,
or creates it when absent. Other NSS configuration is preserved. To enable the
module in a custom configuration, explicitly select the `android` hosts service.
The setup helper is `$PREFIX/libexec/bionilux/configure-dns`; package removal
restores the standard configuration to `hosts: files dns`. Restart running glibc
applications after installation so cached resolver results are discarded.

Programs that deliberately bypass libc/NSS and query the servers in
`$PREFIX/etc/resolv.conf` directly still need their own network DNS configuration.
That file remains unchanged. The distinction and the problems with copying
`getprop net.dns1` are discussed in
[Termux issue #1174](https://github.com/termux/termux-packages/issues/1174).
The [glibc Chrome setup](../../overlays/Browser+Chromium/browsers/install-chrome.py)
preserves the NSS configuration installed by the shared package.

Support for transparent `.local` resolution depends on the installed Android
resolver module. See AOSP's [mDNS resolution documentation](https://source.android.com/docs/core/ota/modular-system/dns-resolver#mdns-local-resolution).
