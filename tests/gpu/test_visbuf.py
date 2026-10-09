"""Visibility-buffer renderer on a tiny scene (two boxes): id encoding and draw-slot splitting, picks, selection flag,
clip discard, odd sizes, and several page groups. Everything that needs a GPU skips without a wgpu adapter.

    python -m pytest tests/gpu/test_visbuf.py -q -p no:cacheprovider
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402


def _gpu_or_none():
    try:
        from app.gpu.device import get_gpu
        return get_gpu()
    except Exception:
        return None


GPU = _gpu_or_none()
needs_gpu = unittest.skipIf(GPU is None, "no wgpu adapter available")
W, H = 128, 96


def fixture_model():
    from general_fixtures import write_fixture_model
    from app.viewer.model import Model
    d = Path(tempfile.mkdtemp())
    write_fixture_model(d / "m.glb")
    m = Model(d / "m.glb")
    m.evaluate(m.clip_range[0], None, 0.0)
    return m


def camera_for(model):
    from app.viewer.camera import OrbitCamera
    cam = OrbitCamera()
    cam.set_scene(model.bounds_min, model.bounds_max)
    cam.target = cam.scene_centre.copy()
    cam.distance = cam.fit_distance(cam.scene_radius, W / H)
    cam.yaw, cam.pitch = 0.4, 0.3
    cam.snap()
    return cam


def target(size=(W, H)):
    import wgpu
    return GPU.device.create_texture(size=(size[0], size[1], 1), format="rgba8unorm",
                                     usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC
                                     | wgpu.TextureUsage.TEXTURE_BINDING)


def pixel_of(r, point, size=(W, H)):
    """Render pixel (x, y from the top-left) of a world point under the last frame's camera."""
    q = r.last_vp @ np.array([*point, 1.0])
    ndc = q[:3] / q[3]
    return int((ndc[0] * 0.5 + 0.5) * size[0]), int((0.5 - ndc[1] * 0.5) * size[1])


class IdEncoding(unittest.TestCase):
    def test_slot_and_primitive_fit_the_32_bit_id(self):
        for bits in (20, 12, 8):
            slot, prim = (1 << (32 - bits)) - 1, (1 << bits) - 1
            tid = (slot << bits) | prim
            self.assertLess(tid, 1 << 32)
            self.assertEqual(tid >> bits, slot)
            self.assertEqual(tid & ((1 << bits) - 1), prim)
            self.assertNotEqual((1 << bits) | 0, 0)         # slot 1, primitive 0 is not the background id 0


