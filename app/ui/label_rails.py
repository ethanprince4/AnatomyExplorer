"""The checkpoint 3 numbered circles and caption rails, shared by native 3D views."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QTextLayout, QTextOption

from . import theme

LABEL_GOLD = "#d4b47e"
LABEL_GOLD_INK = "#231b0d"


def reserve_caption_space(viewport):
    """Fit the visible specimen between the two caption walls when opening labels."""
    bounds = getattr(viewport, '_label_specimen_bounds', None)
    if bounds is None:
        return
    if viewport.camera.animating:
        return
    width, height = viewport.width(), viewport.height()
    if min(width, height) <= 0:
        return
    left, top, right, bottom = bounds
    factor = max(1.0, (right-left)/(width*.48), (bottom-top)/(height*.76))
    if factor <= 1.04:
        return
    camera = viewport.camera
    options = {'ortho_width': camera.ortho_width*factor} if hasattr(camera, 'ortho_width') else {}
    camera.animate_to(camera.target, camera.distance*factor, camera.yaw, camera.pitch, .2, **options)
    viewport.update()


def _caption_lines(text, font, width):
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    lines = []
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max(1.0, width))
        lines.append(text[line.textStart():line.textStart() + line.textLength()].strip())
    layout.endLayout()
    return lines or [""]


def paint_label_rails(painter, size, font, rows, number_ids, opened, selected,
                      hovered=None, focused=None, numbers=None, specimen_bounds=None,
                      insets=(16.0, 24.0, 16.0, 24.0), caption_zones=None):
    """Paint (key, structure ID, x, y, caption) rows; return numbers and hit areas.

    Keys can differ from structure IDs: a radiology case may pin two names to
    different places on the same structure. Number order persists during orbit.
    """
    width, height = map(float, size)
    font = QFont(font)
    pixels = font.pixelSize() if font.pixelSize() > 0 else round(font.pointSizeF() * 96 / 72)
    font.setPixelSize(max(15, pixels))
    if not rows:
        return (), [], []
    keys = {row[0] for row in rows}
    if set(number_ids) != keys:
        number_ids = tuple(row[0] for row in sorted(rows, key=lambda row: (row[3], row[2], str(row[0]))))
    number = {key: index for index, key in enumerate(number_ids, 1)}
    number.update(numbers or {})
    order = {key: index for index, key in enumerate(number_ids)}
    rows = sorted(rows, key=lambda row: order[row[0]])
    dot_rects, caption_rects = [], []
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setFont(font)
    metrics = QFontMetricsF(font)
    digit_font = QFont(font)
    digit_font.setWeight(QFont.DemiBold)
    selected_font = QFont(font)
    selected_font.setWeight(QFont.DemiBold)
    for key, sid, x, y, _text in rows:
        is_selected, is_open = sid in selected, key in opened
        disc, ink = ((LABEL_GOLD, LABEL_GOLD_INK) if is_selected or is_open else
                     (theme.CANVAS, theme.TEXT))
        painter.setPen(QPen(theme.qc(LABEL_GOLD), 1.2))
        painter.setBrush(theme.qc(disc))
        painter.drawEllipse(QPointF(x, y), 9.0, 9.0)
        painter.setPen(theme.qc(ink))
        painter.setFont(digit_font)
        painter.drawText(QRectF(x - 9, y - 9, 18, 18), Qt.AlignCenter, str(number[key]))
        if key == focused:
            painter.setPen(QPen(theme.qc(theme.TEXT_2), 2.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(x, y), 13.0, 13.0)
        dot_rects.append((QRectF(x - 14, y - 14, 28, 28), key))

    # The specimen leads; names form a quiet column beyond its anchor span.
    # Split at the specimen stage centre. A lesson may intentionally have every
    # anchor on one side; the label cluster's centre would invent a second rail.
    centre = width * .5
    left_inset, top_inset, right_inset, bottom_inset = map(float, insets)
    safe_left, safe_right = left_inset, max(left_inset + 1, width - right_inset)
    safe_top, safe_bottom = top_inset, max(top_inset + 1, height - bottom_inset)
    stage_limits = (safe_left, safe_top, safe_right, safe_bottom)
    if specimen_bounds is None:
        specimen_bounds = (min(row[2] for row in rows), min(row[3] for row in rows),
                           max(row[2] for row in rows), max(row[3] for row in rows))
    body_left, _body_top, body_right, _body_bottom = specimen_bounds
    sides = {-1: [], 1: []}
    for row in rows:
        sides[-1 if row[2] < centre else 1].append(row)
    pitch = max(30.0, metrics.height() + 10.0)
    for side, all_rows in sides.items():
        shown = [row for row in all_rows if row[0] in opened or row[0] in (hovered, focused)]
        if not shown:
            continue
        safe_left, safe_top, safe_right, safe_bottom = stage_limits
        zone = (caption_zones or {}).get(side)
        if zone is not None:
            # A wall below instruments is a different shape from the central
            # model-safe inset. It must override both axes, not clamp inward.
            zx, zy, zw, zh = map(float, zone)
            safe_left, safe_top = max(0, zx) + 2, max(0, zy) + 6
            safe_right, safe_bottom = min(width, zx + zw) - 2, min(height, zy + zh) - 6
            if safe_right <= safe_left or safe_bottom <= safe_top:
                continue
        shown.sort(key=lambda row: (row[3], row[2], str(row[0])))
        rail = body_left - 64 if side < 0 else body_right + 64
        max_width = safe_right - safe_left if zone is not None else max(80.0, min(360.0, (safe_right - safe_left) * .36))
        text_width = min(max_width,
                         max(QFontMetricsF(selected_font if row[1] in selected else font).horizontalAdvance(row[4])
                             for row in shown) + 4)
        x = rail - text_width if side < 0 else rail
        x = max(safe_left, min(safe_right - text_width, x))
        capacity = max(1, int(max(1.0, safe_bottom - safe_top - metrics.height()) / pitch) + 1)
        wrapped = ({row[0]: _caption_lines(row[4], selected_font if row[1] in selected else font, text_width)
                    for row in shown} if zone is not None else {})
        row_heights = {row[0]: len(wrapped.get(row[0], [row[4]])) * metrics.height() + 4 for row in shown}
        if zone is not None:
            needed = sum(row_heights.values()) + max(0, len(shown) - 1) * 10
            if needed <= safe_bottom - safe_top:
                capacity = len(shown)
            else:
                # Very dense views retain the established multiple-column
                # fallback instead of stacking captions on top of one another.
                wrapped = {}
                row_heights = {row[0]: metrics.height() + 4 for row in shown}
        # Dense models retain every caption by using a compact additional column.
        # Split vertically rather than clamping multiple rows onto one position.
        columns = max(1, math.ceil(len(shown) / capacity))
        if columns > 1:
            text_width = min(text_width, max(48.0, ((safe_right - safe_left) * .48 - 12 * columns) / columns))
            x = safe_left if side < 0 else safe_right - columns * text_width - (columns - 1) * 12
        for column_index in range(columns):
            column = shown[column_index * capacity:(column_index + 1) * capacity]
            heights = [row_heights[row[0]] for row in column]
            ys = [max(safe_top + row_height / 2, float(row[3])) for row, row_height in zip(column, heights)]
            for index in range(1, len(ys)):
                spacing = (heights[index - 1] + heights[index]) / 2 + 10 if wrapped else pitch
                ys[index] = max(ys[index], ys[index - 1] + spacing)
            overflow = max(0.0, ys[-1] - (safe_bottom - heights[-1] / 2))
            ys = [y - overflow for y in ys]
            column_x = x + column_index * (text_width + 12)
            spine_x = column_x + text_width + 7 if side < 0 else column_x - 7
            painter.setPen(QPen(theme.qc(theme.BORDER_STRONG, 190), 1.0))
            painter.drawLine(QPointF(spine_x, ys[0]), QPointF(spine_x, ys[-1]))
            for (key, sid, ax, ay, text), cy, row_height in zip(column, ys, heights):
                faint = key not in opened
                painter.setPen(QPen(theme.qc(theme.BORDER_STRONG, 128 if faint else 225), 1.0))
                vx, vy = spine_x - ax, cy - ay
                length = max(11.0, math.hypot(vx, vy))
                start = QPointF(ax + vx * 11 / length, ay + vy * 11 / length)
                join_x = column_x + text_width + 2 if side < 0 else column_x - 2
                painter.drawLine(start, QPointF(spine_x, cy))
                painter.drawLine(QPointF(spine_x, cy), QPointF(join_x, cy))
                text_font = selected_font if sid in selected else font
                painter.setFont(text_font)
                painter.setPen(theme.qc(theme.MUTED if faint else theme.TEXT))
                rect = QRectF(column_x, cy - row_height / 2, text_width, row_height)
                # A fine contour keeps wall lettering legible when zoomed
                # anatomy passes beneath it, without adding a caption panel.
                fm = QFontMetricsF(text_font)
                lines = wrapped.get(key) or [fm.elidedText(text, Qt.ElideRight, int(text_width))]
                baseline = rect.top() + 2 + fm.ascent()
                glyphs = QPainterPath()
                for line in lines:
                    tx = rect.right() - fm.horizontalAdvance(line) if side < 0 else rect.left()
                    glyphs.addText(QPointF(tx, baseline), text_font, line)
                    baseline += metrics.height()
                painter.strokePath(glyphs, QPen(theme.qc(theme.CANVAS, 210), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.fillPath(glyphs, theme.qc(theme.MUTED if faint else theme.TEXT))
                caption_rects.append((rect.adjusted(-2, -3, 2, 3), key))
    painter.restore()
    return number_ids, dot_rects, caption_rects
