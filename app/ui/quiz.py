"""Study quiz: find a named structure in 3D, hunt for one buried in the whole body, or name a highlighted one.

Questions are drawn from what is currently visible (or one system), grouped by base name so left/right count
as one. Per-structure results are kept in data/user/quiz_stats.json and used to weight weak structures.

"Hunt" is the deep-end mode: the whole body is switched on, nothing is named anywhere on screen, and the only
way in is to right-click structures away one at a time until you can see what you are looking for. Three
wrong clicks end the question, and it then shows the answer and names the three things you actually clicked."""
import json
import random
import re
import time

import numpy as np
from PySide6.QtCore import QStringListModel, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDockWidget, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..config import USER_DIR
from .. import srs
from . import theme

STATS_PATH = USER_DIR / "quiz_stats.json"
EXCLUDED_SYSTEMS = {"attachments", "regions", "reference"}
MODES = [("find", "Find it in 3D"), ("hunt", "Hunt it down — dig through the whole body"),
         ("choice", "Name it — multiple choice"), ("typed", "Name it — type the answer")]
FIND_MODES = ("find", "hunt")
MIN_SIZE = 0.015  # metres (bounding-box diagonal) unless small structures are included
HUNT_SKIP_SYSTEMS = EXCLUDED_SYSTEMS | {"findings", "fascia"}
# a hunt target has to be identifiable by sight. These are not: one of a numbered series, or a subdivision
# whose neighbours look identical.
SKIP_NAME = re.compile(r"segmental bronchus|segment of liver|nucleus pulposus|unlabeled", re.I)
# a few brain-surface parts still carry the source atlas's internal codes ("Lat_Fis-post", "Sulcus
# interm_prim-Jensen"): not names anyone could be asked to type or pick out
RAW_NAME = re.compile(r"_")
SIBLING_TOKEN = re.compile(r"\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"
                           r"|eleventh|twelfth)\b|\b[clts]\d+(?:-[clts]?\d+)?\b|\d+", re.I)
SIBLING_FAMILY = 4        # this many names differing only by a number and none of them is a fair target
GREEN = (0.25, 0.85, 0.35)
RED = (0.95, 0.25, 0.2)
CHOICE = "text-align: left; padding: 7px 12px;"
CHOICE_RIGHT = CHOICE + f" background:{theme.SUCCESS_FILL}; border:1px solid {theme.SUCCESS}; color:{theme.TEXT_STRONG};"
CHOICE_WRONG = CHOICE + f" background:{theme.DANGER_FILL}; border:1px solid {theme.DANGER}; color:{theme.TEXT_STRONG};"


def _norm_answer(text):
    t = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    t = re.sub(r"\b(muscle|bone|the|of|m|n|a|v)\b", " ", t)
    return " ".join(t.split())


