"""The whole-body renderer's draw lists (app/draw_ranges.py): each pass is given only the structures that can show
in it, and the picture is the same as drawing the whole buffer."""
import logging
import struct
import unittest
from types import SimpleNamespace

import numpy as np

from app.draw_ranges import Chunks, DrawRanges, F_GHOST, F_NOCLIP, F_SELECTED, F_VISIBLE

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
        indirect, r.use_occlusion = r._indirect, False
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
            r.use_occlusion = True

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


def wall_scene():
    """A wall with things behind it, beside it, on it and a see-through sheet in front of it."""
    spec = [((0.0, 0.0, 0.5), 0.6, (0, 0)),        # 0 the wall
            ((0.0, 0.0, 0.0), 0.2, (2, 2)),        # 1 behind the wall: covered from the front
            ((0.7, 0.0, 0.0), 0.3, (0, 0)),        # 2 behind and beside it: partly in sight
            ((0.0, 0.0, 1.0), 0.8, (1, 1)),        # 3 see-through, in front of everything
            ((-0.2, 0.2, -0.5), 0.1, (2, 2)),      # 4 far behind the wall: covered
            ((0.3, 0.3, 0.5), 0.2, (2, 2))]        # 5 on the wall's own plane: the wall is drawn first and wins
    verts, structures = [], []
    for sid, (c, h, mats) in enumerate(spec):
        structures.append({"id": sid, "i_start": 6 * sid, "i_count": 6, "material": mats[0]})
        verts += quad(c, h, sid, mats)
    return structures, b"".join(verts), np.arange(6 * len(spec), dtype="<u4").tobytes()


class Pieces(unittest.TestCase):
    def setUp(self):
        self.structures, self.vertices, self.indices = wall_scene()
        self.ranges = DrawRanges.build(self.structures, MATERIALS, self.vertices, self.indices)
        self.pieces = Chunks.build(self.ranges, self.vertices, self.indices, size=1)

    def test_pieces_tile_the_buffer_in_order_with_boxes_of_their_own_triangles(self):
        p = self.pieces
        self.assertEqual(p.n, 12)
        self.assertEqual(p.first.tolist(), list(range(0, 36, 3)))
        self.assertEqual(p.end.tolist(), list(range(3, 39, 3)))
        self.assertEqual(p.struct.tolist(), [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5])
        pos = np.frombuffer(self.vertices, dtype=np.uint8).reshape(-1, 28)[:, :12].copy().view("<f4")
        for k in range(p.n):
            tri = pos[3 * k:3 * k + 3].astype(np.float64)
            np.testing.assert_allclose(p.center[k] - p.half[k], tri.min(axis=0))
            np.testing.assert_allclose(p.center[k] + p.half[k], tri.max(axis=0))
        uneven = Chunks.build(self.ranges, self.vertices, self.indices, size=4)       # 2 triangles a structure
        self.assertEqual(uneven.count.tolist(), [6] * 6)
        self.assertIsNone(Chunks.build(None, self.vertices, self.indices))
        self.assertIsNone(Chunks.build(self.ranges, self.vertices, self.indices[:-12]))

    def test_draws_join_neighbouring_pieces(self):
        mask = np.zeros(12, dtype=bool)
        mask[[0, 1, 2, 7, 11]] = True
        first, count = self.pieces.runs(mask)
        self.assertEqual(list(zip(first.tolist(), count.tolist())), [(0, 9), (21, 3), (33, 3)])
        self.assertEqual(len(self.pieces.runs(np.zeros(12, dtype=bool))[0]), 0)

    def test_view_and_section_tests_work_piece_by_piece(self):
        p = self.pieces
        view, proj = view_projection((0.0, 0.0, 3.0))
        self.assertFalse(p.outside_view(proj @ view).any())
        view, proj = view_projection((5.0, 0.0, 3.0))                 # everything is off to the left now
        self.assertTrue(p.outside_view(proj @ view).all())
        for eye in ((0.0, 0.0, 3.0), (0.9, 0.2, 1.2), (1.6, 0.0, 3.0), (5.0, 0.0, 3.0), (0.0, 0.0, 0.7)):
            view, proj = view_projection(eye)
            inside = self.ranges.inside_view(proj @ view)       # skipping whole structures changes no answer
            self.assertFalse((inside & self.ranges.outside_view(proj @ view)).any())
            self.assertEqual(p.outside_view(proj @ view, ~inside).tolist(), p.outside_view(proj @ view).tolist())
        view, proj = view_projection((0.0, 0.0, 3.0))
        self.assertTrue(self.ranges.inside_view(proj @ view).any())
        flags = np.full(6, F_VISIBLE)
        flags[4] |= F_NOCLIP
        gone = p.cut_away(([(1.0, 0, 0, -0.45), (0, 0, 0, 0), (0, 0, 0, 0)], [True, False, False], 0), flags)
        # x < 0.45 is removed: structures 1 and 4 lie wholly there (4 may not be cut), 2 and the wall do not
        self.assertEqual(gone.tolist(), [False, False, True, True, False, False, False, False, False, False,
                                         False, False])

    def test_a_box_that_reaches_the_near_side_is_never_left_to_the_test(self):
        p = self.pieces
        view, proj = view_projection((0.0, 0.0, 1.05), near=0.1)       # the see-through sheet is 0.05 away
        near = p.at_near(proj @ view, 0.01)
        self.assertEqual(near.tolist(), [False] * 6 + [True, True] + [False] * 4)
        pad_near = p.padding(proj @ view, 0.01)
        self.assertGreater(pad_near[8], pad_near[0])                    # farther from the eye: grown by more
        self.assertTrue((pad_near > 0).all())
        p.box_ok[0] = False                                             # no usable box: always drawn
        self.assertTrue(p.at_near(proj @ view, 0.01)[0])


