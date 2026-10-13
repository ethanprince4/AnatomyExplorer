"""What the three stores of prepared data share (app/viewer/prepared_cache.py helpers, used by the prepared-model, the
cluster and the page store), tried in each store: an entry is removed whole or left whole, a file of the right size with
a lost end is a miss and is replaced, what a dead writer left is cleared before the free-disk floor is asked while a
live writer's folder is never touched, and a good entry whose time of opening cannot be set (a read-only store) is
used all the same. Temporary folders, no adapter.

    python -m unittest discover -s tests -p test_store_integrity.py
"""
import gc
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests", ROOT / "tests" / "gpu"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.viewer import prepared_cache                           # noqa: E402

if __name__ == "__main__" and sys.argv[1:2] == ["--writer"]:
    # A writer in another process:  python -B <this file> --writer <store folder> <key> lock|legacy
    # "lock" is a writer of this version; "legacy" one from before the lock (a folder with its process id, no lock).
    store, key, mode = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    store.mkdir(parents=True, exist_ok=True)
    if mode == "lock":
        claim = prepared_cache.TempFolder(store, key)
        folder = claim.path
    else:
        folder = store / f".tmp-{key[:12]}-{os.getpid()}-0badc0de"
    folder.mkdir()
    (folder / "vertices.npy").write_bytes(b"half written " * 1000)
    print(folder.name, flush=True)
    sys.stdin.readline()                                        # until the test lets go or kills this process
    sys.exit(0)

import numpy as np                                              # noqa: E402

import test_cache_identity_and_saving as L0                     # noqa: E402
import test_page_cache as TP                                    # noqa: E402
from app.gpu import cluster_cache                               # noqa: E402
from app.gpu import geometry as G                               # noqa: E402
from app.gpu import page_cache as PC                            # noqa: E402

N, TRIS, PAGE = 4000, 6000, 1 << 22
TIGHT = TP.TIGHT


class Prepared:
    name, folder, big = "prepared", "prepared_models", "vertices.npy"
    prune = staticmethod(prepared_cache.prune)

    def key(self, i):
        return f"{i:02d}" + "a" * 38

    def save(self, i):
        return bool(prepared_cache._save(L0.fake_model(i, n=N, tris=TRIS), L0.plan_for(self.key(i), N, TRIS)))

    def hit(self, i):
        return prepared_cache.lookup(self.key(i)) is not None


class Clusters:
    name, folder, big = "clusters", "clusters", "perm.npy"
    prune = staticmethod(cluster_cache.prune)

    def key(self, i):
        return f"{i:02d}" + "c" * 38

    def save(self, i):
        rng = np.random.default_rng(i)
        cd = SimpleNamespace(stats={"clusters": 3})
        for k, name in enumerate(cluster_cache._ARRAYS):
            setattr(cd, name, rng.integers(1, 1000, size=3000 + k).astype(np.int32))
        return bool(cluster_cache.save(self.key(i), cd))

    def hit(self, i):
        return cluster_cache.load(self.key(i)) is not None


class Pages:
    name, folder, big = "pages", "gpu_pages", "page0.npy"
    prune = staticmethod(PC.prune)

    def __init__(self):
        self.fresh = {}

    def key(self, i):
        return PC.make_key(TP.keyed_model(seed=i), PAGE)

    def save(self, i):
        info = PC.bake(TP.keyed_model(seed=i), PAGE)
        self.fresh[i] = None if info is None else info["fresh"]
        return info is not None

    def hit(self, i):
        return PC.load(TP.keyed_model(seed=i), G.HostSink(), PAGE) is not None


