"""The Decals page: what the vinyl editor offers, and whether it will draw.

The vinyl editor's list is one table - ``custom.decals.nct`` - and a font.  A
record either draws a code point out of ``r3_decals.ttf`` or a ``.pvr`` picture
under ``vehicles/decals/``, and the game only shows it if the thing it names is
actually there.  That makes this page a reader first: it is the only place that
says, in one list, which of the 229 shapes will appear and which of them the
game will draw as nothing.

It edits records too, but only the parts the file can hold: a name key, a
category, and which of the two halves the record draws from.

Drawing a *new shape* is the one thing that needs two files at once, so it is
the one thing that can leave the game in a bad state on its own: a record that
names a code point the font does not have draws nothing, and says nothing about
why.  That is why the shape dialog writes both halves in a single undo step, and
why removing a record that drew a glyph offers to clear the glyph with it.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import decals as decallib
from . import widgets as W
from .worker import Task

COLUMNS = ("", "Id", "What it is called", "Kind", "Draws", "Category", "Name key")

#: Widths the header starts at; every one is draggable afterwards.
WIDTHS = (28, 46, 300, 66, 190, 130, 330)


class DecalDialog(QDialog):
    """Change one record: its name key, its category, and what it draws."""

    def __init__(self, row, categories, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Decal {row['id']}")
        self.row = row
        lay = QVBoxLayout(self)

        note = W.muted(
            "A record draws either a code point out of the font or a picture "
            "under vehicles/decals - never both. Changing the name key only "
            "changes what the editor calls it, not the shape.")
        note.setWordWrap(True)
        lay.addWidget(note)

        form = QFormLayout()
        self.name = QLineEdit(row["name"])
        self.name.setMinimumWidth(360)
        form.addRow("Name key", self.name)

        self.category = QComboBox()
        self.category.setEditable(True)
        for key, _count in categories:
            self.category.addItem(decallib.category_label(key), key)
        index = self.category.findData(row["category"])
        if index < 0:
            self.category.addItem(decallib.category_label(row["category"]),
                                  row["category"])
            index = self.category.count() - 1
        self.category.setCurrentIndex(index)
        form.addRow("Category", self.category)

        self.draws = QComboBox()
        self.draws.addItem("A code point from the font", "glyph")
        self.draws.addItem("A picture under vehicles/decals", "page")
        self.draws.setCurrentIndex(0 if row["kind"] == "glyph" else 1)
        self.draws.currentIndexChanged.connect(self._shape_changed)
        form.addRow("Draws", self.draws)

        self.code = QLineEdit(row["glyph"] if row["kind"] == "glyph" else "")
        self.code.setPlaceholderText("0x0029 or a single character")
        form.addRow("Code point", self.code)

        self.page = QLineEdit(row["page"] if row["kind"] == "page" else "")
        self.page.setPlaceholderText("vehicles/decals/sponsors/decal_x.pvr")
        form.addRow("Picture", self.page)

        self.order = QSpinBox()
        self.order.setRange(0, 9999)
        self.order.setValue(int(row.get("position", 0)))
        self.order.setToolTip("Where in the list the editor shows it")
        form.addRow("Position", self.order)
        lay.addLayout(form)

        self.problem = W.muted("")
        self.problem.setWordWrap(True)
        lay.addWidget(self.problem)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._shape_changed()

    def _shape_changed(self, *_args) -> None:
        glyph = self.draws.currentData() == "glyph"
        self.code.setEnabled(glyph)
        self.page.setEnabled(not glyph)

    def _accept(self) -> None:
        if not self.name.text().strip():
            self.problem.setText("A record needs a name key, even one that "
                                 "gametext.txt does not have.")
            return
        if self.draws.currentData() == "glyph" and not self.code.text().strip():
            self.problem.setText("A shape needs a code point to draw.")
            return
        if self.draws.currentData() == "page" and not self.page.text().strip():
            self.problem.setText("A picture needs a path under vehicles/decals.")
            return
        self.accept()

    def result_info(self) -> dict:
        """Only the fields that actually differ from what the record had."""
        out = {}
        name = self.name.text().strip().encode("latin-1", "replace")
        if name != self.row["name"].encode("latin-1", "replace"):
            out["name"] = name
        category = (self.category.currentData() or "").encode("latin-1", "replace")
        if category != self.row["category"].encode("latin-1", "replace"):
            out["category"] = category
        if self.draws.currentData() == "glyph":
            text = self.code.text().strip().encode("latin-1", "replace")
            if text != self.row["glyph"].encode("latin-1", "replace"):
                out["glyph"] = text
        else:
            text = self.page.text().strip().encode("latin-1", "replace")
            if text != self.row["page"].encode("latin-1", "replace"):
                out["page"] = text
        if self.order.value() != int(self.row.get("position", 0)):
            out["position"] = self.order.value()
        return out


class DecalsPage(QWidget):
    """Every decal in the list, with the two ways a row can be wrong."""

    status = Signal(str)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.depot = ""
        self.root = ""
        self.editor = None
        self.rows = []
        self.info = {}
        self._task = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lay.addWidget(W.heading("Vinyl decals", 2))
        self.note = W.muted(
            "Every shape the vinyl editor offers comes from one table, "
            "custom.decals.nct, and every shape it draws comes from one font, "
            "r3_decals.ttf. A row here that says the glyph is missing is a record "
            "the game will show as nothing.")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name, category or id")
        self.search.textChanged.connect(self._fill)
        bar.addWidget(self.search, 1)
        self.kind = QComboBox()
        self.kind.addItem("Everything", "")
        self.kind.addItem("Shapes (a glyph)", "glyph")
        self.kind.addItem("Pictures (a page)", "page")
        self.kind.currentIndexChanged.connect(self._fill)
        bar.addWidget(self.kind)
        self.only_bad = QCheckBox("Only the ones that will not draw")
        self.only_bad.setToolTip(
            "A record whose code point is not in the font shows as nothing")
        self.only_bad.toggled.connect(self._fill)
        bar.addWidget(self.only_bad)
        lay.addLayout(bar)

        acts = QHBoxLayout()
        self.edit_btn = W.button("Change this record...", self.edit_decal,
                                 tip="Rename it, move it to another category, or "
                                     "point it at another picture")
        acts.addWidget(self.edit_btn)
        self.new_btn = W.button("Add a record...", self.add_decal,
                                tip="A record needs a code point the font already "
                                    "has, or a picture the game already ships")
        acts.addWidget(self.new_btn)
        self.del_btn = W.button("Remove this record", self.remove_decal,
                                tip="Takes the row out of the list; the font and "
                                    "the picture are left alone")
        acts.addWidget(self.del_btn)
        self.shape_btn = W.button("Draw a new shape...", self.add_shape,
                                  tip="Puts a glyph in r3_decals.ttf and the "
                                      "record that names it, in one step")
        acts.addWidget(self.shape_btn)
        acts.addStretch(1)
        lay.addLayout(acts)

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
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._buttons)
        self._buttons()
        lay.addWidget(self.table, 1)

        self.summary = W.muted("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        self.log = W.LogPane()
        self.log.setMinimumHeight(60)
        self.log.setMaximumHeight(110)
        lay.addWidget(self.log)

    # ------------------------------------------------------------ loading
    def attach_root(self, root: str) -> None:
        """Point the page at the game folder, so a new record shows up."""
        self.root = root or ""

    def _read_depot(self) -> str:
        """Where the table is read from: the game folder when it has one."""
        if self.root:
            got = os.path.join(self.root, ".depot")
            if os.path.isfile(os.path.join(got, "vehicles", "data",
                                           "custom.decals.nct")):
                return got
        return self.depot

    def load(self, depot: str, root: str = "") -> None:
        self.depot = depot
        if root:
            self.attach_root(root)
        if self._task is not None:
            return
        where = self._read_depot()
        if not where:
            return
        self.summary.setText("Reading the decal list...")
        self._task = Task(self._gather, where, parent=self)
        self._task.done.connect(self._loaded)
        self._task.fail.connect(self._failed)
        self._task.start()

    def _gather(self, where: str) -> dict:
        return {"where": where, "info": decallib.summary(where),
                "rows": decallib.rows(where),
                "problems": decallib.problems(where)}

    def _loaded(self, payload) -> None:
        self._task = None
        self.info = payload.get("info") or {}
        self.rows = payload.get("rows") or []
        self._fill()
        self._say(payload.get("problems") or [])

    def _failed(self, text: str) -> None:
        self._task = None
        self.summary.setText(f"The decal list could not be read: {text}")

    def _say(self, problems) -> None:
        for level, text in problems:
            if level == "error":
                self.log.error(text)
            elif level == "warn":
                self.log.warn(text)
            else:
                self.log.note(text)

    # ------------------------------------------------------------ the table
    def _keep(self, row) -> bool:
        wanted = self.search.text().strip().lower()
        if wanted:
            haystack = (f"{row['id']} {row['shown']} {row['category_label']} "
                        f"{row['name']} {row['page']} {row['glyph']}").lower()
            if wanted not in haystack:
                return False
        kind = self.kind.currentData()
        if kind and row["kind"] != kind:
            return False
        if self.only_bad.isChecked() and row["in_font"] is not False:
            return False
        return True

    def _fill(self) -> None:
        keep = [row for row in self.rows if self._keep(row)]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(keep))
        for index, row in enumerate(keep):
            self._put(index, row)
        self.table.setSortingEnabled(True)
        self._say_counts(len(keep))

    def _put(self, index: int, row) -> None:
        mark = QTableWidgetItem("" if row["in_font"] is not False else "!")
        if row["in_font"] is False:
            mark.setToolTip("This code point is not in the font, so nothing draws")
        self.table.setItem(index, 0, mark)
        self.table.setItem(index, 1, QTableWidgetItem(str(row["id"])))
        self.table.setItem(index, 2, QTableWidgetItem(row["shown"]))
        self.table.setItem(index, 3, QTableWidgetItem(row["kind"]))
        if row["kind"] == "glyph":
            draws = f"U+{row['code_point']:04X} ({row['glyph']})"
            if row["in_font"] is False:
                draws += " - missing from the font"
        else:
            draws = row["page"]
        self.table.setItem(index, 4, QTableWidgetItem(draws))
        self.table.setItem(index, 5, QTableWidgetItem(row["category_label"]))
        name = QTableWidgetItem(row["name"] if row["has_name"] else
                                f"{row['name']}  (no such key)")
        if not row["has_name"]:
            name.setToolTip("gametext.txt has no line for this key, so the game "
                            "shows the shape itself")
        self.table.setItem(index, 6, name)
        self.table.item(index, 1).setData(Qt.UserRole, row["id"])

    def _say_counts(self, shown: int) -> None:
        got = self.info
        if not got:
            return
        parts = [f"{shown} of {got['decals']} decal(s)"]
        parts.append(f"{got['glyphs']} draw a glyph, {got['pages']} a picture")
        parts.append(f"{got['categories']} categories")
        if got["missing_from_font"]:
            parts.append(f"{got['missing_from_font']} code point(s) are not in "
                         f"the font")
        else:
            parts.append(f"all {got['code_points']} code points are in the font")
        parts.append(f"{got['font_glyphs']} glyphs in {decallib.FONT}")
        self.summary.setText("; ".join(parts) + ".")

    def reload(self) -> None:
        if self.depot:
            self.load(self.depot, self.root)

    # ------------------------------------------------------------ editing
    def attach_editor(self, editor) -> None:
        """Hand the page the editor, so it can write and stage a change."""
        self.editor = editor
        self._buttons()

    def _picked(self):
        """The row the table is on, or None."""
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        if item is None:
            return None
        wanted = item.data(Qt.UserRole)
        for got in self.rows:
            if got["id"] == wanted:
                return got
        return None

    def _root(self) -> str:
        if self.editor is None:
            return self.root
        return self.editor.for_tables()

    def _write(self, what: str, call) -> dict:
        """Run one edit, then say what happened and reload the list."""
        try:
            got = call(self._root())
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, what, str(exc))
            return {}
        if not got.get("changed", True):
            self.log.note(f"{what}: nothing changed.")
            return got
        self.log.ok(f"{what}: {got.get('before_bytes', '?')} -> "
                    f"{got.get('after_bytes', '?')} bytes")
        self.status.emit(what)
        self.changed.emit()
        self.reload()
        return got

    def edit_decal(self) -> None:
        row = self._picked()
        if row is None:
            QMessageBox.information(self, "Change a record",
                                    "Select a record in the table first.")
            return
        got = decallib.load(self._read_depot())
        box = DecalDialog(row, got.categories(), self)
        if box.exec() != QDialog.Accepted:
            return
        info = box.result_info()
        if not info:
            return
        from .. import edit as editlib

        position = info.pop("position", None)
        self._write(f"Change decal {row['id']}",
                    lambda root: editlib.set_decal(root, row["id"], **info))
        if position is not None:
            self._write(f"Move decal {row['id']}",
                        lambda root: editlib.move_decal(root, row["id"], position))

    def add_decal(self) -> None:
        got = decallib.load(self._read_depot())
        blank = {"id": 0, "position": len(got.decals), "category": "", "name": "",
                 "kind": "glyph", "glyph": "", "code_point": None, "page": ""}
        box = DecalDialog(blank, got.categories(), self)
        box.setWindowTitle("A new decal")
        if box.exec() != QDialog.Accepted:
            return
        info = box.result_info()
        category = info.get("category", b"")
        name = info.get("name", b"")
        if not category or not name:
            QMessageBox.information(self, "A new decal",
                                    "A record needs a category and a name key.")
            return
        glyph = info.get("glyph", b"")
        page = info.get("page", b"")
        if not glyph and not page:
            QMessageBox.information(self, "A new decal",
                                    "A record has to draw something.")
            return
        from .. import edit as editlib

        position = info.get("position", -1)
        self._write("Add a decal",
                    lambda root: editlib.add_decal(root, category=category,
                                                   name=name, glyph=glyph,
                                                   page=page, position=position))

    def remove_decal(self) -> None:
        row = self._picked()
        if row is None:
            QMessageBox.information(self, "Remove a record",
                                    "Select a record in the table first.")
            return
        # A record that draws a glyph leaves that glyph behind.  Saying so here is
        # the only chance to offer clearing it: after the row is gone nothing
        # remembers which code point it used.
        glyph = bool(row.get("code_point") is not None)
        extra = ("\n\nIts code point is left in the font, so a record can be "
                 "pointed at it again." if glyph else
                 "\n\nThe picture is left where it is, so a record can be pointed "
                 "at it again.")
        ok = QMessageBox.question(
            self, "Remove a record",
            f"Take decal {row['id']} ({row['shown']}) out of the list?{extra}"
            "\n\nNothing that is already painted on a car changes.")
        if ok != QMessageBox.Yes:
            return
        from .. import edit as editlib

        if not glyph:
            self._write(f"Remove decal {row['id']}",
                        lambda root: editlib.remove_decal(root, row["id"]))
            return

        # Ask about the glyph only after the record is gone, because only then is
        # it knowable whether anything else still uses that code point.
        got = self._write(f"Remove decal {row['id']}",
                          lambda root: editlib.remove_decal_shape(root, row["id"]))
        if got.get("cleared"):
            self.log.note(f"U+{row['code_point']:04X} had no other user, so its "
                          f"glyph was emptied too.")
        elif got:
            self.log.note(f"U+{row['code_point']:04X} is still named by another "
                          f"record, so its glyph was kept.")

    def add_shape(self) -> None:
        """Draw a glyph into the font and write the record that names it."""
        from .. import edit as editlib
        from . import shapedlg

        got = decallib.load(self._read_depot())
        taken = set(got.code_points())
        code = 0xE000
        while code in taken and code < 0xFFFF:
            code += 1
        box = shapedlg.ShapeDialog(self, code_point=code, taken=taken)
        if box.exec() != QDialog.Accepted:
            return
        info = box.result_info()
        code_point = info["code_point"]
        self._write(f"Add the shape U+{code_point:04X}",
                    lambda root: editlib.add_decal_shape(
                        root, code_point=code_point,
                        contours=info["contours"], advance=info["advance"],
                        category=info["category"], name=info["name"]))

    def _buttons(self) -> None:
        picked = self._picked() is not None
        ready = self.editor is not None
        self.edit_btn.setEnabled(picked and ready)
        self.del_btn.setEnabled(picked and ready)
        self.new_btn.setEnabled(ready)
        self.shape_btn.setEnabled(ready)
