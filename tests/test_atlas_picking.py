"""Non-GPU regressions for logical/backing mapping and failed driver readback."""
import math
import unittest
from types import SimpleNamespace

import moderngl
import numpy as np
from PySide6.QtCore import QPointF

from app.renderer import Renderer
from app.viewport import Viewport


class PickingMathTests(unittest.TestCase):
    def viewport(self, width, height, dpr, scale):
        size = (max(int(round(width*dpr)*scale), 2), max(int(round(height*dpr)*scale), 2))
        return SimpleNamespace(width=lambda: width, height=lambda: height,
                               renderer=SimpleNamespace(size=size))

    def test_pixel_edges_at_retina_and_fractional_scaling(self):
        for dpr in (1, 1.25, 1.5, 2, 2.5):
            for scale in (0.5, 0.67, 0.75, 1):
                view = self.viewport(641, 479, dpr, scale)
                w, h = view.renderer.size
                with self.subTest(dpr=dpr, scale=scale):
                    self.assertEqual(Viewport._gl_xy(view, QPointF(0, 0)), (0, h-1))
                    self.assertEqual(Viewport._gl_xy(view, QPointF(640.999, 478.999)), (w-1, 0))
                    self.assertEqual(Viewport._gl_xy(view, QPointF(641, 479)), (w, -1))
                    self.assertEqual(Viewport._gl_xy(view, QPointF(-0.1, -0.1)), (-1, h))

    def test_each_axis_uses_actual_buffer_size(self):
        view = self.viewport(641, 479, 1.5, 0.67)
        w, h = view.renderer.size
        for px, py in ((0.5, 0.5), (100.2, 113.7), (317.1, 470.2)):
            self.assertEqual(Viewport._gl_xy(view, QPointF(px, py)),
                             (math.floor(px*w/641), h-1-math.floor(py*h/479)))

    def test_stale_frame_is_refreshed_before_read(self):
        view = SimpleNamespace(_state_dirty=False, _pick_frame_key="old", _frame_key=lambda: "new")
        rendered = []
        view.paintGL = lambda: rendered.append(True)
        Viewport._ensure_pick_frame(view)
        self.assertEqual(len(rendered), 1)
        view._pick_frame_key = "new"
        Viewport._ensure_pick_frame(view)
        self.assertEqual(len(rendered), 1)
        view._state_dirty = True
        Viewport._ensure_pick_frame(view)
        self.assertEqual(len(rendered), 2)


class ReadbackTests(unittest.TestCase):
    def renderer(self, value=None, error=False):
        renderer = Renderer.__new__(Renderer)
        renderer.size = (100, 100)
        renderer.frame_ok = True
        renderer.ds = SimpleNamespace(n=10)
        renderer.last_vp = np.identity(4)

        def read_into(buffer, **kwargs):
            if error:
                raise moderngl.Error("simulated driver failure")
            if value is not None:
                buffer[0] = value
        ctx = SimpleNamespace(fbo=None, viewport=(0, 0, 100, 100))
        def bind():
            ctx.fbo = renderer.gbuffer
        renderer.gbuffer = SimpleNamespace(read_into=read_into, use=bind)
        ctx.fbo = renderer.gbuffer
        renderer.ctx = ctx
        return renderer

    def test_failed_or_invalid_read_never_returns_stale_id(self):
        for value in (None, np.nan, np.inf, -np.inf, -1, 0, 2.5, 11):
            with self.subTest(value=value):
                self.assertEqual(self.renderer(value).pick(50, 50), -1)
        self.assertEqual(self.renderer(error=True).pick(50, 50), -1)

    def test_id_endpoints_and_outside_buffer(self):
        self.assertEqual(self.renderer(1).pick(0, 0), 0)
        self.assertEqual(self.renderer(10).pick(99, 99), 9)
        self.assertEqual(self.renderer(10).pick(100, 99), -1)
        self.assertEqual(self.renderer(10).pick(-1, 99), -1)

    def test_depth_failure_does_not_invent_measurements(self):
        for value in (None, np.nan, np.inf, -0.1, 1, 2):
            with self.subTest(value=value):
                self.assertIsNone(self.renderer(value).world_at(50, 50))
        self.assertIsNone(self.renderer(error=True).world_at(50, 50))
        self.assertTrue(np.isfinite(self.renderer(0.5).world_at(50, 50)).all())


if __name__ == "__main__":
    unittest.main()
