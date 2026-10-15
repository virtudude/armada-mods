"""Synthetic format tests: no game assets are test fixtures."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import model_assets as models


def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)


def string(text):
    encoded = text.encode()
    return pack('I', len(encoded)) + encoded


def av(translation=(0, 0, 0), flags=14):
    return (pack('iIiI', -1, 0, -1, flags) + pack('3f', *translation)
            + pack('9f', 1, 0, 0, 0, 1, 0, 0, 0, 1) + pack('fi', 1, -1))


def fixture_nif(skin=-1, indices=(0, 1, 2), flags=14):
    node = av((10, 0, 0)) + pack('Ii', 1, 1)
    vertex_data = b''.join(pack('4f', *p, 0) for p in [(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    shape = (av((1, 0, 0), flags) + pack('4f', 0, 0, 0, 1) + pack('3i', skin, -1, -1)
             + pack('QIHI', (0x401 << 44) | 4, 1, 3, len(vertex_data) + 6)
             + vertex_data + pack('3H', *indices))
    return (b'Gamebryo File Format, Version 20.2.0.7\n' + pack('IBIII', 0x14020007, 1, 12, 2, 130)
            + b'\0' * 4 + pack('H', 2) + string('NiNode') + string('BSTriShape')
            + pack('2H', 0, 1) + pack('2I', len(node), len(shape)) + pack('3I', 0, 0, 0)
            + node + shape + pack('Ii', 1, 0))


class Models(unittest.TestCase):
    def test_real_triangles_transforms_and_bounds(self):
        model = models.parse_nif(fixture_nif())
        shape = model['primitives'][0]
        self.assertEqual(shape['positions'], [[11., 0., 0.], [12., 0., 0.], [11., 1., 0.]])
        self.assertEqual(shape['indices'], [0, 1, 2])
        self.assertEqual(model['bounds'], {'min': [11., 0., 0.], 'max': [12., 1., 0.]})

    def test_rejects_truncated_bad_indices_skin_and_hidden(self):
        for data in (fixture_nif()[:-8], fixture_nif(indices=(0, 1, 9)), fixture_nif(skin=2), fixture_nif(flags=15)):
            with self.assertRaises(models.ModelError):
                models.parse_nif(data)

    def test_bgsm_diffuse_and_alpha(self):
        header = (pack('4sII', b'BGSM', 2, 3) + pack('5f', 0, 0, 1, 1, .5)
                  + pack('BII', 0, 1, 0) + pack('2B', 128, 1) + pack('8B', 1, 1, 0, 0, 0, 1, 0, 0)
                  + pack('2BfBfB', 0, 0, 0, 0, 0, 0))
        material = models.parse_bgsm(header + string('Props/Test_d.dds\0'))
        self.assertEqual(material['diffuseSource'], 'Props/Test_d.dds')
        self.assertEqual(material['alpha'], .5)
        self.assertTrue(material['twoSided'])
        self.assertAlmostEqual(material['alphaTest'], 128 / 255)

    def test_esm_index_and_unsupported_descriptors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / 'game'
            (game / 'Data').mkdir(parents=True)
            # Derive length rather than rely on hand-counted string size.
            name = b'Props\\Test.nif\0'
            body = b'MODL' + pack('H', len(name)) + name
            body += b'MODS' + pack('HI', 4, 0x123)
            record = pack('4sIII', b'MISC', len(body), 0, 123) + b'\0' * 8 + body
            (game / 'Data/Fallout4.esm').write_bytes(record)
            index = models.model_index(game, root / 'cache')
            self.assertEqual(index['123']['mesh'], 'meshes/props/test.nif')
            self.assertTrue(index['123']['materialSwap'])
            self.assertEqual(index, models.model_index(game, root / 'cache'))
            result = models.prepare_model(game, root / 'cache', 123)
            self.assertEqual(result['status'], 'unsupported')
            self.assertIn('material-swap', result['reason'])
            self.assertEqual(models.prepare_model(game, root / 'cache', 0xFF000001)['status'], 'unsupported')

    def test_path_traversal_rejected(self):
        for path in ['../outside.nif', '/absolute.nif', 'c:/absolute.nif', 'foo//bar.nif']:
            with self.assertRaises(models.ModelError):
                models.asset_path(path, 'meshes')


if __name__ == '__main__':
    unittest.main()
