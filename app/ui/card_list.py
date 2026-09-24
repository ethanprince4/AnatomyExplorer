"""A card list: a bold title, a wrapped grey summary underneath it, an optional badge, and section headings.

A plain QListWidget with word wrap turned on runs the title and the summary of every entry together into one
grey wall of text, which is what the Lessons and Radiology browsers used to look like. Here each entry is a
card with its own background, so the eye can find where one ends and the next begins, and the title is clearly
the title.
"""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

ROLE_KIND = Qt.UserRole + 20        # "card" | "header" | "note"
ROLE_TITLE = Qt.UserRole + 21
ROLE_SUMMARY = Qt.UserRole + 22
ROLE_BADGE = Qt.UserRole + 23
ROLE_ACCENT = Qt.UserRole + 24
ROLE_DIM = Qt.UserRole + 25
ROLE_PROGRESS = Qt.UserRole + 26     # 0..1, drawn as a bar along the bottom of the card
ROLE_DONE = Qt.UserRole + 27

CARD_BG = QColor("#1e232b")
CARD_HOVER = QColor("#262d37")
CARD_SEL = QColor("#1f3a4a")
CARD_SEL_EDGE = QColor("#3f87ad")
TITLE = QColor("#e7edf5")
TITLE_DIM = QColor("#9aa5b3")
SUMMARY = QColor("#95a1b1")
HEADING = QColor("#79879a")
RULE = QColor("#2b313a")
BADGE_BG = QColor("#2b3540")
BADGE_FG = QColor("#a3b5c8")
DEFAULT_ACCENT = QColor("#4f8fb8")
TRACK = QColor("#2c3440")
DONE = QColor("#63c08a")

MARGIN_X = 5        # gap between the card and the edge of the list
PAD_L = 11          # inside the card, left of the stripe
STRIPE = 3
TEXT_L = PAD_L + STRIPE + 9
PAD_R = 10
PAD_T = 8
PAD_B = 9
GAP = 3             # between title and summary
MAX_LINES = 3
TITLE_LINES = 2


def _wrap(text, fm, width, max_lines=MAX_LINES):
    """Break text into at most max_lines lines that fit width, eliding the last one if it overflows."""
    lines, cur = [], ""
    for word in (text or "").split():
        trial = f"{cur} {word}".strip()
        if cur and fm.horizontalAdvance(trial) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fm.elidedText(lines[-1] + " …", Qt.ElideRight, width)
    return lines


