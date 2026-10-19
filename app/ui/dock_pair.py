"""The joined Labels / Show all control used in the model-viewer dock."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget



class LabelDockPair(QWidget):
    """A compact two-part control; the second action appears only while labels are enabled."""

    labelsToggled = Signal(bool)
    showAllClicked = Signal()
    layoutChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("labelDockPair")
        self.setAccessibleName("Model labels")
        self.setToolTip("Show numbered labels on visible anatomy")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.labels = QToolButton(self)
        self.labels.setText("Labels")
        self.labels.setCheckable(True)
        self.labels.setAccessibleName("Show anatomy labels")
        self.labels.toggled.connect(self.labelsToggled)
        row.addWidget(self.labels)
        self.show_all = QToolButton(self)
        self.show_all.setText("Show all")
        self.show_all.setAccessibleName("Show every label caption")
        self.show_all.setToolTip("Open a caption beside every visible label")
        self.show_all.clicked.connect(self.showAllClicked)
        row.addWidget(self.show_all)
        self.show_all.hide()
        self.labels.setObjectName("labelsPairMain")
        self.show_all.setObjectName("labelsPairAll")

    def set_labels_on(self, enabled):
        enabled = bool(enabled)
        old = self.labels.blockSignals(True)
        self.labels.setChecked(enabled)
        self.labels.blockSignals(old)
        self.show_all.setVisible(enabled)
        if not enabled:
            self.set_all_open(False)
        self.layout().invalidate()
        self.layout().activate()
        self.updateGeometry()
        self.layoutChanged.emit()

    def set_all_open(self, enabled):
        enabled = bool(enabled)
        self.show_all.setText("Hide all" if enabled else "Show all")
        self.show_all.setToolTip("Close every label caption" if enabled else
                                 "Open a caption beside every visible label")
        self.updateGeometry()
        self.layoutChanged.emit()

    def set_enabled_state(self, enabled):
        self.show_all.setEnabled(bool(enabled))
