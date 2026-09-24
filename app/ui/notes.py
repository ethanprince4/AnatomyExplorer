from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QSplitter, QVBoxLayout)


class NoteDialog(QDialog):
    def __init__(self, key, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Note · {key}")
        self.resize(520, 360)
        lay = QVBoxLayout(self)
        lab = QLabel(f"Your notes for <b>{key}</b> (saved locally, shown in the Details panel):")
        lay.addWidget(lab)
        self.edit = QPlainTextEdit(text)
        lay.addWidget(self.edit, 1)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.edit.setFocus()

    def text(self):
        return self.edit.toPlainText().strip()


class AllNotesDialog(QDialog):
    noteActivated = Signal(str)

    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My notes")
        self.resize(760, 480)
        self.content = content
        lay = QVBoxLayout(self)
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
        if not content.notes:
            self.view.setPlainText("No notes yet. Select a structure and press N (or right-click → Edit note).")
        self.list.currentTextChanged.connect(lambda k: self.view.setPlainText(content.notes.get(k, "")))
        self.list.itemDoubleClicked.connect(lambda it: (self.noteActivated.emit(it.text()), self.accept()))
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        lay.addWidget(QLabel("Double-click a note to show that structure."))
        lay.addWidget(box)
