"""Search remains usable when optional content metadata is malformed."""
import unittest
from types import SimpleNamespace

from app.search import SearchIndex


class SearchRecoveryTests(unittest.TestCase):
    def test_radiology_missing_label_text_retains_case_and_structure_search(self):
        dataset = SimpleNamespace(structures=[], systems=[], nodes={}, landmarks=[])
        for optional_text in (None, "", 17):
            with self.subTest(optional_text=optional_text):
                label = SimpleNamespace(text=optional_text, structures=["Thyroid gland"])
                case = SimpleNamespace(id="thyroid_fixture", title="Isotope uptake fixture",
                                       modality="Nuclear medicine", region="Neck",
                                       summary="Functional tracer distribution",
                                       labels=[label, SimpleNamespace(text="Uptake pattern", structures=[])])
                index = SearchIndex(dataset)
                index.add_radiology([case])
                for query in ("thyroid gland", "uptake pattern", "isotope", "tracer", "nuclear medicine"):
                    self.assertIn(case.id, [entry.node for entry in index.search(query)])
                self.assertEqual(label.text, optional_text, "indexing must not change authored labels")
                self.assertEqual(len(index.entries), 1)


if __name__ == "__main__":
    unittest.main()
