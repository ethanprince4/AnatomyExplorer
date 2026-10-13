"""The prepared-model and cluster stores: what a key depends on, and that a save can never leave a bad entry behind."""
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from app.gpu import cluster_cache
from app.load_control import LoadToken
from app.viewer import prepared_cache
from app.viewer.model import VERTEX_FLOATS

Usage = namedtuple("Usage", "total used free")
GIB = 1 << 30
TOOTH = Path(__file__).resolve().parents[1] / "data" / "local_model_library" / "models" / "tooth" / "v4" / "model.npz"


def write_npz(path, change=None):
    arrays = {"meta": np.frombuffer(b'{"parts": [{"name": "a"}]}', dtype=np.uint8),
              "p0": np.arange(300, dtype=np.float32), "f0": np.arange(90, dtype=np.int32)}
    if change:
        arrays[change] = arrays[change].copy()
        arrays[change][7] += 1                      # one value of one member; every size stays the same
    np.savez_compressed(path, **arrays)
    return path


def fake_model(seed=0, n=40, tris=60):
    rng = np.random.default_rng(seed)
    vertices = rng.normal(size=(n, VERTEX_FLOATS)).astype(np.float32)
    indices = rng.integers(0, n, size=tris * 3).astype(np.uint32)
    lo, hi = vertices[:, :3].min(0), vertices[:, :3].max(0)
    return SimpleNamespace(vertices=vertices, indices=indices, parts=[SimpleNamespace(name="p1", id=1)],
                           _geom_log=[(0, indices.size, 0, n, lo, hi, (lo + hi) / 2, 1.0)], _finish_bounds=(lo, hi),
                           lod={1: SimpleNamespace(cells=[0.5, 1.0], indices=[indices, indices[:30].copy()])})


def plan_for(key, n=40, tris=60):
    return dict(key=key, source=dict(path="somewhere"), decode=[(n, tris, False)], warnings=[])


def fake_clusters(seed=0):
    rng = np.random.default_rng(seed)
    cd = SimpleNamespace(stats={"clusters": 3})
    for i, name in enumerate(cluster_cache._ARRAYS):
        setattr(cd, name, rng.integers(0, 1000, size=5 + i).astype(np.int32))
    return cd


def snapshot(folder):
    return {f.name: (f.read_bytes(), f.stat().st_mtime_ns) for f in sorted(folder.iterdir())}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="cache-safe-test-"))
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

    def temp_folders(self, root):
        return [p.name for p in root.iterdir() if p.name.startswith(".tmp-")] if root.exists() else []


