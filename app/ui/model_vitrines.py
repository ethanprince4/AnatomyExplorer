"""Metadata-only catalogue using retained reference and installed-model renders."""
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QLabel, QListView, QListWidget, QStyle, QStyledItemDelegate

from . import theme

ENTRY_ROLE = Qt.UserRole + 1
ASSETS = Path(__file__).parent / "resources" / "studio"
PLATES = {"whole_heart": "heart_home_clean", "heart": "heart_home_clean", "kidney_nephron": "kidney_v_kidney",
          "cardiac_muscle": "cardiac_muscle"}


def specimen_image(entry):
    """Only an identity-matched geometry render may stand for a catalogue entry."""
    name = PLATES.get(entry.id, "thumb_" + entry.id)
    for folder in ("model-vitrines", "lesson-vitrines"):
        path = ASSETS / folder / (name + ".webp")
        if path.is_file():
            return QImage(str(path))
    return QImage()


class ModelSpecimenGrid(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.specimen_scale = 1.0
        self.setViewMode(QListView.IconMode)
        self.setMovement(QListView.Static)
        self.setResizeMode(QListView.Adjust)
        self.setWrapping(True)
        self.setSpacing(0)
        self.setGridSize(QSize(270, 288))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setStyleSheet("QListWidget,QListWidget::item,QListWidget::item:hover,QListWidget::item:selected "
                           "{background:transparent;border:0;padding:0;}")
        self.setItemDelegate(ModelSpecimenDelegate(self))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(1, self.contentsRect().width() - self.verticalScrollBar().sizeHint().width())
        columns = 4 if width >= 600 else 3 if width >= 390 else 2
        self.specimen_scale = max(.76, min(1.0, width / 1100))
        # QListView reserves the final edge pixel when wrapping icon-mode cells.
        # Reserve the scroll extent too: QListView wraps against it before the bar appears.
        size = QSize(max(100, (width - 20) // columns), round(176 * self.specimen_scale) + 112)
        if self.gridSize() != size:
            self.setGridSize(size)
            self.scheduleDelayedItemsLayout()


class ModelSpecimenDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.images = {}
        self.fitted_images = {}

    def image(self, entry):
        if entry.id not in self.images:
            self.images[entry.id] = specimen_image(entry)
        return self.images[entry.id]

    def sizeHint(self, option, index):
        return self.view.gridSize()

    def fitted_image(self, entry, width, height):
        # Wheel scrolling repaints the same specimens repeatedly. Resample only
        # when their display size changes, rather than during every paint.
        cached = self.fitted_images.get(entry.id)
        size = (width, height)
        if cached is None or cached[0] != size:
            fitted = self.image(entry).scaled(width, height, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation)
            cached = (size, fitted)
            self.fitted_images[entry.id] = cached
        return cached[1]

    def paint(self, painter, option, index):
        entry = index.data(ENTRY_ROLE)
        if entry is None:
            return
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        scale = self.view.specimen_scale
        bay = QRectF(rect.left() + 8, rect.top() + 4, rect.width() - 16, 176 * scale)
        pool = QRadialGradient(bay.center(), min(bay.width(), bay.height()) * .5)
        pool.setColorAt(0, theme.qc(theme.palette()["spot"], 180 if option.state & QStyle.State_MouseOver else 100))
        pool.setColorAt(1, theme.qc(theme.palette()["spot"], 0))
        painter.fillRect(bay, pool)
        image = self.image(entry)
        if not image.isNull():
            fitted = self.fitted_image(entry, round(bay.width() * .84), round(150 * scale))
            painter.drawImage(QRectF(bay.center().x() - fitted.width() / 2,
                                     bay.center().y() - fitted.height() / 2,
                                     fitted.width(), fitted.height()), fitted)
        if option.state & (QStyle.State_Selected | QStyle.State_HasFocus):
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(theme.qc(theme.ACCENT), 2))
            painter.drawRect(bay.adjusted(1, 1, -1, -1))
        painter.setFont(theme.font_for("caption", scale=scale))
        painter.setPen(theme.qc(theme.TEXT_STRONG))
        painter.drawText(QRectF(rect.left() + 4, bay.bottom() + 8, rect.width() - 8, 64),
                         Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, entry.name)
        # Keep the specimen caption to its name. The full authored description
        # belongs in the selected model's detail panel.
        painter.restore()


class ModelSpecimenPreview(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(180)
        self.setFixedHeight(340)
        self.setStyleSheet("background:transparent;border:0;")

    def set_entry(self, entry):
        self._image = specimen_image(entry) if entry is not None else QImage()
        self.setAccessibleName(entry.name + " specimen preview" if entry is not None else "Model specimen preview")
        self.update()

    def paintEvent(self, event):
        if self._image.isNull():
            return
        painter = QPainter(self)
        pool = QRadialGradient(QRectF(self.rect()).center(), min(self.width(), self.height()) * .48)
        pool.setColorAt(0, theme.qc(theme.palette()["spot"], 160))
        pool.setColorAt(1, theme.qc(theme.palette()["spot"], 0))
        painter.fillRect(self.rect(), pool)
        image = self._image.scaled(max(1, self.width() - 32), max(1, self.height() - 24),
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawImage(QRectF((self.width() - image.width()) / 2, (self.height() - image.height()) / 2,
                                 image.width(), image.height()), image)
        painter.end()
