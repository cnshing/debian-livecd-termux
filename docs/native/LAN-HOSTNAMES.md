# LAN hostname resolution

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
