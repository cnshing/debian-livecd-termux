#!/usr/bin/env python3
"""Query native VA decode capabilities using Chromium's explicit dlopen names.

Run in the launcher's VA-API environment. Opens no media and decodes no frames.
This diagnostic does not prove that an advertised hardware decoder works.
"""
import ctypes as c
import json
import os
import sys


def function(library, name, result, *arguments):
    value = getattr(library, name)
    value.restype = result
    value.argtypes = arguments
    return value


def main():
    va = c.CDLL('libva.so.2', mode=c.RTLD_GLOBAL)
    drm = c.CDLL('libva-drm.so.2')
    display_type = c.c_void_p
    integer_pointer = c.POINTER(c.c_int)
    get_display = function(drm, 'vaGetDisplayDRM', display_type, c.c_int)
    initialize = function(va, 'vaInitialize', c.c_int, display_type, integer_pointer, integer_pointer)
    terminate = function(va, 'vaTerminate', c.c_int, display_type)
    max_profiles = function(va, 'vaMaxNumProfiles', c.c_int, display_type)
    max_entrypoints = function(va, 'vaMaxNumEntrypoints', c.c_int, display_type)
    query_profiles = function(va, 'vaQueryConfigProfiles', c.c_int, display_type, integer_pointer, integer_pointer)
    query_entrypoints = function(va, 'vaQueryConfigEntrypoints', c.c_int, display_type, c.c_int,
                                 integer_pointer, integer_pointer)
    fd = os.open(sys.argv[1] if len(sys.argv) > 1 else '/dev/kgsl-3d0', os.O_RDWR | os.O_CLOEXEC)
    display = get_display(fd)
    active = False
    try:
        major, minor = c.c_int(), c.c_int()
        status = initialize(display, c.byref(major), c.byref(minor))
        if status:
            raise RuntimeError('vaInitialize returned ' + str(status))
        active = True
        profiles = (c.c_int * max_profiles(display))()
        count = c.c_int()
        if query_profiles(display, profiles, c.byref(count)):
            raise RuntimeError('vaQueryConfigProfiles failed')
        result = {'libraries_loaded': True, 'va_version': [major.value, minor.value], 'profiles': []}
        for profile in profiles[:count.value]:
            entrypoints = (c.c_int * max_entrypoints(display))()
            entries = c.c_int()
            if query_entrypoints(display, profile, entrypoints, c.byref(entries)):
                raise RuntimeError('vaQueryConfigEntrypoints failed for ' + str(profile))
            result['profiles'].append({'profile': profile, 'entrypoints': list(entrypoints[:entries.value])})
        print(json.dumps(result, indent=2))
    finally:
        if active:
            terminate(display)
        os.close(fd)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(json.dumps({'error': str(error)}))
        sys.exit(1)
