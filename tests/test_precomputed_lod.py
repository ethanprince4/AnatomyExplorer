"""Portable LOD must match exact native layout without changing full geometry."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from app.viewer import lod, precomputed_lod


class PrecomputedLodTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.glb'
        self.viewer = self.root / 'source.viewer.json'
        self.source.write_bytes(b'exact immutable geometry binding fixture')
        self.viewer.write_bytes(b'{"start_view":"Overview"}')
        grid = np.array([[x * .0001, y * .0001, 0] for y in range(61) for x in range(61)], dtype=np.float32)
        faces = []
        for y in range(60):
            for x in range(60):
                a = y * 61 + x
                faces.extend([[a, a + 1, a + 61], [a + 1, a + 62, a + 61]])
        vertices = np.c_[grid, np.zeros((len(grid), 16), dtype=np.float32)].astype(np.float32)
        part = SimpleNamespace(id=1, name='dense-software-fixture', first=0, count=len(faces)*3,
            vertex_base=0, vertex_count=len(grid), look=SimpleNamespace(texture=None))
        self.model = SimpleNamespace(vertices=vertices, indices=np.asarray(faces, np.uint32).reshape(-1),
            parts=[part], bounds_min=np.array([0., 0., 0.]), bounds_max=np.array([2., 2., 2.]),
            anim_vertices=None, part_matrix=lambda part: np.eye(4))
        self.expected = lod.build(self.model)
        self.assertIn(1, self.expected)

    def bundle(self, changes=None, corrupt_indices=False):
        arrays, parts = {}, []
        for part_id, levels in self.expected.items():
            keys = []
            for index, values in enumerate(levels.indices):
                key = 'part' + str(part_id) + '_level' + str(index)
                keys.append(key)
                arrays[key] = values.copy()
            parts.append({'part_id': part_id, 'cells': levels.cells.tolist(), 'arrays': keys})
        if corrupt_indices:
            arrays[parts[0]['arrays'][0]][0] = len(self.model.vertices)
        metadata = {'schema': precomputed_lod.SCHEMA, 'source_sha256': precomputed_lod.digest(self.source),
            'companion_sha256': {'viewer': precomputed_lod.digest(self.viewer)},
            'algorithm_constants': precomputed_lod.constants(), 'vertex_count': len(self.model.vertices),
            'index_count': int(self.model.indices.size), 'part_layout': precomputed_lod.part_layout(self.model), 'parts': parts}
        metadata.update(changes or {})
        arrays['meta'] = np.frombuffer(json.dumps(metadata).encode(), dtype=np.uint8)
        path = self.root / 'bundle.npz'
        np.savez(path, **arrays)
        return path

    def test_exact_levels_load_without_mutating_full_geometry(self):
        before_v, before_i = self.model.vertices.copy(), self.model.indices.copy()
        actual = precomputed_lod.load(self.model, self.bundle(), self.source, {'viewer': self.viewer})
        for part_id, expected in self.expected.items():
            np.testing.assert_array_equal(actual[part_id].cells, expected.cells)
            for actual_level, expected_level in zip(actual[part_id].indices, expected.indices):
                np.testing.assert_array_equal(actual_level, expected_level)
        np.testing.assert_array_equal(self.model.vertices, before_v)
        np.testing.assert_array_equal(self.model.indices, before_i)

    def test_stale_viewer_geometry_constants_and_layout_rejected(self):
        for changes in ({'source_sha256': '0'*64}, {'companion_sha256': {'viewer': '0'*64}},
                        {'algorithm_constants': {}}, {'part_layout': []}):
            with self.assertRaises(ValueError):
                precomputed_lod.load(self.model, self.bundle(changes), self.source, {'viewer': self.viewer})

    def test_cross_primitive_triangle_reference_rejected(self):
        with self.assertRaisesRegex(ValueError, 'vertex range'):
            precomputed_lod.load(self.model, self.bundle(corrupt_indices=True), self.source, {'viewer': self.viewer})


if __name__ == '__main__':
    unittest.main()
