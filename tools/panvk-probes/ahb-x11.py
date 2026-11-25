"""Modifier-1255 transport check, called only inside an owned private X server."""
import ctypes as C
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import time

PTR, U32, U64 = C.c_void_p, C.c_uint32, C.c_uint64
U8, U16, I16 = C.c_uint8, C.c_uint16, C.c_int16


class Screen(C.Structure):
    _fields_ = [('root', U32), ('default_colormap', U32), ('white', U32), ('black', U32),
        ('masks', U32), ('width', U16), ('height', U16), ('width_mm', U16), ('height_mm', U16),
        ('min_maps', U16), ('max_maps', U16), ('visual', U32), ('backing', U8), ('save', U8),
        ('depth', U8), ('depths', U8)]


class Iterator(C.Structure):
    _fields_ = [('data', C.POINTER(Screen)), ('rem', C.c_int), ('index', C.c_int)]


def present(buffer, android, display, desc, record, capture):
    if not re.fullmatch(r':(?:7[4-9]|[89][0-9])', display) or os.environ.get('DISPLAY') != display:
        raise RuntimeError('AHB Present requires the owned private display in :74–:99')
    if not os.environ.get('LIVECD_FULLSCREEN_TEST'):
        raise RuntimeError('Missing private-display ownership marker')
    xcb, dri3, present_lib = (C.CDLL(name) for name in ('libxcb.so', 'libxcb-dri3.so', 'libxcb-present.so'))
    libc = C.CDLL(None)
    libc.free.argtypes, libc.free.restype = [PTR], None
    def fn(lib, name, result, *arguments):
        function = getattr(lib, name)
        function.argtypes, function.restype = arguments, result
        return function
    connect = fn(xcb, 'xcb_connect', PTR, C.c_char_p, PTR)
    disconnect = fn(xcb, 'xcb_disconnect', None, PTR)
    connection = connect(display.encode(), None)
    error = fn(xcb, 'xcb_connection_has_error', C.c_int, PTR)
    flush = fn(xcb, 'xcb_flush', C.c_int, PTR)
    check = fn(xcb, 'xcb_request_check', PTR, PTR, U32)
    def checked(cookie):
        reply = check(connection, cookie)
        if reply:
            try:
                data = C.string_at(reply, 12)
                raise RuntimeError(f'X error {data[1]}, major {data[10]}, minor {struct.unpack_from("=H", data, 8)[0]}')
            finally:
                libc.free(reply)
    try:
        if error(connection):
            raise RuntimeError('Could not connect to private X server')
        for lib, prefix in ((dri3, 'xcb_dri3'), (present_lib, 'xcb_present')):
            cookie = fn(lib, prefix + '_query_version', U32, PTR, U32, U32)(connection, 1, 2)
            reply = fn(lib, prefix + '_query_version_reply', PTR, PTR, U32, PTR)(connection, cookie, None)
            if not reply:
                raise RuntimeError('Missing ' + prefix + ' extension')
            try:
                version = struct.unpack_from('=II', C.string_at(reply, 16), 8)
                record[prefix + '_version'] = list(version)
                if prefix == 'xcb_dri3' and version < (1, 2):
                    raise RuntimeError('DRI3 1.2 is required for modifier 1255')
            finally:
                libc.free(reply)
        setup = fn(xcb, 'xcb_get_setup', PTR, PTR)(connection)
        screens = fn(xcb, 'xcb_setup_roots_iterator', Iterator, PTR)(setup)
        screen = screens.data.contents
        if (screen.width, screen.height) != (desc.width, desc.height) or screen.depth != 24:
            raise RuntimeError('Probe AHB must match the private 24-bit root size')
        new_id = fn(xcb, 'xcb_generate_id', U32, PTR)
        window, pixmap, event_id = [new_id(connection) for _ in range(3)]
        create = fn(xcb, 'xcb_create_window_checked', U32, PTR, U8, U32, U32,
                    I16, I16, U16, U16, U16, U16, U32, U32, PTR)
        override = U32(1)
        checked(create(connection, screen.depth, window, screen.root, 0, 0,
                       desc.width, desc.height, 0, 1, screen.visual, 1 << 9, C.byref(override)))
        checked(fn(xcb, 'xcb_map_window_checked', U32, PTR, U32)(connection, window))
        checked(fn(present_lib, 'xcb_present_select_input_checked', U32,
                   PTR, U32, U32, U32)(connection, event_id, window, 2))
        from_buffers = fn(dri3, 'xcb_dri3_pixmap_from_buffers_checked', U32,
            PTR, U32, U32, U8, U16, U16, *([U32] * 8), U8, U8, U64, PTR)
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        with left, right:
            left.settimeout(3)
            # XCB takes ownership of its duplicate; retain the original for cleanup.
            descriptor = C.c_int32(os.dup(right.fileno()))
            cookie = from_buffers(connection, pixmap, window, 1, desc.width, desc.height,
                desc.stride * 4, 0, 0, 0, 0, 0, 0, 0, 24, 32, 1255, C.byref(descriptor))
            flush(connection)
            if left.recv(1) != b'\x01':
                raise RuntimeError('Server did not request the AHB handle')
            send = fn(android, 'AHardwareBuffer_sendHandleToUnixSocket', C.c_int, PTR, C.c_int)
            result = send(buffer, left.fileno())
            record['ahb_socket_send_result'] = result
            if result:
                raise RuntimeError(f'AHB socket send failed: {result}')
            checked(cookie)
        record['dri3_ahb_imported'] = True
        submit = fn(present_lib, 'xcb_present_pixmap_checked', U32, PTR,
            U32, U32, U32, U32, U32, I16, I16, U32, U32, U32, U32, U64, U64, U64, U32, PTR)
        poll = fn(xcb, 'xcb_poll_for_event', PTR, PTR)
        modes = []
        server_pid = int(os.environ['LIVECD_AHB_SERVER_PID'])
        def cpu_state():
            fields = (Path('/proc') / str(server_pid) / 'stat').read_text().rsplit(')', 1)[1].split()
            return int(fields[11]) + int(fields[12]), fields[19]
        ticks_before, birth = cpu_state()
        started = time.monotonic()
        for serial in range(1, 181):
            checked(submit(connection, window, pixmap, serial, 0, 0, 0, 0,
                           0, 0, 0, 0, 0, 0, 0, 0, None))
            deadline = time.monotonic() + 3
            while True:
                event = poll(connection)
                if event:
                    try:
                        data = C.string_at(event, 32)
                        if data[0] == 0:
                            raise RuntimeError(f'Asynchronous X error {data[1]}')
                        if (data[0] & 127 == 35 and struct.unpack_from('=H', data, 8)[0] == 1
                                and struct.unpack_from('=I', data, 20)[0] == serial):
                            modes.append(data[11])
                            break
                    finally:
                        libc.free(event)
                if error(connection) or time.monotonic() > deadline:
                    raise RuntimeError('No matching Present completion on the private display')
                time.sleep(.001)
            time.sleep(max(0, started + serial / 60 - time.monotonic()))
        elapsed = time.monotonic() - started
        ticks_after, birth_after = cpu_state()
        if birth != birth_after:
            raise RuntimeError('Private X server identity changed')
        record['present'] = {'frames': len(modes), 'elapsed_seconds': elapsed,
            'complete_modes': {str(mode): modes.count(mode) for mode in set(modes)},
            'all_flipped': all(mode == 1 for mode in modes),
            'server_cpu_percent_one_core': 100 * (ticks_after - ticks_before) / os.sysconf('SC_CLK_TCK') / elapsed,
            'android_activity_attached': False}
        get_image = fn(xcb, 'xcb_get_image', U32, PTR, U8, U32, I16, I16, U16, U16, U32)
        cookie = get_image(connection, 2, screen.root, 0, 0, desc.width, desc.height, 0xFFFFFFFF)
        reply = fn(xcb, 'xcb_get_image_reply', PTR, PTR, U32, PTR)(connection, cookie, None)
        if not reply:
            raise RuntimeError('No root image after Present')
        try:
            size = fn(xcb, 'xcb_get_image_data_length', C.c_int, PTR)(reply)
            pointer = fn(xcb, 'xcb_get_image_data', PTR, PTR)(reply)
            if size != desc.width * desc.height * 4:
                raise RuntimeError('Unexpected root image size')
            data = C.string_at(pointer, size)
            pixels = desc.width * desc.height
            record['present']['root_pixels_verified'] = (data[0::4] == b'\x00' * pixels and
                data[1::4] == b'\xff' * pixels and data[2::4] == b'\x00' * pixels)
        finally:
            libc.free(reply)
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'x11grab', '-video_size',
            f'{desc.width}x{desc.height}', '-i', display, '-frames:v', '1', str(capture)],
            check=True, timeout=10, stdout=subprocess.DEVNULL)
        if not record['present']['all_flipped'] or not record['present']['root_pixels_verified']:
            raise RuntimeError('AHB Present did not flip with the expected root pixels')
    finally:
        disconnect(connection)
