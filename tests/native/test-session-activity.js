// Run with the GNOME 48 GJS/GI environment used by the native session.
import Shell from 'gi://Shell';

if (!Shell.Global)
    throw new Error('GNOME Shell resources are required');
const {SessionActivityUser, IDLE_THRESHOLD_MS} = await import(
    'resource:///org/gnome/shell/misc/termux/sessionActivity.js');

function assert(condition, message) {
    if (!condition)
        throw new Error(message);
}

class Monitor {
    constructor(idle = 0) {
        this.idle = idle;
        this.serial = 0;
        this.idleWatches = new Map();
        this.activeWatches = new Map();
    }

    get_idletime() {
        return this.idle;
    }

    add_idle_watch_full(threshold, callback, flags) {
        assert(threshold === 60000 && flags !== 0, 'Use uninhibitable session input inactivity');
        const id = ++this.serial;
        this.idleWatches.set(id, callback);
        return id;
    }

    add_user_active_watch(callback) {
        const id = ++this.serial;
        this.activeWatches.set(id, callback);
        return id;
    }

    remove_watch(id) {
        this.idleWatches.delete(id);
        this.activeWatches.delete(id);
    }

    goIdle() {
        this.idle = IDLE_THRESHOLD_MS;
        for (const callback of this.idleWatches.values())
            callback();
    }

    goActive() {
        this.idle = 0;
        const callbacks = [...this.activeWatches.values()];
        this.activeWatches.clear();
        callbacks.forEach(callback => callback());
    }
}

const monitor = new Monitor();
const user = new SessionActivityUser(monitor);
const changes = [];
user.connect('g-properties-changed', () => changes.push(user.IdleHint));
assert(user.State === 'active' && !user.IdleHint, 'Start with an active desktop');
for (let i = 0; i < 3; i++) {
    monitor.goIdle();
    monitor.goIdle();
    assert(monitor.activeWatches.size === 1 && user.IdleHint, 'Only one resume watch while idle');
    monitor.goActive();
    assert(!user.IdleHint && monitor.activeWatches.size === 0, 'Input resumes active accounting');
}
assert(JSON.stringify(changes) === '[true,false,true,false,true,false]', 'Only signal actual state changes');
monitor.goIdle();
user.destroy();
assert(monitor.idleWatches.size === 0 && monitor.activeWatches.size === 0, 'Remove both watches on cleanup');
const initiallyIdle = new Monitor(IDLE_THRESHOLD_MS + 1);
const idleUser = new SessionActivityUser(initiallyIdle);
assert(idleUser.IdleHint && initiallyIdle.activeWatches.size === 1, 'Honor existing inactivity at startup');
initiallyIdle.goActive();
assert(!idleUser.IdleHint, 'Resume when the first event arrives');
idleUser.destroy();
print('PASS: native screen-time activity tracks input, repeated idle/resume, startup idle and watch cleanup');
