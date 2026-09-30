"""Opt-in UI trace tests: actual MainWindow and native QMenu, own process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.fixture_paths import fixture_root


NATIVE_DRIVER = r'''
import sys
from pathlib import Path
from app.picking_diagnostics import run_native_trace
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
results = {}
def ready(window):
    from app.depth import cache_candidates as depth_cache
    from app.relations import cache_candidates as relation_cache
    results['cache_writes_are_scoped'] = all(
        any(part.startswith('anatomy-native-picking-') for part in function(window.ds.dir / name)[1].parts)
        and window.ds.dir not in function(window.ds.dir / name)[1].parents
        for function, name in ((depth_cache, 'depth.npz'), (relation_cache, 'samples.npz')))
    if '--fail-capture-sample' in sys.argv:
        from app.picking_diagnostics import NativeGL
        def failed_state(self):
            raise RuntimeError('intentional capture sample failure')
        NativeGL.state = failed_state
    view = window.viewport
    point = QPoint(view.width() // 2, view.height() // 3)
    results['before_count'] = int(window.state.visible_mask().sum())
    def inspect_menu():
        menu = QApplication.activePopupWidget()
        results['native_menu'] = isinstance(menu, QMenu)
        results['visible'] = bool(menu and menu.isVisible())
        results['target'] = list(window.state.selected)
        if isinstance(menu, QMenu):
            if window.cmds.actions['hide'] in menu.actions():
                window.cmds.actions['hide'].trigger()
                results['after_count'] = int(window.state.visible_mask().sum())
            menu.close()
        QTimer.singleShot(50, window.close)
    def click():
        QTimer.singleShot(150, inspect_menu)
        QTimer.singleShot(1500, window.close)  # watchdog: this task's own window only
        QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, point)
    QTimer.singleShot(0, click)
report = run_native_trace(Path(sys.argv[1]), seconds=4, _on_ready=ready)
report['synthetic_menu_observations'] = results
Path(sys.argv[1]).write_text(__import__('json').dumps(report, indent=2))
raise SystemExit(0 if report['passed'] else 1)
'''


@unittest.skipUnless(os.environ.get("ANATOMY_NATIVE_PICKING_DIAGNOSTICS") == "1", "opt-in real Qt menu subprocess")
class NativeTraceTests(unittest.TestCase):
    def run_trace(self, fail_sample=False):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture_root(directory) / "native-trace.json"
            command = [sys.executable, "-c", NATIVE_DRIVER, str(path)]
            if fail_sample:
                command.append("--fail-capture-sample")
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                                    capture_output=True, text=True, timeout=60)
            report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            self.assertEqual(result.returncode, 1 if fail_sample else 0,
                             result.stdout + result.stderr + str(report.get("error")))
            return report

    def test_actual_right_click_menu_and_hide_are_captured(self):
        # Expected anatomy is deliberately not asserted: this checks the real
        # handler/menu route. Independent GPU IDs have a separate oracle.
        report = self.run_trace()
        self.assertFalse(report["native_menu_substituted"])
        self.assertTrue(report["synthetic_test_driver"])
        self.assertFalse(report["capture_incomplete"])
        observations = report["synthetic_menu_observations"]
        self.assertTrue(observations["native_menu"])
        self.assertTrue(observations["visible"])
        self.assertTrue(observations["cache_writes_are_scoped"])
        self.assertTrue(observations["target"])
        self.assertLess(observations["after_count"], observations["before_count"])
        events = report["events"]
        kinds = [event["kind"] for event in events]
        self.assertIn("MouseButtonRelease", kinds)
        self.assertIn("pick_returned", kinds)
        self.assertIn("menu_show", kinds)
        self.assertIn("hide_action_completed", kinds)
        samples = [event for event in events if event["kind"] == "pick_returned"]
        self.assertEqual(samples[0]["id"], observations["target"][0])
        self.assertEqual(samples[0]["raw_rgba"][0], samples[0]["id"] + 1)
        self.assertEqual(samples[0]["frame_key"], samples[0]["current_frame_key"])
        self.assertFalse(samples[0]["gl_errors_after_sample"])

    def test_failed_capture_sample_preserves_real_handler_but_reports_incomplete(self):
        report = self.run_trace(fail_sample=True)
        self.assertFalse(report["passed"])
        self.assertTrue(report["capture_completed"])
        self.assertTrue(report["capture_incomplete"])
        self.assertTrue(any("intentional capture sample failure" in error for error in report["capture_errors"]))
        self.assertTrue(report["synthetic_menu_observations"]["visible"])
        self.assertIn("hide_action_completed", [event["kind"] for event in report["events"]])
        self.assertFalse(report["picking_validated"])
        self.assertFalse(report["physical_menu_visibility_validated"])


if __name__ == "__main__":
    unittest.main()
