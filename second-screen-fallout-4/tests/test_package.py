"""Release boundary regressions use synthetic content, never game assets."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('package', Path(__file__).parents[1] / 'native/package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.stage = self.root / 'source', self.root / 'stage'
        for name in package.SOURCE_FILES:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}' if path.suffix == '.json' else 'synthetic source')
        (self.root / 'THIRD-PARTY.md').write_text('Synthetic notices')
        package.stage_sources(self.source, self.stage)
        (self.stage / 'host/pipboy-host').write_bytes(b'\x7fELF\x02\x01' + bytes(12) + b'\xb7\x00')
        (self.stage / 'licenses').mkdir()
        (self.stage / 'licenses/dependencies.json').write_text('[]')
        (self.stage / 'licenses/README.md').write_text('Synthetic license index')

    def test_named_source_stage_excludes_runtime_data(self):
        extra = self.source / 'assets/models/123.json'
        extra.parent.mkdir(parents=True)
        extra.write_text('{"primitives":[]}')
        package.stage_sources(self.source, self.stage)
        self.assertFalse((self.stage / 'assets').exists())
        self.assertEqual({p.relative_to(self.stage).as_posix() for p in self.stage.rglob('*') if p.is_file()},
                         set(package.SOURCE_FILES) | {'THIRD-PARTY.md'})

    def test_valid_package_and_stray_asset_rejection(self):
        package.check_package(self.source, self.stage)
        for name in ('assets/models/123.json', 'assets/manifest.json', 'overlay/Fallout4.exe',
                     'art.svg', 'tools/extra.py', 'licenses/extra.json'):
            with self.subTest(name=name):
                path = self.stage / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic stray content')
                with self.assertRaises(ValueError):
                    package.check_package(self.source, self.stage)
                path.unlink()

    def test_links_rejected_in_stage_and_source(self):
        link = self.stage / 'assets'
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            package.check_package(self.source, self.stage)
        link.unlink()
        original = self.source / 'mod.json'
        original.unlink()
        original.symlink_to(self.root / 'THIRD-PARTY.md')
        with self.assertRaises(ValueError):
            package.stage_sources(self.source, self.stage)

    def test_missing_changed_or_wrong_binary_rejected(self):
        path = self.stage / 'mod.json'
        path.write_text('{"unexpected":"content"}')
        with self.assertRaises(ValueError):
            package.check_package(self.source, self.stage)
        path.unlink()
        with self.assertRaises(ValueError):
            package.check_package(self.source, self.stage)
        path.write_bytes((self.source / 'mod.json').read_bytes())
        (self.stage / 'host/pipboy-host').write_bytes(b'MZ synthetic Windows binary')
        with self.assertRaises(ValueError):
            package.check_package(self.source, self.stage)


if __name__ == '__main__':
    unittest.main()
