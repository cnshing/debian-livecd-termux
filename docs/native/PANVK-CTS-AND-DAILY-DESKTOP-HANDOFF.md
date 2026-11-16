# PanVK handoff: daily desktop acceptance and optional broader CTS

State: 2026-11-15. Target: Galaxy S20 `x1s`, Exynos 990, Mali-G77 MC11,
architecture 9, Android vendor `mali_kbase`/ION. This is a practical engineering
handoff. Official certification, Adopter membership and submission paperwork
are outside the user's objective.

## Decision and scope

Full CTS passage is **not a prerequisite for this user's daily desktop use**.
Our recommendation is to qualify the applications and rendering paths actually
used, retain focused regression tests and expand CTS when a failure or feature
change justifies the cost. Full CTS can expose obscure correctness bugs, but
passing it would not replace application and integration testing.

The immediate goal is a dependable desktop with correct pixels, responsive
windows and no reproducible crashes, stale frames or GPU loss in the supported
workloads. Use the description “desktop validated, with selected CTS coverage.”
Keep the exact tested hardware, binaries and modes attached to that claim.
Do not describe unexecuted tests as passing or infer complete API correctness
from a working desktop. Do not raise API versions just to improve the reported
version number.

User constraints persist:

- No further timed soak runs or soak minutes.
- Do not rerun all CTS selections after every proposed fix.
- All driver, CTS and C probe compilation runs in GitHub Actions, not on the
  workstation or phone. Host Python checks and phone test execution are fine.
- Main pushes and CI builds are authorized. This handoff does not itself
  request a new full CTS campaign, runner registration or package promotion.

## Latest measured state and exact identities

The detailed evidence and history remain in
[PANVK-VERSION-BUMP-HANDOFF.md](PANVK-VERSION-BUMP-HANDOFF.md).

| Candidate | What was measured |
| --- | --- |
| `combined-platform`, thirteen patches, both ABIs | 597/597 expanded GLES; Vulkan core/info/ordinary mapping 115 Pass, 9 NotSupported; nested CPU-oracle checks; installed desktop 30/30 in default and nested modes |
| `combined-ahb`, fourteen patches, Bionic only | Exact buffer/image cases 2/2 Pass; dedicated AHB group 12 Pass, 1 NotSupported; imported-image GPU rendering and Android CPU pixel readback Pass; installed desktop 30/30 in default and nested modes |

