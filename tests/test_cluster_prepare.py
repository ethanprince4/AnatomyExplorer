"""The fast renderer's clusters are made on the load thread (app/gpu/prep.py): the GUI thread's request gets the set
riding on the model, nothing is built twice when the set cannot be kept on disk, and a cancelled load stops the build
at its next part. No GPU: the geometry is built into a host sink, the way the renderer builds it into the device."""
import hashlib
import inspect
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from app.gpu import cluster_cache, clusters as cl, device, geometry as G, prep
from app.load_control import LoadCancelled
from app.viewer import prepared_cache
from app.viewer.model_loading import ModelLoadQueue

LOAD, MAIN = "model-load", threading.main_thread().name
SHEETS = 48


def write_model(path, ribbon=True, sheets=SHEETS):
    """A small valid model file: ``sheets`` wavy sheets of 40 x 40 squares (no detail levels) and, with ``ribbon``, a
    ribbon of 3000 x 4 squares first, fine enough against the size of the model to get detail levels."""
    shapes = ([("ribbon", 3001, 5, 4.0 / 3000.0)] if ribbon else []) + [(f"sheet{k}", 41, 41, 1.0) for k in range(sheets)]
    arrays = {"meta": np.frombuffer(json.dumps({"parts": [{"name": s[0]} for s in shapes]}).encode(), np.uint8)}
    for i, (_name, nu, nv, width) in enumerate(shapes):
        v, u = np.meshgrid(np.linspace(0.0, width, nv), np.linspace(0.0, 1.0, nu))
        a = (np.arange(nu - 1)[:, None] * nv + np.arange(nv - 1)[None, :]).reshape(-1)
        z = 0.05 * np.sin(9.0 * u + i) * np.cos(7.0 * v) + 0.3 * i
        arrays[f"p{i}"] = np.stack([u, v, z], axis=-1).reshape(-1, 3).astype(np.float32)
        arrays[f"i{i}"] = np.concatenate([np.stack([a, a + 1, a + nv], 1), np.stack([a + 1, a + nv + 1, a + nv], 1)]).astype(np.int32)
    np.savez_compressed(path, **arrays)
    return path


def entry_of(path):
    from app.variants.catalog import DeferredVariantEntry
    from app.variants.local_library import SingleFileLibrary
    store = SingleFileLibrary(str(path))
    return DeferredVariantEntry(store.metadata(store.model_id), store)


def sha1s(cd):
    return {name: hashlib.sha1(np.ascontiguousarray(np.asarray(getattr(cd, name))).data).hexdigest()
            for name in cluster_cache._ARRAYS}


class Case(unittest.TestCase):
    """Caches in a temporary folder, the fast renderer asked for by the settings, clusters from 1000 triangles on, and a
    record of the thread of every cluster step."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="cluster-prepare-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        env = mock.patch.dict(os.environ, {"ANATOMY_PREPARED_CACHE": str(self.root / "prepared_models"),
                                           "ANATOMY_CLUSTER_CACHE": str(self.root / "clusters"),
                                           "ANATOMY_CULL_MIN_TRIS": "1000"})
        env.start()
        self.addCleanup(env.stop)
        for name in ("ANATOMY_RENDERER", "ANATOMY_CULL"):
            os.environ.pop(name, None)
        self.addCleanup(prep.use_settings, prep._settings)
        prep.use_settings({"fast_renderer": True})
        self.patch(device, "_failure", None)
        saved = dict(prepared_cache._refused)
        prepared_cache._refused.clear()
        self.addCleanup(prepared_cache._refused.update, saved)
        self.addCleanup(prepared_cache._refused.clear)
        self.addCleanup(prepared_cache.wait_for_saves)
        self.steps = []                     # (step, thread name)
        self.build = cl.build_clusters
        for obj, name in ((cl, "build_clusters"), (cluster_cache, "load"), (cluster_cache, "save"), (cluster_cache, "make_key")):
            self.spy(obj, name)
        self.path = write_model(self.root / "model.npz")

    def patch(self, obj, name, value):
        patcher = mock.patch.object(obj, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def spy(self, obj, name):
        original = getattr(obj, name)

        def wrapper(*args, **kwargs):
            self.steps.append((name, threading.current_thread().name))
            return original(*args, **kwargs)
        self.patch(obj, name, wrapper)

    def threads(self, step):
        return [thread for name, thread in self.steps if name == step]

    def open(self, path=None):
        """One open on the app's load queue, the main thread polling as the app does. Returns the model."""
        queue = ModelLoadQueue()
        self.addCleanup(queue.close)
        queue.request("m", entry_of(path or self.path))
        deadline = time.monotonic() + 120.0
        result = None
        while result is None and time.monotonic() < deadline:
            result = queue.take_result()
            if result is None:
                time.sleep(0.005)
        queue.close()
        self.assertIsNotNone(result, "the load did not finish")
        self.assertEqual(result.error, "")
        prepared_cache.wait_for_saves()
        return result.model

    def draw(self, model):
        """What the renderer's set_model does with the model on the GUI thread, into a host sink."""
        return G.build_geometry(model, G.HostSink(), 1 << 22, cluster_order=prep.wants_clusters(model))


