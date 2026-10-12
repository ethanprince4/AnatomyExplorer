"""The whole-body renderer's draw lists (app/draw_ranges.py): each pass is given only the structures that can show
in it, and the picture is the same as drawing the whole buffer."""
import struct
import unittest
from types import SimpleNamespace

import numpy as np

from app.draw_ranges import DrawRanges, F_GHOST, F_NOCLIP, F_SELECTED, F_VISIBLE

MATERIALS = [{"color": [0.8, 0.3, 0.2], "distinct": [0.2, 0.6, 0.9], "alpha": 1.0, "category": "other"},
             {"color": [0.3, 0.7, 0.4], "distinct": [0.9, 0.8, 0.1], "alpha": 0.4, "category": "other"},
             {"color": [0.9, 0.9, 0.8], "distinct": [0.5, 0.1, 0.7], "alpha": 1.0, "category": "other"}]


def quad(center, half, sid, mats=(0, 0)):
    """Two triangles facing +Z; the second may carry another material (a muscle and its tendon)."""
    cx, cy, cz = center
    corners = [(-1, -1), (1, -1), (1, 1), (-1, -1), (1, 1), (-1, 1)]
    out = []
    for k, (dx, dy) in enumerate(corners):
        out.append(struct.pack("<3f3f2H", cx + dx * half, cy + dy * half, cz, 0.0, 0.0, 1.0, sid, mats[k // 3]))
    return out


def scene():
    """Eight structures: in view, off to each side, behind the eye, see-through, mixed, and two on the same plane."""
    spec = [((0.0, 0.0, 0.0), 0.5, (0, 0)),        # 0 centre
            ((0.2, 0.1, 0.0), 0.5, (2, 2)),        # 1 same plane as 0: the first drawn wins the tie
            ((9.0, 0.0, 0.0), 0.5, (0, 0)),        # 2 far to the right, outside the view
            ((0.0, 0.0, 9.0), 0.5, (0, 0)),        # 3 behind the eye
            ((-0.4, 0.3, 0.5), 0.4, (1, 1)),       # 4 see-through, in front
            ((0.5, -0.4, 0.3), 0.3, (0, 2)),       # 5 two opaque materials
            ((-0.6, -0.5, 0.2), 0.3, (0, 0)),      # 6
            ((0.0, -9.0, 0.0), 0.5, (0, 0))]       # 7 far below
    verts, structures = [], []
    for sid, (c, h, mats) in enumerate(spec):
        structures.append({"id": sid, "i_start": 6 * sid, "i_count": 6, "material": mats[0]})
        verts += quad(c, h, sid, mats)
    vertices = b"".join(verts)
    indices = np.arange(6 * len(spec), dtype="<u4").tobytes()
    return structures, vertices, indices


def view_projection(eye=(0.0, 0.0, 3.0), fov=45.0, aspect=1.0, near=0.1, far=50.0):
    f = 1.0 / np.tan(np.radians(fov) / 2)
    proj = np.array([[f / aspect, 0, 0, 0], [0, f, 0, 0],
                     [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)], [0, 0, -1, 0]])
    view = np.identity(4)
    view[:3, 3] = -np.asarray(eye)
    return view, proj


class Layout(unittest.TestCase):
    def setUp(self):
        self.structures, self.vertices, self.indices = scene()
        self.r = DrawRanges.build(self.structures, MATERIALS, self.vertices, self.indices)

    def test_ranges_boxes_and_alphas_come_from_the_buffers(self):
        r = self.r
        self.assertIsNotNone(r)
        self.assertEqual(r.triangles, 16)
        np.testing.assert_allclose(r.box_min[0], [-0.5, -0.5, 0.0])
        np.testing.assert_allclose(r.box_max[2], [9.5, 0.5, 0.0])
        self.assertEqual((float(r.alpha_min[4]), float(r.alpha_max[4])), (np.float32(0.4), np.float32(0.4)))
        self.assertEqual((float(r.alpha_min[5]), float(r.alpha_max[5])), (1.0, 1.0))

    def test_layouts_that_cannot_be_proved_are_refused(self):
        s = [dict(x) for x in self.structures]
        s[3]["i_start"] = 12                                   # overlaps structure 2 and leaves a gap
        self.assertIsNone(DrawRanges.build(s, MATERIALS, self.vertices, self.indices))
        same = [{"i_start": 0, "i_count": 3} for _ in range(8)]   # the picking diagnostics' synthetic dataset
        self.assertIsNone(DrawRanges.build(same, MATERIALS, self.vertices[:84], struct.pack("<3I", 0, 1, 2)))
        idx = np.frombuffer(self.indices, dtype="<u4").copy()
        idx[7] = 40                                            # structure 1 borrows a vertex of structure 6
        self.assertIsNone(DrawRanges.build(self.structures, MATERIALS, self.vertices, idx.tobytes()))
        v = bytearray(self.vertices)
        v[28 * 9 + 24:28 * 9 + 26] = struct.pack("<H", 6)      # a vertex of structure 1 tagged as structure 6
        self.assertIsNone(DrawRanges.build(self.structures, MATERIALS, bytes(v), self.indices))
        self.assertIsNone(DrawRanges.build(self.structures[:7], MATERIALS, self.vertices, self.indices))
        self.assertIsNone(DrawRanges.build([], MATERIALS, b"", b""))

    def test_each_pass_gets_only_what_can_show_in_it(self):
        r = self.r
        flags = np.full(8, F_VISIBLE, dtype=np.int32)
        flags[6] = 0                                           # hidden
        flags[5] |= F_SELECTED
        flags[0] |= F_GHOST
        opaque, transparent, mask = r.passes(flags, np.ones(8, np.float32), 0.1)
        self.assertEqual(opaque.tolist(), [False, True, True, True, False, True, False, True])
        self.assertEqual(transparent.tolist(), [True, False, False, False, True, False, False, False])
        self.assertEqual(mask.tolist(), [False] * 5 + [True, False, False])
        self.assertFalse((opaque & transparent).any())         # no triangle is sent twice
        opacity = np.ones(8, np.float32)
        opacity[1], opacity[2] = 0.5, 0.995                    # a faded system; one exactly on the limit
        opaque, transparent, _ = r.passes(flags, opacity, 0.1)
        self.assertEqual((bool(opaque[1]), bool(transparent[1])), (False, True))
        self.assertEqual((bool(opaque[2]), bool(transparent[2])), (True, True))   # the shader decides

    def test_view_test_never_drops_a_structure_with_a_vertex_in_view(self):
        rng = np.random.default_rng(3)
        n = 400
        lo = rng.uniform(-6, 6, (n, 3))
        size = rng.uniform(0.01, 3.0, (n, 3))
        r = DrawRanges()
        r.n, r.box_min, r.box_max = n, lo, lo + size
        r._finish_boxes(np.ones(n, dtype=bool))
        dropped = kept = 0
        for eye in ((0, 0, 3), (4, 1, 8), (0, 0, 0.2), (-7, 2, -1)):
            view, proj = view_projection(eye, aspect=1.6)
            vp = np.asarray(proj @ view, dtype=np.float32).astype(np.float64)
            out = r.outside_view(vp)
            pts = lo[:, None, :] + size[:, None, :] * rng.uniform(0, 1, (n, 200, 3))
            clip = np.concatenate([pts, np.ones((n, 200, 1))], axis=2) @ vp.T
            inside = (np.abs(clip[:, :, :3]) <= clip[:, :, 3:]).all(axis=2).any(axis=1)
            self.assertFalse((out & inside).any())
            dropped += int(out.sum())
            kept += int((~out).sum())
        self.assertGreater(dropped, 100)
        self.assertGreater(kept, 100)

    def test_sections_drop_only_what_they_remove_completely(self):
        r = self.r
        flags = np.full(8, F_VISIBLE, dtype=np.int32)
        planes = [(1.0, 0.0, 0.0, -1.0), (0.0, 1.0, 0.0, 2.0), (0.0, 0.0, 1.0, 0.0)]     # keeps x > 1, y > -2
        gone = r.cut_away((planes, [True, False, False], 0), flags)
        self.assertEqual(gone.tolist(), [True, True, False, True, True, True, True, True])
        gone = r.cut_away((planes, [True, True, False], 1), flags)                    # corner cut: both must hold
        self.assertEqual(gone.tolist(), [False] * 7 + [True])
        flags[7] |= F_NOCLIP
        self.assertFalse(r.cut_away((planes, [True, True, False], 1), flags).any())
        self.assertFalse(r.cut_away((planes, [False, False, False], 0), flags).any())
        on_plane = r.cut_away(([(0.0, 0.0, 1.0, 0.0)] * 3, [True, False, False], 0), flags)
        self.assertFalse(on_plane[0])                          # a structure on the plane is left to the shader

    def test_draws_join_neighbours_and_keep_buffer_order(self):
        r = self.r
        mask = np.array([True, True, False, True, False, False, True, True])
        first, count = r.runs(mask)
        self.assertEqual((first.tolist(), count.tolist()), ([0, 18, 36], [12, 6, 12]))
        f2, c2 = r.bridge(first, count, 2)
        self.assertEqual((f2.tolist(), c2.tolist()), ([0, 36], [24, 12]))       # the smaller gap is drawn through
        self.assertEqual(r.bridge(first, count, 1)[1].tolist(), [48])
        self.assertEqual(r.runs(np.zeros(8, dtype=bool))[0].tolist(), [])
        cmd = r.commands(first, count)
        self.assertEqual(cmd.tolist(), [[12, 1, 0, 0, 0], [6, 1, 18, 0, 0], [12, 1, 36, 0, 0]])
        self.assertEqual(cmd.dtype.itemsize * cmd.shape[1], 20)


class SamePicture(unittest.TestCase):
    """Lists against whole-buffer drawing on a real OpenGL context: every buffer must match byte for byte."""

    @classmethod
    def setUpClass(cls):
        try:
            import moderngl
            cls.ctx = moderngl.create_standalone_context(require=410)
        except Exception as error:                              # noqa: BLE001 - no OpenGL 4.1 on this machine
            raise unittest.SkipTest(f"no OpenGL context: {error}")
        from app.renderer import Renderer
        structures, vertices, indices = scene()
        ds = SimpleNamespace(n=len(structures), structures=structures, materials=MATERIALS)
        cls.renderer = Renderer(cls.ctx, ds, vertices, indices)
        cls.renderer.resize(96, 96)
        cls.target = cls.ctx.framebuffer([cls.ctx.texture((96, 96), 4)])

    @classmethod
    def tearDownClass(cls):
        cls.renderer.release()
        cls.ctx.release()

    def frame(self, flags, clip, eye, has_selection):
        from app.config import DEFAULT_SETTINGS
        from app.state import STATE_TEX_WIDTH
        r = self.renderer
        state = np.zeros((2, STATE_TEX_WIDTH, 4), np.float32)
        state[0, :8, 3] = flags
        state[1, :8, 0] = 1.0
        r.update_state(state)
        view, proj = view_projection(eye)
        camera = SimpleNamespace(view=lambda: view, proj=lambda aspect: proj, eye=lambda: np.array(eye, dtype=float),
                                 distance=3.0, basis=lambda: tuple(np.array(v, dtype=float)
                                                                   for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))))
        r.render(self.target, camera, dict(DEFAULT_SETTINGS), clip, hover_id=1, has_selection=has_selection)
        self.assertTrue(r.frame_ok)
        self.assertEqual(self.ctx.error, "GL_NO_ERROR")
        return (self.target.read(components=4), r.color_tex.read(), r.id_tex.read(), r.depth_tex.read(),
                r.mask_tex.read(), r.ldr_tex.read()), dict(r.last_stats)

    def test_lists_draw_the_same_picture_with_fewer_triangles(self):
        r = self.renderer
        self.assertTrue(r.wait_ranges(10))
        no_clip = ([(1.0, 0, 0, 0), (0, 0, 1.0, 0), (0, 1.0, 0, 0)], [False, False, False], 0)
        cut = ([(1.0, 0, 0, -0.1), (0, 0, 1.0, 0), (0, 1.0, 0, 0.2)], [True, False, True], 0)
        corner = (cut[0], [True, False, True], 1)
        all_on = [F_VISIBLE] * 8
        mixed = [F_VISIBLE | F_GHOST, F_VISIBLE, F_VISIBLE, F_VISIBLE, F_VISIBLE, F_VISIBLE | F_SELECTED, 0, F_VISIBLE]
        cases = [(all_on, no_clip, (0.0, 0.0, 3.0), False), (mixed, no_clip, (0.0, 0.0, 3.0), True),
                 (mixed, cut, (0.3, 0.2, 2.5), True), (all_on, corner, (0.0, 0.0, 3.0), False),
                 (mixed, no_clip, (8.5, 0.0, 2.0), True), (all_on, no_clip, (0.0, 0.0, 12.0), False)]
        indirect = r._indirect
        try:
            for flags, clip, eye, selected in cases:
                r.use_ranges, r._indirect = False, indirect
                whole, whole_stats = self.frame(flags, clip, eye, selected)
                self.assertEqual(whole_stats["opaque"], (16, 1))
                modes = [(indirect, r.LOOP_DRAWS), (False, r.LOOP_DRAWS), (False, 2)]
                for use_indirect, limit in modes:
                    r.use_ranges, r._indirect, r.LOOP_DRAWS = True, use_indirect, limit
                    r._lists_key = None
                    listed, stats = self.frame(flags, clip, eye, selected)
                    for a, b in zip(whole, listed):
                        self.assertEqual(a, b)
                    self.assertLess(stats["opaque"][0] + stats["transparent"][0], 16)
                    if selected:
                        self.assertLessEqual(stats["mask"][0], 2)
            self.assertGreater(np.frombuffer(whole[2], dtype=np.float32).max(), 0)     # something was drawn
        finally:
            r.use_ranges, r._indirect, r.LOOP_DRAWS = True, indirect, type(r).LOOP_DRAWS

    def test_an_unproved_layout_draws_the_whole_buffer(self):
        from app.renderer import Renderer
        structures, vertices, indices = scene()
        overlapping = [{"i_start": 0, "i_count": 6} for _ in structures]
        ds = SimpleNamespace(n=len(structures), structures=overlapping, materials=MATERIALS)
        r = Renderer(self.ctx, ds, vertices, indices)
        try:
            self.assertFalse(r.wait_ranges(10))
            self.assertIsNone(r._frame_lists(np.identity(4), ([(0, 0, 0, 0)] * 3, [False] * 3, 0), {}))
        finally:
            r.release()


if __name__ == "__main__":
    unittest.main()
