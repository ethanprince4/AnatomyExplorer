"""The store of GPU-ready pages (app/gpu/page_cache.py): what bake writes and load hands to a sink is byte for byte what
build_geometry hands to it, for every layout; the key follows the limits and the request; a damaged entry is no entry;
the draw order comes from the model in hand; saving is as safe as in the other stores. No adapter is needed.

    python -m unittest discover -s tests/gpu -p test_page_cache.py
"""
import dataclasses
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

from app.gpu import cluster_cache                               # noqa: E402
from app.gpu import geometry as G                               # noqa: E402
from app.gpu import page_cache as PC                            # noqa: E402
from app.load_control import LoadCancelled                      # noqa: E402
from app.viewer import lod                                      # noqa: E402
from app.viewer import prepared_cache                           # noqa: E402
from app.viewer.model import Look                               # noqa: E402

ROOMY = SimpleNamespace(total=1 << 40, used=0, free=1 << 40)
TIGHT = SimpleNamespace(total=1 << 40, used=(1 << 40) - (1 << 30), free=1 << 30)


def synthetic_model(parts=3, n=12, seed=3):
    """The model of test_geometry.synthetic_model (importing that file would start a graphics device): parts of a sphere
    grid, one with varying uv, one with a varying morph delta, the rest of the extra attributes constant per part."""
    rng = np.random.default_rng(seed)
    th, ph = np.meshgrid(np.linspace(0, np.pi, n + 1), np.linspace(0, 2 * np.pi, n + 1), indexing="ij")
    pos = np.stack([np.sin(th) * np.cos(ph), np.cos(th), np.sin(th) * np.sin(ph)], -1).reshape(-1, 3).astype(np.float32)
    i = np.arange(n)[:, None] * (n + 1) + np.arange(n)[None, :]
    tris = np.stack([i, i + n + 1, i + 1, i + 1, i + n + 1, i + n + 2], -1).reshape(-1).astype(np.uint32)
    nv = len(pos)
    verts, idx, plist = [], [], []
    for k in range(parts):
        v = np.zeros((nv, G.VERTEX_FLOATS), dtype=np.float32)
        v[:, 0:3] = pos * (1.0 + 0.1 * k)
        nrm = rng.normal(size=(nv, 3)).astype(np.float32)
        v[:, 3:6] = nrm / np.linalg.norm(nrm, axis=1, keepdims=True)
        v[:, 6:19] = (0.25, 0.5, 0.75, 0, 0, 0, 0.5, 0.2, 0.3, 0.4, 1.0, 0, 0)
        if k == 1:
            v[:, 17:19] = rng.random((nv, 2)).astype(np.float32)
        if k == 2:
            v[:, 6:9] = rng.normal(size=(nv, 3)).astype(np.float32)
        plist.append(SimpleNamespace(id=k + 1, name=f"part{k}", first=k * len(tris), count=len(tris),
                                     vertex_base=k * nv, vertex_count=nv, item=k, look=Look(), material_name="mat"))
        verts.append(v)
        idx.append(tris + np.uint32(k * nv))
    return SimpleNamespace(vertices=np.concatenate(verts), indices=np.concatenate(idx), parts=plist, lod=None)


def keyed_model(parts=3, n=40, seed=3, levels=True):
    """That model with an identity (as local_runtime gives a library file) and, for one part, detail levels of which
    the first two share one array."""
    m = synthetic_model(parts=parts, n=n, seed=seed)
    m.anim_vertices = None
    m._prepared_key = f"model-{parts}-{n}-{seed}-{int(levels)}"
    if levels and parts > 1:
        p = m.parts[1]
        tris = m.indices[p.first:p.first + p.count].reshape(-1, 3)
        arrays = [np.ascontiguousarray(tris[::2 ** (k + 1)]).reshape(-1) for k in range(lod.LEVELS)]
        arrays[1] = arrays[0]
        m.lod = {p.id: SimpleNamespace(indices=arrays)}
    return m