class LoadThreadTests(Case):
    def test_the_main_thread_neither_builds_nor_reads_the_clusters(self):
        first = self.open()
        self.assertIsNone(getattr(first.vertices, "filename", None), "the first open decodes into RAM")
        self.assertTrue(first.lod, "the ribbon has detail levels")
        self.assertEqual(self.threads("build_clusters"), [LOAD])
        self.assertEqual(self.threads("save"), [LOAD])
        riding = cluster_cache.carried(first)
        self.assertIsNotNone(riding)
        self.assertEqual((riding.stats["cached"], riding.stats["saved"]), (False, True))
        self.assertEqual(sha1s(riding), sha1s(self.build(first, None)))
        on_load = len(self.steps)

        self.assertIs(cluster_cache.get_clusters(first), riding)
        geom = self.draw(first)
        self.assertTrue(geom.cluster_ordered)
        self.assertEqual(sha1s(geom.clusters), sha1s(riding))
        self.assertEqual(self.steps[on_load:], [], "the main thread's request must cost nothing")
        self.assertNotIn(MAIN, [thread for _name, thread in self.steps])

        second = self.open()                # the prepared path: mapped arrays, clusters found in the store
        self.assertIsInstance(second.vertices, np.memmap)
        self.assertEqual(self.threads("build_clusters"), [LOAD], "the second open builds nothing")
        self.assertEqual(cluster_cache.carried(second).stats["cached"], True)
        self.assertEqual(sha1s(self.draw(second).clusters), sha1s(riding))
        self.assertNotIn(MAIN, [thread for _name, thread in self.steps])

    def test_built_exactly_once_when_the_set_cannot_be_kept(self):
        def refuse(*_args, **_kwargs):
            raise PermissionError("read-only folder")
        # save() is asked in the first three cases and gives up at once; a model with no identity never asks
        cases = {"cluster cache off": (mock.patch.dict(os.environ, {"ANATOMY_CLUSTER_CACHE": "off"}), [LOAD]),
                 "disk full": (mock.patch.object(prepared_cache, "disk_allows", lambda *_a, **_k: False), [LOAD]),
                 "read-only": (mock.patch.object(cluster_cache, "_write", refuse), [LOAD]),
                 "no identity": (mock.patch.object(cluster_cache, "prepared_identity", lambda _model: None), [])}
        for n, (label, (arranged, saves)) in enumerate(cases.items()):
            folders = {"ANATOMY_PREPARED_CACHE": str(self.root / f"prepared-{n}"), "ANATOMY_CLUSTER_CACHE": str(self.root / f"clusters-{n}")}
            with self.subTest(label), mock.patch.dict(os.environ, folders), arranged:
                del self.steps[:]
                prepared_cache._refused.clear()
                model = self.open()
                riding = cluster_cache.carried(model)
                self.assertIsNotNone(riding)
                self.assertEqual((riding.stats["cached"], bool(riding.stats.get("saved"))), (False, False))
                first, again = self.draw(model), self.draw(model)       # a view, and a hidden tab drawn again
                self.assertEqual(self.threads("build_clusters"), [LOAD], "built once, on the load thread")
                self.assertEqual(self.threads("save"), saves)
                self.assertNotIn(MAIN, [thread for _name, thread in self.steps])
                self.assertEqual(list(self.root.glob(f"clusters-{n}/*/meta.json")), [], "nothing was kept on disk")
                self.assertEqual(sha1s(first.clusters), sha1s(again.clusters))
                self.assertEqual(sha1s(first.clusters), sha1s(self.build(model, None)))

    def test_a_set_made_for_another_layout_is_not_handed_out(self):
        model = self.open()
        riding = cluster_cache.carried(model)
        self.assertIsNotNone(riding)
        model.lod = {}                      # the ribbon loses its detail levels: the ranges of the set no longer fit
        self.assertIsNone(cluster_cache.carried(model))
        del self.steps[:]
        fresh = cluster_cache.get_clusters(model)
        self.assertEqual(self.threads("build_clusters"), [MAIN])
        self.assertLess(fresh.n_ranges, riding.n_ranges)

    def test_a_build_that_fails_is_not_run_again_on_the_main_thread(self):
        def bad(*_args, **_kwargs):
            self.steps.append(("failing build", threading.current_thread().name))
            raise cl.ClusterError("parts index vertices outside their own range: sheet0")
        self.patch(cl, "build_clusters", bad)
        with self.assertLogs("app.gpu.prep", "WARNING"):
            model = self.open()             # the model still opens
        self.assertEqual(self.threads("failing build"), [LOAD])
        with self.assertRaisesRegex(cl.ClusterError, "sheet0"):
            cluster_cache.get_clusters(model)
        with self.assertRaisesRegex(cl.ClusterError, "sheet0"):
            self.draw(model)
        self.assertEqual(self.threads("failing build"), [LOAD])


