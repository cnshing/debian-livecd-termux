# Native Mission Center

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

This port builds Mission Center 1.2.0 and its matching Magpie collector for
native Termux/Bionic. It implements the request-driven design from the
[/proc/stat investigation](../termux-procstat-shizuku-investigation.md).

The GUI and collector run as the Termux UID. CPU, process and sensor reads now
come from the shared [native resource backend](../resources/README.md), rather
than a Mission Center-owned reader or Shizuku connection. Ordinary programs can
use the same backend through their usual `/proc` and supported `/sys` paths.
The backend reads only when a client asks, with no background sampler or copied
statistics file. Normal Linux collection continues to read `/proc/stat` directly.

## Build and run

Build and install an APT-owned package on the phone with the shared Termux builder:

```sh
bash tools/build-packages.sh --install mission-center
# Compatibility entry point: bash packages/mission-center/build-on-device.sh
```

The helper uses the pinned `termux-packages` checkout, builds `livecd-resources`
first, and installs the resulting `.deb` files with APT. Sources and build output
are managed by Termux's builder. `LIVECD_TERMUX_BUILDER` selects an existing
checkout at the pinned revision. See [package building](../structure.md#building-packages).

Shizuku must be running and Termux must be authorized. Export `rish` and its DEX
into `~/.local/lib/shizuku/`, then run:

```sh
livecd-resources-setup
livecd-native exec -- missioncenter
```

For another rish location, set `LIVECD_RESOURCES_RISH` for setup and the first client
that starts the broker. `MC_RISH` remains a fallback for older configurations.
`missioncenter-shizuku-setup` is a compatibility alias. Setup installs
the fixed reader into a private, shell-owned directory under `/data/local/tmp`.
Repeat setup after removing that directory or updating the reader. No Termux
APK patch, PRoot, preload shim, SELinux change, or additional Shizuku APK is used.

The default System Monitor overlay installs the package.

## Supported data and failure behavior

CPU utilization uses genuine aggregate and per-core kernel tick counters and
Magpie's existing delta calculation. The first sample establishes a baseline.
Process enumeration runs as shell and includes accessible Android and system
processes, with CPU tick deltas and resident memory (RSS). RSS is not PSS and
must not be added up as unique device memory. PID start times prevent CPU spikes
when Android reuses a PID. Process control retains native Termux permissions.
The process tree includes every visible root, including PID 1 and kernel threads.
System RAM comes directly from the readable `/proc/meminfo`.

The shared transport bounds Shizuku startup to 15 seconds and an active snapshot
to two seconds, with a 64 KiB CPU limit and an 8 MiB process/sensor limit. Shizuku
starts a fixed native reader, which authenticates to the broker over loopback
with a random token. The Java client then exits. CPU, processes and sensors share
that one native connection across applications. The reader blocks on requests
and exits when its last native client disconnects. See the
[resource backend](../resources/README.md) for protocol, failure and compatibility details.

A transport failure becomes an explicit **CPU counters unavailable** state in the
GUI. Graphs receive no replacement samples during that state. Recovery establishes
a new baseline before calculating another interval. A single inaccessible file
does not invalidate the connection or unrelated categories.

On Qualcomm devices exposing KGSL, GPU collection reads the model, busy/total
ratio, available frequencies and GPU thermal sensors through shell. CPU
temperature is the hottest readable CPU/CPUSS thermal sensor. Missing GPU clock,
memory, power or utilization readings remain unavailable; `gpubusy = 0 0` is
not treated as a measured utilization value. This is a KGSL backend, separate
from Linux's NVTOP/udev backend. Other GPU vendors need their own source adapters.
UDisks disk-management operations and other optional hardware telemetry/system
services remain subject to Android's access restrictions. The Linux additional-setup
dialog is disabled on Android because its group and service changes do not
apply to Termux. Privileged reads expand the displayed process list without
changing the GUI/collector UID or granting native file/control permissions.

The Battery page reads [UPower](../battery/README.md) on the session's system bus,
so it needs Mission Center started inside the session. Magpie's Linux fallback
cannot work here, because Termux may not list `/sys/class/power_supply`. On Android,
Magpie calls `Refresh()` on each update and replaces its previous sample, because
its Linux code keeps the first value of any field that has no sysfs file. Those
reads happen only while Mission Center is open.

[Running Services Monitor](https://github.com/biplobsd/running_services_monitor/tree/772e266fb7dd95c76a64b74d10b33af8b95122ab)
was inspected as a reference. It obtains Android service/LRU information and PSS
through `dumpsys`. This port uses kernel process snapshots for the frequently
refreshed CPU/RSS list, avoiding a complete `dumpsys meminfo` on each refresh.

## Source pins

| Component | Commit |
|---|---|
| Mission Center 1.2.0 | `193e3729367035cf184da004c3246efe79d5c53e` |
| Magpie | `a5272b3c1d853caa4044b737cf49257bfc4c86f2` |
| app-rummage | `26b93b8c6f0de6912f0a17022f7ece76bad87612` |

GUI and collector share the same generated protocol, including the optional
CPU error field added by this port. Install them together.

## Verification

The standalone transport tests run in native Termux:

```sh
cargo test --locked --manifest-path tests/mission-center/source/Cargo.toml
cargo build --locked --manifest-path tests/mission-center/source/Cargo.toml
```

With the established [phone rig](../phone-test-rig.md), stop Mission Center and
run this on the PC to check real counters, idle behavior and reconnect:

```sh
python3 tests/mission-center/test-transport.py
```

To exercise the actual backend, copy
[`native-probe.rs`](../../tests/mission-center/native-probe.rs) into the pinned
Magpie tree as `examples/native-probe.rs`. Compile `workload.c` with native clang,
set `MC_TEST_WORKLOAD` to its absolute path, then run
`cargo run --release --locked --example native-probe`. It creates and cleans up
its own CPU workload and tests the collector's CPU/RSS and signal behavior.

Raw results are recorded in the evidence directory (`temp/docs/evidence/mission-center`).

The [device verification](VERIFICATION.md) records the tested package, native
workload, GUI screenshots, recovery behavior and runtime measurements.

The original [device verification](VERIFICATION.md) records the earlier private
reader. The shared backend's [verification](../resources/VERIFICATION.md) records
the refactor, ordinary Linux tools and the rebuilt Magpie collector.
