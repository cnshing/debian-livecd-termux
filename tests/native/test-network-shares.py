#!/data/data/com.termux/files/usr/bin/python
"""Read-only GIO acceptance check. Run inside livecd-native exec.

SMB_TEST_URI supplies a reachable share. Optional SMB_TEST_USER, SMB_TEST_PASSWORD
and SMB_TEST_DOMAIN supply credentials through the environment. Output contains
only check results; server addresses and directory entries are not printed.
"""
import json
import os
import sys
import time

from gi.repository import Gio, GLib


def mount(file):
    operation = Gio.MountOperation()

    def password(op, message, default_user, default_domain, flags):
        if os.environ.get('SMB_TEST_USER'):
            op.set_username(os.environ['SMB_TEST_USER'])
            op.set_password(os.environ.get('SMB_TEST_PASSWORD', ''))
            op.set_domain(os.environ.get('SMB_TEST_DOMAIN', ''))
        else:
            op.set_anonymous(True)
        op.reply(Gio.MountOperationResult.HANDLED)

    operation.connect('ask-password', password)
    loop = GLib.MainLoop()
    errors = []

    def done(source, result):
        try:
            source.mount_enclosing_volume_finish(result)
        except GLib.Error as error:
            if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                errors.append(error)
        loop.quit()

    cancel = Gio.Cancellable()
    timer = GLib.timeout_add_seconds(30, lambda: (cancel.cancel(), True)[1])
    file.mount_enclosing_volume(Gio.MountMountFlags.NONE, operation, cancel, done)
    loop.run()
    GLib.source_remove(timer)
    if errors:
        raise errors[0]


def entries(uri):
    file = Gio.File.new_for_uri(uri)
    mount(file)
    iterator = file.enumerate_children('standard::name,standard::target-uri', Gio.FileQueryInfoFlags.NONE, None)
    result = []
    try:
        while (item := iterator.next_file(None)) is not None:
            result.append(item)
    finally:
        iterator.close(None)
    return result


def main():
    uri = os.environ.get('SMB_TEST_URI')
    if not uri or not uri.startswith('smb://'):
        raise SystemExit('Set SMB_TEST_URI to an smb://HOST/SHARE location.')
    result = {}
    schemes = Gio.Vfs.get_default().get_supported_uri_schemes()
    result['smb_backend'] = 'smb' in schemes
    result['dnssd_backend'] = 'dns-sd' in schemes
    try:
        entries(uri)
        result['share_directory_readable'] = True
    except GLib.Error as error:
        result['share_directory_readable'] = False
        result['share_error_code'] = error.code
    # The first listing starts gvfsd-dnssd, which fills in as Avahi's browse
    # results arrive; Nautilus watches the location, so poll the same way.
    result['smb_service_discovered'] = False
    deadline = time.monotonic() + 20
    while not result['smb_service_discovered'] and time.monotonic() < deadline:
        try:
            found = entries('dns-sd://local/')
            result['smb_service_discovered'] = any('_smb._tcp' in x.get_name() for x in found)
        except GLib.Error as error:
            result['discovery_error_code'] = error.code
            break
        if not result['smb_service_discovered']:
            time.sleep(2)
    print(json.dumps(result, indent=2))
    return 0 if all(result.get(key) for key in ('smb_backend', 'dnssd_backend',
                   'share_directory_readable', 'smb_service_discovered')) else 1


if __name__ == '__main__':
    sys.exit(main())