class WantedTests(Case):
    def built_on_load(self):
        del self.steps[:]
        self.opens = getattr(self, "opens", 0) + 1
        os.environ["ANATOMY_CLUSTER_CACHE"] = str(self.root / f"clusters-{self.opens}")       # an empty store every time
        model = self.open()
        riding = cluster_cache.carried(model)
        self.assertEqual(self.threads("build_clusters"), [LOAD] if riding is not None else [])
        return riding is not None

    def test_only_when_the_fast_renderer_is_wanted_and_the_triangle_rule_holds(self):
        self.assertTrue(self.built_on_load())
        prep.use_settings({"fast_renderer": False})
        self.assertFalse(self.built_on_load(), "the standard renderer needs no clusters")
        prep.use_settings({"fast_renderer": False, "renderer_backend": "wgpu"})
        self.assertTrue(self.built_on_load())
        prep.use_settings(None)
        self.assertFalse(self.built_on_load(), "outside the app nothing is prepared unasked")
        with mock.patch.dict(os.environ, {"ANATOMY_RENDERER": "wgpu"}):
            self.assertTrue(self.built_on_load(), "ANATOMY_RENDERER=wgpu asks for it by name")
        prep.use_settings({"fast_renderer": True})
        with mock.patch.dict(os.environ, {"ANATOMY_RENDERER": "opengl"}):
            self.assertFalse(self.built_on_load())
        with mock.patch.dict(os.environ, {"ANATOMY_CULL": "off"}):
            self.assertFalse(self.built_on_load(), "the culler is switched off")
        with mock.patch.dict(os.environ, {"ANATOMY_CULL_MIN_TRIS": "1000000"}):
            self.assertFalse(self.built_on_load(), "too few triangles for the culler to ever run")
            with mock.patch.dict(os.environ, {"ANATOMY_CULL": "on"}):
                self.assertTrue(self.built_on_load())
        with mock.patch.object(device, "_failure", "no adapter"):
            self.assertFalse(self.built_on_load(), "the fast renderer could not start in this session")
        self.assertTrue(self.built_on_load())


class CancelTests(Case):
    def test_a_cancel_stops_the_build_at_the_next_progress_call(self):
        path = write_model(self.root / "sheets.npz", ribbon=False)
        workers = min(8, max(1, os.cpu_count() or 2))
        self.assertLess(2 * workers, SHEETS)
        started, gate, lock, ranges, progress, ended = threading.Event(), threading.Event(), threading.Lock(), [], [], []
        build_range, checkpoint, build = cl._build_range, prep._checkpoint, cl.build_clusters

        def slow_range(*args, **kwargs):
            with lock:
                ranges.append(threading.current_thread().name)
            started.set()
            gate.wait(60.0)                 # the parts being worked on wait here until the load has been cancelled
            time.sleep(0.05)                # and stay slow, so the load thread hears of the first one before many more start
            return build_range(*args, **kwargs)

        def counted(done, total):
            progress.append((done, total))
            return checkpoint(done, total)

        def watched(*args, **kwargs):
            try:
                return build(*args, **kwargs)
            except BaseException as exc:
                ended.append(type(exc))
                raise
            finally:
                ended.append("left")

        self.patch(cl, "_build_range", slow_range)
        self.patch(prep, "_checkpoint", counted)
        self.patch(cl, "build_clusters", watched)
        queue = ModelLoadQueue()
        self.addCleanup(queue.close)
        self.addCleanup(gate.set)
        queue.request("m", entry_of(path))
        self.assertTrue(started.wait(120.0), "the cluster build did not start on the load thread")
        queue.cancel("m")                   # the tab is closed while the build runs
        gate.set()
        deadline = time.monotonic() + 60.0
        while "left" not in ended and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(ended, [LoadCancelled, "left"], "the build must end with the load's cancellation")
        self.assertEqual(progress, [(1, SHEETS)], "the first progress call after the cancel is the last")
        # the parts being worked on finish, and a free worker may take one more before the load thread hears of the first
        self.assertLessEqual(len(ranges), 2 * workers, "the parts not started must be dropped")
        self.assertNotIn(MAIN, ranges)
        count = len(ranges)
        time.sleep(0.1)
        self.assertEqual(len(ranges), count, "no part is started after the build has ended")
        self.assertIsNone(queue.take_result())
        self.assertEqual(list(self.root.glob("clusters/*/meta.json")), [])
        self.assertEqual(self.threads("save"), [])

    def test_a_raising_progress_callback_drops_the_parts_not_started(self):
        model = self.open(write_model(self.root / "sheets.npz", ribbon=False))
        seen, calls = [], []
        build_range = cl._build_range

        def slow_range(*args, **kwargs):
            calls.append(1)
            time.sleep(0.02)
            return build_range(*args, **kwargs)

        def stop(done, total):
            seen.append(done)
            raise LoadCancelled()
        self.patch(cl, "_build_range", slow_range)
        with self.assertRaises(LoadCancelled):
            self.build(model, None, threads=2, progress=stop)
        self.assertEqual(seen, [1])
        time.sleep(0.1)
        self.assertLessEqual(len(calls), 8, "a build stopped after its first part must not work through the rest")
        self.assertLess(len(calls), SHEETS)


