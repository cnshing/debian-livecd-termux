#!/usr/bin/env python3
"""Note10+/Android acceptance for Bluetooth auto mode. PCM is counted and discarded.

Run in Termux with the desktop running, headset connected, and both mic controllers off:
  python tests/mic/test-bluetooth-auto-device.py [--controller PATH]
Requires cork-recorder.py beside this script. Creates only its own recording/playback clients.
"""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time


def run(*arguments):
    result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=50)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def eventually(check, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (RuntimeError, TimeoutError):
            pass  # Route setup can temporarily occupy the controller's command loop.
        time.sleep(0.1)
    raise AssertionError('Timed out waiting for route transition')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', default='android-pulseaudio-bluetooth')
    args = parser.parse_args()
    prefix = Path(os.environ.get('PREFIX', '/data/data/com.termux/files/usr'))
    os.environ.setdefault('PULSE_SERVER', f'unix:{prefix}/tmp/livecd-host/pulse.sock')

    def command(*arguments):
        return json.loads(run(sys.executable, args.controller, *arguments)) if '/' in args.controller else \
               json.loads(run(args.controller, *arguments))

    def route(active):
        def ready():
            state = command('status')
            return state if state.get('route_active') == active else None
        state = eventually(ready)
        android = command('devices')
        assert android['sco_on'] == active, (state, android)
        sources = run('pactl', 'list', 'short', 'sources')
        assert 'android_bluetooth_input\t' in sources, sources
        assert ('android_bluetooth_capture\t' in sources) == active, sources
        return state

    def reply():
        assert select.select([recorder.stdout], [], [], 12)[0], 'No recorder response'
        line = recorder.stdout.readline()
        assert line, 'Recorder exited unexpectedly'
        return json.loads(line)

    def cork(value):
        recorder.stdin.write('c\n' if value else 'u\n')
        recorder.stdin.flush()
        result = reply()
        assert result['corked'] == value, result
        return result

    assert not command('status').get('active'), 'Stop the existing Bluetooth controller first'
    assert json.loads(run('android-pulseaudio-mic', 'status'))['microphone'] == 'off', 'Turn phone mic off first'
    assert not command('devices')['sco_on'], 'An Android call route is already in use'
    original = {kind: run('pactl', f'get-default-{kind}') for kind in ('source', 'sink')}
    recorder = playback = second = None
    started = False
    try:
        command('auto', '--default')
        started = True
        route(False)
        assert run('pactl', 'get-default-sink') == original['sink']
        with open('/dev/zero', 'rb') as silence:
            playback = subprocess.Popen(['pacat', '--playback', '--raw', '--latency-msec=20'],
                stdin=silence, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        eventually(lambda: json.loads(run('pactl', '--format=json', 'list', 'sink-inputs')))
        playback_id = next(item['index'] for item in json.loads(run('pactl', '--format=json', 'list', 'sink-inputs'))
                           if item['properties'].get('application.process.id') == str(playback.pid))

        def playback_sink():
            inputs = json.loads(run('pactl', '--format=json', 'list', 'sink-inputs'))
            sinks = json.loads(run('pactl', '--format=json', 'list', 'sinks'))
            stream = next(item for item in inputs if item['index'] == playback_id)
            return next(sink['name'] for sink in sinks if sink['index'] == stream['sink'])

        recorder = subprocess.Popen([sys.executable, str(Path(__file__).with_name('cork-recorder.py')),
            'android_bluetooth_input'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert reply()['corked']
        route(False)
        print(json.dumps({'check': 'enumerated-without-SCO', 'passed': True}), flush=True)
        for cycle in range(2):
            cork(False)
            route(True)
            assert playback_sink() == 'android_bluetooth_output'
            time.sleep(1)
            levels = cork(True)
            assert levels['bytes'] > 0, levels
            route(False)
            assert playback_sink() == original['sink']
            assert run('pactl', 'get-default-sink') == original['sink']
            print(json.dumps({'check': 'uncork-capture-cork-media', 'cycle': cycle,
                              'passed': True, 'discarded_bytes': levels['bytes']}), flush=True)
        cork(False)
        route(True)
        second = subprocess.Popen(['parec', '--raw', '--device=android_bluetooth_input'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        source_id = next(item['index'] for item in json.loads(run('pactl', '--format=json', 'list', 'sources'))
                         if item['name'] == 'android_bluetooth_input')
        eventually(lambda: len([item for item in json.loads(run('pactl', '--format=json', 'list', 'source-outputs'))
                               if item['source'] == source_id]) == 2)
        cork(True)
        assert command('status')['route_active'], 'First client closed the second client\'s route'
        second.terminate()
        second.wait(timeout=5)
        route(False)
        print(json.dumps({'check': 'last-recorder-releases-SCO', 'passed': True}), flush=True)
    finally:
        for child in (recorder, second, playback):
            if child is not None and child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
        if recorder is not None:
            recorder.stdin.close()
            recorder.stdout.close()
        if started:
            command('off')
    assert not command('devices')['sco_on']
    assert {kind: run('pactl', f'get-default-{kind}') for kind in original} == original
    print(json.dumps({'check': 'off-restores-defaults', 'passed': True}), flush=True)


if __name__ == '__main__':
    main()
