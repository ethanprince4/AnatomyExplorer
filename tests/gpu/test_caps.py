"""Cut caps on wgpu (app/gpu/caps.py) against the GL chain on a synthetic closed-mesh scene (tools/perf/gpu/caps_parity.py).
Skips without a wgpu adapter or a GL 4.1 context.

    python -m pytest tests/gpu/test_caps.py -q -p no:cacheprovider
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np                                              # noqa: E402

SIZE = (192, 144)


def _setup():
    try:
        from app.gpu.device import get_gpu
        gpu = get_gpu()
        from tools.perf.gpu import caps_parity as cp
        model = cp.build_scene(0.5)
        return gpu, cp, model, cp.GLSide(model, SIZE)
    except Exception as exc:                                    # no adapter, no GL context
        return exc


STATE = _setup()
needs = unittest.skipIf(isinstance(STATE, Exception), f"no wgpu adapter or GL context: {STATE!r}")


@needs
class CapParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gpu, cls.cp, cls.model, cls.glside = STATE
        cls.wg = cls.cp.WGSide(cls.gpu, cls.model, SIZE)

    def run_case(self, name, msaa=1):
        case = self.cp.CASES[name]
        gl = self.glside.run(case, msaa)
        wg = self.wg.run(gl, case)
        return gl, wg, self.cp.compare(gl, wg, SIZE, msaa)

    def check(self, row):
        self.assertGreater(row["cap_px_gl"], 200)
        self.assertEqual((row["only_gl"], row["only_wgpu"]), (0, 0))           # same cut-face pixels
        self.assertEqual(row["uniform_records_differ"], 0)                      # same per-draw look / clip uniforms
        self.assertEqual(row["cap_id_mismatch"], 0)
        self.assertLess(row["zp_max_abs"], 1e-5)
        self.assertEqual(row["normal_max_abs"], 0.0)
        self.assertEqual(row["id_flags_differ"], 0)                             # id / flag 2 after the lay-in
        self.assertEqual(row["nd_differ_outside_caps"], 0)
        self.assertLess(row["lay_nd_depth_max_rel"], 1e-5)
        self.assertLess(row["col_max"], 2.0)                                    # 1/255 units, same draw as CAPMIX_FS
        self.assertLess(row["col_mean"], 0.2)
        self.assertLess(row["depth_after_max_abs"], 1e-5)

    def test_clip_mode0_two_planes(self):
        self.check(self.run_case("m0_2planes")[2])

    def test_clip_mode1_corner(self):
        self.check(self.run_case("m1_3planes")[2])

    def test_orthographic_and_msaa4(self):
        self.check(self.run_case("ortho_1plane", 4)[2])

    def test_selection_and_hover_flags(self):
        gl, wg, row = self.run_case("tilted_sel_hover")
        self.check(row)
        ids = np.unique(wg["id_cap"][wg["zp"] > 0][:, 0])
        self.assertTrue({2.0, 5.0} & set(ids.tolist()))                         # item 1 is selected (id 2) and hovered 2 (id 3)
        sel = (np.rint(wg["id_cap"][..., 1]).astype(int) & 1) != 0
        self.assertEqual(int(sel.sum()), int(((np.rint(gl["id_cap"][..., 1]).astype(int) & 1) != 0).sum()))

    def test_mirrored_part_cut_and_noclip_item_never(self):
        mirrored = {p.item for p in self.model.parts if np.linalg.det(self.model.part_matrix(p)[:3, :3]) < 0}
        noclip = {i for i, it in enumerate(self.model.items) if not it.clip}
        self.assertTrue(mirrored and noclip)
        gl, wg, row = self.run_case("m1_2planes")
        self.check(row)
        cut = {int(v) - 1 for v in np.unique(wg["id_cap"][..., 0][wg["zp"] > 0])}
        self.assertTrue(mirrored <= cut, "the negative-determinant part must carry a cut face")
        self.assertFalse(noclip & cut, "an item with clip = False must never be capped")
        flagged = {int(v) - 1 for v in np.unique(wg["id"][..., 0][(np.rint(wg["id"][..., 1]).astype(int) & 2) != 0])}
        self.assertTrue(mirrored <= flagged)

    def test_no_plane_crossing_no_plan(self):
        case = dict(self.cp.CASES["m0_1plane"], planes=self.cp._planes((-1, 0, 0, 100.0)))
        gl = self.glside.run(case, 1)
        self.assertIsNone(self.wg.run(gl, case)["plan"])


if __name__ == "__main__":
    unittest.main()