class KeyFollowsContentNotPlace(StoreCase):
    def test_a_copied_file_under_another_path_has_the_same_key(self):
        a, b = self.root / "one", self.root / "two" / "deeper"
        a.mkdir()
        b.mkdir(parents=True)
        first = write_npz(a / "model.npz")
        second = Path(shutil.copy(first, b / "renamed.npz"))
        os.utime(second, (1_000_000, 1_000_000))                     # another modified time as well
        key = prepared_cache.make_key(first)
        self.assertTrue(key)
        self.assertEqual(key, prepared_cache.make_key(second))
        self.assertEqual(prepared_cache.source_identity(first)[0], "zip")

    def test_copied_companions_keep_the_key_and_a_changed_companion_changes_it(self):
        keys = []
        for name in ("one", "two"):
            folder = self.root / name
            folder.mkdir()
            write_npz(folder / "model.npz")
            write_npz(folder / "vertex_colors.npz")
            (folder / "catalog.json").write_text('{"parts": {}}', encoding="utf-8")
            keys.append(prepared_cache.make_key(folder / "model.npz", [("catalog", folder / "catalog.json"),
                                                                       ("colors", folder / "vertex_colors.npz")]))
        self.assertEqual(keys[0], keys[1])
        folder = self.root / "two"
        companions = [("catalog", folder / "catalog.json"), ("colors", folder / "vertex_colors.npz")]
        (folder / "catalog.json").write_text('{"parts": {"a": 1}}', encoding="utf-8")
        changed_json = prepared_cache.make_key(folder / "model.npz", companions)
        self.assertNotEqual(keys[0], changed_json)
        write_npz(folder / "vertex_colors.npz", change="p0")
        self.assertNotEqual(changed_json, prepared_cache.make_key(folder / "model.npz", companions))
        self.assertNotEqual(keys[0], prepared_cache.make_key(folder / "model.npz", companions[:1]))

    def test_one_changed_member_is_another_key(self):
        first = write_npz(self.root / "a.npz")
        second = write_npz(self.root / "b.npz", change="p0")
        self.assertEqual(first.stat().st_size > 0, True)
        self.assertNotEqual(prepared_cache.zip_directory_digest(first), prepared_cache.zip_directory_digest(second))
        self.assertNotEqual(prepared_cache.make_key(first), prepared_cache.make_key(second))

    def test_the_library_model_that_opens_a_file_is_part_of_the_key(self):
        path = write_npz(self.root / "a.npz")
        alone = prepared_cache.make_key(path)
        self.assertNotEqual(alone, prepared_cache.make_key(path, owner=["tooth", False]))
        self.assertNotEqual(prepared_cache.make_key(path, owner=["tooth", False]),
                            prepared_cache.make_key(path, owner=["kidney", False]))

    def test_changed_text_of_a_shaping_source_file_is_another_key(self):
        folder = self.root / "code"
        folder.mkdir()
        name = "shaping_probe_" + self.root.name.replace("-", "_")
        source = folder / f"{name}.py"
        source.write_text("LEVELS = 3\n", encoding="utf-8")
        sys.path.insert(0, str(folder))
        self.addCleanup(sys.path.remove, str(folder))
        self.addCleanup(prepared_cache._code_ids.clear)
        path = write_npz(self.root / "a.npz")
        model = SimpleNamespace(vertices=np.zeros((0, VERTEX_FLOATS), np.float32), indices=np.zeros(0, np.uint32),
                                parts=[], anim_vertices=None)
        with mock.patch.object(prepared_cache, "SHAPING_MODULES", (name,)), \
                mock.patch.object(cluster_cache, "SHAPING_MODULES", (name,)), \
                mock.patch.object(cluster_cache, "prepared_identity", return_value="p" * 40):
            importlib.invalidate_caches()
            before = prepared_cache.make_key(path), cluster_cache.make_key(model)
            self.assertEqual(before, (prepared_cache.make_key(path), cluster_cache.make_key(model)))
            source.write_text("LEVELS = 4\n", encoding="utf-8")
            prepared_cache._code_ids.clear()             # what a restart of the program does
            after = prepared_cache.make_key(path), cluster_cache.make_key(model)
            source.write_bytes(b"LEVELS = 4\r\n")       # the same text with other line ends is the same code
            prepared_cache._code_ids.clear()
            self.assertEqual(after, (prepared_cache.make_key(path), cluster_cache.make_key(model)))
        self.assertTrue(all(before) and all(after))
        self.assertNotEqual(before[0], after[0])
        self.assertNotEqual(before[1], after[1])

    def test_the_real_shaping_modules_can_be_read(self):
        prepared_cache._code_ids.clear()
        self.assertEqual(len(prepared_cache.code_id(prepared_cache.SHAPING_MODULES)), 16)
        self.assertEqual(len(prepared_cache.code_id(cluster_cache.SHAPING_MODULES)), 16)

    def test_a_shaping_module_that_cannot_be_read_means_no_cache_not_an_error(self):
        path = write_npz(self.root / "a.npz")
        prepared_cache._code_ids.clear()
        self.addCleanup(prepared_cache._code_ids.clear)
        with mock.patch.object(prepared_cache, "SHAPING_MODULES", ("no_such_module_anywhere",)):
            self.assertIsNone(prepared_cache.make_key(path))

    @unittest.skipUnless(TOOTH.is_file(), "the tooth model file is not in this copy")
    def test_a_copy_of_a_model_file_opens_from_the_entry_of_the_original(self):
        from app.variants.catalog import DeferredVariantEntry
        from app.variants.local_library import SingleFileLibrary
        from app.viewer.model_loading import prepare_model
        models = []
        for name in ("first place", "second place"):
            folder = self.root / name
            folder.mkdir()
            store = SingleFileLibrary(str(shutil.copy(TOOTH, folder / "model.npz")))
            models.append(prepare_model(DeferredVariantEntry(store.metadata(store.model_id), store), LoadToken()))
            prepared_cache.wait_for_saves()
        self.assertNotIsInstance(models[0].vertices, np.memmap)
        self.assertIsInstance(models[1].vertices, np.memmap)
        self.assertEqual(len([p for p in self.prepared_root.iterdir() if (p / "meta.json").exists()]), 1)
        self.assertTrue(np.array_equal(np.asarray(models[0].vertices), np.asarray(models[1].vertices)))
        self.assertTrue(np.array_equal(np.asarray(models[0].indices), np.asarray(models[1].indices)))
        del models


