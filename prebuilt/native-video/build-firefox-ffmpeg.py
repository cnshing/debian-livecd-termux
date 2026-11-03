#!/data/data/com.termux/files/usr/bin/python
"""Build private native FFmpeg decoder libraries with VA-API for Firefox."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

HERE = Path(__file__).resolve().parent
PREFIX = Path('/data/data/com.termux/files/usr')
ROOT = Path.home() / '.local/opt/livecd-native/acceleration'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    if os.environ.get('PREFIX') != str(PREFIX) or args.jobs < 1:
        parser.error('Run in native Termux with a positive job count')
    pins = json.loads((HERE / 'firefox-ffmpeg.lock.json').read_text())
    inputs = {'pins': pins, 'builder': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:16]
    destination = ROOT / ('firefox-ffmpeg-' + digest)
    work = Path.home() / '.cache/livecd-native-video' / ('firefox-ffmpeg-' + digest)
    work.mkdir(parents=True, exist_ok=True)
    if not (destination / 'manifest.json').is_file():
        archive = work / 'source.tar.xz'
        if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != pins['sha256']:
            urllib.request.urlretrieve(pins['url'], archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != pins['sha256']:
            raise RuntimeError('FFmpeg source checksum mismatch')
        source = work / 'source'
        if not (source / '.patched').exists():
            if source.exists():
                shutil.rmtree(source)
            source.mkdir()
            with tarfile.open(archive) as contents:
                for member in contents.getmembers():
                    parts = member.name.split('/', 1)
                    if len(parts) == 2 and parts[1]:
                        member.name = parts[1]
                        contents.extract(member, source, filter='data')
            for name, expected in pins['patches'].items():
                patch = (HERE / 'ffmpeg-patches' / name).read_bytes()
                if hashlib.sha256(patch).hexdigest() != expected:
                    raise RuntimeError('FFmpeg patch checksum mismatch: ' + name)
                subprocess.run(['patch', '--batch', '-p1'], cwd=source,
                    input=patch.replace(b'@TERMUX_PREFIX@', str(PREFIX).encode()), check=True)
            (source / '.patched').touch()
        stage = work / 'runtime'
        build = work / 'build'
        build.mkdir(exist_ok=True)
        env = {k:v for k,v in os.environ.items() if k not in ('LD_LIBRARY_PATH', 'LD_PRELOAD')}
        # Keep native Termux's env shebang translation for configure generators.
        preload = PREFIX / 'lib/libtermux-exec.so'
        if preload.is_file():
            env['LD_PRELOAD'] = str(preload)
        stack = (ROOT / 'bionic').resolve()
        env['PKG_CONFIG_PATH'] = str(stack / 'lib/pkgconfig')
        def run(command):
            print('+', *map(str, command), flush=True)
            subprocess.run(list(map(str, command)), cwd=build, env=env, check=True)
        if not (build / 'config.h').is_file():
            run([source / 'configure', '--prefix=' + str(stage), '--libdir=' + str(stage / 'lib'),
                '--target-os=android', '--arch=aarch64', '--enable-cross-compile',
                '--cc=clang --target=aarch64-linux-android29', '--cxx=clang++ --target=aarch64-linux-android29',
                '--ar=llvm-ar', '--nm=llvm-nm', '--ranlib=llvm-ranlib', '--strip=llvm-strip',
                '--disable-autodetect', '--disable-programs', '--disable-doc', '--disable-debug',
                '--disable-static', '--enable-shared', '--disable-symver', '--enable-pic',
                '--disable-encoders', '--disable-muxers', '--disable-demuxers', '--disable-protocols',
                '--disable-devices', '--disable-filters', '--disable-avdevice', '--disable-avfilter',
                '--disable-avformat', '--disable-network', '--enable-vaapi',
                '--enable-hwaccel=hevc_vaapi,h264_vaapi,vp9_vaapi,av1_vaapi,vp8_vaapi'])
        run(['make', '-j' + str(args.jobs)])
        run(['make', 'install'])
        for path in (stage / 'lib').glob('*.so*'):
            if path.is_file() and not path.is_symlink():
                run(['patchelf', '--set-rpath', '$ORIGIN', path])
        for path in source.glob('COPYING*'):
            shutil.copy2(path, stage / path.name)
        for name in ('libavcodec.so.63', 'libavutil.so.61'):
            if not (stage / 'lib' / name).is_file():
                raise RuntimeError('Missing FFmpeg ABI library: ' + name)
        (stage / 'manifest.json').write_text(json.dumps({'format': 1, 'abi': 'bionic',
            'inputs': inputs, 'runtime_verified': False}, indent=2) + '\n')
        stage.rename(destination)
    selector = ROOT / 'firefox-ffmpeg.next'
    selector.unlink(missing_ok=True)
    selector.symlink_to(destination.name)
    selector.replace(ROOT / 'firefox-ffmpeg')
    print('Selected Firefox VA-API decoder libraries:', destination, flush=True)


if __name__ == '__main__':
    main()
