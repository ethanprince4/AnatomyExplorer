"""Cut faces (caps.py) with the part classification on and off: the cap targets are identical bit for bit.

A part wholly on the removed side is not drawn by the cap passes, one wholly on the kept side draws without the clip test
(and without a fragment stage in the parity pass); the facing test is the pipeline's cull mode. None of it may change a pixel.
The scene is the cap parity scene (tools/perf/gpu/caps_parity.py); item 3 has two parts, one on each side of the planes used.
Needs a wgpu adapter only (no GL).

    python -m pytest tests/gpu/test_caps_skip.py -q -p no:cacheprovider
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np                                              # noqa: E402

SIZE = (256, 192)


def _setup():
    try:
        from app.gpu.device import get_gpu
        gpu = get_gpu()
        from tools.perf.gpu import caps_parity as cp
        return gpu, cp, cp.build_scene(0.5)
    except Exception as exc:
        return exc


STATE = _setup()
needs = unittest.skipIf(isinstance(STATE, Exception), f"no wgpu adapter: {STATE!r}")


@needs
class CapSkip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gpu, cls.cp, cls.model = STATE
        cls.wg = cls.cp.WGSide(cls.gpu, cls.model, SIZE)

    def run_caps(self, planes, on, mode=0, classify=True, yaw=0.4, pitch=0.3, ortho=False):
        from app.viewer.renderer import FrameState, Settings
        cp, wg, model = self.cp, self.wg, self.model
        w, h = SIZE
        cam = cp.make_camera(model, w, h, yaw, pitch, ortho)
        V, P = cam.view_matrix(), cam.proj_matrix(w / h)
        fs = FrameState(clip_planes=planes, clip_on=tuple(bool(x) for x in on), clip_mode=mode)
        s = Settings(msaa=1, ao=False, shadows=False)
        clip = (np.array(planes, np.float32), tuple(int(x) for x in on), mode)
        draws = [p for p in model.parts if not p.look.translucent]
        wg.caps.classify = classify
        plan = wg.caps.plan(model, wg.geom, draws, P @ V, V, SIZE, fs, s, clip, cam)
        if plan is None:
            return None, None, wg.caps.last_classes
        enc = wg.dev.create_command_encoder()
        wg.caps.encode_gather(enc, plan)
        wg.dev.queue.submit([enc.finish()])
        t = wg.caps.t
        out = {"zp": wg.read(t["zp"], np.float32, 1), "albedo": wg.read(t["albedo"], np.float16, 4),
               "normal": wg.read(t["normal"], np.float16, 4), "id": wg.read(t["id"], np.float32, 2),
               "key": wg.read(t["key"], np.float32, 1)}
        return plan, out, wg.caps.last_classes

    def same(self, planes, on, mode=0, **kw):
        """Targets with the classification on equal the ones with it off; returns (plan, class counts)."""
        pa, a, cls = self.run_caps(planes, on, mode, True, **kw)
        pb, b, _ = self.run_caps(planes, on, mode, False, **kw)
        self.assertIsNotNone(pa)
        self.assertGreater(int((a["zp"] > 0).sum()), 100)
        for k in a:
            self.assertTrue(np.array_equal(a[k], b[k]), f"{k} differs")
        return pa, cls

    @staticmethod
    def item_draws(plan, item):
        return [d for ci in plan.items if ci.item == item for d in ci.draws]

    # item 3: small spheres at x = 0.62 and x = -0.55 (radius 0.22, the same item). A plane (-1, 0, 0, d) removes x > d.
    def test_removed_part_is_skipped(self):
        plan, cls = self.same([(-1, 0, 0, -0.55), (0, 0, 0, 0), (0, 0, 0, 0)], (1, 0, 0))     # the right sphere is gone
        self.assertEqual(len(self.item_draws(plan, 3)), 1)
        self.assertGreater(cls[2], 0)

    def test_kept_part_takes_the_plain_pipelines(self):
        plan, cls = self.same([(-1, 0, 0, 0.62), (0, 0, 0, 0), (0, 0, 0, 0)], (1, 0, 0))      # the left sphere is kept
        d = self.item_draws(plan, 3)
        self.assertEqual(sorted(x[4] for x in d), [False, True])                              # (clip test needed): one plain, one clipped
        self.assertGreater(cls[0], 0)

    def test_other_planes_and_modes(self):
        planes = [(-1, 0, 0, 0.15), (0, -1, 0, 0.25), (0, 0, -1, 0.3)]
        self.same(planes, (1, 1, 0), 0, yaw=0.5, pitch=0.45)
        self.same(planes, (1, 1, 0), 1, yaw=0.55, pitch=0.5)
        self.same(planes, (1, 1, 1), 0, yaw=0.6, pitch=0.5)
        self.same(planes, (1, 1, 1), 1, yaw=0.6, pitch=0.55)
        self.same([(1, 0, 0, 0.62), (0, 0, 0, 0), (0, 0, 0, 0)], (1, 0, 0), yaw=-0.5)         # flipped: removes x < -0.62

    def test_orthographic(self):
        self.same([(-1, 0, 0, 0.05), (0, 0, 0, 0), (0, 0, 0, 0)], (1, 0, 0), yaw=0.35, pitch=0.25, ortho=True)


if __name__ == "__main__":
    unittest.main()
