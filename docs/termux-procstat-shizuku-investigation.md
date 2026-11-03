# Native Termux `/proc/stat` through Shizuku: investigation

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](privacy.md).

**Implementation follow-up:** the [native Mission Center port](mission-center/README.md)
now implements this design and extends privileged reads to Android processes
and hardware telemetry. See its [device verification](mission-center/VERIFICATION.md).
The investigation below records the earlier prototype and its evidence boundary.

Investigated on the connected Galaxy Note10+, Android 11 / SDK 30,
ARM64, with SELinux enforcing and Shizuku+ 13.6.0.r2551 running as ADB shell.

**A native Mission Center can receive genuine `/proc/stat` data without patching
the Termux APK or running PRoot.** A small privileged reader can answer requests
over one persistent Shizuku/rish connection. The tested native client stays at
the Termux UID; the reader stays at the shell UID. This makes the data available
through IPC, rather than granting Termux permission to open the kernel file.

**The requested design has no independent polling helper.** After clarification,
the requirement is to read only when Mission Center asks for a sample at its
normal refresh. The request-driven prototype below meets that requirement.
There is no timer in the reader, continuous copying, or snapshot file. A complete
native Mission Center port has not been built or benchmarked in this investigation.

## What works, and what “direct access” means

| Approach | Finding | Evidence boundary |
| --- | --- | --- |
| Native Termux opens the real `/proc/stat` | Denied, including from native Rust | Reproduced on this phone |
| `rish -c 'cat /proc/stat'` from Termux | Reads genuine device counters as UID 2000, domain `shell` | Reproduced through the installed Shizuku+ |
| Persistent request/response reader through `rish` | Works, without an autonomous sampler or copied file | Implemented and tested on this phone |
| Existing preload shim redirects a native Rust file read | Works, but the old file-copy delivery does not meet the clarified preference | Diagnostic test only; helper stopped |
| Shizuku+ `StorageProxy.openFile("/proc/stat", …)` returns the original FD | Not a supported way to grant the Termux domain access to this inode | Source-based conclusion; direct Binder call not tested |
| Run the whole Termux installation under `rish` | Shell cannot access the app's private prefix and libraries | Documented by the rish project; not a native desktop solution |
| Patch Termux's APK to integrate Shizuku | Could add a privileged service/client, but does not by itself change SELinux's file policy | Unnecessary for the demonstrated reader |

Native code runs as the Termux app in `untrusted_app_27`; `/proc/stat` has mode 0444 but
label `proc_stat`. The native Rust read fails with `EACCES`, and native
`os.access(..., R_OK)` returns false. Shizuku+'s running server and the reader
instead run as UID 2000 in `shell`. Raw native probes (`temp/docs/evidence/procstat-investigation/native-result.txt`)

