"""The Lessons tab: a library segmented by body system, region or level, and a runner that teaches one lesson.

The runner is deliberately more than a slideshow. Every lesson opens on what you should be able to do by the
end, every step can ask you a question before you move on, and the last step collects the things worth
remembering. How far you got is kept between runs, so the library shows what you have finished.

Lessons written for the lab course sit at the top under "My lab course", one heading per lab in course order.
Each opens on a cover with two ways in: Learn (the stepper) and Practice (a short graded session built from the
lesson's practice items and step questions - see practice.py).
"""
from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QShortcut, QTextDocument
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..lessons import LessonProgress, course_units, group_lessons, practice_pool
from .card_list import CardList

# one colour per body system, so the stripe down the side of a card says what kind of lesson it is
SYSTEM_COLOUR = {
    "skeletal": "#cbb89a", "muscular": "#d4736f", "cardiovascular": "#e0707a", "respiratory": "#7fb2f0",
    "digestive": "#e8b45c", "urinary": "#6cc4b0", "reproductive": "#d78fc0", "endocrine": "#c79ae0",
    "lymphatic": "#8fc98f", "nervous": "#e8d15c", "sensory": "#7fd0e0", "integumentary": "#c9a68a",
}
LEVEL_MARK = {"foundation": "●", "core": "●●", "advanced": "●●●"}
EXAM_LENGTHS = [(20, "20 questions"), (40, "40 questions"), (60, "60 questions"), (0, "Everything")]
PAGE_LIBRARY, PAGE_RUNNER, PAGE_COVER = 0, 1, 2


class StepBar(QWidget):
    """The row of segments under the title: how many steps, which one you are on, which you have seen."""

    stepClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.total = 0
        self.index = 0
        self.seen = set()
        self.setFixedHeight(14)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_state(self, total, index, seen):
        self.total, self.index, self.seen = total, index, set(seen)
        self.update()

    def _rects(self):
        if not self.total:
            return []
        gap = 3.0
        w = (self.width() - gap * (self.total - 1)) / self.total
        return [QRectF(i * (w + gap), 4.0, max(w, 2.0), 6.0) for i in range(self.total)]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i, r in enumerate(self._rects()):
            if i == self.index:
                p.setBrush(QColor("#4fc3f7"))
            elif i in self.seen:
                p.setBrush(QColor("#39708c"))
            else:
                p.setBrush(QColor("#2c3440"))
            p.drawRoundedRect(r, 3, 3)
        p.end()

    def mousePressEvent(self, e):
        for i, r in enumerate(self._rects()):
            if r.adjusted(-1.5, -4, 1.5, 4).contains(e.position()):
                self.stepClicked.emit(i)
                return


