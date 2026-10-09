"""The Lessons tab: a library segmented by body system, region or level, and a runner that teaches one lesson.

The runner is deliberately more than a slideshow. Every lesson opens on what you should be able to do by the
end, every step can ask you a question before you move on, and the last step collects the things worth
remembering. How far you got is kept between runs, so the library shows what you have finished.

Lessons written for the lab course sit at the top under "My lab course", one heading per lab in course order.
Each opens on a cover with two ways in: Learn (the stepper) and Practice (a short graded session built from the
lesson's practice items and step questions - see practice.py).
Lessons written for the lecture exams have a grouping of their own ("Lecture"): one heading per exam chapter,
then each exam's full review.
"""
import html

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QFont, QKeySequence, QPainter, QShortcut, QTextDocument, QTextTable
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..lessons import LessonProgress, course_units, group_lessons, lecture_units, practice_pool
from . import theme
from .card_list import CardList
from .stable_rows import fill_combo
from .flow import FlowLayout

# one colour per body system, so the stripe down the side of a card says what kind of lesson it is
SYSTEM_COLOUR = {
    "skeletal": "#cbb89a", "muscular": "#d4736f", "cardiovascular": "#e0707a", "respiratory": "#7fb2f0",
    "digestive": "#e8b45c", "urinary": "#6cc4b0", "reproductive": "#d78fc0", "endocrine": "#c79ae0",
    "lymphatic": "#8fc98f", "nervous": "#e8d15c", "sensory": "#7fd0e0", "integumentary": "#c9a68a",
}
LEVEL_MARK = {"foundation": "●", "core": "●●", "advanced": "●●●"}
EXAM_LENGTHS = [(20, "20 questions"), (40, "40 questions"), (60, "60 questions"), (0, "Everything")]
PAGE_LIBRARY, PAGE_RUNNER, PAGE_COVER = 0, 1, 2
# reading text in the cover and the runner
LESSON_CSS = (f"p {{ margin-top:0px; margin-bottom:10px; line-height:130%; }}"
              f"h3 {{ margin:2px 0 7px 0; color:{theme.TEXT_STRONG}; font-size:{theme.FS_LEAD + 0.5}pt; }}"
              f"b {{ color:{theme.TEXT_STRONG}; }}"
              f"a {{ color:{theme.ACCENT_TEXT}; }}")


class LessonReading(QTextBrowser):
    """Rounded reading sections using document geometry, including while scrolling."""
    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qc(theme.RAISED))
        layout = self.document().documentLayout()
        for frame in self.document().rootFrame().childFrames():
            if isinstance(frame, QTextTable):
                # Qt's table frame rectangle includes trailing layout space;
                # use the cell text bounds so the background cannot cover the next heading.
                block = frame.firstCursorPosition().block()
                rect = QRectF()
                while block.isValid() and block.position() <= frame.lastPosition():
                    rect = rect.united(layout.blockBoundingRect(block))
                    block = block.next()
                padding = frame.format().cellPadding()
                rect = rect.adjusted(-padding, -padding, padding, padding).translated(
                    -self.horizontalScrollBar().value(), -self.verticalScrollBar().value())
                painter.drawRoundedRect(rect, theme.R_LG, theme.R_LG)
        painter.end()
        super().paintEvent(event)


class StepBar(QWidget):
    """The row of segments under the title: how many steps, which one you are on, which you have seen."""

    stepClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.total = 0
        self.index = 0
        self.seen = set()
        self.setFixedHeight(28)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Lesson steps")
        self.setToolTip("Choose a step. Arrow keys move; Home and End go to the first and last step.")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_state(self, total, index, seen):
        self.total = max(0, int(total))
        self.index = max(0, min(int(index), self.total - 1))
        self.seen = set(seen)
        self.setAccessibleDescription(f"Step {self.index + 1} of {self.total}" if self.total else "No steps")
        self.update()

    def _rects(self):
        if not self.total:
            return []
        gap = min(3.0, self.width() / max(1, self.total * 3))
        w = (self.width() - gap * (self.total - 1)) / self.total
        return [QRectF(i * (w + gap), 10.0, max(w, 0.0), 6.0) for i in range(self.total)]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i, r in enumerate(self._rects()):
            if i == self.index:
                p.setBrush(theme.qc(theme.ACCENT))
            elif i in self.seen:
                p.setBrush(theme.qc(theme.ACCENT_BORDER))
            else:
                p.setBrush(theme.qc(theme.BORDER))
            p.drawRoundedRect(r, 3, 3)
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(theme.qc(theme.ACCENT))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        p.end()

    def keyPressEvent(self, event):
        targets = {Qt.Key_Left: self.index - 1, Qt.Key_Right: self.index + 1,
                   Qt.Key_Home: 0, Qt.Key_End: self.total - 1}
        if event.key() in targets and self.total:
            self.stepClicked.emit(max(0, min(self.total - 1, targets[event.key()])))
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, e):
        for i, r in enumerate(self._rects()):
            if r.adjusted(-1.5, -10, 1.5, 12).contains(e.position()):
                self.stepClicked.emit(i)
                return


