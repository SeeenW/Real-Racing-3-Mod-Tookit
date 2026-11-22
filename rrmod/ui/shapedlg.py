"""Drawing a shape for the vinyl editor, in font units.

A decal shape is a glyph, so what has to be produced here is a list of contours
of ``(x, y)`` points in a 2048-unit em square.  That is a small enough target that
a full vector editor would be the wrong shape of tool: the shapes the vinyl
editor offers are stickers - a star, a flag, a number, a sponsor's mark - and the
thing that makes them hard is not drawing them, it is getting them into a font
without breaking the 186 that are already there.

So the canvas does the two things that are actually needed:

* **Draw one by hand**, by clicking points around an outline.
* **Start from something regular** - a square, a circle, a star, a triangle, a
  diamond, an arrow - and then move it and size it.

Everything is kept in font units, with the em square drawn behind it so a shape
that would hang out of the glyph box is visible before it is written.  The y axis
points up, which is the font's own direction and the opposite of the screen's;
the canvas flips it once, on the way in and on the way out, so nothing else in
the code has to think about it.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QSpinBox, QVBoxLayout,
                               QWidget)

from . import widgets as W

#: The em square the shipped font uses.
EM = 2048

#: What the canvas offers before anything is drawn.
PRESETS = ("Square", "Circle", "Triangle", "Diamond", "Star", "Arrow", "Cross")


def preset(name: str, size: int = 1600, centre=(EM // 2, EM // 2)) -> list:
    """One contour for a named shape, in font units."""
    cx, cy = centre
    half = size // 2
    if name == "Square":
        return [[(cx - half, cy - half), (cx + half, cy - half),
                 (cx + half, cy + half), (cx - half, cy + half)]]
    if name == "Triangle":
        return [[(cx, cy + half), (cx + half, cy - half), (cx - half, cy - half)]]
    if name == "Diamond":
        return [[(cx, cy + half), (cx + half, cy), (cx, cy - half), (cx - half, cy)]]
    if name == "Circle":
        return [_ring(cx, cy, half, half, 32)]
    if name == "Star":
        points = []
        for step in range(10):
            angle = math.pi / 2 + step * math.pi / 5
            reach = half if step % 2 == 0 else half // 3
            points.append((cx + int(reach * math.cos(angle)),
                           cy + int(reach * math.sin(angle))))
        return [points]
    if name == "Arrow":
        arm = half // 3
        return [[(cx - half, cy + arm), (cx + arm, cy + arm),
                 (cx + arm, cy + half), (cx + half, cy),
                 (cx + arm, cy - half), (cx + arm, cy - arm),
                 (cx - half, cy - arm)]]
    if name == "Cross":
        arm = half // 3
        return [[(cx - arm, cy - half), (cx + arm, cy - half),
                 (cx + arm, cy - arm), (cx + half, cy - arm),
                 (cx + half, cy + arm), (cx + arm, cy + arm),
                 (cx + arm, cy + half), (cx - arm, cy + half),
                 (cx - arm, cy + arm), (cx - half, cy + arm),
                 (cx - half, cy - arm), (cx - arm, cy - arm)]]
    return []


def _ring(cx: int, cy: int, rx: int, ry: int, steps: int) -> list:
    return [(cx + int(rx * math.cos(2 * math.pi * i / steps)),
             cy + int(ry * math.sin(2 * math.pi * i / steps)))
            for i in range(steps)]


def scale_contours(contours, factor: float) -> list:
    """Grow or shrink every contour around the em square's centre."""
    cx = cy = EM // 2
    return [[(int(cx + (x - cx) * factor), int(cy + (y - cy) * factor))
             for x, y in contour] for contour in contours]


def fit_contours(contours, box: int = 1600) -> list:
    """Scale a drawing so its longest side fills ``box``, and centre it."""
    points = [p for contour in contours for p in contour]
    if not points:
        return contours
    low_x = min(p[0] for p in points)
    high_x = max(p[0] for p in points)
    low_y = min(p[1] for p in points)
    high_y = max(p[1] for p in points)
    wide = max(1, high_x - low_x)
    tall = max(1, high_y - low_y)
    factor = min(box / wide, box / tall)
    cx = (low_x + high_x) / 2.0
    cy = (low_y + high_y) / 2.0
    mid = EM / 2.0
    return [[(int(mid + (x - cx) * factor), int(mid + (y - cy) * factor))
             for x, y in contour] for contour in contours]


