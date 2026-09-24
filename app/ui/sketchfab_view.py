"""The Sketchfab tab: a list of online models on the left, Sketchfab's own player on the right.

The player is the public embed that Sketchfab offers for every published model, loaded into a web view, so
the model streams from sketchfab.com with its creator and Sketchfab's branding shown - nothing is downloaded.
The web view uses an off-the-record profile: no cookies or cache are written to disk, and the embed is asked
not to track (dnt=1).
"""
import json

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from ..sketchfab import TOPICS
from .card_list import CardList
from .sketchfab_bridge import CameraBridge, host_html

TOPIC_COLOUR = {"cardio": "#e0707a", "msk-skin": "#cbb89a", "viscera": "#e8b45c", "neuro-senses": "#e8d15c"}
IDLE = ("<div style='color:#8a94a3; font-size:11pt; line-height:150%'>"
        "<p style='font-size:14pt; color:#d9dee6'><b>Online 3D models</b></p>"
        "<p>Pick a model on the left. These are shown in Sketchfab's own player and stream from sketchfab.com, "
        "so they need an internet connection. Nothing is downloaded or saved.</p>"
        "<p>Selecting a structure in the atlas also lists any matching model under <b>Details</b>.</p></div>")
OFFLINE = ("<div style='color:#8a94a3; font-size:11pt; line-height:150%'>"
           "<p style='font-size:13pt; color:#e0a06a'><b>Could not reach Sketchfab</b></p>"
           "<p>This model streams from sketchfab.com, so it needs an internet connection. "
           "Check the connection and press <b>Reload</b>.</p></div>")


_PROFILE = None


def _profile():
    """One off-the-record profile for the whole run - no cookies, cache or history written to disk.

    It belongs to the application rather than to a panel, so it always outlives the pages that use it;
    Qt complains, and can crash, if a profile is destroyed before its pages."""
    global _PROFILE
    if _PROFILE is None:
        _PROFILE = QWebEngineProfile(QApplication.instance())
    return _PROFILE


