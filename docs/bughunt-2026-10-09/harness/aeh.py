# Helper injected into a scripted Anatomy Explorer instance (via eval). Defines builtins.H.
import builtins, json, sys, traceback
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (QApplication, QAbstractButton, QLineEdit, QTextEdit, QPlainTextEdit,
                               QComboBox, QTabBar, QAbstractItemView, QLabel, QSlider, QSpinBox, QWidget)
from PySide6.QtTest import QTest

KEYS = {k[4:].lower(): getattr(Qt.Key, k) for k in dir(Qt.Key) if k.startswith("Key_")}


class _H:
    def __init__(self, w, out):
        self.w, self.out = w, out

    def log(self, msg):
        with open(self.out + "/helper.log", "a") as f:
            f.write(msg + "\n")

    def overlay(self):
        from PySide6.QtWidgets import QDialog
        o = QApplication.activePopupWidget() or QApplication.activeModalWidget()
        if o is None:
            dialogs = [x for x in QApplication.topLevelWidgets() if isinstance(x, QDialog) and x.isVisible()]
            o = dialogs[-1] if dialogs else None
        return o

    def top(self):
        return self.overlay() or self.w

    def _label(self, x):
        for attr in ("text", "currentText", "windowTitle", "placeholderText", "title"):
            try:
                v = getattr(x, attr)()
                if v:
                    return str(v).replace("\n", " ")[:60]
            except Exception:
                pass
        n = x.accessibleName() or x.toolTip() or ""
        if not n:
            kids = [c.text() for c in x.findChildren(QLabel) if c.isVisible() and c.text()][:3]
            n = " / ".join(kids)
        return (n or x.objectName() or "")[:60]

    def _frac(self, x, root):
        p = x.mapTo(root, QPoint(0, 0)) if root.isAncestorOf(x) else x.mapToGlobal(QPoint(0, 0)) - root.mapToGlobal(QPoint(0, 0))
        W, Hh = max(root.width(), 1), max(root.height(), 1)
        return (round((p.x() + x.width() / 2) / W, 3), round((p.y() + x.height() / 2) / Hh, 3))

    def dump(self, name):
        root = self.top()
        rows = []
        from PySide6.QtWidgets import QMenu
        if isinstance(root, QMenu):
            for a in root.actions():
                if a.isVisible():
                    rows.append("menuitem       %-60s%s%s" % (repr(a.text().replace("&", "")), "" if a.isEnabled() else " DISABLED",
                                                                 " checked" if a.isChecked() else ""))
        for x in root.findChildren(QWidget):
            if not x.isVisible() or x.width() < 4 or x.height() < 4:
                continue
            if not self._clickable(x):
                continue
            cx, cy = self._frac(x, root)
            if not (0 <= cx <= 1 and 0 <= cy <= 1):
                continue
            extra = ""
            if isinstance(x, QAbstractButton) and x.isCheckable():
                extra = " checked" if x.isChecked() else " unchecked"
            if isinstance(x, QComboBox):
                extra = " items=" + "|".join(x.itemText(i) for i in range(min(x.count(), 12)))
            if isinstance(x, QTabBar):
                extra = " tabs=" + "|".join(x.tabText(i) for i in range(x.count()) if x.isTabVisible(i))
            if isinstance(x, QAbstractItemView) and x.model() is not None:
                extra = " rows=%d" % x.model().rowCount()
            rows.append("%-14s %-60s @%.3f,%.3f%s%s" % (type(x).__name__, repr(self._label(x)), cx, cy,
                                                        "" if x.isEnabled() else " DISABLED", extra))
            if isinstance(x, QAbstractItemView):
                for txt, vp, rect in self._items(x)[:60]:
                    c = vp.mapTo(root, rect.center()) if root.isAncestorOf(vp) else rect.center()
                    rows.append("  row          %-60s @%.3f,%.3f" % (repr(txt[:60]), c.x() / root.width(), c.y() / root.height()))
        with open("%s/%s.txt" % (self.out, name), "w") as f:
            f.write("root=%s %r size=%dx%d\n" % (type(root).__name__, self._label(root), root.width(), root.height()))
            f.write("\n".join(rows) + "\n")

    def _clickable(self, x):
        if isinstance(x, (QAbstractButton, QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QTabBar,
                          QAbstractItemView, QSlider, QSpinBox)):
            return True
        if isinstance(x, QLabel) and "<a" in (x.text() or ""):
            return True
        return x.testAttribute(Qt.WA_SetCursor) and x.cursor().shape() == Qt.PointingHandCursor

    def _find(self, text):
        root = self.top()
        cands = [x for x in root.findChildren(QWidget) if x.isVisible() and self._clickable(x)]
        t = text.lower()
        for exact in (True, False):
            for x in cands:
                labs = [self._label(x).lower(), (x.accessibleName() or "").lower()]
                tip = (x.toolTip() or "").lower()
                if any((l == t) if exact else (t in l) for l in labs if l) or (exact and tip == t):
                    return x
        return None

    def _items(self, view):
        m, vp, out = view.model(), view.viewport(), []
        if m is None:
            return out
        def walk(parent, depth):
            for r in range(min(m.rowCount(parent), 400)):
                idx = m.index(r, 0, parent)
                rect = view.visualRect(idx)
                if rect.isValid() and rect.height() > 0 and vp.rect().intersects(rect):
                    txt = m.data(idx) or m.data(idx, Qt.AccessibleTextRole) or m.data(idx, Qt.ToolTipRole) or ""
                    if not isinstance(txt, str):
                        txt = ""
                    if not txt:
                        ud = m.data(idx, Qt.UserRole)
                        txt = getattr(ud, "title", None) or getattr(ud, "name", None) or (ud if isinstance(ud, str) else "")
                    out.append((str(txt).replace("\n", " "), vp, rect))
                if depth < 4 and m.rowCount(idx) > 0 and (not hasattr(view, "isExpanded") or view.isExpanded(idx)):
                    walk(idx, depth + 1)
        walk(view.rootIndex(), 0)
        return out

    def _find_item(self, text):
        t = text.lower()
        views = [v for v in self.top().findChildren(QAbstractItemView) if v.isVisible()]
        for exact in (True, False):
            for v in views:
                for txt, vp, rect in self._items(v):
                    if (txt.lower() == t) if exact else (t in txt.lower()):
                        return vp, rect
        return None

    def press(self, text, kind="click"):
        from PySide6.QtWidgets import QMenu
        menu = QApplication.activePopupWidget()
        if isinstance(menu, QMenu):
            t = text.lower()
            acts = [a for a in menu.actions() if a.isVisible() and a.text()]
            a = next((a for a in acts if a.text().replace("&", "").lower() == t), None) or \
                next((a for a in acts if t in a.text().replace("&", "").lower()), None)
            if a is not None:
                if a.menu() is not None:
                    menu.setActiveAction(a)
                    a.menu().popup(menu.mapToGlobal(menu.actionGeometry(a).topRight()))
                    self.log("press: opened submenu %r" % text)
                else:
                    menu.close()
                    a.trigger()
                    self.log("press: ok menu item %r" % text)
                return
        x = self._find(text)
        if x is None:
            t = text.lower()
            for bar in [b for b in self.top().findChildren(QTabBar) if b.isVisible()]:
                for i in range(bar.count()):
                    lab = bar.tabText(i).replace("&", "").lower()
                    if bar.isTabVisible(i) and (lab == t or t in lab):
                        QTest.mouseClick(bar, Qt.LeftButton, Qt.NoModifier, bar.tabRect(i).center())
                        self.log("press: ok tab %r" % text)
                        return
            it = self._find_item(text)
            if it:
                vp, rect = it
                if kind == "dclick":
                    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, rect.center())
                    QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, rect.center())
                else:
                    QTest.mouseClick(vp, Qt.RightButton if kind == "rclick" else Qt.LeftButton, Qt.NoModifier, rect.center())
                self.log("press: ok row %r (%s)" % (text, kind))
                return
            self.log("press: NOT FOUND %r" % text)
            return
        if not x.isEnabled():
            self.log("press: DISABLED %r" % text)
        if isinstance(x, (QLineEdit, QTextEdit, QPlainTextEdit)) or (isinstance(x, QComboBox) and x.isEditable()):
            self._last_text = x
            x.setFocus()
        from PySide6.QtWidgets import QCheckBox, QRadioButton
        if isinstance(x, (QCheckBox, QRadioButton)):
            QTest.mouseClick(x, Qt.LeftButton, Qt.NoModifier, QPoint(9, x.height() // 2))
            self.log("press: ok %r -> %s (box)" % (text, type(x).__name__))
            return
        if kind == "dclick":
            QTest.mouseClick(x, Qt.LeftButton, Qt.NoModifier, x.rect().center())
            QTest.mouseDClick(x, Qt.LeftButton, Qt.NoModifier, x.rect().center())
        else:
            QTest.mouseClick(x, Qt.RightButton if kind == "rclick" else Qt.LeftButton, Qt.NoModifier, x.rect().center())
        self.log("press: ok %r -> %s (%s)" % (text, type(x).__name__, kind))

    def wclick(self, fx, fy, kind="click"):
        root = self.top()
        pt = QPoint(int(fx * root.width()), int(fy * root.height()))
        target = root.childAt(pt) or root
        lp = target.mapFrom(root, pt) if target is not root else pt
        edit = target
        while edit is not None and edit is not root and not isinstance(edit, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox)):
            edit = edit.parentWidget()
        if isinstance(edit, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox)):
            self._last_text = edit
            edit.setFocus()
        if kind == "click":
            QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, lp)
        elif kind == "rclick":
            QTest.mouseClick(target, Qt.RightButton, Qt.NoModifier, lp)
        else:
            QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, lp)
            QTest.mouseDClick(target, Qt.LeftButton, Qt.NoModifier, lp)
        self.log("%s: %.3f,%.3f -> %s %r" % (kind, fx, fy, type(target).__name__, self._label(target)))

    def type(self, text):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        over = self.overlay()
        f = (over.focusWidget() if over is not None else None) or QApplication.focusWidget() or self.w.focusWidget()
        last = getattr(self, "_last_text", None)
        if (f is None or not isinstance(f, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox))) and last is not None and last.isVisible():
            f = last
            f.setFocus()
        if f is None:
            self.log("type: no focus widget")
            return
        for ch in text:
            for et in (QEvent.KeyPress, QEvent.KeyRelease):
                QApplication.sendEvent(f, QKeyEvent(et, 0, Qt.NoModifier, ch))
        self.log("type: %r into %s" % (text, type(f).__name__))

    def key(self, name):
        mods = Qt.NoModifier
        parts = name.lower().split("+")
        for m in parts[:-1]:
            mods |= {"ctrl": Qt.ControlModifier, "meta": Qt.MetaModifier, "shift": Qt.ShiftModifier, "alt": Qt.AltModifier}[m]
        k = KEYS.get(parts[-1])
        over = self.overlay()
        if over is not None:
            f = over.focusWidget() or over
        else:
            f = QApplication.focusWidget() or self.w.focusWidget() or getattr(self, "_last_text", None) or self.top()
        if k is None:
            self.log("key: unknown %r" % name)
            return
        QTest.keyClick(f, k, mods)
        self.log("key: %s -> %s" % (name, type(f).__name__))

    def combo(self, label, item):
        x = self._find(label)
        if not isinstance(x, QComboBox):
            self.log("combo: NOT FOUND %r" % label)
            return
        i = x.findText(item, Qt.MatchContains)
        x.setCurrentIndex(i if i >= 0 else int(item) if item.isdigit() else 0)
        self.log("combo: %r -> %r" % (label, x.currentText()))

    def state(self, name):
        w = self.w
        d = {"center": w.center.currentIndex(), "center_widget": type(w.center.currentWidget()).__name__,
             "modal": type(QApplication.activeModalWidget()).__name__ if QApplication.activeModalWidget() else None,
             "top_windows": [type(t).__name__ + ":" + (t.windowTitle() or "") for t in QApplication.topLevelWidgets() if t.isVisible()]}
        with open("%s/%s.json" % (self.out, name), "w") as f:
            json.dump(d, f, indent=1)


