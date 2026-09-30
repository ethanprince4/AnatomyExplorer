"""Practice mode: a short graded session on one lesson, or on a whole lab practical.

Learn walks you through a lesson; Practice makes you use it. A session is drawn from the lesson's `practice`
items plus its step `check` questions (a lab practical's `practice_from` adds every item of the labs it covers),
and mixes six kinds of question:

  find        find a named structure in the 3D atlas: left-click it, right-click anything in the way to peel it
              off, three wrong clicks and it is shown to you
  name        a structure is highlighted in the atlas; pick its name from ones taught alongside it
  find_micro  the same as find, inside a 3D microanatomy model
  mcq         a multiple-choice question with a one-line "why"
  recall      a flashcard: think of the answer, show it, and say honestly whether you knew it
  order       put a sequence in order (drag, or the arrow buttons)

Every answer goes into the quiz's spaced-repetition store (data/user/quiz_stats.json, see app/srs.py): finding or
naming a structure shares the quiz's own key for it, so a miss here brings it back in "Review what is due".
The session runs in a dock of its own on the right, like the quiz, and puts the 3D view back when it closes.
"""
import html
import random
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDockWidget, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .. import srs
from ..storage import load_json, write_json
from ..lessons import TYPE_NAME, build_session, default_length, item_key, practice_pool
from . import theme
from .diagram import DiagramView
from .study_colors import highlight, restore_colors
from .study_scene import capture_scene, restore_scene

GREEN = (0.25, 0.85, 0.35)
RED = (0.95, 0.25, 0.2)
OK_HTML = f'<span style="color:{theme.SUCCESS}; font-weight:700">{{}}</span>'
BAD_HTML = f'<span style="color:{theme.DANGER}; font-weight:700">{{}}</span>'
BTN = "text-align:left; padding:7px 12px;"
BTN_RIGHT = BTN + f" background:{theme.SUCCESS_FILL}; border:1px solid {theme.SUCCESS}; color:{theme.TEXT_STRONG};"
BTN_WRONG = BTN + f" background:{theme.DANGER_FILL}; border:1px solid {theme.DANGER}; color:{theme.TEXT_STRONG};"
MAX_CHOICES = 6
# the parts of a lesson step that set the atlas up; the step's own selection and x-ray are left out, since they
# would point straight at the answer
SCENE_KEYS = ("systems", "regions", "side", "show", "focus", "ghost_focus", "dissect", "layer_only", "clip",
              "view", "frame_on", "camera", "reset_clips")
TIPS = {
    "find": "Left-click it in the 3D view. <b>Right-click</b> anything in the way to peel it off (Ctrl+Z puts it "
            "back). Three wrong clicks and it is shown to you.",
    "name": "The highlighted structure: which is it?",
    "find_micro": "Left-click the part in the model. <b>Right-click</b> a part to peel it away. Three wrong clicks "
                  "and it is shown to you.",
    "mcq": "Pick one. Keys 1–6 work too.",
    "recall": "Answer it in your head first, then show the answer and be honest about whether you knew it.",
    "order": "Drag the rows into order, or select one and use the arrows, then Check.",
}


def esc(s):
    return html.escape(str(s or ""))


