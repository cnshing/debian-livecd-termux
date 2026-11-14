#!/usr/bin/env python3
"""Check Ghostty's own fresh terminal pixels, GPU identity and normal exit."""
import argparse
import json
import re
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


def check(folder, software_control=False, reject_cpu_fallback=False, require_dmabuf=False, require_dmabuf_gl=False):
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
    if reject_cpu_fallback or require_dmabuf or require_dmabuf_gl:
        assert not cpu_fallback, 'Ghostty reported CPU presentation fallback; DMA-BUF is not accepted'
    imports = log.count('Creating dmabuf texture, format ')
    downloads = log.count('Used mmap for downloading ')
    gl_imports = len(re.findall(r'Imported [^\n]+ dmabuf as GL_TEXTURE_', log))
    cpu_downloads = log.count('Downloading dmabuf texture to CPU')
    if require_dmabuf or require_dmabuf_gl:
        assert not software_control, 'DMA-BUF acceptance requires the GPU run'
        assert imports >= len(captures), 'Missing positive GTK DMA-BUF import evidence'
        if require_dmabuf_gl:
            assert ghostty.get('renderer') == 'gl', 'GPU import requires the explicit GTK GL renderer run'
            assert gl_imports >= len(captures), 'Missing positive GTK GL DMA-BUF import evidence'
            assert downloads == 0 and cpu_downloads == 0, 'GTK downloaded a DMA-BUF to CPU memory'
        else:
            assert downloads >= len(captures), 'Missing positive GTK mmap download evidence'
        assert any('libgtk-4' in p for p in ghostty['libraries']), 'GTK mapping was not audited'
        log_bytes = (folder / 'ghostty.log').read_bytes()
        for capture in captures:
            begin, end = (capture.get(key) for key in ('presentation_log_start', 'presentation_log_end'))
            assert isinstance(begin, int) and isinstance(end, int), 'Missing per-capture presentation log bounds'
            assert 0 <= begin < end <= len(log_bytes), 'Invalid presentation log bounds'
            segment = log_bytes[begin:end].decode(errors='replace')
            assert 'Creating dmabuf texture, format ' in segment, capture['path'] + ': no fresh GTK DMA-BUF import'
            if require_dmabuf_gl:
                assert re.search(r'Imported [^\n]+ dmabuf as GL_TEXTURE_', segment), capture['path'] + ': no fresh GTK GL import'
            else:
                assert 'Used mmap for downloading ' in segment, capture['path'] + ': no fresh GTK mmap download'
    report = {'cpu_presentation_fallback_reported': cpu_fallback, 'ok': True,
              'gtk_dmabuf_imports': imports, 'gtk_dmabuf_mmap_downloads': downloads,
              'dmabuf_mmap_verified': require_dmabuf,
              'gtk_dmabuf_gl_imports': gl_imports, 'gtk_dmabuf_cpu_downloads': cpu_downloads,
              'dmabuf_gl_verified': require_dmabuf_gl,
              'software_control': software_control, 'captures': checked,
              'stale_negative_control_rejected': True}
    (folder / 'ghostty-pixel-results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(folder.name, 'PASS', len(checked), 'Ghostty captures;',
          'software control' if software_control else 'PanVK/Mali GPU', '; normal exit;',
          'GTK DMA-BUF GL import verified' if require_dmabuf_gl else
          'GTK DMA-BUF mmap verified' if require_dmabuf else (
              'CPU presentation fallback' if cpu_fallback else 'presentation path unverified'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--software-control', action='store_true')
    parser.add_argument('--reject-cpu-fallback', action='store_true',
                        help='Reject a known CPU fallback; absence of the warning alone is not DMA-BUF proof')
    presentation = parser.add_mutually_exclusive_group()
    presentation.add_argument('--require-dmabuf', action='store_true',
                        help='Require positive GTK import/mmap diagnostics for every fresh capture')
    presentation.add_argument('--require-dmabuf-gl', action='store_true',
                              help='Require fresh GTK GL imports and reject all DMA-BUF CPU downloads')
    args = parser.parse_args()
    check(args.folder, args.software_control, args.reject_cpu_fallback, args.require_dmabuf, args.require_dmabuf_gl)
