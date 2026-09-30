"""Damaged derived atlas caches must recover without disabling study aids."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.depth import DepthIndex
from app.relations import geometry_stamp, sample_points
from app.cache_io import save_npz


class AtlasCacheRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="anatomy-atlas-cache-")
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        dtype = np.dtype([("pos", "<f4", (3,)), ("normal", "<f4", (3,)),
                          ("structure", "<u2"), ("material", "<u2")])
        verts = np.zeros(3, dtype=dtype)
        verts["pos"] = [[0, 0, 0], [0.02, 0, 0], [0, 0.02, 0]]
        verts["normal"] = [0, 0, 1]
        verts.tofile(root / "vertices.bin")
        np.array([0, 1, 2], dtype="<u4").tofile(root / "indices.bin")
        self.ds = SimpleNamespace(dir=root, n=1, findings=None,
                                  structures=[{"id": 0, "i_start": 0, "i_count": 3, "system": "regions"}])

    def damaged(self, filename, kind):
        path = self.ds.dir / filename
        if kind == "empty":
            path.write_bytes(b"")
        else:
            np.savez(path, stamp=geometry_stamp(self.ds), dummy=np.arange(8))
            path.write_bytes(path.read_bytes()[:-20])

    def test_empty_and_truncated_surface_samples_are_rebuilt(self):
        for kind in ("empty", "truncated"):
            with self.subTest(kind=kind):
                self.damaged("samples.npz", kind)
                points, offsets = sample_points(self.ds)
                np.testing.assert_array_equal(offsets, [0, 3])
                np.testing.assert_allclose(points, [[0, 0, 0], [0.02, 0, 0], [0, 0.02, 0]])
                with np.load(self.ds.dir / "samples.npz") as archive:
                    np.testing.assert_array_equal(archive["stamp"], geometry_stamp(self.ds))
                    np.testing.assert_array_equal(archive["points"], points)

    def test_empty_and_truncated_depth_caches_keep_dissection_available(self):
        for kind in ("empty", "truncated"):
            with self.subTest(kind=kind):
                self.damaged("depth.npz", kind)
                index = DepthIndex(self.ds)
                index._run()
                self.assertTrue(index.ready)
                self.assertFalse(index.failed)
                np.testing.assert_array_equal(index.depth, [0.0])
                np.testing.assert_array_equal(index.absolute, [0.0])
                with np.load(self.ds.dir / "depth.npz") as archive:
                    np.testing.assert_array_equal(archive["stamp"], geometry_stamp(self.ds))
                    np.testing.assert_array_equal(archive["depth"], index.depth)

    def test_failed_atomic_replace_keeps_previous_cache_bytes(self):
        path = self.ds.dir / "safe.npz"
        save_npz(path, value=np.array([1, 2, 3]))
        original = path.read_bytes()
        with patch("app.cache_io.os.replace", side_effect=OSError("simulated file lock")):
            with self.assertRaises(OSError):
                save_npz(path, value=np.array([4, 5, 6]))
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(self.ds.dir.glob(".safe-*.npz")))

    def test_failed_serialization_keeps_previous_cache_bytes(self):
        path = self.ds.dir / "safe.npz"
        save_npz(path, value=np.array([1, 2, 3]))
        original = path.read_bytes()
        with patch("app.cache_io.np.savez", side_effect=ValueError("simulated serialization failure")):
            with self.assertRaises(ValueError):
                save_npz(path, value=np.array([4, 5, 6]))
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(self.ds.dir.glob(".safe-*.npz")))


if __name__ == "__main__":
    unittest.main()
