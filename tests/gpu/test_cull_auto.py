"""ANATOMY_CULL=auto chooses per frame between the cluster culler and the plain draw (app/gpu/cull_policy.py). GPU side: the counters
the choice reads (kept / pulled clusters, written by the culler every frame), their asynchronous readback, and that switching
between the two paths never changes the picture. The switching logic itself is tested without a GPU in tests/test_cull_policy.py.

    python -m pytest tests/gpu/test_cull_auto.py -q -p no:cacheprovider
"""
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests", ROOT / "tests" / "gpu"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

from test_frame_cull import GPU, H, W, camera_for, make_model, needs_gpu, target   # noqa: E402


@needs_gpu
class AutoChoice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.gpu.renderer import WgpuRenderer
        from app.viewer.renderer import Settings
        cls.model = make_model()
        cls.s = Settings()
        cls.s.msaa = 4
        cls.tgt = target()
        cls.on = WgpuRenderer(GPU, cull="on")
        cls.on.set_model(cls.model)
        cls.auto = WgpuRenderer(GPU, cull="auto", cull_min_tris=100)       # the small test scene is ordered and has a governor
        cls.auto.set_model(cls.model)

    @classmethod
    def tearDownClass(cls):
        cls.on.release()
        cls.auto.release()

    def frame(self, r, cam):
        r.render(self.tgt, (W, H), cam, self.s, None)
        return r.read_ids()[0], r.read_model_triangles()

    def test_the_counters_agree_with_the_per_cluster_statistics(self):
        cam = camera_for(self.model)
        self.on.culler.collect_stats = True
        try:
            for _ in range(3):
                self.frame(self.on, cam)
            st = self.on.culler.read_stats()
        finally:
            self.on.culler.collect_stats = False
        self.assertGreater(st["kept"], 0)
        self.assertEqual(st["kept"], st["p1"] + st["p2"])
        self.assertEqual(st["pulled"], st["pull_slots"])

    def test_clusters_over_the_index_budget_are_counted_as_pulled(self):
        from app.gpu.renderer import WgpuRenderer
        old = os.environ.get("ANATOMY_CULL_BUDGET")
        os.environ["ANATOMY_CULL_BUDGET"] = "128"                          # two slots of 64 triangles
        try:
            r = WgpuRenderer(GPU, cull="on")
            r.set_model(self.model)
        finally:
            if old is None:
                del os.environ["ANATOMY_CULL_BUDGET"]
            else:
                os.environ["ANATOMY_CULL_BUDGET"] = old
        try:
            r.culler.collect_stats = True
            cam = camera_for(self.model)
            for _ in range(3):
                self.frame(r, cam)
            st = r.culler.read_stats()
            self.assertGreater(st["pulled"], 0)
            self.assertEqual(st["pulled"], st["pull_slots"])
            self.assertEqual(st["kept"] - st["pulled"], st["idx_slots"])
        finally:
            r.release()

    def test_counters_arrive_without_waiting_and_feed_the_governor(self):
        r = self.auto
        gov = r.gov
        self.assertIsNotNone(gov)
        gov.save_tris = 1.0                                                # the scene saves more than that: the probe ends culled
        gov._to("probe")
        gov.probe_frames = 0
        gov.got_counters = False
        cam = camera_for(self.model)
        for _ in range(80):
            self.frame(r, cam)
            if gov.got_counters:
                break
            time.sleep(0.01)
        self.assertTrue(r.culled_frame)
        self.assertTrue(gov.got_counters, "no counters came back")
        for _ in range(10):
            self.frame(r, cam)
            time.sleep(0.01)
        self.assertEqual(gov.state, "cull")
        self.assertIsNotNone(gov.saved(10_000))

    def test_both_paths_and_the_switch_between_them_give_the_same_picture(self):
        r, gov = self.auto, self.auto.gov
        for yaw, pitch in ((0.4, 0.3), (2.0, -0.4)):
            cam = camera_for(self.model, yaw, pitch)
            ref_ids, (ref_part, ref_tri) = None, (None, None)
            for state in ("cull", "plain", "cull", "plain"):
                gov.state, gov.since, gov.interval = state, gov.frame, 10 ** 9
                gov.save_tris, gov.recent = (1.0 if state == "cull" else 1e12), type(gov.recent)(maxlen=gov.recent.maxlen)
                ids, (part, tri) = self.frame(r, cam)
                if state == "cull":
                    self.assertTrue(r.culled_frame)
                elif not r.geom.compressed:
                    self.assertFalse(r.culled_frame)
                else:
                    self.assertTrue(r.culled_frame and r.cull_accept_all)      # compressed geometry: the culler accepting every cluster
                if ref_ids is None:
                    ref_ids, ref_part, ref_tri = ids, part, tri
                    continue
                self.assertTrue(np.array_equal(ids, ref_ids), f"items differ ({state}, yaw {yaw})")
                self.assertTrue(np.array_equal(part, ref_part))
                bad = int((tri != ref_tri).sum())
                self.assertLessEqual(bad, max(2, int((part >= 0).sum()) // 1000))


if __name__ == "__main__":
    unittest.main()