class ShapeCanvas(QWidget):
    """Where a shape is drawn: click to add a point, drag to move one."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 360)
        self.contours = []
        self._drag = None
        self.setMouseTracking(True)

    # ---------------------------------------------------------------- geometry
    def _scale(self) -> float:
        return min(self.width(), self.height()) / float(EM)

    def _origin(self) -> tuple:
        size = EM * self._scale()
        return ((self.width() - size) / 2.0, (self.height() - size) / 2.0)

    def to_screen(self, x: int, y: int) -> QPoint:
        ox, oy = self._origin()
        scale = self._scale()
        # The font's y axis points up and the screen's points down, so this is the
        # one place the flip happens.
        return QPoint(int(ox + x * scale), int(oy + (EM - y) * scale))

    def to_font(self, point: QPoint) -> tuple:
        ox, oy = self._origin()
        scale = self._scale() or 1.0
        return (int((point.x() - ox) / scale), int(EM - (point.y() - oy) / scale))

    # ---------------------------------------------------------------- painting
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#1b1b1b"))

        # The em square, and the middle of it.
        ox, oy = self._origin()
        size = int(EM * self._scale())
        painter.setPen(QPen(QColor("#3a3a3a"), 1))
        painter.drawRect(int(ox), int(oy), size, size)
        painter.setPen(QPen(QColor("#2a2a2a"), 1, Qt.DashLine))
        painter.drawLine(int(ox), int(oy + size / 2), int(ox + size),
                         int(oy + size / 2))
        painter.drawLine(int(ox + size / 2), int(oy), int(ox + size / 2),
                         int(oy + size))

        if not self.contours:
            painter.setPen(QPen(QColor("#7a7a7a"), 1))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "Pick a shape, or click to place points")
            return

        painter.setPen(QPen(QColor("#f0c040"), 2))
        for contour in self.contours:
            path = QPainterPath()
            first = self.to_screen(*contour[0])
            path.moveTo(first)
            for x, y in contour[1:]:
                path.lineTo(self.to_screen(x, y))
            path.closeSubpath()
            painter.drawPath(path)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.setBrush(QColor("#f0c040"))
        for contour in self.contours:
            for x, y in contour:
                point = self.to_screen(x, y)
                painter.drawEllipse(point, 3, 3)

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        here = self.to_font(event.position().toPoint())
        # Close to an existing point: drag that one instead of adding another.
        for ci, contour in enumerate(self.contours):
            for pi, (x, y) in enumerate(contour):
                if abs(x - here[0]) < 40 and abs(y - here[1]) < 40:
                    self._drag = (ci, pi)
                    return
        if not self.contours:
            self.contours = [[]]
        self.contours[-1].append(here)
        self.changed.emit()
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            return
        ci, pi = self._drag
        self.contours[ci][pi] = self.to_font(event.position().toPoint())
        self.update()

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag is not None:
            self._drag = None
            self.changed.emit()

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-click on a point removes it; on empty space, starts a contour."""
        here = self.to_font(event.position().toPoint())
        for ci, contour in enumerate(self.contours):
            for pi, (x, y) in enumerate(contour):
                if abs(x - here[0]) < 40 and abs(y - here[1]) < 40:
                    if len(contour) > 3:
                        del contour[pi]
                    else:
                        self.contours.pop(ci)
                    self.changed.emit()
                    self.update()
                    return
        self.contours.append([])
        self.changed.emit()
        self.update()

    # ------------------------------------------------------------------- data
    def set_contours(self, contours) -> None:
        self.contours = [[(int(x), int(y)) for x, y in contour]
                         for contour in contours if contour]
        self.changed.emit()
        self.update()

    def points(self) -> int:
        return sum(len(c) for c in self.contours)

    def usable(self) -> bool:
        return bool(self.contours) and all(len(c) >= 3 for c in self.contours)


