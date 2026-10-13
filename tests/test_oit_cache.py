"""The fast renderer's translucent pass from per-part arrays, and what it keeps between frames (app/gpu/oit.py
OitPass.encode_parts, app/gpu/drawtable.py oit_rows, WgpuRenderer._oit_frame).

The first class needs no GPU: the array code must give the records the per-draw packer (oit.pack_draws) gives, and a
look record laid under the frame-wide bytes must be the ShadeU block packed from both sets of uniforms at once.

The second class needs a wgpu adapter. One renderer goes through a row of changes, each made the way the user interface
makes it (the SceneState calls of the model view, the viewport's own frame_state / clip_config / set_explode, the render
settings), and after each one its picture, its ids and the bytes it has on the GPU for the translucent draws are compared
with those of a renderer built from nothing for that state. A still frame must write nothing, a moved camera only the
frame-wide bytes.

    python -m unittest discover -s tests -p test_oit_cache.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

from app.gpu import drawtable as dt                             # noqa: E402
from app.gpu import oit as O                                    # noqa: E402
from app.gpu.shading_uniforms import FIELD_BY_NAME, SIZE, pack_shading_uniforms    # noqa: E402


class TranslucentArrays(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(11)

    def made_up(self, n=40):
        rng = self.rng
        parts = [SimpleNamespace(item=int(rng.integers(0, 9)),
                                 look=SimpleNamespace(facing=(0.05, 0.4, 0.7) if rng.integers(0, 3) == 0 else None))
                 for _ in range(n)]
        geom = SimpleNamespace(const_tail=rng.normal(size=(n, 13)).astype(np.float32),
                               stream_base=rng.integers(-1, 5000, (n, 5)).astype(np.int64),
                               vbase=rng.integers(0, 90000, n).astype(np.int64),
                               anim_base=rng.integers(-1, 300, n).astype(np.int64))
        return parts, geom

    def test_rows_equal_the_per_draw_packer(self):
        rng = self.rng
        for opaque in (False, True):
            parts, geom = self.made_up()
            n = len(parts)
            M, nmat = rng.normal(size=(n, 4, 4)), rng.normal(size=(n, 3, 3))
            weight = np.where(rng.integers(0, 3, n) == 0, rng.random(n), 0.0)
            ghost = rng.integers(0, 2, 9).astype(bool)
            alpha = rng.choice(np.array([1.0, 0.5, 0.08], dtype=np.float32), 9)
            idx = rng.permutation(n)[:25]
            draws = []
            for i in idx.tolist():
                p = parts[i]
                u = {"u_model": M[i], "u_nmat": nmat[i], "u_weight": float(weight[i]), "u_ghost": int(ghost[p.item]),
                     "u_ghost_alpha": 0.1, "u_alpha_mul": float(alpha[p.item]), "u_facing_on": 0}
                if p.look.facing and not opaque:
                    u.update(u_facing_on=1, u_facing=np.array(p.look.facing))
                draws.append(O.OitDraw(part=i, first=0, count=3, item=p.item, uniforms=u))
            want = O.pack_draws(draws, geom)
            row = np.zeros((n, dt.XF_FLOATS), dtype=np.float32)
            row[:, 0:16] = M.transpose(0, 2, 1).reshape(n, 16)
            cols = np.zeros((n, 3, 4), dtype=np.float32)
            cols[:, :, :3] = nmat.transpose(0, 2, 1)
            row[:, 16:28] = cols.reshape(n, 12)
            base, facing = dt.oit_base(parts, geom)
            item = np.array([parts[i].item for i in idx.tolist()])
            got = dt.oit_rows(base, facing, idx, row[idx], weight[idx], ghost[item], alpha[item], 0.1, opaque)
            self.assertEqual(got.shape, (len(idx), O.DRAW_FLOATS))
            self.assertEqual(got.tobytes(), want.tobytes())
            self.assertEqual(dt.OIT_FLOATS, O.DRAW_FLOATS)

    def test_no_animation_stream_is_minus_one(self):
        parts, geom = self.made_up(4)
        geom.anim_base = None
        base, _facing = dt.oit_base(parts, geom)
        self.assertTrue(np.all(base.view(np.int32)[:, 51] == -1))

    def test_look_record_under_the_frame_wide_bytes_is_the_whole_block(self):
        rng = self.rng
        look = {"u_base": rng.random(3), "u_alpha": 0.7, "u_rough": 0.4, "u_metal": 0.0, "u_f0": 0.04, "u_wrap": 0.2,
                "u_emis": rng.random(3), "u_use_vcol": 1, "u_alpha_cut": 0.0, "u_has_tex": 0, "u_stripe": 1,
                "u_stripe_p": rng.random(4), "u_shorten": 0.3, "u_stripe_a": rng.random(3), "u_stripe_b": rng.random(3),
                "u_mottle": 0, "u_detail_on": 0, "u_flip": 1, "u_weight": 0.25, "u_noclip": 0, "u_batched": 1}
        frame = {"u_view": rng.normal(size=(4, 4)), "u_campos": rng.random(3), "u_ortho": 0, "u_viewdir": rng.random(3),
                 "u_screen": np.array([640.0, 480.0], dtype=np.float32), "u_ao_on": 1.0, "u_ao_direct": 0.3,
                 "u_ldir0": rng.random(3), "u_lrad0": rng.random(3), "u_lsize0": 0.2, "u_sh": rng.random((9, 3)),
                 "u_spec_layers": 6.0, "u_env_diffuse": 1.0, "u_env_spec": 1.0, "u_bounce": 0.5,
                 "u_clip0": rng.random(4), "u_clip_on": (1, 0, 0), "u_clip_mode": 0}
        whole = pack_shading_uniforms({**frame, **look})
        runs = dt.byte_runs([FIELD_BY_NAME[name] for name in frame])
        block = np.frombuffer(pack_shading_uniforms(look), dtype=np.uint8).copy()
        g = np.frombuffer(pack_shading_uniforms(frame), dtype=np.uint8)
        for a, b in runs:
            block[a:b] = g[a:b]
        self.assertEqual(block.tobytes(), whole)
        self.assertTrue(all(0 <= a < b <= SIZE for a, b in runs))
        self.assertTrue(all(runs[i][1] < runs[i + 1][0] for i in range(len(runs) - 1)), "runs are merged and in order")


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


class View:
    """What the model viewport holds for frame_state, with the viewport's own methods (no window, no renderer)."""

    def __init__(self, model):
        from app.config import DEFAULT_SETTINGS
        from app.state import SceneState
        from app.viewer.dataset import ModelDataset
        from app.viewer.viewport_core import distinct_colours
        self.model = model
        self.settings = dict(DEFAULT_SETTINGS)
        self.state = SceneState(ModelDataset(model), self.settings)
        self._distinct = distinct_colours(len(model.items))
        self._group_colours = np.full((len(model.items), 3), 0.5, dtype=np.float32)
        self.sections = [None, None, None]
        self.cut_on, self.cut_planes = False, None
        self.anim_t = 0.0
        self.explode = 0.0

    def invalidate_labels(self):
        pass

    def frame_state(self):
        from app.viewer.viewport_core import ViewportCore
        return ViewportCore.frame_state(self)

    def clip_config(self):
        from app.viewer.viewport_core import ViewportCore
        return ViewportCore.clip_config(self)

    def anim_kind(self):
        from app.viewer.viewport_core import ViewportCore
        return ViewportCore.anim_kind(self)

    def set_explode(self, amount):
        from app.viewer.viewport_core import ViewportCore
        return ViewportCore.set_explode(self, amount)


