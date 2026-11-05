#!/data/data/com.termux/files/usr/bin/python
"""Retire the former sidebar helper while the installer holds the desktop lock."""
import importlib.util
from pathlib import Path

from desktop import PREFIX, environment

path = PREFIX / 'libexec/android-gvfs/migrate.py'
spec = importlib.util.spec_from_file_location('storage_migration', path)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
env = environment()
migration.retire_bookmarks(Path(env['XDG_CONFIG_HOME']), Path(env['XDG_STATE_HOME']), Path.home())
