"""Left panel: draggable list of grandMA3 controls + executor numbering."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit,
                               QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import apc
from ..model import CATALOG, CATALOG_BY_ID, CatalogItem
from .apc_widget import MIME_CATALOG

ROLE_ID = Qt.UserRole + 1


class CatalogTree(QTreeWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragOnly)
        groups: dict[str, QTreeWidgetItem] = {}
        for item in CATALOG:
            g = groups.get(item.group)
            if g is None:
                g = QTreeWidgetItem([item.group])
                g.setFlags(Qt.ItemIsEnabled)
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                self.addTopLevelItem(g)
                groups[item.group] = g
            icon = "▮" if item.kind == "fader" else "■"
            ti = QTreeWidgetItem([f"{icon}  {item.name.replace('{page}', 'N')}"])
            ti.setData(0, ROLE_ID, item.id)
            ti.setToolTip(0, self._tooltip(item))
            ti.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            g.addChild(ti)
        self.expandAll()

    @staticmethod
    def _tooltip(item: CatalogItem) -> str:
        lines = [f"<b>{item.name}</b> ({item.kind})"]
        if item.help:
            lines.append(item.help)
        if item.press:
            lines.append(f"press: <code>{item.press}</code>")
        if item.release:
            lines.append(f"release: <code>{item.release}</code>")
        if item.value:
            lines.append(f"value: <code>{item.value}</code>")
        if item.osc_key:
            lines.append("sends OSC Key press/release")
        if item.osc_fader:
            lines.append("sends OSC executor fader")
        return "<br>".join(lines)

    def startDrag(self, actions) -> None:
        it = self.currentItem()
        if it is None or not it.data(0, ROLE_ID):
            return
        md = QMimeData()
        md.setData(MIME_CATALOG, it.data(0, ROLE_ID).encode())
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.exec(Qt.CopyAction)

    def filter(self, text: str) -> None:
        text = text.lower()
        for gi in range(self.topLevelItemCount()):
            g = self.topLevelItem(gi)
            any_vis = False
            for ci in range(g.childCount()):
                c = g.child(ci)
                vis = not text or text in c.text(0).lower() or text in g.text(0).lower()
                c.setHidden(not vis)
                any_vis |= vis
            g.setHidden(not any_vis)


class CatalogPanel(QWidget):
    """Catalogue + 'which executor does a dropped control target' settings."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(QLabel("<b>grandMA3 controls</b> — drag onto the APC"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        lay.addWidget(self.search)
        self.tree = CatalogTree()
        lay.addWidget(self.tree, 1)
        self.search.textChanged.connect(self.tree.filter)

        box = QGroupBox("Executor for dropped controls")
        f = QFormLayout(box)
        self.mode = QComboBox()
        self.mode.addItems(["By column (base + column)", "Fixed number", "Auto-increment"])
        self.page = QSpinBox()
        self.page.setRange(0, 9999)
        self.page.setSpecialValueText("Current page")
        self.base = QSpinBox()
        self.base.setRange(1, 9999)
        self.base.setValue(201)
        f.addRow("Mode", self.mode)
        f.addRow("Page", self.page)
        f.addRow("Exec / base", self.base)
        hint = QLabel("Column mode: pad column 1 → base, column 2 → base+1 … "
                      "Fader 1-8 likewise.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 10px;")
        f.addRow(hint)
        lay.addWidget(box)

    def resolve(self, catalog_id: str, control: str) -> tuple[int, int]:
        """(page, exec) for a control dropped onto `control`."""
        page = self.page.value()
        base = self.base.value()
        mode = self.mode.currentIndex()
        if mode == 0:
            kind, _, idx = control.partition(":")
            col = 0
            if kind == "pad":
                col = int(idx) % 8
            elif kind in ("track", "fader"):
                col = min(int(idx), 7)
            elif kind == "scene":
                col = int(idx)
            return page, base + col
        if mode == 2:
            ex = base
            self.base.setValue(base + 1)
            return page, ex
        return page, base

    @staticmethod
    def accepts(catalog_id: str, control: str) -> bool:
        item = CATALOG_BY_ID.get(catalog_id)
        if item is None:
            return False
        is_fader = control.startswith("fader:")
        if item.kind == "fader":
            return is_fader
        if item.kind == "button":
            return apc.is_button(control)
        return True
