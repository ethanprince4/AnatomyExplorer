"""Saved atlas views, using the host's existing storage and restoration contract.

The dialog never opens QSettings or interprets camera/renderer state. Metadata is
an explanatory preview of the saved record; apply_view remains its validator.
"""
from copy import deepcopy
from datetime import datetime

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFormLayout, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from . import theme


def _count(value):
    return len(value) if isinstance(value, list) else 0


def _created(view):
    value = view.get("created")
    if isinstance(value, str):
        try:
            date = datetime.fromisoformat(value)
            return date.strftime("%d %b %Y, %H:%M")
        except ValueError:
            pass
    return "Not recorded"


def _metadata(view):
    """Read only known fields; retain unknown fields untouched when editing."""
    data = view["data"]
    selected = _count(data.get("selected"))
    hidden = _count(data.get("hidden"))
    isolated = data.get("isolated")
    clip = data.get("clip")
    planes = (sum(value is True or value == 1 for value in clip[0])
              if isinstance(clip, list) and clip and isinstance(clip[0], list) else 0)
    return [
        ("Saved", _created(view)),
        ("Selection", f"{selected} structure" + ("" if selected == 1 else "s")),
        ("Hidden", f"{hidden} structure" + ("" if hidden == 1 else "s")),
        ("Isolation", "Off" if isolated is None else
         f"{_count(isolated)} structure" + ("" if _count(isolated) == 1 else "s")),
        ("Cutting planes", str(planes)),
        ("Slice-only view", "On" if data.get("radiology_slice") is True else "Off"),
    ]


