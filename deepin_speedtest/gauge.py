"""The speed dial: a custom-painted, resolution-independent arc gauge."""

from __future__ import annotations

import math
from typing import List, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QConicalGradient, QFont, QPainter, QPen
from PyQt5.QtWidgets import QPushButton, QSizePolicy, QWidget

# Piecewise scale so that both 5 Mbit/s and 900 Mbit/s are readable.
TICKS: List[float] = [0, 5, 10, 25, 50, 100, 250, 500, 1000]
SCALES = {
    1000: TICKS,
    2500: [0, 10, 25, 50, 100, 250, 500, 1000, 2500],
    5000: [0, 10, 50, 100, 250, 500, 1000, 2500, 5000],
}


def tick_label(tick: float) -> str:
    return ("%gG" % (tick / 1000.0)) if tick >= 1000 else ("%g" % tick)
START_ANGLE = 215.0   # degrees, Qt convention (0 = 3 o'clock, counter-clockwise)
SPAN = 250.0


def value_to_fraction(value: float, ticks: List[float] = TICKS) -> float:
    if value <= 0:
        return 0.0
    if value >= ticks[-1]:
        return 1.0
    seg = 1.0 / (len(ticks) - 1)
    for i in range(len(ticks) - 1):
        lo, hi = ticks[i], ticks[i + 1]
        if value <= hi:
            return seg * (i + (value - lo) / (hi - lo))
    return 1.0


class SpeedGauge(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(280, 260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._target = 0.0
        self._shown = 0.0
        self._ticks = TICKS
        self._unit = "Mbit/s"
        self._caption = "Ready"
        self._accent = QColor("#14b8a6")
        self._accent2 = QColor("#f59e0b")
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)
        self.setAccessibleName("Speed gauge")

    def set_colors(self, accent: QColor, accent2: QColor) -> None:
        self._accent, self._accent2 = accent, accent2
        self.update()

    def set_max_speed(self, mbps: int) -> None:
        """Choose the dial range: 1000, 2500 or 5000 Mbit/s."""
        self._ticks = SCALES.get(mbps, TICKS)
        self.update()

    def set_value(self, value: float, unit: str = "Mbit/s") -> None:
        self._target = max(0.0, value)
        self._unit = unit
        self.setAccessibleDescription("%.1f %s" % (value, unit))
        if not self._timer.isActive():
            self._timer.start()

    def set_caption(self, text: str) -> None:
        self._caption = text
        self.update()

    def reset(self) -> None:
        self._target = 0.0
        self._timer.start()

    def _step(self) -> None:
        diff = self._target - self._shown
        if abs(diff) < 0.05:
            self._shown = self._target
            self._timer.stop()
        else:
            self._shown += diff * 0.18
        self.update()

    def _geometry(self) -> Tuple[QRectF, float]:
        side = min(self.width(), self.height() * 1.08) - 24
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2 + side * 0.04, side, side)
        return rect, side

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        fg = pal.windowText().color()
        track = QColor(fg)
        track.setAlphaF(0.10)
        rect, side = self._geometry()
        width = max(8.0, side * 0.055)
        arc = rect.adjusted(width, width, -width, -width)

        pen = QPen(track, width, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(arc, int(START_ANGLE * 16), int(-SPAN * 16))

        frac = value_to_fraction(self._shown, self._ticks) if self._unit == "Mbit/s" else min(1.0, self._shown / 200.0)
        if frac > 0.001:
            grad = QConicalGradient(arc.center(), START_ANGLE)
            # Qt's conical gradient runs counter-clockwise from START_ANGLE while
            # the arc is drawn clockwise, so the arc covers [1 - SPAN/360, 1].
            grad.setColorAt(0.0, self._accent)
            grad.setColorAt(1.0 - SPAN / 360.0, self._accent2)
            grad.setColorAt(1.0, self._accent)
            p.setPen(QPen(grad, width, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(arc, int(START_ANGLE * 16), int(-SPAN * frac * 16))

        # tick labels
        label_font = QFont(self.font())
        label_font.setPointSizeF(max(7.0, side * 0.032))
        p.setFont(label_font)
        dim = QColor(fg)
        dim.setAlphaF(0.55)
        p.setPen(dim)
        radius = arc.width() / 2 - width * 1.6
        c = arc.center()
        if self._unit == "Mbit/s":
            for i, tick in enumerate(self._ticks):
                ang = math.radians(START_ANGLE - SPAN * i / (len(self._ticks) - 1))
                pt = QPointF(c.x() + radius * math.cos(ang), c.y() - radius * math.sin(ang))
                text = tick_label(tick)
                p.drawText(QRectF(pt.x() - 22, pt.y() - 10, 44, 20), Qt.AlignCenter, text)

        # value
        big = QFont(self.font())
        big.setPointSizeF(max(14.0, side * 0.13))
        big.setWeight(QFont.DemiBold)
        p.setFont(big)
        p.setPen(fg)
        shown = self._shown
        txt = ("%.0f" % shown) if shown >= 100 else ("%.1f" % shown)
        p.drawText(QRectF(rect.left(), c.y() - side * 0.12, rect.width(), side * 0.18), Qt.AlignCenter, txt)
        small = QFont(self.font())
        small.setPointSizeF(max(8.0, side * 0.042))
        p.setFont(small)
        p.setPen(dim)
        p.drawText(QRectF(rect.left(), c.y() + side * 0.07, rect.width(), side * 0.07), Qt.AlignCenter, self._unit)
        p.setPen(self._accent)
        p.drawText(QRectF(rect.left(), c.y() + side * 0.27, rect.width(), side * 0.08), Qt.AlignCenter,
                   self._caption)
        p.end()


class PillButton(QPushButton):
    """The Start/Stop button, painted by hand.

    Desktop styles (Deepin's in particular) draw their own rectangular focus
    frame and shadow behind a style-sheet button, which shows up as dark
    corners around a rounded button. Painting the pill ourselves gives the
    same look on every desktop.
    """

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self._fill = QColor("#14b8a6")
        self._hover = QColor("#0d9488")
        self._text = QColor("#ffffff")
        self.setMinimumSize(190, 46)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFlat(True)
        font = QFont(self.font())
        font.setPointSizeF(12.0)
        font.setWeight(QFont.DemiBold)
        self.setFont(font)

    def set_colors(self, fill: QColor, hover: QColor, text: QColor) -> None:
        self._fill, self._hover, self._text = fill, hover, text
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        color = self._hover if (self.underMouse() or self.isDown()) else self._fill
        if not self.isEnabled():
            color = QColor(color)
            color.setAlphaF(0.4)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(rect, radius, radius)
        if self.hasFocus() and self._keyboard_focus:
            ring = QColor(self._text)
            ring.setAlphaF(0.55)
            p.setPen(QPen(ring, 1.5))
            p.setBrush(Qt.NoBrush)
            inner = rect.adjusted(3, 3, -3, -3)
            p.drawRoundedRect(inner, inner.height() / 2, inner.height() / 2)
        p.setPen(self._text)
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignCenter, self.text())
        p.end()

    _keyboard_focus = False

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._keyboard_focus = event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(event)
