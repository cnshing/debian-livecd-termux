"""Device-selected Android output for the desktop's private PulseAudio server."""
import json
import os
from pathlib import Path


def server(config, socket, inherited=None):
    path = Path(config) / 'audio.json'
    settings = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(settings, dict):
        raise ValueError('audio.json must contain an object')
    backend = settings.get('backend', 'sles')
    if backend not in ('sles', 'aaudio'):
        raise ValueError('audio.json backend must be sles or aaudio')
    env = dict(os.environ if inherited is None else inherited)
    env.pop('PULSE_SERVER', None)
    command = ['pulseaudio']
    prefix = settings.get('server_prefix')
    if prefix:
        prefix = Path(prefix)
        if not prefix.is_absolute():
            raise ValueError('audio.json server_prefix must be absolute')
        modules = prefix / 'lib/pulseaudio/modules'
        for item in (prefix / 'bin/pulseaudio', modules / ('module-' + backend + '-sink.so')):
            if not item.is_file():
                raise ValueError('Missing candidate audio runtime: ' + str(item))
        command = [str(prefix / 'bin/pulseaudio'), '--dl-search-path=' + str(modules)]
        env['LD_LIBRARY_PATH'] = ':'.join([str(prefix / 'lib/pulseaudio'), str(prefix / 'lib'),
                                         env.get('LD_LIBRARY_PATH', '')]).rstrip(':')
    if backend == 'aaudio':
        command.append('--log-level=info')
    sink = 'AAudio_sink' if backend == 'aaudio' else 'OpenSL_ES_sink'
    # A speaker monitor must never become the fallback microphone.
    command += ['--daemonize=no', '--exit-idle-time=-1', '--use-pid-file=no', '-n',
                '--load=module-' + backend + '-sink sink_name=' + sink,
                '--load=module-null-source source_name=android_no_microphone format=s16le rate=48000 channels=1 description="No microphone"',
                '--load=module-native-protocol-unix socket=' + str(socket) + ' auth-anonymous=1']
    return command, env, sink


def expected_sink(config):
    return server(config, '/unused')[2]