class QuizPanel(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.c = controller
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # ------------------------------------------------------------ setup page
        setup = QWidget()
        sl = QVBoxLayout(setup)
        sl.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Quiz")
        title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H1, 700))
        sl.addWidget(title)
        intro = QLabel("Questions come from the structures currently visible, so use Systems, Regions or the Tree "
                       "to narrow the topic first, or pick a system below.")
        intro.setWordWrap(True)
        intro.setStyleSheet(theme.text_css(theme.TEXT_2))
        sl.addWidget(intro)
        sl.setSpacing(8)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.mode = QComboBox()
        for key, label in MODES:
            self.mode.addItem(label, key)
        want = controller.win.qsettings.value("quiz_mode", "")   # the mode you last chose is the one you meant
        if want:
            i = self.mode.findData(want)
            if i >= 0:
                self.mode.setCurrentIndex(i)
        self.mode.currentIndexChanged.connect(
            lambda _i: controller.win.qsettings.setValue("quiz_mode", self.mode.currentData()))
        self.scope = QComboBox()
        self.scope.addItem("Everything currently visible", None)
        for s in controller.ds.systems:
            if s["key"] not in EXCLUDED_SYSTEMS:
                self.scope.addItem(s["name"], s["key"])
        self.count = QSpinBox()
        self.count.setRange(0, 500)
        self.count.setValue(20)
        self.count.setSpecialValueText("Endless")
        self.small = QCheckBox("Include small structures")
        self.small.setToolTip("Small branches, tiny nodes and the like, under about 1.5 cm across")
        self.weak = QCheckBox("Favour structures I often miss")
        self.weak.setChecked(True)
        self.xray = QCheckBox("X-ray everything else when naming")
        self.xray.setChecked(True)
        self.wide = QCheckBox("Hunt: anything at all")
        self.wide.setToolTip("Hunt through the whole atlas, not just the ~500 structures the lessons, radiology "
                             "cases and clinical notes name")
        form.addRow("Mode", self.mode)
        form.addRow("Topic", self.scope)
        form.addRow("Questions", self.count)
        sl.addLayout(form)
        for w in (self.small, self.weak, self.xray, self.wide):
            sl.addWidget(w)
        self.setup_msg = QLabel("")
        self.setup_msg.setWordWrap(True)
        self.setup_msg.setStyleSheet(theme.text_css(theme.DANGER))
        sl.addWidget(self.setup_msg)
        start = QPushButton("Start quiz")
        start.setMinimumHeight(36)
        theme.set_variant(start, "primary")
        start.clicked.connect(lambda: controller.start())
        sl.addWidget(start)
        self.review_btn = QPushButton("Review what is due")
        self.review_btn.setMinimumHeight(30)
        self.review_btn.clicked.connect(controller.start_review)
        sl.addWidget(self.review_btn)
        self.review_note = QLabel("")
        self.review_note.setWordWrap(True)
        self.review_note.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        sl.addWidget(self.review_note)
        progress = QPushButton("My progress…")
        theme.set_variant(progress, "ghost")
        progress.clicked.connect(controller.show_progress)
        sl.addWidget(progress)
        sl.addStretch(1)
        self.stack.addWidget(setup)

        # ------------------------------------------------------------ question page
        q = QWidget()
        ql = QVBoxLayout(q)
        ql.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.progress = QLabel("")
        self.progress.setStyleSheet(theme.text_css(theme.MUTED))
        self.score = QLabel("")
        self.score.setStyleSheet(theme.text_css(theme.TEXT_STRONG, None, 700))
        top.addWidget(self.progress)
        top.addStretch(1)
        top.addWidget(self.score)
        ql.addLayout(top)
        self.instruction = QLabel("")
        self.instruction.setStyleSheet(theme.text_css(theme.ACCENT_TEXT, theme.FS_SMALL, 700))
        ql.addWidget(self.instruction)
        self.prompt = QLabel("")
        self.prompt.setWordWrap(True)
        self.prompt.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H2, 700) + " margin: 4px 0 8px 0;")
        ql.addWidget(self.prompt)

        self.choices = QWidget()
        grid = QGridLayout(self.choices)
        grid.setContentsMargins(0, 0, 0, 0)
        self.choice_buttons = []
        for i in range(4):
            b = QPushButton("")
            b.setMinimumHeight(44)
            b.setStyleSheet(CHOICE)
            b.clicked.connect(lambda _=False, i=i: controller.answer_choice(i))
            grid.addWidget(b, i, 0)
            self.choice_buttons.append(b)
        ql.addWidget(self.choices)

        self.typed = QLineEdit()
        self.typed.setPlaceholderText("Type the name and press Enter")
        self.typed.setMinimumHeight(32)
        self.completer = QCompleter()
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.typed.setCompleter(self.completer)
        self.typed.returnPressed.connect(controller.answer_typed)
        ql.addWidget(self.typed)

        self.feedback = QLabel("")
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.RichText)
        self.feedback.setMinimumHeight(48)
        ql.addWidget(self.feedback)

        self.peeled = QLabel("")
        self.peeled.setWordWrap(True)
        self.peeled.setStyleSheet(theme.text_css(theme.ACCENT_TEXT))
        ql.addWidget(self.peeled)

        row = QHBoxLayout()
        self.hint_btn = QPushButton("Hint")
        self.reveal_btn = QPushButton("Reveal")
        self.next_btn = QPushButton("Next  ▸")
        theme.set_variant(self.next_btn, "primary")
        self.hint_btn.clicked.connect(controller.hint)
        self.reveal_btn.clicked.connect(controller.reveal)
        self.next_btn.clicked.connect(controller.next_question)
        for b in (self.hint_btn, self.reveal_btn, self.next_btn):
            row.addWidget(b)
        ql.addLayout(row)
        self.unhide_btn = QPushButton("Put everything back")
        self.unhide_btn.clicked.connect(controller.unhide_all)
        self.unhide_btn.hide()
        ql.addWidget(self.unhide_btn)
        row2 = QHBoxLayout()
        self.details_btn = QPushButton("Open details")
        self.details_btn.clicked.connect(controller.open_details)
        finish = QPushButton("Finish")
        theme.set_variant(finish, "ghost")
        finish.clicked.connect(controller.finish)
        row2.addWidget(self.details_btn)
        row2.addStretch(1)
        row2.addWidget(finish)
        ql.addLayout(row2)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{theme.BORDER}; background:{theme.BORDER}; max-height:1px; border:none;")
        ql.addWidget(sep)
        self.tips = QLabel("")
        self.tips.setWordWrap(True)
        self.tips.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL + 0.5))
        ql.addWidget(self.tips)
        ql.addStretch(1)
        self.stack.addWidget(q)

        # ------------------------------------------------------------ summary page
        s = QWidget()
        sm = QVBoxLayout(s)
        sm.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("")
        self.summary.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        sm.addWidget(self.summary)
        self.missed_label = QLabel("To review (double-click to show):")
        sm.addWidget(self.missed_label)
        self.missed = QListWidget()
        self.missed.itemDoubleClicked.connect(lambda it: controller.show_base(it.data(Qt.UserRole)))
        sm.addWidget(self.missed, 1)
        row3 = QHBoxLayout()
        again = QPushButton("Retry missed")
        again.clicked.connect(controller.retry_missed)
        self.retry_btn = again
        new = QPushButton("New quiz")
        new.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        close = QPushButton("Close")
        close.clicked.connect(controller.stop)
        for b in (again, new, close):
            row3.addWidget(b)
        sm.addLayout(row3)
        self.stack.addWidget(s)