class ShapeDialog(QDialog):
    """Draw one shape and say what to call it."""

    def __init__(self, parent=None, *, code_point: int = 0xE000,
                 taken=()):
        super().__init__(parent)
        self.setWindowTitle("A new shape")
        self.taken = set(taken)
        lay = QVBoxLayout(self)

        note = W.muted(
            "A shape is a glyph in r3_decals.ttf plus the record that names it. "
            "Both are written in one step, because either alone draws nothing. "
            "Pick a starting shape and adjust it, or click points on the canvas.")
        note.setWordWrap(True)
        lay.addWidget(note)

        bar = QHBoxLayout()
        self.preset = QComboBox()
        for name in PRESETS:
            self.preset.addItem(name)
        bar.addWidget(self.preset)
        bar.addWidget(W.button("Use this shape", self._use_preset))
        bar.addWidget(W.button("Clear", self._clear))
        bar.addWidget(W.button("Fit to the box", self._fit))
        bar.addStretch(1)
        lay.addLayout(bar)

        self.canvas = ShapeCanvas()
        self.canvas.changed.connect(self._say)
        lay.addWidget(self.canvas, 1)

        form = QFormLayout()
        self.code = QLineEdit(f"0x{code_point:04X}")
        self.code.setToolTip(
            "The code point the record will name. It has to be in the basic "
            "multilingual plane, and it should be one the font does not use yet.")
        form.addRow("Code point", self.code)
        self.name = QLineEdit("")
        self.name.setPlaceholderText("GAMETEXT_RRMOD_SHAPE (left empty: one is made)")
        form.addRow("Name key", self.name)
        self.category = QLineEdit("GAMETEXT_CUSTOMISATION_DECALS_SHAPES_NAME")
        form.addRow("Category", self.category)
        self.advance = QSpinBox()
        self.advance.setRange(0, 20000)
        self.advance.setValue(0)
        self.advance.setToolTip("0 leaves a margin past the shape's own width")
        form.addRow("Advance width", self.advance)
        self.grow = QCheckBox("Grow it to fill the glyph box when it is saved")
        self.grow.setChecked(True)
        form.addRow("", self.grow)
        lay.addLayout(form)

        self.problem = W.muted("")
        self.problem.setWordWrap(True)
        lay.addWidget(self.problem)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._use_preset()
        self._say()

    # ------------------------------------------------------------------ pieces
    def _use_preset(self) -> None:
        self.canvas.set_contours(preset(self.preset.currentText()))

    def _clear(self) -> None:
        self.canvas.set_contours([])

    def _fit(self) -> None:
        self.canvas.set_contours(fit_contours(self.canvas.contours))

    def _say(self) -> None:
        count = len(self.canvas.contours)
        points = self.canvas.points()
        if not count:
            self.problem.setText("Nothing drawn yet.")
            return
        if not self.canvas.usable():
            self.problem.setText("Every contour needs at least three points.")
            return
        low = min(p[1] for c in self.canvas.contours for p in c)
        high = max(p[1] for c in self.canvas.contours for p in c)
        if low < 0 or high > EM:
            self.problem.setText(
                f"The shape runs from y={low} to y={high}, outside the 0..{EM} "
                f"box. It still draws, but it will sit oddly against text.")
            return
        self.problem.setText(f"{count} contour(s), {points} point(s).")

    def _accept(self) -> None:
        if not self.canvas.usable():
            self.problem.setText("Draw a closed shape with at least three points.")
            return
        try:
            code = int(self.code.text().strip(), 0)
        except ValueError:
            self.problem.setText("The code point has to be a number, like 0xE000.")
            return
        if not 0 < code <= 0xFFFF:
            self.problem.setText("A code point has to be between 1 and 0xFFFF.")
            return
        if code in self.taken:
            self.problem.setText(
                f"U+{code:04X} already has a glyph in this font. Writing it again "
                f"would replace that drawing, which some record may be using.")
            return
        self.accept()

    # ------------------------------------------------------------------- result
    def result_info(self) -> dict:
        contours = self.canvas.contours
        if self.grow.isChecked():
            contours = fit_contours(contours)
        return {"code_point": int(self.code.text().strip(), 0),
                "contours": contours,
                "advance": int(self.advance.value()),
                "name": self.name.text().strip().encode("latin-1", "replace"),
                "category": self.category.text().strip().encode("latin-1", "replace")}
