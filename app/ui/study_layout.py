"""Lesson metadata visibility for the inset reader."""
from PySide6.QtCore import QObject
from .lessons import PAGE_RUNNER


class StudyLayout(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.panel = window.lessons_panel
        self.snapshot = None
        if self.panel is not None:
            self.panel.tools_toggle.toggled.connect(self.show_metadata)
            self.panel.stack.currentChanged.connect(self.sync)
            window.center.currentChanged.connect(self.sync)

    def sync(self, *_):
        if self.panel is None:
            return
        reading = (not self.window.lesson_reader.isHidden() and
                   self.panel.stack.currentIndex() == PAGE_RUNNER)
        if not reading:
            self.leave()
            return
        if self.snapshot is None:
            self.snapshot = self.panel.meta.isHidden()
        self.panel.meta.setVisible(self.panel.tools_toggle.isChecked())

    def show_metadata(self, on):
        if self.snapshot is not None:
            self.panel.meta.setVisible(on)

    def leave(self):
        if self.snapshot is not None:
            self.panel.meta.setVisible(not self.snapshot)
            self.snapshot = None
