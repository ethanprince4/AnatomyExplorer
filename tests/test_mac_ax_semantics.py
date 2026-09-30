"""A surviving process with a destroyed accessibility tree is not a pass."""
import runpy
import unittest
from pathlib import Path

CHECK = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                          "packaging/diagnostics/mac_ax/mac_native_probe.py"))["probe_semantics"]


class AccessibilitySemanticsTests(unittest.TestCase):
    def result(self, count=2, role="AXOutline", enabled=True, parent=True, children=17):
        return {"selected_children_count": count, "hierarchy": {"nodes": [
            {"role": role, "enabled": enabled, "has_parent": parent, "child_count_bounded": children}]}}

    def test_usable_tree_with_correct_selection_passes(self):
        for count in (1, 2):
            self.assertTrue(CHECK(self.result(count=count), count, True)["semantic_valid"])

    def test_one_column_silent_invalidation_is_rejected(self):
        result = self.result(count=0, role="AXUnknown", enabled=False, parent=False, children=0)
        self.assertFalse(CHECK(result, 1, True)["semantic_valid"])

    def test_selected_count_must_match_independent_qt_state(self):
        self.assertFalse(CHECK(self.result(count=0), 2, True)["semantic_valid"])

    def test_collapsed_phase_still_requires_usable_accessibility(self):
        self.assertTrue(CHECK(self.result(count=0), 2, False)["semantic_valid"])
        self.assertFalse(CHECK(self.result(role="AXUnknown"), 2, False)["semantic_valid"])

    def test_absent_or_empty_hierarchy_is_rejected(self):
        self.assertFalse(CHECK({}, 0, False)["semantic_valid"])
        self.assertFalse(CHECK(self.result(children=0), 0, False)["semantic_valid"])


if __name__ == "__main__":
    unittest.main()
