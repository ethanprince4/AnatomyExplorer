"""Rebindable commands. Shortcuts are stored in QSettings under 'keybindings'."""
import json
import sys

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
    ("structure_labels", "Show structure labels", "Visibility", "", "", False),
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
    ("open_model_file", "Open a 3D model file", "3D models", "Ctrl+O", "", False),
    ("model_next_view", "Next view of the model", "3D models", "PgDown", "", False),
    ("model_prev_view", "Previous view of the model", "3D models", "PgUp", "", False),
    ("model_projection", "Perspective / flat projection", "3D models", "P", "", False),
    ("model_state", "Assembled / teased", "3D models", "T", "", False),
    ("model_play", "Play / pause the animation", "3D models", "Space", "", False),
]

# Qt reads Ctrl as Command on a Mac, where Command+Q quits, Command+H hides the app, F11 shows the desktop and
# Command+Shift+3/4/5 take screenshots, so those defaults never reach the app (or quit it). The Mac's Delete key
# sends Backspace, and Control+Command+F is its fullscreen key.
MAC = sys.platform == "darwin"
MAC_DEFAULTS = {
    "fullscreen": ("Meta+Ctrl+F", "F11"),
    "histology_tab": ("Meta+Ctrl+5", ""),
    "hide": ("H", "Backspace"),
    "quiz": ("Ctrl+Alt+Q", ""),
}
if MAC:
    ACTION_DEFS = [d[:3] + MAC_DEFAULTS.get(d[0], d[3:5]) + d[5:] for d in ACTION_DEFS]

# The workspace switcher's modifier: Control+Command on a Mac, whose Command+Shift+3/4/5 are screenshots.
WORKSPACE_MODIFIER = "Meta+Ctrl+" if MAC else "Ctrl+Shift+"
# Command+click adds to a selection on a Mac, where Control+click is a right-click.
SELECT_MODIFIER = "\N{PLACE OF INTEREST SIGN}" if MAC else "Ctrl"


def key_text(sequence):
    """A shortcut written the way this platform shows it: Ctrl+F on Windows, the Command symbols on a Mac."""
    return QKeySequence(sequence).toString(QKeySequence.NativeText)


def default_key_text(action_id):
    """The default primary shortcut of a command, as key_text writes it."""
    return key_text(next(d[3] for d in ACTION_DEFS if d[0] == action_id))


class ActionRegistry:
    def __init__(self, window, viewport, qsettings):
        self.window = window
        self.viewport = viewport
        self.qsettings = qsettings
        self.actions = {}
        self.defs = {d[0]: d for d in ACTION_DEFS}
        try:
            saved = json.loads(qsettings.value("keybindings", "{}"))
            self.overrides = {key: pair for key, pair in saved.items()
                              if isinstance(pair, list) and len(pair) == 2
                              and all(isinstance(value, str) for value in pair)} if isinstance(saved, dict) else {}
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
