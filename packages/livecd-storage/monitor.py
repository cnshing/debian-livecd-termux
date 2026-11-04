#!/data/data/com.termux/files/usr/bin/python
"""Publish Android's readable directories as GIO mounts on the desktop bus."""
import hashlib
import os
from pathlib import Path

from gi.repository import Gio, GLib

from storage import storage_locations

NAME = 'org.gtk.vfs.LivecdStorageVolumeMonitor'
PATH = '/org/gtk/Private/RemoteVolumeMonitor'
INTERFACE = 'org.gtk.Private.RemoteVolumeMonitor'
MOUNT_TYPE = '(ssssssbsassa{sv})'
LIST_TYPE = '(a(ssssbbbbbbbbuasa{ss}sa{sv})a(ssssssbbssa{ss}sa{sv})a' + MOUNT_TYPE + ')'


def mount_record(uri, label):
    identity = 'livecd-storage-' + hashlib.sha256(uri.encode()).hexdigest()[:20]
    if label == 'Internal storage':
        icon = 'drive-harddisk'
    elif label.startswith('SD card'):
        icon = 'media-flash-sd-mmc'
    else:
        icon = 'drive-removable-media'
    # Android owns the kernel mount. Do not advertise an unmount/eject action.
    return (identity, label, icon, icon + '-symbolic', identity, uri,
            False, '', [], 'livecd-storage-' + label, {})


class StorageMonitor:
    def __init__(self, connection, scan=storage_locations, mountinfo=None):
        self.connection = connection
        self.scan = scan
        self.mountinfo = mountinfo or open('/proc/self/mountinfo')
        self.mounts = {}
        self.node = Gio.DBusNodeInfo.new_for_xml(Path(__file__).with_name('protocol.xml').read_text())
        self.registration = connection.register_object(PATH, self.node.interfaces[0], self.call, None, None)
        self.refresh(emit=False)
        # Only exceptional/priority readiness indicates a mount change. Normal
        # readability is always true for proc files and would cause a busy loop.
        self.channel = GLib.IOChannel.unix_new(self.mountinfo.fileno())
        self.source = GLib.io_add_watch(self.channel, GLib.PRIORITY_DEFAULT,
            GLib.IOCondition.PRI | GLib.IOCondition.ERR | GLib.IOCondition.HUP | GLib.IOCondition.NVAL,
            self.mounts_changed)

    def refresh(self, emit=True):
        self.mountinfo.seek(0)
        locations = self.scan(self.mountinfo.read())
        current = {uri: mount_record(uri, label) for uri, label in locations.items()}
        previous, self.mounts = self.mounts, current
        if emit:
            for uri, record in previous.items():
                if uri not in current:
                    self.signal('MountRemoved', record)
            for uri, record in current.items():
                if uri not in previous:
                    self.signal('MountAdded', record)
                elif record != previous[uri]:
                    self.signal('MountChanged', record)

    def signal(self, member, record):
        self.connection.emit_signal(None, PATH, INTERFACE, member,
                                    GLib.Variant('(ss' + MOUNT_TYPE + ')', (NAME, record[0], record)))

    def mounts_changed(self, channel, condition):
        if condition & (GLib.IOCondition.HUP | GLib.IOCondition.NVAL):
            self.source = 0
            return GLib.SOURCE_REMOVE
        self.refresh()
        return GLib.SOURCE_CONTINUE

    def call(self, connection, sender, path, interface, method, parameters, invocation):
        if method == 'IsSupported':
            invocation.return_value(GLib.Variant('(b)', (bool(os.environ.get('LIVECD_NATIVE_SESSION')),)))
        elif method == 'List':
            invocation.return_value(GLib.Variant(LIST_TYPE, ([], [], list(self.mounts.values()))))
        elif method == 'CancelOperation':
            invocation.return_value(GLib.Variant('(b)', (False,)))
        else:
            invocation.return_dbus_error('org.gtk.vfs.Error.NotSupported',
                                         'Android manages storage mounting and removal.')

    def close(self):
        if self.source:
            GLib.source_remove(self.source)
        self.channel = None
        self.mountinfo.close()
        self.connection.unregister_object(self.registration)


def main():
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()
    monitor = StorageMonitor(connection)
    owner = Gio.bus_own_name_on_connection(connection, NAME, Gio.BusNameOwnerFlags.NONE,
                                         None, lambda *args: loop.quit())
    try:
        loop.run()
    finally:
        Gio.bus_unown_name(owner)
        monitor.close()


if __name__ == '__main__':
    main()