def stub_model(tris=3000, morph=False, anim=None, texture=None, alpha_cut=0.0, parts=2):
    look = SimpleNamespace(texture=texture, alpha_cut=alpha_cut)
    return SimpleNamespace(anim_vertices=anim, parts=[SimpleNamespace(id=f"p{k}", look=look, has_morph=morph and k == 1,
                                                                      count=3 * tris // parts) for k in range(parts)])


class SameRuleTests(unittest.TestCase):
    """prep.py repeats two rules it cannot import on the load thread. These hold each pair together."""

    def setUp(self):
        self.saved = {name: os.environ.pop(name, None) for name in ("ANATOMY_RENDERER", "ANATOMY_CULL", "ANATOMY_CULL_MIN_TRIS")}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in self.saved.items()])

    def test_the_backend_rule_is_the_model_views(self):
        from app.ui import model_view
        for env in (None, "opengl", "wgpu", "WGPU", "nonsense", ""):
            os.environ.pop("ANATOMY_RENDERER", None)
            if env is not None:
                os.environ["ANATOMY_RENDERER"] = env
            for settings in ({}, {"fast_renderer": True}, {"fast_renderer": False}, {"fast_renderer": None},
                             {"renderer_backend": "wgpu", "fast_renderer": False}, {"renderer_backend": "opengl"},
                             {"renderer_backend": "nonsense", "fast_renderer": False}, {"renderer_backend": " WGPU "}):
                self.assertEqual(prep.renderer_backend(settings), model_view.renderer_backend(settings), (env, settings))

    def test_the_cluster_rule_is_the_renderers(self):
        try:
            from app.gpu import renderer as R
        except Exception as exc:            # noqa: BLE001 - no wgpu on this PC
            self.skipTest(f"the fast renderer cannot be imported: {exc}")
        self.assertEqual(prep.CULL_MIN_TRIS, R.CULL_MIN_TRIS)
        reads = inspect.getsource(R.WgpuRenderer.__init__)
        for text in ('os.environ.get("ANATOMY_CULL", "auto")', '("on", "off", "auto", "plain")',
                     'os.environ.get("ANATOMY_CULL_MIN_TRIS") or CULL_MIN_TRIS'):
            self.assertIn(text, reads, "the renderer reads its cull mode another way now: bring app/gpu/prep.cull_rule in line")
        models = {"static": stub_model(), "large": stub_model(tris=2_000_000), "edge": stub_model(tris=1_000_000),
                  "below": stub_model(tris=999_999), "morph": stub_model(tris=2_000_000, morph=True),
                  "animated": stub_model(tris=2_000_000, anim=np.zeros((1, 3), np.float32))}
        for mode in (None, "on", "off", "auto", "plain", "ON ", "nonsense"):
            for least in (None, "1000", "2.5e6", "0"):
                for name, value in (("ANATOMY_CULL", mode), ("ANATOMY_CULL_MIN_TRIS", least)):
                    os.environ.pop(name, None)
                    if value is not None:
                        os.environ[name] = value
                cull_mode, cull_min_tris = prep.cull_rule()
                renderer = SimpleNamespace(cull_mode=cull_mode, cull_min_tris=cull_min_tris)
                for label, model in models.items():
                    self.assertEqual(prep.wants_clusters(model), R.WgpuRenderer._wants_cluster_order(renderer, model),
                                     (mode, least, label))
        # a model set_model refuses (alpha-cut texture: OpenGL draws it) gets no clusters
        cut = stub_model(tris=2_000_000, texture=0, alpha_cut=0.5)
        with self.assertRaises(NotImplementedError):
            R.WgpuRenderer.set_model(SimpleNamespace(release_model=lambda: None), cut)
        self.assertFalse(prep.wants_clusters(cut))
        self.assertTrue(prep.wants_clusters(stub_model(tris=2_000_000, texture=0, alpha_cut=0.0)))


if __name__ == "__main__":
    unittest.main()
