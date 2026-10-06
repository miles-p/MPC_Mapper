"""Main application window."""
from __future__ import annotations

import copy
import os
import sys
from typing import Optional

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QSplitter, QTabWidget, QTextBrowser,
                               QToolBar, QVBoxLayout, QWidget)

from .. import apc
from ..engine import Engine
from ..model import CATALOG_BY_ID, Mapping, assignment_from_catalog, demo_mapping
from .apc_widget import APCWidget
from .catalog import CatalogPanel
from .inspector import Inspector
from .led_lab import LedLab
from .widgets import mono_font

MA3_SETUP_HTML = """
<h3>grandMA3 setup (one time)</h3>
<ol>
<li><b>Menu → In &amp; Out → OSC</b>. Turn on <b>Enable Input</b> and <b>Enable Output</b>.</li>
<li>Line 1 — <i>commands from this app</i>: Destination IP = this computer,
    Port = <b>MA3 port</b> (default 8000), Prefix = <b>gma3</b> (same as the app),
    <b>Receive</b> = Yes, <b>Receive Command</b> = Yes. Fader Range 100.</li>
<li>Line 2 — <i>feedback to this app</i>: Destination IP = this computer,
    Port = <b>Listen port</b> (default 8001), <b>Send</b> = Yes and
    <b>Send Command</b> = Yes, Receive off.<br>
    MA3 uses one port per line for both directions, which is why two lines are
    needed when the app and MA3 run on the same machine.</li>
<li>Import the plugin <code>ma3_plugin/APC_Feedback.xml</code> (+ .lua) into the
    Plugins pool and run it once (or use <i>MA3 → Start feedback plugin</i>).
    It reports executor on/off, fader level and appearance colour, and the
    current page, via <code>SendOSC 2 …</code>. Edit <code>OSC_LINE</code> at the top
    of the Lua file if your feedback line is not line 2.</li>
<li>Press <i>MA3 → Send watch list</i> (done automatically on connect) so the
    plugin knows which executors to report.</li>
</ol>
<p>Status bar shows <b>MA3 ●</b> green when feedback packets arrive.</p>
<h3>APC tips</h3>
<ul>
<li>Shift + Scene 6/7 on the hardware switches the APC into Drum/Note mode — the pads
    then stop sending on the control port. Press Shift + Scene 5 (Session) to get back.</li>
<li>Pad colours: <i>palette</i> (128 fixed colours, can pulse/blink) or <i>true RGB</i>
    via SysEx (static only). "Use MA3 appearance colour" uses true RGB when solid and
    falls back to the nearest palette colour when an animated mode is chosen.</li>
</ul>
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MPC Mapper — APC mini mk2 → grandMA3")
        self.qs = QSettings("MPCMapper", "MPCMapper")
        self.path: Optional[str] = None
        self.dirty = False

        mapping = self._initial_mapping()
        self.mapping = mapping
        self.engine = Engine(mapping, self)

        # ---------------- central widgets ----------------
        self.catalog = CatalogPanel()
        self.diagram = APCWidget(mapping)
        self.diagram.accepts = self.catalog.accepts
        self.inspector = Inspector(mapping)
        self.inspector.setMinimumWidth(330)

        top = QSplitter(Qt.Horizontal)
        top.addWidget(self.catalog)
        top.addWidget(self.diagram)
        top.addWidget(self.inspector)
        top.setStretchFactor(1, 1)
        top.setSizes([260, 760, 360])

        self.tabs = QTabWidget()
        self.lab = LedLab(self.engine.apc, lambda: self.diagram.selected_control)
        self.tabs.addTab(self.lab, "LED Lab")
        self.tabs.addTab(self._make_log(), "Log")
        help_ = QTextBrowser()
        help_.setHtml(MA3_SETUP_HTML)
        self.tabs.addTab(help_, "MA3 setup")

        vs = QSplitter(Qt.Vertical)
        vs.addWidget(top)
        vs.addWidget(self.tabs)
        vs.setStretchFactor(0, 1)
        vs.setSizes([640, 260])
        self.setCentralWidget(vs)

        self._make_toolbar()
        self._make_menu()
        self._make_status()

        # ---------------- wiring ----------------
        self.engine.led_changed.connect(self.diagram.set_led)
        self.engine.control_event.connect(self.diagram.hw_event)
        self.engine.fader_sync.connect(self._fader_sync)
        self.engine.log.connect(self._log)
        self.engine.status_changed.connect(self._update_status)
        self.engine.page_changed.connect(lambda _p: self._update_status())
        self.diagram.selected.connect(self.inspector.set_control)
        self.diagram.catalog_dropped.connect(self._on_catalog_drop)
        self.diagram.control_moved.connect(self._on_move)
        self.diagram.simulate_button.connect(self.engine.handle_button)
        self.diagram.simulate_fader.connect(self.engine.handle_fader)
        self.diagram.clear_requested.connect(self._clear)
        self.inspector.changed.connect(self._on_inspector_change)
        self.inspector.cleared.connect(self._clear)
        self.lab.lab_mode_changed.connect(self.engine.set_lab_mode)

        self.engine.refresh_all_leds(force=True)
        QTimer.singleShot(0, self._autoconnect)

    # ------------------------------------------------------------------ #
    # setup helpers
    # ------------------------------------------------------------------ #
    def _initial_mapping(self) -> Mapping:
        last = self.qs.value("last_file", "")
        if last and os.path.exists(last):
            try:
                m = Mapping.load(last)
                self.path = last
                return m
            except Exception as e:
                print(f"MPC Mapper: could not load {last}: {e}")
        return demo_mapping()

    def _make_toolbar(self) -> None:
        tb = QToolBar("Connection")
        tb.setMovable(False)
        self.addToolBar(tb)
        s = self.mapping.settings

        tb.addWidget(QLabel(" APC in "))
        self.midi_in = QComboBox()
        self.midi_in.setMinimumWidth(180)
        tb.addWidget(self.midi_in)
        tb.addWidget(QLabel(" out "))
        self.midi_out = QComboBox()
        self.midi_out.setMinimumWidth(180)
        tb.addWidget(self.midi_out)
        rb = QPushButton("↻")
        rb.setToolTip("Rescan MIDI ports")
        rb.clicked.connect(self._scan_ports)
        tb.addWidget(rb)
        self.midi_btn = QPushButton("Connect APC")
        self.midi_btn.clicked.connect(self._toggle_midi)
        tb.addWidget(self.midi_btn)
        tb.addSeparator()

        tb.addWidget(QLabel(" MA3 IP "))
        self.host = QLineEdit(s.ma3_host)
        self.host.setFixedWidth(120)
        tb.addWidget(self.host)
        tb.addWidget(QLabel(" port "))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(s.ma3_port)
        tb.addWidget(self.port)
        tb.addWidget(QLabel(" listen "))
        self.listen = QSpinBox()
        self.listen.setRange(1, 65535)
        self.listen.setValue(s.listen_port)
        tb.addWidget(self.listen)
        tb.addWidget(QLabel(" prefix "))
        self.prefix = QLineEdit(s.osc_prefix)
        self.prefix.setFixedWidth(60)
        tb.addWidget(self.prefix)
        self.ma3_btn = QPushButton("Connect MA3")
        self.ma3_btn.clicked.connect(self._connect_ma3)
        tb.addWidget(self.ma3_btn)
        self._scan_ports()

    def _make_menu(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&File")
        for text, key, fn in [
            ("New (empty)", QKeySequence.New, self._new),
            ("Load demo layout", None, self._demo),
            ("Open…", QKeySequence.Open, self._open),
            ("Save", QKeySequence.Save, self._save),
            ("Save as…", QKeySequence.SaveAs, self._save_as),
            (None, None, None),
            ("Quit", QKeySequence.Quit, self.close),
        ]:
            if text is None:
                f.addSeparator()
                continue
            a = QAction(text, self)
            if key is not None:
                a.setShortcut(key)
            a.triggered.connect(fn)
            f.addAction(a)
        m = mb.addMenu("&MA3")
        for text, fn in [
            ("Send watch list", self.engine.sync_watch_list),
            ("Start feedback plugin", lambda: self.engine.ma3.command('Plugin "APC_Feedback"')),
            ("Send command…", self._send_cmd),
        ]:
            a = QAction(text, self)
            a.triggered.connect(fn)
            m.addAction(a)
        d = mb.addMenu("&Device")
        a = QAction("Re-send all LEDs", self)
        a.triggered.connect(lambda: self.engine.refresh_all_leds(force=True))
        d.addAction(a)
        a = QAction("Sync fader positions (intro SysEx)", self)
        a.triggered.connect(self.engine.apc.send_intro)
        d.addAction(a)

    def _make_status(self) -> None:
        sb = self.statusBar()
        self.st_midi = QLabel()
        self.st_ma3 = QLabel()
        self.st_page = QLabel()
        for w in (self.st_midi, self.st_ma3, self.st_page):
            sb.addPermanentWidget(w)
        self._update_status()

    def _make_log(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 2, 2, 2)
        h = QHBoxLayout()
        self.log_midi = QCheckBox("MIDI")
        self.log_midi.setChecked(False)
        self.log_osc = QCheckBox("OSC")
        self.log_osc.setChecked(True)
        clear = QPushButton("Clear")
        h.addWidget(self.log_midi)
        h.addWidget(self.log_osc)
        h.addStretch(1)
        h.addWidget(clear)
        v.addLayout(h)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setFont(mono_font(9))
        clear.clicked.connect(self.log_view.clear)
        v.addWidget(self.log_view)
        return w

    # ------------------------------------------------------------------ #
    # connection
    # ------------------------------------------------------------------ #
    def _scan_ports(self) -> None:
        ins, outs = apc.list_ports()
        s = self.mapping.settings
        for combo, names, saved in ((self.midi_in, ins, s.midi_in),
                                    (self.midi_out, outs, s.midi_out)):
            combo.clear()
            combo.addItem("(none)", "")
            for n in names:
                combo.addItem(n, n)
            pick = apc.match_port(saved, names) or apc.guess_port(names)
            if pick:
                combo.setCurrentIndex(combo.findData(pick))

    def _toggle_midi(self) -> None:
        if self.engine.apc.connected:
            self.engine.disconnect_midi()
        else:
            try:
                self.engine.connect_midi(self.midi_in.currentData(), self.midi_out.currentData())
            except Exception as e:
                hint = ("\n\nOn Windows a MIDI port can only be used by one program at a "
                        "time. Close other software using the APC (DAW, MIDI monitor, "
                        "grandMA3 onPC MIDI input) and try again."
                        if sys.platform == "win32" else "")
                QMessageBox.warning(self, "MIDI", f"Could not open MIDI ports:\n{e}{hint}")
        self._update_status()

    def _connect_ma3(self) -> None:
        s = self.mapping.settings
        s.ma3_host = self.host.text().strip()
        s.ma3_port = self.port.value()
        s.listen_port = self.listen.value()
        s.osc_prefix = self.prefix.text().strip().strip("/")
        try:
            self.engine.connect_ma3()
        except OSError as e:
            QMessageBox.warning(self, "OSC", f"Could not open listen port {s.listen_port}:\n{e}")
            return
        self.engine.sync_watch_list()
        self.ma3_btn.setText("Reconnect MA3")
        self._update_status()

    def _autoconnect(self) -> None:
        if self.midi_in.currentData() or self.midi_out.currentData():
            try:
                self.engine.connect_midi(self.midi_in.currentData(), self.midi_out.currentData())
            except Exception as e:
                self._log("midi", "err", f"auto-connect failed: {e}")
        self._connect_ma3()

    def _update_status(self) -> None:
        a = self.engine.apc
        if a.connected:
            self.st_midi.setText("<span style='color:#4c4'>●</span> APC connected")
            self.midi_btn.setText("Disconnect APC")
        else:
            self.st_midi.setText("<span style='color:#c44'>●</span> APC not connected "
                                 "(Shift+click the drawing to simulate)")
            self.midi_btn.setText("Connect APC")
        m = self.engine.ma3
        if m.client is None:
            self.st_ma3.setText("<span style='color:#c44'>●</span> MA3 off")
        elif m.plugin_alive:
            self.st_ma3.setText(f"<span style='color:#4c4'>●</span> MA3 feedback "
                                f"{('v' + m.plugin_version) if m.plugin_version else ''}")
        else:
            self.st_ma3.setText(f"<span style='color:#ca4'>●</span> MA3 → {m.host}:{m.port} "
                                f"(no feedback on :{m.listen_port})")
        self.st_page.setText(f"  Page {m.current_page}  ")

    def _fader_sync(self, values: list) -> None:
        for i, v in enumerate(values):
            self.diagram.hw_event(f"fader:{i}", v)

    # ------------------------------------------------------------------ #
    # editing
    # ------------------------------------------------------------------ #
    def _changed(self, control: Optional[str] = None, replaced: bool = False) -> None:
        self.dirty = True
        self._title()
        if control:
            if replaced:
                self.engine.assignment_replaced(control)
            else:
                self.engine.update_led(control)
        self.diagram.update()

    def _on_catalog_drop(self, catalog_id: str, control: str) -> None:
        item = CATALOG_BY_ID[catalog_id]
        page, ex = self.catalog.resolve(catalog_id, control)
        self.mapping.assignments[control] = assignment_from_catalog(item, control, page, ex)
        self._changed(control, replaced=True)
        self.engine.sync_watch_list()
        self.inspector.set_control(control)

    def _on_move(self, src: str, dst: str, copy_: bool) -> None:
        a = self.mapping.assignments.get(src)
        if a is None:
            return
        new = copy.deepcopy(a)
        if apc.is_rgb(src) != apc.is_rgb(dst):  # pad <-> single colour button
            new.led.off_color, new.led.on_color = (
                (apc.SINGLE_OFF, apc.SINGLE_ON) if not apc.is_rgb(dst) else (1, 21))
            new.led.off_mode = new.led.on_mode = apc.MODE_SOLID_100
            new.led.use_ma3_color = False
        self.mapping.assignments[dst] = new
        if not copy_:
            del self.mapping.assignments[src]
            self.engine.assignment_replaced(src)
        self._changed(dst, replaced=True)
        self.inspector.set_control(dst)

    def _clear(self, control: str) -> None:
        if self.mapping.assignments.pop(control, None) is not None:
            self._changed(control, replaced=True)
            self.inspector.set_control(control)
            self.engine.sync_watch_list()

    def _on_inspector_change(self, control: str) -> None:
        self._changed(control)
        self._watch_debounce()

    def _watch_debounce(self) -> None:
        if not hasattr(self, "_wd"):
            self._wd = QTimer(self)
            self._wd.setSingleShot(True)
            self._wd.timeout.connect(self.engine.sync_watch_list)
        self._wd.start(800)

    def _send_cmd(self) -> None:
        text, ok = QInputDialog.getText(self, "Send command", "grandMA3 command line:")
        if ok and text:
            self.engine.ma3.command(text)

    def _log(self, src: str, direction: str, text: str) -> None:
        if src == "midi" and not self.log_midi.isChecked():
            return
        if src == "osc" and not self.log_osc.isChecked():
            return
        arrow = {"in": "←", "out": "→"}.get(direction, "!")
        self.log_view.appendPlainText(f"{src.upper():4} {arrow} {text}")

    # ------------------------------------------------------------------ #
    # files
    # ------------------------------------------------------------------ #
    def _title(self) -> None:
        name = os.path.basename(self.path) if self.path else "untitled"
        self.setWindowTitle(f"MPC Mapper — {name}{' *' if self.dirty else ''}")

    def _replace_mapping(self, m: Mapping, path: Optional[str]) -> None:
        # New/demo keep the live connection settings; a loaded file brings its own.
        # The Mapping object itself is shared with engine/widgets, so mutate it.
        self.mapping.assignments = m.assignments
        if path is not None:
            old = self.mapping.settings
            self.mapping.settings = s = m.settings
            self.host.setText(s.ma3_host)
            self.port.setValue(s.ma3_port)
            self.listen.setValue(s.listen_port)
            self.prefix.setText(s.osc_prefix)
            self._scan_ports()
            if (old.ma3_host, old.ma3_port, old.listen_port, old.osc_prefix) != (
                    s.ma3_host, s.ma3_port, s.listen_port, s.osc_prefix):
                self._connect_ma3()
            if (old.midi_in, old.midi_out) != (s.midi_in, s.midi_out) and (s.midi_in or s.midi_out):
                try:
                    self.engine.connect_midi(self.midi_in.currentData(), self.midi_out.currentData())
                except Exception as e:
                    self._log("midi", "err", f"connect failed: {e}")
        self.path = path
        self.dirty = False
        self.engine.latched.clear()
        self.engine.mapping_changed()
        self.inspector.set_control(self.diagram.selected_control)
        self.diagram.update()
        self._title()

    def _maybe_save(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Save changes to the mapping?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            return self._save()
        return True

    def _new(self) -> None:
        if self._maybe_save():
            self._replace_mapping(Mapping(), None)

    def _demo(self) -> None:
        if self._maybe_save():
            self._replace_mapping(demo_mapping(), None)
            self.dirty = True
            self._title()

    def _open(self) -> None:
        if not self._maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open mapping", self._dir(), "Mapping (*.json)")
        if path:
            try:
                self._replace_mapping(Mapping.load(path), path)
                self.qs.setValue("last_file", path)
            except Exception as e:
                QMessageBox.warning(self, "Open", f"Could not load {path}:\n{e}")

    def _dir(self) -> str:
        here = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "mappings")
        return os.path.dirname(self.path) if self.path else here

    def _save(self) -> bool:
        if not self.path:
            return self._save_as()
        self._sync_settings()
        try:
            self.mapping.save(self.path)
        except OSError as e:
            QMessageBox.warning(self, "Save", f"Could not save {self.path}:\n{e}")
            return False
        self.qs.setValue("last_file", self.path)
        self.dirty = False
        self._title()
        return True

    def _save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save mapping",
                                              os.path.join(self._dir(), "mapping.json"),
                                              "Mapping (*.json)")
        if not path:
            return False
        if not path.endswith(".json"):
            path += ".json"
        self.path = path
        return self._save()

    def _sync_settings(self) -> None:
        s = self.mapping.settings
        s.ma3_host = self.host.text().strip()
        s.ma3_port = self.port.value()
        s.listen_port = self.listen.value()
        s.osc_prefix = self.prefix.text().strip().strip("/")
        s.midi_in = self.midi_in.currentData() or ""
        s.midi_out = self.midi_out.currentData() or ""

    def closeEvent(self, e) -> None:
        if not self._maybe_save():
            e.ignore()
            return
        self.engine.shutdown()
        e.accept()
