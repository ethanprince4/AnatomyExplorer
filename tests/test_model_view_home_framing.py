"""Home-view framing leaves named anatomy views and source metadata untouched."""
from types import SimpleNamespace
import unittest

import numpy as np

from app.ui.model_view import ModelView, model_intro


class FakeCamera:
    min_distance = 0.0
    yaw = 0.7
    pitch = 0.2
    animating = False

    def fit_distance(self, radius, _aspect):
        self.fitted_radius = radius
        return radius * 2.0

    def ortho_fit_width(self, _lo, _hi, _aspect, _yaw, _pitch, radius):
        return radius * 2.2

    def animate_to(self, target, distance, yaw, pitch, duration, ortho_width=None):
        self.pose = (np.asarray(target), distance, yaw, pitch, duration, ortho_width)


class HomeFramingTests(unittest.TestCase):
    def test_home_fit_uses_visible_bounds_and_adds_safe_margin(self):
        camera = FakeCamera()
        viewport = SimpleNamespace(
            camera=camera,
            scene_bounds=lambda: (np.array([-2.0, -1.0, -3.0]), np.array([2.0, 1.0, 3.0])),
            aspect=lambda: 1.5,
            duration=lambda: 0.55,
            update=lambda: None,
        )

        ModelView._frame_home_composition(SimpleNamespace(gl_widget=viewport), animate=False)

        target, distance, yaw, pitch, duration, ortho_width = camera.pose
        np.testing.assert_allclose(target, [0.0, 0.0, 0.0])
        self.assertAlmostEqual(camera.fitted_radius, np.linalg.norm([4.0, 2.0, 6.0]) / 2.0 * 1.15)
        self.assertAlmostEqual(distance, camera.fitted_radius * 2.0)
        self.assertEqual((yaw, pitch, duration), (0.7, 0.2, 0.0))
        self.assertAlmostEqual(ortho_width, (np.linalg.norm([4.0, 2.0, 6.0]) / 2.0) * 2.2 * 1.15)

    def test_kidney_header_replaces_build_summary_without_mutating_source(self):
        source = "One kidney teaching bundle with preserved gross, independent section and 15x nephron views."
        entry = SimpleNamespace(id="kidney_nephron", summary=source)

        self.assertEqual(model_intro(entry), "Explore the kidney’s gross anatomy, renal vessels and nephron structures.")
        self.assertEqual(entry.summary, source)


if __name__ == "__main__":
    unittest.main()
