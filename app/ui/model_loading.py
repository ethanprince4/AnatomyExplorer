"""Qt-owned delivery of CPU models, plus a small closeable pending tab."""
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from . import theme

from ..viewer.model_loading import ModelLoadQueue


class ModelLoader(QObject):
    finished = Signal(object)

    def __init__(self, parent=None, *, queue=None):
        super().__init__(parent)
        self.queue = queue if queue is not None else ModelLoadQueue()
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._poll)
        # Capture only the Python queue; a worker can outlive the deleted widget
        # without calling a dead QObject or preventing Qt-owned destruction.
        self.destroyed.connect(self.queue.close)

    def _owning_thread(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError('ModelLoader must be used on its owning Qt thread')

    def request(self, key, entry):
        self._owning_thread()
        serial = self.queue.request(key, entry)
        self.timer.start()
        return serial

    def cancel(self, key):
        self._owning_thread()
        self.queue.cancel(key)
        if not self.queue.pending:
            self.timer.stop()

    def close(self):
        self._owning_thread()
        self.timer.stop()
        self.queue.close()

    def _poll(self):
        self._owning_thread()
        result = self.queue.take_result()
        if not self.queue.pending:
            self.timer.stop()
        if result is not None:
            self.finished.emit(result)


class ModelLoadingTab(QWidget):
    """A cancellable pending tab, retaining a readable error and explicit retry."""
    cancelled = Signal()
    retryRequested = Signal()

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.setObjectName('modelLoadingTab')
        self.setStyleSheet('QWidget#modelLoadingTab { background: #141b22; }')
        self.entry = entry
        self.serial = None
        self.callbacks = []
        self.setAccessibleName(f"Loading {entry.name}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)
        layout.addStretch()
        self.title = QLabel()
        self.title.setTextFormat(Qt.PlainText)
        self.title.setWordWrap(True)
        self.title.setStyleSheet(theme.text_css("#eef3f6", theme.FS_H2, 600))
        layout.addWidget(self.title)
        self.note = QLabel()
        self.note.setTextFormat(Qt.PlainText)
        self.note.setWordWrap(True)
        self.note.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.note.setStyleSheet(theme.text_css("#c7d5df"))
        layout.addWidget(self.note)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("Model loading in progress")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(420)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.retry = QPushButton("Try again")
        self.retry.setObjectName("primary")
        self.retry.clicked.connect(self.retryRequested)
        actions.addWidget(self.retry)
        self.cancel = QPushButton("Cancel loading")
        self.cancel.clicked.connect(self.cancelled)
        actions.addWidget(self.cancel)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        self.set_loading()

    def set_loading(self):
        self.title.setText(f"Loading {self.entry.name} · {getattr(self.entry, 'label', '3D model')}…")
        self.note.setText("Preparing the model. You can keep using other tabs, or cancel this request.")
        self.setAccessibleName(f"Loading {self.entry.name}")
        self.progress.show()
        self.retry.hide()
        self.cancel.setText("Cancel loading")

    def set_error(self, message):
        self.title.setText(f"Could not open {self.entry.name}")
        self.note.setText(f"{message}\n\nTry again after the model files are available, or close this tab.")
        self.setAccessibleName(f"Model loading failed: {self.entry.name}")
        self.progress.hide()
        self.retry.show()
        self.cancel.setText("Close tab")
