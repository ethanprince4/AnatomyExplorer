"""Prepared-model cache: a cached open gives exactly what the ordinary open gives, and trouble means "no cache"."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from app.load_control import LoadToken
from app.viewer import lod, prepared_cache
from app.viewer.model import Item, Part, Look, ViewerModel

MODEL = "tooth"            # the smallest library model that has LOD levels (about 2 million triangles)


def _open(model_id):
    from app.viewer.catalog import load_catalog
    from app.viewer.model_loading import prepare_model
    entry = load_catalog()[model_id]
    model = prepare_model(entry, LoadToken())
    prepared_cache.wait_for_saves()
    return model


def _same(test, a, b, path="model"):
    if isinstance(a, np.ndarray):
        test.assertIsInstance(b, np.ndarray, path)
        test.assertEqual(a.dtype, b.dtype, path)
        test.assertEqual(a.shape, b.shape, path)
        test.assertTrue(np.array_equal(a, b), path)
    elif isinstance(a, (list, tuple)):
        test.assertEqual(len(a), len(b), path)
        for i, (x, y) in enumerate(zip(a, b)):
            _same(test, x, y, f"{path}[{i}]")
    elif isinstance(a, dict):
        test.assertEqual(list(a), list(b), path)
        for k in a:
            _same(test, a[k], b[k], f"{path}.{k}")
    else:
        test.assertEqual(a, b, path)


def _part_state(p):
    return [p.id, p.node, p.name, p.mesh_name, p.material_name, p.structure, p.label, p.look, p.first, p.count,
            p.vertex_base, p.vertex_count, p.has_morph, p.has_fibre, p.local_centre, p.local_radius, p.local_min,
            p.local_max, p.visible, p.role, p.item]


class CachedOpenIsIdentical(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.viewer.catalog import load_catalog
        if MODEL not in load_catalog():
            raise unittest.SkipTest(f"{MODEL} is not in the library")
        cls.folder = Path(tempfile.mkdtemp(prefix="prepared-cache-test-"))
        cls._env = mock.patch.dict(os.environ, {"ANATOMY_PREPARED_CACHE": str(cls.folder)})
        cls._env.start()
        cls.first = _open(MODEL)                       # writes the cache
        cls.entries = [p for p in cls.folder.iterdir() if (p / "meta.json").exists()]
        cls.second = _open(MODEL)                      # reads it
        with mock.patch.dict(os.environ, {"ANATOMY_PREPARED_CACHE": "off"}):
            cls.plain = _open(MODEL)                   # never touches it

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()
        del cls.first, cls.second, cls.plain
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_first_open_wrote_one_entry_of_plain_npy_files(self):
        self.assertEqual(len(self.entries), 1)
        names = {p.name for p in self.entries[0].iterdir()}
        self.assertTrue({"vertices.npy", "indices.npy", "meta.json"} <= names)

    def test_second_open_used_the_cache(self):
        self.assertIsInstance(self.second.vertices, np.memmap)
        self.assertNotIsInstance(self.plain.vertices, np.memmap)

    def test_every_array_matches_the_uncached_open(self):
        for other in (self.first, self.second):
            _same(self, np.asarray(self.plain.vertices), np.asarray(other.vertices), "vertices")
            _same(self, np.asarray(self.plain.indices), np.asarray(other.indices), "indices")
            self.assertEqual(sorted(self.plain.lod), sorted(other.lod))
            for pid, level in self.plain.lod.items():
                _same(self, level.cells, other.lod[pid].cells, f"lod[{pid}].cells")
                _same(self, [np.asarray(a) for a in level.indices], [np.asarray(a) for a in other.lod[pid].indices],
                      f"lod[{pid}].indices")
            _same(self, self.plain.bounds_min, other.bounds_min, "bounds_min")
            _same(self, self.plain.bounds_max, other.bounds_max, "bounds_max")

    def test_parts_items_and_metadata_match_the_uncached_open(self):
        for other in (self.first, self.second):
            _same(self, [_part_state(p) for p in self.plain.parts], [_part_state(p) for p in other.parts], "parts")
            _same(self, [{**vars(i), "parts": [q.id for q in i.parts]} for i in self.plain.items],
                  [{**vars(i), "parts": [q.id for q in i.parts]} for i in other.items], "items")
            _same(self, [vars(g) for g in self.plain.groups], [vars(g) for g in other.groups], "groups")
            self.assertEqual(self.plain.runtime_warnings, other.runtime_warnings)
            self.assertEqual(self.plain.metres_per_unit, other.metres_per_unit)
            self.assertEqual(self.plain.sidecar, other.sidecar)
            self.assertEqual(self.plain.cameras, other.cameras)
            self.assertEqual(self.plain.triangle_count, other.triangle_count)

    def test_a_changed_source_file_is_a_different_key(self):
        path = Path(__file__)
        base = prepared_cache.make_key(path)
        self.assertEqual(base, prepared_cache.make_key(path))
        with mock.patch.object(prepared_cache, "_stat", return_value=[1, 2]):
            self.assertNotEqual(base, prepared_cache.make_key(path))
        with mock.patch.object(prepared_cache, "FORMAT_VERSION", prepared_cache.FORMAT_VERSION + 1):
            self.assertNotEqual(base, prepared_cache.make_key(path))
        self.assertNotEqual(base, prepared_cache.make_key(path, retired=["x"]))

    def test_a_damaged_entry_falls_back_to_a_normal_open(self):
        entry = self.entries[0]
        copy = Path(tempfile.mkdtemp(prefix="prepared-cache-damaged-"))
        try:
            shutil.copytree(entry, copy / entry.name)
            (copy / entry.name / "indices.npy").write_bytes(b"not an array")
            with mock.patch.dict(os.environ, {"ANATOMY_PREPARED_CACHE": str(copy)}):
                model = _open(MODEL)
            self.assertTrue(np.array_equal(np.asarray(model.vertices), np.asarray(self.plain.vertices)))
            # the damaged entry was replaced by a good one
            self.assertEqual(np.load(copy / entry.name / "indices.npy", mmap_mode="r").shape, self.plain.indices.shape)
        finally:
            shutil.rmtree(copy, ignore_errors=True)


class CacheFolderRules(unittest.TestCase):
    def test_least_recently_used_entries_go_first_and_the_cap_holds(self):
        root = Path(tempfile.mkdtemp(prefix="prepared-cache-prune-"))
        try:
            for i, name in enumerate(("old", "mid", "new")):
                folder = root / name
                folder.mkdir()
                (folder / "vertices.npy").write_bytes(b"x" * 1000)
                (folder / "meta.json").write_text("{}")
                os.utime(folder / "meta.json", (1000 + i, 1000 + i))
            prepared_cache.prune(root, cap=2100)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["mid", "new"])
            prepared_cache.prune(root, keep="mid", cap=1)
            self.assertEqual([p.name for p in root.iterdir()], ["mid"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_off_and_unwritable_locations_mean_no_cache(self):
        with mock.patch.dict(os.environ, {"ANATOMY_PREPARED_CACHE": "off"}):
            self.assertIsNone(prepared_cache.cache_root())
            self.assertIsNone(prepared_cache.lookup("abc"))
        with mock.patch.dict(os.environ, {"ANATOMY_PREPARED_CACHE": str(Path(tempfile.gettempdir()) / "nope" / "x")}):
            self.assertIsNone(prepared_cache.lookup("abc"))

    def test_default_folder_is_per_user_and_not_under_the_repository(self):
        with mock.patch.dict(os.environ, {"ANATOMY_PREPARED_CACHE": ""}):
            root = prepared_cache.cache_root()
        from app import config
        self.assertIsNotNone(root)
        self.assertFalse(Path(root).resolve().is_relative_to(config.ROOT))


class UnchangedResults(unittest.TestCase):
    def test_float64_normals_match_the_np_add_at_version(self):
        from app.variants.local_runtime import _normals
        rng = np.random.default_rng(3)
        verts = rng.normal(size=(500, 3)).astype(np.float32)
        faces = rng.integers(0, 500, size=(3000, 3)).astype(np.int64)
        tri = verts[faces].astype(np.float64)
        cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        expect = np.zeros((500, 3))
        for i in range(3):
            np.add.at(expect, faces[:, i], cross)
        length = np.linalg.norm(expect, axis=1)
        good = length > 0
        expect[good] /= length[good, None]
        expect[~good] = [0, 0, 1]
        self.assertTrue(np.array_equal(_normals(verts, faces), expect.astype(np.float32)))

    def test_parallel_lod_equals_serial(self):
        from tests.test_viewer_lod import sphere
        pos_a, tri_a = sphere(120)
        pos_b, tri_b = sphere(90, base=len(pos_a))
        model = ViewerModel()
        model.vertices = np.zeros((len(pos_a) + len(pos_b), 19), np.float32)
        model.vertices[:len(pos_a), :3] = pos_a
        model.vertices[len(pos_a):, :3] = pos_b
        model.indices = np.concatenate([tri_a.ravel(), tri_b.ravel()]).astype(np.uint32)
        model.bounds_min, model.bounds_max = np.full(3, -500.0), np.full(3, 500.0)   # a pixel is wide enough to cluster
        for pid, (tris, base, n) in enumerate([(tri_a, 0, len(pos_a)), (tri_b, len(pos_a), len(pos_b))], 1):
            part = Part(id=pid, node=0, name=f"p{pid}", mesh_name="", material_name="", structure="", structure_id="",
                        label="", extras={}, look=Look())
            part.first = 0 if pid == 1 else tri_a.size
            part.count, part.vertex_base, part.vertex_count = tris.size, base, n
            model.parts.append(part)
        with mock.patch.object(lod, "WORKERS", 1):
            serial = lod.build(model)
        with mock.patch.object(lod, "WORKERS", 3):
            parallel = lod.build(model)
        self.assertTrue(serial)
        self.assertEqual(list(serial), list(parallel))
        for pid in serial:
            _same(self, serial[pid].cells, parallel[pid].cells)
            _same(self, serial[pid].indices, parallel[pid].indices)

    def test_group_sort_key_matches_the_linear_search(self):
        from app.viewer.model import Model
        model = object.__new__(Model)
        ViewerModel.__init__(model)
        for i, (group, sid) in enumerate([("B", "S10"), ("A", "S02"), ("B", "S03"), ("C", ""), ("D", "x")]):
            part = SimpleNamespace(structure_id=sid)
            model.items.append(Item(index=i, key=str(i), name=str(i), group=group, parts=[part]))
        model.items.append(Item(index=5, key="5", name="5", group="E", parts=[]))

        def old(title):
            import re
            for it in model.items:
                if it.group == title and it.parts:
                    m = re.match(r"S(\d+)$", it.parts[0].structure_id or "")
                    if m:
                        return (0, int(m.group(1)), title)
                    break
            return (1, 0, title)
        model._build_groups(order=model._group_sid)
        for title in "ABCDEZ":
            self.assertEqual(model._group_sid(title), old(title), title)
        self.assertEqual([g.key for g in model.groups], ["A", "B", "C", "D", "E"])


if __name__ == "__main__":
    unittest.main()