def three_page_bytes(model, **kw):
    """A page limit under which build_geometry lays this model out on exactly three pages."""
    total = G.build_geometry(model, G.HostSink(), 1 << 24, **kw).stats["gpu_bytes"]
    for size in range(total // 3 // 256 * 256, total, 1024):
        try:
            if len(G.build_geometry(model, G.HostSink(), size, max_pages=3, **kw).pages) == 3:
                return size
        except G.GeometryError:
            continue
    raise AssertionError("no page limit gives three pages")


class StoreCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "gpu_pages"
        env = mock.patch.dict(os.environ, {"ANATOMY_PREPARED_CACHE": str(self.root / "prepared_models"),
                                           "ANATOMY_CLUSTER_CACHE": str(self.root / "clusters"),
                                           "ANATOMY_PAGE_CACHE": str(self.store)})
        env.start()
        self.addCleanup(env.stop)
        for name in ("ANATOMY_GEOM_QERR", "ANATOMY_PAGE_CACHE_GB", "ANATOMY_CLUSTER_CACHE_GB"):
            os.environ.pop(name, None)
        disk = mock.patch.object(prepared_cache, "_disk_usage", return_value=ROOMY)     # a full PC must not fail these
        disk.start()
        self.addCleanup(disk.stop)

    def entries(self):
        return sorted(f.name for f in self.store.iterdir()) if self.store.exists() else []

    def assert_same(self, built, loaded):
        """Every field of the loaded GpuGeometry equals the built one; the page buffers byte for byte."""
        self.assertEqual(len(built.pages), len(loaded.pages))
        for a, b in zip(built.pages, loaded.pages):
            for f in dataclasses.fields(G.Page):
                if f.name != "buffer":
                    self.assertEqual(getattr(a, f.name), getattr(b, f.name), f.name)
            self.assertEqual((a.buffer.dtype, a.buffer.shape), (b.buffer.dtype, b.buffer.shape))
            self.assertEqual(a.buffer.tobytes(), b.buffer.tobytes())
        for name in ("page_of", "vbase", "vcount", "stream_base", "const_tail", "anim_base"):
            x, y = getattr(built, name), getattr(loaded, name)
            self.assertEqual((x.dtype, x.shape), (y.dtype, y.shape), name)
            self.assertEqual(x.tobytes(), y.tobytes(), name)
        self.assertEqual([[(int(first), int(count)) for first, count in levels] for levels in built.ranges], loaded.ranges)
        self.assertEqual(built.gl_keys, loaded.gl_keys)
        self.assertEqual(built.stats, loaded.stats)
        for name in ("page_bytes", "compressed", "stage", "cluster_ordered"):
            self.assertEqual(getattr(built, name), getattr(loaded, name), name)
        self.assertEqual(built.quant is None, loaded.quant is None)
        if built.quant is not None:
            self.assertEqual(sorted(built.quant), sorted(loaded.quant))
            for name, value in built.quant.items():
                if isinstance(value, np.ndarray):
                    self.assertEqual((value.dtype, value.shape), (loaded.quant[name].dtype, loaded.quant[name].shape), name)
                    self.assertEqual(value.tobytes(), loaded.quant[name].tobytes(), name)
                else:
                    self.assertEqual(value, loaded.quant[name], name)
        self.assertEqual(built.clusters is None, loaded.clusters is None)
        if built.clusters is not None:
            for f in dataclasses.fields(built.clusters):
                if f.name != "stats":
                    x, y = np.asarray(getattr(built.clusters, f.name)), np.asarray(getattr(loaded.clusters, f.name))
                    self.assertEqual((x.dtype, x.shape), (y.dtype, y.shape), f.name)
                    self.assertEqual(x.tobytes(), y.tobytes(), f.name)
            self.assertIsInstance(loaded.order, G.TriangleOrder)
            self.assertIs(loaded.order.cd, loaded.clusters)
        else:
            self.assertIsNone(loaded.order)

    def round_trip(self, model, page_bytes, **kw):
        built = G.build_geometry(model, G.HostSink(), page_bytes, **kw)
        info = PC.bake(model, page_bytes, **kw)
        self.assertIsNotNone(info)
        self.assertTrue(info["fresh"])
        self.assertEqual(info["stage"], built.stage)
        self.assertEqual(info["pages"], len(built.pages))
        self.assertEqual(info["bytes"], built.stats["gpu_bytes"])
        loaded = PC.load(model, G.HostSink(), page_bytes, **kw)
        self.assertIsNotNone(loaded)
        self.assert_same(built, loaded)
        va, ia = G.decode_geometry(built, model)
        vb, ib = G.decode_geometry(loaded, model)
        self.assertEqual(va.tobytes(), vb.tobytes())
        self.assertEqual(sorted(ia), sorted(ib))
        for k in ia:
            self.assertTrue(np.array_equal(ia[k], ib[k]))
        return built, loaded, info


class RoundTrip(StoreCase):
    """bake then load into a HostSink equals build_geometry, byte for byte."""

    def test_plain(self):
        built, loaded, info = self.round_trip(keyed_model(), 1 << 22)
        self.assertEqual((built.stage, len(built.pages), built.clusters), (0, 1, None))

    def test_cluster_ordered(self):
        built, loaded, info = self.round_trip(keyed_model(), 1 << 22, cluster_order=True)
        self.assertEqual(built.stage, 0)
        self.assertIsNotNone(loaded.clusters)
        self.assertFalse(loaded.compressed)

    def test_cluster_ordered_with_the_cluster_store_off(self):
        self.round_trip(keyed_model(), 1 << 22, cluster_order=True, cluster_cache_use=False)

    def test_stage_one(self):
        built, loaded, info = self.round_trip(keyed_model(), 1 << 22, cluster_order=True, compress=1)
        self.assertEqual(loaded.stage, 1)
        self.assertTrue(loaded.pages[0].compressed)
        self.assertFalse(loaded.pages[0].quantised)

    def test_stage_two(self):
        os.environ["ANATOMY_GEOM_QERR"] = "1.0"          # a loose budget, so the small model really is quantised coarsely
        built, loaded, info = self.round_trip(keyed_model(), 1 << 22, cluster_order=True, compress=2)
        self.assertEqual(loaded.stage, 2)
        self.assertTrue(loaded.pages[0].quantised)
        self.assertTrue(np.any(loaded.quant["err"] > 0))
        self.assertFalse(np.array_equal(loaded.clusters.cl_geom, cluster_cache.get_clusters(keyed_model()).cl_geom))

    def test_three_pages(self):
        model = keyed_model(levels=False, n=12)
        nv = model.parts[0].vertex_count
        need = G.section_layout({"pos": nv, "nrm": nv, "dpos": nv, "index": model.parts[0].count})[1] * 4
        built, loaded, info = self.round_trip(model, need, max_pages=3)
        self.assertEqual(len(loaded.pages), 3)
        self.assertEqual(sorted(f.name for f in (self.store / info["key"]).iterdir()),
                         ["meta.json", "page0.npy", "page1.npy", "page2.npy", "tables.json", "tables.npz"])

    def test_three_pages_cluster_ordered_and_compressed(self):
        model = keyed_model()
        for compress in (0, 1):
            size = three_page_bytes(model, cluster_order=True, compress=compress)
            built, loaded, info = self.round_trip(model, size, max_pages=3, cluster_order=True, compress=compress)
            self.assertEqual((len(loaded.pages), loaded.stage), (3, compress))
            self.assertEqual(len(loaded.clusters.page_cfirst), 4)

    def test_auto_keeps_the_request_in_the_key_and_the_stage_in_meta(self):
        model = keyed_model()
        kw = dict(cluster_order=True, max_pages=1)
        plain = G.build_geometry(model, G.HostSink(), 1 << 22, **kw).stats["gpu_bytes"]
        small = G.build_geometry(model, G.HostSink(), 1 << 22, compress=1, **kw).stats["gpu_bytes"]
        tight = (plain + small) // 2 // 256 * 256
        _, loaded, roomy = self.round_trip(model, 1 << 22, compress="auto", **kw)
        self.assertEqual((loaded.stage, roomy["stage"], roomy["compress"]), (0, 0, "auto"))
        _, loaded, info = self.round_trip(model, tight, compress="auto", **kw)
        self.assertEqual((loaded.stage, info["stage"], info["compress"]), (1, 1, "auto"))
        meta = json.loads((self.store / info["key"] / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["stage"], meta["compress"], meta["page_bytes"], meta["max_pages"]), (1, "auto", tight, 1))

    def test_a_page_handed_over_in_many_pieces(self):
        with mock.patch.object(PC, "CHUNK", 4096):
            sink = mock.Mock(wraps=G.HostSink())
            model = keyed_model()
            built = G.build_geometry(model, G.HostSink(), 1 << 22, cluster_order=True)
            PC.bake(model, 1 << 22, cluster_order=True)
            loaded = PC.load(model, sink, 1 << 22, cluster_order=True)
        self.assertEqual(sink.write.call_count, -(-built.pages[0].words * 4 // 4096))
        self.assertTrue(all(c.args[1] % 4096 == 0 for c in sink.write.call_args_list))
        loaded.sink = built.sink
        self.assert_same(built, loaded)

    def test_pages_are_written_through_open_memmap(self):
        model = keyed_model(levels=False, n=12)
        nv = model.parts[0].vertex_count
        need = G.section_layout({"pos": nv, "nrm": nv, "dpos": nv, "index": model.parts[0].count})[1] * 4
        kinds = []                                         # the kinds only: a kept mapping would hold its file open
        real = np.lib.format.open_memmap

        def spy(*args, **kw):
            handle = real(*args, **kw)
            kinds.append((type(handle), kw.get("mode"), Path(args[0]).name))
            return handle

        seen = []
        build = G.build_geometry
        with mock.patch.object(np.lib.format, "open_memmap", side_effect=spy), \
                mock.patch.object(G, "build_geometry", side_effect=lambda m, sink, *a, **k: seen.append(sink) or build(m, sink, *a, **k)):
            info = PC.bake(model, need, max_pages=3)
        self.assertEqual(info["pages"], 3)
        self.assertEqual(kinds, [(np.memmap, "w+", f"page{i}.npy") for i in range(3)])
        self.assertIsInstance(seen[0], PC._FileSink)
        self.assertEqual(seen[0].maps, [])                 # nothing mapped is kept once the entry is in place


class Keys(StoreCase):
    def test_another_limit_or_request_gives_another_key(self):
        model = keyed_model()
        base = dict(page_bytes=1 << 22, max_pages=8, cluster_order=True, compress="auto")
        key = PC.make_key(model, **base)
        self.assertEqual(len(key), 40)
        self.assertEqual(key, PC.make_key(model, **base))
        others = [dict(base, page_bytes=1 << 21), dict(base, max_pages=4), dict(base, max_pages=None),
                  dict(base, cluster_order=False), dict(base, compress=0), dict(base, compress=1), dict(base, compress=2)]
        keys = [PC.make_key(model, **kw) for kw in others]
        self.assertEqual(len({key, *keys}), len(others) + 1)
        self.assertEqual(PC.make_key(model, **dict(base, compress=True)), PC.make_key(model, **dict(base, compress=1)))
        self.assertEqual(PC.make_key(model, **dict(base, compress=False)), PC.make_key(model, **dict(base, compress=0)))

    def test_another_page_limit_finds_no_pages(self):
        model = keyed_model()
        self.assertIsNotNone(PC.bake(model, 1 << 22))
        self.assertIsNone(PC.load(model, G.HostSink(), 1 << 23))
        self.assertIsNotNone(PC.load(model, G.HostSink(), 1 << 22))

    def test_the_key_follows_the_model_and_the_code(self):
        model = keyed_model()
        for order in (False, True):
            key = PC.make_key(model, 1 << 22, cluster_order=order)
            other = keyed_model()
            other._prepared_key = "another file"
            self.assertNotEqual(key, PC.make_key(other, 1 << 22, cluster_order=order))
            other = keyed_model()
            other.lod = None                                # the same file before its detail levels are built
            self.assertNotEqual(key, PC.make_key(other, 1 << 22, cluster_order=order))
            real = prepared_cache._module_bytes
            for name in ("app.gpu.page_cache", "app.gpu.geometry", "app.gpu.quant"):     # an edit to a shaping file
                with mock.patch.dict(prepared_cache._code_ids, clear=True), \
                        mock.patch.object(prepared_cache, "_module_bytes",
                                          side_effect=lambda n, name=name: real(n) + (b"\n# edited\n" if n == name else b"")):
                    self.assertNotEqual(key, PC.make_key(model, 1 << 22, cluster_order=order), name)
            self.assertEqual(key, PC.make_key(model, 1 << 22, cluster_order=order))
            with mock.patch.object(PC, "PAGES_VERSION", PC.PAGES_VERSION + 1):
                self.assertNotEqual(key, PC.make_key(model, 1 << 22, cluster_order=order))
        self.assertEqual({"app.gpu.page_cache", "app.gpu.geometry", "app.gpu.quant", "app.gpu.clusters"}, set(PC.SHAPING_MODULES))

    def test_no_identity_no_key_and_nothing_stored(self):
        model = keyed_model()
        model._prepared_key = None
        animated = keyed_model()
        animated.anim_vertices = np.zeros(len(animated.vertices), dtype=[("m", "<f2", 16), ("phase", "<f4")])
        for m in (model, animated):
            for order in (False, True):
                self.assertIsNone(PC.make_key(m, 1 << 22, cluster_order=order))
        self.assertIsNone(PC.bake(model, 1 << 22))
        self.assertIsNone(PC.load(model, G.HostSink(), 1 << 22))
        self.assertEqual(self.entries(), [])

    def test_the_store_can_be_switched_off(self):
        model = keyed_model()
        os.environ["ANATOMY_PAGE_CACHE"] = "off"
        self.assertIsNone(PC.cache_root())
        self.assertIsNone(PC.bake(model, 1 << 22))
        self.assertIsNone(PC.load(model, G.HostSink(), 1 << 22))
        del os.environ["ANATOMY_PAGE_CACHE"]
        self.assertEqual(PC.cache_root(), self.root / "gpu_pages")          # beside the prepared models
        os.environ["ANATOMY_PREPARED_CACHE"] = "off"
        self.assertIsNone(PC.cache_root())


class DrawOrder(StoreCase):
    """The draw-order keys are not stored: a loaded geometry has the order the model's looks give now."""

    def looks(self, model, table):
        for p, (material, look) in zip(model.parts, table):
            p.material_name, p.look = material, look

    def test_a_changed_look_table_changes_the_order_as_for_a_built_geometry(self):
        model = keyed_model()
        first = [("bone", Look()), ("bone", Look()), ("bone", Look())]
        second = [("skin", Look(alpha=0.5)), ("bone", Look()), ("artery", Look(base=(0.8, 0.1, 0.1)))]
        for kw in (dict(), dict(cluster_order=True, compress=1)):
            self.looks(model, first)
            key = PC.make_key(model, 1 << 22, **kw)
            built_first = G.build_geometry(model, G.HostSink(), 1 << 22, **kw)
            self.assertTrue(PC.bake(model, 1 << 22, **kw)["fresh"])
            self.assertEqual(PC.load(model, G.HostSink(), 1 << 22, **kw).gl_keys, built_first.gl_keys)
            self.looks(model, second)
            self.assertEqual(key, PC.make_key(model, 1 << 22, **kw))            # looks are in no key
            built_second = G.build_geometry(model, G.HostSink(), 1 << 22, **kw)
            loaded = PC.load(model, G.HostSink(), 1 << 22, **kw)
            self.assertNotEqual(built_first.gl_keys, built_second.gl_keys)
            self.assertEqual(loaded.gl_keys, built_second.gl_keys)
            self.assert_same(built_second, loaded)
            self.assertFalse(PC.bake(model, 1 << 22, **kw)["fresh"])            # and the entry is still the first one

    def test_nothing_of_the_order_or_the_clusters_is_in_the_entry(self):
        model = keyed_model()
        info = PC.bake(model, 1 << 22, cluster_order=True, compress=2)
        folder = self.store / info["key"]
        self.assertEqual(sorted(f.name for f in folder.iterdir()), ["meta.json", "page0.npy", "tables.json", "tables.npz"])
        with np.load(folder / "tables.npz", allow_pickle=False) as z:              # no pickle: this would raise
            names = set(z.files)
            self.assertTrue(all(z[n].dtype != object for n in names))
        self.assertEqual(names, set(PC._TABLES) | {"quant_" + n for n in PC._QUANT_ARRAYS})
        text = (folder / "tables.json").read_text(encoding="utf-8")
        self.assertNotIn("gl_keys", text)
        self.assertNotIn("gl_keys", json.loads((folder / "meta.json").read_text(encoding="utf-8")))
        self.assertEqual(np.load(folder / "page0.npy", allow_pickle=False).dtype, np.uint8)


class DamagedEntries(StoreCase):
    def baked(self, **kw):
        model = keyed_model()
        info = PC.bake(model, 1 << 22, **kw)
        return model, self.store / info["key"]

    def test_a_truncated_page_gives_none_and_the_next_bake_repairs_it(self):
        model, folder = self.baked()
        size = (folder / "page0.npy").stat().st_size
        os.truncate(folder / "page0.npy", size // 2)
        sink = mock.Mock(wraps=G.HostSink())
        self.assertIsNone(PC.load(model, sink, 1 << 22))
        sink.create.assert_not_called()                     # refused before anything reaches the sink
        info = PC.bake(model, 1 << 22)
        self.assertTrue(info["fresh"])
        self.assertEqual((folder / "page0.npy").stat().st_size, size)
        self.assert_same(G.build_geometry(model, G.HostSink(), 1 << 22), PC.load(model, G.HostSink(), 1 << 22))

    def test_a_page_of_the_right_size_with_a_bad_header_gives_none(self):
        model, folder = self.baked()
        raw = bytearray((folder / "page0.npy").read_bytes())
        raw[:6] = b"broken"
        (folder / "page0.npy").write_bytes(bytes(raw))
        self.assertIsNone(PC.load(model, G.HostSink(), 1 << 22))

    def test_a_missing_or_foreign_file_gives_none(self):
        for name in ("tables.npz", "tables.json", "meta.json"):
            model, folder = self.baked()
            (folder / name).unlink()
            self.assertIsNone(PC.load(model, G.HostSink(), 1 << 22), name)
            prepared_cache.remove_entry(folder)
        model, folder = self.baked()
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        for change in ({"key": "0" * 40}, {"version": PC.PAGES_VERSION + 1}, {"files": None}):
            (folder / "meta.json").write_text(json.dumps({**meta, **change}), encoding="utf-8")
            self.assertIsNone(PC.load(model, G.HostSink(), 1 << 22), change)
        (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        self.assertIsNotNone(PC.load(model, G.HostSink(), 1 << 22))

    def test_an_entry_that_does_not_fit_the_model_in_hand_gives_none(self):
        model, folder = self.baked()
        other = keyed_model(n=30)
        self.assertIsNone(PC.load(other, G.HostSink(), 1 << 22, key=folder.name))
        self.assertIsNotNone(PC.load(model, G.HostSink(), 1 << 22, key=folder.name))

    def test_stage_two_pages_of_another_budget_are_refused_then_replaced(self):
        os.environ["ANATOMY_GEOM_QERR"] = "1.0"
        kw = dict(cluster_order=True, compress=2)
        model, folder = self.baked(**kw)
        self.assertIsNotNone(PC.load(model, G.HostSink(), 1 << 22, **kw))
        os.environ["ANATOMY_GEOM_QERR"] = "0.25"
        self.assertEqual(folder.name, PC.make_key(model, 1 << 22, **kw))        # the budget is not in the key
        self.assertIsNone(PC.load(model, G.HostSink(), 1 << 22, **kw))
        self.assertTrue(PC.bake(model, 1 << 22, **kw)["fresh"])
        self.assert_same(G.build_geometry(model, G.HostSink(), 1 << 22, **kw), PC.load(model, G.HostSink(), 1 << 22, **kw))
        os.environ["ANATOMY_GEOM_QERR"] = "1.0"
        self.assertIsNone(PC.load(model, G.HostSink(), 1 << 22, **kw))

    def test_a_failing_sink_gives_none_and_frees_what_it_made(self):
        model = keyed_model(levels=False, n=12)
        nv = model.parts[0].vertex_count
        need = G.section_layout({"pos": nv, "nrm": nv, "dpos": nv, "index": model.parts[0].count})[1] * 4
        self.assertEqual(PC.bake(model, need, max_pages=3)["pages"], 3)
        sink = mock.Mock(wraps=G.HostSink())
        made = []

        def create(size, label=""):
            if len(made) == 2:
                raise MemoryError("device out of memory")
            made.append(np.zeros(size, np.uint8))
            return made[-1]

        sink.create.side_effect = create
        self.assertIsNone(PC.load(model, sink, need, max_pages=3))
        freed = [c.args[0] for c in sink.destroy.call_args_list]
        self.assertEqual(len(freed), 2)
        self.assertTrue(all(x is y for x, y in zip(freed, made)))


class SafeSaving(StoreCase):
    def test_too_little_disk_writes_nothing_and_is_remembered(self):
        model = keyed_model()
        with mock.patch.object(prepared_cache, "_disk_usage", return_value=TIGHT):
            self.assertIsNone(PC.bake(model, 1 << 22))
        self.assertEqual(self.entries(), [])                # no entry and no temporary folder
        key = PC.make_key(model, 1 << 22)
        self.assertIn("free disk", prepared_cache._refused[(str(self.store), key)])
        with mock.patch.object(G, "build_geometry") as build:
            self.assertIsNone(PC.bake(model, 1 << 22))      # not tried again in this run, although the disk has room now
            build.assert_not_called()
        self.assertIsNotNone(PC.bake(model, 1 << 23))       # another key is not held back

    def test_an_entry_over_the_cap_is_refused(self):
        os.environ["ANATOMY_PAGE_CACHE_GB"] = str(1000 / (1 << 30))
        self.assertIsNone(PC.bake(keyed_model(), 1 << 22))
        self.assertEqual(self.entries(), [])

    def test_a_model_that_does_not_fit_its_pages_is_refused_once(self):
        model = keyed_model(levels=False, n=12)
        self.assertIsNone(PC.bake(model, 256))
        self.assertEqual(self.entries(), [])
        with mock.patch.object(G, "build_geometry") as build:
            self.assertIsNone(PC.bake(model, 256))
            build.assert_not_called()

    def test_a_save_cut_off_before_meta_leaves_nothing_an_open_accepts(self):
        model = keyed_model()
        with mock.patch.object(prepared_cache, "write_meta", side_effect=OSError("power cut")):
            self.assertIsNone(PC.bake(model, 1 << 22))
        self.assertEqual(self.entries(), [])
        self.assertIsNone(PC.load(model, G.HostSink(), 1 << 22))

    def test_every_file_is_flushed_before_meta_and_meta_before_the_rename(self):
        model = keyed_model()
        steps = []
        real_fsync, real_meta, real_commit = os.fsync, prepared_cache.write_meta, prepared_cache.commit
        names = {}

        def opened(path, *a, **k):
            fh = real_open(path, *a, **k)
            names[fh.fileno()] = Path(path).name
            return fh

        real_open = open
        with mock.patch.object(PC, "open", side_effect=opened, create=True), \
                mock.patch.object(PC.os, "fsync", side_effect=lambda fd: steps.append(names.pop(fd, "?")) or real_fsync(fd)), \
                mock.patch.object(prepared_cache, "write_meta", side_effect=lambda *a: steps.append("meta") or real_meta(*a)), \
                mock.patch.object(prepared_cache, "commit", side_effect=lambda *a: steps.append("rename") or real_commit(*a)):
            self.assertTrue(PC.bake(model, 1 << 22)["fresh"])
        self.assertEqual(steps[steps.index("meta") + 1], "?")              # meta.json itself, flushed by write_meta
        named = [s for s in steps if s != "?"]
        self.assertEqual(named[-2:], ["meta", "rename"])
        self.assertEqual(sorted(named[:-2]), ["page0.npy", "tables.json", "tables.npz"])

    def test_a_second_writer_leaves_the_first_entry_as_it_is(self):
        model = keyed_model()
        info = PC.bake(model, 1 << 22)
        folder = self.store / info["key"]
        before = {f.name: (f.stat().st_mtime_ns, f.read_bytes()) for f in folder.iterdir()}
        self.assertFalse(PC.bake(model, 1 << 22)["fresh"])              # found: nothing is built
        real, calls = PC._open, []

        def blind_once(*args):
            calls.append(args)
            return None if len(calls) == 1 else real(*args)

        with mock.patch.object(PC, "_open", side_effect=blind_once):     # a writer that saw no entry when it started
            again = PC.bake(model, 1 << 22)
        self.assertFalse(again["fresh"])
        self.assertEqual(again["created"], info["created"])
        self.assertEqual(before, {f.name: (f.stat().st_mtime_ns, f.read_bytes()) for f in folder.iterdir()})
        self.assertEqual(self.entries(), [info["key"]])                  # its own temporary folder is gone

    def test_a_cancel_from_the_progress_callback_is_raised_and_not_remembered(self):
        model = keyed_model(levels=False, n=12)
        nv = model.parts[0].vertex_count
        need = G.section_layout({"pos": nv, "nrm": nv, "dpos": nv, "index": model.parts[0].count})[1] * 4

        def cancel(done, total):
            raise LoadCancelled()

        with self.assertRaises(LoadCancelled):
            PC.bake(model, need, max_pages=3, progress=cancel)          # raised after the first page was written
        self.assertEqual(self.entries(), [])                            # the half-made folder could be deleted
        self.assertTrue(PC.bake(model, need, max_pages=3)["fresh"])
        with self.assertRaises(LoadCancelled):
            PC.load(model, G.HostSink(), need, max_pages=3, progress=cancel)
        kw = dict(cluster_order=True, cluster_cache_use=False)
        with self.assertRaises(LoadCancelled):
            PC.bake(keyed_model(), 1 << 22, cluster_progress=cancel, **kw)
        self.assertTrue(PC.bake(keyed_model(), 1 << 22, **kw)["fresh"])


class Prune(StoreCase):
    def test_the_least_recently_opened_entries_go_first_and_meta_goes_first(self):
        model = keyed_model()
        infos = [PC.bake(model, size) for size in (1 << 22, 1 << 23, 1 << 24)]
        keys = [i["key"] for i in infos]
        for age, key in zip((300, 200, 100), keys):
            stamp = (self.store / key / "meta.json").stat().st_mtime - age
            os.utime(self.store / key / "meta.json", (stamp, stamp))
        size = sum(f.stat().st_size for f in (self.store / keys[0]).iterdir())
        self.assertIsNotNone(PC.load(model, G.HostSink(), 1 << 22))      # the oldest is opened: now the newest
        with mock.patch.object(prepared_cache.shutil, "rmtree"):         # what was moved aside cannot be deleted just now
            PC.prune(self.store, cap=2 * size + 100)
        left = [name for name in self.entries() if name.startswith(".tmp-gone-")]
        self.assertEqual(self.entries(), sorted([keys[0], keys[2]] + left))     # the middle one went, and only that one
        self.assertEqual(len(left), 1)
        self.assertEqual(sorted(f.name for f in (self.store / left[0]).iterdir()),      # of it, meta.json went first
                         ["page0.npy", "tables.json", "tables.npz"])
        self.assertIsNone(PC.load(model, G.HostSink(), 1 << 23))
        self.assertIsNotNone(PC.load(model, G.HostSink(), 1 << 22))
        self.assertIsNotNone(PC.load(model, G.HostSink(), 1 << 24))
        PC.prune(self.store, keep=keys[2], cap=0)
        self.assertEqual(self.entries(), sorted([keys[2]] + left))       # prune leaves what is not an entry alone
        self.assertTrue(PC.bake(model, 1 << 23)["fresh"])                # the next save clears it
        self.assertEqual(self.entries(), sorted([keys[1], keys[2]]))

    def test_a_save_prunes_to_the_cap_and_keeps_what_it_wrote(self):
        model = keyed_model()
        first = PC.bake(model, 1 << 22)
        size = sum(f.stat().st_size for f in (self.store / first["key"]).iterdir())
        os.environ["ANATOMY_PAGE_CACHE_GB"] = str((size + size // 2) / (1 << 30))
        second = PC.bake(model, 1 << 23)
        self.assertEqual(self.entries(), [second["key"]])

    def test_a_save_clears_abandoned_temporary_folders_and_never_one_whose_writer_holds_its_lock(self):
        model = keyed_model()
        abandoned = self.store / ".tmp-abandoned"
        abandoned.mkdir(parents=True)
        (abandoned / "page0.npy").write_bytes(b"x")
        writer = prepared_cache.TempFolder(self.store, "in-use")
        writer.path.mkdir()
        (writer.path / "page0.npy").write_bytes(b"x")
        old = writer.path.stat().st_mtime - 7200
        os.utime(writer.path, (old, old))                               # age says nothing about a writer
        in_use = [writer.path.name, writer.path.name + ".lock"]
        PC.prune(self.store, cap=0)
        self.assertEqual(self.entries(), sorted([".tmp-abandoned"] + in_use))
        with mock.patch.object(prepared_cache, "_disk_usage", return_value=TIGHT):
            self.assertIsNone(PC.bake(model, 1 << 22))                  # refused by the floor, and still it cleared up
        self.assertEqual(self.entries(), sorted(in_use))
        info = PC.bake(model, 1 << 23)
        self.assertEqual(self.entries(), sorted(in_use + [info["key"]]))
        writer.release()
        self.assertEqual(self.entries(), [info["key"]])

if __name__ == "__main__":
    unittest.main()