class PracticePanel(QWidget):
    def __init__(self, controller):
        super().__init__()
        c = controller
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # ------------------------------------------------------------ question page
        q = QWidget()
        ql = QVBoxLayout(q)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.setSpacing(6)
        self.where = QLabel("")
        self.where.setWordWrap(True)
        self.where.setStyleSheet(theme.text_css(theme.ACCENT_TEXT, theme.FS_SMALL, 700))
        ql.addWidget(self.where)
        top = QHBoxLayout()
        self.progress = QLabel("")
        self.progress.setStyleSheet(theme.text_css(theme.MUTED))
        self.score = QLabel("")
        self.score.setStyleSheet(theme.text_css(theme.TEXT_STRONG, None, 700))
        top.addWidget(self.progress)
        top.addStretch(1)
        top.addWidget(self.score)
        ql.addLayout(top)
        self.kind = QLabel("")
        self.kind.setStyleSheet(theme.tag_css(theme.ACCENT, theme.ON_ACCENT))
        ql.addWidget(self.kind, 0, Qt.AlignLeft)
        self.prompt = QLabel("")
        self.prompt.setWordWrap(True)
        self.prompt.setTextFormat(Qt.RichText)
        self.prompt.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H2 - 1, 700) + " margin:4px 0 6px 0;")
        ql.addWidget(self.prompt)
        self.diagram = DiagramView(max_height=260)
        self.diagram.hide()
        ql.addWidget(self.diagram)

        # multiple choice (mcq and name)
        self.choices = QWidget()
        cl = QVBoxLayout(self.choices)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        self.choice_buttons = []
        for i in range(MAX_CHOICES):
            b = QPushButton("")
            b.setMinimumHeight(38)
            b.setStyleSheet(BTN)
            b.clicked.connect(lambda _=False, i=i: c.answer_choice(i))
            cl.addWidget(b)
            self.choice_buttons.append(b)
        ql.addWidget(self.choices)

        # recall
        self.recall = QWidget()
        rl = QVBoxLayout(self.recall)
        rl.setContentsMargins(0, 0, 0, 0)
        self.show_answer = QPushButton("Show answer")
        self.show_answer.setMinimumHeight(34)
        self.show_answer.clicked.connect(c.reveal_recall)
        rl.addWidget(self.show_answer)
        self.answer = QLabel("")
        self.answer.setWordWrap(True)
        self.answer.setTextFormat(Qt.RichText)
        self.answer.setStyleSheet(theme.well_css(theme.ACCENT_TEXT, theme.SP_3))
        rl.addWidget(self.answer)
        self.grade_row = QWidget()
        gl = QHBoxLayout(self.grade_row)
        gl.setContentsMargins(0, 0, 0, 0)
        self.knew = QPushButton("I knew it")
        theme.set_variant(self.knew, "success")
        self.knew.clicked.connect(lambda: c.grade_recall(True))
        self.didnt = QPushButton("I didn't")
        theme.set_variant(self.didnt, "danger")
        self.didnt.clicked.connect(lambda: c.grade_recall(False))
        gl.addWidget(self.knew)
        gl.addWidget(self.didnt)
        rl.addWidget(self.grade_row)
        ql.addWidget(self.recall)

        # order
        self.order = QWidget()
        ol = QHBoxLayout(self.order)
        ol.setContentsMargins(0, 0, 0, 0)
        self.order_list = QListWidget()
        self.order_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.order_list.setDefaultDropAction(Qt.MoveAction)
        self.order_list.setStyleSheet("QListWidget::item { padding:6px 4px; }")
        self.order_list.setWordWrap(True)
        self.order_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ol.addWidget(self.order_list, 1)
        arrows = QVBoxLayout()
        up = QPushButton("▲")
        down = QPushButton("▼")
        for b, d in ((up, -1), (down, 1)):
            b.setFixedWidth(34)
            b.setStyleSheet("padding: 5px 0;")
            b.clicked.connect(lambda _=False, d=d: c.move_order(d))
            arrows.addWidget(b)
        arrows.addStretch(1)
        self.check_order = QPushButton("Check")
        self.check_order.clicked.connect(c.check_order)
        arrows.addWidget(self.check_order)
        ol.addLayout(arrows)
        ql.addWidget(self.order)

        self.feedback = QLabel("")
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.RichText)
        self.feedback.setMinimumHeight(36)
        ql.addWidget(self.feedback)
        self.peeled = QLabel("")
        self.peeled.setWordWrap(True)
        self.peeled.setStyleSheet(theme.text_css(theme.ACCENT_TEXT))
        ql.addWidget(self.peeled)

        row = QHBoxLayout()
        self.giveup = QPushButton("Show me")
        self.giveup.setMinimumHeight(32)
        self.giveup.setToolTip("Give up on this one and show the answer (counts as missed)")
        self.giveup.clicked.connect(c.give_up)
        self.next_btn = QPushButton("Next  ›")
        self.next_btn.setMinimumHeight(32)
        theme.set_variant(self.next_btn, "primary")
        self.next_btn.clicked.connect(c.next_item)
        row.addWidget(self.giveup)
        row.addWidget(self.next_btn, 1)
        ql.addLayout(row)
        row2 = QHBoxLayout()
        row2.addStretch(1)
        end = QPushButton("End session")
        theme.set_variant(end, "ghost")
        end.clicked.connect(c.finish)
        row2.addWidget(end)
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
        for w in (self.choices, self.recall, self.order):
            w.hide()
        # a question with a diagram and six choices is taller than a laptop screen's dock: scroll, rather than
        # push the whole window taller than the screen
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(q)
        self.stack.addWidget(scroll)

        # ------------------------------------------------------------ summary page
        s = QWidget()
        sm = QVBoxLayout(s)
        sm.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        sm.addWidget(self.summary)
        self.missed_label = QLabel("Missed (double-click to see it again):")
        sm.addWidget(self.missed_label)
        self.missed = QListWidget()
        self.missed.setWordWrap(True)
        self.missed.itemDoubleClicked.connect(lambda it: c.show_missed(it.data(Qt.UserRole)))
        sm.addWidget(self.missed, 1)
        row3 = QHBoxLayout()
        self.retry = QPushButton("Retry missed")
        self.retry.clicked.connect(c.retry_missed)
        again = QPushButton("New session")
        again.clicked.connect(c.again)
        close = QPushButton("Close")
        close.clicked.connect(c.stop)
        for b in (self.retry, again, close):
            row3.addWidget(b)
        sm.addLayout(row3)
        self.stack.addWidget(s)

        for i in range(MAX_CHOICES):
            sc = QShortcut(QKeySequence(str(i + 1)), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda i=i: c.answer_choice(i))
        for key in ("Return", "Enter"):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(c.enter)


