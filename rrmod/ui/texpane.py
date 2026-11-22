"""The pages a car keeps in its own folder, and the pictures that can replace them.

A car's own pages - calipers, wheels, lights, the paint mask - are named the way
its models are: ``misc.png`` becomes ``<car>_misc`` in the car's folder, which is
the rule :mod:`rrmod.slots` already applies to ``LOD_A.m3g``.  This pane is the
Cars page's half of that table: it shows what each slot loads now and what a
picture would be written as, and nothing is written until **Save the texture
changes** is pressed - the same split the Build dialog makes, where a picture is
converted on Build.

The Build dialog and this pane write through the same function
(:func:`rrmod.edit.install_textures`), so a page built from a folder and one
saved from here are byte-for-byte the same kind of file.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout,
                               QHeaderView, QMessageBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import edit as editlib
from .. import texslots as texlib
from . import settings as settingslib
from . import widgets as W

#: What a picture can be; a finished page is accepted too, because a user who
#: already converted one should not have to convert it again.
PICTURE_FILTER = ("Pictures and pages (*.png *.jpg *.jpeg *.bmp *.webp *.tga "
                  "*.tif *.tiff *.dxt.dds.z *.dxt.dds.bin *.etc.dds.z "
                  "*.atc.dds.z *.ptc.pvr.z *.rgb.pvr.z);;All files (*)")

COLUMNS = ("Slot", "Loads now", "New picture", "Will be written as")


class CarTexturePane(QWidget):
    """One row per page of the car's own folder, with a picture slot beside it."""

    changed = Signal()
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = None
        self.car = ""
        self.depot = ""
        self._root = ""
        self._rows: list = []
        #: ``{stem: picture}`` - what Save will write, keyed the way the build
        #: dialog keys it so the two tables read the same
        self._pending: dict = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(6)

        lay.addWidget(W.heading("The pages in this car's folder", 2))
        self.note = W.muted(
            "A car's own pages are named the way its models are: misc.png "
            "becomes <car>_misc, wheel.png becomes <car>_wheel. Pick a picture "
            "for a slot and it is converted to the texture format chosen in "
            "Settings when you press Save - not when you pick it.")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        head.setSectionResizeMode(3, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)

        bar = QHBoxLayout()
        self.set_btn = W.button(
            "Set a picture...", self._set_picture,
            tip="Choose the picture this slot should load instead")
        bar.addWidget(self.set_btn)
        self.forget_btn = W.button(
            "Forget this change", self._forget,
            tip="Leave the slot as it is - nothing is written for it")
        self.forget_btn.setEnabled(False)
        bar.addWidget(self.forget_btn)
        bar.addStretch(1)
        self.save_btn = W.button("Save the texture changes", self.save,
                                 primary=True,
                                 tip="Encode every picture chosen here and "
                                     "write it into the car's folder")
        bar.addWidget(self.save_btn)
        lay.addLayout(bar)

        self.summary = W.muted("")
        lay.addWidget(self.summary)
        self.table.itemSelectionChanged.connect(self._picked)

    # ---- loading ------------------------------------------------------
    def load(self, editor, car: str) -> None:
        """Show ``car``'s pages.  A change queued for another car is dropped."""
        same = (car == self.car and editor is self.editor)
        self.editor = editor
        self.car = car or ""
        if not same:
            self._pending = {}
        self.depot = ""
        self._rows = []
        if editor is not None and self.car:
            try:
                root = editor.for_car(self.car)
                # the pages are read from the depot tables, the pictures are
                # written into the install - which is the same folder, but the
                # tables live one level down
                self.depot = os.path.join(root, ".depot")
                self._root = root
            except Exception as exc:             # noqa: BLE001
                self.summary.setText(f"Could not read {self.car}: {exc}")
                self.table.setRowCount(0)
                return
            try:
                self._rows = texlib.car_pages(self.depot, self.car)
            except Exception as exc:             # noqa: BLE001
                self.summary.setText(f"Could not read the pages: {exc}")
                self._rows = []
        self._fill()

    def reload(self) -> None:
        self.load(self.editor, self.car)

    # ---- the table ----------------------------------------------------
    def _fill(self) -> None:
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            stem = row["stem"]
            head = QTableWidgetItem(stem)
            label = dict(texlib.STANDARD).get(stem, "")
            head.setToolTip(
                f"{row['name'] or 'a page of its own'}"
                + (f" - {label}" if label else ""))
            self.table.setItem(i, 0, head)
            page = row.get("path") or ""
            now = QTableWidgetItem(os.path.basename(page) if page else "(none)")
            if page:
                now.setToolTip(page)
            self.table.setItem(i, 1, now)
            chosen = self._pending.get(stem, "")
            cell = QTableWidgetItem(os.path.basename(chosen) if chosen
                                    else "(unchanged)")
            if chosen:
                cell.setToolTip(chosen)
            self.table.setItem(i, 2, cell)
            suffix = texlib.page_suffix(chosen or page) or texlib.family_suffix(
                self.depot, key=settingslib.texture_family())
            target = QTableWidgetItem(texlib.target_rel(self.car, stem, suffix)
                                      if self.car else f"{stem}{suffix}")
            target.setFlags(Qt.ItemIsEnabled)
            if chosen and texlib.is_picture(chosen):
                target.setToolTip("A picture is encoded into this page when you "
                                  "press Save.")
            self.table.setItem(i, 3, target)
        self._picked()
        if not self.car:
            self.summary.setText("Select a car to see the pages it keeps.")
        elif not self._rows:
            self.summary.setText(
                "This car's livery table names no pages of its own, so there is "
                "nothing here to fill.")
        else:
            missing = [r["stem"] for r in self._rows if not r.get("path")]
            self.summary.setText(
                f"{len(self._rows)} page(s) in {self.car}'s folder"
                + (f", {len(missing)} of them not on disk yet "
                   f"({', '.join(missing[:4])})" if missing else "")
                + (f". {len(self._pending)} picture(s) queued - press Save."
                   if self._pending else "."))
        self.save_btn.setEnabled(bool(self._pending))

    def _picked(self) -> None:
        rows = self.table.selectionModel().selectedRows() if \
            self.table.selectionModel() else []
        if not rows:
            self.forget_btn.setEnabled(False)
            return
        stem = self._rows[rows[0].row()]["stem"]
        self.forget_btn.setEnabled(stem in self._pending)

    # ---- acting -------------------------------------------------------
    def _set_picture(self) -> None:
        rows = self.table.selectionModel().selectedRows() if \
            self.table.selectionModel() else []
        if not rows:
            QMessageBox.information(self, "Set a picture",
                                    "Select a slot in the table first.")
            return
        if self.editor is None or not self.car:
            QMessageBox.information(self, "Set a picture",
                                    "Select a car and open a game folder first.")
            return
        row = self._rows[rows[0].row()]
        start = self._pending.get(row["stem"]) or row.get("path") or ""
        path, _f = QFileDialog.getOpenFileName(
            self, f"A picture for {row['stem']}",
            os.path.dirname(start) if start else os.path.expanduser("~"),
            PICTURE_FILTER)
        if not path:
            return
        self._pending[row["stem"]] = path
        self._fill()
        self.table.selectRow(rows[0].row())
        suffix = (texlib.page_suffix(path)
                  or texlib.family_suffix(self.depot,
                                          key=settingslib.texture_family()))
        self.status.emit(
            f"{os.path.basename(path)} will be written as "
            f"{texlib.target_rel(self.car, row['stem'], suffix)} "
            "when you press Save")

    def _forget(self) -> None:
        rows = self.table.selectionModel().selectedRows() if \
            self.table.selectionModel() else []
        if not rows:
            return
        stem = self._rows[rows[0].row()]["stem"]
        if self._pending.pop(stem, None) is not None:
            self._fill()
            self.table.selectRow(rows[0].row())
            self.status.emit(f"{stem} will be left as it is")

    def save(self) -> None:
        """Encode every picture chosen here and write it into the car folder."""
        if self.editor is None or not self.car:
            QMessageBox.information(self, "Save the texture changes",
                                    "Select a car and open a game folder first.")
            return
        items = [{"slot": row["slot"], "stem": row["stem"],
                  "source": self._pending[row["stem"]]}
                 for row in self._rows if self._pending.get(row["stem"])]
        if not items:
            self.status.emit("Nothing to save: no slot has a new picture.")
            return
        pictures = [i for i in items if texlib.is_picture(i["source"])]
        ok = QMessageBox.question(
            self, "Save the texture changes",
            f"Write {len(items)} page(s) into {self.car}'s folder"
            + (f", converting {len(pictures)} picture(s) to the format chosen "
               f"in Settings" if pictures else "")
            + "?\n\nEvery file it replaces is copied to the undo history first, "
              "so Ctrl+Z takes it back.")
        if ok != QMessageBox.Yes:
            return
        editlib.begin(f"Replace {len(items)} texture page(s) of {self.car}")
        try:
            got = editlib.install_textures(
                getattr(self, "_root", "") or self.editor.for_car(self.car),
                self.car, items,
                family_key=settingslib.texture_family(), log=lambda m: None)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Save the texture changes", str(exc))
            return
        self._pending = {}
        self.reload()
        made = len(got.get("written") or [])
        self.status.emit(f"Wrote {made} texture page(s) for {self.car}")
        self.changed.emit()