class SavedViewsDialog(QDialog):
    """Browse, find, preview and manage records supplied by a MainWindow."""

    def __init__(self, window):
        super().__init__(window)
        self.host = window
        self._views = []
        self.setObjectName("savedViewsDialog")
        self.setWindowTitle("Saved views")
        self.setAccessibleName("Saved atlas views")
        self.resize(820, 560)
        self.setMinimumSize(600, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)
        heading = self._label("Saved views", theme.TEXT_STRONG, theme.FS_H2, 600)
        layout.addWidget(heading)
        hint = self._label("Return to a saved atlas camera, selection and visibility setup.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("savedViewsSearch")
        self.search.setAccessibleName("Search saved views")
        self.search.setPlaceholderText("Search views by name or saved date")
        self.search.setClearButtonEnabled(True)
        self.search.installEventFilter(self)
        self.search.textChanged.connect(self._filter)
        search_row.addWidget(self.search, 1)
        self.save_button = self._button("Save current view…", self._save_current)
        self.save_button.setToolTip("Save the current atlas setup with a name")
        search_row.addWidget(self.save_button)
        layout.addLayout(search_row)

        self.summary = self._label("", theme.MUTED, theme.FS_SMALL)
        self.summary.setAccessibleName("Saved view results")
        layout.addWidget(self.summary)

        self.body = QStackedWidget()
        layout.addWidget(self.body, 1)
        results = QWidget()
        result_layout = QHBoxLayout(results)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(20)
        self.list = QListWidget()
        self.list.setObjectName("savedViewsList")
        self.list.setAccessibleName("Saved views")
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setStyleSheet(f"QListWidget::item {{ padding: 10px 12px; }} "
                               f"QListWidget::item:focus {{ border: 1px solid {theme.ACCENT}; }}")
        self.list.currentItemChanged.connect(self._preview)
        self.list.itemActivated.connect(self._open_selected)
        self.list.installEventFilter(self)
        result_layout.addWidget(self.list, 5)

        preview = QWidget()
        preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setFrameShape(QFrame.NoFrame)
        self.preview_scroll.setAccessibleName("Saved view details")
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        detail = QWidget()
        detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 8, 8)
        detail_layout.setSpacing(12)
        self.preview_title = self._label("Choose a saved view", theme.TEXT_STRONG, theme.FS_TITLE, 600)
        self.preview_title.setWordWrap(True)
        self.preview_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_layout.addWidget(self.preview_title)
        self.preview_hint = self._label("Select a view to inspect its saved setup.")
        self.preview_hint.setWordWrap(True)
        detail_layout.addWidget(self.preview_hint)
        self.metadata_widget = QWidget()
        self.metadata_form = QFormLayout(self.metadata_widget)
        self.metadata_form.setContentsMargins(0, 4, 0, 0)
        self.metadata_form.setHorizontalSpacing(16)
        self.metadata_form.setVerticalSpacing(12)
        self.metadata_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.metadata_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.metadata_labels = {}
        for name, _ in _metadata({"data": {}}):
            value = self._label("")
            value.setWordWrap(True)
            self.metadata_form.addRow(self._label(name, theme.MUTED, theme.FS_SMALL), value)
            self.metadata_labels[name] = value
        detail_layout.addWidget(self.metadata_widget)
        detail_layout.addStretch(1)
        self.preview_scroll.setWidget(detail)
        preview_layout.addWidget(self.preview_scroll, 1)
        selected_actions = QHBoxLayout()
        self.rename_button = self._button("Rename…", self._rename_selected)
        self.delete_button = self._button("Delete…", self._delete_selected)
        self.delete_button.setToolTip("Delete this saved view after confirmation")
        selected_actions.addWidget(self.rename_button)
        selected_actions.addStretch(1)
        selected_actions.addWidget(self.delete_button)
        preview_layout.addLayout(selected_actions)
        result_layout.addWidget(preview, 6)
        self.body.addWidget(results)

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.addStretch(1)
        self.empty_title = self._label("", theme.TEXT_STRONG, theme.FS_TITLE, 600)
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_title.setWordWrap(True)
        self.empty_message = self._label("")
        self.empty_message.setWordWrap(True)
        self.empty_message.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_message)
        self.clear_button = self._button("Clear search", self.search.clear)
        empty_layout.addWidget(self.clear_button, 0, Qt.AlignHCenter)
        empty_layout.addStretch(1)
        self.body.addWidget(empty)

        footer = QHBoxLayout()
        self.close_button = self._button("Close", self.reject)
        footer.addWidget(self.close_button)
        footer.addStretch(1)
        self.open_button = self._button("Open view", self._open_selected)
        theme.set_variant(self.open_button, "primary")
        self.open_button.setToolTip("Restore the selected atlas setup and close this dialog")
        footer.addWidget(self.open_button)
        layout.addLayout(footer)
        self.refresh()
        self.search.setFocus()

    @staticmethod
    def _label(text, color=None, size=None, weight=None):
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setStyleSheet(theme.text_css(color or theme.TEXT_2, size, weight))
        return label

    @staticmethod
    def _button(text, callback):
        button = QPushButton(text)
        button.setAutoDefault(False)
        button.clicked.connect(callback)
        return button

    def refresh(self, preferred=None, row=0):
        """Reload host storage and retain a surviving selection where possible."""
        if preferred is None:
            preferred = self._current_view()
        self._views = deepcopy(self.host._saved_views())
        self._filter(preferred=preferred, row=row)

    def _current_view(self):
        item = self.list.currentItem()
        index = item.data(Qt.UserRole) if item is not None else None
        return self._views[index] if type(index) is int and 0 <= index < len(self._views) else None

    def _filter(self, _text=None, *, preferred=None, row=0):
        preferred = preferred if preferred is not None else self._current_view()
        words = self.search.text().casefold().split()
        self.list.blockSignals(True)
        self.list.clear()
        selected_row = None
        for index, view in sorted(enumerate(self._views), key=lambda pair: pair[1]["name"].casefold()):
            searchable = " ".join([view["name"], str(view.get("created", "")), _created(view)]).casefold()
            if not all(word in searchable for word in words):
                continue
            item = QListWidgetItem(view["name"] or "Untitled view")
            item.setData(Qt.UserRole, index)
            item.setToolTip(view["name"] + "\nSaved: " + _created(view))
            item.setData(Qt.AccessibleDescriptionRole, "Saved " + _created(view))
            self.list.addItem(item)
            if view == preferred:
                selected_row = self.list.count() - 1
        count, total = self.list.count(), len(self._views)
        if count:
            self.list.setCurrentRow(selected_row if selected_row is not None else min(row, count - 1))
        self.list.blockSignals(False)
        self.summary.setText((f"{count} of {total} saved views" if words else
                              f"{total} saved view" + ("" if total == 1 else "s")))
        self.body.setCurrentIndex(0 if count else 1)
        self.empty_title.setText("No matching views" if total else "Keep a useful view for later")
        self.empty_message.setText("Try another name or saved date, or clear your search." if total else
                                   "Set up the atlas, then choose Save current view to keep its camera, "
                                   "selection and visibility settings.")
        self.clear_button.setVisible(bool(words))
        self._preview()

    def _preview(self, *_args):
        view = self._current_view()
        for button in (self.open_button, self.rename_button, self.delete_button):
            button.setEnabled(view is not None)
        self.metadata_widget.setVisible(view is not None)
        self.preview_title.setText(view["name"] if view is not None else "Choose a saved view")
        self.preview_hint.setText("Opening restores this saved atlas setup." if view is not None else
                                 "Select a view to inspect its saved setup.")
        if view is not None:
            for name, value in _metadata(view):
                self.metadata_labels[name].setText(value)
        self.preview_scroll.verticalScrollBar().setValue(0)

    def _selected(self):
        """Resolve the snapshot against fresh storage before any action."""
        view = self._current_view()
        if view is None:
            return [], None
        views = deepcopy(self.host._saved_views())
        index = self.list.currentItem().data(Qt.UserRole)
        if index < len(views) and views[index] == view:
            return views, index
        matches = [i for i, candidate in enumerate(views) if candidate == view]
        if len(matches) == 1:
            return views, matches[0]
        self.refresh()
        QMessageBox.information(self, "Saved view changed", "This saved view changed or was removed. "
                                "Select it again from the updated list.")
        return views, None

    def _store(self, views):
        try:
            self.host._store_views(views)
        except (OSError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Could not save changes", str(error))
            return False
        return True

    def _open_selected(self, *_args):
        views, index = self._selected()
        if index is not None:
            opener = getattr(self.host, "open_saved_view", self.host.apply_view)
            opener(views[index]["data"])
            self.accept()

    def _rename_selected(self):
        views, index = self._selected()
        if index is None:
            return
        original = views[index]
        name, ok = QInputDialog.getText(self, "Rename view", "Name:", text=original["name"])
        name = name.strip()
        if not ok or not name or name == original["name"]:
            return
        # The prompt may have admitted nested events; check fresh storage again.
        views, index = self._selected()
        if index is None:
            return
        if any(view["name"] == name for i, view in enumerate(views) if i != index):
            QMessageBox.warning(self, "Name already used", "A saved view with that name already exists. "
                                "Choose another name.")
            return
        views[index]["name"] = name
        if self._store(views):
            self.refresh(preferred=views[index])
            if self._current_view() != views[index]:
                # A name search must not make a successfully renamed view vanish.
                self.search.blockSignals(True)
                self.search.clear()
                self.search.blockSignals(False)
                self.refresh(preferred=views[index])

    def _delete_selected(self):
        views, index = self._selected()
        if index is None:
            return
        answer = QMessageBox.question(self, "Delete saved view?",
                                      f'Delete “{views[index]["name"]}”?\n\n'
                                      "This removes the saved setup. The current atlas view stays unchanged.",
                                      QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        views, index = self._selected()
        if index is None:
            return
        row = self.list.currentRow()
        views.pop(index)
        if self._store(views):
            self.refresh(row=row)

    def _save_current(self):
        before = deepcopy(self.host._saved_views())
        self.host.save_view_dialog()
        after = self.host._saved_views()
        changed = [view for view in after if view not in before]
        if changed:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        self.refresh(preferred=changed[-1] if changed else None)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if watched is self.search and key in (Qt.Key_Up, Qt.Key_Down):
                if self.list.count():
                    delta = 1 if key == Qt.Key_Down else -1
                    self.list.setCurrentRow(max(0, min(self.list.count() - 1, self.list.currentRow() + delta)))
                return True
            if watched in (self.search, self.list) and key in (Qt.Key_Return, Qt.Key_Enter):
                self._open_selected()
                return True
        return super().eventFilter(watched, event)
