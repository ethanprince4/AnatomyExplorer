"""Rebindable commands. Shortcuts are stored in QSettings under 'keybindings'."""
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence

# id, label, category, default primary, default secondary, viewport-only
ACTION_DEFS = [
    ("search", "Focus search box", "General", "Ctrl+F", "/", False),
    ("settings", "Open settings", "General", "Ctrl+,", "", False),
    ("screenshot", "Save screenshot", "General", "F12", "Ctrl+S", False),
    ("export_figure", "Export labelled figure", "General", "Ctrl+Shift+S", "", False),
    ("fullscreen", "Toggle fullscreen", "General", "F11", "", False),
    ("borderless", "Borderless window", "General", "Shift+F11", "", False),
    ("toggle_panels", "Hide / show side panels", "General", "Ctrl+B", "", False),
    ("escape", "Clear x-ray, then selection", "General", "Esc", "", False),
    ("back", "Previous item (history)", "General", "Alt+Left", "", False),
    ("forward", "Next item (history)", "General", "Alt+Right", "", False),
    ("save_view", "Save current view", "General", "Ctrl+D", "", False),
    ("histology_tab", "Open histology browser", "General", "Ctrl+H", "", False),
    ("frame", "Frame selection", "Camera", "F", "", False),
    ("reset_view", "Reset camera", "Camera", "Home", "", False),
    ("view_anterior", "Anterior view", "Camera", "1", "", False),
    ("view_posterior", "Posterior view", "Camera", "Ctrl+1", "", False),
    ("view_right", "Right lateral view", "Camera", "3", "", False),
    ("view_left", "Left lateral view", "Camera", "Ctrl+3", "", False),
    ("view_superior", "Superior view", "Camera", "7", "", False),
    ("view_inferior", "Inferior view", "Camera", "Ctrl+7", "", False),
    ("orbit_left", "Rotate left", "Camera", "Left", "A", True),
    ("orbit_right", "Rotate right", "Camera", "Right", "D", True),
    ("orbit_up", "Rotate up", "Camera", "Up", "W", True),
    ("orbit_down", "Rotate down", "Camera", "Down", "S", True),
    ("zoom_in", "Zoom in", "Camera", "=", "+", True),
    ("zoom_out", "Zoom out", "Camera", "-", "", True),
    ("auto_rotate", "Toggle auto-rotate", "Camera", "R", "", False),
    ("hide", "Hide selection", "Visibility", "H", "Delete", False),
    ("isolate", "Isolate selection", "Visibility", "I", "", False),
    ("xray", "Toggle x-ray around selection", "Visibility", "X", "", False),
    ("both_sides", "Select both sides", "Visibility", "B", "", False),
    ("show_all", "Show all", "Visibility", "Shift+H", "Alt+H", False),
    ("default_visibility", "Default visibility", "Visibility", "Ctrl+Shift+H", "", False),
    ("undo", "Undo visibility change", "Visibility", "Ctrl+Z", "", False),
    ("landmarks", "Toggle landmark labels", "Visibility", "L", "", False),
    ("measure", "Measure distances", "Visibility", "M", "", False),
    ("peel_in", "Dissect deeper", "Visibility", "]", "", False),
    ("peel_out", "Dissect shallower", "Visibility", "[", "", False),
    ("peel_reset", "Undo the dissection", "Visibility", "Ctrl+[", "", False),
    ("color_mode", "Cycle color mode", "Visibility", "C", "", False),
    ("clip_sagittal", "Toggle sagittal cross-section", "Visibility", "Ctrl+Alt+1", "", False),
    ("clip_coronal", "Toggle coronal cross-section", "Visibility", "Ctrl+Alt+2", "", False),
    ("clip_transverse", "Toggle transverse cross-section", "Visibility", "Ctrl+Alt+3", "", False),
    ("quiz", "Start / stop quiz mode", "Study", "Ctrl+Q", "", False),
    ("lessons", "Open guided lessons", "Study", "Ctrl+L", "", False),
    ("radiology", "Open radiology cases", "Study", "Ctrl+R", "", False),
    ("note", "Edit note for selection", "Study", "N", "", False),
]


class ActionRegistry:
    def __init__(self, window, viewport, qsettings):
        self.window = window
        self.viewport = viewport
        self.qsettings = qsettings
        self.actions = {}
        self.defs = {d[0]: d for d in ACTION_DEFS}
        try:
            self.overrides = json.loads(qsettings.value("keybindings", "{}"))
        except (TypeError, ValueError):
            self.overrides = {}

    def register(self, action_id, callback):
        d = self.defs[action_id]
        a = QAction(d[1], self.window)
        a.triggered.connect(callback)
        if d[5]:
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.viewport.addAction(a)
        else:
            a.setShortcutContext(Qt.WindowShortcut)
            self.window.addAction(a)
        self.actions[action_id] = a
        self._apply(action_id)
        return a

    def shortcuts(self, action_id):
        d = self.defs[action_id]
        primary, secondary = self.overrides.get(action_id, [d[3], d[4]])
        return primary, secondary

    def _apply(self, action_id):
        seqs = [QKeySequence(s) for s in self.shortcuts(action_id) if s]
        self.actions[action_id].setShortcuts(seqs)

    def set_shortcuts(self, action_id, primary, secondary):
        d = self.defs[action_id]
        if [primary, secondary] == [d[3], d[4]]:
            self.overrides.pop(action_id, None)
        else:
            self.overrides[action_id] = [primary, secondary]
        if action_id in self.actions:
            self._apply(action_id)
        self.qsettings.setValue("keybindings", json.dumps(self.overrides))

    def reset_all(self):
        self.overrides = {}
        for aid in self.actions:
            self._apply(aid)
        self.qsettings.setValue("keybindings", "{}")

    def label_with_shortcut(self, action_id):
        p, _ = self.shortcuts(action_id)
        return f"{self.defs[action_id][1]} ({QKeySequence(p).toString(QKeySequence.NativeText)})" if p else \
            self.defs[action_id][1]
