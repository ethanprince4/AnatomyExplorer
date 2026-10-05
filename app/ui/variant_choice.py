"""Independent selection of one immutable model version at a time."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme

LABELS = {"pre": "Pre refine", "post": "Post refine"}


class VariantChoice(QWidget):
    requested = Signal(str)
    componentRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        layout = QHBoxLayout()
        layout.setSpacing(8)
        outer.addLayout(layout)
        label = QLabel("Version")
        label.setStyleSheet(theme.text_css(theme.TEXT_2, theme.FS_SMALL))
        self.choice = QComboBox()
        self.choice.setAccessibleName("Model version")
        self.choice.setAccessibleDescription("View Pre refine or Post refine, one version at a time")
        self.choice.setToolTip("Pre refine is the newly built model before microrefine. Post refine is its separate validated result.")
        self.choice.setMinimumContentsLength(12)
        self.choice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        label.setBuddy(self.choice)
        layout.addWidget(label)
        layout.addWidget(self.choice, 1)
        self.scene_row = QWidget()
        scenes = QHBoxLayout(self.scene_row)
        scenes.setContentsMargins(0, 0, 0, 0)
        scene_label = QLabel("Scene")
        scene_label.setStyleSheet(theme.text_css(theme.TEXT_2, theme.FS_SMALL))
        self.scene = QComboBox()
        self.scene.setAccessibleName("Axillary model scene")
        self.scene.setAccessibleDescription("Skin or enlarged cell inset in separate scene spaces, in the selected model version")
        scene_label.setBuddy(self.scene)
        scenes.addWidget(scene_label)
        scenes.addWidget(self.scene, 1)
        outer.addWidget(self.scene_row)
        self.scene.activated.connect(self._component_requested)
        self.result_status = QLabel()
        self.result_status.setTextFormat(Qt.PlainText)
        self.result_status.setWordWrap(True)
        self.result_status.setStyleSheet(theme.text_css(theme.TEXT_2, theme.FS_SMALL))
        outer.addWidget(self.result_status)
        self.choice.activated.connect(self._requested)
        self.set_entry(None)

    def set_entry(self, entry):
        """Metadata only. This control never loads, writes, or compares geometry."""
        local = bool(getattr(getattr(entry, "store", None), "is_local", False))
        labels = {"pre": "Before", "post": "After"} if local else LABELS
        self.choice.setAccessibleDescription("View Before or After, one version at a time" if local else "View Pre refine or Post refine, one version at a time")
        self.choice.setToolTip("Before is the source model. After is its saved refinement for your review." if local else "Pre refine is the newly built model before microrefine. Post refine is its separate validated result.")
        available = tuple(getattr(entry, "available_variants", ()))
        selected = getattr(entry, "variant", None)
        self._selected = selected
        components = tuple(getattr(entry, "available_components", ()))
        self._component = getattr(entry, "component", "main")
        self.scene.blockSignals(True)
        try:
            self.scene.clear()
            for component, title in (("main", "Skin"), ("cell_inset", "Cell inset")):
                if component in components:
                    self.scene.addItem(title, component)
            self.scene.setCurrentIndex(self.scene.findData(self._component))
        finally:
            self.scene.blockSignals(False)
        self.scene_row.setVisible(bool(components))
        no_change = selected == "post" and getattr(entry, "outcome", None) == "no_change"
        baseline = getattr(entry, "baseline_defects", None)
        pre_scope = selected == "pre" and getattr(entry, "validation_scope", None) == "source_technical_correspondence"
        text = "No changes from microrefine" if no_change else "Pre refine snapshot Â· technical integrity checked" if pre_scope else ""
        if pre_scope and baseline and baseline.get("findings"):
            text += " Â· Baseline defects recorded"
        self.result_status.setText(text)
        self.result_status.setVisible(bool(text))
        self.choice.blockSignals(True)
        try:
            self.choice.clear()
            for key, text in labels.items():
                self.choice.addItem(text, key)
                item = self.choice.model().item(self.choice.count() - 1)
                item.setEnabled(key in available)
                if key not in available:
                    item.setData("This version has not been imported into the local library." if local else "This validated version is not available. Run or resume the model preparation launcher.", Qt.ToolTipRole)
            self.choice.setCurrentIndex(self.choice.findData(selected))
        finally:
            self.choice.blockSignals(False)
        self.setVisible(entry is not None and bool(available))
        self.choice.setEnabled(bool(available))

    def _requested(self, index):
        variant = self.choice.itemData(index)
        if variant in LABELS and variant != self._selected and self.choice.model().item(index).isEnabled():
            self.requested.emit(variant)
            # A selection is only persisted after verification and preparation.
            # The loading tab names the requested version in the meantime.
            self.choice.setCurrentIndex(self.choice.findData(self._selected))

    def _component_requested(self, index):
        component = self.scene.itemData(index)
        if component and component != self._component:
            self.componentRequested.emit(component)
            self.scene.setCurrentIndex(self.scene.findData(self._component))
