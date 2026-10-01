"""Focused tests for launch checks and the explicit restart handshake."""
import contextlib
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import restart, updater
from app.ui.updates import UpdateController


class Settings:
    def __init__(self, **values):
        self.data = values
    def value(self, key, default=None, type=None):
        return self.data.get(key, default)
    def setValue(self, key, value):
        self.data[key] = value


class LaunchCheckTests(unittest.TestCase):
    def controller(self, started=False, result=None, automatic=True):
        timer = SimpleNamespace(start=Mock(), stop=Mock())
        settings = Settings(**{"updates/automatic": automatic,
                               "updates/last_success": 9999999999.0,
                               "updates/last_attempt": 100.0,
                               "updates/consecutive_failures": 1})
        value = SimpleNamespace(
            closed=threading.Event(), busy=False, launch_check_started=started,
            result=result, automatic_timer=timer,
            window=SimpleNamespace(qsettings=settings), worker_generation=0,
            message=SimpleNamespace(emit=Mock()), dialog=None)
        def check():
            value.launch_check_started = True
        value.check = Mock(side_effect=check)
        return value

    def test_new_launch_ignores_recent_persisted_success(self):
        value = self.controller()
        UpdateController.automatic(value)
        value.check.assert_called_once()

    def test_success_does_not_start_an_infinite_check_loop(self):
        value = self.controller()
        UpdateController.automatic(value)
        value.result = {"status": "current"}
        UpdateController.automatic(value)
        UpdateController.automatic(value)
        value.check.assert_called_once()
        value.automatic_timer.stop.assert_called()

    def test_manual_attempt_counts_and_disables_startup_timer(self):
        value = self.controller()
        with patch("app.ui.updates.threading.Thread") as worker:
            UpdateController.check(value)
        self.assertTrue(value.launch_check_started)
        self.assertTrue(value.busy)
        value.automatic_timer.stop.assert_called_once()
        worker.return_value.start.assert_called_once()

    def test_optout_is_preserved(self):
        value = self.controller(automatic=False)
        UpdateController.automatic(value)
        value.check.assert_not_called()
        value.automatic_timer.stop.assert_called_once()

    def test_ready_does_not_repeat_automatic_check(self):
        value = self.controller(started=True, result={"status": "ready"})
        UpdateController.automatic(value)
        value.check.assert_not_called()

    def test_failure_backoff_is_bounded_and_retries_when_due(self):
        value = self.controller(started=True, result={"status": "error"})
        with patch("app.ui.updates.time.time", return_value=101.0):
            UpdateController.automatic(value)
        value.check.assert_not_called()
        delay = value.automatic_timer.start.call_args.args[0]
        self.assertGreater(delay, 0)
        self.assertLessEqual(delay, 6 * 3600 * 1000)
        with patch("app.ui.updates.time.time", return_value=2000.0):
            UpdateController.automatic(value)
        value.check.assert_called_once()


class RestartHandshakeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name) / "updates"
        root.mkdir()
        self.store = SimpleNamespace(root=root, base=Path(self.temporary.name) / "base",
                                     policy=lambda: ("stable", 1),
                                     state=lambda: {"pending": "downloaded-version"})
        self.process = Mock()
        self.process.poll.return_value = None

    def prepare(self):
        with patch.object(restart, "store_for", return_value=self.store), \
             patch.object(restart.subprocess, "Popen", return_value=self.process) as spawn, \
             patch.dict(os.environ, {"AE_READY_FILE": "old-session-ready-token"}):
            request = restart.prepare_restart(("stable", 1))
        return request, spawn

    def test_helper_starts_unarmed_without_old_readiness_marker(self):
        request, spawn = self.prepare()
        self.assertIs(json.loads(request.path.read_text())["armed"], False)
        args, kwargs = spawn.call_args
        self.assertEqual(args[0][1], "--ae-restart-helper")
        self.assertNotIn("--ae-managed", args[0])
        self.assertEqual(kwargs["env"]["AE_INSTALL_BASE"], str(self.store.base))
        self.assertNotIn("AE_READY_FILE", kwargs["env"])
        self.assertEqual(kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        request.cancel()
        self.assertFalse(request.path.exists())

    def test_armed_helper_uses_original_base_and_waiting_normal_launcher(self):
        request, unused = self.prepare()
        request.arm()
        token = request.path.stem.removeprefix("restart-")
        with patch.object(restart, "store_for", return_value=self.store), \
             patch.object(restart, "launch_managed", return_value=0) as launch:
            self.assertEqual(restart.run_helper(token), 0)
        launch.assert_called_once_with([], base=self.store.base, wait_seconds=90)
        self.assertFalse(request.path.exists())

    def test_cancelled_request_never_launches(self):
        request, unused = self.prepare()
        token = request.path.stem.removeprefix("restart-")
        request.cancel()
        with patch.object(restart, "store_for", return_value=self.store), \
             patch.object(restart, "launch_managed") as launch:
            self.assertEqual(restart.run_helper(token), 0)
        launch.assert_not_called()

    def test_spawn_failure_removes_unarmed_request(self):
        with patch.object(restart, "store_for", return_value=self.store), \
             patch.object(restart.subprocess, "Popen", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                restart.prepare_restart(("stable", 1))
        self.assertEqual(list(self.store.root.glob("restart-*.json")), [])

    def test_channel_change_is_rejected_before_spawn(self):
        with patch.object(restart, "store_for", return_value=self.store), \
             patch.object(restart.subprocess, "Popen") as spawn:
            with self.assertRaises(updater.UpdateError):
                restart.prepare_restart(("experimental", 1))
        spawn.assert_not_called()

    def test_unarmed_request_expires_without_launching(self):
        request, unused = self.prepare()
        token = request.path.stem.removeprefix("restart-")
        with patch.object(restart, "store_for", return_value=self.store), \
             patch.object(restart.time, "monotonic", side_effect=[0.0, 0.0, 91.0]), \
             patch.object(restart.time, "sleep"), \
             patch.object(restart, "launch_managed") as launch:
            with self.assertRaises(updater.UpdateError):
                restart.run_helper(token)
        launch.assert_not_called()
        self.assertFalse(request.path.exists())

    def test_malformed_handshake_and_invalid_token_never_launch(self):
        request, unused = self.prepare()
        token = request.path.stem.removeprefix('restart-')
        request.path.write_text('{"schema":1,"armed":"yes"}')
        with patch.object(restart, 'store_for', return_value=self.store), \
             patch.object(restart, 'launch_managed') as launch:
            with self.assertRaises(updater.UpdateError):
                restart.run_helper(token)
            for invalid in ('../outside', '', 'z' * 32, 'a' * 33):
                with self.assertRaises(updater.UpdateError):
                    restart.run_helper(invalid)
        launch.assert_not_called()
        self.assertFalse(request.path.exists())


class RestartLockTests(unittest.TestCase):
    def test_restart_waits_but_normal_launch_stays_nonblocking(self):
        attempts = []
        @contextlib.contextmanager
        def busy_then_free(path):
            attempts.append(path)
            if len(attempts) < 3:
                raise updater.UpdateError("busy")
            yield
        with patch.object(updater, "lock", busy_then_free), \
             patch.object(updater.time, "monotonic", return_value=0.0), \
             patch.object(updater.time, "sleep"):
            with updater.session_lock(Path("fixture"), 1):
                self.assertEqual(len(attempts), 3)
        attempts.clear()
        with patch.object(updater, "lock", busy_then_free), \
             patch.object(updater.time, "monotonic", return_value=0.0):
            with self.assertRaises(updater.UpdateError):
                with updater.session_lock(Path("fixture")):
                    self.fail("A normal launch must not acquire this busy lock")
        self.assertEqual(len(attempts), 1)


class RollbackPolicyTests(unittest.TestCase):
    def setUp(self):
        from tests.fixture_paths import fixture_root
        from tests.test_updater_channels import package
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = fixture_root(temporary.name)
        package(root / 'base', '3.1.2', 'stable', 'v3.1.2')
        first, first_source = package(root / 'current', '3.1.3', 'stable', 'v3.1.3')
        self.store = updater.UpdateStore(root / 'base', root / 'updates')
        self.store.prepare(first, first_source)
        self.store.activate()
        self.store.healthy()
        self.later, self.source = package(root / 'later', '3.1.4', 'stable', 'v3.1.4')

    def test_rollback_advances_policy_removes_pending_and_keeps_version_choices(self):
        self.store.prepare(self.later, self.source)
        before, token = self.store.state(), self.store.policy()
        self.store.request_rollback()
        after = self.store.state()
        self.assertEqual(self.store.policy(), (token[0], token[1] + 1))
        self.assertEqual(after.get('current'), before.get('current'))
        self.assertEqual(after.get('previous'), before.get('previous'))
        self.assertTrue(after['rollback_requested'])
        self.assertIsNone(after.get('pending'))

    def test_chunk_callback_rollback_cannot_republish_pending(self):
        token = self.store.policy()
        active = self.store.active()
        self.source.callback = self.store.request_rollback
        result = self.store.prepare(self.later, self.source, policy_token=token)
        self.assertGreater(self.source.bytes, 0)
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNone(self.store.state().get('pending'))
        self.assertTrue(self.store.state()['rollback_requested'])
        self.assertEqual(self.store.active(), active)

    def test_prepare_respects_queued_previous_version_without_downloading(self):
        self.store.request_rollback()
        with patch.object(self.source, 'chunk', wraps=self.source.chunk) as download:
            result = self.store.prepare(self.later, self.source)
        download.assert_not_called()
        self.assertEqual(result['status'], 'returning')
        self.assertIs(result['return_to_stable'], False)
        self.assertIsNone(self.store.state().get('pending'))


class RestartQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QMainWindow
        from tests.fixture_paths import fixture_root
        from tests.test_updater_channels import package
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = fixture_root(temporary.name)
        package(root / 'base', '3.1.2', 'stable', 'v3.1.2')
        manifest, source = package(root / 'next', '3.1.3', 'stable', 'v3.1.3')
        self.store = updater.UpdateStore(root / 'base', root / 'updates')
        self.store.prepare(manifest, source)
        class Window(QMainWindow):
            veto = False
            saved = False
            def closeEvent(self, event):
                if self.veto:
                    event.ignore()
                else:
                    self.saved = True
                    super().closeEvent(event)
        self.window = Window()
        self.window.qsettings = QSettings(str(root / 'qt.ini'), QSettings.IniFormat)
        self.controller = UpdateController(self.window)
        self.controller.automatic_timer.stop()
        self.controller.result = {'status': 'ready', 'version': '3.1.3', 'policy': self.store.policy()}
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window.veto = False
        if self.controller.ready_notice is not None:
            self.controller.ready_notice.close()
        self.window.close()

    def test_not_now_keeps_study_and_deduplicates_ready_notice(self):
        from PySide6.QtCore import Qt
        with patch('app.ui.updates.store_for', return_value=self.store), \
             patch.object(self.controller, 'restart_now') as launch:
            self.controller.notify_ready(self.controller.result)
            notice = self.controller.ready_notice
            self.assertEqual(notice.windowModality(), Qt.NonModal)
            self.assertEqual(notice.defaultButton().text(), 'Not now')
            self.controller.notify_ready(self.controller.result)
            self.assertIs(self.controller.ready_notice, notice)
            next(button for button in notice.buttons() if button.text() == 'Not now').click()
            self.assertIsNone(self.controller.ready_notice)
            self.controller.notify_ready(self.controller.result)
            self.assertIsNone(self.controller.ready_notice)
            launch.assert_not_called()
            self.assertFalse(self.controller.closed.is_set())
            self.assertIsNotNone(self.store.state().get('pending'))

    def test_later_updates_dialog_can_restart(self):
        from PySide6.QtWidgets import QDialog
        def examine(dialog):
            self.assertTrue(dialog.restart_button.isEnabled())
            dialog.restart_button.click()
            return 0
        with patch('app.ui.updates.store_for', return_value=self.store), \
             patch.object(self.controller, 'restart_now') as launch, \
             patch.object(QDialog, 'exec', examine):
            self.controller.open_dialog()
        launch.assert_called_once()

    def test_spawn_failure_keeps_window_open(self):
        with patch.object(restart, 'prepare_restart', side_effect=OSError('fixture')):
            self.controller.restart_now()
        self.assertFalse(self.controller.closed.is_set())
        self.assertFalse(self.window.saved)

    def test_close_veto_cancels_unarmed_helper_and_restores_controller(self):
        self.window.veto = True
        request = Mock()
        with patch.object(restart, 'prepare_restart', return_value=request):
            self.controller.restart_now()
        request.cancel.assert_called_once()
        request.arm.assert_not_called()
        self.assertFalse(self.controller.closed.is_set())
        self.assertFalse(self.window.saved)
        self.window.veto = False
        self.window.close()
        self.assertTrue(self.controller.closed.is_set(), 'close filter must be restored')

    def test_accepted_close_saves_before_arming(self):
        request = Mock()
        def assert_saved():
            self.assertTrue(self.window.saved)
            self.assertTrue(self.controller.closed.is_set())
        request.arm.side_effect = assert_saved
        with patch.object(restart, 'prepare_restart', return_value=request):
            self.controller.restart_now()
        request.arm.assert_called_once()
        request.cancel.assert_not_called()

    def test_cached_tampered_pending_reports_error_and_offers_no_restart(self):
        import time
        from PySide6.QtWidgets import QDialog
        pending = self.store.path(self.store.state()['pending'])
        (pending / 'AnatomyExplorer.exe').write_bytes(b'tampered staged executable')
        def examine(dialog):
            self.assertFalse(dialog.restart_button.isEnabled())
            self.assertIn('integrity', dialog.status.text())
            return 0
        with patch('app.ui.updates.store_for', return_value=self.store), \
             patch('app.ui.updates.GitHubSource') as source, \
             patch.object(self.controller, 'notify_ready') as notify:
            self.controller.check()
            deadline = time.monotonic() + 5
            while self.controller.busy and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.001)
            self.assertFalse(self.controller.busy)
            self.assertEqual(self.controller.result['status'], 'error')
            source.return_value.latest.assert_not_called()
            notify.assert_not_called()
            with patch.object(QDialog, 'exec', examine):
                self.controller.open_dialog()

    def test_later_staged_tamper_is_rejected_at_activation_and_keeps_working_base(self):
        pending = self.store.path(self.store.state()['pending'])
        self.store.verify(pending)
        (pending / 'AnatomyExplorer.exe').write_bytes(b'tampered after readiness verification')
        with self.assertRaises(updater.UpdateError):
            self.store.activate()
        self.assertEqual(self.store.active(), self.store.base)
        self.store.verify(self.store.active())

    def test_channel_change_dismisses_notice_and_disables_dialog_restart(self):
        from PySide6.QtWidgets import QCheckBox, QDialog
        def examine(dialog):
            self.assertTrue(dialog.restart_button.isEnabled())
            option = next(widget for widget in dialog.findChildren(QCheckBox)
                          if widget.text().startswith('Enable experimental'))
            option.setChecked(True)
            self.assertIsNone(self.controller.ready_notice)
            self.assertFalse(dialog.restart_button.isEnabled())
            self.assertIsNone(self.controller.result)
            return 0
        with patch('app.ui.updates.store_for', return_value=self.store), \
             patch.object(self.controller, 'check'), \
             patch.object(QDialog, 'exec', examine):
            self.controller.notify_ready(self.controller.result)
            self.controller.open_dialog()

    def test_rollback_request_dismisses_notice_and_disables_dialog_restart(self):
        from PySide6.QtWidgets import QDialog, QPushButton
        self.store.activate()
        self.store.healthy()
        def examine(dialog):
            self.assertTrue(dialog.restart_button.isEnabled())
            button = next(widget for widget in dialog.findChildren(QPushButton)
                          if widget.text() == 'Use the previous version on next launch')
            self.assertTrue(button.isEnabled())
            button.click()
            self.assertTrue(self.store.state().get('rollback_requested'))
            self.assertIsNone(self.controller.ready_notice)
            self.assertFalse(dialog.restart_button.isEnabled())
            self.assertIsNone(self.controller.result)
            return 0
        with patch('app.ui.updates.store_for', return_value=self.store), \
             patch.object(QDialog, 'exec', examine):
            self.controller.notify_ready(self.controller.result)
            self.controller.open_dialog()

    def test_late_ready_after_rollback_ends_worker_without_notice_or_restart(self):
        import time
        from PySide6.QtWidgets import QDialog, QPushButton
        from tests.test_updater_channels import package
        self.store.activate()
        self.store.healthy()
        target, source = package(self.store.root.parent / 'later', '3.1.4', 'stable', 'v3.1.4')
        self.store.prepare(target, source)
        old_policy = self.store.policy()
        self.controller.result = None
        self.controller.busy = True
        self.controller.worker_generation = 1
        self.controller.launch_check_started = True
        def examine(dialog):
            button = next(widget for widget in dialog.findChildren(QPushButton)
                          if widget.text() == 'Use the previous version on next launch')
            button.click()
            self.controller.finish((1, {'status': 'ready', 'version': '3.1.4', 'policy': old_policy}))
            self.assertFalse(self.controller.busy, 'old worker ownership ends normally')
            self.assertEqual(self.controller.worker_generation, 1)
            self.assertIsNone(self.controller.result)
            self.assertIsNone(self.controller.ready_notice)
            self.assertFalse(dialog.restart_button.isEnabled())
            deadline = time.monotonic() + 5
            while self.controller.result is None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.001)
            self.assertFalse(self.controller.busy)
            self.assertEqual(self.controller.result['status'], 'returning')
            self.assertIs(self.controller.result['return_to_stable'], False)
            self.assertIn('previous version', dialog.status.text())
            self.assertFalse(dialog.restart_button.isEnabled())
            return 0
        with patch('app.ui.updates.store_for', return_value=self.store), \
             patch('app.ui.updates.GitHubSource') as source, \
             patch.object(self.controller, 'notify_ready') as notice, \
             patch.object(QDialog, 'exec', examine):
            self.controller.open_dialog()
        notice.assert_not_called()
        source.return_value.latest.assert_not_called()
        source.return_value.chunk.assert_not_called()


if __name__ == '__main__':
    unittest.main()
