"""Which material each part of a car uses, and which page it samples.

The game does not read a mesh's material from the ``.m3g``.  It looks the mesh up
in the car's livery tables and uses the material named there, falling back to a
shipped default table.  That is why a tyre whose texture lives in
``vehicles/common`` looks right on every car without the model saying anything
about it, and why changing a part's look is a livery edit rather than a modelling
one.

Two tabs, because there are two independent things to change:

**Parts** picks a model file and shows every mesh in it with the material the
engine will give it.  The wheels, tyres, discs and calipers are *not* in the body
file - they are in ``<car>_shared.m3g`` - so the model dropdown is not a nicety,
it is the only way to reach them.

**Textures** shows the pages a car loads and which meshes read each one.  A tag
like ``_mm_tyre`` names the slot ``ext_tyre``, and every mesh sharing that tag
samples one page, so pointing the page at a picture of your own changes the whole
set at once - that is how a different tread, disc or carbon weave is done.  A
page can also be saved out as a PNG and edited in any paint program; putting it
back needs the page to be the same size, because the game allocates by size.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QComboBox, QDialog, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTabWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from .. import materials as matlib
from .. import pages as pagelib
from .. import textures as texlib
from .. import texslots as texslotslib
from . import settings as settingslib
from . import widgets as W

#: Where a material came from, in the words the table shows.
SOURCES = {
    "paint": "this paint scheme",
    "car": "the car's table",
    "default": "the shipped default",
    "none": "nothing - a hard coded fallback",
    "no slot": "no slot - the engine skips this mesh",
}

#: Where a texture page comes from.
WHERE = {
    "this car": "this car",
    "common": "shared (common/)",
    "none": "not named by this car",
}

#: The same three places, for the page picker, where a page is being chosen
#: rather than reported.
PLACE_LABEL = {
    "common": "shared with every car (common/)",
    "car": "this car's own folder",
}

#: What a texture picker will accept.
PICTURE_FILTER = ("Game textures (*.dxt.dds.z *.etc.dds.z *.atc.dds.z "
                  "*.ptc.pvr.z *.dds.z *.pvr.z);;All files (*)")

#: What a page can be built from.
SOURCE_FILTER = ("Pictures (*.png *.jpg *.jpeg *.bmp *.webp *.tga);;All files (*)")


class ShippedPageDialog(QDialog):
    """Pick one of the pages ``vehicles/common`` already holds.

    Only pages of the same kind as the slot's own are offered - a tyre slot gets
    the tyre pages, an interior weave slot the weaves - because a page that is
    the wrong kind is not a cosmetic mistake, it draws the wrong material
    entirely.  The whole list is one click away for the cases the guess is wrong.
    """

    def __init__(self, rows, parent=None, *, label: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"Another page for {label}" if label
                            else "Another page")
        self.resize(560, 460)
        lay = QVBoxLayout(self)
        note = W.muted(
            "These pages ship with the game, so nothing new is copied into the "
            "car's folder - only the livery row changes. The pages listed first "
            "are the same kind as the one the slot holds now.")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.only = QCheckBox("Only pages of the same kind")
        self.only.setChecked(True)
        lay.addWidget(self.only)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(("Page", "Kind"))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setStretchLastSection(True)
        self.table.setColumnWidth(0, 380)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.ok_btn = QPushButton("Use this page")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(W.button("Cancel", self.reject))
        row.addWidget(self.ok_btn)
        lay.addLayout(row)
        self._rows = list(rows)
        self.only.toggled.connect(self._fill)
        self.table.doubleClicked.connect(lambda _i: self.accept())
        self.table.itemSelectionChanged.connect(self._buttons)
        self._fill()

    def _fill(self) -> None:
        same = self.only.isChecked()
        shown = [r for r in self._rows if r.get("now")] if same else self._rows
        if not shown:
            shown = self._rows
        self.table.setRowCount(len(shown))
        for i, row in enumerate(shown):
            page = QTableWidgetItem(row["stem"])
            page.setToolTip(row["path"])
            self.table.setItem(i, 0, page)
            self.table.setItem(i, 1, QTableWidgetItem(row.get("kind") or "-"))
        if shown:
            self.table.selectRow(0)
        self._buttons()

    def _buttons(self) -> None:
        self.ok_btn.setEnabled(bool(self.table.selectionModel().selectedRows())
                               if self.table.selectionModel() else False)

    def chosen(self) -> str:
        rows = self.table.selectionModel().selectedRows() if \
            self.table.selectionModel() else []
        if not rows:
            return ""
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item is not None else ""


class ImportPageDialog(QDialog):
    """Turn a picture into a page and put it in ``common/`` or the car folder.

    Two choices, and both matter:

    * **the format** is which GPU family the file is encoded for.  DXT is what
      this install unpacks and what every page here already is; ETC and ATC
      exist because a livery can name them.  PVRTC is listed and refused, with
      the reason, rather than left out - "why is it not here" is a worse
      question than "why is it greyed out".
    * **the place** decides whether every car can name this page or only this
      one.  ``common/`` is written once and shared; the car's own folder costs
      that car a file and nobody else anything.
    """

    def __init__(self, root: str, car: str, parent=None, *,
                 where: str = "common", stem: str = "", picture: str = "",
                 labels: bool = False):
        super().__init__(parent)
        self.setWindowTitle(f"Add a page for {car}")
        self.resize(600, 380 if not labels else 430)
        self.root = root
        self.car = car
        self.result: dict = {}
        #: True until the user types a name of their own: a label then keeps
        #: rewriting the suggested name, and never touches a name that was typed.
        self._auto_name = not stem

        lay = QVBoxLayout(self)
        note = W.muted(
            "The picture is encoded as it is - it is never resized, because a "
            "page has to stay the size the art was authored for. A power of two "
            "is what the game's own pages use.")
        note.setWordWrap(True)
        lay.addWidget(note)

        form = QGridLayout()
        form.setColumnStretch(1, 1)
        form.addWidget(QLabel("Picture"), 0, 0)
        self.picture = QLineEdit(picture)
        form.addWidget(self.picture, 0, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        form.addWidget(browse, 0, 2)

        line = 1
        self.label = None
        if labels:
            form.addWidget(QLabel("Label"), line, 0)
            self.label = QComboBox()
            self.label.setEditable(True)
            self.label.setToolTip(
                "What the page is. The name is built from it, because nothing "
                "else records what a shared page is for.")
            for key, hint in texslotslib.COMMON_LABELS:
                self.label.addItem(key, key)
                index = self.label.count() - 1
                item = self.label.model().item(index)
                if item is not None:
                    item.setToolTip(hint)
            self.label.setCurrentIndex(0)
            form.addWidget(self.label, line, 1, 1, 2)
            line += 1

        form.addWidget(QLabel("Name"), line, 0)
        self.stem = QLineEdit(stem)
        self.stem.setToolTip(
            "The page's name without a suffix. Shipped pages are lowercase with "
            "underscores, and a name is folded into that shape - the engine's "
            "token matching never sees anything else.")
        form.addWidget(self.stem, line, 1, 1, 2)
        line += 1

        form.addWidget(QLabel("Format"), line, 0)
        self.format = QComboBox()
        for row in pagelib.FORMATS:
            self.format.addItem(row["label"], row["suffix"])
            if not row["writable"]:
                index = self.format.count() - 1
                item = self.format.model().item(index)
                if item is not None:
                    item.setEnabled(False)
                    item.setToolTip(row["note"])
        # The format this install was unpacked for is answered once, when the
        # game folder is chosen; here it only needs to be the default.  Getting
        # it wrong writes a page the GPU cannot decode, and the part draws as
        # nothing - so the dialog starts on the install's own family rather
        # than on whichever family happens to be listed first.
        preset = pagelib.suffix_for_family(settingslib.texture_family())
        if preset:
            self.format.setCurrentIndex(max(0, self.format.findData(preset)))
        form.addWidget(self.format, line, 1, 1, 2)

        form.addWidget(QLabel("Where"), line + 1, 0)
        self.place = QComboBox()
        for key, label in PLACE_LABEL.items():
            self.place.addItem(label, key)
        self.place.setCurrentIndex(max(0, self.place.findData(where)))
        form.addWidget(self.place, line + 1, 1, 1, 2)
        lay.addLayout(form)

        self.info = W.muted("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.why = W.muted("")
        self.why.setWordWrap(True)
        lay.addWidget(self.why)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(W.button("Cancel", self.reject))
        self.ok_btn = QPushButton("Add this page")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self._accept)
        row.addWidget(self.ok_btn)
        lay.addLayout(row)

        self.format.currentIndexChanged.connect(lambda _i: self._describe())
        self.picture.textChanged.connect(lambda _t: self._describe())
        # ``textEdited`` and not ``textChanged``: the latter also fires when the
        # label rewrites the name, which would look like the user typed it.
        self.stem.textEdited.connect(lambda _t: setattr(self, "_auto_name", False))
        self.stem.textChanged.connect(lambda _t: self._describe())
        if self.label is not None:
            self.label.currentTextChanged.connect(lambda _t: self._label_changed())
            # an editable combo's own typing arrives here, not at the one above
            self.label.editTextChanged.connect(lambda _t: self._label_changed())
            self._label_changed()
        self._describe()

    # ---- the label ----------------------------------------------------
    def _label_changed(self) -> None:
        """Name the page after its label, while the name is still ours."""
        if self.label is None or not self._auto_name:
            return
        # the text, not ``currentData``: a typed label is not in the list yet
        word = texslotslib.clean_stem(self.label.currentText())
        if not word:
            return
        taken = texslotslib.common_taken(os.path.join(self.root, ".depot"))
        self.stem.setText(texslotslib.common_name(word, taken))

    def _browse(self) -> None:
        path, _filt = QFileDialog.getOpenFileName(
            self, "Pick a picture", self.picture.text(), SOURCE_FILTER)
        if not path:
            return
        self.picture.setText(path)
        if not self.stem.text().strip():
            self.stem.setText(pagelib.clean_stem(os.path.basename(path)))

    def _size_of(self, path: str) -> tuple:
        from PySide6.QtGui import QImage

        image = QImage(path)
        return (image.width(), image.height()) if not image.isNull() else (0, 0)

    def _describe(self) -> None:
        path = self.picture.text().strip()
        suffix = self.format.currentData() or ""
        fmt = pagelib.format_row(suffix)
        self.why.setText(fmt["note"])
        if not path or not os.path.isfile(path):
            self.info.setText("Pick a picture to see what it would become.")
            self.ok_btn.setEnabled(False)
            return
        width, height = self._size_of(path)
        name = pagelib.clean_stem(self.stem.text() or os.path.basename(path))
        where = self.place.currentData() or "common"
        leaf = (f"{self.car}/{name}" if where == "car" else f"common/{name}")
        bits = [f"{width}x{height} -> {leaf}{suffix}"]
        if width and height and not (pagelib._is_pot(width)
                                     and pagelib._is_pot(height)):
            bits.append("not a power of two - legal, but the game's own pages "
                        "are, and a mipmapped page wants to be")
        self.info.setText(".  ".join(bits))
        self.ok_btn.setEnabled(bool(name) and bool(fmt["writable"]))

    def _accept(self) -> None:
        try:
            got = pagelib.import_page(
                self.root, self.car, self.picture.text().strip(),
                stem=self.stem.text(), where=self.place.currentData() or "common",
                suffix=self.format.currentData() or pagelib.DEFAULT_SUFFIX)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Add a page", str(exc))
            return
        self.result = got
        self.accept()


class PagePickerDialog(QDialog):
    """Pick the page one region slot samples, and say where that file lives.

    The list is the pages this install has - ``vehicles/common`` and the car's
    own folder - because a page nothing holds is a slot the game draws as
    nothing.  Rows of the same kind as the slot's current page come first: a
    tyre slot wants a tyre, and pointing the glass at a tread is not a cosmetic
    mistake.

    A page that is not here yet is one button away: **Add a page...** encodes a
    picture and drops it in the chosen place, then selects it, so "I need a page
    of my own" does not mean leaving this dialog.
    """

    def __init__(self, rows, parent=None, *, label: str = "", current: str = "",
                 root: str = "", car: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"The page for {label}" if label else "Pick a page")
        self.resize(720, 520)
        self.root = root
        self.car = car
        self._rows = list(rows)
        self._current = current
        self.added: dict = {}

        lay = QVBoxLayout(self)
        note = W.muted(
            "A page is chosen by the part's tag, not by the part: every mesh "
            "ending in _mm_<tag> reads the same region page, so this changes all "
            "of them at once. Give a part its own tag to give it its own page.")
        note.setWordWrap(True)
        lay.addWidget(note)

        top = QHBoxLayout()
        top.addWidget(QLabel("Show"))
        self.place = QComboBox()
        self.place.addItem("shared and this car", "")
        self.place.addItem("shared only (common/)", "common")
        self.place.addItem("this car only", "car")
        self.place.currentIndexChanged.connect(lambda _i: self._fill())
        top.addWidget(self.place)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name")
        self.search.textChanged.connect(lambda _t: self._fill())
        top.addWidget(self.search, 1)
        self.add_btn = QPushButton("Add a page...")
        self.add_btn.setToolTip(
            "Encode a picture into a new page, here or in common/, and select it")
        self.add_btn.clicked.connect(self._add)
        top.addWidget(self.add_btn)
        lay.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("Page", "Where", "Kind", "Size"))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setStretchLastSection(True)
        for column, width in enumerate((380, 180, 100, 90)):
            self.table.setColumnWidth(column, width)
        self.table.doubleClicked.connect(lambda _i: self.accept())
        self.table.itemSelectionChanged.connect(self._buttons)
        lay.addWidget(self.table, 1)

        self.note = W.muted("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(W.button("Cancel", self.reject))
        self.ok_btn = QPushButton("Use this page")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        row.addWidget(self.ok_btn)
        lay.addLayout(row)
        self._fill()

    def _fill(self) -> None:
        text = self.search.text().strip().lower()
        where = self.place.currentData() or ""
        shown = [r for r in self._rows
                 if (not where or r["where"] == where)
                 and (not text or text in r["rel"].lower())]
        # Same kind first, then the shared ones: a shared page costs the car
        # nothing, so it is the better default when both would do.
        shown.sort(key=lambda r: (r.get("kind") != self._kind, r["where"] != "common",
                                  r["rel"].lower()))
        self.table.setRowCount(len(shown))
        pick = -1
        for i, row in enumerate(shown):
            page = QTableWidgetItem(row["rel"])
            page.setToolTip(row["path"])
            self.table.setItem(i, 0, page)
            place = "shared" if row["where"] == "common" else "this car"
            self.table.setItem(i, 1, QTableWidgetItem(place))
            self.table.setItem(i, 2, QTableWidgetItem(row.get("kind") or "-"))
            size = QTableWidgetItem(f"{row.get('bytes', 0):,} B")
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 3, size)
            if self._current and row["rel"] == self._current:
                pick = i
        self._shown = shown
        if pick >= 0:
            self.table.selectRow(pick)
        elif shown:
            self.table.selectRow(0)
        self._buttons()

    @property
    def _kind(self) -> str:
        """The kind of the page this slot holds now, for sorting."""
        for row in self._rows:
            if self._current and row["rel"] == self._current:
                return row.get("kind") or ""
        return ""

    def _buttons(self) -> None:
        has = bool(self.table.selectionModel().selectedRows()) \
            if self.table.selectionModel() else False
        self.ok_btn.setEnabled(has)
        if not has:
            self.note.setText("")
            return
        index = self.table.selectionModel().selectedRows()[0].row()
        row = self._shown[index]
        if row["rel"] == self._current:
            self.note.setText("That is the page this slot reads now.")
        else:
            kind = row.get("kind") or "unclassified"
            place = "every car can name it" if row["where"] == "common" \
                else "only this car can name it"
            self.note.setText(f"{kind}, {row.get('bytes', 0):,} bytes - {place}.")

    def _add(self) -> None:
        box = ImportPageDialog(self.root, self.car, self,
                               where=self.place.currentData() or "common")
        if box.exec() != QDialog.Accepted or not box.result:
            return
        self.added = box.result
        self._rows = pagelib.library(self.root, self.car)
        self.place.setCurrentIndex(0)
        self._fill()
        for i, row in enumerate(self._shown):
            if row["rel"] == self.added["rel"]:
                self.table.selectRow(i)
                break

    def chosen(self) -> str:
        rows = self.table.selectionModel().selectedRows() \
            if self.table.selectionModel() else []
        if not rows:
            return ""
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item is not None else ""


class PartsPane(QWidget):
    """The parts of one car, their materials, and the pages they sample."""

    changed = Signal()
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = None
        self.car = ""
        self._rows: list = []
        self._textures: list = []
        self._library: list = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Model"))
        self.lod = QComboBox()
        self.lod.setMinimumWidth(190)
        self.lod.setToolTip(
            "Which file to read. The wheels, tyres, discs and calipers live in "
            "the shared file, not in the body.")
        self.lod.currentIndexChanged.connect(lambda _i: self.reload())
        top.addWidget(self.lod)
        top.addWidget(QLabel("Filter"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by mesh, material or page")
        self.search.textChanged.connect(lambda _t: self._fill())
        top.addWidget(self.search, 1)
        self.reload_btn = W.button("Reload", self.reload,
                                   tip="Read the car's files again")
        top.addWidget(self.reload_btn)
        lay.addLayout(top)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        # ---- parts ----
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 4, 0, 0)
        pl.setSpacing(6)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("Mesh", "Slot", "Material", "From",
                                              "Page"))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Draggable columns, not ResizeToContents: a mesh name can be 40
        # characters and the one worth reading is the one being searched for.
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setStretchLastSection(True)
        for column, width in enumerate((300, 55, 210, 140, 180)):
            self.table.setColumnWidth(column, width)
        pl.addWidget(self.table, 1)

        pick = QHBoxLayout()
        pick.addWidget(QLabel("Give the selected part"))
        self.material = QComboBox()
        self.material.setToolTip(
            "Only the materials the livery string table has a slot for can be "
            "used - those are the ones the engine can name by number.")
        pick.addWidget(self.material, 1)
        self.apply_btn = W.button("Set material", self._apply, primary=True,
                                  tip="Write this material for the selected part")
        pick.addWidget(self.apply_btn)
        self.page_btn = W.button(
            "Set page...", self._set_page,
            tip="Choose which texture page this part samples, and whether that "
                "file lives in common/ or in this car's own folder. The page is "
                "chosen by the part's tag, so every mesh with the same _mm_<tag> "
                "moves with it.")
        pick.addWidget(self.page_btn)
        self.borrow_btn = W.button(
            "Borrow a shipped name...", self._borrow_name,
            tip="A mesh whose name is not in the string table is skipped by the "
                "engine - the log calls it an unreferenced mesh. The game keeps "
                "a per-car list of part names, so an invented name can never be "
                "drawn; borrowing a shipped name this car leaves empty gives the "
                "part an identity the engine already knows. Rename the mesh in "
                "Blender to the name shown here.")
        pick.addWidget(self.borrow_btn)
        pl.addLayout(pick)
        self.note = W.muted("")
        self.note.setWordWrap(True)
        pl.addWidget(self.note)
        self.tabs.addTab(page, "Parts")

        # ---- textures ----
        page = QWidget()
        tl = QVBoxLayout(page)
        tl.setContentsMargins(0, 4, 0, 0)
        tl.setSpacing(6)
        self.tex_table = QTableWidget(0, 4)
        self.tex_table.setHorizontalHeaderLabels(
            ("Page", "Loaded from", "Where", "Meshes that read it"))
        self.tex_table.verticalHeader().setVisible(False)
        self.tex_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tex_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        head = self.tex_table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setStretchLastSection(True)
        for column, width in enumerate((220, 320, 130, 300)):
            self.tex_table.setColumnWidth(column, width)
        tl.addWidget(self.tex_table, 1)

        trow = QHBoxLayout()
        self.tex_out_btn = W.button(
            "Save this page as a PNG...", self._export_texture,
            tip="Decode the selected page and write it out, so it can be edited "
                "in any paint program")
        trow.addWidget(self.tex_out_btn)
        self.tex_btn = W.button("Put a picture in this page...",
                                self._pick_texture, primary=True,
                                tip="Encode your picture into the page the game "
                                    "loads. It has to be the same size.")
        trow.addWidget(self.tex_btn)
        self.tex_pick_btn = W.button(
            "Use another shipped page...", self._use_shipped,
            tip="Point this slot at a different page from vehicles/common - "
                "another tyre, disc, glass or interior weave. Nothing is "
                "copied: only the livery row changes")
        trow.addWidget(self.tex_pick_btn)
        self.add_page_btn = W.button(
            "Add a page from a picture...", self._add_page,
            tip="Encode a picture into a new page and put it in common/ (shared "
                "with every car) or in this car's own folder. Pick the format: "
                "DXT, ETC1 or ATC can be written, PVRTC cannot.")
        trow.addWidget(self.add_page_btn)
        trow.addStretch(1)
        tl.addLayout(trow)
        self.tex_note = W.muted(
            "The tyres, discs, wheels and interior materials all come from "
            "pages here. Changing one changes every mesh that samples it. "
            "Only the DXT copies can be written; the ETC, ATC and PVRTC copies "
            "of the same picture can be saved out but not put back.")
        self.tex_note.setWordWrap(True)
        tl.addWidget(self.tex_note)
        self.tabs.addTab(page, "Textures")

        self.summary = W.muted("")
        lay.addWidget(self.summary)
        self._idle()

    # ---- content ------------------------------------------------------
    def load(self, editor, car: str) -> None:
        self.editor = editor
        self.car = car
        self._fill_models()
        self.reload()

    def _root(self) -> str:
        """Where to read from: the game folder the editor is on."""
        if self.editor is None or not self.car:
            return ""
        try:
            return self.editor.read_root(self.car)
        except Exception:                        # noqa: BLE001
            return ""

    def _depot(self) -> str:
        if self.editor is None:
            return ""
        return getattr(self.editor, "depot", "") or ""

    def _model_key(self) -> str:
        return self.lod.currentData() or "A"

    def _fill_models(self) -> None:
        """Fill the model dropdown with the files this car actually has."""
        current = self._model_key()
        self.lod.blockSignals(True)
        self.lod.clear()
        root = self._root()
        found = matlib.models(root, self.car) if root and self.car else []
        if not found:
            for key, label in matlib.MODELS[:8]:
                self.lod.addItem(label, key)
        for key, label, _path in found:
            self.lod.addItem(label, key)
        self.lod.blockSignals(False)
        index = self.lod.findData(current)
        self.lod.setCurrentIndex(index if index >= 0 else 0)

    def reload(self) -> None:
        root = self._root()
        if not root or not self.car:
            self._rows = []
            self._textures = []
            self._fill()
            self._idle()
            return
        key = self._model_key()
        try:
            self._rows = matlib.parts(root, self.car, model=key)
        except Exception as exc:                 # noqa: BLE001
            self._rows = []
            self.note.setText(f"Could not read {self.car}: {exc}")
        try:
            # The readers column follows the file on screen: switching to the
            # interior used to leave the body's meshes listed against every
            # page, which reads as "nothing changed" when it did.
            self._textures = texlib.car_pages(root, self.car, model=key)
        except Exception:                        # noqa: BLE001
            self._textures = []
        self._fill()
        self._fill_library()
        self.apply_btn.setEnabled(bool(self._rows))
        self.page_btn.setEnabled(bool(self._rows))
        self.add_page_btn.setEnabled(bool(self.car))
        self.tex_btn.setEnabled(any(r.get("writable") for r in self._textures))
        self.tex_pick_btn.setEnabled(bool(self._textures))
        self.tex_out_btn.setEnabled(bool(self._textures))

    def _fill_library(self) -> None:
        depot = self._depot()
        if not depot:
            return
        if not self._library:
            try:
                self._library = matlib.choices(depot)
            except Exception:                    # noqa: BLE001
                self._library = []
        current = self.material.currentText()
        self.material.blockSignals(True)
        self.material.clear()
        for label, material in self._library:
            if material:
                self.material.addItem(label, material)
            else:
                self.material.addItem(label)
                index = self.material.count() - 1
                item = self.material.model().item(index)
                if item is not None:
                    item.setEnabled(False)
        self.material.blockSignals(False)
        if current:
            self.material.setCurrentText(current)

    def _fill(self) -> None:
        text = self.search.text().strip().lower()
        # Which file each page slot loads, so the Parts tab can say both "which
        # region page" and "which file" - the region name is what the engine
        # resolves, and the file is what a person is actually looking for.
        files = {r["slot"]: r.get("path") or "" for r in self._textures}

        shown = [r for r in self._rows
                 if not text or text in r["mesh"].lower()
                 or text in (r["material"] or "").lower()
                 or text in (r["texture"] or "").lower()]
        self.table.setRowCount(len(shown))
        for i, row in enumerate(shown):
            self.table.setItem(i, 0, QTableWidgetItem(row["mesh"]))
            slot = QTableWidgetItem("" if row["slot"] is None else str(row["slot"]))
            slot.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 1, slot)
            material = QTableWidgetItem(row["material"] or "-")
            if row["material"] and row["material"].startswith("car_paint"):
                material.setToolTip("Car paint")
            self.table.setItem(i, 2, material)
            source = QTableWidgetItem(SOURCES.get(row["source"], row["source"]))
            if row["slot"] is None:
                source.setToolTip(
                    "The engine keeps a per-car list of part names and skips "
                    "anything not on it - logcat says 'contains unreferenced "
                    "mesh'. Borrow a shipped name instead of inventing one.")
            self.table.setItem(i, 3, source)
            page = QTableWidgetItem(row.get("texture") or "-")
            if row.get("texture"):
                loaded = files.get(row.get("texture_slot")) or ""
                page.setToolTip(
                    f"every mesh ending in _mm_{row.get('tag') or '?'} reads this "
                    f"page - that is the whole rule, and it is why a part's own "
                    f"texture row changes nothing"
                    + (f"\n\nloads: {loaded}" if loaded else
                       "\n\nno file named for it yet"))
            else:
                page.setToolTip(
                    "this tag has no region name in the string table, so the "
                    "engine has no page to load for it")
            if row.get("part_row"):
                page.setToolTip(
                    (page.toolTip() or "") +
                    f"\n\nthe part has its own texture row ({row['part_row']}) "
                    f"and the engine ignores it - the page comes from the tag")
            self.table.setItem(i, 4, page)

        pages = [r for r in self._textures
                 if not text or text in r["name"].lower()
                 or text in r["label"].lower()
                 or text in r["path"].lower()
                 or text in (r.get("onDisk") or "").lower()
                 or any(text in m.lower() for m in r["meshes"])]
        self.tex_table.setRowCount(len(pages))
        for i, row in enumerate(pages):
            page = QTableWidgetItem(f"{row['label']}  ({row['name']})")
            page.setToolTip(f"slot {row['slot']}")
            self.tex_table.setItem(i, 0, page)
            named = QTableWidgetItem(row["path"] or "-")
            if row.get("onDisk") and row["onDisk"] != row["path"]:
                named.setToolTip(
                    f"the livery names this one; this install holds the "
                    f"{row.get('family') or 'other'} copy:\n{row['onDisk']}")
            self.tex_table.setItem(i, 1, named)
            where = WHERE.get(row["from"], row["from"])
            if row.get("writable"):
                where += "  (can be written)"
            elif row.get("onDisk"):
                where += "  (read only)"
            self.tex_table.setItem(i, 2, QTableWidgetItem(where))
            meshes = QTableWidgetItem(", ".join(row["meshes"]) or "-")
            meshes.setToolTip("\n".join(row["meshes"]))
            self.tex_table.setItem(i, 3, meshes)

        used = len({r["material"] for r in self._rows if r["material"]})
        skipped = sum(1 for r in self._rows if r["slot"] is None)
        if self._rows:
            text = (f"{len(self._rows)} mesh(es) in {self.lod.currentText()}, "
                    f"{used} different material(s), "
                    f"{len(self._textures)} page slot(s).")
            if skipped:
                text += (f"  {skipped} has no livery slot and is skipped by the "
                         f"engine - see 'Borrow a shipped name'.")
            self.summary.setText(text)
        else:
            self.summary.setText("")
        if not self._rows and self.car:
            self.note.setText(
                f"{self.car} has no {self.lod.currentText()} to read.")

    def _idle(self) -> None:
        empty = not self._rows
        self.apply_btn.setEnabled(not empty)
        self.page_btn.setEnabled(not empty)
        self.add_page_btn.setEnabled(bool(self.car))
        self.tex_btn.setEnabled(False)
        self.tex_pick_btn.setEnabled(False)
        self.tex_out_btn.setEnabled(bool(self._textures))
        self.reload_btn.setEnabled(bool(self.car))
        if not self.car:
            self.note.setText("Select a car to see its parts.")
            self.summary.setText("")

    # ---- editing ------------------------------------------------------
    def _picked_mesh(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows() if \
            self.table.selectionModel() else []
        if not rows:
            return None
        mesh = self.table.item(rows[0].row(), 0)
        if mesh is None:
            return None
        return next((r for r in self._rows if r["mesh"] == mesh.text()), None)

    def _picked_texture(self) -> dict | None:
        rows = self.tex_table.selectionModel().selectedRows() if \
            self.tex_table.selectionModel() else []
        if not rows:
            return None
        item = self.tex_table.item(rows[0].row(), 0)
        if item is None:
            return None
        name = item.toolTip().replace("slot ", "").strip()
        return next((r for r in self._textures if str(r["slot"]) == name), None)

    def _borrow_name(self) -> None:
        """Offer shipped part names this car leaves empty, for a custom part.

        The point is *not* to write anything: the fix happens in the model, by
        renaming the mesh.  What this does is find a name the engine already
        knows and put it on the clipboard, because picking one by hand out of
        2076 entries is how people end up inventing a name that never draws.
        """
        row = self._picked_mesh()
        if row is None:
            QMessageBox.information(
                self, "Borrow a name",
                "Select a part in the table first. The rows marked "
                "\"no slot\" are the ones that need it.")
            return
        root = self._root()
        if not root:
            return
        mesh = row["mesh"]
        bits = mesh.split("_")
        lod = bits[1] if len(bits) > 1 and len(bits[1]) == 1 else "A"
        tag = mesh.rsplit("_mm_", 1)[1] if "_mm_" in mesh else ""
        try:
            names = matlib.free_names(root, self.car, lod=lod, tag=tag, limit=60)
            if not names:
                names = matlib.free_names(root, self.car, lod=lod, limit=60)
            if not names:
                names = matlib.free_names(root, self.car, lod="", limit=60)
        except Exception as exc:                # noqa: BLE001
            QMessageBox.warning(self, "Borrow a name", f"Could not read the "
                                f"string table: {exc}")
            return
        if not names:
            QMessageBox.information(
                self, "Borrow a name",
                "Every shipped name is already in use on this car, so there is "
                "none to borrow. Reuse an existing part's name (and page) "
                "instead of adding one.")
            return
        name, ok = QInputDialog.getItem(
            self, "Borrow a name",
            f"Shipped names this car leaves empty, closest first.\n"
            f"Rename {mesh} to the one you pick (Blender: object name).",
            names, 0, False)
        if not ok or not name:
            return
        QApplication.clipboard().setText(name)
        QMessageBox.information(
            self, "Borrow a name",
            f"Copied to the clipboard:\n\n{name}\n\n"
            "Rename the mesh to it and re-export. It already has a livery "
            "slot, so the Parts tab can give it a material and the Textures "
            "tab a page - neither of which an invented name can do.")

    def _set_page(self) -> None:
        """Choose the page the selected part samples, and where that file lives.

        The target is the part's **region slot**, not its own slot.  The engine
        resolves ``_mm_misc`` to ``ext_misc`` and loads that row; a row on the
        part's own slot is read by nothing.  So the button edits the row that is
        actually consulted, and says how many other meshes move with it - the
        tag is shared, so a page is never private to one part without a tag of
        its own.
        """
        row = self._picked_mesh()
        if row is None:
            QMessageBox.information(self, "Set the page",
                                    "Select a part in the table first.")
            return
        from .. import edit as editlib

        try:
            root = self.editor.for_car(self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Set the page", str(exc))
            return

        slot = row.get("texture_slot")
        tag = row.get("tag") or ""
        if slot is None:
            if not tag:
                QMessageBox.warning(
                    self, "Set the page",
                    f"{row['mesh']} does not end in _mm_<tag>, so there is no "
                    "tag to resolve a page from. Rename the mesh in Blender to "
                    "end in _mm_<something> first.")
                return
            ok = QMessageBox.question(
                self, "Set the page",
                f"No region name holds this tag yet, so the engine has no page "
                f"to load for _mm_{tag}.\n\n"
                f"Add ext_{tag} to the livery string table and give it a page? "
                f"This is how a shipped car's tags work - the name is what "
                f"selects the page.")
            if ok != QMessageBox.Yes:
                return
            try:
                editlib.add_slot_names(root, [f"ext_{tag}"],
                                       log=lambda _m: None)
            except Exception as exc:             # noqa: BLE001
                QMessageBox.critical(self, "Set the page", str(exc))
                return
            try:
                rows = matlib.parts(root, self.car, model=row.get("model") or "a")
            except Exception:                    # noqa: BLE001
                rows = []
            fresh = next((r for r in rows if r["mesh"] == row["mesh"]), None)
            slot = fresh.get("texture_slot") if fresh else None
            if slot is None:
                QMessageBox.warning(self, "Set the page",
                                    f"ext_{tag} was added but the page slot still "
                                    f"does not resolve. Reload and try again.")
                return

        shared = [r["mesh"] for r in self._rows
                  if (r.get("tag") or "") == tag and r["mesh"] != row["mesh"]]
        try:
            pages = pagelib.library(root, self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Set the page", str(exc))
            return
        current = ""
        have = next((r for r in self._textures if r["slot"] == slot), None)
        if have:
            current = have.get("path") or ""
        box = PagePickerDialog(pages, self, label=row.get("texture") or f"_mm_{tag}",
                               current=current, root=root, car=self.car)
        if shared:
            box.setWindowTitle(
                f"The page for _mm_{tag} - {len(shared) + 1} meshes in this file")
        if box.exec() != QDialog.Accepted:
            return
        chosen = box.chosen()
        if not chosen or chosen == current:
            return
        try:
            got = pagelib.point(root, self.car, slot, chosen)
            self.editor.capture(self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Set the page", str(exc))
            return
        moved = len(shared) + 1
        self.status.emit(
            f"{got['slot_name']} now reads {chosen} - {moved} mesh(es) in this "
            f"file end in _mm_{tag} and move with it")
        self.changed.emit()
        self.reload()

    def _apply(self) -> None:
        row = self._picked_mesh()
        if row is None:
            QMessageBox.information(self, "Set material",
                                    "Select a part in the table first.")
            return
        if row["slot"] is None:
            QMessageBox.warning(
                self, "Set material",
                f"{row['mesh']} has no livery slot, so the engine never looks a "
                "material up for it. Renaming the mesh to a name the game knows "
                "is the only way to change what it looks like.")
            return
        material = self.material.currentData() or ""
        if not material:
            return
        if material == row["material"]:
            return
        ok = QMessageBox.question(
            self, "Set material",
            f"Point {row['mesh']} at {material}?\n\n"
            "It is written into the game folder; the Test tab pushes it.")
        if ok != QMessageBox.Yes:
            return
        from .. import edit as editlib

        try:
            root = self.editor.for_car(self.car)
            got = editlib.set_part_material(root, self.car, row["slot"], material)
            self.editor.capture(self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Set material", str(exc))
            return
        self.status.emit(
            f"{row['mesh']} now uses {material}"
            if got["changed"] else f"{row['mesh']} already used {material}")
        self.changed.emit()
        self.reload()

    def _pick_texture(self) -> None:
        row = self._picked_texture()
        if row is None:
            QMessageBox.information(self, "Set the page",
                                    "Select a page in the table first.")
            return
        if not row.get("writable"):
            QMessageBox.warning(
                self, "Set the page",
                f"{row['name']} is held as a "
                f"{(row.get('family') or 'non-DXT').upper()} page here, and this "
                "can only write the DXT family. You can still save it out and "
                "edit it, but it cannot be put back.")
            return
        path, _filt = QFileDialog.getOpenFileName(
            self, f"Pick a picture for {row['label']}", "", PICTURE_FILTER)
        if not path:
            return
        ok = QMessageBox.question(
            self, "Set the page",
            f"Encode {os.path.basename(path)} into {row['name']}?\n\n"
            f"The page is {row['meshes'] and len(row['meshes']) or 'no'} mesh(es) "
            "worth of picture and every mesh that samples it changes with it. "
            "It is written into the game folder; the Test tab pushes it.")
        if ok != QMessageBox.Yes:
            return
        try:
            root = self.editor.for_car(self.car)
            got = texlib.replace(root, row["path"], path, car=self.car)
            self.editor.capture(self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Set the page", str(exc))
            return
        self.status.emit(
            f"{row['label']} rebuilt from {os.path.basename(path)} "
            f"({got['before']:,} -> {got['after']:,} bytes)")
        self.changed.emit()
        self.reload()

    def _use_shipped(self) -> None:
        row = self._picked_texture()
        if row is None:
            QMessageBox.information(self, "Another page",
                                    "Select a page in the table first.")
            return
        try:
            root = self.editor.read_root(self.car)
            rows = texlib.shipped_pages(root, row["path"])
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Another page", str(exc))
            return
        if not rows:
            QMessageBox.information(
                self, "Another page",
                "This install has no pages in vehicles/common to choose from.")
            return
        box = ShippedPageDialog(rows, self, label=row["label"])
        if box.exec() != QDialog.Accepted:
            return
        page = box.chosen()
        if not page:
            return
        ok = QMessageBox.question(
            self, "Another page",
            f"Point {row['label']} at {page}?\n\n"
            "Nothing is copied into the car's folder - only the livery row "
            "changes, so this costs no space and only the livery table is "
            "pushed. Every mesh that samples this slot changes with it.")
        if ok != QMessageBox.Yes:
            return
        from .. import edit as editlib

        try:
            root = self.editor.for_car(self.car)
            got = editlib.set_texture_slot_page(root, self.car, row["slot"], page)
            self.editor.capture(self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Another page", str(exc))
            return
        if not got["changed"]:
            self.status.emit(f"{row['label']} already used {page}")
        else:
            self.status.emit(
                f"{row['label']} now reads {got['page']} "
                f"({got['on_disk']} is the file on disk)")
        self.changed.emit()
        self.reload()

    def _add_page(self) -> None:
        """Encode a picture into a new page, here or in common/.

        Two ways in and they both belong here: a page with no slot yet (art
        nothing names) and a page about to replace one.  So the slot on screen
        decides what happens next - with a slot selected, the new page is
        offered to it; with nothing selected, the page is simply added and the
        Textures tab grows a row for it.
        """
        if not self.car:
            QMessageBox.information(self, "Add a page",
                                    "Select a car first.")
            return
        row = self._picked_texture()
        where = "common"
        if row and row.get("from") == "this car":
            where = "car"
        # ``for_car`` and not ``read_root``: this writes, so the page needs a
        # folder it can be written into.  Importing through a read-only view
        # would drop the page somewhere the row that names it never looks.
        try:
            root = self.editor.for_car(self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Add a page", str(exc))
            return
        box = ImportPageDialog(root, self.car, self, where=where)
        if box.exec() != QDialog.Accepted or not box.result:
            return
        got = box.result
        # The page and its manifest rows are already in the game folder; all
        # that is left is telling the rest of the window about it.
        self.changed.emit()
        self.reload()
        if not row:
            self.status.emit(
                f"{got['rel']} added ({got['width']}x{got['height']}, "
                f"{got['family']}, {got['bytes']:,} bytes)")
            return
        ok = QMessageBox.question(
            self, "Add a page",
            f"{got['rel']} is in the game folder.\n\n"
            f"Point {row['label']} at it now? That writes slot {row['slot']} "
            f"({row['name']}) in this car's livery table.")
        if ok != QMessageBox.Yes:
            self.status.emit(f"{got['rel']} added, not used yet")
            return
        try:
            pagelib.point(root, self.car, row["slot"], got["rel"])
            self.editor.capture(self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Add a page", str(exc))
            return
        self.status.emit(
            f"{row['label']} now reads {got['rel']} "
            f"({got['width']}x{got['height']}, {got['family']})")
        self.changed.emit()
        self.reload()

    def _export_texture(self) -> None:
        row = self._picked_texture()
        if row is None:
            QMessageBox.information(self, "Save the page",
                                    "Select a page in the table first.")
            return
        stem = os.path.basename(row["onDisk"] or row["path"] or row["name"])
        for suffix in texlib.SUFFIXES:
            if stem.lower().endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        path, _filt = QFileDialog.getSaveFileName(
            self, f"Save {row['label']}", stem + ".png",
            "Pictures (*.png *.bmp *.jpg)")
        if not path:
            return
        try:
            root = self.editor.read_root(self.car)
            got = texlib.export(root, row["path"], path, car=self.car)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Save the page", str(exc))
            return
        self.status.emit(
            f"{row['label']} saved as {os.path.basename(path)} "
            f"({got['width']}x{got['height']}, {got['bytes']:,} bytes)")
