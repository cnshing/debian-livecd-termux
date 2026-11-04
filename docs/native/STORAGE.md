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

Open these locations using Nautilus's Ctrl+L. The standard Termux links do not
establish GNOME removable-volume detection, automatic sidebar entries or eject
support: the upstream GVfs build disables UDisks2.

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

For network shares, see [LAN hostname resolution](LAN-HOSTNAMES.md).
