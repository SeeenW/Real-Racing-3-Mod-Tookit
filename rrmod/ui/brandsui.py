"""The Brands page: every manufacturer the game files a car under, and the ones we add.

A brand is a string in the spec, so this page is mostly a viewer: it lists the 53
makes the install ships, how many cars each one has, whether it has a logo
picture and whether it has a localised display name.  The interesting part is the
second button - adding a brand - because that is what a new car with a new maker
needs, and what the game's own data has no record of.

Adding a brand is two independent things, and the page keeps them apart:

* **the name** - it only exists once a car's spec says it, so the page records it
  in ``rr3mods.json`` and the car builder offers it in its manufacturer list;
* **the logo** - a picture in ``gui_assets/<size>/common/manufacturer_logos/``.
  The sheets are packed edge to edge, so a new picture becomes a page of its own,
  exactly like a career card.  All three screen sizes get one, fitted to the size
  the shipped logos in that sheet use.

Both go straight into the game folder, and the Test tab is what tells you the
device is behind.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import atlas as atlaslib
from .. import brands as brandlib
from .. import depot as depotlib
from .. import edit as editlib
from .. import thumbs
from . import widgets as W
from .worker import Task

COLUMNS = ("Brand", "Cars", "Logo", "Display name")


def _state_dir(depot: str) -> str:
    return depotlib.state_dir(depot)


class BrandDialog(QDialog):
    """Name a brand and, if the user has one, give it a logo picture."""

    def __init__(self, parent=None, *, name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Add a brand")
        self.resize(560, 260)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        form = QFormLayout()
        form.setSpacing(6)

        self.name = QLineEdit(name)
        self.name.setPlaceholderText("Nonesuch Motors")
        form.addRow("Brand name", self.name)

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.picture = QLineEdit()
        self.picture.setPlaceholderText("leave empty to add the name only")
        rl.addWidget(self.picture, 1)
        browse = W.button("...", self._browse, tip="Choose a PNG or JPEG logo")
        browse.setFixedWidth(32)
        rl.addWidget(browse)
        form.addRow("Logo picture", row)
        lay.addLayout(form)

        self.preview = QLabel("(no picture)")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(90)
        self.preview.setStyleSheet(
            "background:#f4f4f6; border:1px solid #ddd; border-radius:4px;")
        lay.addWidget(self.preview)

        self.note = W.muted(
            "A logo is copied into all three gui_assets sizes, fitted to the "
            "size the shipped logos use. It is written into the game folder "
            "right away, and the Test tab pushes it to the device.")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        lay.addStretch(1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Add it")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self.name.textChanged.connect(self._refresh)
        self.picture.textChanged.connect(self._refresh)
        self._refresh()

    def _browse(self) -> None:
        start = self.picture.text().strip() or os.path.expanduser("~")
        got, _ = QFileDialog.getOpenFileName(
            self, "Choose a logo", start,
            "Pictures (*.png *.jpg *.jpeg *.bmp);;All files (*)")
        if got:
            self.picture.setText(got)

    def _refresh(self) -> None:
        text = self.picture.text().strip()
        if not text or not os.path.isfile(text):
            self.preview.setPixmap(QPixmap())
            self.preview.setText("(no picture)" if not text else "(not a file)")
        else:
            pm = QPixmap(text)
            if pm.isNull():
                self.preview.setPixmap(QPixmap())
                self.preview.setText("(cannot read that picture)")
            else:
                self.preview.setPixmap(
                    pm.scaledToHeight(88, Qt.SmoothTransformation))
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(
            bool(self.name.text().strip()))

    def result_info(self) -> dict:
        return {"name": self.name.text().strip(),
                "picture": self.picture.text().strip()}


class BrandsPage(QWidget):
    """The brands on the left, the chosen one's logo and facts on the right."""

    status = Signal(str)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.inv = None
        self.depot = ""
        self.editor = None
        self.texts = None
        self.rows = []
        self._state = ""
        self._pixmap = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter brands")
        self.search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.search, 1)
        self.only_mine = QCheckBox("Only brands I added")
        self.only_mine.toggled.connect(self._apply_filter)
        bar.addWidget(self.only_mine)
        self.add_btn = W.button("Add a brand...", self.add_brand, primary=True,
                                tip="Name a manufacturer that is not in the "
                                    "game, and give it a logo")
        bar.addWidget(self.add_btn)
        self.logo_btn = W.button("Give it a logo...", self.give_logo,
                                 tip="Add or replace the logo picture of the "
                                     "chosen brand")
        self.logo_btn.setEnabled(False)
        bar.addWidget(self.logo_btn)
        self.remove_btn = W.button("Remove...", self.remove_brand,
                                   tip="Forget a brand this program added")
        self.remove_btn.setEnabled(False)
        bar.addWidget(self.remove_btn)
        self.reload_btn = W.button("Reload", self.reload)
        bar.addWidget(self.reload_btn)
        lay.addLayout(bar)

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
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 220)
        self.table.itemSelectionChanged.connect(self._picked)
        split.addWidget(self.table)

        side = QWidget()
        slay = QVBoxLayout(side)
        slay.setContentsMargins(0, 0, 0, 0)
        slay.setSpacing(6)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setMinimumHeight(140)
        self.picture.setStyleSheet(
            "background:#f4f4f6; border:1px solid #ddd; border-radius:4px;")
        self.picture.setText("(no brand chosen)")
        slay.addWidget(self.picture)
        self.facts = W.KeyValue()
        slay.addWidget(self.facts)
        slay.addWidget(W.muted(
            "The logo is the game's own art: it is cut from "
            "gui_assets/<size>/common/manufacturer_logos. A brand with no logo "
            "still works - the menus fall back to the name."))
        slay.addStretch(1)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)

        self.summary = W.muted("")
        lay.addWidget(self.summary)
        self.log = W.LogPane()
        self.log.setMaximumHeight(110)
        lay.addWidget(self.log)

    # ---- loading -------------------------------------------------------
    def load(self, inv) -> None:
        self.inv = inv
        self.depot = inv.depot if inv else ""
        self.texts = None
        self._state = _state_dir(self.depot) if self.depot else ""
        self._pixmap.clear()
        if not self.depot:
            self.rows = []
            self._fill()
            return
        self.summary.setText("Reading the brand list...")
        self._task = Task(self._gather, parent=self)
        self._task.done.connect(self._loaded)
        self._task.fail.connect(self._failed)
        self._task.start()

    def reload(self) -> None:
        if self.inv is not None:
            self.load(self.inv)

    def _gather(self):
        from rr3lib import texts as textslib

        texts = textslib.Texts.load(self.depot)
        ours = depotlib.brand_names(self.depot)
        return {"texts": texts, "rows": brandlib.brands(self.inv, texts, ours=ours),
                "summary": brandlib.summary(self.inv, texts, ours=ours)}

    def _loaded(self, payload) -> None:
        self.texts = payload["texts"]
        self.rows = payload["rows"]
        s = payload["summary"]
        self.summary.setText(
            f"{s['brands']} brands, {s['with_logo']} with a logo, "
            f"{s['with_text']} with a display name, {s['cars']} cars"
            + (f", {s['ours']} of them mine" if s["ours"] else ""))
        self._fill()

    def _failed(self, text: str) -> None:
        self.summary.setText("Could not read the brand list.")
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
            if row["ours"]:
                font = name.font()
                font.setBold(True)
                name.setFont(font)
                name.setToolTip("A brand this program added")
            self.table.setItem(r, 0, name)
            cars = QTableWidgetItem()
            cars.setData(Qt.DisplayRole, int(row["cars"]))
            cars.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 1, cars)
            self.table.setItem(r, 2, QTableWidgetItem(
                "yes" if row["has_logo"] else "-"))
            shown = QTableWidgetItem(row["shown"])
            if not row["has_text"]:
                shown.setToolTip("The spec carries no CAR_MANUFACTURER_ key; "
                                 "the menus show the make string itself")
            self.table.setItem(r, 3, shown)
        self.table.setSortingEnabled(True)
        if chosen:
            self.select_name(chosen)
        else:
            self._picked()

    def _shown(self) -> list:
        text = self.search.text().strip().lower()
        only = self.only_mine.isChecked()
        out = []
        for row in self.rows:
            if only and not row["ours"]:
                continue
            if text and text not in row["name"].lower() \
                    and text not in row["shown"].lower():
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
            self.picture.setPixmap(QPixmap())
            self.picture.setText("(no brand chosen)")
            self.facts.clear()
            self.logo_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
            return
        self.logo_btn.setEnabled(True)
        # Only a brand this program invented can be forgotten; the game's own 53
        # makes are not ours to delete.
        self.remove_btn.setEnabled(bool(row["ours"]))
        self.remove_btn.setToolTip(
            f"Forget {name}" if row["ours"] else
            f"{name} is one of the game's own makes")
        self.facts.update_all({
            "Brand": row["name"],
            "Shown as": row["shown"],
            "Text key": row["text_key"] if row["has_text"] else "(none shipped)",
            "Cars": row["cars"],
            "Logo picture": row["picture"] if row["has_logo"] else "(none)",
            "Where from": "added by me" if row["ours"] else "the game",
        })
        pixmap = self._logo_for(name)
        if pixmap.isNull():
            self.picture.setPixmap(QPixmap())
            self.picture.setText("(the game has no logo for this brand)")
        else:
            self.picture.setPixmap(
                pixmap.scaled(360, 150, Qt.KeepAspectRatio,
                              Qt.SmoothTransformation))

    def _read_depot(self) -> str:
        """The depot to read logos from: the game folder the editor is on.

        A logo the user just added is written straight into that folder, so
        reading anywhere else showed the old sheet and the new picture looked
        like it had not been added at all.
        """
        if self.editor is not None:
            return self.editor.depot
        return self.depot

    def _logo_for(self, name: str) -> QPixmap:
        if name in self._pixmap:
            return self._pixmap[name]
        out = QPixmap()
        try:
            w, h, channels, pixels = brandlib.logo(self._read_depot(), name)
        except brandlib.BrandError:
            self._pixmap[name] = out
            return out
        path = os.path.join(self._state or ".", "brands",
                            brandlib.picture_of(name))
        try:
            thumbs.write_png_bytes(path, w, h, channels, pixels)
            out = QPixmap(path)
        except Exception:                        # noqa: BLE001 - a blank tile is fine
            out = QPixmap()
        self._pixmap[name] = out
        return out

    # ---- adding --------------------------------------------------------
    def add_brand(self) -> None:
        if not self.depot:
            return
        dlg = BrandDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        info = dlg.result_info()
        name = info["name"]
        if not name:
            return
        if any(row["name"] == name for row in self.rows):
            QMessageBox.information(
                self, "Add a brand",
                f"The game already files cars under {name}. Use 'Give it a "
                f"logo...' to change its picture.")
            return
        self._write(name, info["picture"], registering=True)

    def give_logo(self) -> None:
        name = self._picked_name()
        if not name or not self.depot:
            return
        got, _ = QFileDialog.getOpenFileName(
            self, f"Choose a logo for {name}", os.path.expanduser("~"),
            "Pictures (*.png *.jpg *.jpeg *.bmp);;All files (*)")
        if not got:
            return
        self._write(name, got, registering=True)

    def _write(self, name: str, picture: str, *, registering: bool) -> None:
        if self.editor is None:
            QMessageBox.critical(
                self, "No game folder",
                "The window did not hand this page a game folder, so there is "
                "nowhere to write the logo.")
            return
        staged = []
        if picture:
            # One undo step for the whole logo, not one per list it touches.
            # ``sync_file`` opens a step only when none is open, so without this
            # the atlas and the page would be filed under whatever edit ran
            # before - and undoing the logo would undo that car edit too.
            editlib.begin()
            try:
                out_dir = self.editor.for_gfx()
                made = brandlib.add_logo(
                    self.depot, name, picture, out_dir=out_dir,
                    backup=lambda path: editlib.backup_before_write(
                        self.editor.root, path),
                    log=self.log.note)
            except Exception as exc:             # noqa: BLE001
                QMessageBox.critical(self, "The logo", str(exc)[:2000])
                return
            # The sheet and the page it points at are two files in a folder no
            # car edit walks, and they are claimed by
            # ``asset_list_gui_assets_core.txt``.  Writing them without teaching
            # that list about the new page is what made the game decide a
            # download was in order - it sees a file on disk that no list
            # mentions.  So every one of them goes through sync_file.
            try:
                for local, rel in made["files"]:
                    # ``sync_file`` speaks game paths (``/gui_assets/...``); the
                    # logo helper hands back install-relative ones
                    # (``.depot/gui_assets/...``) because that is where it wrote.
                    game_path = ("/" + rel[len(".depot/"):]
                                 if rel.startswith(".depot/") else "/" + rel)
                    editlib.sync_file(self.editor.root, name="",
                                      rel_path=game_path, local=local,
                                      create=True)
            except Exception as exc:             # noqa: BLE001
                QMessageBox.critical(
                    self, "The logo",
                    f"The picture was written but its asset list could not be "
                    f"updated, so the game would want to download it again:\n\n"
                    f"{str(exc)[:1500]}")
                return
            staged = list(made["files"])
            self.log.ok(f"{made['picture']}: {made['width']}x{made['height']} "
                        f"into {made['sizes']} sheet(s), "
                        f"{len(staged)} file(s) written")
        if registering:
            depotlib.register_brand(self.depot, name,
                                    logo=brandlib.picture_of(name) if picture else "")
            self.log.note(f"{name} is on my list of brands now")
        # The atlas index is cached per (depot, folder, size) for the life of the
        # process, so a new picture would keep showing as missing until restart.
        atlaslib.forget()
        self._pixmap.clear()
        self.status.emit(f"Brand {name} written into the game folder")
        self.changed.emit()
        self.reload()

    def remove_brand(self) -> None:
        """Forget a brand this program added, and take its picture out again.

        Only brands this program invented can be removed - the 53 the studio
        ships are part of the game's data and deleting the record would just make
        the list lie.  Removing one does not touch any car: a car whose spec says
        ``Nonesuch Motors`` keeps saying it, and will keep offering that maker.
        """
        name = self._picked_name()
        row = self._row_of(name) if name else None
        if row is None or self.editor is None:
            return
        if not row["ours"]:
            QMessageBox.information(
                self, "Remove a brand",
                f"{name} is one of the game's own makes, so it is not this "
                f"program's to remove. A car that uses it keeps using it.")
            return
        cars = int(row["cars"])
        extra = (f"\n\n{cars} car(s) still name it as their maker; they are not "
                 f"changed." if cars else "")
        ok = QMessageBox.question(
            self, "Remove a brand",
            f"Forget {name}?{extra}\n\nIts logo picture is left on disk - a "
            f"share may still use it.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ok != QMessageBox.Yes:
            return
        depotlib.unregister_brand(self.depot, name)
        self.log.note(f"{name} is off my list of brands")
        self.status.emit(f"Brand {name} removed")
        self.changed.emit()
        self.reload()

    # ---- helpers -------------------------------------------------------
    def attach_device(self, device) -> None:
        if self.editor is not None:
            self.editor.set_device(device)


def selftest(depot: str) -> int:
    """Read the list without Qt, for the CLI and for the tests."""
    from rr3lib import texts as textslib

    inv = depotlib.scan(depotlib.default_install() or depot)
    texts = textslib.Texts.load(inv.depot)
    rows = brandlib.brands(inv, texts, ours=depotlib.brand_names(inv.depot))
    for row in rows[:10]:
        print(f"  {row['shown']:<24} cars={row['cars']:<4} "
              f"logo={row['has_logo']} text={row['has_text']}")
    print(f"  {len(rows)} brand(s)")
    return 0
