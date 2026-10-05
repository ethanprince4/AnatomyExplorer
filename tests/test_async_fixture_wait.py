"""Tiny 2D guard tests for the failing-deadline async test helper; no app window."""
import unittest
from types import SimpleNamespace
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tests.general_fixtures import wait_for_model_ready
QAPP = QApplication.instance() or QApplication([])


class AsyncFixtureWaitTests(unittest.TestCase):
    def window(self, result, *, delayed=False, installed=True):
        model = object() if result == "model" else None
        window = SimpleNamespace(micro_tabs={}, _loading_models={})
        def notify(callback):
            if model is not None and installed:
                window.micro_tabs["owned"] = model
            callback(model)
        def subscribe(key, callback):
            self.assertEqual(key, "owned")
            if delayed:
                QTimer.singleShot(0, lambda: notify(callback))
            else:
                notify(callback)
        window.when_model_ready = subscribe
        return window, model

    def test_synchronous_already_ready_result(self):
        window, model = self.window("model")
        self.assertIs(wait_for_model_ready(window, "owned"), model)

    def test_actual_queued_callback_is_observed(self):
        window, model = self.window("model", delayed=True)
        self.assertIs(wait_for_model_ready(window, "owned"), model)

    def test_error_or_cancellation_is_a_failure(self):
        window, _ = self.window(None, delayed=True)
        with self.assertRaisesRegex(AssertionError, "failed"):
            wait_for_model_ready(window, "owned")

    def test_missing_callback_fails_at_the_deadline(self):
        window = SimpleNamespace(when_model_ready=lambda *_: None)
        with self.assertRaisesRegex(AssertionError, "did not become ready"):
            wait_for_model_ready(window, "owned", timeout_ms=20)

    def test_stale_or_unpublished_callback_is_a_failure(self):
        window, _ = self.window("model", delayed=True, installed=False)
        with self.assertRaisesRegex(AssertionError, "installed model tab"):
            wait_for_model_ready(window, "owned")


if __name__ == "__main__":
    unittest.main()
