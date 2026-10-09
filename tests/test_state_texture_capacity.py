"""The state texture holds 65,536 structures: packing, the lookups the shaders use, and per-structure writes."""
import re
import unittest
from types import SimpleNamespace

import numpy as np

from app import shaders
from app.renderer import Renderer
from app.state import (F_HOVERED, F_SELECTED, F_VISIBLE, MAX_STRUCTURES, STATE_TEX_WIDTH, SceneState,
                       state_rows, state_texel)


def fake_dataset(n):
    return SimpleNamespace(
        n=n, systems=[{"default_visible": True, "color": (0.5, 0.2, 0.1)}, {"default_visible": True, "color": (0.1, 0.2, 0.9)}],
        system_of=(np.arange(n) % 2).astype(int), subsystem_default=[], subsystem_of=np.full(n, -1),
        regions=[], region_mask=np.zeros(n, dtype=np.int64), structures=[{"i_count": 3}] * n)


class FakeTexture:
    def __init__(self):
        self.data = None
        self.pieces = []

    def write(self, data, viewport=None):
        if viewport is None:
            self.data = bytes(data)
        else:
            self.pieces.append((viewport, bytes(data)))


def shader_fetch(packed, obj, row):
    """What GEOMETRY_VS does: texelFetch(u_state, ivec2(obj & 4095, (obj >> 12) * 2 + row))."""
    return packed[((obj >> 12) * 2) + row, obj & 4095]


class StateTextureCapacity(unittest.TestCase):
    def build(self, n):
        state = SceneState(fake_dataset(n), {})
        state.hidden[7] = True
        state.selected = [min(4097, n - 2), n - 1]
        state.hovered = min(4096, n - 3)
        state.system_alpha = np.array([1.0, 0.5], dtype=np.float32)
        return state, state.build_texture()

    def renderer_stub(self, n):
        stub = SimpleNamespace(ds=fake_dataset(n), state_blocks=state_rows(n), state_tex=FakeTexture())
        return stub

    def test_limits(self):
        self.assertGreaterEqual(MAX_STRUCTURES, 65536)
        self.assertEqual(state_rows(1), 1)
        self.assertEqual(state_rows(4096), 1)
        self.assertEqual(state_rows(4097), 2)
        self.assertEqual(state_rows(65536), 16)
        self.assertEqual(state_texel(4097), (1, 2))
        self.assertIn("obj & 4095", shaders.GEOMETRY_VS)
        self.assertIn("(obj >> 12) * 2", shaders.GEOMETRY_VS)

    def test_state_for_5000_and_65536_structures(self):
        for n in (4000, 5000, 20000, 65536):
            with self.subTest(n=n):
                state, tex = self.build(n)
                self.assertEqual(tex.shape, (2, state_rows(n) * STATE_TEX_WIDTH, 4))
                stub = self.renderer_stub(n)
                Renderer.update_state(stub, tex)
                packed = np.frombuffer(stub.state_tex.data, dtype=np.float32).reshape(
                    stub.state_blocks * 2, STATE_TEX_WIDTH, 4)
                self.assertTrue(np.array_equal(stub._state_flags, tex[0, :n, 3].astype(np.int32)))
                for sid in sorted(s for s in {0, 6, 7, 4095, 4096, 4097, n // 2, n - 2, n - 1} if s < n):
                    colour = shader_fetch(packed, sid, 0)
                    alpha = shader_fetch(packed, sid, 1)
                    flags = int(colour[3] + 0.5)
                    self.assertEqual(bool(flags & F_VISIBLE), sid != 7, sid)
                    self.assertEqual(bool(flags & F_SELECTED), sid in (min(4097, n - 2), n - 1), sid)
                    self.assertEqual(bool(flags & F_HOVERED), sid == min(4096, n - 3), sid)
                    self.assertEqual(alpha[0], 1.0 if sid % 2 == 0 else 0.5, sid)
                # every structure, vectorised
                sid = np.arange(n)
                self.assertTrue(np.array_equal(packed[(sid >> 12) * 2, sid & 4095], tex[0, :n]))
                self.assertTrue(np.array_equal(packed[(sid >> 12) * 2 + 1, sid & 4095], tex[1, :n]))

    def test_single_structure_write_address(self):
        n = 6000
        stub = self.renderer_stub(n)
        Renderer.update_state(stub, np.zeros((2, 2 * STATE_TEX_WIDTH, 4), np.float32))
        packed = np.zeros((4, STATE_TEX_WIDTH, 4), np.float32)
        x, y = state_texel(5000)
        self.assertEqual((x, y), (904, 2))
        packed[y, x] = 9
        self.assertEqual(shader_fetch(packed, 5000, 0)[0], 9)

    def test_old_single_block_layout_is_unchanged(self):
        n = 100
        state, tex = self.build(n)
        stub = self.renderer_stub(n)
        Renderer.update_state(stub, tex)
        packed = np.frombuffer(stub.state_tex.data, dtype=np.float32).reshape(2, STATE_TEX_WIDTH, 4)
        self.assertTrue(np.array_equal(packed, tex))


if __name__ == "__main__":
    unittest.main()
