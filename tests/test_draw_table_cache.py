"""The fast renderer's draw table from per-part arrays (app/gpu/drawtable.py) and its reuse between frames.

The array code must give, bit for bit, the table the renderer used to fill part by part: the first class checks that
against a plain per-part version on made-up parts (levels, split draws, selection, missing geometry). The second class
needs a wgpu adapter: a still view builds the table once, and hiding, selecting, isolating or moving a part builds it
again with the right rows, the same picks and the same picture as a renderer that has kept nothing.

    python -m unittest discover -s tests -p test_draw_table_cache.py
"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

from app.gpu import drawtable as dt                             # noqa: E402


def made_up_parts(rng, n=60, levels=4):
    """(parts, geom) with the fields PartStatics reads: some parts without a page, some with fewer levels, some tiny."""
    parts, ranges, keys = [], [], []
    at = 0
    for i in range(n):
        nl = int(rng.integers(1, levels + 1))
        rg, ky = [], []
        for _k in range(nl):
            count = int(rng.choice([0, 3, 30, 300, 2400, 9000]))
            rg.append((at, count))
            ky.append(int(rng.integers(0, 50)) * 100)             # equal keys happen: the part index breaks the tie
            at += count
        ranges.append(rg)
        keys.append(ky[:int(rng.integers(1, nl + 1))])            # the key list may be shorter than the range list
        parts.append(SimpleNamespace(id=f"p{i}", item=int(rng.integers(0, 12)), role=str(rng.choice(["body", "covering"])),
                                     look=SimpleNamespace(translucent=bool(rng.integers(0, 4) == 0))))
    page_of = rng.integers(-1, 3, n).astype(np.int32)
    geom = SimpleNamespace(ranges=ranges, gl_keys=keys, page_of=page_of, anim_base=rng.integers(-1, 2, n).astype(np.int64))
    return parts, geom


def table_part_by_part(parts, geom, draws, level, bits_max, M, nmat, flip, weight, noclip, selected, rec, tex_slot):
    """The renderer's table code before the arrays (WgpuRenderer._build_table at e54dad0), on plain inputs."""
    items = []
    for pi in draws:
        k = level.get(parts[pi].id, 0)
        rg = geom.ranges[pi]
        first, count = rg[k] if k < len(rg) else rg[0]
        if count < 3 or geom.page_of[pi] < 0:
            continue
        key = geom.gl_keys[pi][k] if k < len(geom.gl_keys[pi]) else geom.gl_keys[pi][0]
        items.append((key, pi, k, first, count))
    items.sort(key=lambda e: (e[0], e[1]))
    bits = bits_max
    while True:
        cap = 1 << bits
        n_slots = sum(-(-(e[4] // 3) // cap) for e in items)
        if n_slots + 1 <= (1 << (31 - bits)):
            break
        bits -= 1
        if bits < 8:
            raise RuntimeError(n_slots)
    table = np.zeros((n_slots + 1, dt.DRAW_FLOATS), dtype=np.float32)
    tu = table.view(np.uint32)
    entries, slot = [], 1
    for _key, pi, k, first, count in items:
        p = parts[pi]
        flags = ((dt.DRAW_NOCLIP if noclip[pi] else 0) | (dt.DRAW_MIRRORED if flip[pi] else 0)
                 | (dt.DRAW_SELECTED if p.item in selected else 0))
        tris = count // 3
        for a in range(0, tris, cap):
            n = min(cap, tris - a)
            table[slot, 0:16] = np.ascontiguousarray(M[pi].T).reshape(-1)
            table[slot, 16:19] = nmat[pi][:, 0]
            table[slot, 20:23] = nmat[pi][:, 1]
            table[slot, 24:27] = nmat[pi][:, 2]
            tu[slot, 28:32] = (first + 3 * a, 0, n, int(geom.page_of[pi]))
            tu[slot, 32:36] = (pi, p.item, flags, k)
            table[slot, 36] = weight[pi]
            tu[slot, 37] = rec[pi]
            tu[slot, 38] = tex_slot[pi]
            entries.append((slot, pi, k, first + 3 * a, 3 * n))
            slot += 1
    return table, entries, bits


class DrawTableArrays(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(7)

    def case(self, bits_max, n=60):
        rng = self.rng
        parts, geom = made_up_parts(rng, n)
        ps = dt.PartStatics(parts, geom)
        M = rng.normal(size=(n, 4, 4))
        nmat = rng.normal(size=(n, 3, 3))
        flip, noclip = rng.integers(0, 2, n), rng.integers(0, 2, n)
        weight = np.where(rng.integers(0, 3, n) == 0, rng.random(n), 0.0)
        rec, tex_slot = rng.integers(0, 9, n), rng.integers(0, 3, n)
        level = np.where(rng.integers(0, 2, n) == 0, rng.integers(0, 6, n), 0)     # 4 and 5 are beyond every part's levels
        selected = frozenset(int(x) for x in rng.integers(0, 12, 3))
        draws = np.flatnonzero(rng.integers(0, 4, n) > 0)
        want = table_part_by_part(parts, geom, draws.tolist(), {parts[i].id: int(level[i]) for i in range(n) if level[i]},
                                  bits_max, M, nmat, flip, weight, noclip, selected, rec, tex_slot)
        idx, k, first, count = dt.order_draws(ps, draws, level)
        row = np.zeros((n, dt.XF_FLOATS), dtype=np.float32)
        row[:, 0:16] = M.transpose(0, 2, 1).reshape(n, 16)
        cols = np.zeros((n, 3, 4), dtype=np.float32)            # the normal matrix, a column to a vec4
        cols[:, :, :3] = nmat.transpose(0, 2, 1)
        row[:, 16:28] = cols.reshape(n, 12)
        sel = np.isin(ps.item[idx], np.array(sorted(selected)))
        flags = noclip[idx] * dt.DRAW_NOCLIP + flip[idx] * dt.DRAW_MIRRORED + sel * dt.DRAW_SELECTED
        got = dt.build_rows(idx, k, first, count, bits_max, row[idx], ps.item[idx], ps.page[idx], flags, weight[idx], rec[idx],
                            tex_slot[idx])
        return want, got, idx

    def test_rows_entries_and_bits_equal_the_part_by_part_table(self):
        for bits_max in (20, 12, 9, 8):
            for _ in range(6):
                (table, entries, bits), (t2, e2, b2, slot0), idx = self.case(bits_max)
                self.assertEqual(table.shape, t2.shape)
                self.assertEqual(table.tobytes(), t2.tobytes())
                self.assertEqual(entries, e2)
                self.assertEqual(bits, b2)
                first_slot = {}
                for slot, pi, *_rest in entries:
                    first_slot.setdefault(pi, slot)
                self.assertEqual([first_slot[pi] for pi in idx.tolist()], slot0.tolist())

    def test_long_draws_are_split_over_slots(self):
        (table, entries, bits), (t2, e2, b2, _slot0), idx = self.case(8)
        self.assertEqual(b2, 8)
        self.assertGreater(len(e2), len(idx), "9000 indices are 3000 triangles: more than 256 a slot")
        self.assertTrue(all(count <= 3 * 256 for *_x, count in e2))

    def test_nothing_drawn_is_one_empty_row(self):
        parts, geom = made_up_parts(self.rng, 5)
        ps = dt.PartStatics(parts, geom)
        idx, k, first, count = dt.order_draws(ps, np.zeros(0, dtype=np.int64), np.zeros(5, dtype=np.int64))
        e = np.zeros(0, dtype=np.int64)
        table, entries, bits, slot0 = dt.build_rows(idx, k, first, count, 20, np.zeros((0, dt.XF_FLOATS), np.float32), e, e, e,
                                                    np.zeros(0), e, e)
        self.assertEqual((table.shape, entries, bits, len(slot0)), ((1, dt.DRAW_FLOATS), [], 20, 0))

    def test_too_many_slots_is_an_error(self):
        with self.assertRaises(dt.SlotError):
            dt.pick_bits(np.full(1 << 16, 1 << 20, dtype=np.int64), 20)

    def test_split_parts_is_the_per_part_rule(self):
        from app.viewer.renderer import _transparent_pass
        rng = self.rng
        parts, geom = made_up_parts(rng, 80)
        ps = dt.PartStatics(parts, geom)
        for opaque in (False, True):
            vis = rng.integers(0, 3, 12) > 0
            ghost = rng.integers(0, 4, 12) == 0
            alpha = rng.choice(np.array([1.0, 0.999, 0.9989999, 0.5], dtype=np.float32), 12)
            inside = rng.integers(0, 5, 80) > 0
            frame = SimpleNamespace(opaque_materials=opaque)
            draws, oit = [], []
            for i, p in enumerate(parts):
                if not vis[p.item] or not inside[i]:
                    continue
                (oit if _transparent_pass(p, bool(ghost[p.item]), float(alpha[p.item]), frame) else draws).append(i)
            got = dt.split_parts(ps, vis, ghost, alpha, opaque, inside)
            self.assertEqual((got[0].tolist(), got[1].tolist()), (draws, oit))

    def test_frame_draws_same(self):
        sig = np.arange(8).reshape(4, 2)
        xf = {}
        d = dt.FrameDraws(sig=sig, scalars=(False, 20), xf=xf, table=None, entries=[], bits=20)
        self.assertTrue(d.same(sig.copy(), (False, 20), xf))
        self.assertFalse(d.same(sig.copy(), (False, 20), {}), "another transform state")
        self.assertFalse(d.same(sig.copy(), (True, 20), xf))
        self.assertFalse(d.same(sig[:, :1].copy(), (False, 20), xf))
        other = sig.copy()
        other[2, 1] = 1                                         # one part became selected
        self.assertFalse(d.same(other, (False, 20), xf))


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


@needs_gpu
class KeptDrawTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wgpu
        from app.viewer.renderer import Settings
        cls.model = fixture_model()
        cls.cam = camera_for(cls.model)
        cls.s = Settings()
        cls.tgt = GPU.device.create_texture(size=(W, H, 1), format="rgba8unorm",
                                            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC
                                            | wgpu.TextureUsage.TEXTURE_BINDING)

    def fresh(self):
        from app.gpu.renderer import WgpuRenderer
        r = WgpuRenderer(GPU)
        r.set_model(self.model)
        self.addCleanup(r.release)
        return r

    def frame(self, r, fs=None, n=1):
        for _ in range(n):
            r.render(self.tgt, (W, H), self.cam, self.s, fs)
        self.assertTrue(r.frame_ok)
        return r

    def picture(self, r, fs=None):
        self.frame(r, fs, 4)                                    # the bounce light reads the frame before
        return r.read_final(self.tgt, (W, H)), r.read_ids()[0]

    def writes_of_the_draw_rows(self, r):
        """Count the uploads of the table's draw rows by wrapping the queue's write_buffer."""
        seen = []
        real = r.queue.write_buffer

        def write(buf, offset, data, *a, **k):
            if buf is r._tab and offset == r._tab_off["draws"] * 4:
                seen.append(offset)
            return real(buf, offset, data, *a, **k)
        r.queue = SimpleNamespace(write_buffer=write, write_texture=r.queue.write_texture, submit=r.queue.submit,
                                  read_buffer=r.queue.read_buffer)
        return seen

    def test_a_still_view_builds_and_uploads_the_table_once(self):
        r = self.frame(self.fresh())
        table, entries = r.last_table, r.last_draws
        seen = self.writes_of_the_draw_rows(r)
        self.frame(r, n=5)
        self.assertIs(r.last_table, table)
        self.assertIs(r.last_draws, entries)
        self.assertEqual(seen, [], "the rows of an unchanged table are not written again")
        self.assertEqual(len(entries), 2)

    def test_moving_the_camera_keeps_the_table(self):
        r = self.frame(self.fresh())
        table = r.last_table
        cam = camera_for(self.model)
        for _ in range(4):
            cam.yaw += 0.2
            cam.snap()
            r.render(self.tgt, (W, H), cam, self.s, None)
        self.assertIs(r.last_table, table)

    def test_hiding_selecting_and_showing_again(self):
        from app.gpu.renderer import DRAW_SELECTED
        from app.viewer.renderer import FrameState
        r = self.frame(self.fresh())
        base = r.last_table
        self.frame(r, FrameState(visible=np.array([True, False])))
        self.assertIsNot(r.last_table, base)
        self.assertEqual([e[1] for e in r.last_draws], [0])
        self.assertEqual(set(np.unique(r.read_ids()[0])), {-1, 0})
        self.frame(r, FrameState(selected=frozenset({1})))
        flags = r.last_table.view(np.uint32)[1:, 34]
        items = r.last_table.view(np.uint32)[1:, 33]
        self.assertTrue(np.all((flags[items == 1] & DRAW_SELECTED) != 0))
        self.assertTrue(np.all((flags[items == 0] & DRAW_SELECTED) == 0))
        self.frame(r, None)
        self.assertEqual(r.last_table.tobytes(), base.tobytes())
        self.assertEqual(set(np.unique(r.read_ids()[0])), {-1, 0, 1})

    def test_same_picture_and_ids_as_a_renderer_that_kept_nothing(self):
        from app.viewer.renderer import FrameState
        states = [None, FrameState(visible=np.array([False, True])), FrameState(selected=frozenset({0})),
                  FrameState(hovered=1), FrameState(ghost=np.array([True, False])), None]
        kept = self.fresh()
        for fs in states:
            img, ids = self.picture(kept, fs)                   # one renderer through every state, in turn
            ref_img, ref_ids = self.picture(self.fresh(), fs)   # a new renderer for each state
            self.assertTrue(np.array_equal(ids, ref_ids))
            self.assertTrue(np.array_equal(img, ref_img))

    def test_a_moved_part_gets_new_rows_and_the_pick_follows(self):
        r = self.frame(self.fresh())
        base = r.last_table.copy()
        m = self.model
        saved = m.item_offsets
        try:
            m.item_offsets = np.zeros((len(m.items), 3), dtype=np.float64)
            m.item_offsets[1] = (0.0, 0.2, 0.0)
            self.frame(r)
            moved = r.last_table
            rows = moved.view(np.uint32)[1:, 33]
            self.assertFalse(np.array_equal(moved[1:][rows == 1], base[1:][rows == 1]))
            self.assertTrue(np.array_equal(moved[1:][rows == 0], base[1:][rows == 0]))
            ref = self.frame(self.fresh())
            self.assertEqual(moved.tobytes(), ref.last_table.tobytes())
            self.assertTrue(np.array_equal(r.read_ids()[0], ref.read_ids()[0]))
        finally:
            m.item_offsets = saved
        self.frame(r)
        self.assertEqual(r.last_table.tobytes(), base.tobytes())

    def test_level_dict_and_part_lists_keep_their_old_form(self):
        r = self.frame(self.fresh())
        self.assertEqual(r._level, {})
        V, Pm = self.cam.view_matrix(), self.cam.proj_matrix(W / H)
        n = len(self.model.items)
        draws, oit = r.visible_parts(Pm @ V, np.ones(n, bool), np.zeros(n, bool), np.ones(n, np.float32), r._fs)
        self.assertEqual([p.id for p in draws], [p.id for p in self.model.parts])
        self.assertEqual(oit, [])
        table, entries, bits = r._build_table(draws, self.s, r._fs)      # a list of parts is still accepted
        self.assertIs(table, r.last_table)
        self.assertEqual((entries, bits), (r.last_draws, r.last_prim_bits))

    def test_post_passes_keep_their_bind_groups_while_nothing_changes(self):
        r = self.frame(self.fresh(), n=3)
        groups, views = dict(r.post._groups), dict(r.post._views)
        self.frame(r, n=3)
        self.assertEqual(set(r.post._groups), set(groups))
        self.assertTrue(all(r.post._groups[k][1] is groups[k][1] for k in groups))
        self.assertEqual(set(r.post._views), set(views))
        r._ensure_targets(W + 2, H, r.samples)                  # new targets: nothing of the old ones is kept
        self.assertEqual((r.post._groups, r.post._views), ({}, {}))


if __name__ == "__main__":
    unittest.main()
