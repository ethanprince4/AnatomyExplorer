"""What you have learned so far: accuracy, the review schedule, and the structures you keep missing."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QVBoxLayout, QWidget)

from .. import srs
from . import theme


class Upcoming(QWidget):
    """A small bar chart of how many structures fall due over the next fortnight."""

    def __init__(self, counts, parent=None):
        super().__init__(parent)
        self.counts = counts
        self.setMinimumHeight(110)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        days = list(range(1, 15))
        top = max([self.counts.get(d, 0) for d in days] + [1])
        if not any(self.counts.get(d, 0) for d in days):
            p.setPen(theme.qc(theme.MUTED))
            p.drawText(0, 0, w, h - 20, Qt.AlignCenter, "Nothing falls due in the next two weeks")
        bw = w / len(days)
        p.setPen(QPen(theme.qc(theme.BORDER_STRONG), 1))
        p.drawLine(0, h - 18, w, h - 18)
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        p.setFont(f)
        for i, d in enumerate(days):
            n = self.counts.get(d, 0)
            bh = (h - 30) * n / top
            x = i * bw + bw * 0.18
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qc(theme.ACCENT, 220 if n else 50))
            p.drawRoundedRect(x, h - 18 - bh, bw * 0.64, max(bh, 1.5), 2, 2)
            if n:
                p.setPen(theme.qc(theme.TEXT_STRONG))
                p.drawText(int(x - bw * 0.18), int(h - 18 - bh - 14), int(bw), 12, Qt.AlignCenter, str(n))
            p.setPen(theme.qc(theme.MUTED))
            p.drawText(int(x - bw * 0.18), h - 16, int(bw), 14, Qt.AlignCenter, str(d))
        p.end()


class LessonBars(QWidget):
    """One bar per body system: how much of that system's lesson library you have finished."""

    def __init__(self, lessons, progress, parent=None):
        super().__init__(parent)
        from ..lessons import group_lessons
        self.rows = []
        for heading, _key, group in group_lessons(lessons, "system"):
            done = sum(1 for x in group if progress.is_done(x.id))
            self.rows.append((heading, done, len(group)))
        self.setMinimumHeight(max(40, 17 * len(self.rows) + 6))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setPointSizeF(8.2)
        p.setFont(f)
        label_w = 132
        for i, (name, done, total) in enumerate(self.rows):
            y = 3 + i * 17
            p.setPen(theme.qc(theme.TEXT_2))
            p.drawText(2, y, label_w - 8, 14, Qt.AlignLeft | Qt.AlignVCenter, name)
            track = QRectF(label_w, y + 4, max(40, self.width() - label_w - 46), 7)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qc(theme.BORDER))
            p.drawRoundedRect(track, 3.5, 3.5)
            if done:
                p.setBrush(theme.qc(theme.SUCCESS))
                p.drawRoundedRect(QRectF(track.x(), track.y(), track.width() * done / total, track.height()),
                                  3.5, 3.5)
            p.setPen(theme.qc(theme.TEXT))
            p.drawText(int(track.right()) + 6, y, 40, 14, Qt.AlignLeft | Qt.AlignVCenter, f"{done}/{total}")
        p.end()


def heading(text):
    """A section heading in the style of the lesson library's group headings."""
    lab = QLabel(text.upper())
    lab.setStyleSheet(theme.overline_css() + " padding-top:12px;")
    return lab


class ProgressDialog(QDialog):
    def __init__(self, stats, lessons=None, lesson_progress=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My progress")
        self.resize(580, 680)
        lay = QVBoxLayout(self)
        s = srs.summary(stats)

        title = QLabel("Study progress")
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 4)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H2, 700))
        lay.addWidget(title)

        row = QHBoxLayout()
        for label, value in (("Structures seen", f"{s['structures']:,}"),
                             ("Questions answered", f"{s['answers']:,}"),
                             ("Overall accuracy", f"{round(s['accuracy'] * 100)}%"),
                             ("Due today", f"{s['due']:,}")):
            box = QWidget()
            box.setObjectName("statTile")
            box.setStyleSheet(f"#statTile {{ background:{theme.RAISED}; border:1px solid {theme.BORDER_SUBTLE};"
                              f" border-radius:{theme.R_LG}px; }}")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 10, 12, 10)
            v = QLabel(value)
            vf = QFont(self.font())
            vf.setPointSizeF(vf.pointSizeF() + 5)
            vf.setBold(True)
            v.setFont(vf)
            v.setStyleSheet(theme.text_css(theme.ACCENT_TEXT, theme.FS_H2, 700))
            k = QLabel(label)
            k.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
            bl.addWidget(v)
            bl.addWidget(k)
            row.addWidget(box)
        lay.addLayout(row)

        lay.addWidget(QLabel(f"<b>{s['learned']:,}</b> structures are on a long interval (three weeks or more); "
                             f"<b>{s['young']:,}</b> are still bedding in."))

        if lessons and lesson_progress is not None:
            done, started, total = lesson_progress.totals(lessons)
            line = f"<b>{done}</b> of <b>{total}</b> finished"
            if started:
                line += f", <b>{started}</b> in progress"
            lay.addWidget(heading("Lessons"))
            lay.addWidget(QLabel(line))
            lay.addWidget(LessonBars(lessons, lesson_progress))
        lay.addWidget(heading("Falling due over the next fortnight · days from today"))
        lay.addWidget(Upcoming(s["upcoming"]))

        lay.addWidget(heading("Structures you miss most"))
        weak = QListWidget()
        for base, miss, seen, rate in srs.weakest(stats, limit=30):
            weak.addItem(QListWidgetItem(f"{base} — missed {miss} of {seen} ({round(rate * 100)}%)"))
        if weak.count() == 0:
            it = QListWidgetItem("Nothing yet – answer a few quiz questions first.")
            it.setFlags(Qt.NoItemFlags)
            it.setForeground(theme.qc(theme.MUTED))
            weak.addItem(it)
        lay.addWidget(weak, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
