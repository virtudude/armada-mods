"""Synthetic format fixtures; never store extracted Fallout 4 bytes in tests."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import zlib


spec = importlib.util.spec_from_file_location("assets", Path(__file__).parents[1] / "tools/assets.py")
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def bits(*fields):
    value = "".join(format(number & ((1 << count) - 1), "0%db" % count) for count, number in fields if count)
    value += "0" * (-len(value) % 8)
    return bytes(int(value[i:i + 8], 2) for i in range(0, len(value), 8))


def tag(kind, data=b""):
    if len(data) >= 63:
        return struct.pack("<HI", (kind << 6) | 63, len(data)) + data
    return struct.pack("<H", (kind << 6) | len(data)) + data


def marker_swf():
    # A filled 20x20 square with a 10-twip translation in its named sprite.
    rect = bits((5, 6), (6, 0), (6, 20), (6, 0), (6, 20))
    records = [(4, 1), (4, 0), (1, 0), (5, 3), (5, 1), (1, 0), (1, 0), (1, 1)]
    for vertical, delta in ((0, 20), (1, 20), (0, -20), (1, -20)):
        records += [(1, 1), (1, 1), (4, 4), (1, 0), (1, vertical), (6, delta)]
    records += [(1, 0), (5, 0)]
    shape = struct.pack("<H", 1) + rect + b"\x01\x00\xff\xff\xff\x00" + bits(*records)
    matrix = bits((1, 0), (1, 0), (5, 5), (5, 10), (5, 0))
    place = tag(26, b"\x06" + struct.pack("<HH", 1, 1) + matrix)
    sprite = struct.pack("<HH", 2, 1) + place + tag(1) + tag(0)
    names = struct.pack("<HH", 1, 2) + b"ExampleMarker\0"
    body = rect + b"\0\x18\x01\0" + tag(2, shape) + tag(39, sprite) + tag(76, names) + tag(0)
    return b"CWS\x0f" + struct.pack("<I", len(body) + 8) + zlib.compress(body)


def ba2(kind, name, data, version=1, compressed=True):
    payload = zlib.compress(data) if compressed else data
    offset = 24 + (36 if kind == b"GNRL" else 48)
    header = struct.pack("<4sI4sIQ", b"BTDX", version, kind, 1, offset + len(payload))
    packed = len(payload) if compressed else 0
    if kind == b"GNRL":
        record = struct.pack("<I4sIIQIII", 0, b"swf\0", 0, 0, offset, packed, len(data), 0xbaadf00d)
    else:
        record = struct.pack("<I4sIBBHHHBBH", 0, b"dds\0", 0, 0, 1, 24, 4, 4, 1, 71, 2048)
        record += struct.pack("<QIIHHI", offset, packed, len(data), 0, 0, 0xbaadf00d)
    name = name.encode()
    return header + record + payload + struct.pack("<H", len(name)) + name


class AssetTests(unittest.TestCase):
    def test_reads_old_and_next_generation_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.ba2"
            for version in (1, 7, 8):
                for compressed in (False, True):
                    path.write_bytes(ba2(b"GNRL", "Interface\\Test.swf", b"hello", version, compressed))
                    _, data = assets.Archive(path).read("interface/test.swf")
                    self.assertEqual(data, b"hello")

    def test_invalid_archive_payload_range_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.ba2"
            data = bytearray(ba2(b"GNRL", "test", b"hello"))
            struct.pack_into("<Q", data, 40, 100000)
            path.write_bytes(data)
            with self.assertRaises(assets.AssetError):
                assets.Archive(path).read("test")

    def test_decompression_is_size_bounded(self):
        with self.assertRaises(assets.AssetError):
            assets.inflate(zlib.compress(b"a" * 10000), 2)
        with self.assertRaises(assets.AssetError):
            assets.inflate(zlib.compress(b"a") + b"trailing", 1)

    def test_bc1_palette_and_transparency(self):
        # Transparent mode, both endpoint colors and the average in one row.
        block = struct.pack("<HHI", 0, 0xffff, 0b11100100)
        rgba = assets.decode_texture(block, 4, 4, 71)
        self.assertEqual(rgba[:16], bytes((0, 0, 0, 255, 255, 255, 255, 255, 127, 127, 127, 255, 0, 0, 0, 0)))

    def test_bc3_color_never_uses_bc1_transparent_mode(self):
        block = bytes((255, 0)) + b"\0" * 6 + struct.pack("<HHI", 0, 0xffff, 3)
        rgba = assets.decode_texture(block, 4, 4, 77)
        self.assertEqual(rgba[:4], bytes((170, 170, 170, 255)))

    def test_bc3_alpha_interpolation(self):
        alpha = sum(index << (i * 3) for i, index in enumerate((0, 1, 2, 7)))
        block = bytes((255, 0)) + alpha.to_bytes(6, "little") + struct.pack("<HHI", 0xffff, 0, 0)
        rgba = assets.decode_texture(block, 4, 1, 77)
        self.assertEqual(list(rgba[3::4]), [255, 0, 218, 36])

    def test_small_texture_edges_and_png(self):
        block = struct.pack("<HHI", 0xf800, 0, 0)
        rgba = assets.decode_texture(block, 2, 3, 71)
        self.assertEqual(rgba, bytes((255, 0, 0, 255)) * 6)
        png = assets.png_bytes(rgba, 2, 3)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack_from(">II", png, 16), (2, 3))

    def test_texture_rejects_unsupported_format_and_truncation(self):
        with self.assertRaises(assets.AssetError):
            assets.decode_texture(b"\0" * 8, 4, 4, 98)
        with self.assertRaises(assets.AssetError):
            assets.decode_texture(b"\0" * 7, 4, 4, 71)

    def test_swf_shape_sprite_transform_and_symbol_export(self):
        icons = assets.extract_markers(marker_swf())
        self.assertEqual(set(icons), {"ExampleMarker"})
        root = ET.fromstring(icons["ExampleMarker"])
        self.assertEqual(root.attrib["viewBox"], "10 0 20 20")
        path = root.find(".//{http://www.w3.org/2000/svg}path")
        self.assertEqual(path.attrib["fill"], "#ffffff")
        self.assertTrue(path.attrib["d"].endswith("Z"))
        self.assertIn("L20 20", path.attrib["d"])

    def test_swf_root_component_uses_named_empty_sprite_slot(self):
        source = marker_swf()
        component = assets.extract_markers(source)["ExampleMarker"]
        body = zlib.decompress(source[8:])[:-2]
        body += tag(39, struct.pack("<HH", 3, 1) + tag(1) + tag(0))
        # Slot translated by 10; inserted component already begins at x=10.
        matrix = bits((1, 0), (1, 0), (5, 5), (5, 10), (5, 0))
        body += tag(26, b"\x26" + struct.pack("<HH", 1, 3) + matrix + b"Head_mc\0")
        body += tag(1) + tag(0)
        source = b"CWS\x0f" + struct.pack("<I", len(body) + 8) + zlib.compress(body)
        self.assertNotIn("root", assets.extract_markers(source, include_root=True))
        images = assets.extract_markers(source, include_root=True, components={"Head_mc": component})
        root = ET.fromstring(images["root"])
        self.assertEqual(root.attrib["viewBox"], "20 0 20 20")
        self.assertIsNotNone(root.find(".//{http://www.w3.org/2000/svg}path"))

    def test_timeline_moves_removes_and_deduplicates_frames(self):
        source = marker_swf()
        body = zlib.decompress(source[8:])[:-2]
        body += tag(26, b"\x06" + struct.pack("<HH", 1, 2) + b"\0") + tag(1) + tag(1)
        matrix = bits((1, 0), (1, 0), (5, 6), (6, 20), (6, 0))
        body += tag(26, b"\x05" + struct.pack("<H", 1) + matrix) + tag(1)
        body += tag(28, struct.pack("<H", 1)) + tag(1) + tag(0)
        source = b"CWS\x0f" + struct.pack("<I", len(body) + 8) + zlib.compress(body)
        movie = assets.Movie(source)
        self.assertEqual(movie.render(frame=0)[1], (10, 30, 0, 20))
        self.assertEqual(movie.render(frame=2)[1], (30, 50, 0, 20))
        self.assertEqual(movie.render(frame=3), ("", None))
        with tempfile.TemporaryDirectory() as directory:
            result = movie.export(directory, "test")
            self.assertEqual(result["viewBox"], [10, 0, 40, 20])
            self.assertEqual(len(result["frames"]), 4)
            self.assertEqual(result["frames"][0], result["frames"][1])
            self.assertNotEqual(result["frames"][1], result["frames"][2])

    def test_shape_line_styles_are_preserved(self):
        rect = bits((5, 6), (6, 0), (6, 20), (6, 0), (6, 20))
        records = [(4, 0), (4, 1), (1, 0), (5, 9), (5, 1), (1, 0), (1, 0), (1, 1)]
        for vertical, delta in ((0, 20), (1, 20), (0, -20), (1, -20)):
            records += [(1, 1), (1, 1), (4, 4), (1, 0), (1, vertical), (6, delta)]
        records += [(1, 0), (5, 0)]
        shape = struct.pack("<H", 1) + rect + b"\0\x01" + struct.pack("<H", 20) + b"\0\0\0" + bits(*records)
        svg, bounds = assets.shape_svg(shape, 1)
        self.assertIn('stroke="#000000"', svg)
        self.assertIn('stroke-width="20"', svg)
        self.assertEqual(bounds, (0, 20, 0, 20))

    def test_shape_can_append_a_second_style_table(self):
        rect = bits((5, 7), (7, 0), (7, 60), (7, 0), (7, 20))
        def square(x, new_styles=False):
            fields = [(4, 1), (4, 0), (1, 0), (5, 3), (5, 7), (7, x), (7, 0), (1, 1)]
            for vertical, delta in ((0, 20), (1, 20), (0, -20), (1, -20)):
                fields += [(1, 1), (1, 1), (4, 4), (1, 0), (1, vertical), (6, delta)]
            fields += [(1, 0), (5, 16 if new_styles else 0)]
            return bits(*fields)
        shape = struct.pack("<H", 1) + rect + b"\x01\0\xff\xff\xff\0" + square(0, True)
        shape += b"\x01\0\xff\0\0\0" + square(40)
        svg, _ = assets.shape_svg(shape, 2)
        self.assertIn('fill="#ffffff"', svg)
        self.assertIn('fill="#ff0000"', svg)

    def test_recursive_manifest_paths_include_animation_frames(self):
        value = {"sources": {"/game/archive": [1, 2]}, "animations": {"frames": ["assets/a.svg", "assets/b.svg"]}}
        self.assertEqual(list(assets.manifest_paths(value)), ["assets/a.svg", "assets/b.svg"])

    def test_cache_reuse_invalidation_and_missing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / "game"
            (game / "Data").mkdir(parents=True)
            source = game / "Data/Fallout4 - Textures6.ba2"
            member = assets.MAPS["commonwealth"][1]
            source.write_bytes(ba2(b"DX10", member, struct.pack("<HHI", 0xf800, 0, 0)))
            interface = game / "Data/Fallout4 - Interface.ba2"
            interface.write_bytes(ba2(b"GNRL", "interface/pipboy_mappage.swf", marker_swf()))
            data_dir = root / "data"
            first = assets.prepare_assets(game, data_dir)
            self.assertEqual(len(first["warnings"]), 1)
            self.assertIn("waiting Vault Boy", first["warnings"][0])
            self.assertEqual(first["maps"]["commonwealth"]["width"], 4)
            with mock.patch.object(assets, "Archive", side_effect=AssertionError("cache was not used")):
                self.assertEqual(assets.prepare_assets(game, data_dir), first)
            image = data_dir / "assets/worldmap.png"
            image.unlink()
            assets.prepare_assets(game, data_dir)
            self.assertTrue(image.is_file())
            source.write_bytes(ba2(b"DX10", member, struct.pack("<HHI", 0x07e0, 0, 0)))
            second = assets.prepare_assets(game, data_dir)
            self.assertNotEqual(first["sources"], second["sources"])
            self.assertEqual(json.loads((data_dir / "assets/manifest.json").read_text()), second)

    def test_missing_game_reports_degraded_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = assets.prepare_assets(Path(directory) / "missing", Path(directory) / "data")
            self.assertEqual(manifest["maps"], {})
            self.assertGreaterEqual(len(manifest["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
