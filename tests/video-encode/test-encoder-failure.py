#!/data/data/com.termux/files/usr/bin/python
"""An encoder whose daemon dies mid-stream must fail cleanly, not abort.

FFmpeg's h264_vaapi and hevc_vaapi encode through a private daemon, which is
killed while pictures are in flight. FFmpeg then maps the coded buffers of
the unfinished pictures and destroys the context. Before android-vaapi 24 the
bridge freed such a picture's feedback in vaMapBuffer and again at context
teardown, and Scudo aborted FFmpeg with SIGABRT. Run this with the VA stack
under test in the environment, as run-phone-tests.sh's session does or as the
installed desktop provides; only TERMUX_VA_SOCKET is replaced. Against
android-vaapi 23 the abort cases must fail, which is this test's control.

Usage: test-encoder-failure.py --daemon PATH --out NEW_DIRECTORY [--repeat N]
"""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ABORT_MARKERS = ('Scudo ERROR', 'double free', 'Fatal signal', 'Aborted', 'Segmentation fault')
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (': ' + detail if detail else ''), flush=True)


def start_daemon(binary, directory):
    sock = directory.resolve() / 'daemon.sock'
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('TVA_', 'TERMUX_VA')) and k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH')}
    log = (directory / 'daemon.log').open('w')
    proc = subprocess.Popen([str(binary.resolve()), '--sock', str(sock), '-v', '-t'],
                            env=env, stdout=log, stderr=log)
    for _ in range(600):
        if sock.exists() or proc.poll() is not None:
            break
        time.sleep(.1)
    if not sock.exists():
        proc.kill()
        raise RuntimeError('daemon did not start')
    return proc, sock, log


def one_run(args, codec, index):
    directory = args.out / f'{codec}-{index}'
    directory.mkdir()
    daemon, sock, log = start_daemon(args.daemon, directory)
    output = directory / f'out.{"h264" if codec == "h264_vaapi" else "hevc"}'
    env = dict(os.environ, TERMUX_VA_SOCKET=str(sock))
    stderr = (directory / 'ffmpeg.log').open('w')
    ffmpeg = subprocess.Popen(
        ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-init_hw_device', 'vaapi=va', '-filter_hw_device', 'va',
         '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30', '-frames:v', '3000',
         '-vf', 'format=nv12,hwupload', '-c:v', codec, '-b:v', '4M', '-bf', '0', '-g', '30', str(output)],
        env=env, stdout=subprocess.DEVNULL, stderr=stderr)
    killed_after = None
    try:
        # Kill the daemon once FFmpeg has written packets, so pictures are in flight.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and ffmpeg.poll() is None:
            if output.exists() and output.stat().st_size > 64 * 1024:
                time.sleep(args.delay)
                killed_after = output.stat().st_size
                daemon.send_signal(signal.SIGKILL)
                break
            time.sleep(.05)
        try:
            code = ffmpeg.wait(timeout=60)
        except subprocess.TimeoutExpired:
            ffmpeg.kill()
            code = 'hang'
    finally:
        if daemon.poll() is None:
            daemon.kill()
        daemon.wait()
        log.close()
        stderr.close()
    text = (directory / 'ffmpeg.log').read_text(errors='replace')
    markers = [marker for marker in ABORT_MARKERS if marker in text]
    started = killed_after is not None
    clean = started and code != 'hang' and isinstance(code, int) and code >= 0 and not markers
    detail = (f'killed daemon after {killed_after} bytes, ffmpeg exit '
              f'{code if not isinstance(code, int) or code >= 0 else signal.Signals(-code).name}'
              f'{", markers " + str(markers) if markers else ""}')
    check(f'{codec} run {index} fails cleanly when the daemon dies', clean, detail)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--daemon', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--delay', type=float, default=0.2, help='seconds between first packets and the kill')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    for codec in ('h264_vaapi', 'hevc_vaapi'):
        for index in range(args.repeat):
            one_run(args, codec, index)
    print(f'RESULT {sum(results)}/{len(results)} passed', flush=True)
    sys.exit(0 if results and all(results) else 1)


if __name__ == '__main__':
    main()
