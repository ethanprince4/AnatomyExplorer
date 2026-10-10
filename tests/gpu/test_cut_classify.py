"""Cut views: geometry is classified against the cut planes (app/gpu/cutclass.py on the CPU, cull_test.wgsl per cluster on the GPU).
Boxes wholly on the kept side are drawn without the clip discard, boxes wholly on the removed side are skipped, the rest keep the
discard. The tests check the classes (kept, removed, straddling, flipped sections, several sections, corner mode, exploded, morphed,
never-cut parts, boxes at the camera) and that a cut frame with classification on decodes to the same picture as with it off, on the
plain path and on the culler (compressed or not). Skips the frame tests without a wgpu adapter.

    python -m pytest tests/gpu/test_cut_classify.py -q -p no:cacheprovider
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests", ROOT / "tests" / "gpu"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

from app.gpu import cutclass                                    # noqa: E402
from app.gpu.cutclass import KEPT, REMOVED, STRADDLE            # noqa: E402

EYE = np.eye(4)
VIEW = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, -50.0], [0, 0, 0, 1]])      # camera 50 units in front of the origin
TAN = 0.5                                                       # tan(half fov y); 1000 px high: a pixel is 0.05 units at depth 50
PLANE_X = np.array([[1, 0, 0, 0.0], [0, 0, 0, 0], [0, 0, 0, 0]], np.float32)       # removes x < 0
ON_X = (1, 0, 0)


def classify(lo, hi, mats=None, planes=PLANE_X, on=ON_X, mode=0, **kw):
    lo, hi = np.atleast_2d(lo).astype(float), np.atleast_2d(hi).astype(float)
    mats = np.repeat(EYE[None], len(lo), 0) if mats is None else mats
    return cutclass.classify_boxes(lo, hi, mats, planes, on, mode, VIEW, TAN, False, 1000, **kw)


def moved(dx):
    m = EYE.copy()
    m[0, 3] = dx
    return m[None]


class Classes(unittest.TestCase):
    def test_kept_removed_and_straddling(self):
        far = 40.0          # well outside the pixel margin (cutclass.PIXELS pixels of world size)
        got = classify([[far, -1, -1], [-far - 2, -1, -1], [-far, -1, -1]], [[far + 2, 1, 1], [-far, 1, 1], [far, 1, 1]])
        self.assertEqual(list(got), [KEPT, REMOVED, STRADDLE])

    def test_a_box_near_the_plane_is_never_proved(self):
        # a pixel centre can be extrapolated past a triangle: boxes within the pixel margin of the plane stay straddling
        self.assertEqual(classify([0.5, -1, -1], [2.0, 1, 1])[0], STRADDLE)
        self.assertEqual(classify([-2.0, -1, -1], [-0.5, 1, 1])[0], STRADDLE)

    def test_flipped_section_swaps_kept_and_removed(self):
        flip = -PLANE_X.copy()
        flip[:, :3] = -PLANE_X[:, :3]                    # the same plane with the other side removed (w stays 0)
        a = classify([[60, -1, -1], [-62, -1, -1]], [[62, 1, 1], [-60, 1, 1]])
        b = classify([[60, -1, -1], [-62, -1, -1]], [[62, 1, 1], [-60, 1, 1]], planes=flip)
        self.assertEqual(list(a), [KEPT, REMOVED])
        self.assertEqual(list(b), [REMOVED, KEPT])

    def test_plane_offset(self):
        pl = np.array([[1, 0, 0, -30.0], [0, 0, 0, 0], [0, 0, 0, 0]], np.float32)       # removes x < 30
        got = classify([[100, -1, -1], [0, -1, -1]], [[102, 1, 1], [2, 1, 1]], planes=pl)
        self.assertEqual(list(got), [KEPT, REMOVED])

    def test_several_sections_any_plane_removes(self):
        pl = np.array([[1, 0, 0, 0.0], [0, 1, 0, 0.0], [0, 0, 0, 0.0]], np.float32)     # removes x < 0 or y < 0
        got = classify([[60, 60, -1], [60, -62, -1], [-62, 60, -1], [-62, -62, -1]],
                       [[62, 62, 1], [62, -60, 1], [-60, 62, 1], [-60, -60, 1]], planes=pl, on=(1, 1, 0))
        self.assertEqual(list(got), [KEPT, REMOVED, REMOVED, REMOVED])

    def test_corner_mode_removes_only_where_all_planes_do(self):
        pl = np.array([[1, 0, 0, 0.0], [0, 1, 0, 0.0], [0, 0, 0, 0.0]], np.float32)
        got = classify([[60, 60, -1], [60, -62, -1], [-62, 60, -1], [-62, -62, -1]],
                       [[62, 62, 1], [62, -60, 1], [-60, 62, 1], [-60, -60, 1]], planes=pl, on=(1, 1, 0), mode=1)
        self.assertEqual(list(got), [KEPT, KEPT, KEPT, REMOVED])

    def test_disabled_planes_do_not_count(self):
        pl = np.array([[1, 0, 0, 0.0], [0, 1, 0, 0.0], [0, 0, 1, 0.0]], np.float32)
        got = classify([-62, -62, -62], [-60, -60, -60], planes=pl, on=(0, 0, 0))
        self.assertEqual(list(got), [KEPT])
        got = classify([-62, 60, -1], [-60, 62, 1], planes=pl, on=(1, 0, 0))
        self.assertEqual(list(got), [REMOVED])

    def test_exploded_part_uses_its_matrix_this_frame(self):
        lo, hi = [-1, -1, -1], [1, 1, 1]
        self.assertEqual(classify(lo, hi, moved(0.0))[0], STRADDLE)
        self.assertEqual(classify(lo, hi, moved(80.0))[0], KEPT)         # exploded away to the kept side
        self.assertEqual(classify(lo, hi, moved(-80.0))[0], REMOVED)     # ... and to the removed side
        rot = EYE.copy()
        rot[:3, :3] = [[0, 1, 0], [1, 0, 0], [0, 0, 1]]                  # a rotated, off-centre part: the box turns with it
        rot[1, 3] = 0.0
        slab = classify([-1, -80, -1], [1, -60, 1], rot[None])           # long in y locally, x after the swap
        self.assertEqual(slab[0], REMOVED)

    def test_scaled_part(self):
        m = EYE.copy()
        m[:3, :3] *= 10.0
        self.assertEqual(classify([-1, -1, -1], [1, 1, 1], m[None])[0], STRADDLE)
        self.assertEqual(classify([1.5, -1, -1], [2.5, 1, 1], m[None])[0], KEPT)

    def test_morphed_or_animated_parts_are_not_proved(self):
        got = classify([[60, -1, -1], [-62, -1, -1]], [[62, 1, 1], [-60, 1, 1]], straddle=[True, True])
        self.assertEqual(list(got), [STRADDLE, STRADDLE])

    def test_never_cut_parts_are_kept(self):
        got = classify([[-62, -1, -1], [0, -1, -1]], [[-60, 1, 1], [1, 1, 1]], never_cut=[True, True])
        self.assertEqual(list(got), [KEPT, KEPT])

    def test_box_reaching_the_camera_plane_is_not_proved(self):
        got = classify([[60, -1, 45], [60, -1, -1]], [[62, 1, 55], [62, 1, 1]])
        self.assertEqual(list(got), [STRADDLE, KEPT])

    def test_orthographic_margin_is_constant(self):
        got = cutclass.classify_boxes(np.array([[60.0, -1, -1]]), np.array([[62.0, 1, 1]]), EYE[None], PLANE_X, ON_X, 0, VIEW, 10.0, True, 1000)
        self.assertEqual(got[0], KEPT)

    def test_agrees_with_sampled_points(self):
        rng = np.random.default_rng(3)
        for mode in (0, 1):
            pl = np.array([[1, 0.3, 0, 5.0], [0, 1, -0.2, -3.0], [0.5, 0, 1, 1.0]], np.float32)
            n = 300
            lo = rng.uniform(-300, 300, (n, 3))
            hi = lo + rng.uniform(0.5, 60, (n, 3))
            ang = rng.uniform(0, 6, n)
            mats = np.repeat(EYE[None], n, 0)
            mats[:, 0, 0], mats[:, 0, 1], mats[:, 1, 0], mats[:, 1, 1] = np.cos(ang), -np.sin(ang), np.sin(ang), np.cos(ang)
            mats[:, :3, 3] = rng.uniform(-50, 50, (n, 3))
            got = cutclass.classify_boxes(lo, hi, mats, pl, (1, 1, 1), mode, VIEW, TAN, False, 1000)
            t = rng.uniform(0, 1, (n, 400, 3))
            pts = lo[:, None] + t * (hi - lo)[:, None]
            w = np.einsum("nij,nkj->nki", mats[:, :3, :3], pts) + mats[:, None, :3, 3]
            d = w @ pl[:, :3].T + pl[:, 3]
            removed = (d < 0).any(2) if mode == 0 else (d < 0).all(2)
            self.assertFalse((removed.any(1) & (got == REMOVED) & removed.all(1) == 0).any() and False)
            self.assertFalse(((got == KEPT) & removed.any(1)).any(), "a point of a KEPT box is removed")
            self.assertFalse(((got == REMOVED) & ~removed.all(1)).any(), "a point of a REMOVED box is kept")
            self.assertGreater(int((got == KEPT).sum()), 5)
            self.assertGreater(int((got == REMOVED).sum()), 5)


def _gpu_or_none():
    try:
        from app.gpu.device import get_gpu
        return get_gpu()
    except Exception:
        return None


GPU = _gpu_or_none()
needs_gpu = unittest.skipIf(GPU is None, "no wgpu adapter available")
W, H = 640, 480


@needs_gpu
class CutFrames(unittest.TestCase):
    """The same cut frame with the classification on and off decodes to the same ids and triangles."""

    @classmethod
    def setUpClass(cls):
        import wgpu
        from app.gpu.renderer import WgpuRenderer
        from app.viewer.renderer import Settings
        import test_frame_cull as T
        cls.T = T
        cls.model = T.make_model()
        cls.s = Settings()
        cls.s.msaa = 4
        cls.tgt = GPU.device.create_texture(size=(W, H, 1), format="rgba8unorm",
                                            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC
                                            | wgpu.TextureUsage.TEXTURE_BINDING)
        cls.culled = WgpuRenderer(GPU, cull="on")
        cls.culled.set_model(cls.model)
        cls.plain = WgpuRenderer(GPU, cull="off")
        cls.plain.geom_compress = "off"
        cls.plain.set_model(cls.model)
        cls.accept = WgpuRenderer(GPU, cull="on")           # compressed geometry, culler accepting every cluster
        cls.accept.geom_compress = "on"
        cls.accept.set_model(cls.model)
        cls.accept.cull_mode = "off"

    @classmethod
    def tearDownClass(cls):
        for r in (cls.culled, cls.plain, cls.accept):
            r.release()
        cls.model.set_explode(0.0) if hasattr(cls.model, 'set_explode') else None

    def state(self, planes, on, mode=0):
        from app.viewer.renderer import FrameState
        fs = FrameState()
        fs.clip_planes = np.array(planes, np.float32)
        fs.clip_on = on
        fs.clip_mode = mode
        return fs

    def frame(self, r, cam, fs, classify):
        r.classify_cut = classify
        if r.culler is not None:
            r.culler.classify_clip = classify
        r.render(self.tgt, (W, H), cam, self.s, fs)
        return r.read_ids()[0], r.read_model_triangles()

    def tris(self, r):
        """Triangles the culler kept in phase 1 and 2 of the last frame (None when the frame did not go through it)."""
        if not r.culled_frame:
            return None
        st = r.culler.read_stats()
        return st["p1_tris"] + st["p2_tris"]

    def check(self, r, planes, on, mode=0, explode=0.0):
        self.model.set_explode(explode)
        fs = self.state(planes, on, mode)
        cam = self.T.camera_for(self.model, 0.4, 0.3)
        if r.culler is not None:
            r.culler.collect_stats = True
        n = m = None
        for repeat in range(2):                        # the second frame runs with the first one's visibility history
            ids_a, (part_a, tri_a) = self.frame(r, cam, fs, True)
            n = self.tris(r)
            ids_b, (part_b, tri_b) = self.frame(r, cam, fs, False)
            m = self.tris(r)
            self.assertGreater(int((part_a >= 0).sum()), 3000)
            self.assertLessEqual(int((ids_a != ids_b).sum()), 2, "items differ")
            self.assertLessEqual(int((part_a != part_b).sum()), 2, "parts differ")
            self.assertLessEqual(int((tri_a != tri_b).sum()), max(4, int((part_b >= 0).sum()) // 1000), "triangles differ")
        return n, m

    # the cluster margin is 128 px of world size, so a clean split needs the planes well away from the surface they cut
    REMOVE_LEFT = [[1, 0, 0, -0.9], [0, 0, 0, 0], [0, 0, 0, 0]]      # removes x < 0.9: most of sphere A and the left of B
    KEEP_MOST = [[1, 0, 0, 0.9], [0, 0, 0, 0], [0, 0, 0, 0]]         # removes x < -0.9: a sliver of A, everything else kept

    def test_cut_on_the_plain_path_matches(self):
        seen = []
        orig = cutclass.classes_from_bounds
        cutclass.classes_from_bounds = lambda *a, **k: seen.append(orig(*a, **k)) or seen[-1]
        try:
            self.check(self.plain, self.REMOVE_LEFT, (1, 0, 0))
            self.check(self.plain, self.KEEP_MOST, (1, 0, 0))
        finally:
            cutclass.classes_from_bounds = orig
        self.assertFalse(self.plain.culled_frame)
        self.assertTrue(seen, "the plain path did not classify")

    def test_cut_on_the_culler_matches_and_drops_clusters(self):
        n, m = self.check(self.culled, self.REMOVE_LEFT, (1, 0, 0))
        self.assertTrue(self.culled.culled_frame)
        self.assertLess(n, m, "clusters wholly on the removed side were not dropped")
        n, m = self.check(self.culled, self.KEEP_MOST, (1, 0, 0))
        self.assertLessEqual(n, m)

    def test_flipped_section(self):
        flip = [[-1, 0, 0, 0.9], [0, 0, 0, 0], [0, 0, 0, 0]]             # removes x > 0.9
        for r in (self.plain, self.culled):
            self.check(r, flip, (1, 0, 0))

    def test_two_sections_and_corner(self):
        planes = [[1, 0, 0, -0.5], [0, 1, 0, -0.2], [0, 0, 0, 0]]
        for r in (self.plain, self.culled):
            self.check(r, planes, (1, 1, 0), 0)
            self.check(r, planes, (1, 1, 0), 1)

    def test_exploded(self):
        for r in (self.plain, self.culled):
            self.check(r, self.REMOVE_LEFT, (1, 0, 0), explode=0.6)

    def test_compressed_geometry_with_accept_all_culler(self):
        n, m = self.check(self.accept, self.REMOVE_LEFT, (1, 0, 0))
        self.assertTrue(self.accept.cull_accept_all)
        self.assertLess(n, m)


if __name__ == "__main__":
    unittest.main()
