#!/data/data/com.termux/files/usr/bin/python
"""Check how /dev/dri/renderD128 looks to an ordinary program, without a GPU call.

Usage: render-node-compat.py
Prints PASS or FAIL per check and exits 1 if any fail.
"""
import os
import stat
import sys

NODE = '/dev/dri/renderD128'
results = []


def check(label, fn):
    try:
        ok, detail = fn()
    except OSError as exc:
        ok, detail = False, f'{exc.__class__.__name__}: {exc.strerror}'
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} {label}: {detail}")


def device_ok(st):
    return stat.S_ISCHR(st.st_mode) and (os.major(st.st_rdev), os.minor(st.st_rdev)) == (226, 128)


def describe(st):
    return f'{stat.filemode(st.st_mode)} {os.major(st.st_rdev)}:{os.minor(st.st_rdev)}'


def opened():
    fd = os.open(NODE, os.O_RDWR | os.O_CLOEXEC)
    try:
        copy = os.dup(fd)
        try:
            return device_ok(os.fstat(fd)) and device_ok(os.fstat(copy)), describe(os.fstat(copy)) + ' (fstat, dup)'
        finally:
            os.close(copy)
    finally:
        os.close(fd)


def hidden_card():
    try:
        os.stat('/dev/dri/card0')
        return False, 'card0 visible'
    except FileNotFoundError:
        return True, 'card0 hidden'


check('stat', lambda: (device_ok(os.stat(NODE)), describe(os.stat(NODE))))
check('access read/write', lambda: (os.access(NODE, os.R_OK | os.W_OK), 'allowed'))
check('/dev/dri listing', lambda: (sorted(os.listdir('/dev/dri')) == ['renderD128'], ' '.join(sorted(os.listdir('/dev/dri')))))
check('display controller hidden', hidden_card)
check('open, fstat and dup', opened)
check('/sys/class/drm listing', lambda: ('renderD128' in os.listdir('/sys/class/drm'), ' '.join(os.listdir('/sys/class/drm'))))
check('/sys/dev/char/226:128 is a DRM device', lambda: (os.path.isdir('/sys/dev/char/226:128/device/drm'), 'device/drm present'))
check('platform subsystem', lambda: (os.path.basename(os.path.realpath('/sys/dev/char/226:128/device/subsystem')) == 'platform',
                                    os.path.realpath('/sys/dev/char/226:128/device/subsystem')))
check('device uevent', lambda: ('OF_FULLNAME=' in open('/sys/class/drm/renderD128/device/uevent').read(), 'OF_FULLNAME present'))
sys.exit(0 if all(results) else 1)
