"""The paint schemes of one car, and the boxes to change them.

A scheme is not just a colour: it names the atlas the body is drawn with, the
finish (gloss, matte, metallic ...) the body and the wing use, and the colour the
game's own customiser starts from.  A car can ship one gloss and one matte
factory colour at the same time, so each scheme is edited on its own rather than
the whole car at once.

A scheme can also give *any* texture slot a page of its own - the body is the
one every scheme does, and 196 shipped schemes point the wheels somewhere else.
That list is what the three-dot button beside each row opens.

Everything here writes straight into the game folder, and the Test tab is what
carries the result to the device.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from rr3lib import livery as liverylib

from .. import paints as paintlib
from .. import texslots as texlib
from . import settings as settingslib
from . import widgets as W

#: The texture slot the body is drawn from (``ext_ext``).
BODY_SLOT = 1932
#: The mesh slot the body's material is looked up through.
BODY_MESH = 30

FINISH_NONE = "leave as it is"

#: What a picture picker accepts.  A PNG is fine here: it is encoded when the
#: change is written, never when it is chosen.
PICTURE_FILTER = ("Pictures and textures (*.png *.jpg *.jpeg *.bmp *.webp *.tga "
                  "*.dxt.dds.z *.etc.dds.z *.atc.dds.z *.ptc.pvr.z *.dds.z "
                  "*.pvr.z);;All files (*)")

#: What the "body atlas" file picker accepts (the older, texture-only path).
ATLAS_FILTER = ("Game textures (*.dxt.dds.z *.etc.dds.z *.atc.dds.z *.ptc.pvr.z "
                "*.dds.z *.pvr.z);;All files (*)")


def _swatch(rgb: bytes) -> QColor:
    if not rgb or len(rgb) < 3:
        return QColor(200, 200, 200)
    return QColor(rgb[0], rgb[1], rgb[2])


def _dots(callback, tip: str) -> QWidget:
    """A three-dot button in a cell, the way every other per-row editor is."""
    wrap = QWidget()
    row = QHBoxLayout(wrap)
    row.setContentsMargins(2, 0, 2, 0)
    button = QToolButton()
    button.setText("\u22ef")
    button.setToolTip(tip)
    button.setCursor(Qt.PointingHandCursor)
    button.clicked.connect(lambda _checked=False: callback())
    row.addWidget(button)
    row.addStretch(1)
    return wrap


def effective_pictures(depot: str, car: str, index: int) -> dict:
    """``{key: page}`` - the page each slot of one scheme currently loads.

    Three levels decide it (the scheme, the car, the game's default table), and
    the first one that names a page wins; a slot none of them names comes back
    empty, which the dialog shows as "(the car's own)".
    """
    L = liverylib.load_car(depot, car)
    if not 0 <= int(index) < len(L.paints):
        return {}
    paint = L.paints[int(index)]
    out = {}
    for row in texlib.scheme_slots(depot, car):
        slot = int(row["slot"])
        got = paint.texture_of(slot)
        if got is None and row["key"] != "body":
            got = L.texture_of(slot)
        if got is None and row["key"] == "body":
            got = L.texture_of(texlib.interior_slot(depot))
        out[row["key"]] = got.decode("utf-8", "replace") if got else ""
    return out


class TextureSlotsDialog(QDialog):
    """What each texture slot of one paint scheme loads, and where to change it.

    A row is one slot: the body first (every scheme has one), then the car's own
    pages.  The picture column shows the page the scheme loads now; setting a new
    one queues it, and nothing is written until the caller saves - which is what
    makes Build convert on Build and the Cars page convert on Save.
    """

    def __init__(self, parent, depot: str, car: str, current: dict, *,
                 pictures=None, tag: str = "", title: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title or f"The textures of a paint scheme of {car}")
        self.resize(760, 460)
        self.depot = depot
        self.car = car
        self.tag = tag or "colour"
        self.result: dict = {}
        self._pictures = list(pictures or [])
        self._rows = texlib.scheme_slots(depot, car)
        self._current = {r["key"]: str(current.get(r["key"], "") or "")
                         for r in self._rows}

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        note = W.muted(
            "A paint scheme can point any of these slots at a page of its own. "
            "The body is the one every scheme sets; the rest are optional, and a "
            "slot left alone loads whatever the car itself loads. A picture is "
            "converted to the texture format in Settings when the change is "
            "saved.")
        note.setWordWrap(True)
        lay.addWidget(note)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ("Slot", "Loads now", "Will be written as"))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.addWidget(W.button("Set a picture...", self._set_picture,
                               tip="Use a picture for the selected slot"))
        row.addWidget(W.button("Use the car's own", self._clear,
                               tip="Drop this scheme's override of the slot"))
        self.combo = QComboBox()
        self.combo.setToolTip("The pictures recognised in the exported folder")
        for item in self._pictures:
            self.combo.addItem(item["leaf"], item["path"])
        if self._pictures:
            row.addWidget(QLabel("or"))
            row.addWidget(self.combo, 1)
            row.addWidget(W.button("Use this one", self._use_combo))
        else:
            row.addStretch(1)
        lay.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._fill()

    def _fill(self) -> None:
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            head = QTableWidgetItem(row["name"] or row["key"])
            head.setToolTip(row["label"])
            if row.get("required"):
                head.setText(head.text() + "  (needed)")
            self.table.setItem(i, 0, head)
            # the whole path, not just the file: a scheme's body lives in
            # livery/ and its wheel next to the car's own page, and which one a
            # slot reads is the thing being shown
            page = self._current.get(row["key"], "")
            now = QTableWidgetItem(page or "(the car's own)")
            if page:
                now.setToolTip(page)
            self.table.setItem(i, 1, now)
            self.table.setItem(i, 2, QTableWidgetItem(self._target(row)))

    def _target(self, row) -> str:
        page = self._current.get(row["key"], "")
        if not page:
            return "-"
        suffix = texlib.page_suffix(page) or texlib.family_suffix(
            self.depot, key=settingslib.texture_family())
        body = row["key"] == "body"
        stem = f"ext_{self.tag}" if body else f"{row['key']}_{self.tag}"
        # a scheme's body goes in livery/; its wheel or badge goes next to the
        # page it stands in for, which is the car's own folder
        return texlib.target_rel(self.car, stem, suffix,
                                 place="livery" if body else "car")

    def _picked(self) -> int:
        rows = self.table.selectionModel().selectedRows() if \
            self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def _set_picture(self) -> None:
        index = self._picked()
        if index < 0:
            QMessageBox.information(self, "Set a picture",
                                    "Select a slot in the table first.")
            return
        path, _f = QFileDialog.getOpenFileName(
            self, "Picture for this slot", "", PICTURE_FILTER)
        if not path:
            return
        self._take(index, path)

    def _use_combo(self) -> None:
        index = self._picked()
        if index < 0:
            QMessageBox.information(self, "Set a picture",
                                    "Select a slot in the table first.")
            return
        path = self.combo.currentData() or ""
        if path:
            self._take(index, path)

    def _take(self, index: int, path: str) -> None:
        key = self._rows[index]["key"]
        self._current[key] = path
        self.result[key] = path
        self._fill()
        self.table.selectRow(index)

    def _clear(self) -> None:
        index = self._picked()
        if index < 0:
            return
        row = self._rows[index]
        if row.get("required"):
            QMessageBox.information(
                self, "The body slot",
                "The body is the one slot a scheme cannot leave alone: a scheme "
                "with no body picture draws the car unpainted.")
            return
        key = row["key"]
        self._current.pop(key, None)
        self.result[key] = ""
        self._fill()

    def values(self) -> dict:
        """``{key: picture}`` for the slots that were changed (``""`` = clear)."""
        return {k: v for k, v in self.result.items() if v}


class NewPaintDialog(QDialog):
    """Name a new paint scheme, give it a colour, and choose its pictures.

    A scheme is a row in the car's livery table, so "adding a preset" means
    "copying a row and giving it its own pictures".  The name continues the
    shipped numbering by default (``07_<car>.livery``) because that number is
    what the frontend orders the colours by.

    The body picture is required - a scheme without one draws the car with the
    copied scheme's body - and every other slot is optional.  Each row shows the
    name the file will carry, which is ``<car>_ext_<colour>`` for the body: the
    same shape the shipped schemes use.
    """

    def __init__(self, parent, car: str, suggestion: str, *, copy_from: str = "",
                 depot: str = "", pictures=None, colour=None):
        super().__init__(parent)
        self.setWindowTitle("Add a paint scheme")
        self.resize(720, 470)
        self.car = car
        self.depot = depot
        self._rgb = tuple(colour or (200, 24, 24))
        self._pictures = list(pictures or [])
        self._rows = texlib.scheme_slots(depot, car) if depot else []
        #: ``{key: picture}`` - the choices made here
        self._chosen: dict = {}

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        tip = W.muted(
            f"{car} gets a new row in its livery table"
            + (f", copied from {copy_from}" if copy_from else "")
            + ". Give it a colour and a body picture and it is a preset the game "
              "can draw; the other slots are optional.")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        top = QGridLayout()
        top.setColumnStretch(1, 1)
        top.addWidget(QLabel("Name"), 0, 0)
        self.name = QLineEdit(suggestion)
        self.name.setToolTip(
            "The row's own name. The leading number is what the paint list is "
            "ordered by, so leaving the suggested value keeps the schemes in "
            "order.")
        top.addWidget(self.name, 0, 1, 1, 2)

        top.addWidget(QLabel("Colour"), 1, 0)
        self.colour_btn = QPushButton()
        self.colour_btn.setFixedSize(48, 22)
        self.colour_btn.clicked.connect(self._pick_colour)
        top.addWidget(self.colour_btn, 1, 1, Qt.AlignLeft)
        self.colour_note = W.muted("")
        top.addWidget(self.colour_note, 1, 2)
        lay.addLayout(top)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ("Slot", "Picture", "Will be written as"))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.addWidget(W.button("Set a picture...", self._set_picture,
                               tip="Choose the picture for the selected slot"))
        self.combo = QComboBox()
        self.combo.setToolTip("The paint pictures recognised in the exported "
                              "folder, if there were any")
        for item in self._pictures:
            self.combo.addItem(item["leaf"], item["path"])
        if self._pictures:
            row.addWidget(QLabel("or"))
            row.addWidget(self.combo, 1)
            row.addWidget(W.button("Use this one", self._use_combo))
        else:
            row.addStretch(1)
        lay.addLayout(row)

        self.note = W.muted("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        # The recognised picture that matches the colour is the obvious body;
        # failing that the first one, because that is what a folder of livery
        # exports is for and asking for it twice would be silly.
        self._auto_body = False
        self._auto_pick_body()
        self._fill()

    def _auto_pick_body(self) -> None:
        """Take the body picture whose colour word matches, else the first."""
        bodies = [p for p in self._pictures
                  if int(p.get("slot") or 0) == texlib.BODY_SLOT]
        if not bodies:
            return
        tag = texlib.colour_word(self._rgb)
        match = next((p["path"] for p in bodies
                      if texlib.clean_stem(p.get("tag") or "") == tag), "")
        self._chosen["body"] = match or bodies[0]["path"]
        self._auto_body = True

    # ---- the table ----------------------------------------------------
    def _tag(self) -> str:
        return texlib.colour_word(self._rgb)

    def _fill(self) -> None:
        tag = self._tag()
        self.colour_btn.setStyleSheet(
            f"background: #{self._rgb[0]:02x}{self._rgb[1]:02x}{self._rgb[2]:02x};"
            " border:1px solid #888; border-radius:3px")
        self.colour_note.setText(
            f"{tag.replace('_', ' ')}  (#{self._rgb[0]:02x}{self._rgb[1]:02x}"
            f"{self._rgb[2]:02x})")
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            head = QTableWidgetItem(row["name"] or row["key"])
            head.setToolTip(row["label"])
            if row.get("required"):
                head.setText(head.text() + "  (needed)")
            self.table.setItem(i, 0, head)
            page = self._chosen.get(row["key"], "")
            cell = QTableWidgetItem(os.path.basename(page) if page else "(none)")
            if page:
                cell.setToolTip(page)
            self.table.setItem(i, 1, cell)
            self.table.setItem(i, 2, QTableWidgetItem(self._target(row)))
        if not self._rows:
            self.note.setText(
                "This install's livery table could not be read, so the slots are "
                "not listed - the scheme can still be added and its pictures set "
                "afterwards from the paint table.")
        else:
            self.note.setText(
                "The body is the one picture a new scheme needs. A picture is "
                "converted to the texture format in Settings when the build or "
                "the save runs.")

    def _target(self, row) -> str:
        page = self._chosen.get(row["key"], "")
        suffix = (texlib.page_suffix(page) if page and not texlib.is_picture(page)
                  else texlib.family_suffix(
                      self.depot, key=settingslib.texture_family()))
        body = row["key"] == "body"
        stem = f"ext_{self._tag()}" if body else f"{row['key']}_{self._tag()}"
        return texlib.target_rel(self.car, stem, suffix,
                                 place="livery" if body else "car")

    def _picked(self) -> int:
        rows = self.table.selectionModel().selectedRows() if \
            self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def _set_picture(self) -> None:
        index = self._picked()
        if index < 0:
            QMessageBox.information(self, "Set a picture",
                                    "Select a slot in the table first.")
            return
        path, _f = QFileDialog.getOpenFileName(
            self, "Picture for this slot", "", PICTURE_FILTER)
        if not path:
            return
        self._take(index, path)

    def _use_combo(self) -> None:
        index = self._picked()
        if index < 0:
            QMessageBox.information(self, "Set a picture",
                                    "Select a slot in the table first.")
            return
        path = self.combo.currentData() or ""
        if path:
            self._take(index, path)

    def _take(self, index: int, path: str) -> None:
        key = self._rows[index]["key"]
        self._chosen[key] = path
        if key == "body":
            self._auto_body = False
        self._fill()
        self.table.selectRow(index)

    def _pick_colour(self) -> None:
        chosen = QColorDialog.getColor(_swatch(self._rgb), self, "Paint colour")
        if not chosen.isValid():
            return
        self._rgb = (chosen.red(), chosen.green(), chosen.blue())
        # a body nobody chose by hand follows the colour to the picture of that
        # name, which is what a folder of ext_<colour>.png files is for
        if self._auto_body:
            self._auto_pick_body()
        self._fill()

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.information(self, "Add a paint scheme",
                                    "The new scheme needs a name.")
            return
        if self._rows and not self._chosen.get("body"):
            QMessageBox.information(
                self, "Add a paint scheme",
                "Set the body picture first: a scheme without one draws the car "
                "with the body of the scheme it was copied from, so it would not "
                "look like a new preset at all.")
            return
        self.accept()

    # ---- answers ------------------------------------------------------
    def values(self) -> tuple:
        """``(name, rgb, pictures, tag)``."""
        return (self.name.text().strip(), self._rgb,
                dict(self._chosen), self._tag())

    def legacy_atlas(self) -> str:
        """The body picture, for the older ``source=`` path."""
        return self._chosen.get("body", "")


class PaintsPane(QWidget):
    """Every paint scheme of the selected car, editable one at a time."""

    changed = Signal()
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = None
        self.car = ""
        self._schemes: list = []
        self._finishes: list = []
        self._dirty_colours: dict = {}
        self._dirty_finishes: dict = {}
        self._dirty_pictures: dict = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(6)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ("Paint scheme", "Colour", "Finish", "Atlas", ""))
        self.table.verticalHeader().setVisible(False)
        # A car's schemes are edited in batches as often as one at a time - "make
        # all six matte" is one thought, not six - so the table takes several
        # rows at once and every button below acts on all of them.
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setStretchLastSection(False)
        head.setSectionResizeMode(4, QHeaderView.Fixed)
        for column, width in enumerate((250, 90, 190, 260, 34)):
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self._picked)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Finish"))
        self.finish = QComboBox()
        self.finish.setToolTip(
            "The customiser's own finishes first, then the factory colours the "
            "shipped cars use. Only materials the livery table has a slot for "
            "are listed, so a part cannot be pointed at a concrete wall by "
            "mistake.")
        row.addWidget(self.finish, 1)
        self.set_finish_btn = W.button(
            "Set finish", self._set_finish, primary=True,
            tip="Use this finish for the selected scheme")
        row.addWidget(self.set_finish_btn)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.colour_btn = W.button("Pick a colour...", self._pick_colour,
                                   tip="The colour the customiser starts from")
        row2.addWidget(self.colour_btn)
        self.atlas_btn = W.button("Pick a body atlas...", self._pick_atlas,
                                  tip="The picture this scheme's body is drawn with")
        row2.addWidget(self.atlas_btn)
        self.add_btn = W.button("Add a scheme...", self._add_scheme, primary=True,
                                tip="Copy a scheme into a new paint preset and "
                                    "give it its own body atlas")
        row2.addWidget(self.add_btn)
        self.del_btn = W.button(
            "Delete scheme(s)...", self._remove_schemes,
            tip="Remove the selected paint schemes. A car needs at least one, so "
                "the last one cannot be removed")
        row2.addWidget(self.del_btn)
        self.reset_btn = W.button("Undo my changes", self._reset,
                                  tip="Forget the edits made here and read again")
        row2.addWidget(self.reset_btn)
        self.save_btn = W.button("Save the paint changes", self.save, primary=True,
                                 tip="Write these edits into the game folder")
        row2.addWidget(self.save_btn)
        row2.addStretch(1)
        lay.addLayout(row2)

        self.note = W.muted("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.summary = W.muted("")
        lay.addWidget(self.summary)
        self._idle()

    # ---- content ------------------------------------------------------
    def load(self, editor, car: str) -> None:
        self.editor = editor
        self.car = car
        self._dirty_colours = {}
        self._dirty_finishes = {}
        self._dirty_pictures = {}
        self.reload()

    def _root(self) -> str:
        if self.editor is None or not self.car:
            return ""
        try:
            return self.editor.read_root(self.car)
        except Exception:                        # noqa: BLE001
            return ""

    def _depot(self) -> str:
        root = self._root()
        return os.path.join(root, ".depot") if root else ""

    def reload(self) -> None:
        root = self._root()
        self._schemes = []
        if root and self.car:
            depot = os.path.join(root, ".depot")
            try:
                table = liverylib.load_slot_table(depot)
                L = liverylib.load_car(depot, self.car)
                self._schemes = self._rows(L, table)
            except Exception as exc:             # noqa: BLE001
                self.note.setText(f"Could not read {self.car}: {exc}")
        self._fill()
        self._fill_finishes()
        self._idle()

    def _rows(self, L, table) -> list:
        rows = []
        for i, p in enumerate(L.paints):
            material = ""
            slot = p.material_of(BODY_MESH)
            if slot is not None:
                material = table.name(slot) or ""
            elif L.material_of(BODY_MESH) is not None:
                material = table.name(L.material_of(BODY_MESH)) or ""
            texture = p.texture_of(BODY_SLOT)
            if texture is None:
                texture = L.texture_of(BODY_SLOT)
            rows.append({
                "index": i,
                "name": p.name(),
                "rgb": bytes(p.rgb),
                "finish": material,
                "atlas": texture.decode("utf-8", "replace") if texture else "",
            })
        return rows

    def _fill_finishes(self) -> None:
        depot = ""
        if self.editor is not None:
            depot = getattr(self.editor, "depot", "") or ""
        if depot and not self._finishes:
            try:
                self._finishes = paintlib.choices(depot)
            except Exception:                    # noqa: BLE001
                self._finishes = []
        current = self.finish.currentText()
        self.finish.blockSignals(True)
        self.finish.clear()
        self.finish.addItem(FINISH_NONE, "")
        for label, material in self._finishes:
            if material:
                self.finish.addItem(label, material)
            else:
                self.finish.addItem(label)
                item = self.finish.model().item(self.finish.count() - 1)
                if item is not None:
                    item.setEnabled(False)
        self.finish.blockSignals(False)
        if current:
            self.finish.setCurrentText(current)

    def _fill(self) -> None:
        # The selection survives a redraw: a batch is several presses in a row
        # (finish, then colour, then atlas) and re-picking the same six rows
        # after each one would make the multi-select pointless.
        keep = self._picked_indexes()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._schemes))
        for i, row in enumerate(self._schemes):
            name = QTableWidgetItem(row["name"])
            self.table.setItem(i, 0, name)
            colour = QTableWidgetItem("#%02x%02x%02x" % tuple(row["rgb"][:3]))
            colour.setBackground(_swatch(row["rgb"]))
            colour.setToolTip("The colour the customiser starts from")
            self.table.setItem(i, 1, colour)
            self.table.setItem(i, 2, QTableWidgetItem(row["finish"] or "-"))
            atlas = QTableWidgetItem(os.path.basename(row["atlas"]) or "-")
            atlas.setToolTip(row["atlas"])
            self.table.setItem(i, 3, atlas)
            self.table.setCellWidget(
                i, 4, _dots(lambda r=i: self._edit_textures(r),
                            "The pictures this scheme loads - the body and any "
                            "page it overrides"))
        # One select() call for the whole set: selectRow() clears what was
        # already selected, so calling it once per row would keep only the last
        # one and turn a six-scheme batch into a single-scheme edit.
        if keep:
            model = self.table.model()
            span = QItemSelection()
            for i in keep:
                if 0 <= i < len(self._schemes):
                    span.select(model.index(i, 0),
                                model.index(i, self.table.columnCount() - 1))
            self.table.selectionModel().select(
                span, QItemSelectionModel.ClearAndSelect
                | QItemSelectionModel.Rows)
        self.table.blockSignals(False)
        self.summary.setText(
            f"{len(self._schemes)} paint scheme(s)." if self._schemes else "")

    def _idle(self) -> None:
        has = bool(self._schemes)
        for button in (self.set_finish_btn, self.colour_btn, self.atlas_btn,
                       self.reset_btn, self.save_btn, self.del_btn):
            button.setEnabled(has)
        if not self.car:
            self.note.setText("Select a car to see its paint schemes.")
        elif not self._schemes:
            self.note.setText(f"{self.car} lists no paint schemes.")
        elif not self.note.text().startswith("Could not"):
            self.note.setText(
                "A scheme's colour is only the one the customiser starts from - "
                "the shipped atlas still draws the car. The finish decides how "
                "the paint behaves under light, and the pictures behind the ... "
                "button are what it draws with. Select several rows to change "
                "them in one go.")

    def _picked_indexes(self) -> list:
        """Every selected row, in the order the table shows them."""
        model = self.table.selectionModel() if self.table.selectionModel() else None
        if model is None:
            return []
        return sorted(row.row() for row in model.selectedRows())

    def _picked_index(self) -> int:
        rows = self._picked_indexes()
        return rows[0] if rows else -1

    def _picked(self) -> None:
        index = self._picked_index()
        if 0 <= index < len(self._schemes):
            row = self._schemes[index]
            if row["finish"]:
                self.finish.setCurrentText(paintlib.label_for(row["finish"]))

    # ---- editing ------------------------------------------------------
    def _needs_rows(self) -> list:
        rows = [i for i in self._picked_indexes() if 0 <= i < len(self._schemes)]
        if not rows:
            QMessageBox.information(
                self, "Paint scheme",
                "Select a paint scheme in the table first - Ctrl+click to take "
                "several.")
        return rows

    def _needs_row(self) -> int:
        rows = self._needs_rows()
        return rows[0] if rows else -1

    def _set_finish(self) -> None:
        rows = self._needs_rows()
        if not rows:
            return
        material = self.finish.currentData() or ""
        if not material:
            QMessageBox.information(
                self, "Finish",
                "Pick one of the game's own finishes from the list.")
            return
        for index in rows:
            self._dirty_finishes[str(index)] = material
            self._schemes[index]["finish"] = material
        self._fill()
        self.status.emit(
            f"{len(rows)} scheme(s) will use {material} - press Save")

    def _pick_colour(self) -> None:
        rows = self._needs_rows()
        if not rows:
            return
        start = _swatch(self._schemes[rows[0]]["rgb"])
        chosen = QColorDialog.getColor(start, self, "Paint colour")
        if not chosen.isValid():
            return
        rgb = (chosen.red(), chosen.green(), chosen.blue())
        for index in rows:
            self._dirty_colours[str(index)] = rgb
            self._schemes[index]["rgb"] = bytes(rgb)
        self._fill()
        self.status.emit(
            f"{len(rows)} scheme(s) will start from {chosen.name()} - press Save")

    def _pick_atlas(self) -> None:
        rows = self._needs_rows()
        if not rows:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Body atlas for these schemes", "", PICTURE_FILTER)
        if not path:
            return
        for index in rows:
            self._dirty_pictures.setdefault(str(index), {})["body"] = path
            self._schemes[index]["atlas"] = path
        self._fill()
        self.status.emit(
            f"{len(rows)} scheme(s) will use {os.path.basename(path)} - press Save")

    def _edit_textures(self, row: int) -> None:
        """Open the slot table of one scheme and keep what it changed."""
        depot = self._depot()
        if not depot or not (0 <= row < len(self._schemes)):
            return
        scheme = self._schemes[row]
        index = scheme["index"]
        try:
            current = effective_pictures(depot, self.car, index)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "The textures of a paint scheme", str(exc))
            return
        # Anything queued here shows as the current choice, so reopening the
        # dialog does not look like the change was lost.
        queued = self._dirty_pictures.get(str(index)) or {}
        for key, path in queued.items():
            current[key] = path
        dlg = TextureSlotsDialog(
            self, depot, self.car, current,
            pictures=self._folder_pictures(),
            tag=texlib.colour_word(scheme["rgb"]),
            title=f"{scheme['name']} - what it loads")
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = dlg.values()
        if not chosen:
            return
        self._dirty_pictures.setdefault(str(index), {}).update(chosen)
        body = self._dirty_pictures[str(index)].get("body")
        if body:
            self._schemes[row]["atlas"] = body
        self._fill()
        self.status.emit(
            f"{scheme['name']}: {len(chosen)} picture(s) chosen - press Save")

    def _folder_pictures(self) -> list:
        """The paint pictures already in the car's ``livery/`` folder."""
        depot = self._depot()
        if not depot or not self.car:
            return []
        folder = os.path.join(depot, "vehicles", self.car, "livery")
        if not os.path.isdir(folder):
            return []
        out = []
        for leaf in sorted(os.listdir(folder)):
            path = os.path.join(folder, leaf)
            if os.path.isfile(path) and texlib.page_suffix(leaf):
                out.append({"leaf": leaf, "path": path,
                            "slot": texlib.BODY_SLOT,
                            "tag": texlib.stem_of(leaf, self.car)})
        return out

    def _add_scheme(self) -> None:
        """Copy a scheme into a new paint preset, with its own pictures."""
        if self.editor is None or not self.car:
            return
        root = self._root()
        if not root:
            QMessageBox.information(self, "Paint scheme",
                                    "Select a car first.")
            return
        index = self._picked_index()
        if index < 0:
            index = 0
        depot = os.path.join(root, ".depot")
        try:
            L = liverylib.load_car(depot, self.car)
            suggestion = L.next_paint_name()
            source_name = L.paints[index].name() if L.paints else ""
            colour = tuple(L.paints[index].rgb[:3]) if L.paints else None
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Paint scheme", str(exc))
            return
        dlg = NewPaintDialog(self, self.car, suggestion, copy_from=source_name,
                             depot=depot, colour=colour,
                             pictures=self._folder_pictures())
        if dlg.exec() != QDialog.Accepted:
            return
        livery_name, rgb, pictures, tag = dlg.values()
        if not livery_name:
            QMessageBox.information(self, "Paint scheme",
                                    "The new scheme needs a name.")
            return
        from .. import edit as editlib

        try:
            got = editlib.add_paint_scheme(
                root, self.car, livery_name=livery_name, copy_from=index,
                pictures=pictures or None, tag=tag,
                family_key=settingslib.texture_family())
            if rgb:
                editlib.set_paint_finish(root, self.car,
                                         colours={got["index"]: tuple(rgb)})
            self.editor.capture(self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Paint scheme", str(exc))
            return
        self.status.emit(
            f"Added paint scheme {got['name']}"
            + (f" with {len(pictures)} picture(s)" if pictures else "")
            + " - Deploy pushes it")
        self.changed.emit()
        self.reload()

    def _remove_schemes(self) -> None:
        """Delete the selected schemes, but never the last one."""
        rows = self._needs_rows()
        if not rows:
            return
        if len(rows) >= len(self._schemes):
            QMessageBox.warning(
                self, "Delete paint schemes",
                f"{self.car} has {len(self._schemes)} paint scheme(s) and all of "
                "them are selected.\n\nA car needs at least one - with none it "
                "comes out of the showroom unpainted - so nothing was deleted. "
                "Leave one out and try again.")
            return
        names = [self._schemes[i]["name"] for i in rows]
        shown = "\n".join("  " + n for n in names[:8])
        if len(names) > 8:
            shown += f"\n  ... and {len(names) - 8} more"
        ok = QMessageBox.question(
            self, "Delete paint schemes",
            f"Delete {len(names)} paint scheme(s) from {self.car}?\n\n{shown}\n\n"
            f"{len(self._schemes) - len(names)} would be left. The body atlases "
            "they point at stay on disk - two schemes can share one picture.")
        if ok != QMessageBox.Yes:
            return
        root = self._root()
        if not root:
            QMessageBox.information(self, "Delete paint schemes",
                                    "Select a car first.")
            return
        from .. import edit as editlib

        try:
            got = editlib.remove_paint_scheme(root, self.car, rows)
            self.editor.capture(self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Delete paint schemes", str(exc))
            return
        # Anything queued for a scheme that no longer exists would be written to
        # whatever scheme took its index, so the queue is dropped.
        self._dirty_colours = {}
        self._dirty_finishes = {}
        self._dirty_pictures = {}
        self.status.emit(
            f"Deleted {len(got['removed'])} paint scheme(s); {got['left']} left")
        self.changed.emit()
        self.reload()

    def pending(self) -> dict:
        """What has been changed but not yet written."""
        return {"colours": dict(self._dirty_colours),
                "finishes": dict(self._dirty_finishes),
                "pictures": dict(self._dirty_pictures)}

    def save(self) -> None:
        if self.editor is None or not self.car:
            return
        pending = self.pending()
        if not any(pending.values()):
            QMessageBox.information(self, "Paint schemes",
                                    "Nothing has been changed yet.")
            return
        ok = QMessageBox.question(
            self, "Paint schemes",
            f"Write {self._count(pending)} change(s) for {self.car}?\n\n"
            "They are written into the game folder; the Test tab pushes them.")
        if ok != QMessageBox.Yes:
            return
        from .. import edit as editlib

        try:
            root = self.editor.for_car(self.car)
            if pending["colours"] or pending["finishes"]:
                editlib.set_paint_finish(
                    root, self.car,
                    colours={int(k): v for k, v in pending["colours"].items()},
                    per_paint={int(k): v for k, v in pending["finishes"].items()})
            for key, pictures in pending["pictures"].items():
                # The scheme's colour may have been changed in the same save, and
                # the file name is built from it - so the colour is written first.
                editlib.set_paint_pictures(
                    root, self.car, int(key),
                    {k: v for k, v in pictures.items() if v},
                    family_key=settingslib.texture_family())
            self.editor.capture(self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Paint schemes", str(exc))
            return
        self._dirty_colours = {}
        self._dirty_finishes = {}
        self._dirty_pictures = {}
        self.status.emit(f"Wrote {self._count(pending)} paint change(s)")
        self.changed.emit()
        self.reload()

    @staticmethod
    def _count(pending: dict) -> int:
        return sum(len(v) for v in pending.values())

    def _reset(self) -> None:
        self._dirty_colours = {}
        self._dirty_finishes = {}
        self._dirty_pictures = {}
        self.reload()
        self.status.emit("Paint changes dropped")
