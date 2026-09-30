"""Optional Qt offscreen tests: never opens a foreground desktop window."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "Qt UI check runs in dependency-backed app CI")
class ChannelUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_opt_in_defaults_off_and_ignores_shared_qsettings(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QCheckBox, QDialog, QMainWindow
        from app import updater as u
        from app.ui.updates import UpdateController
        from tests.test_updater_channels import package
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            package(root / "install", "3.1.2", "stable", "v3.1.2")
            store = u.UpdateStore(root / "install", root / "updates")
            window = QMainWindow()
            window.qsettings = QSettings(str(root / "qt.ini"), QSettings.IniFormat)
            window.qsettings.setValue("updates/experimental", True)  # another install cannot opt this one in
            controller = UpdateController(window)
            checks = []

            def examine(dialog):
                option = next(widget for widget in dialog.findChildren(QCheckBox)
                              if widget.text().startswith("Enable experimental stuff"))
                self.assertFalse(option.isChecked())
                self.assertEqual(store.policy(), ("stable", 0))
                option.setChecked(True)
                self.assertEqual(store.policy()[0], "experimental")
                self.assertIn("stable_anchor", store.state())
                option.setChecked(False)
                self.assertEqual(store.policy()[0], "stable")
                return 0

            with patch("app.ui.updates.store_for", return_value=store), \
                 patch.object(controller, "check", side_effect=lambda: checks.append(True)), \
                 patch.object(QDialog, "exec", examine):
                controller.open_dialog()
            self.assertEqual(len(checks), 2)
            self.assertTrue(window.qsettings.value("updates/experimental", type=bool), "shared settings are untouched")
            window.close()


if __name__ == "__main__":
    unittest.main()