This matches [Shizuku's documented privilege model][shizuku-api]: privileged
Java/JNI code executes in another process, and Linux permissions still depend
on UID, capabilities and SELinux. Native application code does not inherit the
server's identity. Standard Shizuku offers the same UserService/rish mechanism;
only the installed Shizuku+ was tested here. Its [rish documentation][rish]
also explains why preserving Termux's environment does not let the shell process
use the private Termux prefix.

### Why the Shizuku+ file-descriptor API is insufficient

The inspected [StorageProxy implementation][storage] directly calls
`ParcelFileDescriptor.open(File(path), mode)`. Its pipe fallbacks handle particular
storage/app-data paths; it has no `/proc/stat` proxy fallback. Returning the
original FD preserves the protected inode.

The Android common kernel's [SELinux hooks][hooks] check the receiving task's
permissions on Binder FD transfer (`selinux_binder_transfer_file`), SCM_RIGHTS
receipt (`selinux_file_receive`), and subsequent reads if the security identity
differs (`selinux_file_permission`). Consequently, opening the file as shell is
not sufficient to let the app read that same inode. A pipe carrying bytes read
by the privileged process is a different operation, and is what the working
request prototype uses. This is a source-based inference supported by the native
read denial, not a claim to have exercised StorageProxy on the installed build.
The inspected common-kernel source is not the Samsung device's exact kernel tree.

An attempted cross-UID SCM_RIGHTS test was blocked at Unix-socket `connect()` for
both the regular-file control and `/proc/stat`. Therefore it did **not** test FD
receipt and is excluded from the conclusion above. The source and failed test
log (`temp/docs/evidence/procstat-investigation/fd-pass-result.txt`) are retained for clarity.

Shizuku+'s [SU Bridge documentation][su-bridge] also distinguishes real shell
operations from simulated success for operations that require root. A wrapper's
successful `mount` or `chmod` exit status would not establish direct access.
Real root with a suitably privileged domain/policy could change the situation;
this investigation assumes the existing unrooted device.

## The request-driven path, tested

```mermaid
sequenceDiagram
    participant M as Native Magpie (Termux UID)
    participant R as Persistent rish connection
    participant H as Reader (shell UID)
    participant K as Kernel /proc/stat
    Note over H: Blocks waiting for a request
    M->>R: Request CPU sample
    R->>H: stat
    H->>K: Open and read once
    K-->>H: Current counters
    H-->>R: Length + snapshot bytes
    R-->>M: Snapshot for CPU calculations
    Note over H: Blocks again; no timer
```

The C reader (`temp/docs/evidence/procstat-investigation/request-stat.c`) accepts `stat` and
`quit` on stdin and returns a length-framed snapshot. The native Python
client (`temp/docs/evidence/procstat-investigation/request-client.py`) keeps one `rish` process
open. Python is only the transport test client; the eventual Magpie client can
be Rust. Neither side requires rebuilding the Termux app.

Observed results in the request test log (`temp/docs/evidence/procstat-investigation/request-result.txt`):

- The client retains the Termux app identity; the reader uses shell UID 2000.
- During an idle period, the reader remained asleep in `pipe_read`. Across two
  observations, user ticks stayed 0, system ticks stayed 2, and `syscr` stayed 158.
  The client received no unsolicited bytes during its three-second initial wait
  or the one-second wait between requests.
- Two explicit requests returned 2,151-byte snapshots, each with eight core rows
  and `btime`. Aggregate ticks advanced from 132597685 to 132598437.
- The same reader served both requests and exited after `quit`; the client and
  `rish` exited successfully. No test reader was left running.

This demonstrates delivery of live kernel data and idle blocking, not a full
accuracy, power, latency, or Mission Center performance benchmark. The current
Shizuku+ export delivered command output on the stream captured with stderr;
the prototype merges stdout/stderr and recognizes its startup banner. Production
integration needs explicit framing/error handling, bounded waits, disconnection
handling, and reconnect-on-demand. It must not silently substitute static data
after Shizuku stops. A custom Shizuku UserService is an alternative if rish's
stream behavior proves unsuitable; it can return bytes or a pipe rather than the
original protected FD.

The earlier [tx-cpu script][tx-cpu] instead loops copying `/proc/stat` into
`/data/local/tmp/stat`, and patches htop's input path. It establishes the
privileged-read idea, but its autonomous copying model is not the chosen design.
The existing repository copier was used briefly to test Rust's `std::fs` reads
and the preload shim, then stopped. Those diagnostic results (`temp/docs/evidence/procstat-investigation/native-result.txt`)
do not make that copier part of the recommendation.

## Mission Center port boundary

The previous [Mission Center assessment](termux-mission-center-assessment.md)
and [migration measurements](termux-native-migration.md#whole-device-cpu-counters-through-shizuku)
show the application already ran under the forked PRoot with real counters, but
that arrangement cost about 65% of one core, including about 24% for its PRoot
tracer. Those measurements do not establish native performance, nor justify
rejecting a native build. The current desktop monitor selection is unchanged.

For the previously pinned Mission Center 1.2.0 release (`193e3729`) and Magpie
(`a5272b3c`), there are two direct `/proc/stat` reads:

| Source | Purpose | Native change |
| --- | --- | --- |
| [Magpie `platform-linux/src/util.rs`][magpie-util], `cpu_count()` | Counts core rows once and caches the result | Obtain the initial snapshot from the request reader |
| [Magpie `platform-linux/src/cpu/mod.rs`][magpie-cpu], `CpuCache::refresh()` | Calculates overall and per-core usage from tick deltas | Request a fresh snapshot at the existing CPU refresh |

Both should use one shared source abstraction, with normal Linux reads as the
default and the Shizuku transport selected for this Android build. Preserve raw
kernel counters and the existing delta calculations. A separate periodic copier,
sysfs-based reconstruction, and Termux-wide syscall interception are unnecessary
for this port. A returned snapshot remains a sample, not a grant of kernel-file
access to every native program.

There are additional native build obstacles, independently of `/proc/stat`:

- Magpie's [Cargo manifest][magpie-cargo] and `src/main.rs` enable its platform
  backend only for `target_os = "linux"`. Termux's Rust compiler reports
  `target_os = "android"`. Android support must be added consistently.
- The pinned backend calls `libc::__errno_location()` in `util.rs` and
  `cpu/system.rs`; this phone's Bionic libc exports `__errno` instead. These
  calls require Android handling.
- The backend [build script][magpie-build] unconditionally builds NVTOP and probes
  libudev. This phone has libdrm and GBM but no `libudev.pc`. GPU collection needs
  an Android-compatible dependency or an explicitly disabled backend, followed
  by a broader native-dependency audit.
- GTK 4.24.1 and libadwaita 1.10.0 are installed. They satisfy the pinned GUI's
  GTK `gnome_50` and libadwaita 1.9 requirements. GNOME Shell itself need not be
  upgraded to port this application. [GUI requirements][mc-cargo]
- Process enumeration, control, sysfs telemetry and optional desktop services
  retain Android's restrictions. Whole-device CPU counters do not grant access
  to all Android processes or hardware services.

The practical next implementation is to port/build **Magpie first**, add the
request transport, and validate CPU data against controlled Termux workloads.
Then build the GUI and benchmark the complete native application. Pin matching
GUI/collector sources and their protocol; do not mix an arbitrary old GUI with a
new collector. An older release is worth considering only if the current native
build proves disproportionately expensive; it would need its own source audit.
Returning to PRoot would restore the known tracing cost.

## Scope and reproducibility

The investigation added diagnostic sources, logs and this report. It did not
install Shizuku+, rebuild Termux, alter SELinux, switch the desktop monitor, or
install a Mission Center package. Test readers were stopped. The request probe
can be reproduced with the evidence instructions (`temp/docs/evidence/procstat-investigation/README.md`).

Also inspected: Mission Center development commit
`7a8636778b95353b0195ff2d71940d10684390a6`, its Magpie submodule
`a52005279e157566d88cb082e0d9776d508b047d`, and ShizukuPlus-API
`e7d1773f8800daf1f39193965d26944cf31f3e98`. The two `/proc/stat` reads and the
Android/backend issues above were checked against the pinned release as well.

[shizuku-api]: https://github.com/RikkaApps/Shizuku-API/tree/a27f6e4151ba7b39965ca47edb2bf0aeed7102e5#differents-of-the-privilege-betweent-adb-and-root
[rish]: https://github.com/RikkaApps/Shizuku-API/blob/a27f6e4151ba7b39965ca47edb2bf0aeed7102e5/rish/README.md
[storage]: https://github.com/thejaustin/ShizukuPlus/blob/82706fab604de910454b66d8dca524ea1b0106ab/server/src/main/java/rikka/shizuku/server/StorageProxyImpl.kt#L25
[hooks]: https://android.googlesource.com/kernel/common/+/4cdd5f9186bbe80306e76f11da7ecb0b9720433c/security/selinux/hooks.c#2085
[su-bridge]: https://github.com/thejaustin/ShizukuPlus/wiki/Root-Compatibility-Hub
[tx-cpu]: https://github.com/Welpyes/tx-cpu/blob/526695094175b8ebf7d08fc49c0e24a2df2c804d/script.sh
[mc-cargo]: https://gitlab.com/mission-center-devs/mission-center/-/blob/193e3729367035cf184da004c3246efe79d5c53e/Cargo.toml
[magpie-util]: https://gitlab.com/mission-center-devs/gng/-/blob/a5272b3c1d853caa4044b737cf49257bfc4c86f2/platform-linux/src/util.rs
[magpie-cpu]: https://gitlab.com/mission-center-devs/gng/-/blob/a5272b3c1d853caa4044b737cf49257bfc4c86f2/platform-linux/src/cpu/mod.rs
[magpie-cargo]: https://gitlab.com/mission-center-devs/gng/-/blob/a5272b3c1d853caa4044b737cf49257bfc4c86f2/Cargo.toml
[magpie-build]: https://gitlab.com/mission-center-devs/gng/-/blob/a5272b3c1d853caa4044b737cf49257bfc4c86f2/platform-linux/build.rs
