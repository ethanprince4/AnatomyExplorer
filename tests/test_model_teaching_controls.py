"""Small native 2D teaching rail; mocked runtime, no model arrays or native app."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from app.ui.model_teaching import ModelTeachingControls
QAPP = QApplication.instance() or QApplication([])


class TeachingRailTests(unittest.TestCase):
    def setUp(self):
        self.widget = ModelTeachingControls()
        self.addCleanup(self.widget.deleteLater)
        self.session = SimpleNamespace(controls={"functional_sequences": [
            {"id": "flow", "title": "Authored function", "steps": [{"id": "first", "title": "First step"},
                                                                       {"id": "second", "title": "Second step"}]}]},
            function=Mock(return_value={"title": "Authored step", "caption": "Source mechanism", "scale_note": "Schematic detail"}),
            opening=Mock(return_value={"title": "Overview"}))
        self.widget.set_session(self.session)

    def test_initialization_never_starts_function_or_animation(self):
        self.session.function.assert_not_called()
        self.session.opening.assert_not_called()
        self.assertFalse(self.widget.previous.isEnabled())
        self.assertTrue(self.widget.next.isEnabled())

    def test_step_and_navigation_use_exact_selected_sequence(self):
        self.widget.show_step()
        self.session.function.assert_called_once_with("flow", 0)
        self.widget.next.click()
        self.session.function.assert_called_with("flow", 1)
        self.assertFalse(self.widget.next.isEnabled())
        self.assertIn("Source mechanism", self.widget.caption.text())
        self.assertIn("Schematic detail", self.widget.caption.text())

    def test_overview_restores_authored_opening(self):
        self.widget.overview.click()
        self.session.opening.assert_called_once()
        self.assertEqual(self.widget.caption.text(), "Overview")

    def test_failure_explains_recovery(self):
        self.session.function.side_effect = ValueError("variant certificate missing")
        self.widget.show_step()
        self.assertIn("variant certificate missing", self.widget.caption.text())
        self.assertIn("Overview", self.widget.caption.text())

    def test_missing_function_sequence_hides_rail(self):
        self.session.controls = {"functional_sequences": []}
        self.widget.set_session(self.session)
        self.assertTrue(self.widget.isHidden())
        self.assertFalse(self.widget.apply.isEnabled())

    def test_compact_layout_preserves_accessible_controls(self):
        self.widget.resize(300, 210)
        self.widget.show()
        QAPP.processEvents()
        self.assertEqual(self.widget.sequence.accessibleName(), "Model function sequence")
        self.assertEqual(self.widget.step.accessibleName(), "Function step")
        self.assertLessEqual(self.widget.minimumSizeHint().width(), 300)


if __name__ == "__main__":
    unittest.main()
