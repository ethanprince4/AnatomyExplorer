"""A radiology case's image labels also name its 3D reference, numbered as on the scan (no Qt window, no geometry)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.main_window import MainWindow, SECTION_SYSTEMS


def case(*labels):
    return SimpleNamespace(labels=[SimpleNamespace(text=lab[0], structures=lab[1], side=lab[2],
                                                   at=lab[3] if len(lab) > 3 else None) for lab in labels])


class ReferenceLabelTests(unittest.TestCase):
    def groups(self, c, scene, side=""):
        fake = SimpleNamespace(ds=None, lesson_resolver=None)
        lookup = {"Trachea": [3], "Right lung": [7, 8], "Nothing": []}
        with patch("app.radiology_reference.resolve_reference",
                   side_effect=lambda _ds, _res, names, _side: sorted(i for n in names for i in lookup.get(n, []))):
            return MainWindow._radiology_label_groups(fake, c, scene, side)

    def test_image_labels_are_numbered_as_on_the_scan(self):
        c = case(("Trachea", ["Trachea"], ""), ("Gone", ["Nothing"], ""), ("Right lung", ["Right lung"], "Right"))
        self.assertEqual(self.groups(c, {}), [("1  Trachea", [3], False), ("3  Right lung", [7, 8], False)])

    def test_authored_reference_labels_win_and_models_name_their_own_parts(self):
        c = case(("Trachea", ["Trachea"], ""))
        self.assertEqual(self.groups(c, {"reference_labels": [{"text": "Airway", "structures": ["Trachea"]}]}),
                         [("Airway", [3], False)])
        self.assertIsNone(self.groups(c, {"micro": "kidney_nephron", "micro_focus": ["Renal artery"]}))
        self.assertIsNone(self.groups(case(("Gone", ["Nothing"], "")), {}))

    def test_pinned_labels_carry_their_point_and_may_share_a_structure(self):
        c = case(("Head of femur", ["Trachea"], "", (1.0, 2.0, 3.0)),
                 ("Greater trochanter", ["Trachea"], "", (4.0, 5.0, 6.0)), ("Femur", ["Trachea"], ""))
        self.assertEqual(self.groups(c, {}), [("1  Head of femur", [3], False, (1.0, 2.0, 3.0)),
                                              ("2  Greater trochanter", [3], False, (4.0, 5.0, 6.0)),
                                              ("3  Femur", [3], False)])

    def test_sections_include_every_tissue_system(self):
        self.assertTrue({"skeletal", "muscular", "cardiovascular", "visceral", "nervous"} <= SECTION_SYSTEMS)
        self.assertFalse({"attachments", "reference", "regions"} & SECTION_SYSTEMS)


class PinVisibilityTests(unittest.TestCase):
    """A pinned label is drawn at its point only where one of its structures is what the view shows there."""

    def viewport(self):
        import numpy as np
        from app.viewport import Viewport
        vp = Viewport.__new__(Viewport)
        vp.renderer = SimpleNamespace(last_vp=np.eye(4), size=(100, 100))
        return vp

    def ids(self):
        import numpy as np
        ids = np.zeros((50, 50), dtype=np.int32)       # step 2: 100 x 100 pixels, rows bottom-up
        ids[:, 25:] = 4                                 # structure 3 fills the right half
        ids[40:, :25] = 9                               # structure 8 fills the top-left corner
        return ids

    def test_visible_point_on_its_structure(self):
        self.assertEqual(self.viewport()._visible_pin((0.5, 0.0, 0.0), [3], self.ids(), 2), 3)
        self.assertEqual(self.viewport()._visible_pin((-0.5, 0.9, 0.0), [8, 3], self.ids(), 2), 8)

    def test_covered_or_off_screen_point_is_not_drawn(self):
        self.assertIsNone(self.viewport()._visible_pin((-0.5, 0.0, 0.0), [3], self.ids(), 2))   # empty there
        self.assertIsNone(self.viewport()._visible_pin((-0.5, 0.9, 0.0), [3], self.ids(), 2))   # structure 8 covers it
        self.assertIsNone(self.viewport()._visible_pin((1.5, 0.0, 0.0), [3], self.ids(), 2))    # off screen


if __name__ == "__main__":
    unittest.main()
