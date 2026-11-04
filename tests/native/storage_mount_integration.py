"""Exercise the GVfs proxy protocol on a disposable session bus and fixture dirs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROVIDER = '''import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from gi.repository import Gio,GLib
from monitor import StorageMonitor,NAME
fixture,counter=map(Path,sys.argv[2:])
def scan(_):
    count=int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(count+1))
    return json.loads(fixture.read_text())
connection=Gio.bus_get_sync(Gio.BusType.SESSION,None)
server=StorageMonitor(connection,scan=scan)
watch=Gio.File.new_for_path(str(fixture)).monitor_file(0,None)
watch.connect('changed',lambda *args:server.refresh())
loop=GLib.MainLoop()
owner=Gio.bus_own_name_on_connection(connection,NAME,0,None,lambda *args:loop.quit())
try:loop.run()
finally:
    Gio.bus_unown_name(owner)
    watch.cancel()
    server.close()
'''

CLIENT = '''import json,os,sys
from pathlib import Path
from gi.repository import Gio,GLib
stage=Path(sys.argv[1])
initial=(stage/'internal').as_uri()
card=(stage/'card').as_uri()
fixture=stage/'fixture.json'
monitor=Gio.VolumeMonitor.get()
def mounts():
    return {m.get_root().get_uri():m for m in monitor.get_mounts()
            if (m.get_uuid() or '').startswith('livecd-storage-')}
def wait_for(predicate):
    if predicate():return
    loop=GLib.MainLoop()
    def changed(*args):
        if predicate():loop.quit()
    handlers=[monitor.connect(signal,changed) for signal in ('mount-added','mount-removed','mount-changed')]
    timed_out=[]
    def timeout():timed_out.append(True);loop.quit();return GLib.SOURCE_CONTINUE
    timer=GLib.timeout_add_seconds(8,timeout)
    loop.run()
    GLib.source_remove(timer)
    for handler in handlers:monitor.disconnect(handler)
    assert not timed_out and predicate(),'GIO mount change was not delivered'
wait_for(lambda:initial in mounts())
item=mounts()[initial]
assert item.__gtype__.name=='GProxyMount'
assert item.get_root().is_native()
assert not item.can_unmount() and not item.can_eject()
assert not (stage/'config/gtk-3.0/bookmarks').exists()
# A longer-than-old-poll-interval idle period must not rescan storage.
count=(stage/'counter').read_text()
loop=GLib.MainLoop()
GLib.timeout_add(3500,lambda:(loop.quit(),GLib.SOURCE_REMOVE)[1])
loop.run()
assert (stage/'counter').read_text()==count,'Unexpected periodic mount scan'
fixture.write_text(json.dumps({initial:'Internal storage',card:'SD card'}))
wait_for(lambda:card in mounts())
item=mounts()[card]
identity=item.get_uuid()
iterator=item.get_root().enumerate_children('standard::name',0,None)
assert iterator.next_file(None).get_name()=='fixture.txt'
iterator.close(None)
fixture.write_text(json.dumps({initial:'Internal storage',card:'SD card (TEST-0001)'}))
wait_for(lambda:mounts()[card].get_name()=='SD card (TEST-0001)')
assert mounts()[card].get_uuid()==identity
fixture.write_text(json.dumps({initial:'Internal storage'}))
wait_for(lambda:card not in mounts())
assert initial in mounts()
print(json.dumps({'gio_mounts':True,'native_roots':True,'directory_access':True,
                  'mount_added_changed_removed':True,'no_periodic_scan':True,
                  'no_bookmarks':True,'no_unmount_or_eject':True},indent=2))
'''


def integration(source):
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        for name in ('internal', 'card', 'config', 'monitors', 'share/dbus-1/services'):
            (stage / name).mkdir(parents=True)
        (stage / 'card/fixture.txt').write_text('storage fixture\n')
        (stage / 'fixture.json').write_text(json.dumps({(stage / 'internal').as_uri(): 'Internal storage'}))
        (stage / 'provider.py').write_text(PROVIDER)
        (stage / 'client.py').write_text(CLIENT)
        (stage / 'monitors/livecd-storage.monitor').write_bytes((source / 'livecd-storage.monitor').read_bytes())
        service = ('[D-BUS Service]\nName=org.gtk.vfs.LivecdStorageVolumeMonitor\nExec=' + sys.executable +
                   ' ' + str(stage / 'provider.py') + ' ' + str(source) + ' ' + str(stage / 'fixture.json') +
                   ' ' + str(stage / 'counter') + '\n')
        (stage / 'share/dbus-1/services/org.gtk.vfs.LivecdStorageVolumeMonitor.service').write_text(service)
        env = {**os.environ, 'LIVECD_NATIVE_SESSION': 'storage-test', 'GVFS_DISABLE_FUSE': '1',
               'GVFS_MONITOR_DIR': str(stage / 'monitors'), 'XDG_CONFIG_HOME': str(stage / 'config'),
               'XDG_DATA_DIRS': str(stage / 'share') + ':' + os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share')}
        subprocess.run(['dbus-run-session', '--', sys.executable, str(stage / 'client.py'), str(stage)],
                       env=env, check=True, timeout=35)
