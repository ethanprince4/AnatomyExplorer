"""Cluster identity of a model whose arrays are still in RAM: a file's first open saves its clusters and the second
open finds them, because the clusters built from the freshly decoded model and from the mapped (prepared) model are
the same arrays."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from app.gpu import cluster_cache, clusters as cl
from app.load_control import LoadToken
from app.viewer import prepared_cache

TOOTH = "tooth"            # a library model with detail levels (about 2 million triangles)
HOOKED = ("tooth", "tongue_papillae")      # the two models local_runtime has teaching hooks for
SKEL = Path("E:/Full Body Handoff 10-11-26/pipeline/out/male/app/library/skel/model.npz")     # the man's skeleton file


def write_model(path, bump=0.0):
    """A small valid model file of two wavy parts: a ribbon of 3000 x 4 squares, fine enough against the size of the
    model to get detail levels (app/viewer/lod.py), and a sheet of 70 x 70 squares, which gets none."""
    arrays = {"meta": np.frombuffer(json.dumps({"parts": [{"name": "ribbon"}, {"name": "sheet"}]}).encode(), np.uint8)}
    for i, (nu, nv, width) in enumerate(((3001, 5, 4.0 / 3000.0), (71, 71, 1.0))):
        v, u = np.meshgrid(np.linspace(0.0, width, nv), np.linspace(0.0, 1.0, nu))
        a = (np.arange(nu - 1)[:, None] * nv + np.arange(nv - 1)[None, :]).reshape(-1)
        z = 0.05 * np.sin(9.0 * u + i) * np.cos(7.0 * v) + 0.3 * i + bump
        arrays[f"p{i}"] = np.stack([u, v, z], axis=-1).reshape(-1, 3).astype(np.float32)
        arrays[f"i{i}"] = np.concatenate([np.stack([a, a + 1, a + nv], 1), np.stack([a + 1, a + nv + 1, a + nv], 1)]).astype(np.int32)
    np.savez_compressed(path, **arrays)
    return path


def open_file(path):
    from app.variants.catalog import DeferredVariantEntry
    from app.variants.local_library import SingleFileLibrary
    from app.viewer.model_loading import prepare_model
    store = SingleFileLibrary(str(path))
    model = prepare_model(DeferredVariantEntry(store.metadata(store.model_id), store), LoadToken())
    prepared_cache.wait_for_saves()
    return model


def open_library(model_id):
    from app.viewer.catalog import load_catalog
    from app.viewer.model_loading import prepare_model
    model = prepare_model(load_catalog()[model_id], LoadToken())
    prepared_cache.wait_for_saves()
    return model


def sha1s(cd):
    out = {}
    for name in cluster_cache._ARRAYS:
        array = np.ascontiguousarray(np.asarray(getattr(cd, name)))
        out[name] = (hashlib.sha1(array.data).hexdigest(), str(array.dtype), array.shape)
    return out


def model_sha1s(model):
    levels = hashlib.sha1()
    for pid in sorted(model.lod or {}):
        for level in model.lod[pid].indices:
            levels.update(np.ascontiguousarray(level).data)
    return (hashlib.sha1(np.ascontiguousarray(model.vertices).data).hexdigest(),
            hashlib.sha1(np.ascontiguousarray(model.indices).data).hexdigest(), levels.hexdigest())


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="cluster-identity-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        env = mock.patch.dict(os.environ, {"ANATOMY_PREPARED_CACHE": str(self.root / "prepared_models"),
                                           "ANATOMY_CLUSTER_CACHE": str(self.root / "clusters")})
        env.start()
        self.addCleanup(env.stop)
        self.prepared_root, self.cluster_root = self.root / "prepared_models", self.root / "clusters"
        saved = dict(prepared_cache._refused)
        prepared_cache._refused.clear()
        self.addCleanup(prepared_cache._refused.update, saved)
        self.addCleanup(prepared_cache._refused.clear)

    def entries(self, root):
        return sorted(p.name for p in root.iterdir() if (p / "meta.json").exists()) if root.exists() else []

    def first_and_second_open(self, opener):
        """What the two opens of one file give: (in-RAM model, its clusters from the store, mapped model, its clusters
        from the store), with every claim of the job checked on the way."""
        first = opener()
        self.assertIsNone(getattr(first.vertices, "filename", None), "the first open decodes into RAM")
        key = cluster_cache.make_key(first)
        self.assertTrue(key, "a model still in RAM has a cluster key")
        before = model_sha1s(first)
        built_in_ram = sha1s(cl.build_clusters(first, None))
        got_first = cluster_cache.get_clusters(first)
        self.assertEqual(got_first.stats["cached"], False)
        self.assertEqual(got_first.stats["saved"], True, "the first open saves its clusters")
        self.assertEqual(self.entries(self.cluster_root), [key])
        self.assertEqual(sha1s(got_first), built_in_ram)
        self.assertEqual(model_sha1s(first), before, "building and saving must not write into the model")

        second = opener()
        self.assertIsInstance(second.vertices, np.memmap, "the second open maps the prepared entry")
        self.assertEqual(second._prepared_key, first._prepared_key)
        self.assertEqual(cluster_cache.make_key(second), key)
        self.assertEqual(model_sha1s(second), before, "the mapped arrays are the arrays the first open had in RAM")
        built_mapped = sha1s(cl.build_clusters(second, None))
        for name in cluster_cache._ARRAYS:
            self.assertEqual(built_mapped[name], built_in_ram[name], f"{name} differs between the in-RAM and the mapped model")
        got_second = cluster_cache.get_clusters(second)
        self.assertEqual(got_second.stats["cached"], True, "the second open finds the clusters of the first")
        self.assertEqual(sha1s(got_second), built_in_ram)
        self.assertEqual(self.entries(self.cluster_root), [key])
        return first, got_first, second, got_second


class FirstOpenSavesSecondOpenFinds(StoreCase):
    def test_a_file_opened_on_its_own(self):
        path = write_model(self.root / "model.npz")
        first, got, second, _got = self.first_and_second_open(lambda: open_file(path))
        self.assertGreater(int(got.stats["clusters"]), 100)
        self.assertTrue(first.lod, "the test file is meant to have detail levels")
        self.assertGreater(got.n_ranges, len(first.parts), "and its clusters cover them")
        # the key follows the layout the clusters index: the same model before its detail levels exist is another key
        key = cluster_cache.make_key(second)
        with mock.patch.object(second, "lod", None):
            self.assertTrue(cluster_cache.make_key(second))
            self.assertNotEqual(cluster_cache.make_key(second), key)
        self.assertEqual(cluster_cache.make_key(second), key)

    def test_a_copy_of_the_file_in_another_folder_finds_the_same_clusters(self):
        path = write_model(self.root / "model.npz")
        first = open_file(path)
        self.assertEqual(cluster_cache.get_clusters(first).stats["saved"], True)
        (self.root / "elsewhere").mkdir()
        shutil.rmtree(self.prepared_root)                 # no prepared entry: the copy is decoded into RAM again
        copy = open_file(shutil.copy(path, self.root / "elsewhere" / "renamed.npz"))
        self.assertIsNone(getattr(copy.vertices, "filename", None))
        self.assertEqual(cluster_cache.get_clusters(copy).stats["cached"], True)

    def test_another_file_has_other_clusters(self):
        a = open_file(write_model(self.root / "a.npz"))
        b = open_file(write_model(self.root / "b.npz", bump=0.25))
        self.assertNotEqual(cluster_cache.make_key(a), cluster_cache.make_key(b))

    @unittest.skipUnless(SKEL.is_file(), "the man's skeleton file is not on this PC")
    def test_the_skeleton_of_the_man(self):
        _first, got, _second, _got = self.first_and_second_open(lambda: open_file(SKEL))
        self.assertGreater(int(got.stats["triangles"]), 1_000_000)

    def test_a_library_model_as_the_app_opens_it(self):
        from app.viewer.catalog import load_catalog
        if TOOTH not in load_catalog():
            self.skipTest(f"{TOOTH} is not in the library")
        first, _got, _second, _got2 = self.first_and_second_open(lambda: open_library(TOOTH))
        self.assertTrue(first.lod)

    def test_library_models_with_their_teaching_hooks(self):
        """Every library record is a static recipe today, which switches the model's hooks off (local_runtime:
        ``standalone``). Read the record as a live one, so that the hooks that run before the parts are joined and the
        teaching hook that runs on the finished model both take part, on the first open and on the mapped one."""
        from app.variants import local_runtime
        from app.variants.anatomy_runtime_adapters import runtime
        from app.viewer.catalog import load_catalog
        plain_get = local_runtime._get

        def live_record(value, key, default=None):
            return False if key == "static_recipe" else plain_get(value, key, default)

        for model_id in HOOKED:
            with self.subTest(model=model_id):
                if model_id not in load_catalog():
                    self.skipTest(f"{model_id} is not in the library")
                shutil.rmtree(self.cluster_root, ignore_errors=True)
                with mock.patch.object(local_runtime, "_get", live_record), \
                        mock.patch.object(runtime, "_hook", wraps=runtime._hook) as hook:
                    first, _got, second, _got2 = self.first_and_second_open(lambda: open_library(model_id))
                teaching = [c for c in hook.call_args_list if c.args == (model_id, "teaching")]
                self.assertGreaterEqual(len(teaching), 2, "the teaching hook ran on both opens")
                self.assertEqual(first.runtime_warnings, second.runtime_warnings)


class ModelsWithoutAnIdentity(StoreCase):
    def test_an_open_that_did_not_use_the_cache_is_built_every_time_and_never_saved(self):
        from app.variants import local_runtime
        from app.variants.catalog import DeferredVariantEntry
        from app.variants.local_library import SingleFileLibrary
        store = SingleFileLibrary(str(write_model(self.root / "model.npz")))
        model = local_runtime._prepare_local_model(DeferredVariantEntry(store.metadata(store.model_id), store), LoadToken(), False)
        self.assertIsNone(model._prepared_key)
        self.assertIsNone(cluster_cache.make_key(model))
        for _ in range(2):
            got = cluster_cache.get_clusters(model)
            self.assertEqual(got.stats["cached"], False)
            self.assertNotIn("saved", got.stats)
        self.assertEqual(self.entries(self.cluster_root), [])

    def test_a_model_no_loader_gave_a_key_has_none(self):
        model = SimpleNamespace(vertices=np.zeros((3, 19), np.float32), indices=np.arange(3, dtype=np.uint32), parts=[],
                                lod={}, anim_vertices=None)
        self.assertIsNone(cluster_cache.prepared_identity(model))
        self.assertIsNone(cluster_cache.make_key(model))
        model._prepared_key = "k" * 40
        self.assertEqual(cluster_cache.prepared_identity(model), "k" * 40)
        self.assertTrue(cluster_cache.make_key(model))

    def test_a_model_whose_layout_cannot_be_read_has_no_key(self):
        model = SimpleNamespace(_prepared_key="k" * 40, vertices=None, indices=None, parts=[], anim_vertices=None)
        self.assertIsNone(cluster_cache.make_key(model))


class TheKeyFollowsTheLayout(unittest.TestCase):
    def model(self, counts=(30, 60), levels=((30, 12), (60,)), shared=False):
        parts, lod, first, base = [], {}, 0, 0
        for pid, (count, sizes) in enumerate(zip(counts, levels), start=1):
            parts.append(SimpleNamespace(id=pid, first=first, count=count, vertex_base=base, vertex_count=count))
            arrays = [np.zeros(n, np.uint32) for n in sizes]
            if shared:
                arrays.append(arrays[-1])                 # a level that gained nothing repeats the one before
            lod[pid] = SimpleNamespace(indices=arrays)
            first, base = first + count, base + count
        return SimpleNamespace(_prepared_key="k" * 40, vertices=np.zeros((base, 19), np.float32),
                               indices=np.zeros(first, np.uint32), parts=parts, lod=lod, anim_vertices=None)

    def test_same_layout_same_key_and_any_other_layout_another_key(self):
        key = cluster_cache.make_key(self.model())
        self.assertTrue(key)
        self.assertEqual(key, cluster_cache.make_key(self.model()))
        others = [self.model(counts=(33, 60)),                          # a part's draw range
                  self.model(levels=((30, 9), (60,))),                  # the size of a detail level
                  self.model(levels=((30,), (60,))),                    # a level fewer
                  self.model(shared=True),                              # a repeated level
                  self.model(counts=(30,), levels=((30, 12),))]         # a part fewer
        keys = [cluster_cache.make_key(m) for m in others]
        self.assertTrue(all(keys))
        self.assertEqual(len(set(keys + [key])), len(others) + 1)
        bare = self.model()
        bare.lod = None                                                 # detail levels not built yet
        self.assertNotIn(cluster_cache.make_key(bare), [None, key])


if __name__ == "__main__":
    unittest.main()
