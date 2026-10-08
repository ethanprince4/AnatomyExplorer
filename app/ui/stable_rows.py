"""Refill lists and dropdowns without removing their rows.

macOS keeps accessibility elements for the rows of every list and dropdown an assistive app has looked at, and
assistive apps include window managers, password managers and dictation as well as VoiceOver. Removing those
rows while the view is on screen or inside one of its own signals (QListWidget.clear, QComboBox.clear, takeItem)
can crash Qt's Cocoa accessibility bridge; it crashed v4.0.0 and v4.0.1 when a 3D model was chosen. These helpers
rewrite rows in place and hide the rows left over, so refreshing a view never deletes a row. Shown rows are always
the first ones, so row numbers below the returned count keep their usual meaning.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem


def fill_list(widget, values, fill):
    """Show one QListWidget row per value, rewritten by fill(item, value); return how many rows are shown.

    Rows are reused from the top and created only when the list is too short. fill must set every role it ever
    uses, since a reused row keeps whatever an earlier fill gave it."""
    shown = 0
    for shown, value in enumerate(values, 1):
        item = widget.item(shown - 1)
        if item is None:
            item = QListWidgetItem()
            widget.addItem(item)
        fill(item, value)
        item.setHidden(False)
    for row in range(shown, widget.count()):
        widget.item(row).setHidden(True)
    return shown


def fill_combo(combo, entries):
    """Show one QComboBox row per (text, data) entry; return how many rows are shown.

    Leftover rows are disabled and hidden, so keys and the wheel skip them. Tooltips are reset to each row's text."""
    for row, (text, data) in enumerate(entries):
        if row < combo.count():
            combo.setItemText(row, text)
            combo.setItemData(row, data)
        else:
            combo.addItem(text, data)
        combo.setItemData(row, text, Qt.ToolTipRole)
        combo.model().item(row).setEnabled(True)
        combo.view().setRowHidden(row, False)
    for row in range(len(entries), combo.count()):
        combo.model().item(row).setEnabled(False)
        combo.view().setRowHidden(row, True)
    return len(entries)