@needs_gpu
class TinyScene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.gpu.renderer import WgpuRenderer
        from app.viewer.renderer import Settings
        cls.model = fixture_model()
        cls.cam = camera_for(cls.model)
        cls.s = Settings()
        cls.s.msaa = 4
        cls.r = WgpuRenderer(GPU)
        cls.r.set_model(cls.model)
        cls.tgt = target()

    @classmethod
    def tearDownClass(cls):
        cls.r.release()

    def render(self, r=None, fs=None, size=(W, H), tgt=None):
        r = r or self.r
        tgt = tgt or (self.tgt if size == (W, H) else target(size))
        r.render(tgt, size, self.cam, self.s, fs)
        return r

    def centres(self, r, size=(W, H)):
        m = self.model
        out = []
        for it in m.items:
            lo, hi = m.item_bounds([it.index])
            out.append(pixel_of(r, (np.asarray(lo) + np.asarray(hi)) / 2, size))
        return out

    def test_pick_finds_each_box_and_the_background(self):
        r = self.render()
        (x0, y0), (x1, y1) = self.centres(r)
        i0, p0, cap0 = r.pick(x0, y0)
        i1, p1, _ = r.pick(x1, y1)
        self.assertEqual((i0, i1), (0, 1))
        self.assertFalse(cap0)
        lo, hi = self.model.item_bounds([0])
        self.assertTrue(np.all(p0 >= np.asarray(lo) - 1e-3) and np.all(p0 <= np.asarray(hi) + 1e-3))
        self.assertEqual(r.pick(0, 0)[0], -1)
        self.assertEqual(r.pick(-3, 5)[0], -1)
        self.assertEqual(r.ids_at([(x0, y0), (x1, y1), (0, 0), (W + 4, 1)]), [0, 1, -1, -1])

    def test_readbacks_agree_with_each_other(self):
        r = self.render()
        ids, flags = r.read_ids()
        depth = r.read_depth()
        self.assertEqual(ids.shape, (H, W))
        self.assertEqual(depth.shape, (H, W))
        self.assertTrue(np.array_equal(depth > 0, ids >= 0))
        self.assertGreater(int((ids == 0).sum()), 50)
        self.assertGreater(int((ids == 1).sum()), 20)
        self.assertEqual(set(np.unique(ids)), {-1, 0, 1})
        near, far = self.cam.near_far()
        self.assertTrue(np.all(depth[ids >= 0] > near * 0.5) and np.all(depth[ids >= 0] < far))
        step = 8
        gi, gf, gd, gc = r.read_label_samples(step)
        self.assertEqual(gi.shape, (-(-H // step), -(-W // step)))
        self.assertTrue(np.array_equal(gi, ids[::step, ::step]))
        cy = np.minimum(np.arange(gi.shape[0]) * step + step // 2, H - 1)
        cx = np.minimum(np.arange(gi.shape[1]) * step + step // 2, W - 1)
        self.assertTrue(np.array_equal(gd, depth[np.ix_(cy, cx)]))
        self.assertTrue(np.array_equal(gc, ids[np.ix_(cy, cx)]))
        (x0, y0), _ = self.centres(r)
        d = float(depth[y0, x0])
        w = r.world_from_pixel(x0, y0, d)
        V = r.last_camera[0]
        self.assertAlmostEqual(float(-(V @ np.append(w, 1.0))[2]), d, places=3)

    def test_selected_flag(self):
        from app.viewer.renderer import FrameState
        r = self.render(fs=FrameState(selected=frozenset({1})))
        ids, flags = r.read_ids()
        self.assertTrue(np.all((flags[ids == 1] & 1) == 1))
        self.assertTrue(np.all((flags[ids == 0] & 1) == 0))
        self.assertTrue(np.all((flags & 2) == 0))

    def test_hidden_item_is_not_drawn(self):
        from app.viewer.renderer import FrameState
        r = self.render(fs=FrameState(visible=np.array([True, False])))
        ids, _ = r.read_ids()
        self.assertEqual(set(np.unique(ids)), {-1, 0})

    def test_clip_plane_discards_like_gl(self):
        from app.viewer.renderer import FrameState
        # dot(world, plane) < 0 is removed: x < 0.35 goes, so the big block (x <= 0.25) is gone and the small one stays
        fs = FrameState(clip_planes=((1.0, 0.0, 0.0, -0.35), (0.0, 1.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0)),
                        clip_on=(True, False, False), clip_mode=0)
        r = self.render(fs=fs)
        ids, _ = r.read_ids()
        self.assertEqual(set(np.unique(ids)), {-1, 1})
        # an item that is never cut ignores the plane
        self.model.items[0].clip = False
        try:
            ids = self.render(fs=fs).read_ids()[0]
            self.assertEqual(set(np.unique(ids)), {-1, 0, 1})
        finally:
            self.model.items[0].clip = True

    def test_odd_sizes(self):
        size = (101, 67)
        tgt = target(size)
        r = self.render(size=size, tgt=tgt)
        ids, flags = r.read_ids()
        self.assertEqual(ids.shape, (67, 101))
        self.assertEqual(r.read_depth().shape, (67, 101))
        self.assertEqual(r.read_final(tgt, size).shape, (67, 101, 3))
        (x0, y0), (x1, y1) = self.centres(r, size)
        self.assertEqual(r.ids_at([(x0, y0), (x1, y1)]), [0, 1])
        self.assertEqual(r.read_label_samples(16)[0].shape, (5, 7))

    def test_final_image_has_the_boxes_in_it(self):
        r = self.render()
        img = r.read_final(self.tgt, (W, H))
        ids, _ = r.read_ids()
        self.assertEqual(img.shape, (H, W, 3))
        self.assertTrue(np.any(img[ids == 0] != img[0, 0]))

    def test_split_draws_give_the_same_picture(self):
        from app.gpu.renderer import WgpuRenderer
        ref = self.render()
        ref_ids, ref_depth = ref.read_ids()[0], ref.read_depth()
        r = WgpuRenderer(GPU, prim_bits=3)               # 8 triangles per slot: both boxes (12 triangles) split in two
        try:
            r.set_model(self.model)
            r.render(self.tgt, (W, H), self.cam, self.s, None)
            self.assertEqual(len(r.last_draws), 4)
            self.assertEqual([e[0] for e in r.last_draws], [1, 2, 3, 4])
            self.assertEqual(r.last_prim_bits, 3)
            tri = r.read_triangles()
            self.assertTrue(np.all((tri >> 3) <= 4))
            self.assertTrue(np.array_equal(r.read_ids()[0], ref_ids))
            self.assertTrue(np.allclose(r.read_depth(), ref_depth, rtol=1e-5, atol=1e-5))
        finally:
            r.release()

    def test_several_pages_and_page_groups(self):
        from app.gpu.renderer import WgpuRenderer
        ref_ids = self.render().read_ids()[0]
        r = WgpuRenderer(GPU, page_bytes=160, resolve_group_pages=1)
        try:
            r.set_model(self.model)
            self.assertEqual(len(r.geom.pages), 2)
            self.assertEqual(len(r._groups), 2)
            r.render(self.tgt, (W, H), self.cam, self.s, None)
            self.assertTrue(np.array_equal(r.read_ids()[0], ref_ids))
            (x0, y0), (x1, y1) = self.centres(r)
            self.assertEqual((r.pick(x0, y0)[0], r.pick(x1, y1)[0]), (0, 1))
        finally:
            r.release()

    def test_single_sample_matches_the_msaa_picture_closely(self):
        from app.gpu.renderer import WgpuRenderer
        from app.viewer.renderer import Settings
        s1 = Settings()
        s1.msaa = 1
        r = WgpuRenderer(GPU)
        try:
            r.set_model(self.model)
            r.render(self.tgt, (W, H), self.cam, s1, None)
            self.assertEqual(r.samples, 1)
            ids = r.read_ids()[0]
            msaa_ids = self.render().read_ids()[0]
            self.assertGreater(float((ids == msaa_ids).mean()), 0.97)
        finally:
            r.release()

    def test_nothing_drawn_is_background(self):
        from app.viewer.renderer import FrameState
        r = self.render(fs=FrameState(visible=np.array([False, False])))
        ids, _ = r.read_ids()
        self.assertTrue(np.all(ids == -1))
        self.assertTrue(np.all(r.read_depth() == 0.0))
        self.assertEqual(r.pick(W // 2, H // 2)[0], -1)


if __name__ == "__main__":
    unittest.main()