@needs_gpu
class KeptTranslucentPass(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wgpu
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        cls.usage = (wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC | wgpu.TextureUsage.TEXTURE_BINDING)
        cls.tgt = GPU.device.create_texture(size=(W, H, 1), format="rgba8unorm", usage=cls.usage)

    def setUp(self):
        from app.viewer.camera import OrbitCamera
        from app.viewer.renderer import Settings
        self.model = fixture_model()
        self.view = View(self.model)
        self.st = self.view.state
        self.s = Settings()
        cam = OrbitCamera()
        cam.set_scene(self.model.bounds_min, self.model.bounds_max)
        cam.target = cam.scene_centre.copy()
        cam.distance = cam.fit_distance(cam.scene_radius, W / H)
        cam.yaw, cam.pitch = 0.4, 0.3
        cam.snap()
        self.cam = cam
        self.size, self.target = (W, H), self.tgt

    def fresh(self, model=None):
        from app.gpu.renderer import WgpuRenderer
        r = WgpuRenderer(GPU)
        r.set_model(model or self.model)
        self.addCleanup(r.release)
        return r

    def frame(self, r, n=1):
        for _ in range(n):
            r.render(self.target, self.size, self.cam, self.s, self.view.frame_state())
        self.assertTrue(r.frame_ok)
        return r

    def on_gpu(self, r):
        """(part list, record bytes, ShadeU block bytes) of the translucent draws of the last frame, in draw order."""
        if not r.oit.last_draws or r.oit._kept is None or r.oit._kept.part is None:
            return None
        k = r.oit._kept
        slot = k.slot_of[k.part]
        self.assertTrue(np.all(slot >= 0))
        self.assertIs(k.rows_on, r.oit._draw_buf)
        self.assertIs(k.su_on, r.oit._su_buf)
        return k.part.tolist(), k.rows[slot].tobytes(), k.blocks[slot].tobytes()

    def same_as_fresh(self, kept, what, model=None, translucent=True):
        """The kept renderer after a change against a renderer that has kept nothing: picture, ids, GPU bytes."""
        self.frame(kept, 4)                                     # the bounce light reads the frame before
        ref = self.frame(self.fresh(model), 4)
        self.assertEqual(bool(kept.oit.last_draws) and kept.oit._kept is not None, translucent, what)
        a, b = kept.read_final(self.target, self.size), ref.read_final(self.target, self.size)
        self.assertTrue(np.array_equal(kept.read_ids()[0], ref.read_ids()[0]), what)
        self.assertTrue(np.array_equal(a, b), f"{what}: {int(np.count_nonzero(a != b))} differing values")
        if translucent:
            self.assertEqual(self.on_gpu(kept), self.on_gpu(ref), what)
        return a

    def xray_others(self, item=0):
        self.st.select([item])
        self.st.set_ghost_focus(self.st.selected)               # ModelView.toggle_xray

    def writes(self, r):
        """Names of the translucent pass's buffers written from here on (the queue's write_buffer is wrapped)."""
        seen = []
        real = r.oit.device.queue.write_buffer
        names = {id(r.oit._draw_buf): "records", id(r.oit._su_buf): "shade", id(r.oit._frame_ub): "frame"}

        def write(buf, offset, data, *a, **k):
            if id(buf) in names:
                seen.append(names[id(buf)])
            return real(buf, offset, data, *a, **k)
        q = r.oit.device.queue
        fake = SimpleNamespace(write_buffer=write, write_texture=q.write_texture, submit=q.submit, read_buffer=q.read_buffer)
        r.oit.device = SimpleNamespace(queue=fake, create_bind_group=r.oit.device.create_bind_group,
                                       create_buffer=r.oit.device.create_buffer,
                                       create_render_bundle_encoder=r.oit.device.create_render_bundle_encoder,
                                       create_render_pipeline=r.oit.device.create_render_pipeline,
                                       create_shader_module=r.oit.device.create_shader_module,
                                       create_bind_group_layout=r.oit.device.create_bind_group_layout,
                                       create_pipeline_layout=r.oit.device.create_pipeline_layout,
                                       create_texture=r.oit.device.create_texture)
        return seen

    def test_a_still_view_writes_nothing_and_a_moved_camera_only_the_frame_wide_bytes(self):
        self.xray_others()
        r = self.frame(self.fresh(), 3)
        k = r.oit._kept
        self.assertEqual(r.oit.last_draws, 1)
        builds, run = k.builds, k.run
        seen = self.writes(r)
        self.frame(r, 5)
        self.assertEqual(seen, [], "a frame that changes nothing writes none of the pass's buffers")
        self.assertEqual(k.builds, builds)
        self.assertIs(k.run, run)
        self.cam.yaw += 0.2
        self.cam.snap()
        self.frame(r)
        self.assertEqual(sorted(seen), ["frame", "shade"], "the camera is in the frame uniform and in the ShadeU blocks only")
        self.assertEqual(k.builds, builds, "no bundle is made again for a moved camera")
        self.assertIs(r.oit._kept, k)
        self.same_as_fresh(r, "moved camera")

    def test_every_input_changed_in_turn_matches_a_renderer_built_from_nothing(self):
        st, view, s = self.st, self.view, self.s
        r = self.fresh()
        base = self.same_as_fresh(r, "nothing translucent", translucent=False)
        self.xray_others(0)
        xray = self.same_as_fresh(r, "x-ray others")
        self.assertFalse(np.array_equal(base, xray))
        steps = [
            ("the other item selected: it is solid again", lambda: st.select([1]), False),
            ("x-ray focus moved to the other item", lambda: st.set_ghost_focus([1]), True),
            ("selection cleared", st.clear_selection, True),
            ("hovered x-rayed item", lambda: st.set_hovered(0), True),
            ("hover gone", lambda: st.set_hovered(-1), True),
            ("custom colour on the x-rayed item", lambda: st.set_custom_color([0], (0.9, 0.2, 0.1)), True),
            ("custom colour removed", lambda: st.set_custom_color([0], None), True),
            ("distinct colours", lambda: view.settings.__setitem__("color_mode", 1), True),
            ("group colours", lambda: view.settings.__setitem__("color_mode", 2), True),
            ("own colours", lambda: view.settings.__setitem__("color_mode", 0), True),
            ("x-rayed item hidden", lambda: st.set_hidden([0], True), False),
            ("shown again", lambda: st.set_hidden([0], False), True),
            ("parts separated", lambda: view.set_explode(0.6), True),
            ("parts back", lambda: view.set_explode(0.0), True),
            ("a cross-section", lambda: view.sections.__setitem__(1, [0.05, False]), True),
            ("the section flipped", lambda: view.sections.__setitem__(1, [0.05, True]), True),
            ("no section", lambda: view.sections.__setitem__(1, None), True),
            ("x-ray strength", lambda: setattr(s, "ghost_alpha", 0.3), True),
            ("light level", lambda: setattr(s, "light_scale", 1.7), True),
            ("tissue term", lambda: setattr(s, "tissue", 0.4), True),
            ("stripes off", lambda: setattr(s, "stripes", False), True),
            ("environment light", lambda: setattr(s, "env_diffuse", 0.5), True),
            ("highlight colour", lambda: setattr(s, "highlight", (0.2, 1.0, 0.3)), True),
            ("no ambient occlusion", lambda: setattr(s, "ao", False), True),
            ("fewer samples", lambda: setattr(s, "msaa", 4), True),
            ("default samples", lambda: setattr(s, "msaa", 8), True),
            ("x-ray off", st.clear_ghost, False),
            ("lowered opacity", self.opacity(0.5), True),
            ("lower still", self.opacity(0.08), True),
            ("x-ray on top of it", lambda: self.xray_others(1), True),
            ("materials forced opaque", lambda: setattr(st, "opaque_materials", True), True),
            ("materials as authored", lambda: setattr(st, "opaque_materials", False), True),
            ("full opacity", self.opacity(1.0), True),
        ]
        seen = {xray.tobytes()}
        for what, change, translucent in steps:
            change()
            seen.add(self.same_as_fresh(r, what, translucent=translucent).tobytes())
        self.assertGreater(len(seen), 12, "the changes do change the picture")

    def opacity(self, value):
        def change():
            a = np.ones(len(self.model.items), dtype=np.float32)        # ModelView._opacity
            a[0] = value
            self.st.part_alpha = a
            self.st.render_changed.emit()
        return change

    def test_another_size_and_another_target(self):
        self.xray_others()
        r = self.fresh()
        self.same_as_fresh(r, "first size")
        self.size = (W + 32, H + 16)
        self.target = GPU.device.create_texture(size=(*self.size, 1), format="rgba8unorm", usage=self.usage)
        self.same_as_fresh(r, "another size")
        self.size, self.target = (W, H), self.tgt
        self.same_as_fresh(r, "the first size again")

    def test_another_model_keeps_nothing_of_the_first(self):
        self.xray_others()
        r = self.fresh()
        self.same_as_fresh(r, "first model")
        first = r.oit._kept
        other = fixture_model()
        other.item_offsets = np.zeros((len(other.items), 3), dtype=np.float64)
        other.item_offsets[0] = (0.0, 0.15, 0.0)
        r.set_model(other)
        self.assertIsNone(r.oit._kept, "set_model drops what the translucent pass kept")
        self.view.model = self.model = other
        self.same_as_fresh(r, "second model", model=other)
        self.assertIsNot(r.oit._kept, first)

    def test_slots_stay_while_the_list_changes_and_are_dropped_when_they_outnumber_it(self):
        from app.gpu.oit import OitPass
        pas = OitPass.__new__(OitPass)
        pas.su_stride, pas.geom, pas._kept = 512, object(), None
        looks = []
        k = pas._kept_state(2000, looks)
        self.assertIs(pas._kept_state(2000, looks), k)
        a = pas._slots(k, np.arange(0, 300))
        self.assertEqual(a.tolist(), list(range(300)))
        b = pas._slots(k, np.arange(100, 400))                 # 100 new parts: the old ones keep their slots
        self.assertEqual(b[:200].tolist(), list(range(100, 300)))
        self.assertEqual(b[200:].tolist(), list(range(300, 400)))
        k.rows_on = k.su_on = k.epoch = object()
        c = pas._slots(k, np.arange(1000, 1010))               # 410 slots for a list of 10: over 256 and over four to one
        self.assertEqual(c.tolist(), list(range(10)))
        self.assertEqual((k.n_slots, int((k.slot_of >= 0).sum())), (10, 10))
        self.assertEqual((k.rows_on, k.su_on, k.epoch), (None, None, None), "records, blocks and bundles are made again")
        self.assertTrue(np.all(k.slot_look == -1))
        self.assertIsNot(pas._kept_state(2000, []), k, "another list of look records is another model")


if __name__ == "__main__":
    unittest.main()
