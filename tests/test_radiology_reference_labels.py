"""A radiology case's image labels also name its 3D reference, numbered as on the scan (no Qt window, no geometry)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.main_window import MainWindow, SECTION_SYSTEMS


def case(*labels):
    return SimpleNamespace(labels=[SimpleNamespace(text=t, structures=s, side=side) for t, s, side in labels])


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

    def test_sections_include_every_tissue_system(self):
        self.assertTrue({"skeletal", "muscular", "cardiovascular", "visceral", "nervous"} <= SECTION_SYSTEMS)
        self.assertFalse({"attachments", "reference", "regions"} & SECTION_SYSTEMS)


if __name__ == "__main__":
    unittest.main()
