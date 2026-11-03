# Privacy and local artifacts

Public documentation keeps reusable setup steps, compatibility details, software
versions, results and limitations. Identifying setup passages have
been removed, including private network endpoints, machine hostnames, personal
home paths, USB serials, installation-specific Android account IDs, local test
dates, session scratchpad paths and patch timestamps that reveal a timezone.

Standard Termux paths, loopback addresses, protocol ports, Android's standard
shell UID, extension IDs, upstream source links and required attribution remain.
These describe functionality or provenance shared by other users. Note10+ model,
SoC, GPU, Android and kernel details remain because they define the target device.
Upstream release dates, required license attribution, project source URLs and
synthetic test fixtures remain; local collection dates are omitted from reports.

## Local artifacts

Raw captures and session notes were moved under `temp/`, preserving their
relative paths. This directory is ignored by Git and can be deleted manually.
Its files retain their original contents and may still include identifying data.

| Local path | Contents |
| --- | --- |
| `temp/docs/evidence/` | Device logs, screenshots, raw results and diagnostic files |
| `temp/` | The removed `legacy/` and `gnome-48-port/` folders and PRoot docs, including source-port runtime captures |
| `temp/CLAUDE-HANDOFF*.md` | Session handoff notes |
| `temp/docs/proot/HANDOFF.md` | Historical PRoot session handoff |
| `temp/docs/phone-test-rig.md` | Original local setup record |
| `temp/docs/native/LAN-HOSTNAMES.md` | Original local network investigation |

Public reports summarize the results and refer to optional raw captures using
plain `temp/` paths. Raw captures are not included with a fresh checkout and are
not needed to install the desktop or run the maintained test harnesses. Captured
source hashes describe the original test inputs; privacy edits do not establish
a new device acceptance run.

The old raw-capture locations and root handoff names are also ignored to keep
new session output out of commits. Existing ignored build caches, compiled
packages and `.backup/` archives remain local and were not sanitized.

## Device selection

Host helpers use `PHONE_SERIAL`, then `ANDROID_SERIAL`, then ADB's normal
single-device selection. Set these variables in your shell instead of recording
a device identifier in source. See the [rig guide](phone-test-rig.md).

Save new raw diagnostics under `temp/`. Review summaries before sharing them;
keep private keys, pairing codes, tokens and personal device captures local.
