"""Real filesystem aliases must produce the same expected updater paths."""
import ctypes
import sys
import tempfile
import unittest
from pathlib import Path

from app.updater import UpdateStore
from tests.fixture_paths import fixture_root


class FixturePathTests(unittest.TestCase):
    def test_temp_root_matches_store_and_preserves_exact_path_assertions(self):
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            base = root / "original"
            base.mkdir()
            store = UpdateStore(base, root / "updates")
            self.assertEqual(store.active(), base)
            self.assertEqual(store.root, root / "updates")
            self.assertTrue(root.is_absolute())
            self.assertEqual(fixture_root(root / "."), root)

    def test_existing_directory_alias_matches_canonical_child(self):
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            actual = root / "long fixture directory name"
            actual.mkdir()
            if sys.platform == "win32":
                get_short_path = ctypes.windll.kernel32.GetShortPathNameW
                get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
                get_short_path.restype = ctypes.c_uint
                size = get_short_path(str(actual), None, 0)
                self.assertGreater(size, 0)
                result = ctypes.create_unicode_buffer(size)
                self.assertGreater(get_short_path(str(actual), result, size), 0)
                alias = Path(result.value)
            else:
                alias = root / "fixture-alias"
                alias.symlink_to(actual, target_is_directory=True)
            normalized = fixture_root(alias)
            base = normalized / "install"
            base.mkdir()
            self.assertEqual(normalized, actual)
            self.assertEqual(UpdateStore(alias / "install", root / "updates").active(), base)
            (alias / "marker").write_bytes(b"same physical directory")
            self.assertEqual((actual / "marker").read_bytes(), b"same physical directory")

    def test_missing_or_file_root_is_rejected_before_deriving_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            with self.assertRaises(FileNotFoundError):
                fixture_root(root / "missing")
            file = root / "file"
            file.write_bytes(b"file")
            with self.assertRaises(ValueError):
                fixture_root(file)


if __name__ == "__main__":
    unittest.main()
