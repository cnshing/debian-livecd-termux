'''
Ensures the underlying editor theme is consistent with the current GTK theme.
Regenerates the user's elementary-light/dark editor schemes on launch.
Note: Colors are re-read only at startup; any theme change that occurs while Code is running will require a restart.
'''

'''
This module assumes it is run before the color scheme is read at MainWindow's init_layout(), and it currently does that at libpeas import while the PluginsManager is created.
'''


import os
import re
import subprocess
import sys

STOCK = "/usr/share/gtksourceview-4/styles/elementary-%s.xml"
DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
DATA_DIRS = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
OUT_DIR = os.path.join(DATA_HOME, "gtksourceview-4", "styles")


def theme_css(name, filename):
    for d in [os.path.join(DATA_HOME, "themes"), os.path.expanduser("~/.themes")] + [os.path.join(d, "themes") for d in DATA_DIRS]:
        path = os.path.join(d, name, "gtk-3.0", filename)
        if os.path.isfile(path):
            with open(path) as f:
                return f.read()
    return None


def parse_color(value):
    # NOTE: hex, rgb()/rgba() and white/black only; anything else (@refs, shade(), other names) returns None and that variant falls back to the stock scheme.
    value = {"white": "#ffffff", "black": "#000000"}.get(value.lower(), value)
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value)
    if m:
        h = m.group(1) if len(m.group(1)) == 6 else "".join(c * 2 for c in m.group(1))
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,[^)]*)?\)", value)
    return tuple(min(int(v), 255) for v in m.groups()) if m else None


def theme_colors(css):
    colors = {}
    for key in ("base", "bg", "fg"):
        m = re.search(r"@define-color\s+theme_%s_color\s+([^;]+);" % key, css or "")
        rgb = parse_color(m.group(1).strip()) if m else None
        if rgb is None:
            return None
        colors[key] = "#%02x%02x%02x" % rgb
        colors[key + "_dark"] = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255 < 0.5
    return colors


def write_scheme(variant, colors):
    path = os.path.join(OUT_DIR, "elementary-%s.xml" % variant)
    if colors is None:
        if os.path.exists(path):
            os.remove(path)  # fall back to the stock scheme
        return
    # Syntax colors come from the stock scheme that suits the background to ensure a dark-only theme still gets readable text in "light" mode.
    with open(STOCK % ("dark" if colors["base_dark"] else "light")) as f:
        xml = f.read()
    xml = re.sub(r'id="elementary-[a-z]+"', 'id="elementary-%s"' % variant, xml, count=1)
    xml = re.sub(r'(<style name="text"\s+foreground=)"[^"]*" background="[^"]*"',
                 r'\1"%s" background="%s"' % (colors["fg"], colors["base"]), xml)
    xml = re.sub(r'(<style name="(?:current-line|background-pattern)"\s+background=)"[^"]*"',
                 r'\1"%s"' % colors["bg"], xml)
    xml = re.sub(r'(<style name="line-numbers"\s+foreground="[^"]*" background=)"[^"]*"',
                 r'\1"%s"' % colors["bg"], xml)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write(xml)
    os.replace(path + ".tmp", path)


def sync_schemes():
    name, _, env_variant = os.environ.get("GTK_THEME", "").partition(":")
    if not name:
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                           capture_output=True, text=True)
        name = r.stdout.strip().strip("'") if r.returncode == 0 else ""
    # Mirror GTK: the dark variant loads gtk-dark.css when the theme has one, else gtk.css.
    light_css = theme_css(name, "gtk.css") if name else None
    dark_css = (theme_css(name, "gtk-dark.css") if name else None) or light_css
    if os.environ.get("GTK_THEME"):  # GTK_THEME pins the variant; prefer-dark is ignored
        light_css = dark_css = dark_css if env_variant == "dark" else light_css
    write_scheme("light", theme_colors(light_css))
    write_scheme("dark", theme_colors(dark_css))


def _on_plugins_changed(settings, key):
    # Disabled in Preferences > Extensions: drop the generated schemes so the stock
    # look returns on the next start.
    if "theme_sync" not in settings.get_strv(key):
        write_scheme("light", None)
        write_scheme("dark", None)


try:
    sync_schemes()
    from gi.repository import Gio  # already imported by libpeas' Python loader
    _settings = Gio.Settings.new("io.elementary.code.settings")  # keep a reference
    _settings.connect("changed::plugins-enabled", _on_plugins_changed)
except Exception as e:  # never break Code's startup
    print("theme_sync plugin: skipped: %s" % e, file=sys.stderr)
