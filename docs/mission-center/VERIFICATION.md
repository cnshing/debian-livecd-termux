# Native Mission Center: device verification

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

Verified on the connected Galaxy Note10+ SM-N975U1, Android 11,
ARM64, SELinux enforcing. Shizuku+ 13.6.0.r2551 was already installed and running
as ADB shell. The application and Magpie stay at the Termux app UID; the reader
runs as UID 2000 in the shell SELinux domain.

## Build and installation

Mission Center 1.2.0, Magpie and app-rummage use the exact commits and archive
hashes in [the recipe](../../packages/mission-center/build.sh). Both Rust
lockfiles were retained. Native Rust 1.99.1 built the binaries against GTK
4.24.1, libadwaita 1.10.0 and GLib 2.90.1. Both ELF interpreters are
`/system/bin/linker64`, confirming Android/Bionic binaries.

The resulting `mission-center_1.2.0_aarch64.deb` was installed with `dpkg`,
including the desktop entry, icons, translations, schemas, resources and
licenses. It is available locally under `repo/pool/`; its hash is recorded in
artifact.sha256 (`temp/docs/evidence/mission-center/artifact.sha256`).

The native build and package installation were exercised. GitHub Actions cross
compilation and installation on a fresh phone have not been exercised.

## Results

| Check | Result |
|---|---|
| Genuine CPU counters | Aggregate ticks fall between adjacent ADB reference reads; all eight core rows are received |
| Sampling model | Same persistent reader across requests; idle in `pipe_read` with unchanged I/O counters; no autonomous sampler or copied statistics file |
| Transport tests | Nine native Rust tests pass, including malformed frames, checksum errors, EOF, startup exit and bounded timeout |
| Large snapshots | 100 consecutive complete process snapshots pass validation and checksums |
| Android visibility | Roughly 750–830 accessible processes, including PID 1, kernel threads and `system_server` |
| Per-process CPU/RSS | A disposable busy workload reads about 99–101% of one core and about 36 MB RSS for its 32 MiB allocation |
| Native process control | The collector's SIGSTOP freezes workload ticks; SIGCONT resumes them; SIGTERM exits the workload |
| System RAM | `/proc/meminfo` reports 11,992,125,440 bytes total; the GUI displays about 11.2 GiB plus live available/cache/swap data |
| CPU thermals | Hottest readable CPU/CPUSS sensor is shown; the workload test records the temperature increasing under load |
| GPU identification | KGSL reports `Adreno640v2` and a highest available frequency of 585 MHz |
| GPU utilization | A native Turnip Vulkan cube produces nonzero KGSL busy/total intervals; the collector uses their ratio |
| GPU temperature | Readable GPUSS sensors are displayed; the native probe records about 40 °C in that run |
| Missing reader | GUI explicitly shows CPU counters unavailable and retains no replacement samples |
| Recovery | Restoring the reader reconnects and resumes readings without changing the GUI PID |
| Physical desktop | Native GTK window is visible on Termux:X11 using the existing Zink/Turnip profile |
| Package checks | Recipe patches apply to all hash-verified source archives; shell/Python syntax checks pass |

The CPU workload percentages above use one core as 100%. The GUI can normalize
process percentages across the eight cores according to its existing setting.
Per-process memory is RSS, not PSS; shared pages can appear in multiple processes.

## Transport findings

This installed Shizuku+ rish splits a command's stdout between its local stdout
and stderr. Simply merging those streams reordered large snapshots. The
production reader uses acknowledged 2 KiB writes and an FNV-1a checksum per
frame. Direct `write()` calls are necessary: Bionic split unbuffered `fwrite()`
calls into smaller writes and revived the competing-reader race.

One source mutex serves CPU, process and sensor requests. Failures are shared for
one second, and an established source reconnects with a two-second deadline.
This prevents several categories from serializing long authorization waits
after one connection breaks. The initial authorization deadline is 15 seconds.
The reader performs no work until it receives a request or frame acknowledgment.

The GUI recovery test temporarily renamed only this port's reader, killed its
active instance, captured the unavailable state, restored the file and confirmed
a new reader PID with the same GUI PID. Shizuku itself was not stopped.

## Boundaries

Shell can read more than Termux on this device, but access remains selective.
Current GPU clock reads are denied even as shell. GPU memory, power, per-process
GPU/I/O data and Android PSS are not collected by this adapter. Missing optional
GPU data is not replaced with measured zeroes. An idle KGSL `0 0` response has
no utilization denominator and is displayed as unavailable.

The GPU backend currently supports Qualcomm KGSL. Other vendors need source
adapters. Thermals depend on readable sensor names/units. UDisks disk management
is disabled on Android, and Android services are not mapped to systemd/OpenRC.
Android package grouping/icons are not supplied by the Linux desktop-app matcher;
Android processes remain available in the Processes tree.

Shizuku expands read access through the helper. The GUI's process-control
operations retain native Termux permissions; this test signaled only its own
disposable workload. No APK, SELinux policy, PRoot or Termux-wide syscall shim
was changed or required.

## Runtime cost

Two 60-second runs measured the CPU view at the upstream refresh settings:

| Run | CPU, one core = 100% | Summed RSS |
|---|---:|---:|
| Cairo on native Xvfb | 35.2% | 246 MiB |
| Zink/Turnip on physical Termux:X11 | 28.9% | 295 MiB |

The physical run includes about 18.7% for the GUI, 3.6% for Magpie, 5.2% for the
reader and 1.4% for the rish Java process. The GUI's actual maps and file
descriptors confirm the private Turnip driver and `/dev/kgsl-3d0`.

These sums include the GUI, collector, rish launcher/Java client and reader.
They exclude the shared Shizuku server and compositor. RSS counts shared pages
more than once and is not private memory or PSS. The displays, window sizes and
background work differed, so these are configuration measurements rather than
a controlled renderer comparison. They do not establish battery or power use.
The application still has material overhead despite removing PRoot tracing.

Raw records are performance.json (`temp/docs/evidence/mission-center/performance.json`)
and performance-zink.json (`temp/docs/evidence/mission-center/performance-zink.json`).

## Evidence

See the raw logs and screenshots (`temp/docs/evidence/mission-center/README.md`).
CPU/RAM/process/GPU views and failure recovery were also inspected on an
isolated native Xvfb display using the Cairo renderer. Physical desktop checks
use Termux:X11 and the existing Zink/Turnip configuration.