class Case(unittest.TestCase):
    STORE = Prepared

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ANATOMY_PREPARED_CACHE": str(self.root / "prepared_models"),
                                           "ANATOMY_CLUSTER_CACHE": str(self.root / "clusters"),
                                           "ANATOMY_PAGE_CACHE": str(self.root / "gpu_pages")})
        env.start()
        self.addCleanup(env.stop)
        for name in ("ANATOMY_GEOM_QERR", "ANATOMY_PAGE_CACHE_GB", "ANATOMY_CLUSTER_CACHE_GB", "ANATOMY_PREPARED_CACHE_GB"):
            os.environ.pop(name, None)
        disk = mock.patch.object(prepared_cache, "_disk_usage", return_value=TP.ROOMY)   # a full PC must not fail these
        disk.start()
        self.addCleanup(disk.stop)
        saved = dict(prepared_cache._refused)
        prepared_cache._refused.clear()
        self.addCleanup(prepared_cache._refused.update, saved)
        self.addCleanup(prepared_cache._refused.clear)
        self.store = self.STORE()
        self.store.root = self.root / self.store.folder

    @staticmethod
    def names(root):
        return sorted(f.name for f in root.iterdir()) if root.exists() else []

    def temps(self, root):
        return [n for n in self.names(root) if n.startswith(".tmp-")]

    @staticmethod
    def snapshot(folder):
        return {f.name: f.read_bytes() for f in sorted(folder.iterdir())}

    @staticmethod
    def size(folder):
        return sum(f.stat().st_size for f in folder.iterdir())

    def age(self, store, order):
        """Give the entries of ``order`` rising meta.json times: the first is the least recently opened."""
        for rank, i in enumerate(order):
            meta = store.root / store.key(i) / "meta.json"
            stamp = time.time() - 100 * (len(order) - rank)
            os.utime(meta, (stamp, stamp))

    def writer(self, store_root, key="feedfeedfeed", mode="lock"):
        """A process that holds a temporary folder under ``store_root`` until it is killed or let go."""
        proc = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--writer", str(store_root), key, mode],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.end, proc)
        name = proc.stdout.readline().strip()
        self.assertTrue(name.startswith(".tmp-"), name)
        return proc, store_root / name

    @staticmethod
    def end(proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait(30)
        for pipe in (proc.stdin, proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass


class RemovalIsWholeOrNotAtAll:
    @unittest.skipUnless(os.name == "nt", "only Windows keeps a mapped file from being renamed or deleted")
    def test_an_entry_with_a_mapped_file_stays_valid_and_prune_takes_the_next_one_and_stops_at_the_cap(self):
        store = self.store
        for i in (1, 2, 3):
            self.assertTrue(store.save(i))
        self.age(store, (1, 2, 3))                              # 1 is the first candidate
        held = store.root / store.key(1)
        before = self.snapshot(held)
        mapped = np.load(held / store.big, mmap_mode="r")       # as a tab that has the model open
        try:
            self.assertFalse(prepared_cache.remove_entry(held))
            self.assertEqual(self.snapshot(held), before)       # nothing of it was touched, meta.json is there
            self.assertTrue(store.hit(1))
            self.age(store, (1, 2, 3))                          # (the open above made it the newest)
            cap = sum(self.size(store.root / store.key(i)) for i in (1, 2, 3)) - 1      # one removal is enough
            store.prune(store.root, cap=cap)
            self.assertEqual(self.names(store.root), sorted([store.key(1), store.key(3)]))    # 2 went, 3 stayed
            self.assertEqual(self.snapshot(held), before)
            self.assertTrue(store.hit(1) and store.hit(3))
            self.assertFalse(store.hit(2))
            self.assertTrue(store.save(1))                      # its key is not spoiled for this run
            self.assertIsNone(prepared_cache.refused(store.root, store.key(1)))
        finally:
            del mapped
            gc.collect()
        self.assertTrue(prepared_cache.remove_entry(held))      # once nobody has it open it goes whole
        self.assertEqual(self.names(store.root), [store.key(3)])

    def test_a_refused_rename_touches_nothing_and_prune_counts_nothing_as_freed(self):
        store = self.store
        for i in (1, 2, 3):
            self.assertTrue(store.save(i))
        self.age(store, (1, 2, 3))
        held = store.root / store.key(1)
        before = self.snapshot(held)
        real = os.rename

        def rename(src, dst):
            if Path(src) == held:
                raise PermissionError("a file of the entry is mapped")
            return real(src, dst)

        cap = sum(self.size(store.root / store.key(i)) for i in (1, 2, 3)) - 1
        with mock.patch.object(prepared_cache.os, "rename", rename):
            self.assertFalse(prepared_cache.remove_entry(held))
            store.prune(store.root, cap=cap)
        self.assertEqual(self.names(store.root), sorted([store.key(1), store.key(3)]))
        self.assertEqual(self.snapshot(held), before)
        self.assertTrue(store.hit(1) and store.hit(3))

    def test_what_is_moved_aside_loses_meta_first_is_no_entry_and_goes_at_the_next_save(self):
        store = self.store
        for i in (1, 2):
            self.assertTrue(store.save(i))
        self.age(store, (1, 2))
        with mock.patch.object(prepared_cache.shutil, "rmtree"):         # the rest cannot be deleted just now
            store.prune(store.root, cap=self.size(store.root / store.key(2)))
        left = self.temps(store.root)
        self.assertEqual(self.names(store.root), sorted(left + [store.key(2)]))
        self.assertEqual(len(left), 1)
        self.assertTrue(left[0].startswith(".tmp-gone-"))
        self.assertFalse((store.root / left[0] / "meta.json").exists())
        self.assertTrue((store.root / left[0] / store.big).exists())
        self.assertFalse(store.hit(1))
        store.prune(store.root, cap=1 << 40)                            # not an entry: prune neither counts nor takes it
        self.assertEqual(self.temps(store.root), left)
        self.assertTrue(store.save(1))                                  # saved again at once, and the leftover is gone
        self.assertEqual(self.names(store.root), sorted([store.key(1), store.key(2)]))
        self.assertTrue(store.hit(1) and store.hit(2))


def zero_tail(path):
    """Zeros from 4 KiB on (from the end of the .npy header in a small file); the size stays as it was."""
    size = path.stat().st_size
    keep = 4096 if size > 8192 else 128
    with open(path, "r+b") as fh:
        fh.seek(keep)
        fh.write(b"\0" * (size - keep))
    assert path.stat().st_size == size
    return size


class ALostEndIsAMiss:
    def test_a_clean_entry_hits_a_zero_filled_end_misses_and_the_next_save_replaces_it(self):
        store = self.store
        self.assertTrue(store.save(1))
        target = store.root / store.key(1) / store.big
        good = target.read_bytes()
        self.assertTrue(store.hit(1))
        self.assertTrue(store.hit(1))
        zero_tail(target)
        np.load(target, mmap_mode="r", allow_pickle=False)              # still a readable array of the right size
        gc.collect()
        self.assertFalse(store.hit(1))
        self.assertFalse(store.hit(1))
        self.assertTrue(store.save(1))                                  # the save of that open puts a good one there
        self.assertEqual(target.read_bytes(), good)
        self.assertTrue(store.hit(1))
        self.assertEqual(self.names(store.root), [store.key(1)])
        if isinstance(store, Pages):
            self.assertIs(store.fresh[1], True)                         # bake did not keep the zeroed pages as good

    def test_only_the_last_bytes_lost_is_a_miss_too(self):
        store = self.store
        self.assertTrue(store.save(1))
        target = store.root / store.key(1) / store.big
        with open(target, "r+b") as fh:
            fh.seek(-512, os.SEEK_END)
            fh.write(b"\0" * 512)
        self.assertFalse(store.hit(1))

    def test_an_entry_without_digests_misses_once_and_is_replaced(self):
        store = self.store
        self.assertTrue(store.save(1))
        path = store.root / store.key(1) / "meta.json"
        meta = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(meta["digests"]), sorted(meta["files"]))
        self.assertIn(store.big, meta["digests"])
        old = {k: v for k, v in meta.items() if k != "digests"}             # as written before this check
        for changed in (old, {**meta, "digests": None}, {**meta, "digests": {}},
                        {**meta, "digests": {**meta["digests"], store.big: ""}},
                        {**meta, "digests": {k: v for k, v in meta["digests"].items() if k != store.big}}):
            path.write_text(json.dumps(changed), encoding="utf-8")
            self.assertFalse(store.hit(1))                                  # a miss, never an error
        self.assertTrue(store.save(1))
        self.assertIn("digests", json.loads(path.read_text(encoding="utf-8")))
        self.assertTrue(store.hit(1))

    def digest_reads_and_cannot_see(self):
        P = prepared_cache
        path = self.root / "big.bin"
        data = np.random.default_rng(5).integers(1, 255, size=4 << 20, dtype=np.uint8).tobytes()
        path.write_bytes(data)
        good = P.file_digest(path)
        body = len(data) - P.DIGEST_TAIL
        step = body // P.DIGEST_SAMPLES

        def with_zeros(first, count):
            path.write_bytes(data[:first] + b"\0" * count + data[first + count:])
            return P.file_digest(path)

        self.assertNotEqual(with_zeros(len(data) - 1, 1), good)                 # the very last byte
        self.assertNotEqual(with_zeros(body, 16), good)                         # the start of the tail
        self.assertNotEqual(with_zeros(4096, len(data) - 4096), good)           # all but the first 4 KiB
        for i in range(P.DIGEST_SAMPLES):
            self.assertNotEqual(with_zeros(body * i // P.DIGEST_SAMPLES, 8), good, i)
        self.assertNotEqual(with_zeros(P.DIGEST_BLOCK, step), good)             # any stretch as long as the sample spacing
        self.assertEqual(with_zeros(P.DIGEST_BLOCK, step - P.DIGEST_BLOCK), good)       # not seen: wholly between two samples
        path.write_bytes(data + b"\0")
        self.assertNotEqual(P.file_digest(path), good)                          # the size is part of it
        small = self.root / "small.bin"
        small.write_bytes(data[:P.DIGEST_TAIL + P.DIGEST_SAMPLES * P.DIGEST_BLOCK])
        whole = P.file_digest(small)
        for at in range(0, small.stat().st_size, 997):                          # a small file is read whole
            raw = bytearray(small.read_bytes())
            raw[at] ^= 0xFF
            small.write_bytes(bytes(raw))
            self.assertNotEqual(P.file_digest(small), whole)
            raw[at] ^= 0xFF
            small.write_bytes(bytes(raw))
        self.assertEqual(P.file_digest(small), whole)


class LeftoversOfDeadWriters:
    def refused_save(self, store, i):
        with mock.patch.object(prepared_cache, "_disk_usage", return_value=TIGHT):
            self.assertFalse(store.save(i))
        self.assertIn("free disk", prepared_cache.refused(store.root, store.key(i)))

    def test_a_killed_writer_is_cleared_by_the_next_save_even_one_the_floor_refuses(self):
        store = self.store
        proc, folder = self.writer(store.root)
        lock = folder.with_name(folder.name + ".lock")
        self.assertTrue(folder.is_dir() and lock.is_file())
        proc.kill()
        proc.wait(30)
        self.assertTrue(folder.is_dir() and lock.is_file())             # nobody tidied up after it
        self.refused_save(store, 7)
        self.assertEqual(self.names(store.root), [])                    # the folder and its lock file are gone

    def test_a_live_writer_in_another_process_is_never_cleared_whatever_its_age(self):
        store = self.store
        proc, folder = self.writer(store.root)
        lock = folder.with_name(folder.name + ".lock")
        old = folder.stat().st_mtime - 30 * 86400
        os.utime(folder, (old, old))
        before = self.snapshot(folder)
        self.assertEqual(prepared_cache.clear_leftovers(store.root), 0)
        self.refused_save(store, 7)
        self.assertTrue(store.save(1))
        self.assertEqual(self.names(store.root), sorted([folder.name, lock.name, store.key(1)]))
        self.assertEqual(self.snapshot(folder), before)
        proc.kill()
        proc.wait(30)
        self.assertTrue(store.save(2))                                  # the writer is gone: so is its folder
        self.assertEqual(self.names(store.root), sorted([store.key(1), store.key(2)]))

    def test_a_writer_in_this_process_keeps_its_folder_until_it_lets_go(self):
        store = self.store
        store.root.mkdir(parents=True)
        claim = prepared_cache.TempFolder(store.root, "ab" * 20)
        claim.path.mkdir()
        (claim.path / store.big).write_bytes(b"being written")
        self.assertTrue(store.save(1))
        self.assertEqual(prepared_cache.clear_leftovers(store.root), 0)
        self.assertEqual((claim.path / store.big).read_bytes(), b"being written")
        with mock.patch.object(prepared_cache.shutil, "rmtree"):         # it finishes but cannot delete its folder
            claim.release()
        self.assertEqual(self.temps(store.root), [claim.path.name])     # no lock file: a leftover from now on
        self.assertTrue(store.save(2))
        self.assertEqual(self.names(store.root), sorted([store.key(1), store.key(2)]))

    def test_a_folder_without_a_lock_is_kept_only_while_the_process_in_its_name_runs(self):
        store = self.store
        proc, legacy = self.writer(store.root, mode="legacy")           # a writer of a version before the lock
        self.assertEqual(self.names(store.root), [legacy.name])
        ours = store.root / f".tmp-feedfeedfeed-{os.getpid()}-12345678"     # this process holds no lock for it
        aside = store.root / ".tmp-gone-feedfeedfeed-12345678"              # an entry moved aside, not yet deleted
        odd = store.root / ".tmp-abandoned"
        for folder in (ours, aside, odd):
            folder.mkdir()
            (folder / store.big).write_bytes(b"x" * 100)
        self.assertTrue(store.save(1))
        self.assertEqual(self.names(store.root), sorted([legacy.name, store.key(1)]))
        proc.kill()
        proc.wait(30)
        self.refused_save(store, 7)
        self.assertEqual(self.names(store.root), [store.key(1)])

    def process_check(self):
        self.assertTrue(prepared_cache._process_runs(os.getpid()))
        proc, _folder = self.writer(self.root / "x", mode="legacy")
        self.assertTrue(prepared_cache._process_runs(proc.pid))
        proc.kill()
        proc.wait(30)
        self.assertFalse(prepared_cache._process_runs(proc.pid))             # (the handle the test still holds does not count)
        self.assertFalse(prepared_cache._process_runs(0))

    def lock_holders(self):
        path = self.root / "some.lock"
        first = prepared_cache._lock(path, create=True)
        self.assertIsNotNone(first)
        self.assertIsNone(prepared_cache._lock(path))
        os.close(first)
        second = prepared_cache._lock(path)
        self.assertIsNotNone(second)
        os.close(second)
        self.assertIsNone(prepared_cache._lock(self.root / "not there.lock"))


class AnEntryThatCannotBeMarkedIsUsed:
    def test_a_good_entry_whose_access_time_cannot_be_set_is_used_and_nothing_is_rebuilt(self):
        store = self.store
        self.assertTrue(store.save(1))
        folder = store.root / store.key(1)
        before, stamp = self.snapshot(folder), (folder / "meta.json").stat().st_mtime_ns
        for error in (PermissionError(13, "the store is read-only"), OSError(30, "read-only file system"),
                      RuntimeError("anything else")):
            with mock.patch("os.utime", side_effect=error) as utime:
                self.assertTrue(store.hit(1), f"{store.name}: {error!r} from the access-time update lost a good entry")
                self.assertEqual(utime.call_count, 1, "the update is tried once per open, on the entry's meta.json")
                self.assertEqual(Path(utime.call_args.args[0]), folder / "meta.json")
                self.assertTrue(store.save(1))                     # the save finds the good entry: nothing is written
            if store.name == "pages":
                self.assertIs(store.fresh[1], False, "the page entry was baked again")
        self.assertEqual(self.snapshot(folder), before)
        self.assertEqual((folder / "meta.json").stat().st_mtime_ns, stamp)
        self.assertEqual(self.names(store.root), [store.key(1)])
        self.assertEqual(prepared_cache._refused, {})

    def test_an_entry_that_can_be_marked_is_the_last_to_be_pruned(self):
        store = self.store
        for i in (1, 2):
            self.assertTrue(store.save(i))
        self.age(store, [2, 1])                                    # 2 is the least recently opened ...
        self.assertTrue(store.hit(2))                              # ... until it is opened
        store.prune(store.root, cap=self.size(store.root / store.key(2)))
        self.assertEqual(self.names(store.root), [store.key(2)])


class Helpers(Case):
    """What does not depend on the store."""
    test_digest = ALostEndIsAMiss.digest_reads_and_cannot_see
    test_process = LeftoversOfDeadWriters.process_check
    test_lock = LeftoversOfDeadWriters.lock_holders


for _mixin in (RemovalIsWholeOrNotAtAll, ALostEndIsAMiss, LeftoversOfDeadWriters, AnEntryThatCannotBeMarkedIsUsed):
    for _kind in (Prepared, Clusters, Pages):                      # every test of the three classes, once per store
        _name = f"{_mixin.__name__}In{_kind.__name__}"
        globals()[_name] = type(_name, (_mixin, Case), {"STORE": _kind})


if __name__ == "__main__":
    unittest.main()
