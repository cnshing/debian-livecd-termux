# Android shared storage and microSD

The Android 11 Note10+ permits the native Termux desktop to read and write both
internal shared storage and the installed microSD card after granting Termux's
storage permissions. This is device evidence, not a guarantee for other Android
versions, manufacturers, or USB storage devices.

## Set up access

From the connected PC, grant the permissions under Termux's actual app identity:

```sh
adb shell pm grant com.termux android.permission.READ_EXTERNAL_STORAGE
adb shell pm grant com.termux android.permission.WRITE_EXTERNAL_STORAGE
```

Open the Termux Android activity and run `termux-setup-storage` in Termux. The
installed helper sends a broadcast handled by the activity; on this rig the
command returned without creating the links while the activity was not active.
Bringing Termux to the foreground and repeating its storage broadcast created
the links. No desktop restart was needed. If `~/storage` already exists, review
the helper's prompt before rebuilding that directory.

- `~/storage/shared` points to internal shared storage, also called `/sdcard`.
- `~/storage/external-1` points to Termux's app-specific directory on the microSD
  card, under `Android/data/com.termux/files`; it is not the card's root.
- On this Samsung, the card's root under `/storage/<volume-id>` is also readable
  and writable with the granted permissions. Android mounts the card; Nautilus
  does not need to mount it.

## Files sidebar mounts

The File Manager overlay installs `livecd-storage`. GVfs activates its volume
monitor on the native desktop's session bus when an application asks GIO for
mounts. It exposes **Internal storage**, **SD card**, and accessible **USB drive**
locations as `GMount` objects whose roots are Android's existing directories.
These are device/mount entries in Files, not bookmarks. There is no second kernel
mount, bind mount, symlink redirection or filesystem content copying.

The monitor scans on activation, explicit mount-list requests and kernel mount
notifications from `/proc/self/mountinfo`. Its main loop waits for priority/error
readiness on that descriptor; it has no periodic rescan timer. Ordinary file
readability is deliberately excluded to prevent a busy loop. Notifications
produce GIO mount-added, mount-changed and mount-removed signals.

Only mounted, readable storage is exposed. Private runtime views are deduplicated;
unknown hardware uses **Removable storage**, and multiple devices get distinct
labels. Android must already grant Termux access. The provider does not grant
permissions, mount devices or advertise unmount/eject actions. Use Android's
storage controls for removal. Plain `.local` or network-drive resolution is
unaffected.

Setup removes the old bookmark helper and only the exact bookmark entries it
recorded as its own. Custom bookmarks, including renamed generated entries,
remain intact. Migration runs during stopped setup so the retired watcher cannot
write entries back. The new provider requires no autostart entry: D-Bus activates
it on demand, and desktop session cleanup owns its process.

The provider follows GVfs 1.62's remote volume monitor protocol. Its platform
independent recipe installs the service and monitor registration; GVfs continues
to handle network mounts alongside it. Tests must verify the protocol against
actual GIO proxy mount objects when changing GVfs versions.

## Verification

Checks ran through `livecd-native exec -- python`, using the desktop environment
and Termux app identity. Internal shared storage, the microSD app directory and
the microSD root each passed:

1. Directory enumeration through `Gio.File.enumerate_children()`.
2. Creating a uniquely named temporary file.
3. Reading the file back and checking its contents.
4. Deleting the temporary file.

Existing user files were not modified. The granted permissions and generated
storage links remain in place. Local evidence is `temp/storage-dns/results.json`.
USB mass-storage devices and behavior after reboot or card removal were not
tested. These results do not establish Unix executable, symlink or permission
semantics on shared storage.

The mount provider is checked with `tests/native/test-storage-mounts.py`.
The isolated integration test uses a disposable D-Bus session, the real GVfs
proxy module and fixture directories. It checks native-root `GMount` objects,
readable directories, mount-added/changed/removed signals, no periodic rescans,
no bookmark writes and no unsupported eject actions. Scanner and migration tests
cover storage access, duplicate views, device labels, escaped paths and custom
bookmark preservation. Physical card/USB hotplug has not been performed.
On the Android 11 phone, the Actions-built package activated on demand and
reported Internal storage and SD card as real GIO `GProxyMount` objects with
readable native roots. Both directories enumerated successfully. The old helper
process, autostart entry and owned bookmarks were removed; the bookmarks file
was empty while GIO still reported both storage mounts. The provider inherited
the desktop's process ownership tag. Eight scanner/migration checks and the
isolated GIO integration test also passed on the phone.
Local device results are under `temp/storage-mounts/`, including
`device-final.json` and `integration-phone.json`.

For network shares, see [LAN hostname resolution](LAN-HOSTNAMES.md).
