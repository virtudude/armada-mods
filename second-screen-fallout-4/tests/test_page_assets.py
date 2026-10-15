"""Page extraction tests use generated shapes, never distributed game bytes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import page_assets as pages


def movie_fixture():
    movie = pages.Movie.__new__(pages.Movie)
    movie.fps = 30
    movie.shapes = {1: ('<path fill="#fff" d="M0 0L20 0L20 20Z"/>', (0, 20, 0, 20))}
    movie.timelines = {
        -1: ([[{"id": 2, "matrix": (1, 0, 0, 1, 100, 200), "born": 0}]], {}),
        2: ([[{"id": 1, "matrix": (1, 0, 0, 1, x, 0), "born": 0}]
             for x in (0, 10, 0)], {}),
    }
    return movie


def bits(*fields):
    value = "".join(format(number & ((1 << count) - 1), "0%db" % count) for count, number in fields if count)
    value += "0" * (-len(value) % 8)
    return bytes(int(value[i:i + 8], 2) for i in range(0, len(value), 8))


def ruler_shape():
    rect = bits((5, 6), (6, 0), (6, 20), (6, 0), (6, 20))
    # No fill; one 20-twip solid white round scaling line; one horizontal edge.
    edges = bits((4, 0), (4, 1), (1, 0), (5, 8), (1, 1),
                 (1, 1), (1, 1), (4, 4), (1, 0), (1, 0), (6, 20), (1, 0), (5, 0))
    return b"\x01\0" + rect + rect + b"\x01\x00\x01\x14\0\0\0\xff\xff\xff\xff" + edges


class PageAssetTests(unittest.TestCase):
    def test_quest_path_matches_companion_case_and_separators(self):
        self.assertEqual(pages.quest_key(r"Interface\Components\Quest Vault Boys\Act 1 Quest\Example.swf"),
                         "components/quest vault boys/act 1 quest/example.swf")
        for path in ("../example.swf", "components/quest vault boys/../../x.swf", "http://x/y.swf", "components/quest vault boys//x.swf"):
            with self.assertRaises(pages.AssetError):
                pages.quest_key(path)

    def test_exports_child_duration_preserving_root_transform_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = pages.export_quest(movie_fixture(), tmp, "pages/test/quest")
            self.assertEqual(len(result["frames"]), 3)
            self.assertEqual(result["frames"][0], result["frames"][2])
            self.assertNotEqual(result["frames"][0], result["frames"][1])
            self.assertEqual(result["viewBox"], [100, 200, 30, 20])
            self.assertTrue(result["playOnce"])
            self.assertEqual(len(list(Path(tmp).rglob("*.svg"))), 2)
            self.assertIn('matrix(1 0 0 1 100 200)', next(Path(tmp).rglob("*.svg")).read_text())

    def test_budgets_fail_before_writing_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kwargs in ({"budget": [1]}, {}):
                context = mock.patch.object(pages, "MAX_CLIP_BYTES", 1) if not kwargs else mock.patch.object(pages, "MAX_CLIP_BYTES", 100000)
                with context, self.assertRaises(pages.AssetError):
                    pages.export_quest(movie_fixture(), tmp, "clip", **kwargs)
            self.assertFalse(list(Path(tmp).rglob("*.svg")))
        with mock.patch.object(pages, "MAX_FRAMES", 2), self.assertRaises(pages.AssetError):
            pages.quest_duration(movie_fixture())

    def test_round_shape4_stroke_is_lossless_and_other_semantics_rejected(self):
        content, bounds = pages.radio_scale_shape(ruler_shape())
        self.assertEqual(bounds, (0, 20, 0, 20))
        self.assertIn('stroke="#ffffffff"', content)
        self.assertIn('stroke-width="20"', content)
        self.assertIn('L20 0', content)
        payload = bytearray(ruler_shape())
        # Extended line flags are immediately before the RGBA color.
        payload[-len(bits((4, 0), (4, 1), (1, 0), (5, 8), (1, 1), (1, 1), (1, 1), (4, 4), (1, 0), (1, 0), (6, 20), (1, 0), (5, 0))) - 5] = 1
        with self.assertRaises(pages.AssetError):
            pages.radio_scale_shape(payload)

    def test_cache_rejects_missing_files_and_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "assets/pages/generation/a.svg"
            good.parent.mkdir(parents=True)
            good.write_text("<svg/>")
            cache = {"schema": pages.SCHEMA, "sources": {}, "additions": {"x": "assets/pages/generation/a.svg"}}
            self.assertTrue(pages._valid_cache(cache, {}, root))
            good.unlink()
            self.assertFalse(pages._valid_cache(cache, {}, root))
            outside = root / "outside.svg"
            outside.write_text("<svg/>")
            cache["additions"]["x"] = "assets/pages/../../outside.svg"
            self.assertFalse(pages._valid_cache(cache, {}, root))

    def test_missing_install_is_reported_and_cached_without_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            game, data = Path(tmp) / "game", Path(tmp) / "data"
            result = pages.prepare_page_assets(game, data)
            self.assertEqual(result["animations"]["quests"]["byPath"], {})
            self.assertEqual(len(result["pageAssetWarnings"]), 2)
            self.assertEqual(pages.prepare_page_assets(game, data), result)
            cache = json.loads((data / "assets/pages-manifest.json").read_text())
            self.assertEqual(cache["schema"], pages.SCHEMA)


if __name__ == "__main__":
    unittest.main()