class QuizController:
    def __init__(self, win):
        self.win = win
        self.ds = win.ds
        self.state = win.state
        self.active = False
        self.dock = None
        self.panel = None
        self.stats = {}
        try:
            self.stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.stats = {}
        self._saved = {}
        self._flash_timer = QTimer()
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)
        self._flash = []
        self._advance = QTimer()
        self._advance.setSingleShot(True)
        self._advance.timeout.connect(self.next_question)
        self.pool = {}
        self.queue = []
        self.missed = []
        self.current = None
        self.mode = "find"
        self._curated = None
        self._siblings = None
        self._peeled = []            # structures the player has right-clicked out of the way, this question
        self._last_click = (-1, 0.0)  # swallow the second half of an accidental double click
        # a lesson's Practice mode (practice.py) borrows the 3D view's clicks through here while it runs, since
        # the main window routes every click in the atlas to the quiz first
        self.delegate = None

    # ------------------------------------------------------------------ lifecycle
    def _ensure_dock(self):
        if self.dock is not None:
            return
        self.panel = QuizPanel(self)
        self.dock = QDockWidget("QUIZ")
        self.dock.setObjectName("quiz_dock")
        self.dock.setWidget(self.panel)
        self.dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                              QDockWidget.DockWidgetClosable)
        self.panel.setMinimumWidth(340)
        self.win.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(self._dock_visibility)

    def _dock_visibility(self, visible):
        if not visible and self.active and not self.dock.isFloating() and not self.win.isMinimized():
            QTimer.singleShot(0, lambda: self.stop() if self.dock and not self.dock.isVisible() else None)

    def toggle(self):
        if self.active:
            self.stop()
        else:
            self.open()

    def _delegate_live(self):
        d = self.delegate
        return d is not None and d.active

    def save_stats(self):
        try:
            STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATS_PATH.write_text(json.dumps(self.stats, indent=0), encoding="utf-8")
        except OSError:
            pass

    def open(self):
        if self._delegate_live():
            self.delegate.stop()
        self._ensure_dock()
        self.active = True
        self._saved = {k: self.win.settings.get(k) for k in ("show_landmarks", "show_hover_tooltip")}
        self._saved["details_visible"] = self.win.right_dock.isVisible()
        self._saved["explore_visible"] = self.win.left_dock.isVisible()
        self._vis_snapshot = self.state._snapshot()
        self.win.right_dock.hide()
        self.dock.show()
        self.dock.raise_()
        self.panel.stack.setCurrentIndex(0)
        self.panel.setup_msg.setText("")
        self.refresh_review_button()
        self.win.center.setCurrentIndex(0)

    def stop(self):
        if not self.active:
            return
        self.active = False
        self._advance.stop()
        self._clear_flash()
        self._clear_marks()
        self._restore_settings()
        snap = getattr(self, "_vis_snapshot", None)
        if snap is not None:
            st = self.state
            st.restore(snap)
            st.clear_selection()
            st._vis_dirty()
            self._vis_snapshot = None
        self._peeled = []
        if self.panel is not None:
            self.panel.peeled.setText("")
            self.panel.unhide_btn.hide()
        if self.dock is not None:
            self.dock.hide()
        if self._saved.get("details_visible", True):
            self.win.right_dock.show()
        if self._saved.get("explore_visible", True):
            self.win.left_dock.show()
        self.current = None

    def names_hidden(self):
        """True while a question is live and nothing on screen should be naming structures."""
        if self._delegate_live():
            return self.delegate.names_hidden()
        return bool(self.active and self.current is not None and not self.current.get("done")
                    and self.mode in FIND_MODES and self.panel is not None
                    and self.panel.stack.currentIndex() == 1)

    def _hide_names(self, hide):
        for k in ("show_landmarks", "show_hover_tooltip"):
            self.win.settings[k] = False if hide else self._saved.get(k, True)
        self.win.viewport.landmark_hosts = []
        self.win.viewport.update()

    def _restore_settings(self):
        self._hide_names(False)

    # ------------------------------------------------------------------ pool
    def _build_pool(self):
        p = self.panel
        ds = self.ds
        scope = p.scope.currentData()
        if scope is not None:
            # show just this system so its structures are not buried under others
            idx = ds.system_index[scope]
            mask = np.zeros(len(ds.systems), dtype=bool)
            mask[idx] = True
            if not np.array_equal(self.state.system_on, mask):
                self.state.set_systems(mask)
        vis = self.state.visible_mask()
        groups = {}
        for sid in np.flatnonzero(vis):
            s = ds.structures[int(sid)]
            if s["system"] in EXCLUDED_SYSTEMS or s.get("role") or (scope is not None and s["system"] != scope):
                continue
            if RAW_NAME.search(s["base"]):
                continue
            groups.setdefault(s["base"], []).append(int(sid))
        pool = {}
        for base, sids in groups.items():
            if not p.small.isChecked():
                b = ds.bounds_of(sids)
                if b is None or float(np.linalg.norm(np.asarray(b[1]) - np.asarray(b[0]))) < MIN_SIZE:
                    continue
            pool[base] = sids
        return pool

    # ------------------------------------------------------------------ the hunt's pool
    def _curated_bases(self):
        """Structures a lesson, a radiology label or a clinical note actually names - the ones worth finding.

        Only literal structure names count: a lesson that says "Anterior compartment of forearm" is naming a
        collection, and the twenty muscles inside it were never singled out by anybody."""
        if self._curated is not None:
            return self._curated
        ds = self.ds
        by_lower = {}
        for name, sids in ds.by_name.items():
            by_lower.setdefault(name.lower(), []).extend(sids)
        bases = set()

        def add(names):
            for n in names or ():
                for sid in by_lower.get((n or "").strip().lower(), ()):
                    bases.add(ds.structures[sid]["base"])

        panel = getattr(self.win, "lessons_panel", None)
        lessons = list(panel.lessons) if panel is not None else []
        if not lessons:
            try:
                from ..lessons import load_lessons
                lessons = load_lessons()
            except (ImportError, OSError, ValueError):
                lessons = []
        for lesson in lessons:
            for step in lesson.steps:
                for key in ("focus", "show", "frame_on", "ghost_focus"):
                    add(step.get(key, []))
        for entry in getattr(self.win.content, "clinical", []):
            add(entry.get("targets", []))
        for case in getattr(self.win, "radiology_cases", []):
            for label in case.labels:
                add(label.structures)
        self._curated = bases
        return bases

    def _sibling_bases(self):
        """Names that are one of a numbered series - a rib, a vertebra, a phalanx. You cannot pick one by eye."""
        if self._siblings is not None:
            return self._siblings
        families = {}
        for s in self.ds.structures:
            families.setdefault(SIBLING_TOKEN.sub("#", s["base"].lower()), set()).add(s["base"])
        self._siblings = {b for v in families.values() if len(v) >= SIBLING_FAMILY for b in v}
        return self._siblings

    def _hunt_pool(self):
        p = self.panel
        ds = self.ds
        scope = p.scope.currentData()
        curated = None if p.wide.isChecked() else self._curated_bases()
        siblings = self._sibling_bases()
        groups = {}
        for s in ds.structures:
            base = s["base"]
            if s["system"] in HUNT_SKIP_SYSTEMS or s.get("role"):
                continue
            if scope is not None and s["system"] != scope:
                continue
            if base in siblings or SKIP_NAME.search(base):
                continue
            if curated is not None and base not in curated:
                continue
            groups.setdefault(base, []).append(s["id"])
        if not p.small.isChecked():
            for base in list(groups):
                b = ds.bounds_of(groups[base])
                if b is None or float(np.linalg.norm(np.asarray(b[1]) - np.asarray(b[0]))) < MIN_SIZE:
                    del groups[base]
        return groups

    def _weight(self, base):
        if not self.panel.weak.isChecked():
            return 1.0
        st = self.stats.get(base)
        if not st:
            return 1.5
        return 1.0 + 3.0 * (st["miss"] + 1) / (st["seen"] + 2)

    def _make_queue(self, bases, n):
        bases = list(bases)
        if not bases:
            return []
        weights = [self._weight(b) for b in bases]
        order = []
        remaining = list(zip(bases, weights))
        while remaining and (n == 0 or len(order) < n) and len(order) < 2000:
            total = sum(w for _, w in remaining)
            r = random.uniform(0, total)
            acc = 0.0
            for i, (b, w) in enumerate(remaining):
                acc += w
                if acc >= r:
                    order.append(b)
                    remaining.pop(i)
                    break
            if not remaining and n == 0:
                break
        return order

    def due_count(self):
        return len(srs.due_bases(self.stats))

    def refresh_review_button(self):
        n = self.due_count()
        total = len(self.stats)
        self.panel.review_btn.setEnabled(n > 0)
        self.panel.review_btn.setText(f"Review what is due ({n})" if n else "Nothing is due today")
        if total:
            s = srs.summary(self.stats)
            self.panel.review_note.setText(
                f"{total:,} structures in your schedule · {s['learned']:,} well known · "
                f"{round(s['accuracy'] * 100)}% right overall")
        else:
            self.panel.review_note.setText("Answer a few questions and they will start coming back on a schedule: "
                                           "sooner if you miss them, later once you know them.")

    def start_review(self):
        due = srs.due_bases(self.stats)
        if not due:
            self.panel.setup_msg.setText("Nothing is due for review yet – take a normal quiz instead.")
            return
        known = {s["base"] for s in self.ds.structures}
        due = [b for b in due if b in known][:60]
        if not due:
            self.panel.setup_msg.setText("Your schedule refers to structures that are not in this dataset.")
            return
        self.state.show_all()
        self.start(bases=due)

    def show_progress(self):
        from .progress import ProgressDialog
        ProgressDialog(self.stats, self.win).exec()

    def start(self, bases=None):
        p = self.panel
        self.mode = p.mode.currentData()
        if self.mode == "hunt":
            # the hunt is through the whole body: no section, no dissection, nothing hidden
            self.win.view_panel.reset_clips()
            self.win.view_panel.set_depth(0.0, False)
        self.pool = self._hunt_pool() if self.mode == "hunt" else self._build_pool()
        if bases is not None:
            bases = [b for b in bases if b in self.pool] or list(bases)
            for b in bases:
                if b not in self.pool:
                    self.pool[b] = [s["id"] for s in self.ds.structures if s["base"] == b]
        if len(self.pool) < 4:
            if self.mode == "hunt":
                p.setup_msg.setText(f"Only {len(self.pool)} structures fit that topic. Pick a broader one, or tick "
                                    "'Hunt: anything at all'.")
            else:
                p.setup_msg.setText(f"Only {len(self.pool)} quizzable structures are visible. Turn on more systems "
                                    "or tick 'Include small structures'.")
            return
        n = p.count.value()
        self.endless = n == 0 and bases is None
        self.queue = list(bases) if bases is not None else self._make_queue(self.pool.keys(), n)
        self.total = len(self.queue) if not self.endless else 0
        self.asked = 0
        self.correct = 0
        self.missed = []
        self.streak = 0
        self.best_streak = 0
        p.completer.setModel(QStringListModel(sorted(self.pool.keys())))
        p.setup_msg.setText("")
        p.stack.setCurrentIndex(1)
        p.unhide_btn.setVisible(self.mode == "hunt")
        p.peeled.setText("")
        self._hide_names(True)
        self.state.clear_ghost()
        self.state.clear_selection()
        if self.mode == "hunt":
            self.win.left_dock.hide()      # search and the tree would answer the question for you
            self._show_body()
            self._frame_body()
        else:
            self.win.viewport.frame_structures([s for v in self.pool.values() for s in v])
        self.win.viewport.setFocus()
        tips = {"find": "Left-click the structure in the 3D view; <b>right-click</b> anything in the way to peel it "
                        "off (Ctrl+Z puts it back). Three wrong clicks reveal the answer.",
                "hunt": "Everything is switched on and nothing is named. Move as usual, <b>right-click</b> to peel a "
                        "structure out of the way, <b>left-click</b> the one you think it is. Three tries, then it "
                        "shows you — and tells you what you clicked. Ctrl+Z puts back the last thing you hid.",
                "choice": "The structure is outlined (and everything else x-rayed). Pick its name.",
                "typed": "Type the name; suggestions appear as you type. Minor wording differences such as "
                         "'muscle' or 'bone' are ignored."}
        p.tips.setText(tips[self.mode])
        self.next_question()

    # ------------------------------------------------------------------ questions
    def next_question(self):
        self._advance.stop()
        self._clear_flash()
        self._clear_marks()
        p = self.panel
        if not self.queue:
            if self.endless:
                self.queue = self._make_queue(self.pool.keys(), 0)
            else:
                self.finish()
                return
        base = self.queue.pop(0)
        self.current = {"base": base, "sids": self.pool.get(base, []), "wrong": 0, "hints": 0, "done": False,
                        "helped": False, "clicks": []}
        if self.mode == "hunt":
            self._reset_body()
        elif self.mode == "find":
            self.unhide_all()             # a structure peeled away last time may be this time's answer
        self.asked += 1
        p.progress.setText(f"Question {self.asked}" + (f" of {self.total}" if self.total else ""))
        self._update_score()
        p.feedback.setText("")
        p.hint_btn.setEnabled(True)
        p.reveal_btn.setEnabled(True)
        p.next_btn.setText("Skip  ▸")
        p.details_btn.setEnabled(False)
        s0 = self.ds.structures[self.current["sids"][0]]
        if self.mode in FIND_MODES:
            p.instruction.setText("Find and click:" if self.mode == "find" else "Somewhere in here is:")
            p.prompt.setText(base)
            p.choices.hide()
            p.typed.hide()
            self.state.clear_ghost()
            self.state.clear_selection()
        else:
            p.instruction.setText("Name the highlighted structure:")
            p.prompt.setText("?")
            sids = self.current["sids"]
            self.state.force_show(sids)
            self.state.select(sids)
            if p.xray.isChecked():
                self.state.set_ghost_focus(sids)
            else:
                self.state.clear_ghost()
            self.win.viewport.frame_structures(sids)
            if self.mode == "choice":
                p.typed.hide()
                p.choices.show()
                opts = [base] + self._distractors(base, s0, 3)
                random.shuffle(opts)
                self.current["options"] = opts
                for b, text in zip(p.choice_buttons, opts):
                    b.setText(text)
                    b.setEnabled(True)
                    b.setStyleSheet(CHOICE)
            else:
                p.choices.hide()
                p.typed.show()
                p.typed.clear()
                p.typed.setEnabled(True)
                p.typed.setFocus()

    # ------------------------------------------------------------------ the hunt
    def _frame_body(self):
        """Back to a whole-body view, so the last answer's camera is not itself a clue."""
        vis = np.flatnonzero(self.state.visible_mask())
        if len(vis):
            self.win.viewport.frame_structures([int(x) for x in vis], view="anterior")

    def _show_body(self):
        """Everything on, except the systems a hunt never asks about."""
        self.state.show_all()
        for key in HUNT_SKIP_SYSTEMS:
            idx = self.ds.system_index.get(key)
            if idx is not None:
                self.state.system_on[idx] = False
        self.state._vis_dirty()

    def _reset_body(self):
        """Every hunt starts from an intact body: nothing peeled, nothing framed."""
        self._peeled = []
        self._show_body()
        self.state.clear_selection()
        self.panel.peeled.setText("")
        self._frame_body()

    def unhide_all(self):
        if not self._peeled:
            return
        self.state.set_hidden(self._peeled, False)
        self._peeled = []
        self.panel.peeled.setText("")
        self.panel.unhide_btn.setVisible(self.mode == "hunt")

    def handle_right_click(self, sid):
        """True when the quiz consumed the right click - it peels that structure away instead of opening a menu.

        This applies to both modes that ask you to find something. The context menu would be worse than useless
        during one: its first line is the name of whatever is under the cursor."""
        if self._delegate_live():
            return self.delegate.handle_right_click(sid)
        if not (self.active and self.mode in FIND_MODES and self.current is not None):
            return False
        if self.panel.stack.currentIndex() != 1:
            return False
        if sid >= 0 and not self.current["done"]:
            self.state.set_hidden([sid], True)
            self._peeled.append(int(sid))
            n = len(self._peeled)
            self.panel.peeled.setText(f"{n} structure{'s' if n != 1 else ''} peeled away "
                                      "— Ctrl+Z puts the last one back")
            self.panel.unhide_btn.show()
        return True                       # never a context menu mid-question, even on empty space

    def _clicked_summary(self, clicks):
        if not clicks:
            return ""
        names = []
        for i, sid in enumerate(clicks, 1):
            s = self.ds.structures[sid]
            names.append(f"{i}. {s['base']}")
        return f"<br><span style=\"color:{theme.MUTED}\">You clicked: " + " &nbsp; ".join(names) + "</span>"

    def _distractors(self, base, s0, k):
        pool = [b for b in self.pool if b != base]
        by_sub = [b for b in pool if self.ds.structures[self.pool[b][0]]["subsystem"] == s0["subsystem"]]
        by_sys = [b for b in pool if self.ds.structures[self.pool[b][0]]["system"] == s0["system"] and b not in by_sub]
        # prefer similar-looking names within the same subsystem, which makes the question discriminating
        words = set(_norm_answer(base).split())
        by_sub.sort(key=lambda b: -len(words & set(_norm_answer(b).split())) + random.random() * 1.5)
        out = by_sub[:k]
        random.shuffle(by_sys)
        out += by_sys[:k - len(out)]
        rest = [b for b in pool if b not in out]
        random.shuffle(rest)
        out += rest[:k - len(out)]
        return out[:k]

    def _update_score(self):
        answered = self.asked - (0 if self.current and self.current["done"] else 1)
        pct = f" · {round(100 * self.correct / answered)}%" if answered > 0 else ""
        streak = f" · streak {self.streak}" if self.streak >= 3 else ""
        self.panel.score.setText(f"{self.correct} correct{pct}{streak}")

    def _record(self, ok):
        cur = self.current
        cur["done"] = True
        base = cur["base"]
        st = self.stats.setdefault(base, {"seen": 0, "miss": 0})
        st["seen"] += 1
        srs.update(st, srs.grade_for(ok, cur.get("helped"), cur.get("wrong", 0)))
        if ok:
            self.correct += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
        else:
            st["miss"] += 1
            self.streak = 0
            if base not in self.missed:
                self.missed.append(base)
        self.save_stats()
        p = self.panel
        p.hint_btn.setEnabled(False)
        p.reveal_btn.setEnabled(False)
        p.next_btn.setText("Next  ▸")
        p.details_btn.setEnabled(True)
        self._update_score()

    def _show_answer(self, color):
        cur = self.current
        sids = cur["sids"]
        self.state.force_show(sids)
        self.state.select(sids)
        self.state.set_ghost_focus(sids)
        self.state.set_custom_color(sids, color)
        self._marked = list(sids)
        self.win.viewport.frame_structures(sids)
        self.panel.prompt.setText(cur["base"])

    def _clear_marks(self):
        marked = getattr(self, "_marked", [])
        if marked:
            self.state.set_custom_color(marked, None)
        self._marked = []

    # ------------------------------------------------------------------ answers
    def handle_click(self, sid, modifiers=None):
        """Return True when the quiz consumed the click."""
        if self._delegate_live():
            return self.delegate.handle_click(sid, modifiers)
        if not self.active or self.current is None or self.panel.stack.currentIndex() != 1:
            return False
        if self.mode not in FIND_MODES or self.current["done"]:
            return True
        if sid < 0:
            return True
        now = time.perf_counter()
        last_sid, last_t = self._last_click
        if sid == last_sid and now - last_t < 0.4:
            return True                   # the second half of a double click must not cost a try
        self._last_click = (sid, now)
        cur = self.current
        hunt = self.mode == "hunt"
        s = self.ds.structures[sid]
        if s["base"] == cur["base"]:
            label = "Correct!" if cur["hints"] == 0 and cur["wrong"] == 0 else "Correct."
            self.panel.feedback.setText(f'<span style="color:{theme.SUCCESS}; font-weight:700">{label}</span>'
                                        + (self._clicked_summary(cur["clicks"]) if hunt else ""))
            self._record(True)
            self._show_answer(GREEN)
            self._advance.start(2600 if hunt and cur["clicks"] else 1600)
            return True
        cur["wrong"] += 1
        cur["clicks"].append(int(sid))
        self._flash_structures([sid], RED)
        if cur["wrong"] >= 3:
            if hunt:
                # only now is anything named: the answer, and the three things that were clicked instead
                self.panel.feedback.setText(f'<span style="color:{theme.DANGER}">Out of tries.</span> '
                                            f'It is <b>{cur["base"]}</b>, shown in green.'
                                            + self._clicked_summary(cur["clicks"]))
            else:
                self.panel.feedback.setText(f'<span style="color:{theme.DANGER}">That was <b>{s["base"]}</b>.</span> '
                                            f'Here is <b>{cur["base"]}</b>.')
            self._record(False)
            self._show_answer(GREEN)
        else:
            left = 3 - cur["wrong"]
            n_left = f'{left} {"try" if left == 1 else "tries"} left.'
            if hunt:                      # naming the wrong structure would give the game away
                self.panel.feedback.setText(f'<span style="color:{theme.DANGER}">Not that one.</span> {n_left}')
            else:
                self.panel.feedback.setText(f'<span style="color:{theme.DANGER}">No — that is <b>{s["base"]}</b>.</span> '
                                            f'{n_left}')
        return True

    def _flash_structures(self, sids, color):
        self._clear_flash()
        self._flash = [s for s in sids if s not in getattr(self, "_marked", [])]
        self.state.set_custom_color(self._flash, color)
        self._flash_timer.start(900)

    def _clear_flash(self):
        if self._flash:
            self.state.set_custom_color(self._flash, None)
        self._flash = []

    def answer_choice(self, i):
        cur = self.current
        if cur is None or cur["done"]:
            return
        p = self.panel
        chosen = cur["options"][i]
        ok = chosen == cur["base"]
        for b, text in zip(p.choice_buttons, cur["options"]):
            b.setEnabled(False)
            if text == cur["base"]:
                b.setStyleSheet(CHOICE_RIGHT)
            elif text == chosen:
                b.setStyleSheet(CHOICE_WRONG)
        p.feedback.setText(f'<span style="color:{theme.SUCCESS}; font-weight:700">Correct!</span>' if ok else
                           f'<span style="color:{theme.DANGER}">Not quite — it is <b>{cur["base"]}</b>.</span>')
        self._record(ok)
        self._show_answer(GREEN if ok else RED)
        if ok:
            self._advance.start(1300)

    def answer_typed(self):
        cur = self.current
        p = self.panel
        if cur is None:
            return
        if cur["done"]:
            self.next_question()
            return
        text = p.typed.text().strip()
        if not text:
            return
        s0 = self.ds.structures[cur["sids"][0]]
        accepted = {_norm_answer(cur["base"]), _norm_answer(s0.get("latin") or "")}
        ok = _norm_answer(text) in accepted
        if ok:
            p.feedback.setText(f'<span style="color:{theme.SUCCESS}; font-weight:700">Correct!</span>')
        else:
            p.feedback.setText(f'<span style="color:{theme.DANGER}">Not quite — it is <b>{cur["base"]}</b>.</span> '
                               'Press Enter for the next question.')
        self._record(ok)
        self._show_answer(GREEN if ok else RED)
        if ok:
            self._advance.start(1300)

    def hint(self):
        cur = self.current
        if cur is None or cur["done"]:
            return
        cur["hints"] += 1
        cur["helped"] = True
        s0 = self.ds.structures[cur["sids"][0]]
        system = self.ds.systems[self.ds.system_index[s0["system"]]]["name"]
        regions = ", ".join(r.replace("_l", "").replace("_r", "").replace("_", " ") for r in s0.get("regions", [])[:2])
        if self.mode in FIND_MODES:
            if cur["hints"] == 1:
                self.panel.feedback.setText(f"Hint: {system} › {s0['subsystem']}" + (f" · {regions}" if regions else ""))
            else:
                b = self.ds.bounds_of(cur["sids"])
                if b is not None:
                    center = (np.asarray(b[0]) + np.asarray(b[1])) / 2
                    radius = float(np.linalg.norm(np.asarray(b[1]) - np.asarray(b[0])))
                    self.win.viewport.frame_point(center, max(radius * 1.6, 0.08))
                self.panel.feedback.setText("Hint: the camera is now centred near it.")
        else:
            base = cur["base"]
            if cur["hints"] == 1:
                self.panel.feedback.setText(f"Hint: {s0['subsystem']} · starts with “{base[:1]}”, "
                                            f"{len(base.split())} word{'s' if len(base.split()) > 1 else ''}")
            else:
                shown = " ".join(w[: max(1, len(w) // 2)] + "…" for w in base.split())
                self.panel.feedback.setText(f"Hint: {shown}")

    def reveal(self):
        cur = self.current
        if cur is None or cur["done"]:
            return
        self.panel.feedback.setText(f"It is <b>{cur['base']}</b>."
                                    + (self._clicked_summary(cur["clicks"]) if self.mode == "hunt" else ""))
        if self.mode == "choice":
            for b, text in zip(self.panel.choice_buttons, cur["options"]):
                b.setEnabled(False)
                if text == cur["base"]:
                    b.setStyleSheet(CHOICE_RIGHT)
        self._record(False)
        self._show_answer(RED)

    def open_details(self):
        if self.current is None:
            return
        self.win.right_dock.show()
        self.win.info.show_structures(self.current["sids"])

    # ------------------------------------------------------------------ summary
    def finish(self):
        self._advance.stop()
        self._clear_flash()
        self._clear_marks()
        p = self.panel
        answered = self.asked if (self.current and self.current["done"]) else max(0, self.asked - 1)
        pct = round(100 * self.correct / answered) if answered else 0
        if answered:
            p.summary.setText(f'<p style="font-size:{theme.FS_H1 + 3}pt; font-weight:700; color:{theme.TEXT_STRONG}">'
                              f'{self.correct} / {answered} correct '
                              f'({pct}%)</p><p>Best streak: {self.best_streak}</p>'
                              + ("" if self.missed else "<p>Nothing to review – you got every one.</p>"))
        else:
            p.summary.setText(f'<p style="font-size:{theme.FS_H1}pt; font-weight:700; color:{theme.TEXT_STRONG}">'
                              f'No questions answered</p>'
                              f'<p style="color:{theme.MUTED}">Start a new quiz when you are ready.</p>')
        p.missed_label.setVisible(bool(self.missed))
        p.missed.setVisible(bool(self.missed))
        p.retry_btn.setVisible(bool(self.missed))
        p.missed.clear()
        for b in self.missed:
            st = self.stats.get(b, {})
            it = QListWidgetItem(f"{b}   ·   missed {st.get('miss', 0)} of {st.get('seen', 0)}")
            it.setData(Qt.UserRole, b)
            p.missed.addItem(it)
        self.current = None
        self._peeled = []
        p.peeled.setText("")
        p.unhide_btn.hide()
        if self._saved.get("explore_visible", True):
            self.win.left_dock.show()
        p.stack.setCurrentIndex(2)
        self._hide_names(False)
        self.state.clear_ghost()
        self.state.clear_selection()

    def retry_missed(self):
        if self.missed:
            bases = list(self.missed)
            random.shuffle(bases)
            self.start(bases)

    def show_base(self, base):
        sids = self.pool.get(base) or [s["id"] for s in self.ds.structures if s["base"] == base]
        self.win.right_dock.show()
        self.win.select_and_focus(sids, xray=True)
