"""Model-viewer ID, cut flag and linear-depth readback regression."""
import importlib.util
import unittest
from types import SimpleNamespace


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in
                         ("moderngl", "numpy", "PySide6")), "viewer dependencies required")
class ModelReadbackTests(unittest.TestCase):
    def fixture(self, fail=False, unwritten=False):
        import moderngl
        import numpy as np
        from app.viewer.renderer import Renderer
        ctx = SimpleNamespace(fbo=None, viewport=(3, 5, 800, 600))

        class Fbo:
            def use(self):
                ctx.fbo = self
                ctx.viewport = (0, 0, 4, 4)

            def read_into(self, values, components, attachment, **kwargs):
                if fail:
                    raise moderngl.Error("synthetic failure")
                if unwritten:
                    return
                row = [0, 0, 1, 3.5] if attachment == 0 else [257, 2]
                values.reshape(-1, components)[:] = row
                if ctx.fbo is not self:
                    np.minimum(values, 1, out=values)

            def read(self, components, attachment, viewport=None, **kwargs):
                count = 16 if viewport is None else viewport[2] * viewport[3]
                values = np.full(count * components, np.nan, np.float32)
                self.read_into(values, components, attachment, **kwargs)
                return values.tobytes()

        previous, prepass = Fbo(), Fbo()
        ctx.fbo = previous
        renderer = object.__new__(Renderer)
        renderer.ctx, renderer.t = ctx, {"fbo_pre": prepass}
        renderer.size, renderer.frame_ok = (4, 4), True
        renderer.last_camera = (np.eye(4), np.eye(4), 1.0, True, (1.0, 1.0), (4, 4))
        return renderer, ctx, previous

    def test_pick_keeps_large_id_cut_flag_and_linear_depth(self):
        import numpy as np
        renderer, ctx, previous = self.fixture()
        item, point, cut = renderer.pick(1, 1)
        self.assertEqual(item, 256)
        self.assertTrue(cut)
        np.testing.assert_allclose(point, [-0.25, 0.25, -3.5])
        self.assertIs(ctx.fbo, previous)
        self.assertEqual(ctx.viewport, (3, 5, 800, 600))

    def test_bulk_reads_and_point_queries_use_same_float_contract(self):
        import numpy as np
        renderer, ctx, previous = self.fixture()
        ids, flags = renderer.read_ids()
        np.testing.assert_array_equal(ids, np.full((4, 4), 256))
        np.testing.assert_array_equal(flags, np.full((4, 4), 2))
        np.testing.assert_array_equal(renderer.read_depth(), np.full((4, 4), 3.5))
        self.assertEqual(renderer.ids_at([(0, 0), (3, 3), (-1, 0), (4, 1)]),
                         [256, 256, -1, -1])
        self.assertIs(ctx.fbo, previous)
        self.assertEqual(ctx.viewport, (3, 5, 800, 600))

    def test_failed_read_restores_state_and_fails_closed(self):
        renderer, ctx, previous = self.fixture(fail=True)
        self.assertEqual(renderer.pick(1, 1), (-1, None, False))
        self.assertEqual(renderer.read_ids(), (None, None))
        self.assertIsNone(renderer.read_depth())
        self.assertEqual(renderer.ids_at([(1, 1)]), [-1])
        self.assertIs(ctx.fbo, previous)
        self.assertEqual(ctx.viewport, (3, 5, 800, 600))

    def test_unwritten_read_cannot_reuse_arbitrary_bytes(self):
        renderer, ctx, previous = self.fixture(unwritten=True)
        self.assertEqual(renderer.pick(1, 1), (-1, None, False))
        self.assertEqual(renderer.read_ids(), (None, None))
        self.assertIsNone(renderer.read_depth())
        self.assertIs(ctx.fbo, previous)


if __name__ == "__main__":
    unittest.main()
