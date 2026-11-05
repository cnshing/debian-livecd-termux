# Shared resource backend verification

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

Tested on the established arm64 Galaxy Note10+, Android 11, with
SELinux enforcing and the existing authorized Shizuku+ installation. The native
clients retained the Termux app UID; the fixed reader ran as shell (2000).
No root, PRoot, APK patch or SELinux modification was used.

## Results

| Check | Result |
|---|---|
| Native shared library, broker, compatibility layer and helper | Built and installed with Termux clang/Rust |
| Transport suite | 12 passed: framing, checksum, binary NULs, errors, timeout, EOF and command rejection |
| Held CPU descriptor and stdio stream | Counters advanced after `lseek` and `rewind`; duplicate descriptors worked |
| Retained PID descriptors | Process ticks refreshed after the originating enumeration closed; directory UID remained correct |
| Standard process paths | `/proc` enumeration, `dup` + `fdopendir`, relative `openat`, directory UID metadata and task paths passed |
| Inaccessible files | Process environment remained inaccessible; a missing PID failed without poisoning the next CPU read |
| Fork after first API use | Child successfully opened fresh CPU counters |
| Thermal paths | 65 sensor type files read through the usual sysfs paths |
| Ordinary libgtop client | Unchanged API reported eight CPUs, advancing counters, over 700 processes and PID 1 runtime |
| Stock procps `ps` | Over 700 processes, including init and system_server |
| Stock Android `top` | Over 700 processes across two refreshes, genuine nonzero CPU utilization |
| Stock Termux `htop` | Android processes and threads, eight online CPU meters, multiple refreshes and clean exit |
| Rebuilt Magpie, shared API | CPU/RSS workload, eight cores, system process visibility, CPU/GPU temperatures and KGSL model passed |
| Native process control | SIGSTOP froze the owned workload, SIGCONT resumed it, SIGTERM ended it |
| Installed Mission Center | GUI remained live on a private X display and D-Bus session, without proc interception or CPU-counter errors |
| Desktop environment construction | Missing-package behavior, preload preservation, deduplication and explicit opt-out checked on the host |
| Recipes and host checks | Mission Center patch applies; dependency plan builds resources first; C warning checks, shell syntax and Python compilation passed |

The controlled Magpie workload reached approximately 99.5–99.9% of a core and
36.3 MB RSS. Its first CPU sample established a zero baseline, then subsequent
samples reported genuine device/per-core deltas. Missing instantaneous KGSL clock
and utilization remained unavailable, as before.

## Efficiency and lifecycle

Two independent native API clients shared exactly one shell reader. The Shizuku
Java client was gone after startup. With both clients connected but issuing no
requests for five seconds, the reader added **zero CPU ticks** and its complete
I/O counters stayed unchanged. It blocked in `wait_woken` on the socket. Its RSS
after process/thread batches was **1,656 KiB** in the final lifecycle run.

Single observations from that run, not statistical benchmarks:

| Request | Size | Latency |
|---|---:|---:|
| Initial CPU sample, including Shizuku launch | 1,981 bytes | 415 ms |
| Warm CPU sample | 1,981 bytes | 0.67 ms |
| Mission Center process batch | 292,804 bytes | 37 ms |
| Full compatibility process batch | 1,380,228 bytes | 90 ms |
| Compact thread batch | 1,291,153 bytes | 98 ms |
| GPU/thermal telemetry | 2,671 bytes | 8.6 ms |

Killing only the test reader surfaced an error in about 1.5 ms. An explicit later
request reconnected in about 424 ms. Closing the first client preserved the
second client's reader; closing the last client ended it. The broker remained
idle for future clients. There is no autonomous sampler, idle retry timer or
statistics file copier.

## Reproduce

Build and set up the package as described in the [README](README.md). On the
phone, from the checkout (the C probes assume this eight-core rig):

```sh
cargo test --locked --manifest-path tests/mission-center/source/Cargo.toml
clang -O2 tests/resources/compat-probe.c -o "$TMPDIR/resource-compat-probe"
android-procfs-run "$TMPDIR/resource-compat-probe"
clang -O2 tests/resources/gtop-probe.c $(pkg-config --cflags --libs libgtop-2.0) \
  -o "$TMPDIR/resource-gtop-probe"
android-procfs-run "$TMPDIR/resource-gtop-probe"
python tests/resources/test-apps.py
python tests/resources/test-mission-center.py
```

The libgtop probe needs its development files. The GUI smoke test needs Xvfb and
xdotool; it creates and removes its own display and bus. The Magpie backend test
uses [the existing native probe](../../tests/mission-center/native-probe.rs) in
the pinned collector workspace, with its owned C workload.

On the PC, with the established SSH/ADB rig and other resource clients closed:

```sh
python3 tests/resources/test-broker.py
```

This test kills only its own reader, never the Shizuku service. Raw output and
installed artifact hashes are in the evidence directory (`temp/docs/evidence/resources`).

## Scope remaining

The complete desktop has not been restarted with the new automatic preload;
its environment construction is checked, and the individual consumers above
were run through the wrapper. The currently running source-port desktop was
left undisturbed. This version of the controller must be installed for the new
session integration to take effect.

The new recipes have not run in the CI cross-compiler or produced a release.
Other Android devices/versions, application sandboxes, static/direct-syscall
programs, every procfs operation and long-running concurrent monitor workloads
have not been validated. These tests establish the implemented native path and
idle behavior, not universal kernel access or a battery-life measurement.
