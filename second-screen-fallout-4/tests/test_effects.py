"""The native scan profiles use uncompressed BGRA rather than BC1/BC3."""
import base64
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from assets import AssetError
from effects import prepare_effects, texture_pixels


class EffectTests(unittest.TestCase):
    def test_bgra_preserves_alpha_and_ignores_lower_mips(self):
        self.assertEqual(texture_pixels(bytes([10, 20, 30, 40, 50, 60, 70, 80, 99]), 2, 1, 87),
                         bytes([30, 20, 10, 40, 70, 60, 50, 80]))

    def test_rejects_truncated_and_invalid_dimensions(self):
        for payload, width, height in [(b'abc', 1, 1), (b'', 0, 1), (b'', 8192, 8192)]:
            with self.assertRaises(AssetError):
                texture_pixels(payload, width, height, 87)

    @unittest.skipUnless(os.environ.get('FALLOUT4_TEST_GAME'), 'Set FALLOUT4_TEST_GAME')
    def test_installed_scan_profiles_and_cache_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = prepare_effects(Path(os.environ['FALLOUT4_TEST_GAME']), Path(tmp))
            self.assertEqual(first['warnings'], [])
            for name in ('scan', 'verticalScan'):
                profile = first['effects'][name]
                self.assertEqual((profile['width'], profile['height']), (4, 32))
            path = Path(tmp) / first['effects']['verticalScan']['path']
            image = path.read_bytes()
            self.assertEqual(image[:8], b'\x89PNG\r\n\x1a\n')
            encoded = first['effects']['verticalScan']['dataURI']
            self.assertEqual(base64.b64decode(encoded.split(',', 1)[1], validate=True), image)
            path.unlink()
            self.assertEqual(prepare_effects(Path(os.environ['FALLOUT4_TEST_GAME']), Path(tmp)), first)
            self.assertEqual(path.read_bytes(), image)
