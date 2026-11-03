"""Start installed integrations through their existing controllers."""
import json
import os
from pathlib import Path
import subprocess
import threading

from component import PREFIX, component_environment


class Integrations:
    def __init__(self, env, state, config):
        self.env = component_environment('integrations', inherited=env)
        self.state = state
        self.config = config
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.result = {'phase': 'starting', 'features': {}}
        self.cleanup = []
        self.thread = threading.Thread(target=self.run, name='livecd-integrations', daemon=True)

    def start(self):
        self.thread.start()

    def status(self):
        with self.lock:
            return {**self.result, 'features': dict(self.result['features'])}

    def report(self, name, status, detail=None):
        with self.lock:
            self.result['features'][name] = {'status': status, **({'detail': detail} if detail else {})}

    def phase(self, value):
        with self.lock:
            self.result['phase'] = value

    def enabled(self, name, command):
        if self.stopping.is_set():
            return False
        if self.options.get(name, True) is False:
            self.report(name, 'disabled')
            return False
        if not os.access(PREFIX / 'bin' / command, os.X_OK):
            self.report(name, 'not-installed')
            return False
        self.report(name, 'starting')
        return True

    def command(self, command, *arguments, timeout=45):
        result = subprocess.run([str(PREFIX / 'bin' / command), *arguments],
            env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        self.log.write('$ ' + ' '.join([command, *arguments]) + '\n' + result.stdout + result.stderr)
        self.log.flush()
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip()[-1000:] or
                               f'{command} exited with status {result.returncode}')
        return result.stdout

    @staticmethod
    def owner(command):
        # Both existing controllers publish the PID and its /proc start token.
        try:
            record = Path.home() / '.local/state' / command / 'session.json'
            data = json.loads(record.read_text())
            fields = Path(f'/proc/{int(data["pid"])}/stat').read_text().rsplit(')', 1)[1].split()
            if fields[0] != 'Z' and fields[19] == data['start']:
                return int(data['pid'])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def owns(self, pid):
        try:
            marker = ('LIVECD_NATIVE_SESSION=' + self.env['LIVECD_NATIVE_SESSION']).encode()
            return marker in Path(f'/proc/{int(pid)}/environ').read_bytes().split(b'\0')
        except (OSError, ValueError, TypeError):
            return False

    def bluetooth_state(self):
        return json.loads(self.command('livecd-mic-bluetooth', 'status', timeout=5))

    def microphone(self):
        if not self.enabled('microphone', 'livecd-mic'):
            self.report('bluetooth', 'disabled', 'Microphone integration is disabled or not installed')
            return
        try:
            current = json.loads(self.command('livecd-mic', 'status', timeout=5))
            if current['microphone'] != 'off':
                self.report('microphone', 'reused')
                self.report('bluetooth', 'skipped', 'A microphone is already enabled')
                return
            if self.enabled('bluetooth', 'livecd-mic-bluetooth'):
                try:
                    if self.bluetooth_state().get('active'):
                        self.report('bluetooth', 'reused')
                    else:
                        self.cleanup.append(('bluetooth', self.stop_bluetooth))
                        self.command('livecd-mic-bluetooth', 'on', '--default', timeout=55)
                        self.report('bluetooth', 'started')
                    self.report('microphone', 'bluetooth')
                    return
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                    self.report('bluetooth', 'unavailable', str(error))
            if not self.stopping.is_set():
                self.cleanup.append(('microphone', lambda: self.command('livecd-mic', 'off', timeout=5)))
                self.command('livecd-mic', 'on', timeout=15)
                self.report('microphone', 'started')
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
            self.report('microphone', 'unavailable', str(error))

    def stop_bluetooth(self):
        if self.owns(self.bluetooth_state().get('controller_pid')):
            self.command('livecd-mic-bluetooth', 'off', timeout=25)

    def service(self, name, command, *arguments):
        if not self.enabled(name, command):
            return
        if self.owner(command):
            self.report(name, 'reused')
            return

        def stop():
            if self.owns(self.owner(command)):
                self.command(command, 'stop', timeout=15)

        self.cleanup.append((name, stop))
        try:
            self.command(command, 'start', *arguments)
            self.report(name, 'started')
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            self.report(name, 'unavailable', str(error))

    def run(self):
        with (self.state / 'integrations.log').open('a', buffering=1) as self.log:
            self.log.write('=== desktop integrations start ===\n')
            self.options = {}
            try:
                path = self.config / 'integrations.json'
                if path.exists():
                    self.options = json.loads(path.read_text())
                    if not isinstance(self.options, dict):
                        raise ValueError('Expected an object in ' + str(path))
                self.microphone()
                self.service('audio', 'livecd-audio', '--pulse-server', self.env['PULSE_SERVER'])
                self.service('gsconnect', 'livecd-gsconnect')
                if self.enabled('resources', 'livecd-resources-setup'):
                    try:
                        self.command('livecd-resources-setup', timeout=20)
                        self.report('resources', 'staged')
                    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                        self.report('resources', 'unavailable', str(error))
                self.phase('ready')
                self.stopping.wait()
            except Exception as error:
                self.report('startup', 'unavailable', str(error))
                self.phase('failed')
                self.stopping.wait()
            finally:
                self.phase('stopping')
                for name, stop in reversed(self.cleanup):
                    try:
                        stop()
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                        self.log.write(f'{name} cleanup: {error}\n')
                self.phase('stopped')

    def stop(self):
        self.stopping.set()
        # Let an in-progress existing start command finish, then stop its owner
        # before desktop cleanup removes PulseAudio and the session buses.
        self.thread.join(timeout=110)
        if self.thread.is_alive():
            print('Optional integration shutdown timed out; continuing session cleanup', flush=True)
