#!/usr/bin/env python3
"""Check Ghostty's own fresh terminal pixels, GPU identity and normal exit."""
import argparse
import json
from pathlib import Path
import subprocess


def check_pixels(folder, capture, stale=False):
    path = folder / capture['path']
    png = path.read_bytes()
    width, height = (int.from_bytes(png[i:i + 4], 'big') for i in (16, 20))
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(path),
        '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
        capture_output=True, check=True, timeout=30).stdout
    assert len(raw) == width * height * 3
    geometry = dict(line.split('=', 1) for line in capture['geometry'].splitlines())
    x, y, w, h = (int(geometry[key]) for key in ('X', 'Y', 'WIDTH', 'HEIGHT'))
    assert 0 <= x < x + w <= width and 0 <= y < y + h <= height
    full = capture['fullscreen_requested']
    assert full == ('_NET_WM_STATE_FULLSCREEN' in capture['wm_state'])
    if full:
        assert (x, y, w, h) == (0, 0, width, height)
    phase = capture['phase'] + int(stale)
    colors = [(255, 255 if phase % 2 else 0, 0), (0, 255, 0),
              (0, 0, 255), (255, 255, 255)]
    bands = []
    # Require broad, solid bands in order, inside the terminal's own window.
    # Text, window decorations and an unchanged desktop cannot satisfy this.
    after = y
    for color in colors:
        needle = bytes(color) * 120
        rows = []
        for row in range(after, y + h):
            line = raw[(row * width + x) * 3:(row * width + x + w) * 3]
            offset = line.find(needle)
            if offset >= 0 and offset % 3 == 0:
                rows.append(row)
                if len(rows) >= 20 and rows[-1] - rows[-20] == 19:
                    bands.append({'rgb': color, 'first_row': rows[-20], 'last_row': row})
                    after = row + 1
                    break
        else:
            raise AssertionError(f'{path.name}: missing fresh color band {color}')
    return {'path': path.name, 'phase': capture['phase'], 'bands': bands}


def check(folder, software_control=False, reject_cpu_fallback=False):
    result = json.loads((folder / 'result.json').read_text())
    assert result.get('completed'), result.get('error')
    assert json.loads((folder / 'isolation.json').read_text())['ok'], 'shared state changed'
    ghostty = result['ghostty']
    assert ghostty['software_control'] == software_control
    assert ghostty['returncode_before_cleanup'] == 0, 'Ghostty did not exit normally'
    assert ghostty['identity']['gl_override'] is None
    assert ghostty['identity']['experiment'] == '1'
    assert not any('angle' in p.lower() for p in ghostty['libraries'])
    panvk = any('libvulkan_panfrost.so' in p for p in ghostty['libraries'])
    mali = any(d['target'] == '/dev/mali0' for d in ghostty['devices'])
    assert (panvk, mali) == ((False, False) if software_control else (True, True))
    captures = ghostty['captures']
    assert len(captures) >= 4 and {c['fullscreen_requested'] for c in captures} == {False, True}
    checked = [check_pixels(folder, c) for c in captures]
    try:
        check_pixels(folder, captures[0], stale=True)
    except AssertionError:
        pass
    else:
        raise AssertionError('Negative control accepted stale terminal output')
    log = (folder / 'ghostty.log').read_text(errors='replace')
    cpu_fallback = any(message in log for message in (
        'falling back to CPU presentation', 'asking renderer for CPU presentation'))
    if reject_cpu_fallback:
        assert not cpu_fallback, 'Ghostty reported CPU presentation fallback; DMA-BUF is not accepted'
    report = {'cpu_presentation_fallback_reported': cpu_fallback, 'ok': True,
              'software_control': software_control, 'captures': checked,
              'stale_negative_control_rejected': True}
    (folder / 'ghostty-pixel-results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(folder.name, 'PASS', len(checked), 'Ghostty captures;',
          'software control' if software_control else 'PanVK/Mali GPU', '; normal exit;',
          'CPU presentation fallback' if cpu_fallback else 'presentation path unverified')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--software-control', action='store_true')
    parser.add_argument('--reject-cpu-fallback', action='store_true',
                        help='Reject a known CPU fallback; absence of the warning alone is not DMA-BUF proof')
    args = parser.parse_args()
    check(args.folder, args.software_control, args.reject_cpu_fallback)
