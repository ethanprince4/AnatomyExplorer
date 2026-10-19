"""The opt-in GLB start-visibility sidecar contract for ModelView reset."""
from types import SimpleNamespace
import unittest

import numpy as np

from app.ui.model_view import ModelView, tissue_opacity


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
    def cardiac_view(self):
        view = FakeView()
        view.entry = SimpleNamespace(id="cardiac_muscle")
        look = SimpleNamespace(alpha=1.0, translucent=False)
        view.vmodel.kind = "procedural"
        view.vmodel.items = [
            SimpleNamespace(key="endomysium__001", group="Endomysium", bulk=False,
                            parts=[SimpleNamespace(look=look)]),
            SimpleNamespace(key="cardiomyocyte__001", group="Cardiomyocyte", bulk=False, parts=[]),
            SimpleNamespace(key="capillary__001", group="Capillaries", bulk=False, parts=[]),
        ]
        return view, look

    def test_cardiac_reset_restores_translucent_sleeves_and_solid_cells(self):
        view, look = self.cardiac_view()
        view.state.opaque_materials = True
        ModelView._fully_visible(view)

        np.testing.assert_allclose(view.state.part_alpha, [0.24, 1.0, 1.0])
        self.assertFalse(view.state.opaque_materials)
        self.assertEqual(look.alpha, 1.0)
        layers, alpha = tissue_opacity(view.vmodel, view.entry.id, 50)
        np.testing.assert_array_equal(layers, [True, False, False])
        np.testing.assert_allclose(alpha, [0.12, 1.0, 1.0])

    def test_cardiac_material_alpha_is_preserved_when_already_authored(self):
        view, look = self.cardiac_view()
        look.alpha = 0.35
        look.translucent = True
        _, alpha = tissue_opacity(view.vmodel, view.entry.id)
        np.testing.assert_allclose(alpha, 1.0)
        self.assertEqual(look.alpha, 0.35)

    def test_procedural_reset_preserves_authored_material_transparency(self):
        view = FakeView()
        view.vmodel.kind = "procedural"
        view.state.opaque_materials = True
        ModelView._fully_visible(view)
        self.assertFalse(view.state.opaque_materials)
        np.testing.assert_allclose(view.state.part_alpha, 1.0)

    def test_procedural_recipe_start_mask_is_reapplied_only_for_home_reset(self):
        view=FakeView({'start_view':'Kidney'},{'Kidney':{'hidden':['nephron','section']}})
        view.vmodel.kind='procedural'
        view.vmodel.items=[SimpleNamespace(key=key) for key in ('kidney','nephron','section')]
        ModelView._fully_visible(view,authored_start=True)
        np.testing.assert_array_equal(view.state.hidden,[False,True,True])
        # A later lesson focus can clear filters before applying its own mask.
        ModelView._fully_visible(view)
        np.testing.assert_array_equal(view.state.hidden,False)

    def test_runtime_opening_keeps_the_procedural_start_composition(self):
        view=FakeView({'start_view':'Kidney'},{'Kidney':{'hidden':['nephron','section']}})
        view.vmodel.kind='procedural'
        view.vmodel.items=[SimpleNamespace(key=key) for key in ('kidney','nephron','section')]
        view.runtime_session=SimpleNamespace(opening=lambda:None)
        view._fully_visible=lambda **kwargs:ModelView._fully_visible(view,**kwargs)
        view.state.clear_selection=lambda:None
        view._show_selection=lambda:None
        ModelView._runtime_opening(view)
        np.testing.assert_array_equal(view.state.hidden,[False,True,True])
        self.assertTrue(view.runtime_opening_done)

    def test_cardiac_lesson_reset_reapplies_translucent_defaults(self):
        view, _ = self.cardiac_view()
        view.state.clear_selection = lambda: None
        view.state.select = lambda ids: setattr(view.state, "selected", ids)
        view._fully_visible = lambda: ModelView._fully_visible(view)
        view.reset_view = view._fully_visible
        view.part_ids = lambda names: ([1], [])
        view._show_selection = lambda: None

        self.assertEqual(ModelView.show_lesson_parts(view, ["Cardiomyocytes"]), [])
        np.testing.assert_allclose(view.state.part_alpha, [0.24, 1.0, 1.0])
        self.assertEqual(view.state.selected, [1])
        self.assertIsNone(view.state.ghost_focus)

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
