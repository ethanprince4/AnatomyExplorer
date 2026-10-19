"""The opt-in GLB start-visibility sidecar contract for ModelView reset."""
from types import SimpleNamespace
import unittest

import numpy as np

from app.ui.model_view import ModelView


class FakeState:
    def __init__(self, n=3):
        self.hidden = np.array([True, False, True][:n], dtype=bool)
        self.forced = np.ones(n, dtype=bool)
        self.isolated = np.ones(n, dtype=bool)
        self.ghost_focus = np.ones(n, dtype=bool)
        self.system_on = np.zeros(2, dtype=bool)
        self.subsystem_on = np.zeros(2, dtype=bool)
        self.region_on = np.zeros(2, dtype=bool)
        self.system_alpha = np.zeros(2, dtype=np.float32)
        self.part_alpha = np.zeros(n, dtype=np.float32)
        self.opaque_materials = False
        self.depth_cut = 0.4
        self.depth_band = 0.2
        self.dirty_count = 0

    def _vis_dirty(self):
        self.dirty_count += 1


class FakeView:
    def __init__(self, sidecar=None, cameras=None):
        self.vmodel = SimpleNamespace(kind="glb", sidecar=sidecar or {})
        self.vmodel.cameras = cameras or {}
        self.vmodel.items = [None, None, None]
        self.state = FakeState()
        self.gl_widget = SimpleNamespace(cut_on=True)
        self.cut = None
        self.opacity = None
        self.clear_sections_count = 0

    def clear_sections(self):
        self.clear_sections_count += 1


class ModelViewStartVisibilityTests(unittest.TestCase):
    def test_opt_in_preserves_authored_start_mask_and_clears_other_state(self):
        view = FakeView(
            {"preserve_start_visibility": True, "start_view": "Overview"},
            {"Overview": {"hidden": ["support-a", "support-b"]}},
        )
        expected_hidden = view.state.hidden.copy()

        ModelView._fully_visible(view)

        np.testing.assert_array_equal(view.state.hidden, expected_hidden)
        np.testing.assert_array_equal(view.state.forced, False)
        self.assertIsNone(view.state.isolated)
        self.assertIsNone(view.state.ghost_focus)
        np.testing.assert_array_equal(view.state.system_on, True)
        np.testing.assert_array_equal(view.state.subsystem_on, True)
        np.testing.assert_array_equal(view.state.region_on, True)
        np.testing.assert_array_equal(view.state.system_alpha, 1.0)
        np.testing.assert_array_equal(view.state.part_alpha, 1.0)
        self.assertEqual(view.state.depth_cut, 0.0)
        self.assertEqual(view.state.depth_band, 0.0)
        self.assertFalse(view.gl_widget.cut_on)
        self.assertEqual(view.clear_sections_count, 1)

    def test_missing_opt_in_keeps_historical_show_everything_behavior(self):
        view = FakeView({"start_view": "Overview"}, {"Overview": {"hidden": ["support-a"]}})

        ModelView._fully_visible(view)

        np.testing.assert_array_equal(view.state.hidden, False)
        np.testing.assert_array_equal(view.state.forced, False)
        self.assertIsNone(view.state.isolated)
        self.assertIsNone(view.state.ghost_focus)

    def test_opt_in_without_authored_start_hidden_list_falls_back_safely(self):
        view = FakeView(
            {"preserve_start_visibility": True, "start_view": "Overview"},
            {"Overview": {"position": [0, 0, 1], "target": [0, 0, 0]}},
        )

        ModelView._fully_visible(view)

        np.testing.assert_array_equal(view.state.hidden, False)


if __name__ == "__main__":
    unittest.main()
