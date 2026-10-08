"""Explicit static function-step navigation for a verified selected model."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QVBoxLayout, QWidget, QHBoxLayout, QPushButton

from . import theme
from .flow import FlowLayout, WrapButton
from .stable_rows import fill_combo


class ModelTeachingControls(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = None
        self.sequences = []
        self.steps = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        header=QHBoxLayout()
        title=QLabel("Function")
        title.setObjectName('studioCardTitle')
        header.addWidget(title);header.addStretch()
        close=QPushButton("×")
        close.setObjectName('headerClose')
        close.setAccessibleName('Close function controls')
        close.clicked.connect(self._close)
        header.addWidget(close)
        layout.addLayout(header)
        row = QGridLayout()
        self.sequence = QComboBox()
        self.sequence.setAccessibleName("Model function sequence")
        self.sequence.setMinimumContentsLength(12)
        self.sequence.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.step = QComboBox()
        self.step.setAccessibleName("Function step")
        self.step.setMinimumContentsLength(12)
        self.step.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.previous = WrapButton("Previous")
        self.next = WrapButton("Next")
        self.apply = WrapButton("Show step")
        self.apply.setMinimumWidth(140)
        self.overview = WrapButton("Overview")
        row.addWidget(QLabel("Function"), 0, 0)
        row.addWidget(self.sequence, 0, 1)
        row.addWidget(QLabel("Step"), 1, 0)
        row.addWidget(self.step, 1, 1)
        row.setColumnStretch(1, 1)
        layout.addLayout(row)
        self.actions = QWidget(self)
        actions = FlowLayout(self.actions, spacing=6)
        for button in (self.previous, self.next, self.apply, self.overview):
            actions.addWidget(button)
        layout.addWidget(self.actions)
        self.caption = QLabel()
        self.caption.setTextFormat(Qt.PlainText)
        self.caption.setWordWrap(True)
        self.caption.setAccessibleName("Selected function explanation and scale")
        self.caption.setStyleSheet(theme.text_css(theme.TEXT_2, theme.FS_SMALL))
        layout.addWidget(self.caption)
        self.sequence.activated.connect(self._sequence_activated)
        self.step.activated.connect(lambda _: self.show_step())
        self.previous.clicked.connect(lambda: self._advance(-1))
        self.next.clicked.connect(lambda: self._advance(1))
        self.apply.clicked.connect(self.show_step)
        self.overview.clicked.connect(self.show_overview)
        self.hide()

    def _close(self):
        scene=self.parentWidget()
        if hasattr(scene,'function'):scene.function.setChecked(False)
        else:self.hide()

    def set_session(self, session):
        self.session = session
        self.sequences = [record for record in session.controls.get("functional_sequences", ())
                          if record.get("id") and isinstance(record.get("steps", record.get("stages")), list)]
        fill_combo(self.sequence, [(record.get("title") or record.get("name") or record.get("mechanism") or record["id"],
                                    record["id"]) for record in self.sequences])
        self.sequence.setCurrentIndex(0 if self.sequences else -1)
        self._fill_steps()
        self.setVisible(bool(self.sequences))

    def _fill_steps(self):
        # Runs inside the sequence combo's activated signal with the step combo on screen: rows are rewritten,
        # never removed (see stable_rows).
        steps = []
        index = self.sequence.currentIndex()
        if 0 <= index < len(self.sequences):
            record = self.sequences[index]
            for i, value in enumerate(record.get("steps", record.get("stages", ()))):
                title = (value.get("title") or value.get("label") or value.get("name") or value.get("id")) if isinstance(value, dict) else str(value)
                steps.append((f"{i + 1}. {title or 'Step ' + str(i + 1)}", i))
        self.steps = fill_combo(self.step, steps)
        self.step.setCurrentIndex(0 if self.steps else -1)
        self._sync()

    def _sync(self):
        index = self.step.currentIndex()
        self.previous.setEnabled(index > 0)
        self.next.setEnabled(0 <= index < self.steps - 1)
        self.apply.setEnabled(index >= 0)

    def _sequence_activated(self, *_):
        self._fill_steps()
        self.show_step()

    def _advance(self, direction):
        index = self.step.currentIndex() + direction
        if 0 <= index < self.steps:
            self.step.setCurrentIndex(index)
            self.show_step()

    def _explain(self, result):
        if isinstance(result, dict):
            self.caption.setText(" · ".join(str(result[key]) for key in ("title", "caption", "scale_note") if result.get(key)))
        else:
            self.caption.setText(str(result or ""))
        self._sync()

    def show_step(self):
        if self.session is None or self.step.currentIndex() < 0:
            return
        try:
            self._explain(self.session.function(self.sequence.currentData(), self.step.currentIndex()))
        except (OSError, ValueError, RuntimeError, KeyError, IndexError, StopIteration) as exc:
            self.caption.setText(f"This function step could not open: {exc}. Choose Overview to return to the opening view.")
            self._sync()

    def show_overview(self):
        if self.session is None:
            return
        try:
            self._explain(self.session.opening())
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self.caption.setText(f"The opening view could not be restored: {exc}.")
