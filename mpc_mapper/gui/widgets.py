"""Small reusable widgets: palette grid, colour picker button."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QDialog, QPushButton, QToolTip, QVBoxLayout,
                               QWidget)

from .. import apc


def qcolor(rgb) -> QColor:
    return QColor(*rgb)


def ui_font(point_size: float, bold: bool = False) -> QFont:
    """The platform's UI font at a given size (generic names like "Sans" only
    resolve on Linux/fontconfig, so ask Qt for the real default family)."""
    f = QFont(QApplication.font())
    f.setPointSizeF(point_size)
    f.setBold(bold)
    return f


def mono_font(point_size: float) -> QFont:
    """The platform's fixed-width font (Consolas on Windows, Menlo on macOS, ...)."""
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPointSizeF(point_size)
    return f


def text_color_for(rgb) -> QColor:
    r, g, b = rgb
    return QColor(0, 0, 0) if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else QColor(235, 235, 235)


class PaletteGrid(QWidget):
    """16 x 8 grid of the 128 APC palette colours. Emits picked(index)."""
    picked = Signal(int)
    COLS, ROWS = 16, 8

    def __init__(self, cell: int = 22, parent=None) -> None:
        super().__init__(parent)
        self.cell = cell
        self.selected = -1
        self.setMouseTracking(True)
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:
        return QSize(self.COLS * self.cell + 1, self.ROWS * self.cell + 1)

    def _rect(self, i: int) -> QRect:
        r, c = divmod(i, self.COLS)
        return QRect(c * self.cell, r * self.cell, self.cell, self.cell)

    def _index_at(self, p: QPoint) -> int:
        c, r = p.x() // self.cell, p.y() // self.cell
        if 0 <= c < self.COLS and 0 <= r < self.ROWS:
            return r * self.COLS + c
        return -1

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        for i, rgb in enumerate(apc.PALETTE):
            rect = self._rect(i).adjusted(1, 1, -1, -1)
            p.fillRect(rect, qcolor(rgb))
            if i == self.selected:
                p.setPen(QPen(QColor("white"), 2))
                p.drawRect(rect.adjusted(1, 1, -1, -1))
                p.setPen(QPen(QColor("black"), 1))
                p.drawRect(rect.adjusted(3, 3, -3, -3))

    def mouseMoveEvent(self, e) -> None:
        i = self._index_at(e.position().toPoint())
        if i >= 0:
            r, g, b = apc.PALETTE[i]
            QToolTip.showText(e.globalPosition().toPoint(),
                              f"Index {i} (0x{i:02X})  #{r:02X}{g:02X}{b:02X}", self)

    def mousePressEvent(self, e) -> None:
        i = self._index_at(e.position().toPoint())
        if i >= 0:
            self.selected = i
            self.update()
            self.picked.emit(i)


class PalettePopup(QDialog):
    def __init__(self, current: int, parent=None) -> None:
        super().__init__(parent, Qt.Popup)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.grid = PaletteGrid()
        self.grid.selected = current
        self.grid.picked.connect(self._pick)
        lay.addWidget(self.grid)
        self.value = current

    def _pick(self, i: int) -> None:
        self.value = i
        self.accept()


class PaletteButton(QPushButton):
    """Shows a palette colour; click opens the palette popup."""
    changed = Signal(int)

    def __init__(self, index: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(90)
        self.set_index(index)
        self.clicked.connect(self._open)

    def set_index(self, i: int) -> None:
        self.index = i
        rgb = apc.PALETTE[i]
        fg = text_color_for(rgb)
        self.setText(f"{i}")
        self.setStyleSheet(
            f"background-color: rgb{rgb}; color: {fg.name()}; border: 1px solid #555;"
            "padding: 4px; border-radius: 3px;")

    def _open(self) -> None:
        pop = PalettePopup(self.index, self)
        pop.move(self.mapToGlobal(QPoint(0, self.height())))
        if pop.exec():
            self.set_index(pop.value)
            self.changed.emit(pop.value)
