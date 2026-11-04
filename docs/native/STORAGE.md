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

## Automatic Files sidebar entries

The File Manager overlay starts `storage-bookmarks.py --watch` with the native
desktop. It checks Android's mount table and directory access every three
seconds and maintains **Internal storage**, **SD card**, and **USB drive**
bookmarks in Files. Unidentified removable devices use **Removable storage**;
multiple devices of the same kind receive distinct labels. Cards point to the
whole readable volume, not just Termux's app directory.

Entries appear when a readable volume is present and disappear after removal
or loss of access. Android must already have mounted the volume and granted
Termux access. The helper does not request permissions or mount devices itself.
USB behavior depends on Android exposing an accessible mount path.

Custom bookmarks are preserved. Existing bookmarks to the same location are
reused without duplication. Only exact entries recorded as helper-owned are
removed; renaming a generated bookmark makes it a custom bookmark. Updates use
GIO's file version check to retry concurrent edits made in Files. The helper
writes only when entries change.

Bookmarks live in the native profile's `gtk-3.0/bookmarks`, with ownership data
under its XDG state directory. A single watcher runs per desktop session and
inherits its process ownership tag for cleanup. Android remains responsible for
ejecting/unmounting storage; the bookmarks do not provide an eject control.

The helper and its autostart entry install through the File Manager overlay;
no GVfs rebuild is needed. To refresh an installed profile immediately:

```sh
livecd-native exec -- python "$HOME/.local/lib/livecd-native/storage-bookmarks.py"
```

This returns without starting a second helper when the watcher is already active.
You can also open a storage path directly with Nautilus's Ctrl+L.

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

The automatic sidebar entries were also verified visually in the running Files
application. `tests/native/test-storage-bookmarks.py` passed 17 checks on both
the host and phone, including GIO file persistence, concurrent edits, ownership,
URI escaping, access restrictions, duplicate mount views, device labels, and
simulated removal/reinsertion. Physical card removal and USB insertion were not
performed. Local UI captures are under `temp/storage-sidebar/`.

For network shares, see [LAN hostname resolution](LAN-HOSTNAMES.md).