class LessonsPanel(QWidget):
    stepRequested = Signal(object)          # the step dict to apply to the scene
    lessonOpened = Signal(object)           # Lesson
    lessonClosed = Signal()
    quizRequested = Signal(object)          # Lesson - test me on everything it named
    linkActivated = Signal(str, str)        # scheme, payload - "see also" links out of a lesson

    def __init__(self, lessons, parent=None):
        super().__init__(parent)
        self.lessons = lessons
        self.by_id = {x.id: x for x in lessons}
        self.ref_titles = {}                    # scheme -> {id: readable name}, for the "where next" links
        self.lesson = None
        self.index = 0
        self.progress = LessonProgress()
        self.has_course = any(x.unit_key for x in lessons)
        self.group_by = "course" if self.has_course else "system"
        self.answer_shown = False
        self.practice = None                    # PracticeController, made the first time Practice is pressed
        self._diagram_shown = None
        self.stack = QStackedWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.stack)
        self.stack.addWidget(self._build_library())
        self.stack.addWidget(self._build_runner())
        self.stack.addWidget(self._build_cover())
        self._diagram_timer = QTimer(self)
        self._diagram_timer.setSingleShot(True)
        self._diagram_timer.timeout.connect(self._rerender_diagram)
        self._fill()

    def set_lessons(self, lessons):
        """Swap the library for another list of lessons (used to preview a draft course file)."""
        self.lessons = lessons
        self.by_id = {x.id: x for x in lessons}
        self.has_course = any(x.unit_key for x in lessons)
        for b in self.group_buttons.buttons():
            if b.property("group_key") == "course":
                b.setVisible(self.has_course)
        self._set_group("course" if self.has_course else "system")

    def main_window(self):
        """The application window, whether or not the Explore dock is floating."""
        win = self.window()
        if hasattr(win, "apply_scene"):
            return win
        for w in QApplication.topLevelWidgets():
            if hasattr(w, "apply_scene") and hasattr(w, "micro_tabs"):
                return w
        return None

    # ================================================================== library
    def _build_library(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        intro = QLabel("Guided walks that set the view up for you, step by step. Each one opens with what you "
                       "should be able to do by the end and closes with what to remember.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#aab3c0;")
        lay.addWidget(intro)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter lessons…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._fill)
        lay.addWidget(self.filter)

        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(QLabel("Group by"))
        self.group_buttons = QButtonGroup(self)
        for key, label in (("course", "Course"), ("system", "System"), ("region", "Region"),
                           ("level", "Level")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(key == self.group_by)
            b.setProperty("group_key", key)
            b.clicked.connect(lambda _c=False, k=key: self._set_group(k))
            if key == "course":
                b.setToolTip("Your lab course, lab by lab, in the order it is taught. Lessons outside the course "
                             "follow underneath, by body system.")
                b.setVisible(self.has_course)
            self.group_buttons.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        self.stats = QLabel()
        self.stats.setStyleSheet("color:#8a94a3; font-size:8.5pt;")
        lay.addWidget(self.stats)

        self.list = CardList()
        self.list.itemActivated.connect(self._open_item)
        self.list.itemClicked.connect(self._open_item)
        lay.addWidget(self.list, 1)
        return page

    def show_course(self):
        """The library, grouped as the lab course (for a "Lab course" entry point elsewhere in the app)."""
        if self.stack.currentIndex() != PAGE_LIBRARY:
            self.close_lesson()
        self._set_group("course" if self.has_course else "system")

    def _set_group(self, key):
        self.group_by = key
        for b in self.group_buttons.buttons():
            b.setChecked(b.property("group_key") == key)
        self._fill()

    def _matches(self, lesson, needle):
        if not needle:
            return True
        hay = " ".join([lesson.title, lesson.summary, lesson.system_name, lesson.region_name, lesson.level_name,
                        lesson.unit_name, " ".join(lesson.tags), " ".join(lesson.objectives)]).lower()
        return needle in hay

    def _fill(self):
        needle = self.filter.text().strip().lower()
        shown = [x for x in self.lessons if self._matches(x, needle)]
        self.list.clear()

        done, started, total = self.progress.totals(self.lessons)
        bits = [f"{total} lessons", f"{sum(len(x) for x in self.lessons)} steps"]
        if done:
            bits.append(f"{done} finished")
        if started:
            bits.append(f"{started} in progress")
        self.stats.setText(" · ".join(bits))

        if not needle:
            for lesson in self.progress.in_progress(self.lessons)[:1]:
                self.list.add_header("Continue")
                self._add_card(lesson, prefix="Resume at step "
                               f"{min(self.progress.last_step(lesson.id) + 1, len(lesson))} · ")
        if self.group_by == "course":
            self._fill_course(shown)
        else:
            for heading, _key, group in group_lessons(shown, self.group_by):
                self.list.add_header(f"{heading}  ({len(group)})")
                for lesson in group:
                    self._add_card(lesson)
        if self.list.count() == 0:
            self.list.add_note("No lesson matches that.")

    def _fill_course(self, shown):
        """My lab course first - each lab and lab practical under its own heading, mini lessons in the order they
        are taught - then every other lesson by body system."""
        course = [x for x in shown if x.unit_key]
        rest = [x for x in shown if not x.unit_key]
        for heading, _key, group in course_units(course):
            done = sum(1 for x in group if self._finished(x))
            short, _sep, topic = heading.partition(" · ")
            self.list.add_header(f"{short}  {done}/{len(group)} ✓" + (f"  ·  {topic}" if topic else ""))
            for lesson in group:
                self._add_card(lesson)
        for heading, _key, group in group_lessons(rest, "system"):
            self.list.add_header(f"{heading}  ({len(group)})")
            for lesson in group:
                self._add_card(lesson)

    def _finished(self, lesson):
        """A lesson counts as done once it has been read through - or, for one that is only practice, such as a
        practice exam, once it has been practised."""
        if len(lesson):
            return self.progress.is_done(lesson.id)
        return bool(self.progress.practice(lesson.id))

    def _add_card(self, lesson, prefix=""):
        n = len(lesson)
        frac = self.progress.fraction(lesson.id, n)
        done = self._finished(lesson)
        badge = f"{n} step{'s' if n != 1 else ''}" if n else "Practice"
        tip = (f"{lesson.system_name} · {lesson.region_name} · {lesson.level_name} · about {lesson.minutes} min"
               + ("\nFinished" if done else ""))
        title = lesson.title
        summary = prefix + lesson.summary
        if lesson.unit_key:
            title = ("✓ " if done else "") + lesson.title
            rec = self.progress.practice(lesson.id)
            if rec:
                summary = f"Practice best {rec.get('best')}% · " + summary
                tip += f"\nPractice: best {rec.get('best')}%, last {rec.get('last')}%"
        self.list.add_card(title, summary, badge=badge,
                           accent=SYSTEM_COLOUR.get(lesson.system, ""), data=lesson.id, tooltip=tip,
                           progress=frac, done=done)

    def _open_item(self, item):
        lid = item.data(Qt.UserRole)
        if not lid:
            return
        lesson = self.by_id.get(lid)
        if lesson is not None and (lesson.unit_key or not len(lesson)):
            self.open_cover(lid)
        else:
            self.open_lesson(lid)

    # ================================================================== cover: Learn or Practice
    def _build_cover(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(8)
        back = QPushButton("‹ All lessons")
        back.setFlat(True)
        back.clicked.connect(self.close_lesson)
        lay.addWidget(back, 0, Qt.AlignLeft)
        self.cover_unit = QLabel()
        self.cover_unit.setStyleSheet("color:#8fd3ff; font-size:8.5pt; font-weight:600;")
        lay.addWidget(self.cover_unit)
        self.cover_title = QLabel()
        self.cover_title.setStyleSheet("font-size:15pt; font-weight:600;")
        self.cover_title.setWordWrap(True)
        lay.addWidget(self.cover_title)
        self.cover_body = QTextBrowser()
        self.cover_body.setOpenLinks(False)
        self.cover_body.anchorClicked.connect(self._anchor)
        lay.addWidget(self.cover_body, 1)

        big = "QPushButton { font-size:11pt; font-weight:600; padding:10px 8px; }"
        self.learn_btn = QPushButton("Learn  ›")
        self.learn_btn.setStyleSheet(big)
        self.learn_btn.setToolTip("Step through the lesson: each step sets the 3D view up for you")
        self.learn_btn.clicked.connect(lambda: self.lesson and self.open_lesson(self.lesson.id))
        self.practice_btn = QPushButton("Practice  ›")
        self.practice_btn.setStyleSheet(big + "QPushButton { background:#1f4a33; }")
        self.practice_btn.setToolTip("A short graded session: find, name, pick and recall what this lesson covers")
        self.practice_btn.clicked.connect(self._practice_from_cover)
        row = QHBoxLayout()
        row.addWidget(self.learn_btn, 1)
        row.addWidget(self.practice_btn, 1)
        lay.addLayout(row)
        self.length_row = QWidget()
        lr = QHBoxLayout(self.length_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.addWidget(QLabel("Length"))
        self.length = QComboBox()
        for n, label in EXAM_LENGTHS:
            self.length.addItem(label, n)
        self.length.setCurrentIndex(1)
        lr.addWidget(self.length, 1)
        lay.addWidget(self.length_row)
        self.cover_note = QLabel()
        self.cover_note.setWordWrap(True)
        self.cover_note.setStyleSheet("color:#8a94a3; font-size:8.5pt;")
        lay.addWidget(self.cover_note)
        return page

    def open_cover(self, lesson_id):
        lesson = self.by_id.get(lesson_id)
        if lesson is None:
            return
        self.lesson = lesson
        self.cover_unit.setText(lesson.unit_name or f"{lesson.system_name} · {lesson.region_name}")
        self.cover_title.setText(lesson.title)
        parts = [f"<p style='color:#aab3c0'>{lesson.summary}</p>"]
        if lesson.objectives:
            items = "".join(f"<div style='margin-top:3px'>&bull; {x}</div>" for x in lesson.objectives)
            parts.append(self._panel("#4fc3f7", "By the end you should be able to", items))
        pool = practice_pool(lesson, self.lessons)
        n = len(lesson)
        facts = []
        if n:
            seen = len(self.progress.seen(lesson.id))
            state = "finished ✓" if self.progress.is_done(lesson.id) else (
                f"{seen} of {n} steps read" if seen else "not started")
            facts.append(f"<b>Learn</b> · {n} step{'s' if n != 1 else ''}, about {lesson.minutes} min · {state}")
        rec = self.progress.practice(lesson.id)
        prac = f"<b>Practice</b> · {len(pool)} item{'s' if len(pool) != 1 else ''} to draw from"
        if rec:
            prac += f" · best {rec.get('best')}%, last {rec.get('last')}%"
        facts.append(prac)
        if lesson.practice_from:
            facts.append("Draws on " + ", ".join(self._unit_label(ref) for ref in lesson.practice_from))
        parts.append("<p style='margin-top:10px'>" + "<br>".join(facts) + "</p>")
        links = self._see_also_html()
        if links:
            parts.append(self._panel("#8f9bb0", "Related", f"<div style='margin-top:4px'>{links}</div>"))
        self.cover_body.setHtml("".join(parts))
        self.learn_btn.setVisible(n > 0)
        resume = n and not self.progress.is_done(lesson.id) and self.progress.last_step(lesson.id) > 0
        self.learn_btn.setText("Continue  ›" if resume else "Learn  ›")
        self.practice_btn.setEnabled(bool(pool))
        self.practice_btn.setText("Practice exam  ›" if lesson.practice_from else "Practice  ›")
        self.length_row.setVisible(bool(lesson.practice_from))
        self.cover_note.setText("Practice results feed your review schedule: what you miss comes back sooner."
                                if pool else "This lesson has nothing to practise yet.")
        self.stack.setCurrentIndex(PAGE_COVER)
        self.lessonOpened.emit(lesson)

    def _unit_label(self, ref):
        for heading, key, _group in course_units(self.lessons):
            if ref in (f"{key[0]}{key[1]:02d}", f"{key[0]}{key[1]}"):
                return heading.split(" · ")[0]
        other = self.by_id.get(ref)
        return other.title if other else ref

    def _practice_from_cover(self):
        if self.lesson is None:
            return
        n = self.length.currentData() if self.lesson.practice_from else None
        self.start_practice(self.lesson.id, n)

    def start_practice(self, lesson_id, n=None):
        """Open the Practice dock on a lesson. n: how many items (None = the lesson's default, 0 = all)."""
        lesson = self.by_id.get(lesson_id)
        win = self.main_window()
        if lesson is None or win is None:
            return None
        if self.practice is None:
            from .practice import PracticeController
            self.practice = PracticeController(win, self)
        self.practice.start(lesson, n)
        return self.practice

    def practice_finished(self, lesson_id):
        """Called by Practice mode when a session ends, so the cards and the cover show the new score."""
        if self.stack.currentIndex() == PAGE_COVER and self.lesson is not None and self.lesson.id == lesson_id:
            self.open_cover(lesson_id)
        elif self.stack.currentIndex() == PAGE_LIBRARY:
            self._fill()

    # ================================================================== runner
    def _build_runner(self):
        run = QWidget()
        rl = QVBoxLayout(run)
        rl.setContentsMargins(10, 8, 10, 8)
        rl.setSpacing(6)

        top = QHBoxLayout()
        self.run_back = QPushButton("‹ All lessons")
        self.run_back.setFlat(True)
        self.run_back.clicked.connect(self._runner_back)
        top.addWidget(self.run_back, 0, Qt.AlignLeft)
        top.addStretch(1)
        self.level_tag = QLabel()
        self.level_tag.setStyleSheet("color:#0e1319; background:#7fb2f0; border-radius:4px; padding:1px 7px;"
                                     "font-weight:600;")
        top.addWidget(self.level_tag, 0, Qt.AlignRight)
        rl.addLayout(top)

        self.title = QLabel()
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 2.0)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setWordWrap(True)
        rl.addWidget(self.title)

        self.meta = QLabel()
        self.meta.setStyleSheet("color:#8a94a3; font-size:8.5pt;")
        self.meta.setWordWrap(True)
        rl.addWidget(self.meta)

        self.bar = StepBar()
        self.bar.stepClicked.connect(lambda i: self.go(i, force=True))
        rl.addWidget(self.bar)
        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color:#8fd3ff; font-size:8.5pt;")
        rl.addWidget(self.progress_label)

        self.body = QTextBrowser()
        self.body.document().setDefaultStyleSheet(
            "p { margin-top:0px; margin-bottom:11px; }"
            "h3 { margin:2px 0 7px 0; }"
            "a { color:#8fd3ff; }")
        self.body.setOpenExternalLinks(False)
        self.body.setOpenLinks(False)
        self.body.anchorClicked.connect(self._anchor)
        self.body.viewport().installEventFilter(self)
        rl.addWidget(self.body, 1)

        self.check_box = QWidget()
        cl = QVBoxLayout(self.check_box)
        cl.setContentsMargins(9, 7, 9, 8)
        cl.setSpacing(5)
        self.check_box.setStyleSheet("background:#1e232b; border:1px solid #2b313a; border-radius:6px;")
        self.check_q = QLabel()
        self.check_q.setWordWrap(True)
        self.check_q.setStyleSheet("border:none; color:#e0e6ee;")
        cl.addWidget(self.check_q)
        self.check_a = QLabel()
        self.check_a.setWordWrap(True)
        self.check_a.setStyleSheet("border:none; color:#8fd3ff;")
        self.check_a.hide()
        cl.addWidget(self.check_a)
        self.check_btn = QPushButton("Show answer")
        self.check_btn.clicked.connect(self._reveal)
        cl.addWidget(self.check_btn, 0, Qt.AlignLeft)
        rl.addWidget(self.check_box)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("‹ Back")
        self.next_btn = QPushButton("Next ›")
        self.prev_btn.clicked.connect(lambda: self.go(self.index - 1))
        self.next_btn.clicked.connect(self._next)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        rl.addLayout(nav)

        tools = QHBoxLayout()
        replay = QPushButton("Set the view up again")
        replay.clicked.connect(lambda: self.go(self.index, force=True))
        tools.addWidget(replay)
        quiz = QPushButton("Quiz me")
        quiz.clicked.connect(lambda: self.lesson and self.quizRequested.emit(self.lesson))
        tools.addWidget(quiz)
        self.run_practice = QPushButton("Practice")
        self.run_practice.setToolTip("A short graded session on this lesson")
        self.run_practice.clicked.connect(lambda: self.lesson and self.start_practice(self.lesson.id))
        tools.addWidget(self.run_practice)
        rl.addLayout(tools)
        self.done_btn = QPushButton("Mark as finished")
        self.done_btn.clicked.connect(self._toggle_done)
        rl.addWidget(self.done_btn)

        # reading a lesson should not need the mouse
        for keys, slot in ((("Right", "PgDown"), self._next),
                           (("Left", "PgUp"), lambda: self.go(self.index - 1)),
                           (("Space",), self._reveal)):
            for key in keys:
                sc = QShortcut(QKeySequence(key), run)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                sc.activated.connect(slot)
        return run

    # ------------------------------------------------------------------ opening
    def open_lesson(self, lesson_id):
        lesson = self.by_id.get(lesson_id)
        if lesson is None:
            return
        if not len(lesson):
            self.open_cover(lesson_id)          # a practice exam: nothing to read, only to practise
            return
        self.lesson = lesson
        self.title.setText(lesson.title)
        self.level_tag.setText(lesson.level_name)
        self.level_tag.setStyleSheet(
            "color:#0e1319; border-radius:4px; padding:1px 7px; font-weight:600; background:"
            + {"foundation": "#8fc98f", "core": "#7fb2f0", "advanced": "#e0a06a"}.get(lesson.level, "#7fb2f0"))
        prereq = [self.by_id[p].title for p in lesson.prereq if p in self.by_id]
        meta = f"{lesson.system_name} · {lesson.region_name} · {len(lesson)} steps · about {lesson.minutes} min"
        if prereq:
            meta += "<br>After: " + ", ".join(prereq)
        self.meta.setText(meta)
        self.run_back.setText("‹ " + (lesson.unit_name.split(" · ")[0] if lesson.unit_key else "All lessons"))
        self.run_practice.setVisible(lesson.has_practice())
        self.stack.setCurrentIndex(PAGE_RUNNER)
        self.lessonOpened.emit(lesson)
        start = self.progress.last_step(lesson.id) if not self.progress.is_done(lesson.id) else 0
        self.go(min(start, len(lesson) - 1), force=True)

    def _runner_back(self):
        if self.lesson is not None and self.lesson.unit_key:
            self.open_cover(self.lesson.id)
        else:
            self.close_lesson()

    def close_lesson(self):
        self.lesson = None
        self.stack.setCurrentIndex(PAGE_LIBRARY)
        self._fill()
        self.lessonClosed.emit()

    # ------------------------------------------------------------------ steps
    def go(self, index, force=False):
        if self.lesson is None:
            return
        total = len(self.lesson)
        index = max(0, min(total - 1, index))
        if index == self.index and not force and self.body.toPlainText():
            return
        self.index = index
        step = self.lesson.steps[index]
        self.progress.visit(self.lesson.id, index, total)
        self.bar.set_state(total, index, self.progress.seen(self.lesson.id))
        self.progress_label.setText(f"Step {index + 1} of {total}")
        self._add_diagram(step)
        self.body.setHtml(self._html(step, index, total))
        self.body.verticalScrollBar().setValue(0)
        self._set_check(step.get("check"))
        self.prev_btn.setEnabled(index > 0)
        self.next_btn.setText("Next ›" if index < total - 1 else "Finish")
        self.done_btn.setText("Mark as unfinished" if self.progress.is_done(self.lesson.id)
                              else "Mark as finished")
        self.stepRequested.emit(step)
        self._micro_focus(step)

    def _micro_focus(self, step):
        """A step with "micro_focus" picks those parts out in the microanatomy model the step just opened."""
        names = step.get("micro_focus")
        if not names or not step.get("micro"):
            return
        win = self.main_window()
        view = getattr(win, "micro_tabs", {}).get(step["micro"]) if win is not None else None
        if view is not None and hasattr(view, "focus_parts"):
            missing = view.focus_parts(names)
            if missing:
                win.statusBar().showMessage("Lesson step could not find in the model: " + ", ".join(missing), 4000)

    # ------------------------------------------------------------------ diagrams
    def _diagram_width(self):
        return max(120, self.body.viewport().width() - 2 * int(self.body.document().documentMargin()) - 6)

    def _add_diagram(self, step):
        """Paint the step's diagram at the width the panel has now and hand it to the text as an image."""
        did = step.get("diagram")
        self._diagram_shown = None
        if not did:
            return
        from .diagram import render_image
        width = self._diagram_width()
        img = render_image(did, width, self.devicePixelRatioF(), max_height=460)
        if img is not None:
            self.body.document().addResource(QTextDocument.ImageResource, QUrl(f"diagram:{did}"), img)
            self._diagram_shown = (did, width, img.width() / img.devicePixelRatio(),
                                   img.height() / img.devicePixelRatio())

    def _diagram_html(self, step):
        did = step.get("diagram")
        if not did:
            return ""
        shown = self._diagram_shown
        if not shown or shown[0] != did:
            return f"<p style='color:#e0a06a'>(diagram “{did}” is missing)</p>"
        _d, _w, w, h = shown
        return (f"<p align='center' style='margin:4px 0 12px 0'><a href='diagram:{did}'>"
                f"<img src='diagram:{did}' width='{int(w)}' height='{int(h)}'></a><br>"
                f"<a href='diagram:{did}' style='font-size:8pt; color:#8a94a3'>enlarge</a></p>")

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize and obj is self.body.viewport():
            shown = self._diagram_shown
            if shown and abs(self._diagram_width() - shown[1]) > 8:
                self._diagram_timer.start(120)          # the panel was resized: redraw at the new width
        return super().eventFilter(obj, event)

    def _rerender_diagram(self):
        if self.lesson is None or self.stack.currentIndex() != PAGE_RUNNER:
            return
        step = self.lesson.steps[self.index]
        pos = self.body.verticalScrollBar().value()
        self._add_diagram(step)
        self.body.setHtml(self._html(step, self.index, len(self.lesson)))
        self.body.verticalScrollBar().setValue(pos)

    def _next(self):
        if self.lesson is None:
            return
        if self.index >= len(self.lesson) - 1:
            self.progress.set_done(self.lesson.id, len(self.lesson), True)
            if self.lesson.unit_key and self.lesson.has_practice():
                self.open_cover(self.lesson.id)          # read it: now practise it
            else:
                self.close_lesson()
            return
        self.go(self.index + 1)

    def _toggle_done(self):
        if self.lesson is None:
            return
        now_done = not self.progress.is_done(self.lesson.id)
        self.progress.set_done(self.lesson.id, len(self.lesson), now_done)
        self.done_btn.setText("Mark as unfinished" if now_done else "Mark as finished")
        self.bar.set_state(len(self.lesson), self.index, self.progress.seen(self.lesson.id))

    # ------------------------------------------------------------------ step html
    @staticmethod
    def _panel(colour, heading, body):
        """A tinted box with a coloured edge. Built as a table because Qt only paints block backgrounds reliably
        behind table cells, not behind a div that contains a list."""
        return (f"<table width='100%' cellspacing='0' cellpadding='0' style='margin:10px 0'><tr>"
                f"<td width='3' bgcolor='{colour}'></td>"
                f"<td bgcolor='#1b2129' style='padding:7px 11px'>"
                f"<b>{heading}</b>{body}</td></tr></table>")

    def _html(self, step, index, total):
        lesson = self.lesson
        parts = []
        if index == 0 and lesson.objectives:
            items = "".join(f"<div style='margin-top:3px'>&bull; {x}</div>" for x in lesson.objectives)
            parts.append(self._panel("#4fc3f7", "By the end you should be able to", items))
        heading = step.get("title", "")
        if heading:
            parts.append(f"<h3 style='margin:2px 0 6px 0'>{heading}</h3>")
        parts.append(step.get("text", ""))
        parts.append(self._diagram_html(step))
        if step.get("mnemonic"):
            parts.append(self._panel("#e8b45c", "Mnemonic", f" &middot; {step['mnemonic']}"))
        if step.get("pitfall"):
            parts.append(self._panel("#e0707a", "Easily got wrong", f" &middot; {step['pitfall']}"))
        if step.get("clinical"):
            parts.append(self._panel("#63c08a", "In the clinic", f" &middot; {step['clinical']}"))
        if index == total - 1:
            if lesson.takeaways:
                items = "".join(f"<div style='margin-top:3px'>&bull; {x}</div>" for x in lesson.takeaways)
                parts.append(self._panel("#63c08a", "Worth remembering", items))
            links = self._see_also_html()
            if links:
                parts.append(self._panel("#8f9bb0", "Where next", f"<div style='margin-top:4px'>{links}</div>"))
        return "".join(parts)

    def set_reference_titles(self, **by_scheme):
        """Readable names for the things a lesson can link to: set_reference_titles(rad={id: title}, ...)."""
        self.ref_titles.update(by_scheme)

    def _label(self, scheme, key):
        return self.ref_titles.get(scheme, {}).get(key) or key.replace("_", " ").title()

    def _see_also_html(self):
        out = []
        see = self.lesson.see_also if self.lesson else {}
        for lid in see.get("lessons", []):
            other = self.by_id.get(lid)
            if other:
                out.append(f"<a href='lesson:{lid}'>Lesson &middot; {other.title}</a>")
        for cid in see.get("radiology", []):
            out.append(f"<a href='rad:{cid}'>Radiology &middot; {self._label('rad', cid)}</a>")
        for mid in see.get("micro", []):
            out.append(f"<a href='micro:{mid}'>3D micro &middot; {self._label('micro', mid)}</a>")
        for tid in see.get("histology", []):
            out.append(f"<a href='histo:{tid}'>Histology &middot; {self._label('histo', tid)}</a>")
        return "<br>".join(out)

    def _anchor(self, url):
        scheme, _, payload = url.toString().partition(":")
        if scheme == "lesson":
            self.open_lesson(payload)
        elif scheme == "diagram":
            from .diagram import show_large
            show_large(payload, self)
        else:
            self.linkActivated.emit(scheme, payload)

    # ------------------------------------------------------------------ recall
    def _set_check(self, check):
        if not isinstance(check, dict) or not check.get("q"):
            self.check_box.hide()
            return
        self.check_box.show()
        self.answer_shown = False
        self.check_q.setText(f"<b>Check yourself</b> · {check['q']}")
        self.check_a.setText(check.get("a", ""))
        self.check_a.hide()
        self.check_btn.setText("Show answer")
        self.check_btn.setVisible(bool(check.get("a")))

    def _reveal(self):
        self.answer_shown = not self.answer_shown
        self.check_a.setVisible(self.answer_shown)
        self.check_btn.setText("Hide answer" if self.answer_shown else "Show answer")