class Covered(unittest.TestCase):
    """The covered test on a real OpenGL 4.3 context: every frame, the first after a change included, must match
    the frame drawn without it byte for byte, in every buffer."""

    @classmethod
    def setUpClass(cls):
        try:
            import moderngl
            cls.ctx = moderngl.create_standalone_context(require=430)
        except Exception as error:                              # noqa: BLE001 - no OpenGL 4.3 on this machine
            raise unittest.SkipTest(f"no OpenGL 4.3 context: {error}")
        from app.renderer import Renderer

        class OneTrianglePieces(Renderer):
            CHUNK_TRIANGLES = 1
            OCC_OVERHEAD_TRIANGLES = -10 ** 9                   # the test always pays here
            OCC_LOOSE_TRIANGLES = 10 ** 9                       # and no second test in a frame, unless asked
            OCC_MIN_TRIANGLES = 0                               # however short the list

        structures, vertices, indices = wall_scene()
        ds = SimpleNamespace(n=len(structures), structures=structures, materials=MATERIALS)
        cls.renderer = OneTrianglePieces(cls.ctx, ds, vertices, indices)
        cls.renderer.resize(96, 96)
        cls.target = cls.ctx.framebuffer([cls.ctx.texture((96, 96), 4)])

    @classmethod
    def tearDownClass(cls):
        cls.renderer.release()
        cls.ctx.release()

    NO_CLIP = ([(1.0, 0, 0, 0), (0, 0, 1.0, 0), (0, 1.0, 0, 0)], [False, False, False], 0)
    FRONT, SIDE = (0.0, 0.0, 3.0), (3.5, 0.0, 3.0)

    def draw(self, flags, clip, eye, opacity=None, selected=False):
        from app.config import DEFAULT_SETTINGS
        from app.state import STATE_TEX_WIDTH
        r = self.renderer
        state = np.zeros((2, STATE_TEX_WIDTH, 4), np.float32)
        state[0, :6, 3] = flags
        state[1, :6, 0] = 1.0 if opacity is None else opacity
        r.update_state(state)
        proj = view_projection(eye)[1]
        e = np.array(eye, dtype=float)                          # the camera looks at the middle of the scene
        back = e / np.linalg.norm(e)
        right = np.cross((0.0, 1.0, 0.0), back)
        right /= np.linalg.norm(right)
        up = np.cross(back, right)
        view = np.identity(4)
        view[:3, :3] = (right, up, back)
        view[:3, 3] = -view[:3, :3] @ e
        camera = SimpleNamespace(view=lambda: view, proj=lambda aspect: proj, eye=lambda: e.copy(),
                                 distance=float(np.linalg.norm(e)), basis=lambda: (right, up, back))
        r.render(self.target, camera, dict(DEFAULT_SETTINGS), clip, hover_id=2, has_selection=selected)
        self.assertTrue(r.frame_ok)
        self.assertEqual(self.ctx.error, "GL_NO_ERROR")
        return (self.target.read(components=4), r.color_tex.read(), r.id_tex.read(), r.depth_tex.read(),
                r.mask_tex.read(), r.ldr_tex.read()), dict(r.last_stats)

    def same(self, flags, clip=None, eye=None, **state):
        """One frame without the test and one with it, same state: equal buffers. Returns the stats with it."""
        r = self.renderer
        clip, eye = clip or self.NO_CLIP, eye or self.FRONT
        r.use_occlusion = False
        plain, plain_stats = self.draw(flags, clip, eye, **state)
        self.assertNotIn("covered", plain_stats)
        r.use_occlusion = True
        tested, stats = self.draw(flags, clip, eye, **state)
        for name, a, b in zip(("window", "colour", "id", "depth", "mask", "outline"), plain, tested):
            self.assertEqual(a, b, name)
        return stats

    def shown(self):
        """Structures with a pixel in the id buffer of the last frame."""
        ids = np.frombuffer(self.renderer.id_tex.read(), dtype=np.float32)
        return sorted({int(x) - 1 for x in np.unique(ids) if x > 0})

    def setUp(self):
        r = self.renderer
        self.assertTrue(r.wait_ranges(10))
        self.assertEqual(r.chunks.n, 12)
        r._occ_seen = r._occ_need = r._occ_key = r._occ_hint = None
        r._occ_final = False

    def test_what_the_wall_covers_is_not_sent_and_the_picture_is_the_same(self):
        r, on = self.renderer, [F_VISIBLE] * 6
        first = self.same(on)                                   # nothing known yet: all pieces pass
        self.assertEqual(first["covered"][1:3], (0, 10))        # 10 opaque triangles, none in the first draw
        second = self.same(on)                                  # starts from that answer: final
        self.assertEqual(second["covered"][1:3], (10, 6))       # wall, the one beside it, the one on it
        self.assertTrue(r._occ_final)
        third = self.same(on)                                   # drawn from the answer, no test
        self.assertEqual(third["covered"][1:3], (0, 6))
        self.assertEqual(third["opaque"], (6, 3))               # three runs of two triangles
        self.assertEqual(self.shown(), [0, 2])                  # 5 loses the tie with the wall, as without the test
        self.assertEqual(r._occ_need.tolist(), [True, True, False, False, True, True, False, False, False, False,
                                                True, True])
        # selection and hover change no surface: the answer stays, and the pictures still match
        chosen = self.same([F_VISIBLE, F_VISIBLE | F_SELECTED] + [F_VISIBLE] * 4, selected=True)
        self.assertEqual(chosen["covered"][1:3], (0, 6))

    def test_a_first_draw_with_holes_is_followed_by_a_test_against_the_frames_own_depth(self):
        r, on = self.renderer, [F_VISIBLE] * 6
        r.OCC_LOOSE_TRIANGLES = 0
        try:
            first = self.same(on)                               # all 10 pass the empty depth and are drawn
            self.assertEqual(first["covered"][1:3], (0, 10))
            self.assertTrue(r._occ_final)                       # the second test made the answer final at once
            self.assertEqual(first["covered"][4], 6)
            self.assertEqual(self.same(on)["covered"][1:3], (0, 6))
            self.same(on, eye=self.SIDE)                        # a jump: the first frame counts
            self.assertIn(1, self.shown())
            self.same([0] + [F_VISIBLE] * 5)                    # the wall switched off
            self.assertEqual(self.shown(), [1, 2, 4, 5])
        finally:
            del r.OCC_LOOSE_TRIANGLES

    def test_nothing_is_a_frame_late(self):
        on = [F_VISIBLE] * 6
        for _ in range(3):
            self.same(on)
        self.assertEqual(self.shown(), [0, 2])
        for eye in (self.SIDE, self.FRONT, (-3.5, 0.5, 2.0), self.SIDE):      # jumps: the first frame counts
            stats = self.same(on, eye=eye)
            self.assertIn("covered", stats)
        self.same(on, eye=self.SIDE)
        self.assertIn(1, self.shown())                          # from the side, 1 is in sight past the wall
        for _ in range(3):
            self.same(on)
        hidden_wall = [0] + [F_VISIBLE] * 5                     # the wall switched off: 1, 4 and 5 appear at once
        self.same(hidden_wall)
        self.assertEqual(self.shown(), [1, 2, 4, 5])
        self.same(on)                                           # and on again
        self.assertEqual(self.shown(), [0, 2])

    def test_see_through_ghosted_and_cut_structures_hide_only_what_they_really_hide(self):
        on = [F_VISIBLE] * 6
        for _ in range(3):
            self.same(on)
        opacity = np.ones(6, dtype=np.float32)
        opacity[0] = 0.5                                        # the wall made see-through
        for _ in range(3):
            self.same(on, opacity=opacity)
            self.assertEqual(self.shown(), [1, 2, 4, 5])
            self.assertTrue(self.renderer._occ_need[[2, 3, 8, 9]].all())
        for _ in range(3):
            self.same(on)
        for _ in range(3):                                      # the wall ghosted
            self.same([F_VISIBLE | F_GHOST] + [F_VISIBLE] * 5)
            self.assertEqual(self.shown(), [1, 2, 4, 5])
        for _ in range(3):
            self.same(on)
        cut = ([(1.0, 0, 0, 0.1), (0, 0, 1.0, 0), (0, 1.0, 0, 0)], [True, False, False], 0)     # x < -0.1 removed
        for _ in range(3):
            self.same(on, clip=cut)
            self.assertEqual(self.shown(), [0, 2])              # what is left of the wall still covers 1
        cut = ([(-1.0, 0, 0, -0.1), (0, 0, 1.0, 0), (0, 1.0, 0, 0)], [True, False, False], 0)   # x > -0.1 removed
        for _ in range(3):
            self.same(on, clip=cut)
            self.assertEqual(self.shown(), [0, 1, 4])           # the wall's left part covers nothing of 1 and 4
        uncut_wall = [F_VISIBLE | F_NOCLIP] + [F_VISIBLE] * 5   # a structure the section does not cut hides fully
        for _ in range(3):
            self.same(uncut_wall, clip=cut)
            self.assertEqual(self.shown(), [0])

    def test_no_test_while_the_view_moves_when_it_costs_more_than_it_saves(self):
        r, on = self.renderer, [F_VISIBLE] * 6
        r.OCC_OVERHEAD_TRIANGLES = 10 ** 9
        try:
            for eye in (self.FRONT, self.SIDE, (1.0, 0.0, 3.0), (2.0, 0.0, 3.0)):
                stats = self.same(on, eye=eye)                  # moving: the whole list, no test
                self.assertNotIn("covered", stats)
                self.assertEqual(stats["opaque"][0], 10)
            self.assertIn("covered", self.same(on, eye=(2.0, 0.0, 3.0)))                # at rest: tested
            self.assertIn("covered", self.same(on, eye=(2.0, 0.0, 3.0)))
            self.assertTrue(r._occ_final)
            self.assertTrue(r._occ_hint[2])                     # that answer says a moving frame would not pay
            self.assertNotIn("covered", self.same(on, eye=self.SIDE))
            self.assertNotIn("pieces", r._lists["occ"])         # judged from it, with no work per piece
            self.assertNotIn("covered", self.same([F_VISIBLE] * 5 + [0], eye=self.FRONT))
            self.assertIn("pieces", r._lists["occ"])            # another state: judged from its own pieces
        finally:
            del r.OCC_OVERHEAD_TRIANGLES

    def test_fallbacks_draw_the_lists_of_before(self):
        import app.renderer as renderer_module
        from app import shaders
        r, on = self.renderer, [F_VISIBLE] * 6
        self.assertIn("return;", renderer_module.depth_only_fs())
        original = shaders.OPAQUE_FS
        try:                                                    # a discard after the stop: no depth-only shader
            shaders.OPAQUE_FS = original.replace("    o_id = float(v_obj) + 1.0;", "    if (v_alpha < 0.1) discard;\n"
                                                 "    o_id = float(v_obj) + 1.0;")
            self.assertNotEqual(shaders.OPAQUE_FS, original)
            self.assertIsNone(renderer_module.depth_only_fs())
        finally:
            shaders.OPAQUE_FS = original
        indirect, occ = r._indirect, r._occ
        try:
            r._indirect = False                                 # below OpenGL 4.3
            self.assertNotIn("covered", self.same(on))
            r._indirect, r._occ = indirect, False               # the test's shaders did not compile
            self.assertNotIn("covered", self.same(on))
        finally:
            r._indirect, r._occ = indirect, occ
        self.assertIn("covered", self.same(on))

    BUFFERS = ("window", "colour", "id", "depth", "mask", "outline")
    LOG = "anatomy.renderer"
    # One error in each step a frame of the test takes: (step, frames with the test before the faulted one, the
    # eye of the faulted frame, where the object is kept, its name, the method that fails, on which call, after
    # doing its work, a second test in the frame). A failing draw has drawn: the fallback must undo it.
    FAULTS = (
        ("depth-only draw", 1, FRONT, "occ", "depth_vao", "render_indirect", 1, True, False),
        ("depth-only draw after a jump", 2, SIDE, "occ", "depth_vao", "render_indirect", 1, True, False),
        ("depth-only draw, nothing drawn", 1, FRONT, "occ", "depth_vao", "render_indirect", 1, False, False),
        ("depth reduction", 1, FRONT, "occ", "reduce_vao", "render", 1, True, False),
        ("depth reduction, nothing drawn", 0, FRONT, "occ", "reduce_vao", "render", 1, False, False),
        ("box test", 1, FRONT, "occ", "vao", "render", 1, True, False),
        ("box test after a jump", 2, SIDE, "occ", "vao", "render", 1, False, False),
        ("read-back", 1, FRONT, "occ", "seen", "read", 1, True, False),
        ("read-back of the first frame", 0, FRONT, "occ", "seen", "read", 1, False, False),
        ("shaded draw after a test", 1, FRONT, "self", "vao_opaque", "render_indirect", 1, True, False),
        ("shaded draw, nothing drawn", 1, FRONT, "self", "vao_opaque", "render_indirect", 1, False, False),
        ("shaded draw from a final answer", 2, FRONT, "self", "vao_opaque", "render_indirect", 1, True, False),
        ("second test of a frame", 0, FRONT, "occ", "seen", "read", 2, True, True),
        ("the whole box test", 1, FRONT, "self", "_test_boxes", "_test_boxes", 1, False, False),
        ("the piece draw, depth only", 1, FRONT, "self", "_draw_pieces", "_draw_pieces", 1, False, False),
        ("the piece draw, shaded", 1, FRONT, "self", "_draw_pieces", "_draw_pieces", 2, True, False),
    )

    class FailsOnce:
        """Stands in for an object of the test: `method` raises on its call number `at` (after doing its work
        when `after`), as a driver error would; everything else is the object's own. at=0: it never raises."""

        def __init__(self, real, method, at, after):
            self.real, self.method, self.at, self.after = real, method, at, after
            self.calls = self.raised = 0

        def __getattr__(self, name):
            attr = getattr(self.real, name)
            if name != self.method:
                return attr

            def call(*args, **kwargs):
                self.calls += 1
                if self.calls != self.at:
                    return attr(*args, **kwargs)
                self.raised += 1
                if self.after:
                    attr(*args, **kwargs)
                raise RuntimeError(f"injected in {name}")
            return call

    def faulted(self, warm, eye, holder, name, method, at, after, loose):
        """Reference frames without the test, `warm` frames with it, then the views of the references again
        with the stand-in in place. Yields (stand-in, reference, frame, log records) for each of them."""
        r, on = self.renderer, [F_VISIBLE] * 6
        views = ((on, eye), (on, eye), (on, self.SIDE), ([0] + [F_VISIBLE] * 5, self.FRONT), (on, self.FRONT))
        r.use_occlusion = False
        plain = [self.draw(flags, self.NO_CLIP, e) for flags, e in views]   # all taken before anything fails
        r.use_occlusion = True
        if loose:
            r.OCC_LOOSE_TRIANGLES = 0
        place = real = None
        try:
            for _ in range(warm):
                self.assertIn("covered", self.draw(on, self.NO_CLIP, self.FRONT)[1])
            self.assertIsNotNone(r._occlusion())
            place = r._occ if holder == "occ" else vars(r)
            real = place.get(name)
            if name == method:                                  # a method of the renderer itself
                fail = self.FailsOnce(r, method, at, after)
                place[name] = getattr(fail, method)
            else:
                fail = place[name] = self.FailsOnce(real, method, at, after)
            for (flags, e), reference in zip(views, plain):
                handler = _Records()
                logger = logging.getLogger(self.LOG)
                logger.addHandler(handler)
                try:
                    frame = self.draw(flags, self.NO_CLIP, e)
                finally:
                    logger.removeHandler(handler)
                yield fail, reference, frame, handler.records
        finally:
            if loose:
                del r.OCC_LOOSE_TRIANGLES
            if place is not None and (place is not r._occ) == (holder == "self"):
                if real is None:
                    place.pop(name, None)
                else:
                    place[name] = real
            if r._occ is False:
                r._occ = None                                   # the other tests of this class start with the test on

    def test_an_error_in_any_step_of_a_frame_draws_that_frame_from_the_lists_and_ends_the_test(self):
        r = self.renderer
        for step, *case in self.FAULTS:
            with self.subTest(step=step):
                self.setUp()
                frames = self.faulted(*case)
                fail, (plain, plain_stats), (bufs, stats), records = next(frames)
                self.assertEqual(fail.raised, 1)                # the step ran in this frame, and failed in it
                for buffer, a, b in zip(self.BUFFERS, plain, bufs):
                    self.assertEqual(a, b, f"faulted frame: {buffer}")
                self.assertEqual(stats, plain_stats)            # the whole list, and nothing counted twice
                self.assertIs(r._occ, False)
                self.assertEqual((r.occ_fbo, r.occ_small, r.occ_small_tex), (None, None, None))
                self.assertEqual(len(records), 1)               # one line, naming the error
                self.assertEqual(records[0].levelno, logging.WARNING)
                self.assertIn("injected in " + case[4], records[0].getMessage())
                self.assertNotIn("\n", records[0].getMessage())
                following = 0
                for fail, (plain, plain_stats), (bufs, stats), records in frames:
                    following += 1
                    for buffer, a, b in zip(self.BUFFERS, plain, bufs):
                        self.assertEqual(a, b, f"frame {following} after the fault: {buffer}")
                    self.assertEqual(stats, plain_stats)
                    self.assertIs(r._occ, False)                # off for the rest of the session
                    self.assertEqual((fail.raised, records), (1, []))
                self.assertEqual(following, 4)
                self.assertIsNone(r._occ)                       # put back by faulted() for the next case
                self.assertIn("covered", self.same([F_VISIBLE] * 6))
            frames.close()                                      # after a failed case too: the test is put back

    def test_without_an_error_the_test_stays_in_use(self):
        r, on = self.renderer, [F_VISIBLE] * 6
        handler = _Records()
        logging.getLogger(self.LOG).addHandler(handler)
        try:
            sent = []
            for eye in (self.FRONT, self.FRONT, self.FRONT, self.SIDE, self.SIDE, self.SIDE):
                stats = self.same(on, eye=eye)
                self.assertIsInstance(r._occ, dict)
                sent.append(stats["covered"][1:3])
            self.assertEqual(sent[:3], [(0, 10), (10, 6), (0, 6)])      # the counts of before the guard
            self.assertEqual(sent[5][0], 0)                             # a resting view is drawn with no test
            # the stand-ins themselves change nothing: with none of them raising, every frame is still tested
            for step, *case in self.FAULTS:
                with self.subTest(step=step):
                    self.setUp()
                    case[5] = 0
                    for fail, (plain, plain_stats), (bufs, stats), _ in self.faulted(*case):
                        self.assertEqual(plain, bufs)
                        self.assertIn("covered", stats)
                        self.assertIsInstance(r._occ, dict)
                        self.assertEqual(fail.raised, 0)
                    self.assertGreater(fail.calls, 0)
        finally:
            logging.getLogger(self.LOG).removeHandler(handler)
        self.assertEqual(handler.records, [])


class _Records(logging.Handler):
    """Keeps the records of a logger (the renderer logs one line when the covered test fails)."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


if __name__ == "__main__":
    unittest.main()
