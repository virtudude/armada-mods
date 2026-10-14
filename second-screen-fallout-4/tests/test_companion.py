import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("companion", Path(__file__).parents[1] / "tools/companion.py")
companion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(companion)


class CompanionTests(unittest.TestCase):
    def test_jump_targets_native_initializer(self):
        displacement, = struct.unpack("<i", companion.REPLACEMENT[1:])
        self.assertEqual(companion.PATCH_RVA + 5 + displacement, companion.START_RVA)
        self.assertEqual(len(companion.REPLACEMENT), companion.PATCH_SIZE)

    def test_context_hash_and_patch_boundaries(self):
        source = b"synthetic instruction context and padding"
        with patch.multiple(companion, SOURCE_SIZE=len(source),
                            SOURCE_SHA256=hashlib.sha256(source).hexdigest(),
                            CONTEXT_OFFSET=2, CONTEXT_SIZE=20,
                            CONTEXT_SHA256=hashlib.sha256(source[2:22]).hexdigest(),
                            PATCH_OFFSET=10):
            result = companion.patch_bytes(source)
            self.assertEqual(result, source[:10] + companion.REPLACEMENT + source[15:])
            with patch.object(companion, "CONTEXT_SHA256", "0" * 64):
                with self.assertRaises(companion.UnsupportedExecutable):
                    companion.patch_bytes(source)

    def test_unknown_source_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/"original", Path(directory)/"output"
            source.write_bytes(b"unrecognized executable")
            output.write_bytes(b"existing output")
            with self.assertRaises(companion.UnsupportedExecutable):
                companion.prepare_companion(source, output)
            self.assertEqual(output.read_bytes(), b"existing output")
            self.assertEqual(source.read_bytes(), b"unrecognized executable")

    def test_source_aliases_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, alias = Path(directory)/"original", Path(directory)/"alias"
            source.write_bytes(b"original")
            with self.assertRaises(ValueError):
                companion.prepare_companion(source, source)
            alias.symlink_to(source)
            with self.assertRaises(ValueError):
                companion.prepare_companion(source, alias)
            alias.unlink()
            os.link(source, alias)
            with self.assertRaises(ValueError):
                companion.prepare_companion(source, alias)

    def test_atomic_copy_and_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/"original", Path(directory)/"overlay/Fallout4.exe"
            source.write_bytes(b"synthetic original")
            with patch.object(companion, "patch_bytes", return_value=b"synthetic patched"):
                self.assertFalse(companion.prepare_companion(source, output)["cached"])
                self.assertTrue(companion.prepare_companion(source, output)["cached"])
            self.assertEqual(source.read_bytes(), b"synthetic original")
            self.assertEqual(output.read_bytes(), b"synthetic patched")
            self.assertEqual(list(output.parent.iterdir()), [output])

    @unittest.skipUnless(os.environ.get("FALLOUT4_TEST_EXE"), "Set FALLOUT4_TEST_EXE for local installed-game verification")
    def test_installed_executable_roundtrip(self):
        source = Path(os.environ["FALLOUT4_TEST_EXE"])
        original = source.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"Fallout4.exe"
            companion.prepare_companion(source, output)
            patched = output.read_bytes()
            offset = companion.PATCH_OFFSET
            self.assertEqual(patched[offset:offset+5], companion.REPLACEMENT)
            self.assertEqual(patched[:offset], original[:offset])
            self.assertEqual(patched[offset+5:], original[offset+5:])
            self.assertEqual(len(patched), len(original))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), companion.SOURCE_SHA256)


if __name__ == "__main__":
    unittest.main()
