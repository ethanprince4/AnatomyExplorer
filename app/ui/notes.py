from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QSplitter, QVBoxLayout)

from . import theme


class NoteDialog(QDialog):
    def __init__(self, key, text, parent=None, save=None):
        super().__init__(parent)
        self.save_note = save
        self.setWindowTitle(f"Note · {key}")
        self.resize(520, 360)
        lay = QVBoxLayout(self)
        lab = QLabel(f"Your notes for <b>{key}</b> (saved locally, shown in the Details panel):")
        lay.addWidget(lab)
        self.edit = QPlainTextEdit(text)
        lay.addWidget(self.edit, 1)
        self.save_error = QLabel()
        self.save_error.setTextFormat(Qt.PlainText)
        self.save_error.setWordWrap(True)
        self.save_error.setStyleSheet(theme.text_css(theme.DANGER))
        self.save_error.hide()
        lay.addWidget(self.save_error)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.edit.setFocus()

    def text(self):
        return self.edit.toPlainText().strip()

    def accept(self):
        if self.save_note is not None:
            try:
                self.save_note(self.text())
            except OSError as exc:
                self.save_error.setText(f"Could not save note: {exc}")
                self.save_error.show()
                return
        super().accept()


class AllNotesDialog(QDialog):
    noteActivated = Signal(str)

    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My notes")
        self.resize(760, 480)
        self.content = content
        lay = QVBoxLayout(self)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        if not content.notes:
            # nothing to list: say how to make one rather than show two empty panes
            self.resize(460, 200)
            empty = QLabel("<p style='font-size:12pt'><b>No notes yet</b></p>"
                           "<p>Select a structure and press <b>N</b>, or right-click it and choose <i>Edit note for "
                           "selection</i>. Notes are saved on this computer and shown in the Details panel.</p>")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignCenter)
            lay.addWidget(empty, 1)
            lay.addWidget(box)
            return
        split = QSplitter()
        self.list = QListWidget()
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        split.addWidget(self.list)
        split.addWidget(self.view)
        split.setSizes([260, 500])
        lay.addWidget(split, 1)
        for key in sorted(content.notes, key=str.lower):
            QListWidgetItem(key, self.list)
        self.list.currentTextChanged.connect(lambda k: self.view.setPlainText(content.notes.get(k, "")))
        self.list.itemDoubleClicked.connect(lambda it: (self.noteActivated.emit(it.text()), self.accept()))
        self.list.setCurrentRow(0)
        hint = QLabel("Double-click a note to show that structure.")
        hint.setStyleSheet(theme.text_css(theme.MUTED))
        lay.addWidget(hint)
        lay.addWidget(box)