class SketchfabPanel(QWidget):
    structuresRequested = Signal(object)        # [names] to select in the atlas
    openLocal = Signal(str)                     # uid of a downloaded model, to open in the atlas's own viewer

    def __init__(self, models, settings=None, cmds=None, parent=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else {}
        self.cmds = cmds
        self.models = models
        self.by_uid = {m.uid: m for m in models}
        self.current = None

        split = QSplitter(Qt.Horizontal, self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(split)

        # ---- the list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 8, 6, 8)
        ll.setSpacing(6)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(f"Filter {len(models)} models…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._fill)
        ll.addWidget(self.filter)
        self.list = CardList()
        self.list.itemClicked.connect(self._chosen)
        self.list.itemActivated.connect(self._chosen)
        ll.addWidget(self.list, 1)
        note = QLabel("Streamed from sketchfab.com in Sketchfab's own player; each model belongs to its creator. "
                      "Models marked downloaded were fetched under their Creative Commons licence and also open "
                      "offline in the atlas's own viewer.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6f7a89; font-size:8pt;")
        ll.addWidget(note)
        left.setMinimumWidth(260)
        split.addWidget(left)

        # ---- the player
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 10, 8)
        rl.setSpacing(6)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.title = QLabel("")
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 2.0)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setWordWrap(True)
        titles.addWidget(self.title)
        self.credit = QLabel("")
        self.credit.setStyleSheet("color:#8a94a3;")
        titles.addWidget(self.credit)
        head.addLayout(titles, 1)
        self.show3d = QPushButton("Show in the atlas")
        self.show3d.clicked.connect(self._show_in_atlas)
        self.open_local = QPushButton("Open downloaded copy")
        self.open_local.setToolTip("This model is downloaded: open it in the atlas's own viewer, which works offline "
                                   "and lets you pick, hide and cut through its parts")
        self.open_local.clicked.connect(lambda: self.current and self.openLocal.emit(self.current.uid))
        self.open_local.hide()
        self.open_web = QPushButton("Open on Sketchfab")
        self.open_web.clicked.connect(lambda: self.current and QDesktopServices.openUrl(QUrl(self.current.page_url)))
        self.reload = QPushButton("Reload")
        self.reload.clicked.connect(lambda: self.current and self.open(self.current.uid, force=True))
        for b in (self.open_local, self.show3d, self.open_web, self.reload):
            b.setEnabled(False)
            head.addWidget(b, 0, Qt.AlignTop)
        rl.addLayout(head)
        row = QHBoxLayout()
        self.own_controls = QCheckBox("Use my controls")
        self.own_controls.setChecked(True)
        self.own_controls.setToolTip("On: the atlas's own mouse and key controls and Settings drive this model. "
                                     "Off: Sketchfab's own controls, which can click annotation hotspots.")
        self.own_controls.toggled.connect(self._set_bridge)
        row.addWidget(self.own_controls)
        self.annotations = QComboBox()
        self.annotations.setMinimumWidth(220)
        self.annotations.activated.connect(self._goto_annotation)
        self.annotations.hide()
        row.addWidget(self.annotations)
        row.addStretch(1)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#8a94a3;")
        row.addWidget(self.status)
        rl.addLayout(row)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color:#aab3c0;")
        rl.addWidget(self.summary)

        self.stack = QStackedWidget()
        self.message = QLabel(IDLE)
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setTextFormat(Qt.RichText)
        self.message.setMargin(40)
        self.stack.addWidget(self.message)
        self.view = QWebEngineView()
        self.view.setPage(QWebEnginePage(_profile(), self.view))
        self.view.loadFinished.connect(self._loaded)
        player = QWidget()
        grid = QGridLayout(player)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self.view, 0, 0)
        self.bridge = CameraBridge(self.view.page(), self.settings, self.cmds)
        grid.addWidget(self.bridge, 0, 0)
        self.bridge.hide()
        self.stack.addWidget(player)
        self.player = player
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._check_ready)
        self._poll_started = 0.0
        rl.addWidget(self.stack, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([320, 1000])
        self._fill()

    # ------------------------------------------------------------------ list
    def _fill(self):
        needle = self.filter.text().strip().lower()
        self.list.clear()
        for key, name in TOPICS + [("", "Other")]:
            group = [m for m in self.models if (m.topic if m.topic in dict(TOPICS) else "") == key]
            if needle:
                group = [m for m in group if needle in " ".join([m.name, m.summary, m.author, " ".join(m.structures)]).lower()]
            if not group:
                continue
            self.list.add_header(f"{name}  ({len(group)})")
            for m in group:
                tags = [t for t, on in (("downloaded", m.local), ("animated", m.animated),
                                        ("pathology", m.pathology)) if on]
                self.list.add_card(m.name, m.summary, badge=" · ".join(tags), accent=TOPIC_COLOUR.get(m.topic),
                                   data=m.uid, tooltip=m.credit)
        if self.list.count() == 0:
            self.list.add_note("No model matches that.")
        if self.current is not None:
            self._select_card(self.current.uid)

    def _select_card(self, uid):
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == uid:
                self.list.setCurrentRow(i)
                self.list.scrollToItem(self.list.item(i))
                return

    def _chosen(self, item):
        uid = item.data(Qt.UserRole)
        if uid:
            self.open(uid)

    # ------------------------------------------------------------------ player
    def open(self, uid, force=False):
        m = self.by_uid.get(uid)
        if m is None:
            return
        if self.current is m and not force:
            return
        self.current = m
        self.title.setText(m.name)
        self.credit.setText(m.credit)
        self.summary.setText(m.summary)
        for b in (self.open_local, self.show3d, self.open_web, self.reload):
            b.setEnabled(True)
        self.show3d.setEnabled(bool(m.structures))
        self.open_local.setVisible(m.local)
        # a small host page runs Sketchfab's official Viewer API around the embed, so the camera can be driven
        self.bridge.stop()
        self.bridge.hide()
        self.bridge.home = None
        self.bridge.fov_matched = False
        self.annotations.hide()
        self.status.setText("Loading…")
        self.view.setHtml(host_html(m.uid), QUrl("https://localhost/"))
        self.stack.setCurrentWidget(self.player)
        self._select_card(uid)
        import time
        self._poll_started = time.perf_counter()
        self._poll.start()

    def _loaded(self, ok):
        if not ok and self.current is not None:
            self._offline()

    def _offline(self):
        self._poll.stop()
        self.bridge.stop()
        self.message.setText(OFFLINE)
        self.stack.setCurrentWidget(self.message)
        self.status.setText("")

    def _check_ready(self):
        import time
        if time.perf_counter() - self._poll_started > 45:
            self._offline()
            return
        self.view.page().runJavaScript("JSON.stringify(window.__sf || null)", self._on_state)

    def _on_state(self, raw):
        try:
            st = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            st = None
        if not st:
            return
        if st.get("error"):
            self._offline()
            return
        if not st.get("ready") or not st.get("cam"):
            return
        self._poll.stop()
        self.bridge.adopt(st["cam"])
        names = st.get("annotations") or []
        self.annotations.clear()
        if names:
            self.annotations.addItem(f"Annotations ({len(names)})…")
            for i, n in enumerate(names, 1):
                self.annotations.addItem(f"{i}. {n}" if n else f"{i}.")
            self.annotations.show()
        self.status.setText("")
        self._dismiss_hint()
        self._set_bridge(self.own_controls.isChecked())

    def _dismiss_hint(self):
        """The player shows a 'click & hold to rotate' hint until it is clicked once. With the atlas's controls
        on, it never is - so give it one plain click at the edge of the view, where there is only background."""
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        target = self.view.focusProxy() or self.view
        pt = QPointF(target.width() - 12, target.height() * 0.5)
        for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            ev = QMouseEvent(kind, pt, target.mapToGlobal(pt), Qt.LeftButton,
                             Qt.LeftButton if kind == QEvent.MouseButtonPress else Qt.NoButton, Qt.NoModifier)
            QApplication.sendEvent(target, ev)

    def _set_bridge(self, on):
        if self.current is None or self.bridge.home is None:
            return
        if on:
            self._resync(0, then_start=True)
        else:
            self.bridge.stop()
            self.bridge.hide()

    def _resync(self, delay_ms, then_start=False):
        """Pick up wherever the player's camera is now - after an annotation jump or its own controls."""
        page = self.view.page()

        def read():
            page.runJavaScript("sfRead()")
            QTimer.singleShot(250, lambda: page.runJavaScript("JSON.stringify(window.__sf.cam)", adopt))

        def adopt(raw):
            try:
                cam = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                cam = None
            if cam:
                self.bridge.adopt(cam)
            if then_start and self.own_controls.isChecked():
                self.bridge.show()
                self.bridge.raise_()
                self.bridge.start()
                self.bridge.setFocus()

        QTimer.singleShot(delay_ms, read)

    def _goto_annotation(self, index):
        if index <= 0:
            return
        self.view.page().runJavaScript(f"sfGoto({index - 1})")
        self.bridge.stop()
        self._resync(1800, then_start=True)       # after the player's own move to the annotation

    def _show_in_atlas(self):
        if self.current is not None and self.current.structures:
            self.structuresRequested.emit(list(self.current.structures))
