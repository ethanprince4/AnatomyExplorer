"""Temporary lesson layout: reading and anatomy first, supporting panes on demand."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QSplitter

from .lessons import PAGE_RUNNER


class StudyLayout(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.panel = window.lessons_panel
        self.snapshot = None
        self.models = {}
        if self.panel is None:
            return
        self.panel.parts_btn.toggled.connect(self.show_parts)
        self.panel.details_btn.toggled.connect(self.show_details)
        self.panel.tools_toggle.toggled.connect(self.show_metadata)
        self.panel.stack.currentChanged.connect(self.sync)
        window.tabs.currentChanged.connect(self.sync)
        window.center.currentChanged.connect(self.sync)
        window.right_dock.visibilityChanged.connect(self.details_visible)
        window.installEventFilter(self)

    @staticmethod
    def reading_width(window_width):
        # Keep the native rail usable at the supported narrow laptop sizes without
        # consuming most of the anatomy area when a window is resized.
        return min(480, max(300, int(window_width * 0.34)))

    @staticmethod
    def checked(button, on):
        previous = button.blockSignals(True)
        button.setChecked(on)
        button.blockSignals(previous)

    def sync(self, *_):
        w, p = self.window, self.panel
        studying = w.tabs.currentWidget() is p and p.stack.currentIndex() == PAGE_RUNNER
        if not studying:
            self.leave()
            return
        if self.snapshot is None:
            self.snapshot = (w.saveState(), w.search.isHidden(), p.meta.isHidden())
            w.search.hide()
            p.meta.hide()
            w.left_dock.show()
            w.right_dock.hide()
            self.checked(p.parts_btn, False)
            self.checked(p.details_btn, False)
            w.resizeDocks([w.left_dock], [self.reading_width(w.width())], Qt.Horizontal)
        mv = w.active_model_view()
        p.parts_btn.setEnabled(mv is not None)
        for view in list(w.micro_tabs.values()):
            if not hasattr(view, "side"):
                continue
            if view not in self.models:
                split = view.side.parentWidget()
                sizes = split.sizes() if isinstance(split, QSplitter) else None
                self.models[view] = (view.side.isHidden(), sizes)
            view.side.setVisible(view is mv and p.parts_btn.isChecked())

    def show_parts(self, on):
        if self.snapshot is None:
            return
        if on:
            self.checked(self.panel.details_btn, False)
            self.window.right_dock.hide()
        self.sync()
        mv = self.window.active_model_view()
        if on and mv is not None:
            mv.tree.setFocus(Qt.OtherFocusReason)
        elif mv is not None:
            mv.gl_widget.setFocus(Qt.OtherFocusReason)

    def show_metadata(self, on):
        if self.snapshot is not None:
            self.panel.meta.setVisible(on)

    def show_details(self, on):
        if self.snapshot is None:
            return
        if on:
            self.checked(self.panel.parts_btn, False)
            self.sync()
        self.window.right_dock.setVisible(on)
        if on:
            self.window.resizeDocks([self.window.right_dock], [340], Qt.Horizontal)

    def details_visible(self, on):
        if self.snapshot is not None:
            self.checked(self.panel.details_btn, on)
            if on:
                self.checked(self.panel.parts_btn, False)
                self.sync()

    def leave(self):
        if self.snapshot is None:
            return
        layout, search_hidden, meta_hidden = self.snapshot
        self.snapshot = None
        self.window.search.setVisible(not search_hidden)
        self.panel.meta.setVisible(not meta_hidden)
        for view, (hidden, sizes) in self.models.items():
            try:
                view.side.setVisible(not hidden)
                split = view.side.parentWidget()
                if sizes is not None and isinstance(split, QSplitter):
                    split.setSizes(sizes)
            except RuntimeError:  # a tab may have been closed during the lesson
                pass
        self.models.clear()
        self.window.restoreState(layout)
        self.checked(self.panel.parts_btn, False)
        self.checked(self.panel.details_btn, False)

    def eventFilter(self, obj, event):
        if obj is self.window and event.type() == QEvent.Resize and self.snapshot is not None:
            # Keep a useful reading column while a laptop window is resized.
            self.window.resizeDocks([self.window.left_dock],
                                    [self.reading_width(self.window.width())], Qt.Horizontal)
        return False
