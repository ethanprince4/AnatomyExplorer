"""Binding/restoration regression; native GPU controls remain required."""
import importlib.util
import unittest
from types import SimpleNamespace


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in
                         ("moderngl", "numpy", "PySide6")), "renderer dependencies required")
class ReadbackBindingTests(unittest.TestCase):
    def fixture(self, encoded=3922, error=False, write=True):
        import moderngl
        from app.renderer import Renderer
        ctx = SimpleNamespace(fbo=None, viewport=(3, 5, 800, 600))

        class Fbo:
            def __init__(self, viewport):
                self.viewport = viewport

            def use(self):
                ctx.fbo = self
                ctx.viewport = self.viewport

            def read_into(self, destination, **kwargs):
                if error:
                    raise moderngl.Error("synthetic read error")
                if write:
                    # Models the observed Apple normalized-DRAW clamp.
                    destination[0] = encoded if ctx.fbo is self else min(encoded, 1)

        previous = Fbo((0, 0, 800, 600))
        ctx.fbo = previous
        gbuffer = Fbo((0, 0, 64, 64))
        renderer = object.__new__(Renderer)
        renderer.ctx = ctx
        renderer.gbuffer = gbuffer
        renderer.size = (64, 64)
        renderer.frame_ok = True
        renderer.ds = SimpleNamespace(n=3922)
        return renderer, ctx, previous

    def test_known_ids_survive_normalized_output_target(self):
        for encoded in (2, 257, 3922):
            with self.subTest(encoded=encoded):
                renderer, ctx, previous = self.fixture(encoded)
                self.assertEqual(renderer.pick(32, 32), encoded - 1)
                self.assertIs(ctx.fbo, previous)
                self.assertEqual(ctx.viewport, (3, 5, 800, 600))

    def test_background_stays_unselected(self):
        renderer, ctx, previous = self.fixture(0)
        self.assertEqual(renderer.pick(0, 63), -1)
        self.assertIs(ctx.fbo, previous)

    def test_read_error_restores_target_and_viewport(self):
        renderer, ctx, previous = self.fixture(error=True)
        self.assertIsNone(renderer._read_float(32, 32, 2))
        self.assertIs(ctx.fbo, previous)
        self.assertEqual(ctx.viewport, (3, 5, 800, 600))

    def test_unwritten_read_cannot_select_arbitrary_structure(self):
        renderer, ctx, previous = self.fixture(write=False)
        self.assertEqual(renderer.pick(32, 32), -1)
        self.assertIs(ctx.fbo, previous)

    def test_depth_read_remains_unmodified(self):
        renderer, ctx, previous = self.fixture(0.5)
        self.assertEqual(renderer._read_float(32, 32, -1), 0.5)
        self.assertIs(ctx.fbo, previous)
        self.assertEqual(ctx.viewport, (3, 5, 800, 600))


if __name__ == "__main__":
    unittest.main()
