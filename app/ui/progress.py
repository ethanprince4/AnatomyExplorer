"""Honest local study progress with a readable schedule and actionable next steps."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import srs
from . import theme
from .flow import FlowLayout


class Upcoming(QWidget):
    """Upcoming review counts with an equivalent accessible text description."""

    def __init__(self, counts, parent=None):
        super().__init__(parent)
        self.counts = counts
        self.setMinimumHeight(140)
        description = "; ".join(f"Day {day}: {counts.get(day, 0)}" for day in range(1, 15))
        self.setAccessibleName("Reviews due over the next fourteen days")
        self.setAccessibleDescription(description)
        self.setToolTip(description)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()
        days = list(range(1, 15))
        top = max([self.counts.get(day, 0) for day in days] + [1])
        if not any(self.counts.get(day, 0) for day in days):
            painter.setPen(theme.qc(theme.MUTED))
            painter.drawText(self.rect().adjusted(4, 4, -4, -24), Qt.AlignCenter | Qt.TextWordWrap,
                             "No items are scheduled for the next two weeks.")
        step = width / len(days)
        baseline = height - 26
        painter.setPen(QPen(theme.qc(theme.BORDER), 1))
        painter.drawLine(0, baseline, width, baseline)
        font = QFont(self.font())
        font.setPointSizeF(theme.FS_SMALL)
        painter.setFont(font)
        for i, day in enumerate(days):
            count = self.counts.get(day, 0)
            bar_height = max(0, baseline - 24) * count / top
            x = i * step + step * 0.22
            if count:
                painter.setPen(Qt.NoPen)
                painter.setBrush(theme.qc(theme.ACCENT))
                painter.drawRoundedRect(QRectF(x, baseline - bar_height, step * 0.56, bar_height), 2, 2)
                painter.setPen(theme.qc(theme.TEXT_STRONG))
                painter.drawText(QRectF(i * step, baseline - bar_height - 22, step, 20), Qt.AlignCenter, str(count))
            painter.setPen(theme.qc(theme.MUTED))
            painter.drawText(QRectF(i * step, baseline + 3, step, 20), Qt.AlignCenter, str(day))
        painter.end()


class LessonBars(QWidget):
    """Native labelled completion bars, one per installed body-system group."""

    def __init__(self, lessons, progress, parent=None):
        super().__init__(parent)
        from ..lessons import group_lessons
        self.rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for name, _key, group in group_lessons(lessons, "system"):
            done, _started, total = progress.totals(group)
            self.rows.append((name, done, total))
            label = QLabel(f"{name} · {done} of {total} finished")
            label.setWordWrap(True)
            label.setStyleSheet(theme.text_css(theme.TEXT_2))
            layout.addWidget(label)
            bar = QProgressBar()
            bar.setRange(0, max(1, total))
            bar.setValue(done)
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            bar.setAccessibleName(name + " lesson completion")
            bar.setAccessibleDescription(f"{done} of {total} finished")
            layout.addWidget(bar)


def heading(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_TITLE, 700) + " padding-top:12px;")
    return label


class ProgressDialog(QDialog):
    def __init__(self, stats, lessons=None, lesson_progress=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My progress")
        self.resize(660, 700)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 16)
        outer.setSpacing(12)
        title = QLabel("Study progress")
        title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H2, 700))
        outer.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 10, 8)
        lay.setSpacing(10)
        summary = srs.summary(stats)
        if not summary["answers"]:
            intro = QLabel("Your study history starts with your first answer. Read a lesson or begin a quiz when you’re ready.")
        else:
            intro = QLabel("Results are saved on this computer. Review intervals grow when you remember an item and shorten when you miss it.")
        intro.setWordWrap(True)
        intro.setStyleSheet(theme.text_css(theme.TEXT_2))
        lay.addWidget(intro)
        measures = QGridLayout()
        measures.setHorizontalSpacing(24)
        measures.setVerticalSpacing(12)
        values = (("Study items seen", f"{summary['structures']:,}"),
                  ("Questions answered", f"{summary['answers']:,}"),
                  ("Overall accuracy", f"{round(summary['accuracy'] * 100)}%" if summary["answers"] else "—"),
                  ("Due today", f"{summary['due']:,}"))
        for index, (label, value) in enumerate(values):
            row = QWidget()
            row.setObjectName("statTile")  # retained inspection contract for persisted-result regressions
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(2)
            amount = QLabel(value)
            amount.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_TITLE, 700))
            row_layout.addWidget(amount)
            name = QLabel(label)
            name.setWordWrap(True)
            name.setStyleSheet(theme.text_css(theme.MUTED))
            row_layout.addWidget(name)
            measures.addWidget(row, index // 2, index % 2)
        lay.addLayout(measures)
        intervals = QLabel(f"{summary['learned']:,} items have intervals of three weeks or more; "
                           f"{summary['young']:,} have shorter intervals.")
        intervals.setWordWrap(True)
        intervals.setStyleSheet(theme.text_css(theme.TEXT_2))
        lay.addWidget(intervals)
        if lessons and lesson_progress is not None:
            done, started, total = lesson_progress.totals(lessons)
            lay.addWidget(heading("Lessons"))
            label = QLabel(f"{done} of {total} finished · {started} in progress")
            label.setWordWrap(True)
            lay.addWidget(label)
            lay.addWidget(LessonBars(lessons, lesson_progress))
        lay.addWidget(heading("Upcoming reviews"))
        caption = QLabel("Days from today. Today’s due items are counted above.")
        caption.setWordWrap(True)
        caption.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        lay.addWidget(caption)
        lay.addWidget(Upcoming(summary["upcoming"]))
        lay.addWidget(heading("Items to revisit"))
        weak = QListWidget()
        weak.setAccessibleName("Study items most often missed")
        weak.setWordWrap(True)
        weak.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for key, missed, seen, rate in srs.weakest(stats, limit=30):
            label = str(stats.get(key, {}).get("label") or key)
            weak.addItem(QListWidgetItem(f"{label}\nMissed {missed} of {seen} answers ({round(rate * 100)}%)"))
        if not weak.count():
            item = QListWidgetItem("No repeated misses yet. This list appears after an item has at least two answers.")
            item.setFlags(Qt.NoItemFlags)
            weak.addItem(item)
        weak.setMinimumHeight(150)
        weak.setMaximumHeight(260)
        lay.addWidget(weak)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        actions = FlowLayout()
        if parent is not None and callable(getattr(parent, "show_lessons", None)):
            button = QPushButton("Open lessons")
            button.clicked.connect(lambda: self._go(parent.show_lessons))
            actions.addWidget(button)
        quiz = getattr(parent, "quiz", None)
        if quiz is not None:
            known = {structure["base"] for structure in quiz.ds.structures}
            count = sum(key in known for key in srs.due_bases(stats))
            review = QPushButton(f"Review atlas ({count})")
            review.setEnabled(count > 0)
            review.setToolTip("Reviews available atlas structures. Other practice items can be repeated from their lesson.")
            review.clicked.connect(lambda: self._go(lambda: (quiz.open(), quiz.start_review())))
            theme.set_variant(review, "primary")
            actions.addWidget(review)
        outer.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _go(self, callback):
        self.accept()
        callback()
