// Profile-specific replacement for the bundled recursive GTK4 copier.
// Existing user GTK4 CSS is never overwritten or removed.
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export default class Appearance extends Extension {
    enable() {
        this.settings = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
        this.shellTheme = new Gio.Settings({schema_id: 'org.gnome.shell.extensions.user-theme'});
        this.previous = ['gtk-theme', 'icon-theme'].map(key => this.settings.get_string(key));
        this.previousShell = this.shellTheme.get_string('name');
        this.ids = ['accent-color', 'color-scheme'].map(key =>
            this.settings.connect(`changed::${key}`, () => this.update()));
        this.update();
    }

    update() {
        const dark = this.settings.get_string('color-scheme') === 'prefer-dark';
        const accent = this.settings.get_string('accent-color');
        const color = {blue: '-blue', teal: '', green: '-green', yellow: '-yellow',
            orange: '-orange', red: '-red', pink: '-pink', purple: '-purple', slate: '-grey'}[accent] ?? '-blue';
        const theme = `WhiteSur-${dark ? 'Dark' : 'Light'}-solid${color}-nord`;
        const root = GLib.build_filenamev([GLib.get_user_data_dir(), "themes", theme]);
        if (!GLib.file_test(root, GLib.FileTest.IS_DIR))
            return;
        this.settings.set_string('gtk-theme', theme);
        this.shellTheme.set_string('name', theme);
        // Upstream assets use uppercase suffixes, unlike the liveCD's PPA.
        const iconColor = {blue: '', teal: '-Teal', green: '-Green', yellow: '-Yellow', orange: '-Orange',
            red: '-Red', pink: '-Pink', purple: '-Purple', slate: '-Grey'}[accent] ?? '';
        const scheme = dark ? 'Dark' : 'Light';
        let icons = `Colloid${iconColor}-${scheme}`;
        // Installs from before every color was included have only the default and yellow.
        if (!GLib.file_test(GLib.build_filenamev([GLib.get_user_data_dir(), 'icons', icons]), GLib.FileTest.IS_DIR))
            icons = `Colloid-${scheme}`;
        this.settings.set_string('icon-theme', icons);
        const ownedDir = GLib.build_filenamev([GLib.get_user_config_dir(), 'livecd']);
        GLib.mkdir_with_parents(ownedDir, 0o700);
        const owned = `${ownedDir}/gtk4.css`;
        GLib.file_set_contents(owned, `@import url("${root}/gtk-4.0/gtk.css");\n`);
        const dir = GLib.build_filenamev([GLib.get_user_config_dir(), 'gtk-4.0']);
        GLib.mkdir_with_parents(dir, 0o700);
        const link = Gio.File.new_for_path(`${dir}/gtk.css`);
        try {
            const info = link.query_info('standard::is-symlink,standard::symlink-target', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
            // An existing user's CSS wins, including a broken unrelated symlink.
            if (!info.get_is_symlink() || info.get_symlink_target() !== owned)
                return;
        } catch (error) {
            if (!error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
                throw error;
            link.make_symbolic_link(owned, null);
        }
        this.ownedLink = link;
        this.ownedTarget = owned;
    }

    disable() {
        this.ids.forEach(id => this.settings.disconnect(id));
        // Only delete a symlink still pointing to the exact profile-owned file.
        if (this.ownedLink) {
            try {
                const info = this.ownedLink.query_info('standard::is-symlink,standard::symlink-target', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
                if (info.get_is_symlink() && info.get_symlink_target() === this.ownedTarget)
                    this.ownedLink.delete(null);
            } catch (error) {
                if (!error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
                    console.error(error);
            }
        }
        ['gtk-theme', 'icon-theme'].forEach((key, i) => this.settings.set_string(key, this.previous[i]));
        this.shellTheme.set_string('name', this.previousShell);
        this.settings = this.shellTheme = this.ownedLink = null;
    }
}
