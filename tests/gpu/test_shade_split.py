"""The split shaded resolve (app/gpu/shade_split.py, ANATOMY_SHADE_SPLIT): the extra triangles of edge pixels shaded in a compute pass
must give the picture of the plain shade pass (same arithmetic; only the compiler's rounding of a compute versus a fragment shader
differs). Needs a wgpu adapter.

    python -m pytest tests/gpu/test_shade_split.py -q -p no:cacheprovider
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

from test_frame_cull import GPU, H, W, camera_for, make_model, needs_gpu, target   # noqa: E402


def _opaque(r, cam, s, tgt, frames=3):
    for _ in range(frames):                                      # frame 2 reads frame 1's resolved colour (the SSAO)
        r.render(tgt, (W, H), cam, s, None)
    return r._read_texture(r.t["opaque"], 8, np.float16, 4).astype(np.float32)


@needs_gpu
class ShadeSplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.viewer.renderer import Settings
        cls.model = make_model()
        cls.s = Settings()
        cls.s.msaa = 4
        cls.tgt = target()

    def _compare(self, **kw):
        from app.gpu.renderer import WgpuRenderer
        r = WgpuRenderer(GPU, **kw)
        r.set_model(self.model)
        cam = camera_for(self.model)
        r.split.mode = "off"
        a = _opaque(r, cam, self.s, self.tgt)
        n0 = r.split.items
        r.split.mode = "on"
        b = _opaque(r, cam, self.s, self.tgt)
        self.assertGreater(r.split.items, n0, "the split pass ran")
        d = np.abs(a - b)
        self.assertLess(float(d.mean()), 1e-4)
        self.assertLess(float((d.max(-1) > 8 / 255).mean()), 1e-4, "pixels differing by more than 8/255")
        self.assertGreater(float(a[..., :3].max()), 0.1, "something was drawn")
        return r

    def test_same_picture(self):
        self._compare()

    def test_policy_and_storage_budget(self):
        from app.gpu.renderer import WgpuRenderer
        r = WgpuRenderer(GPU)
        r.limits = {"max_storage_buffers_per_shader_stage": 8}          # the apple7 stage budget
        r.split.mode = "off"
        self.assertFalse(r.split.enabled(4, 1))
        r.split.mode = "on"
        self.assertFalse(r.split.enabled(1, 1), "no extra triangles without multisampling")
        self.assertTrue(r.split.enabled(4, 6), "the table, the decode table and 6 pages are 8 storage buffers")
        self.assertFalse(r.split.enabled(4, 7), "one page more than the stage binds")


if __name__ == "__main__":
    unittest.main()
