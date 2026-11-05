# Native resource access

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

Mission Center previously owned a fixed Shizuku reader and its Rust transport.
Its Android Magpie backend used them for whole-device CPU ticks, process metadata,
Qualcomm KGSL GPU data and thermal sensors. Memory still came from `/proc/meminfo`,
and battery data already used the shared UPower daemon. The upstream Linux backend
also collects its own resources, through procfs/sysfs, sysinfo and device-specific
libraries; it does not depend on a universal Linux resource daemon.

That distinction matters for the UPower analogy. Battery has a common D-Bus service.
For CPU and processes, the common Linux interface is primarily the kernel's
[`/proc` filesystem](https://www.kernel.org/doc/html/v6.15/filesystems/proc.html).
Replacing one desktop library would help only its consumers. It would not fix
ordinary programs such as `top` and `htop` that read the files themselves.

`android-procfs` now owns the reader and transport. Mission Center links its
shared library, and dynamically linked native applications can use a compatibility
layer at the libc file interface. Those applications keep their ordinary paths
and parsers. Android's kernel permissions remain intact.

## Build and use

In native Termux, with the existing Shizuku installation running and Termux authorized:

```sh
bash tools/build-packages.sh --install android-procfs
# Compatibility entry point: bash packages/android-procfs/build-on-device.sh
# Export rish and its DEX from Shizuku into ~/.local/lib/shizuku first.
android-procfs-setup

android-procfs-run top
android-procfs-run htop
android-procfs-run ps -A -o pid,ppid,user,comm
android-procfs-run head -3 /proc/stat
```

Setup stages one fixed executable in the shell-owned
`/data/local/tmp/android-procfs-UID/` directory. It does not start a sampler.
Repeat setup after updating the reader. `ANDROID_PROCFS_RISH` selects another
rish export; `MC_RISH` is retained as a fallback. The first client to start the
broker supplies its environment, so stop idle broker processes before changing
that setting.

The [native desktop startup hook](../native/README.md#session-integrations) runs
this same setup command automatically when installed. It adds no background sampler.

`livecd-desktop` depends on the corrected `android-procfs` package, version
`1.0.0-1` or later. Mission Center also depends on it. The desktop controller uses
the APT-owned `$PREFIX/lib/libandroid-procfs.so` and
`$PREFIX/libexec/android-procfs/bin/top`. Termux's own `top` launcher clears
`LD_PRELOAD`, so the packaged launcher reaches Android's `top` through the native
exec helper. `tools/build-session-preload.sh` is a compatibility entry point for
the standard package builder; it no longer builds an isolated copy.

The controller retains the existing Termux preload and tests the proposed preload
with Node.js before adding it to the session, using Python if Node.js is absent.
If that test fails, it leaves the library and `top` override out and reports why.
Restart the desktop after installing the corrected package and controller.
The old isolated runtime stays available for rollback. Outside the session use
`android-procfs-run`, or set the preload explicitly for compatible Termux programs.
`ANDROID_PROCFS_COMPAT=0` disables the controller's automatic preload; Mission Center's
direct library access continues to work.

The earlier library aborted Node.js programs when preloaded. The recipe retains
`-fno-emulated-tls` and now rejects an artifact without an ELF TLS segment. ELF TLS
requires [Android 10 / API 29](https://android.git.googlesource.com/platform/bionic/+/HEAD/android-changes-for-ndk-developers.md#elf-tls-available-for-api-level-29).
The flag fixes the observed crash; its exact mechanism remains unproven.
See the original evidence (`temp/docs/evidence/code-oss/preload-abort.txt`) and
[the integration audit](PROC-STAT-AUDIT.md).

The launcher uses a small native exec helper for explicitly selected Android
system binaries, preserving the requested preload across Termux's exec wrapper.
It leaves the stock `termux-tools`, `htop` and `libgtop` package files intact.

## Request lifecycle

```mermaid
sequenceDiagram
    participant A as Ordinary native application
    participant L as libc compatibility library
    participant B as Shared native broker
    participant S as Native reader (Android shell)
    participant K as procfs / sysfs
    A->>L: open /proc/stat
    L->>B: Request current bytes
    Note over B,S: First request only: Shizuku starts reader and exits
    B->>S: read /proc/stat
    S->>K: Read now
    K-->>S: Current kernel bytes
    S-->>B: Framed bytes + checksum
    B-->>L: Snapshot
    L-->>A: Anonymous memory file descriptor
    Note over B,S: Block between requests; no sampling timer
    A->>L: rewind held descriptor / FILE
    L->>B: Request a new sample
```

The broker activates on demand through a private Unix socket below
`~/.cache/android-procfs/run`. Its directory is mode 0700, and both ends check
the peer UID. All clients share one shell reader. A 256-bit random token
authenticates its initial loopback connection; the listener then closes. The
reader scrubs its token from its command line. Shizuku's Java client is reaped
after connection, leaving native processes for collection.

No component independently refreshes data. Repeated reads happen only at the
application's own refreshes. Opening `/proc` requests one batch containing process
stat, command line, executable, UID/GID, status, statm and accessible I/O counters.
PID reads during that enumeration use the same batch. A separate compact thread
batch is requested only if a caller opens a task directory. Closing an enumeration
ends reuse of its readings; retained PID descriptors fetch fresh data afterward.
A later enumeration collects anew.
There is no timer-based cache or copied statistics file on disk.

The last client disconnect closes the reader's socket, so the reader exits. The
small broker remains asleep in `accept()` for future clients. It retains no
Shizuku connection or Java process while unused. Initial authorization is bounded
to 15 seconds, active reads to two seconds. Broken transports are discarded;
reconnection happens on the next request, with a one-second failure backoff and
no automatic retry timer. Per-file errors preserve the healthy connection.

## Interfaces covered

| Interface | Behavior |
|---|---|
| `/proc/stat` | Genuine aggregate and per-core counters, including reads after `lseek`, `rewind` and stdio seeks |
| `/proc` enumeration | Accessible shell-visible process IDs, batched once per enumeration |
| `/proc/PID/{stat,status,statm,cmdline,io,comm}` | Actual kernel contents, with metadata and NUL-separated command lines preserved |
| `/proc/PID/task/TID/stat` and task enumeration | Actual thread counters, collected only when requested |
| Process directory stat/fstat, relative `openat`, descriptor duplication | Preserve virtual process paths, UID/GID and enumeration context |
| `/proc/PID/exe` readlink | Shell-readable target; unavailable targets remain errors |
| `wchan`, `oom_score`, `oom_score_adj`, `smaps_rollup` | Read on explicit demand, subject to shell access |
| `meminfo`, `uptime`, `loadavg`, `net/dev`, `diskstats`, `vmstat`, pressure files | Keep native reads when accessible; allowlisted privileged fallback when denied |
| `/sys/class/thermal/thermal_zoneN/{type,temp}` | Enumeration and direct sensor reads |
| KGSL model, busy/total, clock and available frequencies | Native paths and Mission Center's shared telemetry request |
| Termux's frozen `var/{htop,libgtop}/stat` inputs | Read the live `/proc/stat` source instead |

The two frozen-path aliases are necessary because Termux patches those applications
away from the real file. See the upstream Termux recipes for
[`htop`](https://github.com/termux/termux-packages/blob/master/packages/htop/build.sh)
and [`libgtop`](https://github.com/termux/termux-packages/blob/master/packages/libgtop/build.sh).
Their installed sample files are not overwritten.

The library also exposes `android_procfs_snapshot()` and
`android_procfs_free()` in `android-procfs.h`, discoverable through
`pkg-config android-procfs`. Mission Center uses this API directly and needs no
preload. Its remaining Android adapter parses data into Magpie's application
model; it no longer launches Shizuku or implements privileged transport.

The reader accepts only fixed categories and a fixed path allowlist. It cannot
open arbitrary files, read process environments, write kernel settings or signal
processes. Native process-control permissions are unchanged. UPower continues to
provide battery data through its existing ordinary API.

## Compatibility boundary

This is native libc compatibility, not a mounted replacement procfs. It covers
the paths and calls above for applications that inherit the preload. Static
binaries, direct inline syscalls, unusual I/O paths and programs that clear their
environment can bypass it. An application sandbox may also deny its IPC or
memory-file operations. Other Android apps do not inherit the layer or gain
access to the broker. Kernel-level transparent access for every program would
require privileged OS changes outside an unrooted Termux installation.

Anonymous descriptors are snapshots, refreshed by the intercepted seek APIs.
Android on this rig denies reopening a memfd even through its creator's
`/proc/self/fd`, so the read-only view is enforced at the same libc boundary;
the underlying descriptor is not a kernel permission boundary. Writing an
anonymous snapshot cannot change its procfs source, and the privileged API has no write path.
On failed refresh the old bytes are discarded. Some ordinary applications may
show an empty value or exit according to their own error handling; Mission Center
retains its explicit unavailable state and resets its CPU baseline on recovery.

Shell's own Android restrictions still apply. GPU-vendor libraries, NVML/DRM
emulation, PSS for inaccessible processes, per-process network accounting,
arbitrary task files, disk-management services and every procfs operation are not
implemented. Missing data stays unavailable. This does not make a phone's
hardware or services identical to a desktop PC.

See [device verification](VERIFICATION.md) for tested programs and measurements.
