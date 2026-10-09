"""The compact index budget of the culler (app/gpu/cull.py): the indexed draws (slots inside the budget) and the pulled draws (slots over
it) write the same ids and depth as the pulled-only path (budget 0), whatever the budget. Skipped without an adapter."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _gpu():
    try:
        from app.gpu.device import get_gpu
        return get_gpu()
    except Exception:
        return None


@unittest.skipIf(_gpu() is None, "no wgpu adapter")
class BudgetSplitTest(unittest.TestCase):
    def _frames(self, budget):
        """(ids, depth bits, stats) of the culled image after two warm frames and an orbit step, model eyeball."""
        from tools.perf.gpu import cull_check as cc
        try:
            H = cc.Harness("eyeball", None, size=(480, 300), budget=budget)
        except Exception as e:
            self.skipTest(f"harness unavailable: {e}")
        try:
            cam = H.reset_view()
            fs = H.base_state()
            H.cu.reset()
            out = []
            for i in range(3):
                if i == 2:
                    cam.orbit(9.0, 2.0)
                    cam.snap()
                r = H.run_frame(cam, fs)
                self.assertEqual(r["false_cull_samples"], 0)
                self.assertEqual(r["nearer_samples"], 0)
                self.assertEqual(r["stray_ids"], 0)
                ids, depth = H._read(H.dump_buf)
                out.append((ids.copy(), depth.view(np.uint32).copy(), dict(r["stats"])))
            return out, H.cu.budget_tris
        finally:
            H.release()

    def test_overflow_split_gives_the_same_picture(self):
        base, b0 = self._frames(0)
        self.assertEqual(b0, 0)
        for fr in base:
            self.assertEqual(fr[2]["idx_slots"], 0)
        for budget in (4096, 40000, 1 << 22):               # over the whole visible set / split / fits entirely
            got, eff = self._frames(budget)
            self.assertEqual(eff, budget // 64 * 64)
            for (i0, d0, s0), (i1, d1, s1) in zip(base, got):
                self.assertEqual(s1["idx_slots"] + s1["pull_slots"], s0["pull_slots"], f"slots drawn, budget {budget}")
                if budget < 1 << 22:
                    self.assertGreater(s1["pull_slots"], 0, f"budget {budget} must overflow")
                self.assertGreater(s1["idx_slots"], 0)
                self.assertTrue(np.array_equal(d0, d1), f"depth differs, budget {budget}")
                self.assertLess(int((i0 != i1).sum()), max(8, len(i0) // 5000), f"ids differ beyond ties, budget {budget}")
            if budget >= 1 << 22:
                self.assertEqual(got[0][2]["pull_slots"], 0)


if __name__ == "__main__":
    unittest.main()