class CardDelegate(QStyledItemDelegate):
    def __init__(self, view, compact=False):
        super().__init__(view)
        self.view = view
        self.compact = compact

    # ------------------------------------------------------------------ metrics
    def _fonts(self, option):
        base = option.font.pointSizeF()
        title = QFont(option.font)
        title.setBold(True)
        title.setPointSizeF(base + (0.0 if self.compact else 0.3))
        sub = QFont(option.font)
        sub.setPointSizeF(base - 1.0)
        badge = QFont(option.font)
        badge.setBold(True)
        badge.setPointSizeF(base - 2.4)
        return title, sub, badge

    def _width(self):
        return max(120, self.view.viewport().width())

    def sizeHint(self, option, index):
        w = self._width()
        kind = index.data(ROLE_KIND)
        if kind == "header":
            return QSize(w, 30)
        if kind == "note":
            return QSize(w, 34)
        title_f, sub_f, badge_f = self._fonts(option)
        pad_t = PAD_T - (2 if self.compact else 0)
        pad_b = PAD_B - (2 if self.compact else 0)
        fm_t = QFontMetricsF(title_f)
        avail = w - TEXT_L - PAD_R - 2 * MARGIN_X
        badge = index.data(ROLE_BADGE)
        badge_w = (QFontMetricsF(badge_f).horizontalAdvance(badge) + 20) if badge else 0
        n_title = len(_wrap(index.data(ROLE_TITLE) or "", fm_t, avail - badge_w, TITLE_LINES))
        h = pad_t + max(1, n_title) * fm_t.lineSpacing() + pad_b
        summary = index.data(ROLE_SUMMARY)
        if summary:
            fm = QFontMetricsF(sub_f)
            lines = _wrap(summary, fm, w - TEXT_L - PAD_R - 2 * MARGIN_X)
            h += GAP + len(lines) * fm.lineSpacing()
        if index.data(ROLE_DONE) or index.data(ROLE_PROGRESS):
            h += 7                                  # room for the progress bar along the bottom
        return QSize(w, int(round(h)) + 4)

    # ------------------------------------------------------------------ painting
    def paint(self, p: QPainter, option, index):
        kind = index.data(ROLE_KIND) or "card"
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        r = QRectF(option.rect)
        if kind == "header":
            self._paint_header(p, option, r, index.data(Qt.DisplayRole) or "")
        elif kind == "note":
            f = QFont(option.font)
            f.setItalic(True)
            p.setFont(f)
            p.setPen(HEADING)
            p.drawText(r, Qt.AlignCenter, index.data(Qt.DisplayRole) or "")
        else:
            self._paint_card(p, option, r, index)
        p.restore()

    def _paint_header(self, p, option, r, text):
        f = QFont(option.font)
        f.setBold(True)
        f.setPointSizeF(option.font.pointSizeF() - 1.3)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.9)
        p.setFont(f)
        p.setPen(HEADING)
        box = QRectF(r.x() + MARGIN_X + 2, r.y() + 10, r.width(), r.height() - 10)
        p.drawText(box, Qt.AlignLeft | Qt.AlignVCenter, text)
        w = p.fontMetrics().horizontalAdvance(text)
        y = box.y() + box.height() / 2 + 0.5
        x0 = box.x() + w + 9
        x1 = r.right() - MARGIN_X - 4
        if x1 > x0:
            p.setPen(QPen(RULE, 1.0))
            p.drawLine(QPointF(x0, y), QPointF(x1, y))

    def _paint_card(self, p, option, r, index):
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        dim = bool(index.data(ROLE_DIM))
        card = r.adjusted(MARGIN_X, 2, -MARGIN_X, -2)
        p.setPen(Qt.NoPen)
        p.setBrush(CARD_SEL if selected else (CARD_HOVER if hover else CARD_BG))
        p.drawRoundedRect(card, 6, 6)
        if selected:
            p.setPen(QPen(CARD_SEL_EDGE, 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

        accent = index.data(ROLE_ACCENT)
        col = QColor(accent) if accent else DEFAULT_ACCENT
        if dim:
            col = QColor(HEADING)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(card.x() + PAD_L - 5, card.y() + 7, STRIPE, card.height() - 14), 1.5, 1.5)

        title_f, sub_f, badge_f = self._fonts(option)
        tx = card.x() + TEXT_L - MARGIN_X
        ty = card.y() + PAD_T - (2 if self.compact else 0)
        avail = card.right() - PAD_R - tx

        badge = index.data(ROLE_BADGE)
        title_w = avail
        if badge:
            p.setFont(badge_f)
            bw = p.fontMetrics().horizontalAdvance(badge) + 12
            bh = QFontMetricsF(badge_f).height() + 3
            box = QRectF(card.right() - PAD_R - bw, ty + 1, bw, bh)
            p.setPen(Qt.NoPen)
            p.setBrush(BADGE_BG)
            p.drawRoundedRect(box, 4, 4)
            p.setPen(BADGE_FG)
            p.drawText(box, Qt.AlignCenter, badge)
            title_w = avail - bw - 8

        fm_t = QFontMetricsF(title_f)
        p.setFont(title_f)
        p.setPen(TITLE_DIM if dim else TITLE)
        y = ty
        for line in _wrap(index.data(ROLE_TITLE) or "", fm_t, title_w, TITLE_LINES) or [""]:
            p.drawText(QRectF(tx, y, title_w, fm_t.lineSpacing()), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += fm_t.lineSpacing()

        summary = index.data(ROLE_SUMMARY)
        if summary:
            fm_s = QFontMetricsF(sub_f)
            p.setFont(sub_f)
            p.setPen(SUMMARY)
            y += GAP
            for line in _wrap(summary, fm_s, avail):
                p.drawText(QRectF(tx, y, avail, fm_s.lineSpacing()), Qt.AlignLeft | Qt.AlignVCenter, line)
                y += fm_s.lineSpacing()

        done = bool(index.data(ROLE_DONE))
        frac = float(index.data(ROLE_PROGRESS) or 0.0)
        if done or frac > 0:
            bar = QRectF(tx, card.bottom() - 6, avail, 3)
            p.setPen(Qt.NoPen)
            p.setBrush(TRACK)
            p.drawRoundedRect(bar, 1.5, 1.5)
            p.setBrush(DONE if done else col)
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), max(3.0, bar.width() * (1.0 if done else frac)),
                                     bar.height()), 1.5, 1.5)


class CardList(QListWidget):
    """QListWidget that paints its items as cards. Rows are still rows: row() and setCurrentRow() work as usual."""

    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self.setItemDelegate(CardDelegate(self, compact=compact))
        self.setMouseTracking(True)
        self.setUniformItemSizes(False)
        self.setWordWrap(False)
        self.setSpacing(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setStyleSheet("QListWidget::item { background: transparent; }")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.scheduleDelayedItemsLayout()       # a card's height depends on how far its summary wraps

    # ------------------------------------------------------------------ building
    def add_header(self, text):
        it = QListWidgetItem(text.upper())
        it.setFlags(Qt.NoItemFlags)
        it.setData(ROLE_KIND, "header")
        self.addItem(it)
        return it

    def add_note(self, text):
        it = QListWidgetItem(text)
        it.setFlags(Qt.NoItemFlags)
        it.setData(ROLE_KIND, "note")
        self.addItem(it)
        return it

    def add_card(self, title, summary="", badge="", accent=None, data=None, tooltip="", dim=False,
                 progress=0.0, done=False):
        it = QListWidgetItem()
        it.setData(ROLE_KIND, "card")
        it.setData(ROLE_TITLE, title)
        it.setData(ROLE_SUMMARY, summary)
        it.setData(ROLE_BADGE, badge)
        if accent:
            it.setData(ROLE_ACCENT, accent)
        if dim:
            it.setData(ROLE_DIM, True)
        if done:
            it.setData(ROLE_DONE, True)
        elif progress > 0:
            it.setData(ROLE_PROGRESS, float(progress))
        if data is not None:
            it.setData(Qt.UserRole, data)
        if tooltip:
            it.setToolTip(tooltip)
        self.addItem(it)
        return it
