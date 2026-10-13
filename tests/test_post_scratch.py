"""The ambient-occlusion scratch textures of the fast renderer belong to the render size in use, not to every size seen.

app/gpu/post.py makes a half-size set (``_lo``), a full-size AO texture (``_hi``) and, for a caller without a depth
texture of its own, a packed depth (``_depth``) for the size it is asked to work at. A window edge being dragged, a
change of render scale and a screenshot at another scale each bring a new size; the textures of the size before must be
destroyed then, with the depth-chain records, views and bind groups that point at them, or the card fills up (one set
per size was kept for ever: 100 window sizes held 102 sets).

The renderer is driven the way the viewport drives it (ViewportCore._paint_frame, grab_image, release_gl), and after
the sizes have come and gone its picture is compared with a renderer built from nothing.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np                                              # noqa: E402

from test_oit_cache import GPU, View, fixture_model, needs_gpu  # noqa: E402

W, H = 128, 96
# a window edge being dragged: every size is new (odd sizes too: the half-size set rounds up)
DRAG = [(W + 7 * i, H + 5 * i) for i in range(1, 12)] + [(W + 33, H + 17)]


@needs_gpu
class ScratchOfOneSize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import wgpu
        from app.viewer.camera import OrbitCamera
        from app.viewer.renderer import Settings
        self.usage = wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC | wgpu.TextureUsage.TEXTURE_BINDING
        self.model = fixture_model()
        self.view = View(self.model)
        self.s = Settings()
        cam = OrbitCamera()
        cam.set_scene(self.model.bounds_min, self.model.bounds_max)
        cam.target = cam.scene_centre.copy()
        cam.distance = cam.fit_distance(cam.scene_radius, W / H)
        cam.yaw, cam.pitch = 0.4, 0.3
        cam.snap()
        self.cam = cam
        # every texture destroyed from here on, held so that its id stays its own
        self.destroyed = {}
        probe = GPU.device.create_texture(size=(2, 2, 1), format="rgba8unorm", usage=self.usage)
        real = type(probe).destroy

        def destroy(tex, *a, **k):
            self.destroyed[id(tex)] = tex
            return real(tex, *a, **k)
        patch = mock.patch.object(type(probe), "destroy", destroy)
        patch.start()
        self.addCleanup(patch.stop)
        self.seen = {}                                          # id -> (post passes, scratch texture they ever held)

    # ------------------------------------------------------------------ the viewport's calls
    def fresh(self):
        from app.gpu.renderer import WgpuRenderer
        r = WgpuRenderer(GPU)
        r.set_model(self.model)
        self.addCleanup(r.release)
        return r

    def target(self, size):
        t = GPU.device.create_texture(size=(*size, 1), format="rgba8unorm", usage=self.usage)
        self.addCleanup(t.destroy)
        return t

    def paint(self, r, out, scale=1.0, n=1, target=None):
        """ViewportCore._paint_frame: the render size is the window's size times the render scale."""
        size = max(int(out[0] * scale), 2), max(int(out[1] * scale), 2)
        target = target or self.target(out)
        self.cam.aspect = size[0] / size[1]
        for _ in range(n):
            r.render(target, size, self.cam, self.s, self.view.frame_state(), out_size=out)
            self.note(r)
        self.assertTrue(r.frame_ok)
        return target

    def grab(self, r, out, scale):
        """ViewportCore.grab_image: three frames into a target of its own at ``scale`` times the window's size."""
        size = int(out[0] * scale), int(out[1] * scale)
        target = self.target(size)
        for _ in range(3):
            r.render(target, size, self.cam, self.s, self.view.frame_state())
            self.note(r)
        img = r.read_final(target, size).copy()
        target.destroy()                                        # _offscreen_end
        return img

    # ------------------------------------------------------------------ what is held
    def scratch(self, post):
        out = [t for lo in post._lo.values() for t in lo.values()]
        return out + list(post._hi.values()) + list(post._depth.values())

    def note(self, r):
        for t in self.scratch(r.post):
            self.seen[id(t)] = (r.post, t)

    def one_size(self, r, what):
        """Scratch of the renderer's size only, every other one destroyed, and nothing kept that points at a
        destroyed texture."""
        post = r.post
        self.assertEqual(list(post._lo), [r.size], what)
        self.assertEqual(list(post._hi), [r.size], what)
        self.assertEqual(list(post._depth), [], what)            # the renderer brings its own depth texture
        held = {id(t) for t in self.scratch(post)}
        left = [i for i, (p, _t) in self.seen.items() if p is post and i not in held and i not in self.destroyed]
        self.assertEqual(len(left), 0, f"{what}: {len(left)} of {len(self.seen)} scratch textures neither held nor destroyed")
        self.assertFalse(held & set(self.destroyed), what)
        self.nothing_points_at_a_destroyed_texture(post, what)

    def nothing_points_at_a_destroyed_texture(self, post, what):
        for tex in [v[0] for v in post._dmip.values()] + [v[0] for v in post._views.values()]:
            self.assertNotIn(id(tex), self.destroyed, what)
        for res, _bg in post._groups.values():
            for x in res:
                self.assertNotIn(id(x), self.destroyed, what)

    def same_as_fresh(self, kept, out, what, scale=1.0):
        """The kept renderer against a renderer that has kept nothing: picture and ids."""
        a_t = self.paint(kept, out, scale, n=4)                 # the bounce light reads the frame before
        ref = self.fresh()
        b_t = self.paint(ref, out, scale, n=4)
        a, b = kept.read_final(a_t, out), ref.read_final(b_t, out)
        self.assertTrue(np.array_equal(kept.read_ids()[0], ref.read_ids()[0]), what)
        self.assertTrue(np.array_equal(a, b), f"{what}: {int(np.count_nonzero(a != b))} differing values")
        self.assertGreater(int(np.ptp(a[..., :3])), 20, "the model is in the picture")

    # ------------------------------------------------------------------ tests
    def test_a_dragged_window_leaves_the_scratch_of_the_last_size_only(self):
        r = self.fresh()
        self.paint(r, (W, H), n=2)
        self.one_size(r, "first size")
        for out in DRAG:
            self.paint(r, out)
            self.one_size(r, f"window {out}")
        self.assertGreaterEqual(len(self.seen), 4 * (len(DRAG) + 1))
        self.same_as_fresh(r, DRAG[-1], "after the drag")
        self.same_as_fresh(r, (W, H), "back at the first size")
        self.one_size(r, "back at the first size")

    def test_render_scale_and_a_screenshot_at_another_scale(self):
        r = self.fresh()
        out = (W + 32, H + 16)
        self.paint(r, out, n=2)
        for scale in (0.5, 0.75, 1.0, 0.5):
            self.paint(r, out, scale, n=2)
            self.one_size(r, f"render scale {scale}")
        self.same_as_fresh(r, out, "render scale 0.5", scale=0.5)
        for scale in (0.5, 2.0):
            ref = self.fresh()
            self.assertTrue(np.array_equal(self.grab(r, out, scale), self.grab(ref, out, scale)), f"grab at {scale}")
            self.one_size(r, f"grab at {scale}")
            self.same_as_fresh(r, out, f"the window after a grab at {scale}")
            self.one_size(r, f"the window after a grab at {scale}")

    def test_another_sample_count_at_the_same_size_keeps_the_scratch(self):
        r = self.fresh()
        self.s.msaa = 4
        self.paint(r, (W, H), n=2)
        before = self.scratch(r.post)
        samples = r.samples
        self.s.msaa = 1                                         # anti-aliasing switched off: new targets, same size
        self.paint(r, (W, H), n=2)
        self.assertNotEqual(r.samples, samples)
        after = self.scratch(r.post)
        self.assertEqual([id(t) for t in before], [id(t) for t in after])
        self.assertFalse({id(t) for t in after} & set(self.destroyed))
        self.one_size(r, "another sample count")
        self.same_as_fresh(r, (W, H), "another sample count")

    def test_release_destroys_all_of_it(self):
        r = self.fresh()
        for out in DRAG[:3]:
            self.paint(r, out)
        post = r.post
        r.release()                                             # ViewportCore.release_gl
        self.assertEqual((len(post._lo), len(post._hi), len(post._depth), len(post._dmip), len(post._views),
                          len(post._groups)), (0, 0, 0, 0, 0, 0))
        left = [i for i, (p, _t) in self.seen.items() if p is post and i not in self.destroyed]
        self.assertEqual(len(left), 0, f"{len(left)} of {len(self.seen)} scratch textures not destroyed")

    def test_a_caller_without_a_depth_texture(self):
        """PostPasses used by itself (tools, the parity tests): the packed depth is per size too."""
        import wgpu
        from app.gpu.post import PostPasses
        dev = GPU.device
        usage = wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_SRC
        post = PostPasses(dev, ao_scale=1, gi_scale=2, far_mips=True)

        def frame(post, size):
            nd, prev, out = (dev.create_texture(size=(*size, 1), format=f, usage=usage)
                             for f in ("rgba32float", "rgba16float", "rgba16float"))
            post.run_ssao(nd, prev, out, tan=(0.5, 0.4), ortho=0, radius=0.1, power=1.6, large=4.0, large_mix=0.5,
                          gi_on=1.0)
            for t in self.scratch(post):
                self.seen[id(t)] = (post, t)
            return out
        for size in DRAG[:6]:
            frame(post, size)
            post.forget(keep=size)                              # the frame is submitted: the other sizes may go
            self.assertEqual((list(post._lo), list(post._hi), list(post._depth)), ([size], [size], [size]))
            held = {id(t) for t in self.scratch(post)}
            self.assertFalse(held & set(self.destroyed))
            self.assertEqual([i for i in self.seen if i not in held and i not in self.destroyed], [])
            self.assertEqual(len(self.seen), 5 * (DRAG.index(size) + 1))
            self.nothing_points_at_a_destroyed_texture(post, f"size {size}")
        size = DRAG[5]
        kept = self.scratch(post)
        a = self.read(frame(post, size))
        self.assertEqual([id(t) for t in kept], [id(t) for t in self.scratch(post)], "the kept size is used again")
        other = PostPasses(dev, ao_scale=1, gi_scale=2, far_mips=True)
        b = self.read(frame(other, size))
        self.assertTrue(np.array_equal(a, b))
        post.forget()
        other.forget()
        self.assertEqual((len(post._lo), len(post._hi), len(post._depth), len(post._dmip)), (0, 0, 0, 0))
        self.assertEqual([i for i in self.seen if i not in self.destroyed], [])

    def read(self, tex):
        w, h = tex.size[:2]
        raw = GPU.device.queue.read_texture({"texture": tex, "mip_level": 0, "origin": (0, 0, 0)},
                                            {"bytes_per_row": w * 8, "rows_per_image": h}, (w, h, 1))
        return np.frombuffer(raw, dtype=np.float16).reshape(h, w, 4).copy()


if __name__ == "__main__":
    unittest.main()
