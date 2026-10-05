"""Small native shell components. No models, image decoding or data writes."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout, QWidget)
from . import theme


class ElidingLabel(QLabel):
    """Keep the whole subject available to accessibility/tooltip while chrome shrinks."""
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setMinimumWidth(80)
        self.setTextFormat(Qt.PlainText)
        self.setText(text)

    def setText(self, text):
        self._full_text = str(text)
        self.setAccessibleName(self._full_text)
        self.setToolTip(self._full_text)
        self._update_text()

    def _update_text(self):
        super().setText(self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, max(80, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_text()


class WorkspaceNotice(QWidget):
    """A persistent, dismissible recovery message; never loses an error on a timer."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workspaceNotice")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        self.message = QLabel()
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.message, 1)
        self.action = QPushButton()
        self.action.clicked.connect(self._run)
        row.addWidget(self.action)
        dismiss = QPushButton("Dismiss")
        dismiss.setAccessibleName("Dismiss workspace message")
        dismiss.clicked.connect(self.hide)
        row.addWidget(dismiss)
        self._callback = None
        self.hide()

    def show_message(self, text, action_label=None, callback=None):
        self.message.setText(text)
        self.setAccessibleName(text)
        self._callback = callback
        self.action.setText(action_label or "")
        self.action.setVisible(bool(action_label and callback))
        self.show()

    def _run(self):
        callback = self._callback
        self.hide()
        if callback is not None:
            callback()


class CommandPalette(QDialog):
    """Search existing QActions and navigate with native list selection."""
    def __init__(self, commands, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find a command")
        self.resize(620, 480)
        self.setMinimumSize(420, 320)
        self._commands = commands
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search actions, workspaces or keyboard shortcuts…")
        self.query.setAccessibleName("Search application commands")
        self.query.setClearButtonEnabled(True)
        self.query.installEventFilter(self)
        layout.addWidget(self.query)
        self.results = QListWidget()
        self.results.setObjectName("commandResults")
        self.results.setAccessibleName("Matching application commands")
        self.results.itemActivated.connect(self._activate)
        layout.addWidget(self.results, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(theme.text_css(theme.MUTED))
        layout.addWidget(self.summary)
        self.query.textChanged.connect(self._filter)
        self._filter("")

    def showEvent(self, event):
        super().showEvent(event)
        self.query.setFocus(Qt.ShortcutFocusReason)
        self.query.selectAll()

    def _filter(self, query):
        self.results.clear()
        terms = query.casefold().split()
        for action in self._commands:
            if action.isSeparator() or not action.isVisible():
                continue
            title = action.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
            key = action.shortcut().toString()
            haystack = (title + " " + key + " " + action.toolTip()).casefold()
            if any(term not in haystack for term in terms):
                continue
            item = QListWidgetItem(title + ("    " + key if key else ""))
            item.setData(Qt.UserRole, action)
            item.setToolTip(action.toolTip() or title)
            if not action.isEnabled():
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.results.addItem(item)
        for row in range(self.results.count()):
            if self.results.item(row).flags() & Qt.ItemIsEnabled:
                self.results.setCurrentRow(row)
                break
        count = self.results.count()
        self.summary.setText((f"{count} commands · Up/down to choose · Enter to run · Esc to close" if count
                              else "No matching command. Try a workspace name, action or shortcut."))

    def eventFilter(self, obj, event):
        if obj is self.query and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Down, Qt.Key_Up):
                step = 1 if event.key() == Qt.Key_Down else -1
                row = self.results.currentRow() + step
                while 0 <= row < self.results.count():
                    if self.results.item(row).flags() & Qt.ItemIsEnabled:
                        self.results.setCurrentRow(row)
                        break
                    row += step
                return True
            if event.key() in (Qt.Key_Enter, Qt.Key_Return):
                self._activate(self.results.currentItem())
                return True
        return super().eventFilter(obj, event)

    def _activate(self, item):
        if item is None or not item.flags() & Qt.ItemIsEnabled:
            return
        action = item.data(Qt.UserRole)
        self.accept()
        if action is not None and action.isEnabled():
            action.trigger()
