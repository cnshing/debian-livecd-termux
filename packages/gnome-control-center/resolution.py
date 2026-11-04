#!/data/data/com.termux/files/usr/bin/python
"""Desktop resolution control using Termux:X11's own preference interface.

The subprocess owns rollback: closing/crashing Settings, a lost pipe or the
confirmation timeout restores the previous preferences without needing GTK.
"""
import json
import os
import re
import select
import subprocess
import sys
import time

KEYS = ('displayResolutionMode', 'displayResolutionCustom')
SIZES = ('1280x720', '1600x900', '1920x1080', '2560x1440')
TIMEOUT = 20


def preferences():
    result = subprocess.run(['termux-x11-preference', 'list'], check=True,
                            capture_output=True, text=True, timeout=10)
    values = dict(re.findall(r'^"([^"\n]+)"="([^"\n]*)"$', result.stdout, re.M))
    if any(key not in values for key in KEYS):
        raise RuntimeError('Termux:X11 did not report its display preferences')
    return {key: values[key] for key in KEYS}


def write_preferences(values):
    if set(values) != set(KEYS):
        raise ValueError('Unexpected display preference')
    result = subprocess.run(['termux-x11-preference', *[key + ':' + values[key] for key in KEYS]],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def target(size, original):
    if size != 'native' and size not in SIZES:
        raise ValueError('Unsupported desktop resolution')
    return {'displayResolutionMode': 'native' if size == 'native' else 'custom',
            'displayResolutionCustom': original['displayResolutionCustom'] if size == 'native' else size}


def watchdog(size):
    original = preferences()
    changed = target(size, original)
    keep = False
    try:
        write_preferences(changed)
        print('applied', flush=True)
        readable, _, _ = select.select([sys.stdin], [], [], TIMEOUT)
        keep = bool(readable and sys.stdin.readline().strip() == 'keep')
    finally:
        if not keep:
            # Preserve a preference change made independently in the Android app.
            if preferences() == changed:
                write_preferences(original)
        print('kept' if keep else 'reverted', flush=True)


def gui():
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gio, GLib, Gtk

    class Resolution(Adw.Application):
        def __init__(self):
            super().__init__(application_id='org.gnome.Settings.DesktopResolution',
                             flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
            self.worker = None
            self.confirmation = None
            self.deadline = 0

        def do_activate(self):
            if hasattr(self, 'window'):
                self.window.present()
                return
            self.window = Adw.ApplicationWindow(application=self, title='Desktop Resolution',
                                               default_width=480, default_height=300)
            toolbar = Adw.ToolbarView()
            toolbar.add_top_bar(Adw.HeaderBar())
            page = Adw.PreferencesPage()
            group = Adw.PreferencesGroup(description='Changes the desktop size. The phone’s display resolution stays unchanged.')
            self.choices = ('native', *SIZES)
            model = Gtk.StringList.new(['Automatic (window size)', *[s.replace('x', ' × ') for s in SIZES]])
            self.row = Adw.ComboRow(title='Resolution', model=model)
            self.status = Gtk.Label(wrap=True)
            self.button = Gtk.Button(label='Apply', halign=Gtk.Align.CENTER)
            self.button.add_css_class('suggested-action')
            self.button.connect('clicked', self.apply)
            group.add(self.row)
            group.add(self.button)
            group.add(self.status)
            page.add(group)
            toolbar.set_content(page)
            self.window.set_content(toolbar)
            self.window.connect('close-request', self.close)
            try:
                values = preferences()
                size = values['displayResolutionCustom'] if values['displayResolutionMode'] == 'custom' else 'native'
                if size in self.choices:
                    self.row.set_selected(self.choices.index(size))
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                self.status.set_label(str(error))
                self.button.set_sensitive(False)
            self.window.present()

        def close(self, *_):
            if self.worker and self.worker.stdin and not self.worker.stdin.closed:
                self.worker.stdin.close()
            return False

        def apply(self, *_):
            size = self.choices[self.row.get_selected()]
            self.button.set_sensitive(False)
            self.row.set_sensitive(False)
            self.status.set_label('Applying…')
            self.worker = subprocess.Popen([sys.executable, os.path.abspath(__file__), '--watchdog', size],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True, start_new_session=True)
            GLib.io_add_watch(self.worker.stdout, GLib.IO_IN | GLib.IO_HUP, self.read_status)

        def read_status(self, source, condition):
            line = source.readline().strip()
            if line == 'applied':
                self.deadline = time.monotonic() + TIMEOUT
                self.confirmation = Adw.AlertDialog(heading='Keep This Resolution?',
                                                   body='The previous resolution will be restored in 20 seconds.')
                self.confirmation.add_response('revert', 'Revert')
                self.confirmation.add_response('keep', 'Keep')
                self.confirmation.set_response_appearance('keep', Adw.ResponseAppearance.SUGGESTED)
                self.confirmation.set_default_response('keep')
                self.confirmation.set_close_response('revert')
                self.confirmation.choose(self.window, None, self.respond)
                return True
            if line in ('kept', 'reverted'):
                if self.confirmation:
                    self.confirmation.close()
                    self.confirmation = None
                self.status.set_label('Resolution saved.' if line == 'kept' else 'Previous resolution restored.')
                self.button.set_sensitive(True)
                self.row.set_sensitive(True)
                self.worker.stdin.close()
                self.worker.wait(timeout=2)
                self.worker = None
                return False
            if not line:
                self.status.set_label('Could not change the desktop resolution.')
                self.button.set_sensitive(True)
                self.row.set_sensitive(True)
                return False
            self.status.set_label(line)
            return True

        def respond(self, dialog, result):
            response = dialog.choose_finish(result)
            self.confirmation = None
            worker = self.worker
            if worker and worker.poll() is None and not worker.stdin.closed:
                try:
                    if response == 'keep' and time.monotonic() < self.deadline:
                        worker.stdin.write('keep\n')
                        worker.stdin.flush()
                    worker.stdin.close()
                except BrokenPipeError:
                    pass

    Resolution().run([sys.argv[0]])


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--watchdog':
        watchdog(sys.argv[2])
    else:
        gui()