class LessonsPanel(QWidget):
    saveFailed = Signal(str)
    saveSucceeded = Signal()
    stepRequested = Signal(object)          # the step dict to apply to the scene
    lessonOpened = Signal(object)           # Lesson
    lessonClosed = Signal()
    quizRequested = Signal(object)          # Lesson - test me on everything it named
    linkActivated = Signal(str, str)        # scheme, payload - "see also" links out of a lesson
    diagramChanged = Signal(str)            # the current step's diagram id ("" for none)

    def __init__(self, lessons, parent=None):
        super().__init__(parent)
        self.lessons = list(lessons)
        self.by_id = {x.id: x for x in lessons}
        self.ref_titles = {}                    # scheme -> {id: readable name}, for the "where next" links
        self.lesson = None
        self.index = 0
        self.progress = LessonProgress(on_save_error=self.saveFailed.emit, on_saved=self.saveSucceeded.emit)
        self.has_course = any(x.unit_key for x in lessons)
        self.has_lecture = any(x.lecture_key for x in lessons)
        self.group_by = "course" if self.has_course else "system"
        self.answer_shown = False
        self._check = None
        self._model_filter = None
        self.practice = None                    # PracticeController, made the first time Practice is pressed
        self._diagram_shown = None
        self.stack = QStackedWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.save_notice = QWidget()
        notice_layout = QVBoxLayout(self.save_notice)
        notice_layout.setContentsMargins(12, 8, 12, 8)
        self.save_status = QLabel()
        self.save_status.setTextFormat(Qt.PlainText)
        self.save_status.setWordWrap(True)
        self.save_status.setStyleSheet(theme.text_css(theme.DANGER))
        notice_layout.addWidget(self.save_status)
        retry = QPushButton("Retry saving progress")
        retry.clicked.connect(self.progress.save)
        notice_layout.addWidget(retry)
        self.save_notice.hide()
        self.saveFailed.connect(self._save_failed)
        self.saveSucceeded.connect(self.save_notice.hide)
        outer.addWidget(self.save_notice)
        outer.addWidget(self.stack)
        self.stack.addWidget(self._build_library())
        self.stack.addWidget(self._build_runner())
        self.stack.addWidget(self._build_cover())
        self._diagram_timer = QTimer(self)
        self._diagram_timer.setSingleShot(True)
        self._diagram_timer.timeout.connect(self._rerender_diagram)
        self._fill()

    def set_lessons(self, lessons):
        """Replace a preview library without leaving a stale lesson/session visible."""
        if self.practice is not None and self.practice.active:
            self.practice.stop()
        self.lessons = list(lessons)
        self.by_id = {lesson.id: lesson for lesson in self.lessons}
        self.has_course = any(lesson.unit_key for lesson in self.lessons)
        self.has_lecture = any(lesson.lecture_key for lesson in self.lessons)
        self._model_filter = None
        self.scope_notice.hide()
        self.filter.clear()
        self.status_filter.setCurrentIndex(0)
        self.close_lesson()
        for button in self.group_buttons.buttons():
            if button.property("group_key") == "course":
                button.setVisible(self.has_course)
            elif button.property("group_key") == "lecture":
                button.setVisible(self.has_lecture)
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
    def _save_failed(self, message):
        self.save_status.setText("Progress is kept for this session, but could not be saved on this computer. "
                                 "Check available storage and retry. " + str(message))
        self.save_notice.show()

    def _build_library(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(10)
        title = QLabel("Learn & recall")
        title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H2, 700))
        lay.addWidget(title)
        intro = QLabel("Choose a lesson, follow its anatomy, then practise what it teaches.")
        intro.setWordWrap(True)
        intro.setStyleSheet(theme.text_css(theme.TEXT_2))
        lay.addWidget(intro)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Search lessons, objectives or topics")
        self.filter.setAccessibleName("Search lessons")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._fill)
        self.filter.returnPressed.connect(self._open_selected)
        self.filter.installEventFilter(self)
        lay.addWidget(self.filter)
        self.scope_notice = QWidget()
        scope = QVBoxLayout(self.scope_notice)
        scope.setContentsMargins(0, 0, 0, 0)
        self.scope_label = QLabel()
        self.scope_label.setWordWrap(True)
        self.scope_label.setStyleSheet(theme.text_css(theme.ACCENT_TEXT))
        scope.addWidget(self.scope_label)
        clear_scope = QPushButton("Show all lessons")
        clear_scope.clicked.connect(self.clear_model_filter)
        scope.addWidget(clear_scope, 0, Qt.AlignLeft)
        self.scope_notice.hide()
        lay.addWidget(self.scope_notice)
        row = FlowLayout(spacing=6)
        self.group_buttons = QButtonGroup(self)
        for key, label in (("course", "Lab"), ("lecture", "Lecture"), ("system", "System"), ("region", "Region"),
                           ("level", "Level")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(key == self.group_by)
            button.setProperty("group_key", key)
            button.setProperty("chip", True)
            button.setAccessibleName("Group lessons by " + label.lower())
            button.clicked.connect(lambda _c=False, k=key: self._set_group(k))
            if key == "course":
                button.setVisible(self.has_course)
            elif key == "lecture":
                button.setVisible(self.has_lecture)
            self.group_buttons.addButton(button)
            row.addWidget(button)
        lay.addLayout(row)
        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName("Lesson progress filter")
        for label, key in (("All progress", "all"), ("In progress", "started"),
                           ("Not started", "new"), ("Finished", "done"), ("With practice", "practice")):
            self.status_filter.addItem(label, key)
        self.status_filter.currentIndexChanged.connect(self._fill)
        lay.addWidget(self.status_filter)
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.stats.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        lay.addWidget(self.stats)
        self.list = CardList(collapsible=True)
        self.list.reserve(2 * len(self.lessons) + 16)   # every lesson plus a header each, at most, plus notes
        self.list.setAccessibleName("Lesson library")
        self.list.itemActivated.connect(self._open_item)
        self.list.itemClicked.connect(self._open_item)
        lay.addWidget(self.list, 1)
        actions = FlowLayout(spacing=6)
        for label, method in (("My progress", "show_progress"), ("My notes", "show_all_notes")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, name=method: self._window_action(name))
            actions.addWidget(button)
        self.resume_button = QPushButton("Continue Where You Last Left Off")
        self.resume_button.clicked.connect(lambda: self._resume_id and self.open_lesson(self._resume_id))
        actions.addWidget(self.resume_button)
        lay.addLayout(actions)
        return page

    def _window_action(self, method):
        window = self.main_window()
        callback = getattr(window, method, None)
        if callback is not None:
            callback()

    def _open_selected(self):
        item = self.list.currentItem()
        if item is None or not item.data(Qt.UserRole):
            item = next((self.list.item(i) for i in range(self.list.count())
                         if self.list.item(i).data(Qt.UserRole)), None)
        if item is not None:
            self._open_item(item)

    @staticmethod
    def _model_ids(lesson):
        """Only authored associations; matching a title is not a relationship."""
        return {step.get("micro") for step in lesson.steps if step.get("micro")} | set(lesson.see_also.get("micro", []))

    def lessons_for_model(self, model_id):
        return [lesson for lesson in self.lessons if model_id in self._model_ids(lesson)]

    def show_model_lessons(self, model_id):
        self.close_lesson()
        self._model_filter = model_id
        self.filter.clear()
        self.status_filter.setCurrentIndex(0)
        self.scope_label.setText("Lessons linked by the existing content to " + self._label("micro", model_id))
        self.scope_notice.show()
        # The Lab and Lecture groupings only list course lessons; a model's linked lessons may be outside both.
        linked = self.lessons_for_model(model_id)
        in_course = lambda x: x.unit_key and (x.unit_key[0] == "lab" and 1 <= x.unit_key[1] <= 9
                                              or x.unit_key[0] == "exam" and x.unit_key[1] in (1, 2))
        hidden = (self.group_by == "course" and any(not in_course(x) for x in linked)
                  or self.group_by == "lecture" and any(not x.lecture_key for x in linked))
        if hidden:
            self._set_group("system")
        else:
            self._fill()
        self.filter.setFocus(Qt.OtherFocusReason)

    def clear_model_filter(self):
        self._model_filter = None
        self.scope_notice.hide()
        self._fill()

    def show_course(self):
        """The library, grouped as the lab course (for a "Lab course" entry point elsewhere in the app)."""
        if self.stack.currentIndex() != PAGE_LIBRARY:
            self.close_lesson()
        self.clear_model_filter()
        self.filter.clear()
        self.status_filter.setCurrentIndex(0)
        self._set_group("course" if self.has_course else "system")

    def show_lecture(self):
        """The library, grouped as the lecture exams (for a "Lecture exams" entry point elsewhere in the app)."""
        if self.stack.currentIndex() != PAGE_LIBRARY:
            self.close_lesson()
        self.clear_model_filter()
        self.filter.clear()
        self.status_filter.setCurrentIndex(0)
        self._set_group("lecture" if self.has_lecture else "system")

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
        return all(word in hay for word in needle.split())

    def _fill(self, *_):
        needle = self.filter.text().strip().lower()
        state = self.status_filter.currentData()
        shown = []
        for lesson in self.lessons:
            if not self._matches(lesson, needle):
                continue
            if self._model_filter and self._model_filter not in self._model_ids(lesson):
                continue
            done = self._finished(lesson)
            started = bool(self.progress.seen(lesson.id)) and not done
            if state == "done" and not done or state == "started" and not started:
                continue
            if state == "new" and (done or started) or state == "practice" and not lesson.has_practice():
                continue
            if self.group_by == "course" and not (lesson.unit_key and
                    (lesson.unit_key[0] == "lab" and 1 <= lesson.unit_key[1] <= 9 or
                     lesson.unit_key[0] == "exam" and lesson.unit_key[1] in (1, 2))):
                continue
            if self.group_by == "lecture" and not lesson.lecture_key:
                continue
            shown.append(lesson)
        selected = self.list.currentItem()
        selected_id = selected.data(Qt.UserRole) if selected is not None else None
        self.list.clear()
        self.list.expand_all = bool(self._model_filter)
        done, started, total = self.progress.totals(self.lessons)
        self.stats.setText(f"{len(shown)} of {total} lessons · {done} finished · {started} in progress")
        resume = next(iter(self.progress.in_progress(self.lessons)), None)
        self.resume_button.setVisible(resume is not None)
        self.resume_button.setToolTip(f"Resume {resume.title}" if resume else "")
        self._resume_id = resume.id if resume else None
        if self.group_by == "course":
            self._fill_course(shown)
        elif self.group_by == "lecture":
            self._fill_lecture(shown)
        else:
            for heading, _key, group in group_lessons(shown, self.group_by):
                self.list.add_header(f"{heading} ({len(group)})")
                for lesson in group:
                    self._add_card(lesson)
        if self.list.count() == 0:
            self.list.add_note("No lessons match these filters. Clear the search or choose All progress."
                               if self.lessons else "No lesson content is installed.")
        for i in range(self.list.count()):
            if selected_id and self.list.item(i).data(Qt.UserRole) == selected_id:
                self.list.setCurrentRow(i)
                break

    def _fill_course(self, shown):
        """Only labs and practicals, in teaching order."""
        course = [x for x in shown if x.unit_key and (x.unit_key[0] == "lab" and 1 <= x.unit_key[1] <= 9
                                                      or x.unit_key[0] == "exam" and x.unit_key[1] in (1, 2))]
        # Header counts describe the whole unit, not just the lessons the current filters let through.
        everything = [x for x in self.lessons if x.unit_key and (x.unit_key[0] == "lab" and 1 <= x.unit_key[1] <= 9
                                                                or x.unit_key[0] == "exam" and x.unit_key[1] in (1, 2))]
        totals = {key: (sum(1 for x in members if self._finished(x)), len(members))
                  for _heading, key, members in course_units(everything)}
        for heading, unit_key, group in course_units(course):
            done, size = totals.get(unit_key, (sum(1 for x in group if self._finished(x)), len(group)))
            _short, _sep, topic = heading.partition(" · ")
            short = f"Lab {unit_key[1]}" if unit_key[0] == "lab" else f"Practical {unit_key[1]}"
            self.list.add_header(f"{short} · {done}/{size} finished" + (f"  ·  {topic}" if topic else ""),
                                 key=f"lab-{unit_key[0]}-{unit_key[1]}")
            for lesson in group:
                self._add_card(lesson)
    def _fill_lecture(self, shown):
        """Exam > chapter > lessons, with reviews after chapters."""
        current_exam = None
        totals = {key: (sum(1 for x in members if self._finished(x)), len(members))
                  for _heading, key, members in lecture_units([x for x in self.lessons if x.lecture_key])}
        for heading, key, group in lecture_units([x for x in shown if x.lecture_key]):
            exam_number, chapter = key
            if exam_number != current_exam:
                self.list.add_header(f"Exam {exam_number}", key=f"lecture-exam-{exam_number}")
                current_exam = exam_number
            done, size = totals.get(key, (sum(1 for x in group if self._finished(x)), len(group)))
            label = heading.partition(" · ")[2] or heading
            self.list.add_header(f"{label} · {done}/{size} finished", level=1,
                                 key=f"lecture-{exam_number}-{chapter}")
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
        badge = f"{n} step{'s' if n != 1 else ''} · {lesson.minutes} min" if n else "Practice"
        tip = (f"{lesson.system_name} · {lesson.region_name} · {lesson.level_name} · about {lesson.minutes} min"
               + ("\nFinished" if done else ""))
        title = lesson.title
        summary = prefix + lesson.summary
        if lesson.unit_key or lesson.lecture_key:
            title = lesson.title
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
        if lid in self.by_id:
            self.open_cover(lid)

    # ================================================================== cover: Learn or Practice
    def _build_cover(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        back = QPushButton("‹ All lessons")
        back.setFlat(True)
        back.clicked.connect(self.close_lesson)
        lay.addWidget(back, 0, Qt.AlignLeft)
        self.cover_unit = QLabel()
        self.cover_unit.setWordWrap(True)
        self.cover_unit.setStyleSheet(theme.text_css(theme.ACCENT_TEXT, theme.FS_SMALL, 700))
        lay.addWidget(self.cover_unit)
        self.cover_title = QLabel()
        self.cover_title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H2, 700))
        self.cover_title.setWordWrap(True)
        lay.addWidget(self.cover_title)
        self.cover_body = LessonReading()
        self.cover_body.document().setDefaultStyleSheet(LESSON_CSS)
        self.cover_body.setAccessibleName("Lesson overview")
        self.cover_body.setOpenExternalLinks(False)
        self.cover_body.setOpenLinks(False)
        self.cover_body.anchorClicked.connect(self._anchor)
        lay.addWidget(self.cover_body, 1)

        big = f"QPushButton {{ font-size:{theme.FS_LEAD}pt; font-weight:700; padding:10px 8px; }}"
        self.learn_btn = QPushButton("Learn  ›")
        self.learn_btn.setStyleSheet(big)
        theme.set_variant(self.learn_btn, "primary")
        self.learn_btn.setToolTip("Step through the lesson: each step sets the 3D view up for you")
        self.learn_btn.clicked.connect(lambda: self.lesson and self.open_lesson(self.lesson.id))
        self.practice_btn = QPushButton("Practice  ›")
        self.practice_btn.setStyleSheet(big)
        theme.set_variant(self.practice_btn, "secondary")
        self.practice_btn.setToolTip("A short graded session: find, name, pick and recall what this lesson covers")
        self.practice_btn.clicked.connect(self._practice_from_cover)
        row = QHBoxLayout()
        row.addWidget(self.learn_btn, 1)
        row.addWidget(self.practice_btn, 1)
        # Primary actions stay immediately below the title. The overview itself
        # scrolls, so starting/resuming does not depend on reaching its bottom.
        lay.insertLayout(3, row)
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
        self.cover_note.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        lay.addWidget(self.cover_note)
        return page

    def open_cover(self, lesson_id):
        lesson = self.by_id.get(lesson_id)
        if lesson is None:
            return
        self.lesson = lesson
        self.cover_unit.setText(lesson.unit_name or f"{lesson.system_name} · {lesson.region_name}")
        self.cover_title.setTextFormat(Qt.PlainText)
        self.cover_title.setText(lesson.title)
        parts = [f"<p style='color:{theme.TEXT_2}'>{lesson.summary}</p>"]
        if lesson.objectives:
            items = "".join(f"<div style='margin-top:3px'>&bull; {x}</div>" for x in lesson.objectives)
            parts.append(self._panel(theme.TOPIC["objectives"], "By the end you should be able to", items))
        pool = practice_pool(lesson, self.lessons)
        n = len(lesson)
        facts = []
        if n:
            seen = sum(i < n for i in self.progress.seen(lesson.id))
            state = "finished" if self.progress.is_done(lesson.id) else (
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
            parts.append(self._panel(theme.TOPIC["related"], "Related", f"<div style='margin-top:4px'>{links}</div>"))
        self.cover_body.setHtml("".join(parts))
        self.cover_body.verticalScrollBar().setValue(0)
        self.diagramChanged.emit("")
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
        (self.learn_btn if n else self.practice_btn).setFocus(Qt.OtherFocusReason)

    def _unit_label(self, ref):
        for heading, key, _group in course_units(self.lessons):
            if ref in (f"{key[0]}{key[1]:02d}", f"{key[0]}{key[1]}"):
                return heading.split(" · ")[0]
        for heading, key, _group in lecture_units(self.lessons):
            if key[1] and ref.lower() in (f"ch{key[1]}", f"ch{key[1]:02d}"):
                return " · ".join(heading.split(" · ")[1:])
        other = self.by_id.get(ref)
        return other.title if other is not None else ref

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
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(6)

        top = QHBoxLayout()
        self.run_back = QPushButton("‹ All lessons")
        self.run_back.setFlat(True)
        self.run_back.clicked.connect(self._runner_back)
        top.addWidget(self.run_back, 0, Qt.AlignLeft)
        top.addStretch(1)
        self.level_tag = QLabel()
        self.level_tag.setStyleSheet(theme.tag_css(theme.ACCENT_SOFT, theme.ACCENT_TEXT))
        top.addWidget(self.level_tag, 0, Qt.AlignRight | Qt.AlignVCenter)
        rl.addLayout(top)

        self.title = QLabel()
        f = QFont(self.font())
        f.setPointSizeF(theme.FS_TITLE)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_TITLE, 700))
        self.title.setWordWrap(True)
        rl.addWidget(self.title)

        self.meta = QLabel()
        self.meta.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        self.meta.setWordWrap(True)
        rl.addWidget(self.meta)

        self.bar = StepBar()
        self.bar.stepClicked.connect(lambda i: self.go(i, force=True))
        rl.addWidget(self.bar)
        self.step_picker = QComboBox()
        self.steps_shown = 0
        self.step_picker.setAccessibleName("Jump to lesson step")
        self.step_picker.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.step_picker.setMinimumContentsLength(14)
        self.step_picker.activated.connect(lambda i: self.go(i, force=True))
        rl.addWidget(self.step_picker)
        self.progress_label = QLabel()
        self.progress_label.setStyleSheet(theme.text_css(theme.ACCENT_TEXT, theme.FS_SMALL, 600))
        rl.addWidget(self.progress_label)

        self.body = LessonReading()
        self.body.setAccessibleName("Lesson reading and recall")
        self.body.document().setDefaultStyleSheet(LESSON_CSS)
        self.body.setOpenExternalLinks(False)
        self.body.setOpenLinks(False)
        self.body.anchorClicked.connect(self._anchor)
        self.body.viewport().installEventFilter(self)
        rl.addWidget(self.body, 1)

        # Recall belongs to the same reading scroll. The reveal action stays reachable.
        self.check_box = QWidget()
        cl = QHBoxLayout(self.check_box)
        cl.setContentsMargins(0, 0, 0, 0)
        self.check_q = QLabel(self.check_box)
        self.check_a = QLabel(self.check_box)
        self.check_q.hide()
        self.check_a.hide()
        self.check_btn = QPushButton("Show answer")
        self.check_btn.setAccessibleName("Show recall answer")
        self.check_btn.clicked.connect(self._reveal)
        theme.set_variant(self.check_btn, "primary")
        self.check_jump = QPushButton("Recall question")
        self.check_jump.clicked.connect(lambda: self.body.scrollToAnchor("recall"))
        cl.addWidget(self.check_jump)
        cl.addWidget(self.check_btn)
        rl.addWidget(self.check_box)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("‹ Back")
        self.next_btn = QPushButton("Next ›")
        theme.set_variant(self.next_btn, "primary")
        self.prev_btn.clicked.connect(lambda: self.go(self.index - 1))
        self.next_btn.clicked.connect(self._next)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        rl.addLayout(nav)

        self.tools_toggle = QPushButton("Lesson tools")
        self.tools_toggle.setCheckable(True)
        self.tools_toggle.setToolTip("Show replay, quiz, practice and completion controls")
        rl.addWidget(self.tools_toggle)
        self.lesson_tools = QWidget()
        extra = QVBoxLayout(self.lesson_tools)
        extra.setContentsMargins(0, 0, 0, 0)
        tools = FlowLayout()
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
        extra.addLayout(tools)
        self.done_btn = QPushButton("Mark as finished")
        self.done_btn.clicked.connect(self._toggle_done)
        extra.addWidget(self.done_btn)
        rl.addWidget(self.lesson_tools)
        self.lesson_tools.hide()
        self.tools_toggle.toggled.connect(self.lesson_tools.setVisible)

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
        self.title.setTextFormat(Qt.PlainText)
        self.title.setText(lesson.title)
        self.level_tag.setText(lesson.level_name)
        self.level_tag.setStyleSheet(theme.tag_css(theme.ACCENT_SOFT, theme.ACCENT_TEXT))
        prereq = [self.by_id[p].title for p in lesson.prereq if p in self.by_id]
        meta = f"{lesson.system_name} · {lesson.region_name} · {len(lesson)} steps · about {lesson.minutes} min"
        if prereq:
            meta += "<br>After: " + ", ".join(prereq)
        self.meta.setText(meta)
        self.run_back.setText("‹ Lesson overview")
        self.run_practice.setVisible(lesson.has_practice())
        self.step_picker.blockSignals(True)
        # rewritten in place, never cleared: lessons open from clicks with the picker on screen (see stable_rows)
        self.steps_shown = fill_combo(self.step_picker, [(f"{i + 1}. {step.get('title') or 'Step ' + str(i + 1)}", i)
                                                         for i, step in enumerate(lesson.steps)])
        self.step_picker.blockSignals(False)
        self.tools_toggle.setChecked(False)
        self.stack.setCurrentIndex(PAGE_RUNNER)
        self.lessonOpened.emit(lesson)
        start = self.progress.last_step(lesson.id) if not self.progress.is_done(lesson.id) else 0
        self.go(min(start, len(lesson) - 1), force=True)
        self.body.setFocus(Qt.OtherFocusReason)

    def _runner_back(self):
        if self.lesson is not None:
            self.open_cover(self.lesson.id)
        else:
            self.close_lesson()

    def close_lesson(self):
        self.lesson = None
        self.stack.setCurrentIndex(PAGE_LIBRARY)
        self._fill()
        self.diagramChanged.emit("")
        self.lessonClosed.emit()

    # ------------------------------------------------------------------ steps
    def go(self, index, force=False):
        if self.lesson is None:
            return
        total = len(self.lesson)
        if not total:
            return
        index = max(0, min(total - 1, index))
        if index == self.index and not force and self.body.toPlainText():
            return
        self.index = index
        step = self.lesson.steps[index]
        self.progress.visit(self.lesson.id, index, total)
        self.bar.set_state(total, index, self.progress.seen(self.lesson.id))
        self.progress_label.setText(f"Step {index + 1} of {total}")
        self.step_picker.setCurrentIndex(index)
        self._add_diagram(step)
        self._set_check(step.get("check"))
        self.body.setHtml(self._html(step, index, total))
        self.body.verticalScrollBar().setValue(0)
        self.prev_btn.setEnabled(index > 0)
        next_lesson = self._next_in_sequence() if index == total - 1 else None
        self.next_btn.setText("Next ›" if index < total - 1 else "Finish + Next" if next_lesson else "Finish")
        self.next_btn.setToolTip("Finish this lesson and open " + next_lesson.title if next_lesson else "")
        self.done_btn.setText("Mark as unfinished" if self.progress.is_done(self.lesson.id)
                              else "Mark as finished")
        self.stepRequested.emit(step)
        self._micro_focus(step)

    def _micro_focus(self, step):
        """A step with "micro_focus" picks those parts out in the microanatomy model the step just opened."""
        names = step.get("micro_focus")
        if not step.get("micro"):
            return
        win = self.main_window()
        if win is None:
            return
        lesson, index = self.lesson, self.index
        def ready(view):
            if (view is None or self.lesson is not lesson or self.index != index
                    or self.lesson.steps[self.index] is not step):
                return
            missing = view.show_lesson_parts(names, view_name=step.get("micro_view"))
            if missing:
                win.statusBar().showMessage("Lesson step could not find in the model: " + ", ".join(missing), 4000)
        win.when_model_ready(step["micro"], ready)

    # ------------------------------------------------------------------ diagrams
    def _diagram_width(self):
        return max(120, self.body.viewport().width() - 2 * int(self.body.document().documentMargin()) - 6)

    def _add_diagram(self, step):
        """Paint the step's diagram at the width the panel has now and hand it to the text as an image."""
        did = step.get("diagram")
        self._diagram_shown = None
        self.diagramChanged.emit(did or "")
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
        if step.get("lesson_view") == "diagram":
            return ""
        did = step.get("diagram")
        if not did:
            return ""
        shown = self._diagram_shown
        if not shown or shown[0] != did:
            return f"<p style='color:{theme.WARNING}'>(diagram “{did}” is missing)</p>"
        _d, _w, w, h = shown
        return (f"<p align='center' style='margin-top:4px; margin-bottom:0px; line-height:100%'>"
                f"<a href='diagram:{did}'><img src='diagram:{did}' width='{int(w)}' height='{int(h)}'></a></p>"
                f"<table width='100%' cellspacing='0' cellpadding='10'><tr><td align='center'>"
                f"<a href='diagram:{did}' style='font-size:{theme.FS_BODY + 2}pt; font-weight:700; "
                f"color:{theme.ACCENT_TEXT}; text-decoration:none'>Open full-size diagram</a>"
                f"</td></tr></table>")

    def eventFilter(self, obj, event):
        if obj is self.filter and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Down:
            first = next((i for i in range(self.list.count()) if self.list.item(i).data(Qt.UserRole)), None)
            if first is not None:
                self.list.setCurrentRow(first)
                self.list.setFocus(Qt.TabFocusReason)
                return True
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

    def _next_in_sequence(self):
        """Follow authored lab/lecture order, independent of search and progress filters."""
        if self.lesson is None:
            return None
        if self.lesson.lecture_key:
            exam = self.lesson.lecture_key[0]
            units = lecture_units([lesson for lesson in self.lessons
                                   if lesson.lecture_key and lesson.lecture_key[0] == exam])
        elif self.lesson.unit_key:
            units = course_units([lesson for lesson in self.lessons if lesson.unit_key and
                                  (lesson.unit_key[0] == "lab" and 1 <= lesson.unit_key[1] <= 9 or
                                   lesson.unit_key[0] == "exam" and lesson.unit_key[1] in (1, 2))])
        else:
            return None
        sequence = [lesson for _heading, _key, group in units for lesson in group]
        for index, lesson in enumerate(sequence[:-1]):
            if lesson.id == self.lesson.id:
                return sequence[index + 1]
        return None

    def _next(self):
        if self.lesson is None:
            return
        if self.index >= len(self.lesson) - 1:
            next_lesson = self._next_in_sequence()
            self.progress.set_done(self.lesson.id, len(self.lesson), True)
            if next_lesson is not None:
                self.open_cover(next_lesson.id)
            elif self.lesson.has_practice():
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
        """Keep section text selectable; LessonReading paints its rounded background."""
        return (f"<table width='100%' cellspacing='0' cellpadding='12' style='margin:10px 0'><tr>"
                f"<td>"
                f"<b style='color:{theme.TEXT_STRONG}'>{heading}</b>{body}</td></tr></table>")

    def _html(self, step, index, total):
        lesson = self.lesson
        parts = []
        if index == 0 and lesson.objectives:
            items = "".join(f"<div style='margin-top:3px'>&bull; {x}</div>" for x in lesson.objectives)
            parts.append(self._panel(theme.TOPIC["objectives"], "By the end you should be able to", items))
        heading = step.get("title", "")
        if heading:
            parts.append(f"<h3 style='margin:2px 0 6px 0'>{heading}</h3>")
        parts.append(step.get("text", ""))
        parts.append(self._diagram_html(step))
        if step.get("micro"):
            mid = step["micro"]
            parts.append(self._panel(theme.ACCENT_TEXT, "This step’s model",
                                     "<p>" + self._reference_link("micro", mid, "3D model") + "</p>"))
        if step.get("mnemonic"):
            parts.append(self._panel(theme.TOPIC["mnemonic"], "Mnemonic", f" &middot; {step['mnemonic']}"))
        if step.get("pitfall"):
            parts.append(self._panel(theme.TOPIC["pitfall"], "Easily got wrong", f" &middot; {step['pitfall']}"))
        if step.get("clinical"):
            parts.append(self._panel(theme.TOPIC["clinical"], "In the clinic", f" &middot; {step['clinical']}"))
        if index == total - 1:
            if lesson.takeaways:
                items = "".join(f"<div style='margin-top:3px'>&bull; {x}</div>" for x in lesson.takeaways)
                parts.append(self._panel(theme.TOPIC["takeaways"], "Worth remembering", items))
            links = self._see_also_html()
            if links:
                parts.append(self._panel(theme.TOPIC["related"], "Where next", f"<div style='margin-top:4px'>{links}</div>"))
        if self._check:
            question = self._check.get("q", "")
            answer = self._check.get("a", "")
            recall = f"<p style='margin-top:5px; margin-bottom:0px; line-height:100%'><a name='recall'></a>{question}</p>"
            if self.answer_shown:
                recall += f"<p style='margin-top:8px; margin-bottom:0px; line-height:100%'>{answer}</p>"
            parts.append(self._panel(theme.ACCENT_TEXT, "Recall before you reveal", recall))
        return "".join(parts)

    def set_reference_titles(self, **by_scheme):
        """Readable names for the things a lesson can link to: set_reference_titles(rad={id: title}, ...)."""
        self.ref_titles.update(by_scheme)

    def _label(self, scheme, key):
        return self.ref_titles.get(scheme, {}).get(key) or key.replace("_", " ").title()

    def _reference_link(self, scheme, key, kind):
        label = html.escape(self._label(scheme, key))
        if key not in self.ref_titles.get(scheme, {}):
            return f"{kind} · {label} <span style='color:{theme.MUTED}'>(not available in this library)</span>"
        url = html.escape(QUrl(f"{scheme}:{key}").toString(), quote=True)
        return f"<a href='{url}'>{kind} · {label}</a>"

    def _see_also_html(self):
        out = []
        see = self.lesson.see_also if self.lesson is not None else {}
        for lid in see.get("lessons", []):
            other = self.by_id.get(lid)
            if other is not None:
                out.append(f"<a href='lesson:{html.escape(lid, quote=True)}'>Lesson · {html.escape(other.title)}</a>")
        for field, scheme, label in (("radiology", "rad", "Radiology"), ("micro", "micro", "3D model"),
                                      ("histology", "histo", "Histology")):
            for key in see.get(field, []):
                out.append(self._reference_link(scheme, key, label))
        return "<br>".join(out)

    def _anchor(self, url):
        scheme, _, payload = url.toString().partition(":")
        payload = QUrl.fromPercentEncoding(payload.encode("utf-8"))
        if scheme == "lesson" and payload in self.by_id:
            self.open_cover(payload)
        elif scheme == "diagram":
            from .diagram import show_large
            show_large(payload, self)
        elif scheme in ("micro", "histo", "rad") and payload in self.ref_titles.get(scheme, {}):
            self.linkActivated.emit(scheme, payload)

    # ------------------------------------------------------------------ recall
    def _set_check(self, check):
        self._check = check if isinstance(check, dict) and check.get("q") else None
        self.answer_shown = False
        self.check_q.setText(check.get("q", "") if self._check else "")
        self.check_a.setText(check.get("a", "") if self._check else "")
        self.check_box.setVisible(bool(self._check and check.get("a")))
        self.check_btn.setText("Show answer")
        self.check_btn.setAccessibleName("Show recall answer")

    def _reveal(self):
        if self.lesson is None or not self._check or not self._check.get("a"):
            return
        self.answer_shown = not self.answer_shown
        self.check_btn.setText("Hide answer" if self.answer_shown else "Show answer")
        self.check_btn.setAccessibleName("Hide recall answer" if self.answer_shown else "Show recall answer")
        position = self.body.verticalScrollBar().value()
        self.body.setHtml(self._html(self.lesson.steps[self.index], self.index, len(self.lesson)))
        self.body.verticalScrollBar().setValue(position)
        if self.answer_shown:
            self.body.scrollToAnchor("recall")
