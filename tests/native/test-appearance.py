#!/data/data/com.termux/files/usr/bin/python
"""Exercise the accent extensions' enable/disable and preservation on the running Shell."""
import json
from pathlib import Path
import time
from gi.repository import Gio, GLib

GTK = 'accent-gtk-theme@brgvos'
proxy = Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE,
    None, 'org.gnome.Shell.Extensions', '/org/gnome/Shell/Extensions', 'org.gnome.Shell.Extensions', None)
settings = Gio.Settings.new('org.gnome.desktop.interface')
shell_theme = Gio.Settings.new('org.gnome.shell.extensions.user-theme')
css = Path.home() / '.config/livecd-native/gtk-4.0/gtk.css'


def wait_for(predicate):
    for _ in range(100):
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError('Shell did not reach the requested appearance state')


def switch(enabled, uuid=GTK):
    proxy.call_sync('EnableExtension' if enabled else 'DisableExtension',
        GLib.Variant('(s)', (uuid,)), Gio.DBusCallFlags.NONE, 10000, None)
    def ready():
        entry = proxy.call_sync('GetExtensionInfo', GLib.Variant('(s)', (uuid,)),
            Gio.DBusCallFlags.NONE, 10000, None).unpack()[0]
        return entry.get('state') == (1 if enabled else 2)
    wait_for(ready)


def linked(variant):
    # The extension links GTK 4's user CSS into the selected WhiteSur variant.
    return css.is_symlink() and str(css.readlink()).endswith(f'/{variant}/gtk-4.0/gtk.css')


def main():
    for uuid in (GTK, 'accent-icons-theme@brgvos', 'accent-user-theme@brgvos'):
        entry = proxy.call_sync('GetExtensionInfo', GLib.Variant('(s)', (uuid,)),
            Gio.DBusCallFlags.NONE, 10000, None).unpack()[0]
        assert entry.get('state') == 1, (uuid, entry.get('state'))
    assert css.is_symlink() and str(css.readlink()).endswith('/gtk-4.0/gtk.css'), \
        'Test expects the extension-owned GTK4 link of a fresh profile'
    original = {k: settings.get_string(k) for k in ('accent-color', 'color-scheme')}
    results = {}
    try:
        switch(False)
        assert not css.exists() and not css.is_symlink()
        marker = '/* user CSS must survive extension lifecycle */\n'
        css.write_text(marker)
        switch(True)
        assert css.read_text() == marker and not css.is_symlink()
        switch(False)
        assert css.read_text() == marker
        css.unlink()
        results['regular_user_css_preserved'] = True

        target = '/nonexistent/livecd-user-theme.css'
        css.symlink_to(target)
        switch(True)
        assert str(css.readlink()) == target
        switch(False)
        assert str(css.readlink()) == target
        css.unlink()
        results['unrelated_broken_symlink_preserved'] = True

        switch(True)
        settings.set_string('accent-color', 'red')
        settings.set_string('color-scheme', 'prefer-light')
        wait_for(lambda: linked('WhiteSur-Light-solid-red-nord')
                 and settings.get_string('icon-theme') == 'Colloid-Red-Light'
                 and settings.get_string('gtk-theme') == 'WhiteSur-Light-solid-red-nord'
                 and shell_theme.get_string('name') == 'WhiteSur-Light-solid-red-nord')
        results['light_red_variant'] = settings.get_string('gtk-theme')
        for accent in ('blue', 'teal', 'green', 'yellow', 'orange', 'red', 'pink', 'purple', 'slate'):
            settings.set_string('accent-color', accent)
        settings.set_string('color-scheme', 'prefer-dark')
        settings.set_string('accent-color', 'yellow')
        wait_for(lambda: linked('WhiteSur-Dark-solid-yellow-nord')
                 and settings.get_string('gtk-theme') == 'WhiteSur-Dark-solid-yellow-nord'
                 and settings.get_string('icon-theme') == 'Colloid-Yellow-Dark')
        results['rapid_changes_finish_at_requested_variant'] = settings.get_string('gtk-theme')
        results['result'] = 'PASS'
        print(json.dumps(results, indent=2))
    finally:
        for key, value in original.items():
            settings.set_string(key, value)
        Gio.Settings.sync()


if __name__ == '__main__':
    main()
