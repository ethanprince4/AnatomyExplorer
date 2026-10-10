"""Regression: Renderer._gather must not switch the scissor test on for the caller's framebuffer; no GL context.

moderngl reports Framebuffer.scissor as the full-size box even when the test is off, and setting it turns the test
on. _gather used to write that box back, which enabled a scissor the size of the window at its first paint (the
framebuffer is detected then) and clipped every later frame to that corner. The fakes below follow moderngl: use()
applies the framebuffer's own state, the ctx.scissor setter enables the test on the bound framebuffer.
"""
import unittest
from types import SimpleNamespace

import numpy as np

from app.renderer import Renderer


class FakeFbo:
    def __init__(self, size, ctx):
        self.size, self.ctx = size, ctx
        self.viewport = (0, 0, *size)
        self._box = (0, 0, *size)
        self.scissor_enabled = False
        self.gl_scissor_enabled = None

    @property
    def scissor(self):
        return self._box

    @scissor.setter
    def scissor(self, value):
        self.scissor_enabled = value is not None
        self._box = (0, 0, *self.size) if value is None else tuple(value)

    def use(self):
        self.ctx.fbo = self
        self.ctx.gl_scissor = self.scissor_enabled

    def read(self, components=4, dtype="f4"):
        return np.zeros((Renderer.GATHER_MAX, 4), np.float32).tobytes()


class FakeCtx:
    def __init__(self):
        self.fbo = None
        self.gl_scissor = False

    @property
    def viewport(self):
        return self.fbo.viewport

    @viewport.setter
    def viewport(self, value):
        self.fbo.viewport = tuple(value)

    @property
    def scissor(self):
        return self.fbo.scissor

    @scissor.setter
    def scissor(self, value):
        self.fbo.scissor = value
        self.gl_scissor = value is not None


class Dummy:
    def use(self, *_):
        pass

    def render(self, **_):
        pass


class GatherScissorTests(unittest.TestCase):
    def make(self):
        r = object.__new__(Renderer)
        r.ctx = FakeCtx()
        r.frame_ok, r.size = True, (924, 922)
        r.id_tex = r.depth_tex = r.gather_vao = Dummy()
        r.p_gather = {"u_pts": SimpleNamespace(write=lambda b: None)}
        r.gather_fbo = FakeFbo((Renderer.GATHER_MAX, 1), r.ctx)
        return r

    def test_gather_leaves_scissor_off_on_the_window(self):
        r = self.make()
        window = FakeFbo((660, 602), r.ctx)        # detect_framebuffer saw the small first-paint size
        window.use()
        window.viewport = (0, 0, 924, 922)
        r._gather(np.array([[10, 10], [500, 400]]))
        self.assertIs(r.ctx.fbo, window)
        self.assertFalse(window.scissor_enabled)
        self.assertFalse(r.ctx.gl_scissor)
        self.assertEqual(window.viewport, (0, 0, 924, 922))

    def test_gather_keeps_a_scissor_the_caller_had_on(self):
        r = self.make()
        window = FakeFbo((924, 922), r.ctx)
        window.use()
        window.scissor = (5, 5, 100, 100)
        r._gather(np.array([[10, 10]]))
        self.assertTrue(window.scissor_enabled)
        self.assertEqual(window.scissor, (5, 5, 100, 100))
        self.assertTrue(r.ctx.gl_scissor)


if __name__ == "__main__":
    unittest.main()