def _safe(fn):
    def wrap(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except Exception:
            self.log("HELPER-ERROR in %s%r (harness problem, not an app bug):\n%s" % (fn.__name__, a, traceback.format_exc(limit=3)))
    return wrap


for _n in ("dump", "press", "wclick", "type", "key", "combo", "state"):
    setattr(_H, _n, _safe(getattr(_H, _n)))


def _deferred(fn):
    # run input later so a modal dialog's nested event loop cannot block the script queue
    from PySide6.QtCore import QTimer
    def wrap(self, *a, **k):
        QTimer.singleShot(0, lambda: fn(self, *a, **k))
    return wrap


for _n in ("press", "wclick", "type", "key", "combo"):
    setattr(_H, _n, _deferred(getattr(_H, _n)))


def _shottop(self, path):
    t = QApplication.activePopupWidget() or QApplication.activeModalWidget()
    if t is None:
        tops = [x for x in QApplication.topLevelWidgets() if x.isVisible() and x is not self.w and x.width() > 20]
        t = tops[-1] if tops else None
    if t is None:
        self.log("shottop: nothing open")
        return
    t.grab().save(path)


_H.shottop = _safe(_shottop)


def _ev(self, code):
    ns = getattr(self, "_ns", None)
    if ns is None:
        ns = self._ns = {"w": self.w, "H": self, "np": __import__("numpy")}
    try:
        exec(code, ns)
    except Exception:
        self.log("EVAL-ERROR (script problem):\n" + traceback.format_exc(limit=2))


_H.ev = _ev


def _act(self, aid):
    from PySide6.QtCore import QTimer
    a = self.w.cmds.actions.get(aid)
    if a is None:
        self.log("action: UNKNOWN action id %r (typo, not an app bug)" % aid)
        return
    QTimer.singleShot(0, a.trigger)     # a modal prompt opened by the action must not block the script


_H.act = _act


def install(w, out):
    # native macOS file sheets block the script queue; Qt's own dialogs can be driven
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    builtins.H = _H(w, out)
