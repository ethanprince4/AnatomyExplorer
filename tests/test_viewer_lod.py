"""Coarser levels of large parts: what they contain and when the renderer draws them."""
import unittest
from types import SimpleNamespace

import numpy as np

from app.viewer import lod
from app.viewer.renderer import Renderer


def sphere(n=100, base=0):
    """A closed-enough UV sphere of radius 1 with about 2 n^2 triangles, its vertices numbered from ``base``."""
    th, ph = np.meshgrid(np.linspace(0, np.pi, n + 1), np.linspace(0, 2 * np.pi, n + 1), indexing="ij")
    pos = np.stack([np.sin(th) * np.cos(ph), np.cos(th), np.sin(th) * np.sin(ph)], -1).reshape(-1, 3)
    i = np.arange(n)[:, None] * (n + 1) + np.arange(n)[None, :]
    quads = np.stack([i, i + n + 1, i + 1, i + 1, i + n + 1, i + n + 2], -1).reshape(-1, 3)
    return pos.astype(np.float32), quads + base


class PartLevelTests(unittest.TestCase):
    def test_levels_are_coarser_subsets_of_the_part_vertices(self):
        pos, tris = sphere()
        levels = lod.part_levels(pos, tris, 0, len(pos))
        self.assertIsNotNone(levels)
        self.assertEqual(len(levels.indices), lod.LEVELS)
        self.assertTrue(np.all(np.diff(levels.cells) >= 0))
        counts = [len(tris)] + [len(i) // 3 for i in levels.indices]
        self.assertLess(counts[1], 0.8 * counts[0])
        self.assertTrue(all(b <= a for a, b in zip(counts, counts[1:])))
        for idx in levels.indices:
            t = idx.reshape(-1, 3)
            self.assertGreaterEqual(len(t), lod.MIN_KEEP)
            self.assertTrue(np.all((t >= 0) & (t < len(pos))))
            self.assertFalse(np.any((t[:, 0] == t[:, 1]) | (t[:, 1] == t[:, 2]) | (t[:, 0] == t[:, 2])))

    def test_vertex_range_is_respected(self):
        pos, tris = sphere(base=0)
        offset = np.concatenate([np.zeros((7, 3), np.float32), pos])
        levels = lod.part_levels(offset, tris + 7, 7, len(pos))
        self.assertTrue(all(int(i.min()) >= 7 for i in levels.indices))
        # a part that indexes vertices outside its own range is left alone
        self.assertIsNone(lod.part_levels(offset, tris + 7, 8, len(pos) - 1))

    def test_small_parts_have_no_levels(self):
        pos, tris = sphere(n=20)
        self.assertLess(len(tris), lod.MIN_TRIANGLES)
        self.assertIsNone(lod.part_levels(pos, tris, 0, len(pos)))


class LevelChoiceTests(unittest.TestCase):
    def renderer(self, depth):
        r = Renderer.__new__(Renderer)
        r._lod = (np.array([0]), [5], np.array([[0.01, 0.02, 0.04, 0.08]]))
        r._spheres = (np.array([[0.0, 0.0, -depth]]), np.array([1.0]))
        r._scales = np.array([1.0])
        r._range = {5: (0, 300)}
        r._lod_range = {5: [(300, 120), (420, 60), (480, 30), (510, 15)]}
        return r

    def choose(self, depth, h=1000, tan_half=0.5):
        r = self.renderer(depth)
        r._level = r._lod_levels(np.eye(4), (tan_half, tan_half), False, h)
        return r._level.get(5, 0), r._span(SimpleNamespace(id=5))

    def test_coarsest_level_whose_cell_fits_in_a_pixel(self):
        # a pixel at depth d covers d * 2 * 0.5 / 1000 = d / 1000 world units at the part's nearest point
        self.assertEqual(self.choose(1 + 5.0), (0, (0, 300)))          # pixel 0.005: finer than every level
        self.assertEqual(self.choose(1 + 15.0), (1, (300, 120)))       # pixel 0.015
        self.assertEqual(self.choose(1 + 50.0), (3, (480, 30)))        # pixel 0.05
        self.assertEqual(self.choose(1 + 500.0), (4, (510, 15)))

    def test_camera_inside_the_part_draws_it_in_full(self):
        self.assertEqual(self.choose(0.5)[0], 0)

    def test_scaled_parts_use_their_world_size(self):
        r = self.renderer(1 + 50.0)
        r._scales = np.array([4.0])                                      # cells 0.04 .. 0.32 in the world
        self.assertEqual(r._lod_levels(np.eye(4), (0.5, 0.5), False, 1000), {5: 1})

    def test_orthographic_pixel_is_the_same_everywhere(self):
        r = self.renderer(1 + 5.0)
        self.assertEqual(r._lod_levels(np.eye(4), (10.0, 25.0), True, 1000), {5: 3})   # pixel 0.05


if __name__ == "__main__":
    unittest.main()
