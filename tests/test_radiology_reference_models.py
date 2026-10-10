"""Radiology cases that open a reference model: every named part resolves, and the camera frames them in the panel."""
import math
import unittest

import numpy as np

from app.load_control import LoadToken
from app.radiology import load_cases
from app.radiology_reference import framing_core
from app.viewer.camera import OrbitCamera
from app.viewer.catalog import load_catalog


class ReferenceModelLookupTests(unittest.TestCase):
    def test_every_case_part_name_resolves_in_its_model(self):
        cases = [c for c in load_cases(include_missing=True) if c.scene.get("micro") and c.scene.get("micro_focus")]
        self.assertGreaterEqual(len(cases), 12)
        catalog = load_catalog()
        models = {}
        for model_id in sorted({c.scene["micro"] for c in cases}):
            entry = catalog.get(model_id)
            self.assertIsNotNone(entry, model_id)
            model = entry.prepare_cpu(LoadToken())
            models[model_id] = (model, getattr(model, "runtime_entry", entry))
        for case in cases:
            model, entry = models[case.scene["micro"]]
            for key in ("micro_focus", "micro_context"):
                ids, missing = entry.resolve(model, case.scene.get(key, []))
                self.assertEqual(missing, [], f"{case.id} {key}")
                if key == "micro_focus":
                    self.assertTrue(ids, case.id)


class FramingTests(unittest.TestCase):
    @staticmethod
    def half_extent(camera, bmin, bmax, aspect):
        """Fraction of the half-width and half-height of the frame that the box's projection fills (ortho)."""
        back = camera.forward_dir()
        right, up, _ = camera.basis()
        lo, hi = np.asarray(bmin, float), np.asarray(bmax, float)
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        rel = corners - camera.target
        hx, hy = camera.ortho_halves(aspect)
        return np.abs(rel @ right).max() / hx, np.abs(rel @ up).max() / hy

    def test_portrait_orthographic_fit_covers_width_and_height(self):
        for aspect in (0.4, 0.58, 0.9, 1.0, 1.6):
            for box in (((0, 0, 0), (1.8, 1.2, 1.0)), ((0, 0, 0), (0.3, 2.0, 0.3))):
                camera = OrbitCamera()
                camera.ortho = True
                camera.frame_bounds(*box, aspect, yaw=0.0, pitch=0.0, duration=0.0)
                fx, fy = self.half_extent(camera, *box, aspect)
                self.assertLessEqual(max(fx, fy), 1.0, (aspect, box))
                if aspect < 1.0:
                    self.assertGreater(max(fx, fy), 0.8, (aspect, box))      # and it is not left small

    def test_landscape_orthographic_fit_is_unchanged(self):
        camera = OrbitCamera()
        camera.ortho = True
        camera.frame_bounds((0, 0, 0), (2, 1, 1), 1.5, yaw=0.0, pitch=0.0, duration=0.0)
        self.assertAlmostEqual(camera.ortho_width, math.sqrt(6) / 2 * 2.2)

    def test_framing_core_drops_a_detached_part_only(self):
        rng = np.random.default_rng(1)
        centres = rng.normal(0, 1000, (30, 3))
        ids = list(range(30))
        self.assertEqual(framing_core(ids, centres), ids)
        centres[7] = (27000, 0, 0)
        self.assertEqual(framing_core(ids, centres), [i for i in ids if i != 7])
        self.assertEqual(framing_core([1, 2, 3], [(0, 0, 0), (9e5, 0, 0), (1, 0, 0)]), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
