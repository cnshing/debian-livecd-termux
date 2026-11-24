#!/usr/bin/env python3
"""Native-pixel regression controls for the offline PanVK recording analyzer."""
import importlib.util
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('race', Path(__file__).with_name('panvk-present-race.py'))
race = importlib.util.module_from_spec(spec)
spec.loader.exec_module(race)


class RecordingControls(unittest.TestCase):
    def test_pixel_masks_match_scalar_reference(self):
        rng = random.Random(1701)
        pixels = [tuple(rng.randrange(256) for _ in range(3)) for _ in range(5000)]
        pixels += [(255, 0, 0), (0, 0, 255), (180, 0, 0), (181, 69, 69)]
        data = bytes(channel for pixel in pixels for channel in pixel)
        actual = race.classify(data)
        self.assertEqual(actual['red'], sum(r > 180 and g < 70 and b < 70 for r, g, b in pixels))
        self.assertEqual(actual['blue'], sum(b > 180 and g < 70 and r < 70 for r, g, b in pixels))
        self.assertTrue(actual['split'])
        self.assertFalse(actual['valid'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools required')
    def test_single_native_pixel_and_invalid_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)

            def encode(name, data):
                source, clip = folder / (name + '.ppm'), folder / (name + '.mkv')
                source.write_bytes(b'P6\n96 80\n255\n' + data)
                subprocess.run(['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(source),
                    '-frames:v', '1', '-c:v', 'ffv1', '-pix_fmt', 'bgr0', '-threads', '1', str(clip)],
                    check=True, timeout=30)
                return clip

            solid = bytes((255, 0, 0)) * (96 * 80)
            clean = race.check(encode('solid', solid))
            self.assertEqual(clean['split_count'], 0)
            self.assertEqual(clean['solid_red_frames'], 1)
            # A single blue pixel must survive decoding and the eight-pixel inset.
            mixed = bytearray(solid)
            offset = (17 * 96 + 17) * 3
            mixed[offset:offset + 3] = bytes((0, 0, 255))
            defective = race.check(encode('single-pixel', mixed))
            self.assertTrue(defective['native_resolution'])
            self.assertEqual(defective['pixels_per_frame'], 80 * 64)
            self.assertEqual(defective['split_frames'], [0])
            self.assertEqual(defective['solid_red_frames'], 0)
            with self.assertRaisesRegex(RuntimeError, 'Invalid capture'):
                race.check(encode('black', bytes(len(solid))))

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_menu_cut_and_calibration_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            opened = bytes((37, 41, 50)) * (96 * 80)
            closed = bytes(96 * 80 * 3)
            cut = opened[:96 * 40 * 3] + closed[96 * 40 * 3:]
            for index, data in enumerate((closed, opened, cut)):
                source = folder / f'frame-{index}.ppm'
                source.write_bytes(b'P6\n96 80\n255\n' + data)
                if index < 2:
                    target = folder / ('menu-open.png' if index else 'menu-closed.png')
                    subprocess.run(['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(source),
                        '-frames:v', '1', '-threads', '1', str(target)], check=True, timeout=30)
            clip = folder / 'menu.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-threads', '1', '-framerate', '30',
                '-i', str(folder / 'frame-%d.ppm'), '-frames:v', '3', '-c:v', 'ffv1',
                '-pix_fmt', 'bgr0', '-threads', '1', str(clip)], check=True, timeout=30)
            calibration = {'strips': [20, 20, 50, 8, 8], 'color': [37, 41, 50]}
            result = race.check_menu(clip, calibration)
            self.assertEqual(result['frames'], 3)
            self.assertEqual(result['cut_frames'], [2])
            self.assertEqual(result['fully_open_frames'], 1)
            self.assertEqual(result['closed_frames'], 1)
            with self.assertRaisesRegex(RuntimeError, 'calibration'):
                race.check_menu(clip, {**calibration, 'color': [255, 0, 0]})


if __name__ == '__main__':
    unittest.main()
