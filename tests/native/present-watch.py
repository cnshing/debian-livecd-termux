#!/usr/bin/env python3
"""Count how the X server completes the compositor's presents: copied or flipped.

Selects Present CompleteNotify on the Composite overlay window and on every window under the
root, so it sees the compositor's presents wherever they go, and records the completion modes
(0 copy, 1 flip, 2 skip, 3 suboptimal copy) for a fixed time. Only a private display.
"""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import re
import struct
import time

PTR, U8, U16, U32 = C.c_void_p, C.c_uint8, C.c_uint16, C.c_uint32
MODES = {0: 'copy', 1: 'flip', 2: 'skip', 3: 'suboptimal_copy'}


class Screen(C.Structure):
    _fields_ = [('root', U32), ('default_colormap', U32), ('white_pixel', U32),
                ('black_pixel', U32), ('current_input_masks', U32), ('width_in_pixels', U16),
                ('height_in_pixels', U16), ('width_in_millimeters', U16),
                ('height_in_millimeters', U16), ('min_installed_maps', U16),
                ('max_installed_maps', U16), ('root_visual', U32), ('backing_stores', U8),
                ('save_unders', U8), ('root_depth', U8), ('allowed_depths_len', U8)]


class Iterator(C.Structure):
    _fields_ = [('data', C.POINTER(Screen)), ('rem', C.c_int), ('index', C.c_int)]


def watch(display, seconds):
    if not re.fullmatch(r':(?:7[4-9]|[89][0-9])', display):
        raise RuntimeError('present-watch only observes private displays :74–:99')
    xcb, present, composite = (C.CDLL(n) for n in
                               ('libxcb.so', 'libxcb-present.so', 'libxcb-composite.so'))
    libc = C.CDLL(None)
    libc.free.argtypes, libc.free.restype = [PTR], None

    def fn(lib, name, result, *arguments):
        function = getattr(lib, name)
        function.argtypes, function.restype = arguments, result
        return function
    connection = fn(xcb, 'xcb_connect', PTR, C.c_char_p, PTR)(display.encode(), None)
    has_error = fn(xcb, 'xcb_connection_has_error', C.c_int, PTR)
    try:
        if has_error(connection):
            raise RuntimeError('Could not connect to ' + display)
        for lib, prefix, version in ((present, 'xcb_present', (1, 2)), (composite, 'xcb_composite', (0, 4))):
            cookie = fn(lib, prefix + '_query_version', U32, PTR, U32, U32)(connection, *version)
            reply = fn(lib, prefix + '_query_version_reply', PTR, PTR, U32, PTR)(connection, cookie, None)
            if not reply:
                raise RuntimeError('Missing ' + prefix)
            libc.free(reply)
        setup = fn(xcb, 'xcb_get_setup', PTR, PTR)(connection)
        root = fn(xcb, 'xcb_setup_roots_iterator', Iterator, PTR)(setup).data.contents.root
        cookie = fn(composite, 'xcb_composite_get_overlay_window', U32, PTR, U32)(connection, root)
        reply = fn(composite, 'xcb_composite_get_overlay_window_reply', PTR, PTR, U32, PTR)(
            connection, cookie, None)
        if not reply:
            raise RuntimeError('No Composite overlay window')
        overlay = struct.unpack_from('=I', C.string_at(reply, 12), 8)[0]
        libc.free(reply)
        query = fn(xcb, 'xcb_query_tree', U32, PTR, U32)
        query_reply = fn(xcb, 'xcb_query_tree_reply', PTR, PTR, U32, PTR)

        def children(window):
            reply = query_reply(connection, query(connection, window), None)
            if not reply:
                return []
            try:
                count = struct.unpack_from('=H', C.string_at(reply, 32), 16)[0]
                return list(struct.unpack_from(f'={count}I', C.string_at(reply, 32 + 4 * count), 32))
            finally:
                libc.free(reply)
        windows, pending = [], [overlay, root]
        while pending and len(windows) < 512:
            window = pending.pop(0)
            if window in windows:
                continue
            windows.append(window)
            pending += children(window)
        select = fn(present, 'xcb_present_select_input_checked', U32, PTR, U32, U32, U32)
        new_id = fn(xcb, 'xcb_generate_id', U32, PTR)
        check = fn(xcb, 'xcb_request_check', PTR, PTR, U32)
        for window in windows:
            # XCB_PRESENT_EVENT_MASK_COMPLETE_NOTIFY (1 would be ConfigureNotify)
            if check(connection, select(connection, new_id(connection), window, 2)):
                raise RuntimeError(f'Present SelectInput failed on window {window:#x}')
        poll = fn(xcb, 'xcb_poll_for_event', PTR, PTR)
        counts, msc, by_window = {}, [], {}
        end = time.monotonic() + seconds
        while time.monotonic() < end and not has_error(connection):
            event = poll(connection)
            if not event:
                time.sleep(.002)
                continue
            try:
                data = C.string_at(event, 40)
                # GenericEvent, CompleteNotify, kind Pixmap.
                if data[0] & 127 == 35 and struct.unpack_from('=H', data, 8)[0] == 1 and data[10] == 0:
                    mode = MODES.get(data[11], str(data[11]))
                    counts[mode] = counts.get(mode, 0) + 1
                    window = struct.unpack_from('=I', data, 16)[0]
                    by_window[window] = by_window.get(window, 0) + 1
                    msc.append(struct.unpack_from('=Q', data, 32)[0])
            finally:
                libc.free(event)
        fn(composite, 'xcb_composite_release_overlay_window', U32, PTR, U32)(connection, root)
        fn(xcb, 'xcb_flush', C.c_int, PTR)(connection)
        total = sum(counts.values())
        return {'display': display, 'overlay_window': overlay, 'watched_windows': windows,
                'seconds': seconds,
                'completions': total, 'modes': counts,
                'completions_by_window': {f'{w:#x}': n for w, n in by_window.items()},
                'flip_fraction': counts.get('flip', 0) / total if total else None,
                'msc_first_last': [msc[0], msc[-1]] if msc else None}
    finally:
        fn(xcb, 'xcb_disconnect', None, PTR)(connection)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.write_text(json.dumps(watch(os.environ['DISPLAY'], args.seconds), indent=2) + '\n')
