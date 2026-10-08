"""Native two-dimensional image-workspace helpers. No renderer or model access."""
import math
from pathlib import Path
from threading import Event

from PySide6.QtCore import QEvent, QObject, QRunnable, QThreadPool, Signal, Slot, Qt
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget


_IMAGE_POOL = QThreadPool()
_IMAGE_POOL.setMaxThreadCount(2)


def trackpad_scroll(event):
    """True for a trackpad swipe, which pans an image as in other image viewers; a mouse wheel zooms. macOS gives
    every trackpad scroll (and its momentum after the fingers lift) a phase, Linux a pixel delta; a wheel has
    neither. Windows touchpads report neither and keep zooming, as before."""
    return event.phase() != Qt.NoScrollPhase or not event.pixelDelta().isNull()


def pinch_steps(event, base):
    """Zoom steps, in powers of base, for a trackpad pinch; None for any other event."""
    if event.type() == QEvent.NativeGesture and event.gestureType() == Qt.ZoomNativeGesture:
        return math.log1p(max(-0.9, event.value())) / math.log(base)    # value() is this event's change in scale
    return None


class _ImageResult(QObject):
    ready = Signal(int, object, str)


class _ReadImage(QRunnable):
    def __init__(self, serial, path, result, cancelled):
        super().__init__()
        self.serial, self.path, self.result = serial, path, result
        self.cancelled = cancelled

    def run(self):
        if self.cancelled.is_set():
            return
        image, error = QImage(), ""
        try:
            if not self.path.is_file():
                error = "Image file is missing. Restore the installed image files, then retry."
            else:
                reader = QImageReader(str(self.path))
                # Preserve source orientation and pixel colours, matching the existing viewer.
                image = reader.read()
                if image.isNull():
                    error = "This image could not be read. Restore the image file, then retry."
        except (OSError, ValueError, RuntimeError):
            error = "This image could not be opened. Check the local image files, then retry."
        if self.cancelled.is_set():
            return
        try:
            self.result.ready.emit(self.serial, image, error)
        except RuntimeError:
            pass  # The owner was closed while the local image was being decoded.


class LocalImageLoader(QObject):
    """Decode QImage off the GUI thread; a newer request always wins.

    The worker only reads a local image. QPixmap conversion remains on the GUI
    thread. Results cannot access a deleted viewer or replace a newer selection.
    """
    loaded = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial = 0
        self._cancelled = Event()
        self._result = _ImageResult(self)
        self._result.ready.connect(self._receive, Qt.QueuedConnection)

    def load(self, path):
        self.cancel()
        self._cancelled = Event()
        _IMAGE_POOL.start(_ReadImage(self._serial, Path(path), self._result, self._cancelled))

    def cancel(self):
        self._cancelled.set()
        self._serial += 1

    @Slot(int, object, str)
    def _receive(self, serial, image, error):
        if serial == self._serial:
            self.loaded.emit(image, error)


def control(text, name, tooltip="", parent=None):
    """A compact native control with a useful accessible name and no fixed width."""
    button = QPushButton(text, parent)
    button.setAccessibleName(name)
    button.setToolTip(tooltip or name)
    button.setMinimumHeight(30)
    button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return button


def searchable_text(*parts):
    return " ".join(str(part or "") for part in parts).casefold()


def matches_words(query, text):
    """Order-independent terms: 'kidney ct' finds the authored CT kidney case."""
    haystack = text.casefold()
    return all(word in haystack for word in query.strip().casefold().split())


CARD_TEXT = "#24343d"
CARD_MUTED = "#526570"

def image_control_card(layout, name):
    """Opaque controls above the dark image canvas, independent of app theme."""
    card = QWidget()
    card.setObjectName(name)
    card.setAttribute(Qt.WA_StyledBackground, True)
    card.setStyleSheet(f"""
        QWidget#{name} {{ background: #f8fafb; color: {CARD_TEXT};
            border: 1px solid #cbd5db; border-radius: 12px; }}
        QWidget#{name} QLabel, QWidget#{name} QCheckBox {{
            background: transparent; color: {CARD_TEXT}; border: none; }}
        QWidget#{name} QPushButton, QWidget#{name} QComboBox {{
            background: #ffffff; color: {CARD_TEXT}; border: 1px solid #cbd5db;
            border-radius: 6px; padding: 5px 9px; }}
        QWidget#{name} QPushButton:hover {{ background: #e5eef2; }}
        QWidget#{name} QPushButton:disabled {{ color: #76858e; }}
    """)
    layout.setContentsMargins(12, 9, 12, 9)
    card.setLayout(layout)
    return card