class PreparedStoreSavesSafely(StoreCase):
    KEY = "k" * 40

    def save(self, seed=0):
        return prepared_cache._save(fake_model(seed), plan_for(self.KEY))

    def test_a_save_round_trips_and_records_every_file_size(self):
        self.assertTrue(self.save())
        entry = prepared_cache.lookup(self.KEY)
        self.assertIsNotNone(entry)
        self.assertTrue(np.array_equal(np.asarray(entry.vertices), fake_model().vertices))
        meta = json.loads((self.prepared_root / self.KEY / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(meta["files"]), ["indices.npy", "lod.npy", "vertices.npy"])
        for name, size in meta["files"].items():
            self.assertEqual((self.prepared_root / self.KEY / name).stat().st_size, size)
        self.assertEqual(meta["code"], prepared_cache.code_id(prepared_cache.SHAPING_MODULES))
        self.assertEqual(self.temp_folders(self.prepared_root), [])
        del entry

    def test_every_file_is_flushed_and_meta_is_written_last(self):
        order = []
        real_fsync, real_replace = os.fsync, os.replace

        def fsync(fd):
            order.append("fsync")
            return real_fsync(fd)

        def replace(a, b):
            order.append("rename")
            self.assertTrue((Path(a) / "meta.json").exists())
            return real_replace(a, b)

        real_meta, real_array = prepared_cache.write_meta, prepared_cache.write_array
        with mock.patch.object(prepared_cache.os, "fsync", fsync), mock.patch.object(prepared_cache.os, "replace", replace), \
                mock.patch.object(prepared_cache, "write_meta", lambda *a: (order.append("meta"), real_meta(*a))[1]), \
                mock.patch.object(prepared_cache, "write_array", lambda *a: (order.append("array"), real_array(*a))[1]):
            self.assertTrue(self.save())
        self.assertEqual(order[:9], ["array", "fsync", "array", "fsync", "array", "fsync", "meta", "fsync", "rename"])

    def test_a_save_cut_off_before_meta_leaves_nothing_an_open_accepts(self):
        with mock.patch.object(prepared_cache, "write_meta", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):               # the process dying: nothing gets to tidy up
                with mock.patch.object(prepared_cache, "remove_entry", return_value=False):
                    prepared_cache._write(fake_model(), plan_for(self.KEY), self.prepared_root, self.KEY)
        left = self.temp_folders(self.prepared_root)
        self.assertEqual(len(left), 1)                               # the arrays are there, in a temporary folder
        self.assertTrue((self.prepared_root / left[0] / "vertices.npy").exists())
        self.assertFalse((self.prepared_root / self.KEY).exists())
        self.assertIsNone(prepared_cache.lookup(self.KEY))
        self.assertIsNone(prepared_cache._read_entry(self.prepared_root / left[0], self.KEY))
        # the same folder under the final name (a rename that outlived the cut) is still not an entry
        os.replace(self.prepared_root / left[0], self.prepared_root / self.KEY)
        self.assertIsNone(prepared_cache.lookup(self.KEY))
        # and the next save puts a good entry there
        self.assertTrue(self.save())
        self.assertIsNotNone(prepared_cache.lookup(self.KEY))

    def test_a_failed_write_cleans_up_and_is_not_tried_again(self):
        with mock.patch.object(prepared_cache, "write_meta", side_effect=OSError("disk went away")):
            self.assertFalse(self.save())
        self.assertEqual(self.temp_folders(self.prepared_root), [])
        self.assertIsNone(prepared_cache.lookup(self.KEY))
        self.assertIn("disk went away", prepared_cache.refused(self.prepared_root, self.KEY))
        with mock.patch.object(prepared_cache, "write_array") as writer:
            self.assertFalse(self.save())
            writer.assert_not_called()

    def test_a_second_writer_leaves_the_first_entry_untouched(self):
        self.assertTrue(self.save(seed=0))
        before = snapshot(self.prepared_root / self.KEY)
        with mock.patch.object(prepared_cache, "write_array") as writer:
            self.assertTrue(self.save(seed=1))                       # sees the good entry: writes nothing
            writer.assert_not_called()
        # a writer that started before the first one finished: it has written its own folder and then finds the entry
        real_exists, calls = Path.exists, []

        def exists(path):
            if path == self.prepared_root / self.KEY and not calls:
                calls.append(1)
                return False                                         # "not there yet" when the late writer starts
            return real_exists(path)

        with mock.patch.object(Path, "exists", exists), mock.patch.object(prepared_cache.shutil, "rmtree",
                                                                          wraps=shutil.rmtree) as rmtree:
            self.assertTrue(self.save(seed=1))
        self.assertTrue(calls)
        removed = [str(c.args[0]) for c in rmtree.call_args_list]
        self.assertEqual(len(removed), 1)
        self.assertIn(".tmp-", removed[0])                           # only its own temporary folder
        self.assertEqual(snapshot(self.prepared_root / self.KEY), before)
        self.assertEqual(self.temp_folders(self.prepared_root), [])
        entry = prepared_cache.lookup(self.KEY)
        self.assertTrue(np.array_equal(np.asarray(entry.vertices), fake_model(0).vertices))
        del entry

    def test_a_wrong_file_size_gives_no_entry(self):
        self.assertTrue(self.save())
        target = self.prepared_root / self.KEY / "indices.npy"
        good = target.read_bytes()
        for damaged in (good + b"\0", good[:-4], b""):
            target.write_bytes(damaged)
            self.assertIsNone(prepared_cache.lookup(self.KEY))
        target.write_bytes(good)
        self.assertIsNotNone(prepared_cache.lookup(self.KEY))
        target.unlink()
        self.assertIsNone(prepared_cache.lookup(self.KEY))

    def test_an_entry_written_before_sizes_were_recorded_is_not_taken(self):
        self.assertTrue(self.save())
        meta_path = self.prepared_root / self.KEY / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for old in ({k: v for k, v in meta.items() if k != "files"}, {**meta, "files": {}}, {**meta, "files": None},
                    {**meta, "version": 1}):
            meta_path.write_text(json.dumps(old), encoding="utf-8")
            self.assertIsNone(prepared_cache.lookup(self.KEY))
        meta_path.write_text("{ not json", encoding="utf-8")
        self.assertIsNone(prepared_cache.lookup(self.KEY))
        self.assertTrue(self.save(seed=2))                           # the unusable entry is replaced, not kept
        entry = prepared_cache.lookup(self.KEY)
        self.assertTrue(np.array_equal(np.asarray(entry.vertices), fake_model(2).vertices))
        del entry

    def test_the_guard_refuses_under_the_free_floor_and_the_refusal_is_remembered(self):
        tight = Usage(total=500 * GIB, used=450 * GIB, free=50 * GIB)        # floor is 10 % = 50 GiB
        with mock.patch.object(prepared_cache, "_disk_usage", return_value=tight), \
                mock.patch.object(prepared_cache, "write_array") as writer:
            self.assertFalse(self.save())
            writer.assert_not_called()
        self.assertFalse((self.prepared_root / self.KEY).exists())
        self.assertEqual(self.temp_folders(self.prepared_root), [])
        self.assertIn("free disk space", prepared_cache.refused(self.prepared_root, self.KEY))
        roomy = Usage(total=500 * GIB, used=100 * GIB, free=400 * GIB)
        with mock.patch.object(prepared_cache, "_disk_usage", return_value=roomy) as usage, \
                mock.patch.object(prepared_cache, "write_array") as writer:
            self.assertFalse(self.save())                            # remembered: not even asked again
            usage.assert_not_called()
            writer.assert_not_called()
            model = fake_model()
            model._prepared_plan = plan_for(self.KEY)
            with mock.patch.object(prepared_cache, "eligible", return_value=True), \
                    mock.patch.object(prepared_cache.threading, "Thread") as thread:
                prepared_cache.save_async(model)
                thread.assert_not_called()
        other = "m" * 40                                             # another key is not held back by it
        self.assertTrue(prepared_cache._save(fake_model(), plan_for(other)))
        self.assertIsNotNone(prepared_cache.lookup(other))

    def test_the_floor_is_the_larger_of_ten_gib_and_a_tenth_of_the_volume(self):
        cases = [(Usage(500 * GIB, 0, 51 * GIB), GIB // 2, True), (Usage(500 * GIB, 0, 51 * GIB), 2 * GIB, False),
                 (Usage(40 * GIB, 0, 11 * GIB), GIB // 2, True), (Usage(40 * GIB, 0, 11 * GIB), 2 * GIB, False),
                 (Usage(40 * GIB, 0, 9 * GIB), 0, False), (Usage(2000 * GIB, 0, 199 * GIB), 0, False)]
        for usage, need, expect in cases:
            with mock.patch.object(prepared_cache, "_disk_usage", return_value=usage):
                self.assertEqual(prepared_cache.disk_allows(self.root, need), expect, (usage, need))
        with mock.patch.object(prepared_cache, "_disk_usage", side_effect=OSError("no such volume")):
            self.assertFalse(prepared_cache.disk_allows(self.root, 0))
        self.assertTrue(prepared_cache._disk_usage(self.root / "not" / "made" / "yet").total > 0)

    def test_removal_moves_the_entry_aside_then_takes_meta_first_and_touches_nothing_when_it_cannot_move_it(self):
        self.assertTrue(self.save())
        folder = self.prepared_root / self.KEY
        with mock.patch.object(prepared_cache.shutil, "rmtree"):     # moved aside, but the rest cannot be deleted
            self.assertTrue(prepared_cache.remove_entry(folder))     # no entry is left under the key
        self.assertFalse(folder.exists())
        left = self.temp_folders(self.prepared_root)
        self.assertEqual(len(left), 1)
        self.assertTrue(left[0].startswith(".tmp-gone-"))
        self.assertFalse((self.prepared_root / left[0] / "meta.json").exists())
        self.assertTrue((self.prepared_root / left[0] / "vertices.npy").exists())
        self.assertIsNone(prepared_cache.lookup(self.KEY))
        self.assertTrue(prepared_cache.remove_entry(folder))         # nothing there: nothing to do
        self.assertTrue(self.save())                                 # the key is saved again, the leftover cleared
        self.assertEqual(self.temp_folders(self.prepared_root), [])
        before = snapshot(folder)
        with mock.patch.object(prepared_cache.os, "rename", side_effect=PermissionError("a file is mapped")), \
                mock.patch.object(Path, "unlink") as unlink, mock.patch.object(prepared_cache.shutil, "rmtree") as rmtree:
            self.assertFalse(prepared_cache.remove_entry(folder))
            unlink.assert_not_called()
            rmtree.assert_not_called()
        self.assertEqual(snapshot(folder), before)
        self.assertIsNotNone(prepared_cache.lookup(self.KEY))
        temp = self.prepared_root / ".tmp-some-writer"               # a temporary folder goes where it lies, meta first
        os.replace(folder, temp)
        with mock.patch.object(prepared_cache.shutil, "rmtree"):
            self.assertFalse(prepared_cache.remove_entry(temp))
        self.assertEqual(self.temp_folders(self.prepared_root), [temp.name])
        self.assertFalse((temp / "meta.json").exists())
        self.assertTrue((temp / "vertices.npy").exists())
        self.assertTrue(prepared_cache.remove_entry(temp))
        self.assertEqual(self.temp_folders(self.prepared_root), [])

    def test_prune_removes_meta_first(self):
        self.assertTrue(self.save())
        with mock.patch.object(prepared_cache.shutil, "rmtree"):
            prepared_cache.prune(self.prepared_root, cap=0)
        self.assertFalse((self.prepared_root / self.KEY).exists())
        left = self.temp_folders(self.prepared_root)
        self.assertEqual(len(left), 1)
        self.assertFalse((self.prepared_root / left[0] / "meta.json").exists())
        self.assertTrue((self.prepared_root / left[0] / "vertices.npy").exists())
        self.assertIsNone(prepared_cache.lookup(self.KEY))

    def test_a_model_file_whose_entry_lost_its_end_opens_right_and_the_entry_is_replaced(self):
        from app.variants.catalog import DeferredVariantEntry
        from app.variants.local_library import SingleFileLibrary
        from app.viewer.model_loading import prepare_model
        store = SingleFileLibrary(str(shutil.copy(TOOTH, self.root / "model.npz")))

        def opened():
            model = prepare_model(DeferredVariantEntry(store.metadata(store.model_id), store), LoadToken())
            prepared_cache.wait_for_saves()
            return model

        first = opened()
        good = (np.array(first.vertices), np.array(first.indices))
        entries = [p for p in self.prepared_root.iterdir() if (p / "meta.json").exists()]
        self.assertEqual(len(entries), 1)
        for name in ("vertices.npy", "indices.npy"):
            del first
            target = entries[0] / name
            size, whole = target.stat().st_size, target.read_bytes()
            with open(target, "r+b") as fh:                          # the size is right, the content from 4 KiB on is zeros
                fh.seek(4096)
                fh.write(b"\0" * (size - 4096))
            again = opened()
            self.assertNotIsInstance(again.vertices, np.memmap, name)        # a miss: built from the file ...
            self.assertTrue(np.array_equal(np.asarray(again.vertices), good[0]), name)
            self.assertTrue(np.array_equal(np.asarray(again.indices), good[1]), name)
            self.assertEqual(target.read_bytes(), whole, name)               # ... and the entry was replaced on that open
            first = opened()
            self.assertIsInstance(first.vertices, np.memmap, name)
            self.assertTrue(np.array_equal(np.asarray(first.vertices), good[0]), name)
        del first, again


class ClusterStoreSavesSafely(StoreCase):
    KEY = "c" * 40

    def test_a_save_round_trips_with_sizes_and_a_wrong_size_gives_no_entry(self):
        cd = fake_clusters()
        self.assertTrue(cluster_cache.save(self.KEY, cd))
        loaded = cluster_cache.load(self.KEY)
        self.assertIsNotNone(loaded)
        for name in cluster_cache._ARRAYS:
            self.assertTrue(np.array_equal(np.asarray(getattr(loaded, name)), getattr(cd, name)), name)
        del loaded
        folder = self.cluster_root / self.KEY
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(meta["files"]), sorted(f"{n}.npy" for n in cluster_cache._ARRAYS))
        self.assertEqual(self.temp_folders(self.cluster_root), [])
        target = folder / "perm.npy"
        good = target.read_bytes()
        target.write_bytes(good + b"\0")
        self.assertIsNone(cluster_cache.load(self.KEY))
        target.write_bytes(good)
        self.assertIsNotNone(cluster_cache.load(self.KEY))
        (folder / "meta.json").write_text(json.dumps({k: v for k, v in meta.items() if k != "files"}), encoding="utf-8")
        self.assertIsNone(cluster_cache.load(self.KEY))               # an entry from before the sizes were recorded

    def test_a_save_cut_off_before_meta_leaves_nothing_an_open_accepts(self):
        with mock.patch.object(prepared_cache, "write_meta", side_effect=KeyboardInterrupt), \
                mock.patch.object(prepared_cache, "remove_entry", return_value=False):
            with self.assertRaises(KeyboardInterrupt):
                cluster_cache._write(self.KEY, fake_clusters(), self.cluster_root)
        left = self.temp_folders(self.cluster_root)
        self.assertEqual(len(left), 1)
        self.assertFalse((self.cluster_root / self.KEY).exists())
        self.assertIsNone(cluster_cache.load(self.KEY))
        os.replace(self.cluster_root / left[0], self.cluster_root / self.KEY)
        self.assertIsNone(cluster_cache.load(self.KEY))
        self.assertTrue(cluster_cache.save(self.KEY, fake_clusters()))
        self.assertIsNotNone(cluster_cache.load(self.KEY))

    def test_a_second_writer_leaves_the_first_entry_untouched(self):
        self.assertTrue(cluster_cache.save(self.KEY, fake_clusters(0)))
        before = snapshot(self.cluster_root / self.KEY)
        real_exists, calls = Path.exists, []

        def exists(path):
            if path == self.cluster_root / self.KEY and not calls:
                calls.append(1)
                return False
            return real_exists(path)

        with mock.patch.object(Path, "exists", exists):
            self.assertTrue(cluster_cache.save(self.KEY, fake_clusters(1)))
        self.assertTrue(calls)
        self.assertEqual(snapshot(self.cluster_root / self.KEY), before)
        self.assertEqual(self.temp_folders(self.cluster_root), [])

    def test_the_guard_refuses_and_remembers_and_a_model_still_gets_its_clusters(self):
        tight = Usage(total=500 * GIB, used=460 * GIB, free=40 * GIB)
        built = fake_clusters()
        with mock.patch.object(prepared_cache, "_disk_usage", return_value=tight) as usage, \
                mock.patch.object(cluster_cache, "make_key", return_value=self.KEY), \
                mock.patch.object(cluster_cache.cl, "build_clusters", return_value=built):
            first = cluster_cache._get(object(), None, True)
            second = cluster_cache._get(object(), None, True)
            self.assertEqual(usage.call_count, 1)                    # the second open does not try the save again
        self.assertIs(first, built)
        self.assertIs(second, built)
        self.assertEqual(first.stats["saved"], False)
        self.assertFalse((self.cluster_root / self.KEY).exists())
        self.assertIn("free disk space", prepared_cache.refused(self.cluster_root, self.KEY))


if __name__ == "__main__":
    unittest.main()
