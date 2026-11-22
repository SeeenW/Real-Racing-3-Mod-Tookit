"""The Materials page: every row of ``materials.bin``, and who wears it.

The library is one flat record stream - 296 material blocks, then 186 shader
bindings - and a material *is* the first table's record block.  So the page can
do two things safely and nothing else: copy a block under a new name (the copy
keeps the application, cull, blend, stencil and flags that make it an instance of
its template) and delete a block this program added.  Both leave every other
offset where it was, because a new block is appended at the end of the material
table and a removed one is spliced out whole.  Editing a field inside a block is
not offered: the records have no length prefixes to resynchronise on, so a wrong
guess would change how a car looks in a way nobody can trace back.

The other reason the page exists: the Parts and Paints pickers only offer the 101
materials that have a livery slot, because a name without a slot cannot be
pointed at.  This page shows the other 195 as well, so it is clear *why* a name
you saw in the game files is not in those dropdowns - and copying one adds the
slot it needs.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLineEdit,
                               QMessageBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import edit as editlib
from .. import matmanager as matlib
from . import widgets as W
from .worker import Task

COLUMNS = ("Material", "Slot", "Application", "Flags", "Cars", "Writable")

#: Widths the header starts at; every one is draggable afterwards.
WIDTHS = (250, 60, 130, 250, 60, 80)


class MaterialsPage(QWidget):
    """The list on the left, the chosen row's innards on the right."""

    status = Signal(str)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.depot = ""
        self.root = ""
        self.editor = None
        self.rows = []
        self.summary_info = {}
        self._loaded_usage = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name, application or flag")
        self.search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.search, 1)
        self.only_writable = QCheckBox("Only the ones a car can point at")
        self.only_writable.setToolTip(
            "A material with no slot in liveryStringTable.bin.nct cannot be "
            "named by any car, so it never appears in the Parts or Paints "
            "dropdowns. This box hides those.")
        self.only_writable.toggled.connect(self._apply_filter)
        bar.addWidget(self.only_writable)
        self.only_used = QCheckBox("Only the ones in use")
        self.only_used.setToolTip("Hide materials no shipped car points at")
        self.only_used.toggled.connect(self._apply_filter)
        bar.addWidget(self.only_used)
        self.reload_btn = W.button("Reload", self.reload)
        bar.addWidget(self.reload_btn)
        lay.addLayout(bar)

        tools = QHBoxLayout()
        self.copy_btn = W.button(
            "Copy this one...", self.copy_material,
            tip="Add a new material that is a copy of the chosen row, with a "
                "name of its own and a livery slot so a car can wear it")
        self.copy_btn.setEnabled(False)
        tools.addWidget(self.copy_btn)
        self.remove_btn = W.button(
            "Delete this copy", self.remove_material,
            tip="Remove a material this program added. The game's own 296 are "
                "never removed.")
        self.remove_btn.setEnabled(False)
        tools.addWidget(self.remove_btn)
        tools.addStretch(1)
        lay.addLayout(tools)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setStretchLastSection(True)
        for column, width in enumerate(WIDTHS):
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self._picked)
        split.addWidget(self.table)

        side = QWidget()
        slay = QVBoxLayout(side)
        slay.setContentsMargins(0, 0, 0, 0)
        slay.setSpacing(6)
        self.facts = W.KeyValue()
        slay.addWidget(self.facts)
        self.flags = W.muted("")
        self.flags.setWordWrap(True)
        slay.addWidget(self.flags)
        self.shader = W.muted("")
        self.shader.setWordWrap(True)
        slay.addWidget(self.shader)
        slay.addWidget(W.muted(
            "Copying a material appends a block at the end of the material "
            "table, so every existing block stays where it was; deleting a copy "
            "splices that one block out. A field inside a block is not edited "
            "here - the records have no length prefixes, so one wrong byte would "
            "shift everything after it."))
        slay.addStretch(1)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)

        self.summary = W.muted("")
        lay.addWidget(self.summary)
        self.log = W.LogPane()
        self.log.setMaximumHeight(90)
        lay.addWidget(self.log)

    # ---- loading -------------------------------------------------------
    def load(self, depot: str) -> None:
        self.depot = depot or ""
        if not self.depot:
            self.rows = []
            self._fill()
            return
        self.summary.setText("Reading materials.bin...")
        self._task = Task(self._gather, parent=self)
        self._task.done.connect(self._loaded)
        self._task.fail.connect(self._failed)
        self._task.start()

    def reload(self) -> None:
        if self.depot:
            self.load(self.depot)

    def _gather(self):
        return matlib.catalogue(self.depot, with_usage=True)

    def _loaded(self, payload) -> None:
        self.rows = payload["materials"]
        self.summary_info = payload
        self._loaded_usage = True
        used = sum(1 for r in self.rows if r["cars"])
        self.summary.setText(
            f"{payload['total']} materials, {payload['writable']} of them with a "
            f"slot a car can point at, {used} in use, {payload['shaders']} shaders")
        self._fill()

    def _failed(self, text: str) -> None:
        self.summary.setText("Could not read materials.bin.")
        self.log.error(text[:2000])

    # ---- the table -----------------------------------------------------
    def _fill(self) -> None:
        chosen = self._picked_name()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for row in self._shown():
            r = self.table.rowCount()
            self.table.insertRow(r)
            name = QTableWidgetItem(row["name"])
            name.setData(Qt.UserRole, row["name"])
            if row["paint"]:
                font = name.font()
                font.setBold(True)
                name.setFont(font)
            self.table.setItem(r, 0, name)
            slot = QTableWidgetItem()
            if row["slot"] is None:
                slot.setText("-")
                slot.setToolTip("No livery slot, so no car can name it")
            else:
                slot.setData(Qt.DisplayRole, int(row["slot"]))
            slot.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 1, slot)
            application = QTableWidgetItem(row["application"])
            if row["applicationText"]:
                application.setToolTip(row["applicationText"])
            self.table.setItem(r, 2, application)
            flags = QTableWidgetItem(", ".join(row["flags"]))
            flags.setToolTip(", ".join(row["flags"]) or "(none)")
            self.table.setItem(r, 3, flags)
            cars = QTableWidgetItem()
            cars.setData(Qt.DisplayRole, int(row["cars"]))
            cars.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 4, cars)
            self.table.setItem(r, 5, QTableWidgetItem(
                "yes" if row["writable"] else "-"))
        self.table.setSortingEnabled(True)
        if chosen:
            self.select_name(chosen)
        else:
            self._picked()

    def _shown(self) -> list:
        text = self.search.text().strip().lower()
        only_slot = self.only_writable.isChecked()
        only_used = self.only_used.isChecked()
        out = []
        for row in self.rows:
            if only_slot and not row["writable"]:
                continue
            if only_used and not row["cars"]:
                continue
            if text:
                hay = " ".join((row["name"], row["application"],
                                row["applicationText"],
                                " ".join(row["flags"]))).lower()
                if text not in hay:
                    continue
            out.append(row)
        return out

    def _apply_filter(self) -> None:
        self._fill()

    def _picked_name(self) -> str:
        item = self.table.currentItem()
        if item is None:
            return ""
        first = self.table.item(item.row(), 0)
        return first.data(Qt.UserRole) if first is not None else ""

    def select_name(self, name: str) -> None:
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item is not None and item.data(Qt.UserRole) == name:
                self.table.selectRow(r)
                return

    def _row_of(self, name: str):
        for row in self.rows:
            if row["name"] == name:
                return row
        return None

    def _picked(self) -> None:
        name = self._picked_name()
        row = self._row_of(name)
        if row is None:
            self.facts.clear()
            self.flags.setText("")
            self.shader.setText("")
            return
        rgba = tuple(row["rgba"])
        self.facts.update_all({
            "Material": row["name"],
            "Template": row["template"] or "(itself)",
            "Application": row["applicationText"] or row["application"] or "(none)",
            "Blend": row["blend"] or "(default)",
            "Cull": row["cull"] or "(default)",
            "Colour": "%d, %d, %d, %d" % rgba[:4],
            "Slot": row["slot"] if row["slot"] is not None else "(none - cannot be named)",
            "Cars using it": row["cars"],
            "Shader": row["shader"] or "(no binding of its own)",
        })
        self.flags.setText("Flags: " + (", ".join(row["flags"]) or "(none)"))
        self._describe(row["name"])
        ours = self._is_ours(name)
        self.copy_btn.setEnabled(bool(self.editor is not None or self.root))
        self.remove_btn.setEnabled(bool(ours and (self.editor is not None
                                                  or self.root)))
        self.remove_btn.setToolTip(
            f"Remove {name} and its livery slot" if ours else
            f"{name} is one of the game's own materials - it is never removed")

    def _is_ours(self, name: str) -> bool:
        """True when this material is one a mod added, not the game's own.

        Asking the row itself would be wrong, because a clone is indistinguishable
        from a shipped material once it is in the table.  A working copy answered
        by comparing with the install it came from; edits land in the install now,
        so the list of names this program cloned is what answers - the same record
        :func:`rrmod.edit.remove_material` uses, so the button and the refusal
        never disagree.
        """
        if not self.root:
            return False
        try:
            from .. import publish as publishlib

            recorded = set(publishlib.mine(self.root))
            if recorded:
                return name in recorded
        except Exception:                            # noqa: BLE001
            return False
        try:
            from rr3lib import gamematerial as gamelib

            install = editlib._install_of(self.root)
            if not install or os.path.abspath(install) == os.path.abspath(self.root):
                return False
            src = os.path.join(install, ".depot",
                               *gamelib.MATERIALS_BIN.split("/"))
            if not os.path.isfile(src):
                return False
            theirs = {n for _a, _b, n
                      in gamelib.block_spans(gamelib.load_records(src)) if n}
        except Exception:                            # noqa: BLE001
            return False
        return name not in theirs

    def _prepare(self) -> str:
        """Mirror what a material edit needs and return the working copy root."""
        if self.editor is None:
            return self.root
        self.editor.for_materials()
        self.root = self.editor.root
        return self.root

    def _show_working_copy(self) -> None:
        """Read the page from the working copy from now on.

        The library a push would carry is the working copy's, not the install's,
        so once a material has been added or removed the page has to show that one
        - otherwise the row the user just made is missing from its own list.
        """
        if self.editor is None:
            return
        got = self.editor.depot
        if got and got != self.depot:
            self.depot = got

    # ---- writing -------------------------------------------------------
    def copy_material(self) -> None:
        """Clone the chosen row under a name the user picks."""
        source = self._picked_name()
        if not source:
            return
        row = self._row_of(source) or {}
        suggested = source + "_copy"
        name, ok = QInputDialog.getText(
            self, "A new material",
            f"Name for the copy of {source}:\n\nIt keeps the same application, "
            f"cull, blend and flags, so it draws exactly like {source} until you "
            f"point a part at it and change its colour.", text=suggested)
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        root = self._prepare()
        if not root:
            return
        rgba = tuple(row.get("rgba") or ())[:4] or None
        try:
            made = editlib.add_material(root, source, name, rgba=rgba,
                                        log=self.log.note)
        except editlib.EditError as exc:
            QMessageBox.critical(self, "The material", str(exc))
            return
        self.log.ok(f"{made['material']}: {made['added']:+,} B, "
                    f"slot {made['slot'] if made['slot'] is not None else 'none'}")
        if made.get("slot_error"):
            self.log.error(f"the livery slot was not added: {made['slot_error']}")
        self.status.emit(f"Added the material {made['material']}")
        self.changed.emit()
        self._show_working_copy()
        self.reload()
        self.select_name(made["material"])

    def remove_material(self) -> None:
        """Delete a material this program added."""
        name = self._picked_name()
        if not name:
            return
        row = self._row_of(name) or {}
        used = row.get("cars") or 0
        extra = (f"\n\n{used} car(s) wear it. They keep the name in their livery "
                 f"table, so they would draw without it - change them first."
                 if used else "")
        got = QMessageBox.question(
            self, "Delete this copy",
            f"Remove the material {name} and its livery slot?{extra}\n\n"
            f"The game's own materials are never touched.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if got != QMessageBox.Yes:
            return
        root = self._prepare()
        if not root:
            return
        try:
            editlib.remove_material(root, name, force=bool(used))
        except editlib.EditError as exc:
            QMessageBox.critical(self, "The material", str(exc))
            return
        self.log.ok(f"removed {name}")
        self.status.emit(f"Removed the material {name}")
        self.changed.emit()
        self._show_working_copy()
        self.reload()

    def attach(self, editor) -> None:
        """Remember the window's workspace, so a copy or a delete can be made.

        ``editor.for_materials()`` is called at that moment rather than here: it
        mirrors ``materials.bin`` and the shared tables into the working copy, and
        doing that on a page load would copy 135 KB every time the tab is opened.
        """
        self.editor = editor
        self.root = getattr(editor, "root", "") if editor is not None else ""

    def attach_root(self, root: str) -> None:
        """Remember the working copy a copy or a delete writes into."""
        self.root = root or ""

    def _describe(self, name: str) -> None:
        try:
            info = matlib.details(self.depot, name)
        except matlib.ManagerError as exc:
            self.shader.setText(str(exc))
            return
        bits = []
        power = info.get("specularPower")
        if power:
            bits.append(f"specular power {power:g} "
                        f"(roughness about {info['roughness']:.2f})")
        colour = info.get("specularColour")
        if colour:
            bits.append("specular tint %d, %d, %d" % tuple(colour)[:3])
        textures = info.get("textures") or []
        if textures:
            bits.append("ramps: " + ", ".join(
                f"slot {slot} {path.rsplit('/', 1)[-1]}"
                for slot, path in textures))
        if info.get("twosided"):
            bits.append("two sided")
        self.shader.setText("; ".join(bits) if bits else "")


def selftest(depot: str) -> int:
    """Return the number of surprises (0 is good)."""
    return matlib.selftest(depot)
