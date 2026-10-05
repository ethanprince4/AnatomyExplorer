"""Readiness dispatch uses completion/failure events, never a guessed delay."""
import unittest
from types import SimpleNamespace
from app.main_window import MainWindow


class Signal:
    def __init__(self): self.callbacks=[]
    def connect(self, callback): self.callbacks.append(callback)
    def emit(self, *args):
        for callback in self.callbacks: callback(*args)


class InteractiveReadinessTests(unittest.TestCase):
    def test_cpu_loaded_view_waits_for_graphics_once_and_failure_finishes(self):
        host=SimpleNamespace(_closing=False)
        def make_view():
            return SimpleNamespace(gl_widget=SimpleNamespace(interactive_ready=False,
                graphics_error='',interactiveReady=Signal(),graphicsFailed=Signal(),destroyed=Signal()))
        view=make_view();received=[]
        MainWindow._when_view_interactive(host,view,received.append)
        self.assertEqual(received,[])
        view.gl_widget.interactiveReady.emit()
        view.gl_widget.interactiveReady.emit()
        self.assertEqual(received,[view])
        failed=make_view();errors=[]
        MainWindow._when_view_interactive(host,failed,errors.append)
        failed.gl_widget.graphicsFailed.emit('No compatible graphics context')
        failed.gl_widget.destroyed.emit()
        self.assertEqual(errors,[None])
