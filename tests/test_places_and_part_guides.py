"""Back/Forward place history and the model part guides (no Qt, no model files)."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ui.places import PlaceHistory
from app.viewer import part_guide


class PlaceHistoryTests(unittest.TestCase):
    def test_back_forward_and_branching(self):
        h = PlaceHistory()
        for name in "abc":
            self.assertTrue(h.push(name, name.upper()))
        self.assertFalse(h.push("c", "C again"))          # the same place only refreshes its label
        self.assertEqual(h.label(-1), "B")
        self.assertEqual(h.go(-1), "b")
        self.assertEqual(h.go(-1), "a")
        self.assertIsNone(h.go(-1))
        self.assertEqual(h.label(1), "B")
        h.push("d", "D")                                   # a new place drops the forward branch
        self.assertFalse(h.can_go(1))
        self.assertEqual([label for _, label, _ in h.recent()], ["D", "A"])

    def test_recent_marks_current_and_jump(self):
        h = PlaceHistory()
        for i in range(5):
            h.push(i, f"P{i}")
        self.assertEqual(h.jump(1), 1)
        self.assertEqual([current for _, _, current in h.recent()], [False, False, False, True, False])
        self.assertIsNone(h.jump(9))

    def test_length_is_bounded(self):
        h = PlaceHistory()
        for i in range(PlaceHistory.LIMIT + 10):
            h.push(i, str(i))
        self.assertEqual(len(h.entries), PlaceHistory.LIMIT)
        self.assertEqual(h.entries[-1][0], PlaceHistory.LIMIT + 9)


class PartGuideTests(unittest.TestCase):
    def guide(self, data, tissues=None):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "m.json").write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
            with patch.object(part_guide, "GUIDE_DIR", Path(tmp)):
                return part_guide.load_part_guide("m", tissues)

    def test_guide_paths_titles_and_structure_notes(self):
        g = self.guide({"tree": [{"path": ["kidney", "Blood vessels"], "groups": ["Gross / renal artery"]},
                                 {"path": ["Adrenal gland"], "groups": ["Gross / adrenal capsule", "Gross / renal artery"]}],
                        "titles": {"Gross / renal artery": "Renal artery"},
                        "groups": {"Gross / adrenal capsule": {"description": "Capsule of the gland.",
                                                               "replace_part_descriptions": True,
                                                               "clinical": [["Title", "Text"], ["bad"]],
                                                               "histology": ["adrenal", "unknown"]}}},
                       tissues={"adrenal"})
        self.assertEqual(g.path("Gross / renal artery"), (("Kidney", "Blood vessels"), "Renal artery"))
        self.assertEqual(g.order, ["Gross / renal artery", "Gross / adrenal capsule"])   # first placement wins
        notes = g.group("Gross / adrenal capsule")
        self.assertTrue(notes.replace_part_descriptions)
        self.assertEqual(notes.clinical, [("Title", "Text")])
        self.assertEqual(notes.histology, ["adrenal"])
        self.assertEqual(g.group("missing").clinical, [])

    def test_without_a_guide_keys_nest_by_their_own_segments(self):
        g = self.guide("not json")
        self.assertEqual(g.path("Gross / renal capsule"), (("Gross",), "Renal capsule"))
        self.assertEqual(g.path("Nephron / Macula densa"), (("Nephron",), "Macula densa"))
        self.assertEqual(g.path("Parts", "Parts"), ((), "Parts"))
        self.assertEqual(g.path("muscle_layer", "Muscle layer"), ((), "Muscle layer"))

    def test_replacement_needs_a_description(self):
        g = self.guide({"groups": {"A": {"description": " ", "replace_part_descriptions": True}}})
        self.assertFalse(g.group("A").replace_part_descriptions)

    def test_a_part_description_comes_before_its_group(self):
        g = self.guide({"groups": {"Taste": {"description": "Taste buds are ...", "replace_part_descriptions": True},
                                   "Plain": {"description": "Group text."}},
                        "parts": [{"keys": ["Basal taste cells", "Basal taste cells 2"], "description": "Basal cells are ..."},
                                  {"keys": ["Taste pore"], "description": " "}, "bad", {"keys": "x", "description": "y"}]})
        part = lambda key, group, own="": SimpleNamespace(key=key, group=group, description=own)
        self.assertEqual(g.description(part("Basal taste cells 2", "Taste", "Build note")), "Basal cells are ...")
        self.assertEqual(g.description(part("Taste pore", "Taste", "Build note")), "Taste buds are ...")
        self.assertEqual(g.description(part("Other", "Plain", "Own text.")), "Own text.")
        self.assertEqual(g.description(part("Other", "Plain")), "Group text.")
        self.assertEqual(g.description(part("Other", "Missing")), "")

    def test_kidney_no_longer_carries_the_adrenal_gland(self):
        g = part_guide.load_part_guide("kidney_nephron")
        self.assertIn("Gross / adrenal capsule", g.excluded_groups)
        self.assertIn("Source section / Suprarenal gland", g.excluded_groups)
        self.assertIn("Suprarenal gland", g.excluded_targets)
        self.assertIn("adrenal", g.excluded_histology)
        self.assertFalse(set(g.order) & g.excluded_groups)

    def test_shipped_guides_are_valid(self):
        for path in sorted(part_guide.GUIDE_DIR.glob("*.json")):
            with self.subTest(path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(data.get("tree"), list)
                placed = [key for node in data["tree"] for key in node["groups"]]
                self.assertEqual(len(placed), len(set(placed)), "a group is placed twice")


if __name__ == "__main__":
    unittest.main()
