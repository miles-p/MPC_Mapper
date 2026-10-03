"""Interactive drawing of the APC mini mk2.

* Drop a grandMA3 control from the catalogue onto a pad/button/fader.
* Drag one control onto another to move the assignment (hold Ctrl to copy).
* Click selects; Shift+click (or right-click > Simulate) fires the control
  as if pressed on the hardware; Shift+drag on a fader moves it.
* Pads are painted with the LED state the engine actually sends.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QDrag, QFont, QLinearGradient, QPainter,
                           QPen)
from PySide6.QtWidgets import QMenu, QWidget

from .. import apc
from ..apc import LedState
from ..model import Mapping
from .widgets import qcolor, text_color_for

MIME_CATALOG = "application/x-ma3-catalog"
MIME_CONTROL = "application/x-apc-control"

# logical geometry (scaled to widget)
PAD, GAP, X0, Y0 = 62.0, 9.0, 34.0, 70.0
GRID = 8 * PAD + 7 * GAP
SCENE_X = X0 + GRID + 18
SCENE_W = 46.0
TRACK_Y = Y0 + GRID + 16
TRACK_H = 22.0
FADER_Y = TRACK_Y + TRACK_H + 26
FADER_H = 170.0
W = SCENE_X + SCENE_W + 30
H = FADER_Y + FADER_H + 46


def _col_x(i: int) -> float:
    return X0 + i * (PAD + GAP)


def control_rect(control: str) -> QRectF:
    kind, _, idx = control.partition(":")
    if kind == "pad":
        n = int(idx)
        row, col = divmod(n, 8)
        return QRectF(_col_x(col), Y0 + (7 - row) * (PAD + GAP), PAD, PAD)
    if kind == "scene":
        n = int(idx)  # 0 = top
        return QRectF(SCENE_X, Y0 + n * (PAD + GAP) + PAD / 2 - 13, SCENE_W, 26)
    if kind == "track":
        return QRectF(_col_x(int(idx)), TRACK_Y, PAD, TRACK_H)
    if kind == "shift":
        return QRectF(SCENE_X, TRACK_Y, SCENE_W, TRACK_H)
    if kind == "fader":
        n = int(idx)
        x = SCENE_X + (SCENE_W - PAD) / 2 if n == 8 else _col_x(n)
        return QRectF(x, FADER_Y, PAD, FADER_H)
    return QRectF()


class APCWidget(QWidget):
    selected = Signal(str)
    catalog_dropped = Signal(str, str)      # catalog_id, control
    control_moved = Signal(str, str, bool)  # src, dst, copy
    simulate_button = Signal(str, bool)
    simulate_fader = Signal(str, int)
    clear_requested = Signal(str)

    def __init__(self, mapping: Mapping, parent=None) -> None:
        super().__init__(parent)
        self.mapping = mapping
        self.leds: dict[str, LedState] = {}
        self.fader_values: dict[str, int] = {f"fader:{i}": 0 for i in range(9)}
        self.hw_pressed: set[str] = set()
        self.selected_control: Optional[str] = None
        self.drop_hover: Optional[str] = None
        self.accepts: Callable[[str, str], bool] = lambda cat, ctrl: True
        self._press_pos: Optional[QPointF] = None
        self._press_ctrl: Optional[str] = None
        self._sim_down: Optional[str] = None
        self._blink = False
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumSize(int(W * 0.75), int(H * 0.75))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)

    # ------------------------------------------------------------------ #
    def _tick(self) -> None:
        self._blink = not self._blink
        if any(s.animated for s in self.leds.values()) or any(
                s.color == apc.SINGLE_BLINK for c, s in self.leds.items() if not apc.is_rgb(c)):
            self.update()

    def set_led(self, control: str, state: LedState) -> None:
        self.leds[control] = state
        self.update()

    def hw_event(self, control: str, value) -> None:
        if control.startswith("fader:"):
            self.fader_values[control] = int(value)
        elif value:
            self.hw_pressed.add(control)
        else:
            self.hw_pressed.discard(control)
        self.update()

    def select(self, control: Optional[str]) -> None:
        self.selected_control = control
        self.update()
        if control:
            self.selected.emit(control)

    # ---------------- geometry ----------------
    def _scale(self) -> tuple[float, float, float]:
        s = min(self.width() / W, self.height() / H)
        ox = (self.width() - W * s) / 2
        oy = (self.height() - H * s) / 2
        return s, ox, oy

    def _to_logical(self, p: QPointF) -> QPointF:
        s, ox, oy = self._scale()
        return QPointF((p.x() - ox) / s, (p.y() - oy) / s)

    def control_at(self, p: QPointF) -> Optional[str]:
        lp = self._to_logical(p)
        for c in apc.ALL_CONTROLS:
            if control_rect(c).adjusted(-3, -3, 3, 3).contains(lp):
                return c
        return None

    # ---------------- painting ----------------
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#1b1d21"))
        s, ox, oy = self._scale()
        p.translate(ox, oy)
        p.scale(s, s)

        # body
        body = QRectF(6, 6, W - 12, H - 12)
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0, QColor("#2c2e33"))
        grad.setColorAt(1, QColor("#202226"))
        p.setPen(QPen(QColor("#45484f"), 2))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(body, 18, 18)
        p.setPen(QColor("#c8c8c8"))
        f = QFont("Sans", 15, QFont.Bold)
        p.setFont(f)
        p.drawText(QRectF(X0, 22, 300, 30), Qt.AlignLeft | Qt.AlignVCenter, "AKAI  APC mini")
        p.setPen(QColor("#e05a2a"))
        p.setFont(QFont("Sans", 11, QFont.Bold))
        p.drawText(QRectF(X0 + 178, 24, 60, 30), Qt.AlignLeft | Qt.AlignVCenter, "mk2")
        p.setPen(QColor("#8a8d94"))
        p.setFont(QFont("Sans", 9))
        p.drawText(QRectF(X0 + 240, 22, W - X0 - 274, 30), Qt.AlignRight | Qt.AlignVCenter,
                   "Shift+click = simulate · drag = move · Ctrl+drag = copy")

        for c in apc.ALL_CONTROLS:
            kind = apc.control_kind(c)
            if kind == "pad":
                self._paint_pad(p, c)
            elif kind == "fader":
                self._paint_fader(p, c)
            else:
                self._paint_button(p, c)

    def _outline(self, p: QPainter, c: str, rect: QRectF, radius: float) -> None:
        if c == self.drop_hover:
            p.setPen(QPen(QColor("#ffd23f"), 3, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), radius + 2, radius + 2)
        if c == self.selected_control:
            p.setPen(QPen(QColor("#3fa9ff"), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), radius + 2, radius + 2)
        if c in self.hw_pressed:
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), radius, radius)

    def _label(self, c: str) -> str:
        a = self.mapping.assignments.get(c)
        return a.name if a else ""

    def _paint_pad(self, p: QPainter, c: str) -> None:
        rect = control_rect(c)
        st = self.leds.get(c, LedState(0))
        rgb = st.display_rgb()
        if st.animated and self._blink:
            if st.mode >= 11:   # blink -> off phase
                rgb = (0, 0, 0)
            else:               # pulse -> dim phase
                rgb = tuple(int(v * 0.35) for v in rgb)
        lit = max(rgb) > 8
        base = qcolor(rgb) if lit else QColor("#3a3c41")
        p.setPen(QPen(QColor("#111"), 1.5))
        p.setBrush(base)
        p.drawRoundedRect(rect, 6, 6)
        if lit:  # soft glow highlight
            g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            g.setColorAt(0, QColor(255, 255, 255, 60))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(rect.adjusted(2, 2, -2, -rect.height() / 2), 5, 5)
        text = self._label(c)
        if text:
            p.setPen(text_color_for(rgb) if lit else QColor("#d0d0d0"))
            p.setFont(QFont("Sans", 7))
            p.drawText(rect.adjusted(3, 3, -3, -3), Qt.AlignCenter | Qt.TextWordWrap, text)
        self._outline(p, c, rect, 6)

    def _paint_button(self, p: QPainter, c: str) -> None:
        rect = control_rect(c)
        kind = apc.control_kind(c)
        st = self.leds.get(c, LedState(0, 0))
        on = st.color == apc.SINGLE_ON or (st.color == apc.SINGLE_BLINK and not self._blink)
        if kind == "track":
            col = QColor("#ff2a1a") if on else QColor("#4a2a28")
        elif kind == "scene":
            col = QColor("#30ff4a") if on else QColor("#26402a")
        else:
            col = QColor("#5a5d64")
        p.setPen(QPen(QColor("#111"), 1.5))
        p.setBrush(col)
        p.drawRoundedRect(rect, 4, 4)
        text = self._label(c) or ("SHIFT" if kind == "shift" else "")
        if text:
            p.setPen(QColor("#111") if on else QColor("#d8d8d8"))
            p.setFont(QFont("Sans", 6))
            p.drawText(rect.adjusted(2, 0, -2, 0), Qt.AlignCenter | Qt.TextWordWrap, text)
        self._outline(p, c, rect, 4)

    def _paint_fader(self, p: QPainter, c: str) -> None:
        rect = control_rect(c)
        slot = QRectF(rect.center().x() - 4, rect.top() + 8, 8, rect.height() - 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0d0e10"))
        p.drawRoundedRect(slot, 4, 4)
        v = self.fader_values.get(c, 0) / 127.0
        cy = slot.bottom() - v * slot.height()
        cap = QRectF(rect.center().x() - 20, cy - 11, 40, 22)
        g = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        g.setColorAt(0, QColor("#d0d2d6"))
        g.setColorAt(1, QColor("#7d8087"))
        p.setBrush(QBrush(g))
        p.setPen(QPen(QColor("#111"), 1))
        p.drawRoundedRect(cap, 3, 3)
        p.setPen(QPen(QColor("#222"), 2))
        p.drawLine(QPointF(cap.left() + 4, cy), QPointF(cap.right() - 4, cy))
        text = self._label(c) or ("Master" if c == "fader:8" else "")
        p.setPen(QColor("#d8d8d8"))
        p.setFont(QFont("Sans", 7))
        p.drawText(QRectF(rect.left() - 4, rect.bottom() + 2, rect.width() + 8, 30),
                   Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, text)
        self._outline(p, c, rect, 6)

    # ---------------- mouse ----------------
    def mousePressEvent(self, e) -> None:
        c = self.control_at(e.position())
        if e.button() == Qt.RightButton:
            if c:
                self._context_menu(c, e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        if c and e.modifiers() & Qt.ShiftModifier:
            if c.startswith("fader:"):
                self._sim_down = c
                self._sim_fader_to(c, e.position())
            else:
                self._sim_down = c
                self.simulate_button.emit(c, True)
            return
        self._press_pos = e.position()
        self._press_ctrl = c
        self.select(c)

    def _sim_fader_to(self, c: str, pos: QPointF) -> None:
        rect = control_rect(c)
        lp = self._to_logical(pos)
        top, bot = rect.top() + 8, rect.bottom() - 8
        v = int(round(max(0.0, min(1.0, (bot - lp.y()) / (bot - top))) * 127))
        self.simulate_fader.emit(c, v)

    def mouseMoveEvent(self, e) -> None:
        if self._sim_down and self._sim_down.startswith("fader:"):
            self._sim_fader_to(self._sim_down, e.position())
            return
        if (self._press_ctrl and self._press_pos is not None and e.buttons() & Qt.LeftButton
                and (e.position() - self._press_pos).manhattanLength() > 8
                and self._press_ctrl in self.mapping.assignments):
            drag = QDrag(self)
            md = QMimeData()
            md.setData(MIME_CONTROL, self._press_ctrl.encode())
            drag.setMimeData(md)
            self._press_ctrl = None
            drag.exec(Qt.MoveAction | Qt.CopyAction)

    def mouseReleaseEvent(self, e) -> None:
        if self._sim_down:
            if not self._sim_down.startswith("fader:"):
                self.simulate_button.emit(self._sim_down, False)
            self._sim_down = None
        self._press_ctrl = None
        self._press_pos = None

    def _context_menu(self, c: str, gpos) -> None:
        self.select(c)
        m = QMenu(self)
        if apc.is_button(c):
            act = m.addAction("Simulate press")
            act.triggered.connect(lambda: (self.simulate_button.emit(c, True),
                                           QTimer.singleShot(150, lambda: self.simulate_button.emit(c, False))))
        clr = m.addAction("Clear assignment")
        clr.setEnabled(c in self.mapping.assignments)
        clr.triggered.connect(lambda: self.clear_requested.emit(c))
        m.exec(gpos)

    # ---------------- drag & drop ----------------
    def _drop_ok(self, e) -> Optional[str]:
        c = self.control_at(e.position())
        if not c:
            return None
        md = e.mimeData()
        if md.hasFormat(MIME_CATALOG):
            cat = bytes(md.data(MIME_CATALOG)).decode()
            return c if self.accepts(cat, c) else None
        if md.hasFormat(MIME_CONTROL):
            src = bytes(md.data(MIME_CONTROL)).decode()
            if src == c:
                return None
            same = (src.startswith("fader:")) == (c.startswith("fader:"))
            return c if same else None
        return None

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasFormat(MIME_CATALOG) or e.mimeData().hasFormat(MIME_CONTROL):
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        c = self._drop_ok(e)
        if c != self.drop_hover:
            self.drop_hover = c
            self.update()
        if c:
            if e.mimeData().hasFormat(MIME_CONTROL):
                e.setDropAction(Qt.CopyAction if e.modifiers() & Qt.ControlModifier
                                else Qt.MoveAction)
                e.accept()
            else:
                e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, _e) -> None:
        self.drop_hover = None
        self.update()

    def dropEvent(self, e) -> None:
        c = self._drop_ok(e)
        self.drop_hover = None
        self.update()
        if not c:
            e.ignore()
            return
        md = e.mimeData()
        if md.hasFormat(MIME_CATALOG):
            self.catalog_dropped.emit(bytes(md.data(MIME_CATALOG)).decode(), c)
        else:
            src = bytes(md.data(MIME_CONTROL)).decode()
            copy = bool(e.modifiers() & Qt.ControlModifier)
            self.control_moved.emit(src, c, copy)
        e.acceptProposedAction()
        self.select(c)
