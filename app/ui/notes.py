"""Local notes with explicit save feedback and searchable, keyboard-accessible reading."""
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from . import theme


class NoteDialog(QDialog):
    def __init__(self, key, text, parent=None, save=None):
        super().__init__(parent)
        self.save_note = save
        self._original = text.strip()
        self.setWindowTitle(f"Note · {key}")
        self.resize(600, 440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(12)
        title = QLabel(key)
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H2, 700))
        lay.addWidget(title)
        lab = QLabel("Saved on this computer and shown with the structure’s details.")
        lab.setWordWrap(True)
        lab.setStyleSheet(theme.text_css(theme.MUTED))
        lay.addWidget(lab)
        self.edit = QPlainTextEdit(text)
        self.edit.setAccessibleName(f"Notes for {key}")
        self.edit.setPlaceholderText("Write your observations, questions or study reminders…")
        lay.addWidget(self.edit, 1)
        self.save_error = QLabel()
        self.save_error.setTextFormat(Qt.PlainText)
        self.save_error.setWordWrap(True)
        self.save_error.setStyleSheet(theme.text_css(theme.DANGER))
        self.save_error.hide()
        lay.addWidget(self.save_error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Save).setText("Save note")
        theme.set_variant(self.buttons.button(QDialogButtonBox.Save), "primary")
        lay.addWidget(self.buttons)
        shortcut = QShortcut(QKeySequence.Save, self)
        shortcut.activated.connect(self.accept)
        self.edit.setFocus(Qt.OtherFocusReason)

    def text(self):
        return self.edit.toPlainText().strip()

    def accept(self):
        if self.save_note is not None:
            try:
                self.save_note(self.text())
            except OSError as exc:
                self.save_error.setText(f"The note could not be saved. Your text is still here. "
                                        f"Check available storage, then choose Save note to retry. {exc}")
                self.save_error.show()
                return
        super().accept()

    def reject(self):
        if self.text() != self._original:
            result = QMessageBox.question(self, "Discard unsaved note?",
                                          "Your changes have not been saved. Discard them?",
                                          QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
            if result != QMessageBox.Discard:
                return
        super().reject()


class AllNotesDialog(QDialog):
    noteActivated = Signal(str)

    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My notes")
        self.resize(820, 580)
        self.content = content
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(12)
        title = QLabel("My notes")
        title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H2, 700))
        lay.addWidget(title)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search structures and note text")
        self.search.setAccessibleName("Search my notes")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        self.search.returnPressed.connect(self._open_note)
        self.search.installEventFilter(self)
        lay.addWidget(self.search)
        self.count_label = QLabel()
        self.count_label.setStyleSheet(theme.text_css(theme.MUTED))
        lay.addWidget(self.count_label)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.list = QListWidget()
        self.list.setAccessibleName("Saved notes")
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMinimumWidth(120)
        self.list.currentItemChanged.connect(self._select_note)
        self.list.itemActivated.connect(lambda _item: self._open_note())
        self.split.addWidget(self.list)
        preview = QWidget()
        reading = QVBoxLayout(preview)
        reading.setContentsMargins(12, 0, 0, 0)
        self.note_title = QLabel()
        self.note_title.setTextFormat(Qt.PlainText)
        self.note_title.setWordWrap(True)
        self.note_title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_TITLE, 700))
        reading.addWidget(self.note_title)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setAccessibleName("Selected note text")
        reading.addWidget(self.view, 1)
        self.split.addWidget(preview)
        self.split.setSizes([280, 500])
        self.split.setStretchFactor(1, 1)
        lay.addWidget(self.split, 1)
        self.empty = QLabel()
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(theme.text_css(theme.TEXT_2))
        lay.addWidget(self.empty, 1)
        hint = QLabel("Select a structure and press N to write a note. Notes stay on this computer.")
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        lay.addWidget(hint)
        actions = QHBoxLayout()
        self.open_button = QPushButton("Show structure")
        self.open_button.clicked.connect(self._open_note)
        theme.set_variant(self.open_button, "primary")
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        actions.addWidget(box)
        lay.addLayout(actions)
        self._fill()
        self.search.setFocus(Qt.OtherFocusReason)

    def _fill(self, *_):
        selected = self.list.currentItem()
        current = selected.data(Qt.UserRole) if selected else None
        needle = self.search.text().casefold().split()
        notes = self.content.notes
        keys = [key for key in sorted(notes, key=str.casefold)
                if all(word in (key + " " + str(notes[key])).casefold() for word in needle)]
        self.list.clear()
        for key in keys:
            item = QListWidgetItem(key)
            item.setData(Qt.UserRole, key)
            self.list.addItem(item)
        self.count_label.setText(f"{len(keys)} of {len(notes)} notes")
        self.empty.setText("No notes yet. Select a structure, then press N to add your first note."
                           if not notes else "No notes match this search. Try another word or clear the search.")
        self.empty.setVisible(not keys)
        self.split.setVisible(bool(keys))
        self.open_button.setEnabled(bool(keys))
        if keys:
            self.list.setCurrentRow(keys.index(current) if current in keys else 0)
        else:
            self.note_title.clear()
            self.view.clear()

    def _select_note(self, current, _previous=None):
        key = current.data(Qt.UserRole) if current is not None else ""
        self.note_title.setText(key)
        self.view.setPlainText(str(self.content.notes.get(key, "")))
        if hasattr(self, "open_button"):
            self.open_button.setEnabled(bool(key))

    def _open_note(self):
        item = self.list.currentItem()
        if item is not None:
            self.noteActivated.emit(item.data(Qt.UserRole))
            self.accept()

    def eventFilter(self, obj, event):
        if obj is self.search and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Down and self.list.count():
            self.list.setFocus(Qt.TabFocusReason)
            return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "split"):
            orientation = Qt.Vertical if self.width() < 640 else Qt.Horizontal
            if self.split.orientation() != orientation:
                self.split.setOrientation(orientation)
                self.split.setSizes([120, 280] if orientation == Qt.Vertical else [260, 500])