class PracticeController:
    def __init__(self, win, lessons_panel):
        self.win = win
        self.lp = lessons_panel
        self.ds = win.ds
        self.state = win.state
        self.res = getattr(win, "lesson_resolver", None)
        self.active = False
        self.dock = None
        self.panel = None
        self.lesson = None
        self.items = []
        self.pos = -1
        self.cur = None
        self.results = []
        self.retrying = False
        self._saved = {}
        self._snapshot = None
        self._marked = []
        self._flash = []
        self._flash_state = None
        self._peeled = []
        self._resolved = {}
        self._last_click = (-1, 0.0)
        self._flash_timer = QTimer()
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)
        self._own_stats = None

    # ------------------------------------------------------------------ the spaced-repetition store
    @property
    def stats(self):
        quiz = getattr(self.win, "quiz", None)
        if quiz is not None:
            return quiz.stats
        if self._own_stats is None:
            from .quiz import STATS_PATH
            self._own_stats, self._own_stats_backup = load_json(STATS_PATH, srs.normalize_stats)
        return self._own_stats

    def _save_stats(self):
        quiz = getattr(self.win, "quiz", None)
        if quiz is not None:
            return quiz.save_stats()
        from .quiz import STATS_PATH
        try:
            write_json(STATS_PATH, self.stats, indent=0, backup=self._own_stats_backup)
            self._own_stats_backup = False
            status = getattr(self.win, "statusBar", None)
            if status is not None and status().currentMessage().startswith("Could not save study results:"):
                status().clearMessage()
            return True
        except OSError as exc:
            status = getattr(self.win, "statusBar", None)
            if status is not None:
                status().showMessage(f"Could not save study results: {exc}", 10000)
            return False

    # ------------------------------------------------------------------ lifecycle
    def _ensure_dock(self):
        if self.dock is not None:
            return
        self.panel = PracticePanel(self)
        self.dock = QDockWidget("PRACTICE")
        self.dock.setObjectName("practice_dock")
        self.dock.setWidget(self.panel)
        self.dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                              QDockWidget.DockWidgetClosable)
        self.panel.setMinimumWidth(330)
        self.win.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(self._dock_visibility)

    def _dock_visibility(self, visible):
        if not visible and self.active and not self.dock.isFloating() and not self.win.isMinimized():
            QTimer.singleShot(0, self.dock, lambda: self.stop() if self.dock and not self.dock.isVisible() else None)

    def start(self, lesson, n=None, items=None):
        """A session on `lesson`: n items (None = the lesson's default, 0 = everything), or exactly `items`."""
        quiz = getattr(self.win, "quiz", None)
        if quiz is not None:
            if quiz.active:
                quiz.stop()
            quiz.delegate = self
        self._ensure_dock()
        if not self.active:
            self._saved = {k: self.win.settings.get(k) for k in ("show_landmarks", "show_hover_tooltip")}
            self._saved["details_visible"] = self.win.right_dock.isVisible()
            self._snapshot = capture_scene(self.win)
        self._end_item()
        self.lesson = lesson
        self.retrying = items is not None
        if items is None:
            pool = self._prepare(practice_pool(lesson, self.lp.lessons))
            if n is None:
                n = default_length(lesson, len(pool))
            items = build_session(pool, n, self.stats)
        self.items = list(items)
        self.pos = -1
        self.results = []
        self.active = True
        self.win.right_dock.hide()            # the details panel names whatever is selected
        self.dock.show()
        self.dock.raise_()
        self.panel.where.setText(("Retrying missed · " if self.retrying else "") + lesson.title)
        self.panel.stack.setCurrentIndex(0)
        if not self.items:
            self.panel.feedback.setText("Nothing to practise in this lesson yet.")
            self.finish()
            return
        self.next_item()

    def stop(self):
        if not self.active:
            return
        self._end_item()
        self.active = False
        self.cur = None
        self._restore_names()
        if self._snapshot is not None:
            restore_scene(self.win, self._snapshot)
            self._snapshot = None
        if self.dock is not None:
            self.dock.hide()
        self.win.right_dock.setVisible(self._saved.get("details_visible", True))

    def _prepare(self, pool):
        """Keep the items this install can actually ask, with their atlas structures resolved."""
        out = []
        micro = getattr(self.win.content, "micro_models", {})
        for item in pool:
            kind = item.get("type")
            item = dict(item)
            if kind in ("find", "name"):
                sids = self._resolve(item.get("structure"))
                if not sids:
                    continue
                item["_sids"] = sids
                bases = {self.ds.structures[s]["base"] for s in sids}
                if len(bases) == 1:
                    item["_base"] = bases.pop()
            elif kind == "find_micro":
                if item.get("model") not in micro or not item.get("part"):
                    continue
            elif kind == "mcq":
                choices = item.get("choices") or []
                if len(choices) < 2 or not 0 <= int(item.get("answer", -1)) < len(choices):
                    continue
            elif kind == "order":
                if len(item.get("items") or []) < 2:
                    continue
            elif kind == "recall":
                if not item.get("q"):
                    continue
            out.append(item)
        return out

    def _resolve(self, name):
        key = (name or "").strip().lower()
        if key not in self._resolved:
            self._resolved[key] = self.res.resolve(name) if self.res is not None and key else []
        return self._resolved[key]

    # ------------------------------------------------------------------ what the rest of the app asks
    def _live(self):
        return (self.active and self.cur is not None and not self.cur["done"] and self.panel is not None
                and self.panel.stack.currentIndex() == 0)

    def names_hidden(self):
        return self._live() and self.cur["item"]["type"] in ("find", "name", "find_micro")

    def _hide_names(self):
        for k in ("show_landmarks", "show_hover_tooltip"):
            self.win.settings[k] = False
        self.win.viewport.landmark_hosts = []
        self.win.viewport.update()

    def _restore_names(self):
        for k in ("show_landmarks", "show_hover_tooltip"):
            if k in self._saved:
                self.win.settings[k] = self._saved[k] if self._saved[k] is not None else True
        self.win.viewport.update()

    # ------------------------------------------------------------------ items
    def next_item(self):
        if not self.active:
            return
        if self.cur is not None and not self.cur["done"] and self.pos >= 0:
            self._record(False)                     # moving on without answering counts as a miss
        self._end_item()
        self.pos += 1
        if self.pos >= len(self.items):
            self.finish()
            return
        item = self.items[self.pos]
        self.cur = {"item": item, "wrong": 0, "done": False, "helped": False}
        p = self.panel
        p.stack.setCurrentIndex(0)
        p.progress.setText(f"{self.pos + 1} of {len(self.items)}")
        self._update_score()
        kind = item["type"]
        p.kind.setText(TYPE_NAME.get(kind, kind).upper())
        p.tips.setText(TIPS.get(kind, ""))
        p.feedback.setText("")
        p.peeled.setText("")
        p.diagram.set_diagram(item.get("diagram"))
        for w in (p.choices, p.recall, p.order):
            w.hide()
        p.giveup.setVisible(kind in ("find", "find_micro"))
        p.giveup.setEnabled(True)
        p.next_btn.setText("Skip  ›")
        getattr(self, f"_ask_{kind}")(item)

    def _end_item(self):
        """Undo whatever the last item did to a 3D view."""
        self._clear_flash()
        if self._marked:
            restore_colors(self.state, getattr(self, "_marked_colors", {}))
            self._marked = []
            self._marked_colors = {}
        if self._peeled:
            self.state.set_hidden(self._peeled, False, undo=False)
            self._peeled = []
        cur = self.cur
        view = cur.get("view") if cur else None
        if view is not None:
            try:
                view.state.set_custom_color(list(range(view.mds.n)), None)
                view.state.clear_ghost()
                view.state.clear_selection()
                view.set_practice(None)
            except RuntimeError:            # the model's tab was closed mid-question
                pass
            cur["view"] = None

    def _update_score(self):
        answered = len(self.results)
        right = sum(1 for _i, ok in self.results if ok)
        pct = f" · {round(100 * right / answered)}%" if answered else ""
        self.panel.score.setText(f"{right} right{pct}")

    def _record(self, ok):
        cur = self.cur
        cur["done"] = True
        cur["ok"] = ok
        item = cur["item"]
        key = item_key(item)
        st = self.stats.setdefault(key, {"seen": 0, "miss": 0})
        st["seen"] = int(st.get("seen", 0)) + 1
        if not ok:
            st["miss"] = int(st.get("miss", 0)) + 1
        if item["type"] not in ("find", "name"):
            st["label"] = self._describe(item)
        srs.update(st, srs.grade_for(ok, cur["helped"], cur["wrong"]))
        self._save_stats()
        self.results.append((item, ok))
        self._restore_names()
        p = self.panel
        p.giveup.hide()
        p.next_btn.setText("Next  ›" if self.pos < len(self.items) - 1 else "See results  ›")
        self._update_score()

    @staticmethod
    def _describe(item):
        kind = item["type"]
        if kind in ("find", "name"):
            return item.get("structure", "")
        if kind == "find_micro":
            return f"{item.get('part')} (in {item.get('model')})"
        return " ".join(str(item.get("q", "")).split())[:120]

    @staticmethod
    def _answer_line(item):
        """The answer, under a missed question in the summary, so the list can be read as a revision sheet."""
        kind = item["type"]
        if kind == "mcq":
            return "\n   → " + str(item["choices"][int(item["answer"])])
        if kind == "recall":
            return "\n   → " + " ".join(str(item.get("a", "")).split())[:160]
        if kind == "order":
            return "\n   → " + " › ".join(item["items"])
        return ""

    def _why(self, item):
        why = item.get("why")
        return f"<br><span style='color:{theme.TEXT_2}'>{esc(why)}</span>" if why else ""

    def enter(self):
        """Return: check an order, or move on once the item is answered."""
        cur = self.cur
        if cur is None or self.panel.stack.currentIndex() != 0:
            return
        if not cur["done"]:
            kind = cur["item"]["type"]
            if kind == "order":
                self.check_order()
            elif kind == "recall" and not cur.get("shown"):
                self.reveal_recall()
            return
        self.next_item()

    # ------------------------------------------------------------------ find / name in the atlas
    def _stage_scene(self, item):
        """Set the atlas up the way the lesson that taught this structure did - without pointing at it."""
        sids = item["_sids"]
        lesson = self.lp.by_id.get(item.get("_lesson"))
        target = set(sids)
        step = None
        for s in (lesson.steps if lesson else []):
            names = [n for k in ("focus", "show", "ghost_focus", "frame_on") for n in s.get(k, [])]
            if item["structure"].lower() in (n.lower() for n in names) or \
                    target & set(self.res.resolve_all(names) if self.res else []):
                step = s
                break
        wide = False
        if step is not None:
            scene = {k: step[k] for k in SCENE_KEYS if k in step}
            names = list(scene.pop("focus", [])) + list(scene.pop("ghost_focus", [])) + list(scene.get("show", []))
            scene["show"] = names
            if not any(k in scene for k in ("frame_on", "camera", "clip")):
                scene["frame_on"] = names
            wide = set(self.res.resolve_all(scene.get("frame_on", []))) <= target if self.res else False
        else:
            scene = {"systems": sorted({self.ds.structures[s]["system"] for s in sids}),
                     "regions": [r["key"] for r in self.ds.regions],
                     "show": [item["structure"]], "frame_on": [item["structure"]]}
            wide = True
        scene["xray"] = False
        if self.win.center.currentIndex() != 0:
            self.win.center.setCurrentIndex(0)
        self.win.apply_scene(scene)
        st = self.state
        st.set_hidden(sids, False, undo=False)
        st.force_show(sids)
        st.clear_ghost()
        st.clear_selection()
        self.win.viewport.focus_landmark = None
        if wide:
            # framing on the answer alone would put it dead centre; stand back so the neighbours are in view too
            b = self.ds.bounds_of(sids)
            if b is not None:
                lo, hi = np.asarray(b[0]), np.asarray(b[1])
                self.win.viewport.frame_point((lo + hi) / 2, max(float(np.linalg.norm(hi - lo)) * 2.2, 0.14))

    def _ask_find(self, item):
        self._stage_scene(item)
        self._hide_names()
        self.panel.prompt.setText(esc(item["structure"]))
        self._peeled = []
        self.win.viewport.setFocus()

    def _ask_name(self, item):
        self._stage_scene(item)
        self._hide_names()
        sids = item["_sids"]
        st = self.state
        st.select(sids)
        st.set_ghost_focus(sids)
        self.win.viewport.frame_structures(sids)
        self.panel.prompt.setText("Which structure is highlighted?")
        options = [item["structure"]] + self._distractors(item, 3)
        random.shuffle(options)
        self._set_choices(options, options.index(item["structure"]))

    def _distractors(self, item, k):
        """Names taught alongside this one - the same lesson, the rest of its lab - that are not this structure."""
        lesson = self.lp.by_id.get(item.get("_lesson"))
        family = [lesson] if lesson else []
        if lesson is not None and lesson.unit_key:
            family += [x for x in self.lp.lessons if x.unit_key == lesson.unit_key and x is not lesson]
        names = [x.get("structure", "") for x in self.items if x.get("type") in ("find", "name")]
        for other in family:
            names += [x.get("structure", "") for x in other.practice if x.get("type") in ("find", "name")]
            names += other.names()
        target = set(item["_sids"])
        system = self.ds.structures[item["_sids"][0]]["system"]
        words = set(item["structure"].lower().split())
        seen = {item["structure"].lower()}
        scored = []
        for n in names:
            if not n or n.lower() in seen:
                continue
            seen.add(n.lower())
            sids = self._resolve(n)
            if not sids or set(sids) & target:
                continue
            same = self.ds.structures[sids[0]]["system"] == system
            scored.append((-(2 if same else 0) - len(words & set(n.lower().split())) - random.random() * 1.5, n))
        scored.sort()
        out = [n for _s, n in scored[:k]]
        if len(out) < k:                    # a lesson that names very little: borrow from the same subsystem
            sub = self.ds.structures[item["_sids"][0]]["subsystem"]
            bases = sorted({s["base"] for s in self.ds.structures if s["subsystem"] == sub and s["id"] not in target
                            and s["base"].lower() not in seen})
            random.shuffle(bases)
            out += bases[:k - len(out)]
        return out

    def handle_click(self, sid, modifiers=None):
        """Clicks in the atlas, while an item is up. True when Practice took the click."""
        cur = self.cur
        if not self._live():
            return False
        kind = cur["item"]["type"]
        if kind == "name":
            return True                            # clicking round would move the highlight off the question
        if kind != "find":
            return False
        if sid < 0:
            return True
        now = time.perf_counter()
        last_sid, last_t = self._last_click
        if sid == last_sid and now - last_t < 0.4:
            return True                            # the second half of a double click must not cost a try
        self._last_click = (sid, now)
        item = cur["item"]
        s = self.ds.structures[sid]
        if sid in item["_sids"] or (item.get("_base") and s["base"] == item["_base"]):
            self.panel.feedback.setText(OK_HTML.format("Correct!" if not cur["wrong"] else "Correct.")
                                        + self._why(item))
            self._record(True)
            self._show_answer(item["_sids"], GREEN)
            return True
        cur["wrong"] += 1
        self._flash_red(self.state, [sid])
        if cur["wrong"] >= 3:
            self.panel.feedback.setText(BAD_HTML.format(f"That was {esc(s['base'])}.")
                                        + f" Here is <b>{esc(item['structure'])}</b>, in green." + self._why(item))
            self._record(False)
            self._show_answer(item["_sids"], GREEN)
        else:
            left = 3 - cur["wrong"]
            self.panel.feedback.setText(BAD_HTML.format(f"No — that is {esc(s['base'])}.")
                                        + f" {left} {'try' if left == 1 else 'tries'} left.")
        return True

    def handle_right_click(self, sid):
        cur = self.cur
        if not self._live() or cur["item"]["type"] != "find":
            return False
        if sid >= 0:
            self.state.set_hidden([sid], True)
            self._peeled.append(int(sid))
            n = len(self._peeled)
            self.panel.peeled.setText(f"{n} structure{'s' if n != 1 else ''} peeled away")
        return True

    def _show_answer(self, sids, colour):
        st = self.state
        st.force_show(sids)
        st.set_hidden(sids, False, undo=False)
        st.select(sids)
        st.set_ghost_focus(sids)
        self._marked_colors = highlight(st, sids, colour, getattr(self, "_marked_colors", None))
        self._marked = list(sids)
        b = self.ds.bounds_of(sids)
        if b is not None:                   # in its setting, not filling the screen
            lo, hi = np.asarray(b[0]), np.asarray(b[1])
            self.win.viewport.frame_point((lo + hi) / 2, max(float(np.linalg.norm(hi - lo)) * 1.4, 0.06))

    def _flash_red(self, state, sids):
        self._clear_flash()
        self._flash_state = state
        self._flash = list(sids)
        self._flash_colors = highlight(state, self._flash, RED)
        self._flash_timer.start(900)

    def _clear_flash(self):
        self._flash_timer.stop()
        if self._flash and self._flash_state is not None:
            restore_colors(self._flash_state, getattr(self, "_flash_colors", {}))
        self._flash = []
        self._flash_colors = {}

    def give_up(self):
        cur = self.cur
        if cur is None or cur["done"]:
            return
        item = cur["item"]
        kind = item["type"]
        if kind == "find":
            self.panel.feedback.setText(f"It is <b>{esc(item['structure'])}</b>, in green." + self._why(item))
            self._record(False)
            self._show_answer(item["_sids"], GREEN)
        elif kind == "find_micro":
            self.panel.feedback.setText(f"It is <b>{esc(item['part'])}</b>, in green." + self._why(item))
            self._record(False)
            self._show_micro_answer()

    # ------------------------------------------------------------------ find in a microanatomy model
    def _ask_find_micro(self, item):
        p = self.panel
        self.win.open_micro(item["model"])
        view = self.win.micro_tabs.get(item["model"])
        sids, _missing = view.part_ids([item["part"]]) if view is not None else ([], [])
        if not sids:
            p.prompt.setText(esc(item["part"]))
            p.feedback.setText(f"<span style='color:{theme.WARNING}'>This model has no part called “{esc(item['part'])}” "
                               "yet - skipped.</span>")
            self.cur["done"] = True                 # not the student's fault: no mark either way
            p.giveup.hide()
            p.next_btn.setText("Next  ›")
            return
        self.cur["view"] = view
        self.cur["sids"] = sids
        view.set_practice(self._micro_click, self._micro_rclick)
        self._hide_names()
        p.prompt.setText(esc(item["part"]) + f"<div style='font-size:{theme.FS_BODY}pt; color:{theme.MUTED}; font-weight:400'>in "
                         f"{esc(view.model.name)}</div>")
        view.gl_widget.setFocus()

    def _micro_click(self, sid):
        cur = self.cur
        if not self._live() or cur.get("view") is None:
            return False                    # answered: the model is yours to click round again
        if sid < 0:
            return True
        view = cur["view"]
        item = cur["item"]
        name = view.mds.parts[sid].name
        if sid in cur["sids"]:
            self.panel.feedback.setText(OK_HTML.format("Correct!" if not cur["wrong"] else "Correct.")
                                        + self._why(item))
            self._record(True)
            self._show_micro_answer()
            return True
        cur["wrong"] += 1
        self._flash_red(view.state, [sid])
        if cur["wrong"] >= 3:
            self.panel.feedback.setText(BAD_HTML.format(f"That was {esc(name)}.")
                                        + f" Here is <b>{esc(item['part'])}</b>, in green." + self._why(item))
            self._record(False)
            self._show_micro_answer()
        else:
            left = 3 - cur["wrong"]
            self.panel.feedback.setText(BAD_HTML.format(f"No — that is {esc(name)}.")
                                        + f" {left} {'try' if left == 1 else 'tries'} left.")
        return True

    def _micro_rclick(self, sid):
        cur = self.cur
        if self._live() and cur.get("view") is not None and sid >= 0:
            cur["view"].state.set_hidden([sid], True)
            n = cur.setdefault("peeled", 0) + 1
            cur["peeled"] = n
            self.panel.peeled.setText(f"{n} part{'s' if n != 1 else ''} peeled away")

    def _show_micro_answer(self):
        view, sids = self.cur.get("view"), self.cur.get("sids")
        if view is None or not sids:
            return
        try:
            view.gl_widget.isVisible()
        except RuntimeError:                # its tab was closed
            return
        view.state.set_hidden(sids, False, undo=False)
        view.state.set_custom_color(sids, GREEN)
        view.state.select(sids)
        view.state.set_ghost_focus(sids)
        view._refresh_labels()
        view.gl_widget.frame_structures(sids)

    # ------------------------------------------------------------------ multiple choice
    def _set_choices(self, options, right):
        p = self.panel
        self.cur["options"] = options
        self.cur["right"] = right
        for i, b in enumerate(p.choice_buttons):
            if i < len(options):
                b.setText(f"{i + 1}.  {options[i]}")
                b.setStyleSheet(BTN)
                b.setEnabled(True)
                b.show()
            else:
                b.hide()
        p.choices.show()

    def _ask_mcq(self, item):
        self.panel.prompt.setText(esc(item["q"]))
        # shuffled every time, so the right answer is never learnt by its position; catch-all options
        # ("all of the above", "both", "neither"...) keep their place at the end
        choices = list(item["choices"])
        right = choices[int(item["answer"])]
        tail = [c for c in choices if c.strip().lower().startswith(("all of", "none of", "both", "neither"))]
        head = [c for c in choices if c not in tail]
        random.shuffle(head)
        order = head + tail
        self._set_choices(order, order.index(right))

    def answer_choice(self, i):
        cur = self.cur
        if cur is None or cur["done"] or "options" not in cur or i >= len(cur["options"]):
            return
        p = self.panel
        ok = i == cur["right"]
        for j, b in enumerate(p.choice_buttons[:len(cur["options"])]):
            b.setEnabled(False)
            if j == cur["right"]:
                b.setStyleSheet(BTN_RIGHT)
            elif j == i:
                b.setStyleSheet(BTN_WRONG)
        right = esc(cur["options"][cur["right"]])
        item = cur["item"]
        p.feedback.setText((OK_HTML.format("Correct!") if ok else
                            BAD_HTML.format("Not quite") + f" — it is <b>{right}</b>.") + self._why(item))
        self._record(ok)
        if item["type"] == "name":
            self._show_answer(item["_sids"], GREEN if ok else RED)
            p.prompt.setText(esc(item["structure"]))

    # ------------------------------------------------------------------ recall
    def _ask_recall(self, item):
        p = self.panel
        p.prompt.setText(esc(item["q"]))
        p.answer.setText(esc(item.get("a", "")) + self._why(item))
        p.answer.hide()
        p.grade_row.hide()
        p.show_answer.show()
        p.knew.setEnabled(True)
        p.didnt.setEnabled(True)
        p.recall.show()

    def reveal_recall(self):
        cur = self.cur
        if cur is None or cur["item"]["type"] != "recall" or cur["done"]:
            return
        cur["shown"] = True
        p = self.panel
        p.show_answer.hide()
        p.answer.show()
        p.grade_row.show()

    def grade_recall(self, knew):
        cur = self.cur
        if cur is None or cur["done"] or not cur.get("shown"):
            return
        self.panel.knew.setEnabled(False)
        self.panel.didnt.setEnabled(False)
        self.panel.feedback.setText(OK_HTML.format("Good.") if knew else
                                    BAD_HTML.format("It will come back sooner."))
        self._record(knew)

    # ------------------------------------------------------------------ order
    def _ask_order(self, item):
        p = self.panel
        p.prompt.setText(esc(item.get("q") or "Put these in order"))
        rows = list(item["items"])
        shuffled = rows[:]
        for _ in range(8):                  # a shuffle that happens to come out right is no question
            random.shuffle(shuffled)
            if shuffled != rows:
                break
        p.order_list.clear()
        for text in shuffled:
            p.order_list.addItem(QListWidgetItem(text))
        p.order_list.setEnabled(True)
        p.check_order.setEnabled(True)
        p.order.show()
        # a long row wraps onto a second line; leave room for it rather than scroll
        p.order_list.setFixedHeight(min(360, 12 + sum(32 + 18 * (len(r) // 38) for r in rows)))

    def move_order(self, d):
        lst = self.panel.order_list
        row = lst.currentRow()
        if row < 0 or not 0 <= row + d < lst.count() or self.cur is None or self.cur["done"]:
            return
        it = lst.takeItem(row)
        lst.insertItem(row + d, it)
        lst.setCurrentRow(row + d)

    def check_order(self):
        cur = self.cur
        if cur is None or cur["done"] or cur["item"]["type"] != "order":
            return
        p = self.panel
        want = list(cur["item"]["items"])
        got = [p.order_list.item(i).text() for i in range(p.order_list.count())]
        ok = got == want
        right = sum(1 for a, b in zip(got, want) if a == b)
        for i in range(p.order_list.count()):
            it = p.order_list.item(i)
            it.setForeground(theme.qc(theme.SUCCESS) if got[i] == want[i] else theme.qc(theme.DANGER))
        p.order_list.setEnabled(False)
        p.check_order.setEnabled(False)
        answer = "<br>".join(f"{i + 1}. {esc(x)}" for i, x in enumerate(want))
        p.feedback.setText((OK_HTML.format("All in order!") if ok else
                            BAD_HTML.format(f"{right} of {len(want)} in the right place.") +
                            f"<br><span style='color:{theme.TEXT_2}'>{answer}</span>") + self._why(cur["item"]))
        self._record(ok)

    # ------------------------------------------------------------------ the end
    def finish(self):
        if self.cur is not None and not self.cur["done"] and self.pos < len(self.items):
            self.cur["done"] = True            # ending early: the unanswered one is simply not counted
        self._end_item()
        self._restore_names()
        self.cur = None
        p = self.panel
        answered = len(self.results)
        right = sum(1 for _i, ok in self.results if ok)
        if answered:
            pct = round(100 * right / answered)
            by_type = {}
            for item, ok in self.results:
                a, b = by_type.get(item["type"], (0, 0))
                by_type[item["type"]] = (a + int(ok), b + 1)
            rows = " · ".join(f"{TYPE_NAME.get(k, k)} {a}/{b}" for k, (a, b) in by_type.items())
            verdict = ("Excellent." if pct >= 90 else "Good work." if pct >= 75 else
                       "Getting there - retry the ones you missed." if pct >= 50 else
                       "Worth another pass through Learn, then try again.")
            p.summary.setText(f"<p style='font-size:{theme.FS_H1 + 5}pt; font-weight:700; color:{theme.TEXT_STRONG};"
                              f" margin-bottom:2px'>{right} / {answered} <span style='color:{theme.ACCENT_TEXT}'>"
                              f"({pct}%)</span></p><p style='color:{theme.MUTED}'>{esc(self.lesson.title)}</p>"
                              f"<p>{verdict}</p><p style='color:{theme.MUTED}; font-size:{theme.FS_SMALL}pt'>{rows}</p>")
            if not self.retrying:
                self.lp.progress.record_practice(self.lesson.id, right, answered)
        else:
            p.summary.setText(f"<p style='font-size:{theme.FS_H1}pt; font-weight:700; color:{theme.TEXT_STRONG}'>"
                              "Nothing answered</p>")
        missed = [item for item, ok in self.results if not ok]
        p.missed.clear()
        for item in missed:
            it = QListWidgetItem(f"{TYPE_NAME.get(item['type'], item['type'])} · {self._describe(item)}"
                                 + self._answer_line(item))
            it.setData(Qt.UserRole, item)
            p.missed.addItem(it)
        p.missed_label.setVisible(bool(missed))
        p.missed.setVisible(bool(missed))
        p.retry.setVisible(bool(missed))
        p.retry.setText(f"Retry missed ({len(missed)})")
        p.stack.setCurrentIndex(1)
        self.state.clear_ghost()
        self.state.clear_selection()
        self.lp.practice_finished(self.lesson.id)

    def retry_missed(self):
        missed = [item for item, ok in self.results if not ok]
        if missed:
            random.shuffle(missed)
            self.start(self.lesson, items=missed)

    def again(self):
        if self.lesson is not None:
            n = None
            if self.lesson.practice_from:
                n = self.lp.length.currentData()
            self.start(self.lesson, n)

    def show_missed(self, item):
        if not item:
            return
        if item["type"] in ("find", "name") and item.get("_sids"):
            self.win.select_and_focus(item["_sids"], xray=True, info=False)
        elif item["type"] == "find_micro":
            self.win.open_micro(item["model"])
            view = self.win.micro_tabs.get(item["model"])
            if view is not None:
                view.focus_parts([item["part"]])
