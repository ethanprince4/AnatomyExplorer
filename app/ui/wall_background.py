"""Sample the single gallery wall at a native viewport's position.

The header and instruments inherit the shell's wall. GPU canvases must sample
that same vertical interval, rather than restart the gradient at their top.
"""
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor


def viewport_background(widget, settings):
    result = dict(settings)
    if not settings.get("custom_background"):
        return result
    root = widget.parentWidget()
    while root is not None and root.objectName() != "studioShell":
        root = root.parentWidget()
    if root is None:
        return result
    y = widget.mapTo(root, QPoint(0, 0)).y()
    height = max(1, root.height())
    top = QColor(settings["bg_top"])
    bottom = QColor(settings["bg_bottom"])

    def colour(at):
        fraction = max(0., min(1., at / height))
        return QColor(*(round(a + (b-a)*fraction) for a, b in
                        zip(top.getRgb()[:3], bottom.getRgb()[:3]))).name()

    result["bg_top"] = colour(y)
    result["bg_bottom"] = colour(y + widget.height())
    return result