The latest AHB candidate was built by
[Actions 43692804161](https://github.com/cnshing/debian-livecd-termux/actions/runs/43692804161)
from repository source `ee95158f279de84e0b60734074e4a1aeb61b4104`.
Its Mesa content tree is `b28956ffc095bda26bf8241badba014be178536b`.
Bionic SHA-256:
`134b668a988626a64f01ce8f1c93307a439cf208e47d775a17a42b60358c5758`.
The qualification record was pushed in `a9f32fe`.

Local evidence in the original workspace:
`temp/panvk-qualification/evidence/ahb-focus/checkpoint.json`, with the exact
CTS logs, process-library mappings and installed desktop identities beside it.
Phone files: `~/gpu-x1s/qualification/ahb-focus/`.

Do not transfer the thirteen-patch driver's broader CTS results to the new
fourteen-patch driver. The glibc artifact was not rebuilt for the AHB change.
At the end of that qualification run, the original release controller was
restored by verified hash and its desktop passed 30/30. Other owners may since
have updated installed packages; inspect current state before any next switch.
That AHB qualification did not change normal package pins. The subsequent
installer integration now pins the fourteen-patch pair; see the version
handoff's default-install checkpoint. Final live installer acceptance remains
pending because the phone disconnected before it could run.

The measured blockers have different resolutions:

- Private Android native-buffer extension exposure: corrected for the hybrid
  Termux/X11 ICD. Public AHB remains available.
- ION placed-map SIGBUS: unsafe optional placed mapping withdrawn. This is not
  a kernel fix. Keep uncached coherent-memory and accepted import behavior.
- Linear RGBA AHB image allocation: fixed using read-only legacy Mali gralloc
  metadata. Unknown/compressed, multi-plane and multi-layer layouts are not
  established by those passing tests.
- The remaining AHB NotSupported result is a sequence CTS explicitly excludes
  for Android AHB, not another image allocation failure.

## Recommended daily desktop acceptance

Use one stable candidate per acceptance round. Prioritize:

1. Installed desktop validation with the actual candidate mapped in Shell;
   check the default mode and the opt-in nested mode if both are supported.
2. A short, bounded application check covering GNOME/GTK windows, Nautilus,
   Settings and Ghostty: open/close, resize, maximize/fullscreen and redraw.
   Check pixels or saved captures and reject stale-frame controls. A 30/30
   structural validation is useful but does not substitute for this check.
3. The user's browser workload: page scrolling, canvas/WebGL if used, and video
   presentation. Verify the intended GPU path rather than silently accepting
   a software fallback. Codec acceleration is a separate integration check;
   Vulkan CTS does not certify the VA/MediaCodec/browser pipeline.
4. Focused memory/import, synchronization and rendering controls relevant to
   changes since the last accepted candidate. Investigate reproducible GPU
   loss, crashes, corruption or growing resource use in those bounded checks.
5. Restore the normal desktop after private experiments; record exact hashes,
   mode flags, results and remaining limitations before considering promotion.

The latest AHB candidate has passed the installed checks but has not gained a
new isolated GTK/Ghostty pixel-cycle pass or browser acceptance from that run.
Earlier candidates' app results are useful context, not its own measurements.
The preceding private GTK/Ghostty attempts on `combined-platform` produced
pixel diagnostics but failed isolation because another owner's processes
changed. Do not count them as isolated passes or repeat them blindly while
another private display/test is active.

If these supported workloads pass, a failure confined to an unused optional
feature can be documented and deferred. A failure affecting shared memory
coherence, ordinary drawing or synchronization deserves higher priority even
if discovered by a synthetic test. Optional features can be omitted when
permitted; required API functionality cannot be relabeled optional.

For a normal package update, build and check every ABI being promoted, pin
immutable assets/hashes and provide rollback. Do not publish a mixed pair as
though both came from the fourteen-patch source. See
[PANVK-SOURCE-PACKAGE.md](PANVK-SOURCE-PACKAGE.md).

## Efficient development loop

1. Reproduce the exact failure on the known candidate and save its identity.
2. Build only the affected ABI/change in CI.
3. Run the exact failed case and one nearby control, stopping on failure.
4. Once fixed, expand to the affected group.
5. On the stable candidate, run the appropriate desktop/application acceptance
   once. Repeat broad compute tests only when the change affects compute or
   another concrete concern warrants them.

The AHB iteration demonstrated this approach: the final two cases took 0.894
seconds total; the thirteen affected cases took 6.252 seconds of execution,
excluding discovery. No repeated 597-case compute run or soak was needed.

`tools/panvk-probes/cts/run.py` accepts repeated `--case <exact-name>` and skips
case enumeration. `--pattern` selects a group. The runner retains driver and
CTS hashes, real process mappings, strict QPA matching, memory/time bounds and
stop-on-failure behavior. Diagnostic runs are not release acceptance.

Example, from Termux with private paths set to the intended artifacts:

```sh
exec 9>"$TMPDIR/livecd-fullscreen-test.lock"
flock -w 5 9
python "$runner" --suite vk --cts "$cts_out" --driver "$candidate" \
  --large-workgroups --nested \
  --case dEQP-VK.api.external.memory.android_hardware_buffer.dedicated.buffer.bind_export_import_bind \
  --case dEQP-VK.api.external.memory.android_hardware_buffer.dedicated.image.bind_export_import_bind \
  --out "$fresh_output" --max-seconds 20
```

Use a fresh output directory and the intended mode. Require at least 3 GB
available memory, inspect `temp/PHONE-STATUS`, coordinate the shared device
lock, and preserve other owners' displays/processes. Private desktop harnesses
acquire the shared lock themselves; do not wrap them in another acquisition.
Do not stop a desktop or replace controller files without verified restoration
and coordination with any active package installation or device test.

## What our upstream already tested

Our package's direct source is Zenith's `panvk-kbase-android`, pinned at
`cf70e02b918e1864cbcd746a7fefa57b96c673ce`, a patch/build layer on Mesa.
It includes genuine Vulkan CTS build/run/resume scripts and substantial saved
subset results. Its 41-test PanProbe app is a separate test set, not the full
Khronos suite. See the [pinned README](https://github.com/zenithblue-oss/panvk-kbase-android/blob/cf70e02b918e1864cbcd746a7fefa57b96c673ce/README.md).

A historical [66,796-case report](https://github.com/zenithblue-oss/panvk-kbase-android/blob/cf70e02b918e1864cbcd746a7fefa57b96c673ce/validation/driver-remaining/beta16-device/cts-sync-memory-query-66796.txt)
records 50,415 Pass, 14,302 NotSupported and 2,079 Fail; a
[later report](https://github.com/zenithblue-oss/panvk-kbase-android/blob/cf70e02b918e1864cbcd746a7fefa57b96c673ce/validation/driver-remaining/beta17-device/cts-b17d-52725-nonpass.txt)
also lists failures. These are historical upstream results, not counts for
our current x1s driver. The [saved CTS build identity](https://github.com/zenithblue-oss/panvk-kbase-android/blob/cf70e02b918e1864cbcd746a7fefa57b96c673ce/validation/g615-v11-csf/dxvk/cts-lock.json)
identifies a G615/Poco X6 Pro environment, not this G77/ION phone. This is real
partial CTS coverage, not evidence of a complete passing run on our package.

Mesa's own [support table](https://docs.mesa3d.org/drivers/panfrost.html)
distinguishes hardware and APIs. Coverage or conformance on a different GPU
and kernel backend does not establish correctness of this downstream kbase
port, Android allocator, Termux loader or Zink desktop combination.

## What GitHub Actions can do

| Work | Where it executes |
| --- | --- |
| Build PanVK, CTS and probes; check package hashes/ABI; host tooling tests | GitHub-hosted runners, using existing workflows |
| Run actual Mali rendering, CTS, import/coherence and desktop checks | The real x1s phone, controlled from a machine that can reach it |
| Schedule, dispatch, collect logs and publish a test report | Actions can coordinate this once a device connection is provided |
| Software-renderer reference comparisons | Cloud runners can help; they do not qualify the Mali driver |

Existing workflows are `.github/workflows/panvk-driver.yml` and
`.github/workflows/panvk-cts.yml`. Driver inputs include
`variant=combined-ahb` and `abi=android|glibc|both`; CTS inputs select `deqp-vk`,
`deqp-gles31` or both. These workflows currently **build** artifacts; they do
not automatically execute the tests on x1s.

A practical future setup is an Actions self-hosted runner on a supported local
computer with USB ADB or private SSH access to the phone. Keep compiling in
hosted build jobs; let the local device job download verified artifacts,
execute the bounded selection on the phone and upload evidence. Alternatively,
a hosted job needs an explicitly configured private network route to a device
controller. The phone's LAN address is not directly reachable from a cloud VM.
No public SSH/ADB exposure is needed. GitHub documents both
[hosted VMs](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners)
and [self-hosted hardware access](https://docs.github.com/en/actions/concepts/runners/self-hosted-runners).

An ARM64 hosted runner does not supply a Mali-G77, Android kbase or ION. An
emulator or lavapipe pass cannot validate those hardware-specific paths.
Use one hardware job at a time per phone, a device lease plus the existing
lock, explicit device identity checks and guaranteed owned-process cleanup.
Run device jobs only from trusted code, keep credentials out of artifacts,
and report unavailable devices as unexecuted rather than passed. No device
runner, network route or automatic hardware campaign is created by this doc.

## Optional deeper CTS campaign

Do this only as a separate engineering objective if broader compatibility is
wanted. It is not the daily-desktop release gate and does not include official
certification work.

- Fix the target API/mode, candidate binary hashes and CTS release first.
  Use official mustpass selections as a reproducible coverage reference.
- Start with desktop-relevant drawing, textures, synchronization, memory and
  presentation, then expand coverage. For GL/ES, test Zink separately; Vulkan
  results alone do not establish the translated GL/ES behavior.
- Use bounded, resumable partitions. Record exact selected/executed/missing
  cases, accepted NotSupported reasons, failures and interrupted cases.
- The current runner stops at the first bad case and refuses to resume a
  report containing failures. An unattended failure-inventory campaign needs
  a separate partition/ledger controller; do not claim that the present runner
  already completes a whole failing suite. Stop for GPU loss or unsafe device
  state instead of continuing blindly.
- During fixes, rerun exact cases and affected groups. Only a final campaign
  on fixed artifacts establishes that campaign's complete coverage; results
  from different binaries cannot be combined into one complete passing run.

Next owner: finish the pending normal-install acceptance recorded in the
version handoff, then complete the missing bounded app checks for the promoted
package. Review existing evidence before selecting any further test scope. Do not begin a full mustpass run merely because “full conformance”
was mentioned in the previous discussion.
