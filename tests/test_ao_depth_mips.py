"""The depth chain of the fast renderer's ambient occlusion (app/gpu/post.py far_mips, wgsl/post_dmip.wgsl): far taps
read a coarser level of the depth texture so the pass costs the same at any zoom. Skips without a wgpu adapter."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.gpu import post as P                                    # noqa: E402
from app.gpu import renderer as R                                # noqa: E402


def _device():
    try:
        from app.gpu.device import get_gpu
        return get_gpu().device
    except Exception as exc:                                     # no adapter on this machine
        raise unittest.SkipTest(f"no wgpu device: {exc}")


def _level(dev, tex, i):
    w, h = max(tex.size[0] >> i, 1), max(tex.size[1] >> i, 1)
    m = dev.queue.read_texture({"texture": tex, "mip_level": i, "origin": (0, 0, 0)},
                               {"bytes_per_row": w * 4, "rows_per_image": h}, (w, h, 1))
    return np.frombuffer(m, dtype=np.float32).reshape(h, w).copy()


class LevelCountTest(unittest.TestCase):
    def test_levels_for_a_target_size(self):
        self.assertEqual(P.depth_mip_levels(3840, 2160), P.DEPTH_MIP_MAX + 1)
        self.assertEqual(P.depth_mip_levels(2560, 1600), P.DEPTH_MIP_MAX + 1)
        self.assertEqual(P.depth_mip_levels(97, 61), 3)          # 30 and 15 rows; 7 would be under 8
        self.assertEqual(P.depth_mip_levels(16, 400), 2)
        self.assertEqual(P.depth_mip_levels(15, 400), 1)
        self.assertEqual(P.depth_mip_levels(1, 1), 1)

    def test_switch_is_on_unless_turned_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANATOMY_AO_DEPTH_MIPS", None)
            self.assertTrue(R.ao_far_mips())
            for v, want in (("0", False), ("off", False), ("No", False), ("false", False), ("1", True), ("on", True), ("", True)):
                os.environ["ANATOMY_AO_DEPTH_MIPS"] = v
                self.assertEqual(R.ao_far_mips(), want, v)

    def test_post_passes_default_is_the_exact_path(self):
        # the parity tools build PostPasses(device) and compare against the GLSL original: that path must stay level 0
        import inspect
        self.assertFalse(inspect.signature(P.PostPasses.__init__).parameters["far_mips"].default)


class DepthChainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dev = _device()

    def test_each_level_is_one_real_depth_of_the_level_below(self):
        dev = self.dev
        pas = P.PostPasses(dev, far_mips=True)
        rng = np.random.default_rng(5)
        for w, h in ((97, 61), (256, 128)):                      # odd sizes: the pick is clamped at the last row / column
            nd = rng.standard_normal((h, w, 4)).astype(np.float32)
            nd[..., 3] = np.where(rng.random((h, w)) < 0.3, 0.0, np.abs(nd[..., 3]) * 5.0 + 0.1)   # 0 = background
            d = pas.pack_depth(P.make_texture(dev, w, h, "rgba32float", nd))
            self.assertEqual(d.mip_level_count, P.depth_mip_levels(w, h))
            pas.build_depth_mips(d)
            prev = _level(dev, d, 0)
            self.assertTrue(np.array_equal(prev.view(np.uint32), nd[..., 3].view(np.uint32)))
            for i in range(1, d.mip_level_count):
                got = _level(dev, d, i)
                hh, ww = got.shape
                y, x = np.mgrid[0:hh, 0:ww]
                want = prev[np.minimum(2 * y + (x & 1), prev.shape[0] - 1), np.minimum(2 * x + (y & 1), prev.shape[1] - 1)]
                self.assertTrue(np.array_equal(got.view(np.uint32), want.view(np.uint32)), (w, h, i))
                self.assertTrue(np.isin(got, nd[..., 3]).all())  # never a mean: background stays exactly 0
                prev = got

    def _scene(self, w=320, h=200):
        rng = np.random.default_rng(11)
        nd = np.zeros((h, w, 4), dtype=np.float32)
        nd[..., 2] = 1.0
        yy, xx = np.mgrid[0:h, 0:w]
        depth = 2.0 + 0.15 * np.sin(xx / 23.0) * np.cos(yy / 17.0)
        depth[60:140, 90:200] = 1.55                             # a block in front of the wall: creases all round it
        depth[:, 250:262] = 2.6                                  # a groove
        depth[:14] = 0.0                                         # a strip of background
        nd[..., 3] = depth
        prev = np.zeros((h, w, 4), dtype=np.float16)
        prev[..., :3] = rng.random((h, w, 3)) * 0.8
        prev[..., 3] = 1.0
        return nd, prev

    def _ssao(self, pas, nd, prev, depth=None):
        dev = self.dev
        h, w = nd.shape[:2]
        out = P.make_texture(dev, w, h, "rgba16float")
        # radius 0.6 at depth 2 with tan 0.5 on 200 rows = 60 px, the large scale 210 px: most taps are far taps
        pas.run_ssao(P.make_texture(dev, w, h, "rgba32float", nd), P.make_texture(dev, w, h, "rgba16float", prev), out,
                     tan=(0.8, 0.5), ortho=0, radius=0.6, power=1.6, large=3.5, large_mix=0.8, gi_on=1.0,
                     depth=depth, depth_ready=depth is not None)
        return P.read_texture(dev, out, np.float16, 4).astype(np.float32)

    def test_off_reads_level_0_only_and_on_keeps_the_picture(self):
        dev = self.dev
        nd, prev = self._scene()
        exact = self._ssao(P.PostPasses(dev, ao_scale=1, gi_scale=2), nd, prev)
        self.assertGreater(float((exact[..., 3] < 0.9).mean()), 0.05)      # the scene does have occlusion to keep

        # a depth texture that has the levels, with the switch off: the same picture bit for bit
        pas = P.PostPasses(dev, ao_scale=1, gi_scale=2, far_mips=True)
        d = pas.pack_depth(P.make_texture(dev, nd.shape[1], nd.shape[0], "rgba32float", nd))
        self.assertGreater(d.mip_level_count, 1)
        pas.far_mips = False
        self.assertTrue(np.array_equal(self._ssao(pas, nd, prev, depth=d), exact))

        # switch on: the far taps read the chain; same darkening on average, differences at the size of the tap noise
        pas.far_mips = True
        got = self._ssao(pas, nd, prev)
        self.assertFalse(np.array_equal(got, exact))                       # the chain really is in use
        ao, ao0 = got[..., 3], exact[..., 3]
        self.assertTrue(np.isfinite(got).all())
        self.assertTrue(np.array_equal(ao[:14], ao0[:14]))                 # background rows untouched
        self.assertLess(abs(float(ao.mean() - ao0.mean())), 0.004, "the chain must not brighten or darken the AO")
        self.assertLess(float(np.abs(ao - ao0).mean()), 0.02)
        self.assertLess(float(np.abs(got[..., :3] - exact[..., :3]).mean()), 0.01)

    def test_full_and_half_resolution_paths_take_the_chain(self):
        dev = self.dev
        nd, prev = self._scene()
        for ao_scale, gi_scale in ((1, 1), (2, 2)):
            exact = self._ssao(P.PostPasses(dev, ao_scale=ao_scale, gi_scale=gi_scale), nd, prev)
            got = self._ssao(P.PostPasses(dev, ao_scale=ao_scale, gi_scale=gi_scale, far_mips=True), nd, prev)
            self.assertLess(abs(float(got[..., 3].mean() - exact[..., 3].mean())), 0.004, (ao_scale, gi_scale))
            self.assertLess(float(np.abs(got[..., 3] - exact[..., 3]).mean()), 0.02, (ao_scale, gi_scale))


if __name__ == "__main__":
    unittest.main()
