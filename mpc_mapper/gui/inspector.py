"""Right panel: edit the assignment + LED feedback of the selected control."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import apc
from ..model import CATALOG_BY_ID, FEEDBACK_SOURCES, Assignment, Mapping
from .widgets import PaletteButton


class Inspector(QWidget):
    changed = Signal(str)            # control whose assignment changed
    cleared = Signal(str)

    def __init__(self, mapping: Mapping, parent=None) -> None:
        super().__init__(parent)
        self.mapping = mapping
        self.control: Optional[str] = None
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.title = QLabel("<b>Select a control</b>")
        lay.addWidget(self.title)
        self.subtitle = QLabel("")
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet("color: #888;")
        lay.addWidget(self.subtitle)

        # ---- action
        self.action_box = QGroupBox("grandMA3 action")
        f = QFormLayout(self.action_box)
        self.name = QLineEdit()
        f.addRow("Label", self.name)
        row = QHBoxLayout()
        self.page = QSpinBox()
        self.page.setRange(0, 9999)
        self.page.setSpecialValueText("Current")
        self.exec = QSpinBox()
        self.exec.setRange(1, 9999)
        row.addWidget(QLabel("Page"))
        row.addWidget(self.page)
        row.addWidget(QLabel("Exec"))
        row.addWidget(self.exec)
        f.addRow(row)
        self.press = QLineEdit()
        self.release = QLineEdit()
        self.value = QLineEdit()
        self.osc_key = QCheckBox("Send as OSC executor key (/PageN/KeyX)")
        self.osc_fader = QCheckBox("Send as OSC executor fader (/PageN/FaderX)")
        f.addRow("Press cmd", self.press)
        f.addRow("Release cmd", self.release)
        f.addRow("Value cmd", self.value)
        f.addRow(self.osc_key)
        f.addRow(self.osc_fader)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("color: #7fbf7f; font-family: monospace; font-size: 10px;")
        f.addRow(self.preview)
        help_ = QLabel("Placeholders: {target} {page} {exec} {value}")
        help_.setStyleSheet("color: #888; font-size: 10px;")
        f.addRow(help_)
        lay.addWidget(self.action_box)

        # ---- LED
        self.led_box = QGroupBox("LED feedback")
        g = QFormLayout(self.led_box)
        self.source = QComboBox()
        for k, v in FEEDBACK_SOURCES.items():
            self.source.addItem(v, k)
        g.addRow("Lit when", self.source)
        # RGB pads
        self.off_color = PaletteButton()
        self.on_color = PaletteButton()
        self.off_mode = QComboBox()
        self.on_mode = QComboBox()
        for cb in (self.off_mode, self.on_mode):
            cb.addItems(apc.LED_MODES)
        r1 = QHBoxLayout()
        r1.addWidget(self.off_color)
        r1.addWidget(self.off_mode, 1)
        r2 = QHBoxLayout()
        r2.addWidget(self.on_color)
        r2.addWidget(self.on_mode, 1)
        self.off_row_label, self.on_row_label = QLabel("Off look"), QLabel("On look")
        g.addRow(self.off_row_label, r1)
        g.addRow(self.on_row_label, r2)
        self.use_ma3 = QCheckBox("Use MA3 appearance colour (true RGB)")
        self.dim = QDoubleSpinBox()
        self.dim.setRange(0.0, 1.0)
        self.dim.setSingleStep(0.05)
        g.addRow(self.use_ma3)
        g.addRow("Off brightness", self.dim)
        # single colour buttons
        self.off_single = QComboBox()
        self.on_single = QComboBox()
        for cb in (self.off_single, self.on_single):
            cb.addItems(apc.SINGLE_STATES)
        self.off_single_label, self.on_single_label = QLabel("Off state"), QLabel("On state")
        g.addRow(self.off_single_label, self.off_single)
        g.addRow(self.on_single_label, self.on_single)
        lay.addWidget(self.led_box)

        btns = QHBoxLayout()
        self.reset_btn = QPushButton("Reset to catalogue defaults")
        self.clear_btn = QPushButton("Clear")
        btns.addWidget(self.reset_btn)
        btns.addWidget(self.clear_btn)
        lay.addLayout(btns)
        lay.addStretch(1)

        for w in (self.name, self.press, self.release, self.value):
            w.textEdited.connect(self._commit)
        for w in (self.page, self.exec):
            w.valueChanged.connect(self._commit)
        for w in (self.osc_key, self.osc_fader, self.use_ma3):
            w.toggled.connect(self._commit)
        for w in (self.source, self.off_mode, self.on_mode, self.off_single, self.on_single):
            w.currentIndexChanged.connect(self._commit)
        self.dim.valueChanged.connect(self._commit)
        self.off_color.changed.connect(self._commit)
        self.on_color.changed.connect(self._commit)
        self.clear_btn.clicked.connect(lambda: self.control and self.cleared.emit(self.control))
        self.reset_btn.clicked.connect(self._reset)
        self.set_control(None)

    # ------------------------------------------------------------------ #
    def set_control(self, control: Optional[str]) -> None:
        self.control = control
        a = self.mapping.assignments.get(control) if control else None
        if control is None:
            self.title.setText("<b>Select a control</b>")
            self.subtitle.setText("Click a pad, button or fader on the APC drawing.")
        else:
            self.title.setText(f"<b>{apc.control_label(control)}</b>  <span style='color:#888'>"
                               f"({control})</span>")
            if a is None:
                self.subtitle.setText("Unassigned — drag a grandMA3 control here.")
            else:
                cat = CATALOG_BY_ID.get(a.catalog_id)
                self.subtitle.setText(f"Type: {cat.group + ' / ' + cat.name if cat else 'Custom'}")
        self.action_box.setVisible(a is not None)
        is_btn = control is not None and apc.is_button(control)
        self.led_box.setVisible(a is not None and is_btn)
        self.reset_btn.setVisible(a is not None)
        self.clear_btn.setVisible(a is not None)
        if a is None:
            return
        self._loading = True
        try:
            self.name.setText(a.name)
            self.page.setValue(a.page)
            self.exec.setValue(a.exec)
            self.press.setText(a.press_cmd)
            self.release.setText(a.release_cmd)
            self.value.setText(a.value_cmd)
            self.osc_key.setChecked(a.osc_key)
            self.osc_fader.setChecked(a.osc_fader)
            fader = control.startswith("fader:")
            for w in (self.press, self.release, self.osc_key):
                w.setEnabled(not fader)
            for w in (self.value, self.osc_fader):
                w.setEnabled(fader)
            led = a.led
            self.source.setCurrentIndex(max(0, self.source.findData(led.source)))
            rgb = apc.is_rgb(control)
            for w in (self.off_color, self.on_color, self.off_mode, self.on_mode, self.use_ma3,
                      self.dim, self.off_row_label, self.on_row_label):
                w.setVisible(rgb)
            for w in (self.off_single, self.on_single, self.off_single_label, self.on_single_label):
                w.setVisible(not rgb)
            if rgb:
                self.off_color.set_index(led.off_color)
                self.on_color.set_index(led.on_color)
                self.off_mode.setCurrentIndex(led.off_mode)
                self.on_mode.setCurrentIndex(led.on_mode)
                self.use_ma3.setChecked(led.use_ma3_color)
                self.dim.setValue(led.ma3_dim)
            else:
                self.off_single.setCurrentIndex(min(2, led.off_color))
                self.on_single.setCurrentIndex(min(2, led.on_color))
            self._update_preview(a)
        finally:
            self._loading = False

    def _update_preview(self, a: Assignment) -> None:
        page = 1
        lines = []
        if self.control and self.control.startswith("fader:"):
            if a.osc_fader:
                lines.append(f"OSC /PageN/Fader{a.exec} ← 0..100")
            elif a.value_cmd:
                lines.append(a.render(a.value_cmd, page, 50))
        else:
            if a.osc_key:
                lines.append(f"OSC /PageN/Key{a.exec} 1 / 0")
            else:
                if a.press_cmd:
                    lines.append("▼ " + a.render(a.press_cmd, page))
                if a.release_cmd:
                    lines.append("▲ " + a.render(a.release_cmd, page))
        from html import escape
        self.preview.setText("<br>".join(escape(l) for l in lines) or "(nothing sent)")

    def _commit(self, *_):
        if self._loading or not self.control:
            return
        a = self.mapping.assignments.get(self.control)
        if a is None:
            return
        a.name = self.name.text()
        a.page = self.page.value()
        a.exec = self.exec.value()
        a.press_cmd = self.press.text()
        a.release_cmd = self.release.text()
        a.value_cmd = self.value.text()
        a.osc_key = self.osc_key.isChecked()
        a.osc_fader = self.osc_fader.isChecked()
        led = a.led
        led.source = self.source.currentData()
        if apc.is_rgb(self.control):
            led.off_color = self.off_color.index
            led.on_color = self.on_color.index
            led.off_mode = self.off_mode.currentIndex()
            led.on_mode = self.on_mode.currentIndex()
            led.use_ma3_color = self.use_ma3.isChecked()
            led.ma3_dim = self.dim.value()
        else:
            led.off_color = self.off_single.currentIndex()
            led.on_color = self.on_single.currentIndex()
        self._update_preview(a)
        self.changed.emit(self.control)

    def _reset(self) -> None:
        from ..model import assignment_from_catalog
        if not self.control:
            return
        a = self.mapping.assignments.get(self.control)
        cat = CATALOG_BY_ID.get(a.catalog_id) if a else None
        if cat is None:
            return
        self.mapping.assignments[self.control] = assignment_from_catalog(
            cat, self.control, a.page, a.exec)
        self.set_control(self.control)
        self.changed.emit(self.control)
