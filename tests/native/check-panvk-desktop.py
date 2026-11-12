#!/usr/bin/env python3
"""Check geometry, fresh color phase, GPU identity and isolated session lifetime."""
import json
from pathlib import Path
import sys
import subprocess

def check_capture(folder, capture, stale=False):
    geometry = dict(s.split('=', 1) for s in capture['geometry'].splitlines())
    x, y, w, h = (int(geometry[k]) for k in ('X', 'Y', 'WIDTH', 'HEIGHT'))
    state = capture['state']
    assert (w, h) == (state['width'], state['height']), 'stale drawable size'
    assert capture['fullscreen_requested'] == ('_NET_WM_STATE_FULLSCREEN' in capture['wm_state'])
    path = folder / capture['path']
    data = path.read_bytes()
    image_w, image_h = int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    assert min(x, y) >= 0 and x + w <= image_w and y + h <= image_h
    if capture['fullscreen_requested']:
        assert (x, y, w, h) == (0, 0, image_w, image_h)
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(path),
        '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
        capture_output=True, check=True, timeout=30).stdout
    assert len(raw) == image_w * image_h * 3
    def pixel(px, py):
        offset = (py * image_w + px) * 3
        return raw[offset:offset + 3]
    phase = state['phase'] + int(stale)
    colors = [(255, 255 if phase % 2 else 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]
    maximum = 0
    for i, color in enumerate(colors):
        for fx in (.15, .3, .5, .7, .85):
            for fy in (.15, .3, .5, .7, .85):
                px = x + int((i % 2 + fx) * w / 2)
                py = y + int((i // 2 + fy) * h / 2)
                difference = max(abs(a - b) for a, b in zip(pixel(px, py), color))
                maximum = max(maximum, difference)
    assert maximum <= 8, f'color error {maximum}: {path.name}'
    return {'path': path.name, 'maximum_channel_error': maximum, 'samples': 100}


def check(folder):
    r = json.loads((folder / 'result.json').read_text())
    assert r.get('completed'), r.get('error')
    assert json.loads((folder / 'isolation.json').read_text())['ok'], 'shared state changed'
    for name in ('nautilus', 'settings'):
        assert r[name]['window_found'], name + ' missing'
    assert 'zink' in r['gtk_initial']['renderer'] and 'Mali-G77' in r['gtk_initial']['renderer']
    for name in ('shell', 'shell_end', 'gtk_process', 'gtk_end'):
        a = r[name]
        assert any('libvulkan_panfrost.so' in p for p in a['libraries']), name + ' has no PanVK'
        assert not any('angle' in p.lower() for p in a['libraries']), name + ' loaded ANGLE'
        assert any(d['target'] == '/dev/mali0' for d in a['devices']), name + ' has no Mali FD'
    assert r['shell']['pid'] == r['shell_end']['pid'], 'shell restarted'
    checked = [check_capture(folder, c) for c in r['captures']]
    assert len(checked) >= 4
    try:
        check_capture(folder, r['captures'][0], stale=True)
    except AssertionError:
        stale_rejected = True
    else:
        raise AssertionError('Negative control accepted a stale color phase')
    result = {'ok': True, 'captures': checked, 'stale_negative_control_rejected': stale_rejected}
    (folder / 'pixel-results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(folder.name, 'PASS', len(checked), 'captures; max error',
          max(c['maximum_channel_error'] for c in checked), '; stale negative control rejected')


if __name__ == '__main__':
    for folder in sys.argv[1:]:
        check(Path(folder))
