"""Optional Qt offscreen tests: never opens a foreground desktop window."""
import importlib.util
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from tests.fixture_paths import fixture_root

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
            root = fixture_root(d)
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

    def test_reopen_and_channel_toggles_keep_delayed_worker_exclusive(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QCheckBox, QDialog, QMainWindow, QPushButton
        from app import updater as u
        from app.ui.updates import UpdateController
        from tests.test_updater_channels import package
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            package(root / "install", "3.1.2", "stable", "v3.1.2")
            store = u.UpdateStore(root / "install", root / "updates")
            window = QMainWindow()
            window.qsettings = QSettings(str(root / "qt.ini"), QSettings.IniFormat)
            controller = UpdateController(window)
            started, release = threading.Event(), threading.Event()
            channels, active, maximum = [], 0, 0
            guard = threading.Lock()

            class Source:
                def __init__(self, channel):
                    self.channel = channel

                def latest(self):
                    nonlocal active, maximum
                    with guard:
                        channels.append(self.channel)
                        number = len(channels)
                        active += 1
                        maximum = max(maximum, active)
                    try:
                        if number == 2:
                            started.set()
                            if not release.wait(5):
                                raise AssertionError("Test did not release worker B")
                        return None
                    finally:
                        with guard:
                            active -= 1

            def until(predicate):
                deadline = time.monotonic() + 4
                while not predicate() and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.001)
                self.assertTrue(predicate(), "Worker/event condition did not complete")

            def reopened(dialog):
                self.assertTrue(controller.busy)
                self.assertIn("Checking", dialog.status.text())
                next(x for x in dialog.findChildren(QPushButton) if x.text() == "Check and download now").click()
                self.assertEqual(len(channels), 2)
                option = next(x for x in dialog.findChildren(QCheckBox) if x.text().startswith("Enable experimental"))
                option.setChecked(True)
                option.setChecked(False)
                option.setChecked(True)
                self.assertTrue(controller.busy)
                self.assertEqual(len(channels), 2)
                return 0

            try:
                with patch("app.ui.updates.store_for", return_value=store), \
                     patch("app.ui.updates.GitHubSource", Source):
                    controller.check()  # A completes and leaves a cached result.
                    until(lambda: controller.result is not None and not controller.busy)
                    saved = controller.result.copy()
                    controller.check()  # B waits deterministically inside latest().
                    self.assertTrue(started.wait(2))
                    self.assertIsNone(controller.result)
                    controller.finish((1, saved))  # stale/duplicate completion cannot clear B.
                    self.assertTrue(controller.busy)
                    with patch.object(QDialog, "exec", reopened):
                        controller.open_dialog()
                        controller.open_dialog()
                    self.assertEqual(len(channels), 2)
                    release.set()
                    until(lambda: len(channels) == 3 and not controller.busy and controller.result is not None)
                    self.assertEqual(channels, ["stable", "stable", "experimental"])
                    self.assertEqual(maximum, 1)
                    self.assertEqual(controller.result["policy"], store.policy())
            finally:
                release.set()
                window.close()

    def test_original_mac_menu_dialog_channel_and_readiness_do_not_inventory(self):
        import json
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QDialog, QMainWindow
        from app import updater as u
        from app.ui.updates import attach_updates
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            base = root / "Anatomy Explorer.app"
            resources = base / "Contents/Resources"
            resources.mkdir(parents=True)
            (resources / "VERSION").write_text("3.1.2")
            (resources / "UPDATE_CHANNEL.json").write_text(json.dumps({"channel": "stable", "release_tag": "v3.1.2"}))
            (resources / "large-asset.bin").write_bytes(b"fixture asset")
            store = u.UpdateStore(base, root / "updates")
            window = QMainWindow()
            window.qsettings = QSettings(str(root / "qt.ini"), QSettings.IniFormat)
            try:
                with patch("app.ui.updates.FROZEN", True), patch("sys.platform", "darwin"), \
                     patch("app.ui.updates.store_for", return_value=store), \
                     patch("app.updater.local_inventory", side_effect=AssertionError("UI inventoried full app")), \
                     patch.object(QDialog, "exec", return_value=0):
                    attach_updates(window)
                    window.update_controller.open_dialog()
                    store.set_channel("experimental")
                    store.set_channel("stable")
                    store.protect_stable_anchor()
                # Full baseline inventory remains part of update integrity work.
                with patch("app.updater.local_inventory", wraps=u.local_inventory) as inventory:
                    u.read_manifest(base)
                    inventory.assert_called_once_with(base)
            finally:
                window.close()

    def test_failed_checks_use_bounded_backoff_and_manual_retry_ignores_it(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QMainWindow
        from app import updater as u
        from app.ui.updates import UpdateController
        from tests.test_updater_channels import package
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            package(root / "install", "3.1.2", "stable", "v3.1.2")
            store = u.UpdateStore(root / "install", root / "updates")
            window = QMainWindow()
            window.qsettings = QSettings(str(root / "qt.ini"), QSettings.IniFormat)
            window.qsettings.setValue("updates/last_check", 9999999)  # obsolete failed-attempt timestamp
            controller = UpdateController(window)
            now, targets, fail = [100000.0], [], [True]

            class DeferredThread:
                def __init__(self, target, **kwargs):
                    self.target = target
                def start(self):
                    targets.append(self.target)

            class Source:
                def __init__(self, **kwargs):
                    pass
                def latest(self):
                    if fail[0]:
                        raise OSError("network unavailable")
                    return None

            try:
                with patch("app.ui.updates.store_for", return_value=store), \
                     patch("app.ui.updates.GitHubSource", Source), \
                     patch("app.ui.updates.threading", SimpleNamespace(Thread=DeferredThread)), \
                     patch("app.ui.updates.time.time", side_effect=lambda: now[0]):
                    controller.automatic()
                    self.assertEqual(len(targets), 1)
                    self.assertEqual(window.qsettings.value("updates/last_attempt", type=float), now[0])
                    self.assertFalse(window.qsettings.contains("updates/last_success"))
                    targets[0]()
                    self.assertEqual(controller.result["status"], "error")
                    self.assertEqual(controller.automatic_timer.interval(), 900000)
                    now[0] += 899
                    controller.automatic()
                    self.assertEqual(len(targets), 1)
                    now[0] += 1
                    controller.automatic()
                    targets[1]()
                    self.assertEqual(controller.automatic_timer.interval(), 1800000)
                    self.assertFalse(window.qsettings.contains("updates/last_success"))
                    now[0] += 1
                    fail[0] = False
                    controller.check()  # manual retry bypasses automatic backoff
                    targets[2]()
                    self.assertEqual(window.qsettings.value("updates/last_success", type=float), now[0])
                    self.assertEqual(window.qsettings.value("updates/consecutive_failures", type=int), 0)
                    self.assertEqual(controller.automatic_timer.interval(), 86400000)
                    window.qsettings.setValue("updates/consecutive_failures", 100)
                    window.qsettings.setValue("updates/last_attempt", now[0])
                    controller.automatic()
                    self.assertEqual(controller.automatic_timer.interval(), 21600000)
                    window.qsettings.setValue("updates/automatic", False)
                    controller.automatic()
                    self.assertFalse(controller.automatic_timer.isActive())
                    self.assertEqual(len(targets), 3)
            finally:
                window.close()

    def test_closed_dialog_and_destroyed_window_ignore_late_worker_callbacks(self):
        from PySide6.QtCore import QCoreApplication, QEvent, QSettings
        from PySide6.QtWidgets import QDialog, QMainWindow
        from shiboken6 import isValid
        from app import updater as u
        from app.ui.updates import UpdateController
        from tests.test_updater_channels import package
        with tempfile.TemporaryDirectory() as d:
            root = fixture_root(d)
            package(root / "install", "3.1.2", "stable", "v3.1.2")
            store = u.UpdateStore(root / "install", root / "updates")
            window = QMainWindow()
            window.qsettings = QSettings(str(root / "qt.ini"), QSettings.IniFormat)
            controller = UpdateController(window)
            targets = []

            class DeferredThread:
                def __init__(self, target, **kwargs):
                    self.target = target
                def start(self):
                    targets.append(self.target)

            class Source:
                def __init__(self, **kwargs):
                    pass
                def latest(self):
                    window.close()
                    window.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                    self.assert_disposed = not isValid(controller)
                    controller.show_message("queued progress after teardown")
                    return None

            with patch("app.ui.updates.store_for", return_value=store), \
                 patch("app.ui.updates.GitHubSource", Source), \
                 patch("app.ui.updates.threading", SimpleNamespace(Thread=DeferredThread)), \
                 patch.object(QDialog, "exec", return_value=0):
                controller.check()
                controller.open_dialog()
                controller.open_dialog()
                self.assertTrue(controller.busy)
                disposed_dialog = QDialog(window)
                controller.dialog = disposed_dialog
                disposed_dialog.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.assertFalse(isValid(disposed_dialog))
                controller.show_message("progress after dialog disposal")
                targets[0]()  # completion happens after actual parent QObject deletion
                self.assertTrue(controller.closed.is_set())
                self.assertFalse(isValid(controller))
                self.assertIsNone(controller.result)
                controller.finish((controller.worker_generation, {"status": "current", "policy": store.policy()}))
                controller.automatic()
                controller.check()
                self.assertEqual(len(targets), 1)


if __name__ == "__main__":
    unittest.main()
