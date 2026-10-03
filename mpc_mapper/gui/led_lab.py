"""LED Lab: explore the APC mini mk2 LED codes live on the hardware."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                               QWidget)

from .. import apc
from ..apc import LedState
from .widgets import PaletteGrid


class LedLab(QWidget):
    lab_mode_changed = Signal(bool)

    def __init__(self, device: apc.APCMini, selected: Callable[[], Optional[str]],
                 parent=None) -> None:
        super().__init__(parent)
        self.device = device
        self.selected = selected
        self.color = 21
        self.rgb = (255, 128, 0)

        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.take = QCheckBox("Lab takes over LEDs (pauses MA3 feedback)")
        self.take.toggled.connect(self.lab_mode_changed)
        left.addWidget(self.take)
        left.addWidget(QLabel("Palette (velocity = colour index). Click to pick:"))
        self.grid = PaletteGrid(cell=20)
        self.grid.selected = self.color
        self.grid.picked.connect(self._pick)
        left.addWidget(self.grid)
        self.info = QLabel()
        left.addWidget(self.info)
        left.addStretch(1)
        lay.addLayout(left)

        right = QVBoxLayout()
        box = QGroupBox("Send to selected control")
        g = QGridLayout(box)
        self.mode = QComboBox()
        self.mode.addItems([f"ch {i + 1:>2} (0x{0x90 | i:02X})  {m}" for i, m in enumerate(apc.LED_MODES)])
        self.mode.setCurrentIndex(apc.MODE_SOLID_100)
        self.mode.currentIndexChanged.connect(self._update_info)
        g.addWidget(QLabel("Behaviour (MIDI channel)"), 0, 0)
        g.addWidget(self.mode, 0, 1)
        b = QPushButton("Send palette colour")
        b.clicked.connect(self._send_palette)
        g.addWidget(b, 1, 0)
        self.rgb_btn = QPushButton("Pick RGB…")
        self.rgb_btn.clicked.connect(self._pick_rgb)
        g.addWidget(self.rgb_btn, 1, 1)
        b = QPushButton("Send RGB (SysEx)")
        b.clicked.connect(self._send_rgb)
        g.addWidget(b, 2, 1)
        g.addWidget(QLabel("Track / Scene buttons:"), 3, 0)
        single = QHBoxLayout()
        for i, n in enumerate(apc.SINGLE_STATES):
            sb = QPushButton(n)
            sb.clicked.connect(lambda _=False, v=i: self._send_single(v))
            single.addWidget(sb)
        g.addLayout(single, 3, 1)
        right.addWidget(box)

        box2 = QGroupBox("Whole-grid demos")
        h = QGridLayout(box2)
        for i, (label, fn) in enumerate([
            ("Palette 0-63", lambda: self._palette_page(0)),
            ("Palette 64-127", lambda: self._palette_page(64)),
            ("Behaviours (row = mode)", self._modes_demo),
            ("RGB rainbow (SysEx)", self._rainbow),
            ("All buttons blink", self._buttons_blink),
            ("All off", self.device.clear_all),
        ]):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, f=fn: self._run(f))
            h.addWidget(btn, i // 2, i % 2)
        right.addWidget(box2)

        box3 = QGroupBox("Raw MIDI (hex)")
        r = QHBoxLayout(box3)
        self.raw = QLineEdit("96 00 05")
        self.raw.setToolTip("e.g. '96 00 05' = Note On ch7 (0x96) pad 0 colour 5 (pulse)\n"
                            "'F0 47 7F 4F 24 00 08 00 00 01 7F 00 00 00 00 F7' = pad 0 red RGB")
        r.addWidget(self.raw, 1)
        sb = QPushButton("Send")
        sb.clicked.connect(self._send_raw)
        r.addWidget(sb)
        right.addWidget(box3)
        right.addStretch(1)
        lay.addLayout(right, 1)
        self._update_info()

    # ------------------------------------------------------------------ #
    def _run(self, fn) -> None:
        if not self.take.isChecked():
            self.take.setChecked(True)
        fn()

    def _pick(self, i: int) -> None:
        self.color = i
        self._update_info()

    def _update_info(self) -> None:
        r, g, b = apc.PALETTE[self.color]
        ch = self.mode.currentIndex()
        self.info.setText(
            f"Colour <b>{self.color}</b> (0x{self.color:02X}) #{r:02X}{g:02X}{b:02X}<br>"
            f"Pad message: <code>{0x90 | ch:02X} &lt;pad&gt; {self.color:02X}</code> "
            f"(Note On, MIDI ch {ch + 1})")

    def _target(self) -> Optional[str]:
        c = self.selected()
        return c if c and apc.is_button(c) else None

    def _send_palette(self) -> None:
        c = self._target()
        if c and apc.is_rgb(c):
            self._run(lambda: self.device.set_led(c, LedState(self.color, self.mode.currentIndex()),
                                                  force=True))

    def _pick_rgb(self) -> None:
        from PySide6.QtGui import QColor
        col = QColorDialog.getColor(QColor(*self.rgb), self, "Pad RGB colour")
        if col.isValid():
            self.rgb = (col.red(), col.green(), col.blue())
            self.rgb_btn.setStyleSheet(f"background-color: rgb{self.rgb};")

    def _send_rgb(self) -> None:
        c = self._target()
        if c and apc.is_rgb(c):
            self._run(lambda: self.device.set_led(c, LedState(rgb=self.rgb), force=True))

    def _send_single(self, v: int) -> None:
        c = self._target()
        if c and not apc.is_rgb(c):
            self._run(lambda: self.device.set_led(c, LedState(v, 0), force=True))

    def _palette_page(self, offset: int) -> None:
        for n in range(64):
            self.device.set_led(f"pad:{n}", LedState(offset + n, apc.MODE_SOLID_100), force=True)

    def _modes_demo(self) -> None:
        # bottom row solid 100%, then pulses, then blinks, using palette pick
        modes = [6, 3, 0, 7, 9, 10, 11, 15]
        for row in range(8):
            for col in range(8):
                self.device.set_led(apc.pad_id(row, col),
                                    LedState(self.color, modes[row]), force=True)

    def _rainbow(self) -> None:
        import colorsys
        for n in range(64):
            row, col = divmod(n, 8)
            h = (col / 8.0 + row / 64.0) % 1.0
            r, g, b = colorsys.hsv_to_rgb(h, 1.0, 1.0 - row * 0.08)
            self.device.set_led(f"pad:{n}", LedState(rgb=(int(r * 255), int(g * 255),
                                                          int(b * 255))), force=True)

    def _buttons_blink(self) -> None:
        for i in range(8):
            self.device.set_led(f"track:{i}", LedState(apc.SINGLE_BLINK, 0), force=True)
            self.device.set_led(f"scene:{i}", LedState(apc.SINGLE_BLINK, 0), force=True)

    def _send_raw(self) -> None:
        try:
            data = [int(x, 16) for x in self.raw.text().replace(",", " ").split()]
        except ValueError:
            self.info.setText("<span style='color:#f66'>Invalid hex</span>")
            return
        self._run(lambda: self.device.send_raw(data))
