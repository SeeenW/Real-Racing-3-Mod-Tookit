"""Pickers for the two things a career series has to name: cars and tracks.

Both dialogs are the same shape - a filter box, a grouped list on the left, a
picture and a few facts on the right - because that is what the user asked for:
"selecting a car should not mean typing an id, and the track should work the same
way".

Pictures come from the game itself:

* cars - ``gui_assets/<size>/car_sales/cars/build_*/`` holds
  ``car_sales_car_<id>.png`` for 511 of the 540 cars (:mod:`rrmod.thumbs`).
* tracks - ``events/daily_race/regular`` and friends hold a card per circuit for
  126 of the 162 track names (:mod:`rrmod.tracks`).

Nothing is downloaded, and a missing picture is a blank tile rather than an
error, because 30 cars and 36 track names genuinely have no art.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QSplitter, QVBoxLayout, QWidget)

from .. import atlas as atlaslib
from .. import maps as maplib
from .. import tracks as tracklib
from .. import thumbs
from . import thumbcache
from . import widgets as W


def _state_dir(depot: str) -> str:
    from .. import depot as depotlib
    return depotlib.state_dir(depot)


def _count_label(text: str = "") -> QLabel:
    """A label holding generated text (``"38 of 540 cars"``), not interface copy."""
    lab = W.muted(text)
    lab.setProperty("rr3_skip_translate", True)
    return lab


def _map_source(depot: str, name: str) -> str:
    """Where a track's picture comes from, in words."""
    if not depot:
        return "-"
    _path, source = maplib.picture_for(depot, name)
    if source == "mine":
        return "the picture you gave it"
    if source == "game":
        return "the game's own card"
    return "none - give it one"


def _scale(pixmap: QPixmap, width: int) -> QPixmap:
    if pixmap.isNull():
        return pixmap
    return pixmap.scaledToWidth(width, Qt.SmoothTransformation)


# ----------------------------------------------------------------- car picker
class CarPickerDialog(QDialog):
    """Choose one or more cars, by manufacturer, with the game's own picture."""

    def __init__(self, inv, parent=None, *, selected=None, multiple: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Pick cars")
        self.resize(920, 620)
        self.inv = inv
        self._selected = [int(x) for x in (selected or [])]
        self._entries = []
        self._shown = []
        self._state = _state_dir(inv.depot) if inv else ""

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name, make, class or id")
        self.search.textChanged.connect(self._apply_filter)
        top.addWidget(self.search, 1)
        self.make_box = QComboBox()
        self.make_box.addItem("All makes", "")
        for make in (inv.makes() if inv else []):
            self.make_box.addItem(make.replace("_", " "), make)
        self.make_box.currentIndexChanged.connect(self._apply_filter)
        top.addWidget(self.make_box)
        self.class_box = QComboBox()
        self.class_box.addItem("All classes", "")
        for name in (inv.classes() if inv else []):
            self.class_box.addItem(name, name)
        self.class_box.currentIndexChanged.connect(self._apply_filter)
        top.addWidget(self.class_box)
        lay.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.ExtendedSelection if multiple
            else QAbstractItemView.SingleSelection)
        self.list.currentItemChanged.connect(lambda *_: self._show())
        self.list.itemSelectionChanged.connect(self._update_ok)
        split.addWidget(self.list)

        side = QWidget()
        slay = QVBoxLayout(side)
        slay.setContentsMargins(0, 0, 0, 0)
        slay.setSpacing(6)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setMinimumHeight(150)
        self.picture.setStyleSheet(
            "background:#f4f4f6; border:1px solid #ddd; border-radius:4px;")
        self.picture.setText("(no picture)")
        slay.addWidget(self.picture)
        self.facts = W.KeyValue()
        slay.addWidget(self.facts)
        slay.addStretch(1)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)

        self.count = _count_label()
        lay.addWidget(self.count)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Use these")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self._load()

    # -- data ---------------------------------------------------------
    def _load(self) -> None:
        self._entries = list(self.inv.cars) if self.inv else []
        self._entries.sort(key=lambda e: ((e.make or ""), e.label.lower()))
        self._apply_filter()

    def _apply_filter(self) -> None:
        text = self.search.text().strip().lower()
        make = self.make_box.currentData() or ""
        klass = self.class_box.currentData() or ""
        self.list.clear()
        self._shown = []
        for entry in self._entries:
            if make and entry.make != make:
                continue
            if klass and (entry.car_class or "") != klass:
                continue
            if text:
                hay = " ".join((entry.label, entry.make or "", entry.model or "",
                                str(entry.car_id), entry.car_class or "",
                                entry.display_name or "")).lower()
                if text not in hay:
                    continue
            self._shown.append(entry)
            item = QListWidgetItem(f"{entry.label}   [{entry.car_id}]")
            item.setData(Qt.UserRole, entry.car_id)
            if entry.car_id in self._selected:
                item.setSelected(True)
            self.list.addItem(item)
        total = len(self._entries)
        if len(self._shown) == total:
            self.count.setText(f"{total} cars")
        else:
            self.count.setText(f"{len(self._shown)} of {total} cars")
        self._update_ok()
        if self.list.count():
            self.list.setCurrentRow(0)

    # -- view ---------------------------------------------------------
    def _entry(self):
        item = self.list.currentItem()
        if item is None:
            return None
        car_id = item.data(Qt.UserRole)
        return next((e for e in self._shown if e.car_id == car_id), None)

    def _show(self) -> None:
        entry = self._entry()
        if entry is None:
            self.picture.setText("(no picture)")
            self.picture.setPixmap(QPixmap())
            self.facts.clear()
            return
        pixmap = thumbcache.pixmap(self.inv.depot, entry.car_id, self._cache_dir())
        if pixmap.isNull():
            self.picture.setText("(no picture)")
            self.picture.setPixmap(QPixmap())
        else:
            self.picture.setPixmap(_scale(pixmap, 300))
        self.facts.update_all({
            "Car": entry.label,
            "Id": entry.car_id,
            "Make": (entry.make or "").replace("_", " "),
            "Class": entry.car_class or "",
            "PR": entry.pr if entry.pr is not None else "",
            "LODs": ", ".join(entry.lods),
            "Paints": entry.liveries,
        })

    def _cache_dir(self) -> str:
        return thumbcache.cache_dir(self._state)

    def _update_ok(self) -> None:
        n = len(self.list.selectedItems())
        ok = self.buttons.button(QDialogButtonBox.Ok)
        ok.setEnabled(n > 0)
        ok.setText("Use this car" if n <= 1 else f"Use these {n} cars")

    # -- result -------------------------------------------------------
    def chosen(self) -> list:
        return [item.data(Qt.UserRole) for item in self.list.selectedItems()]


# --------------------------------------------------------------- track picker
class TrackPickerDialog(QDialog):
    """Choose one or more tracks, grouped by circuit, with the game's card art."""

    def __init__(self, depot: str, tracks, parent=None, *, selected=None,
                 multiple: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Pick tracks")
        self.resize(880, 600)
        self.depot = depot
        self._all = list(tracks)
        self._selected = list(selected or [])
        self._state = _state_dir(depot)
        self._pixmap: dict = {}

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter circuits and layouts")
        self.search.textChanged.connect(self._apply_filter)
        lay.addWidget(self.search)

        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.ExtendedSelection if multiple
            else QAbstractItemView.SingleSelection)
        self.list.currentItemChanged.connect(lambda *_: self._show())
        self.list.itemSelectionChanged.connect(self._update_ok)
        split.addWidget(self.list)

        side = QWidget()
        slay = QVBoxLayout(side)
        slay.setContentsMargins(0, 0, 0, 0)
        slay.setSpacing(6)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setMinimumHeight(160)
        self.picture.setStyleSheet(
            "background:#f4f4f6; border:1px solid #ddd; border-radius:4px;")
        self.picture.setText("(no picture)")
        slay.addWidget(self.picture)
        self.facts = W.KeyValue()
        slay.addWidget(self.facts)
        self.map_btn = W.button(
            "Give it a picture...", self._choose_map,
            tip="The game draws a card for most circuits but stores no layout "
                "map; bring your own picture for the ones without one")
        slay.addWidget(self.map_btn)
        self.map_note = W.muted("")
        self.map_note.setWordWrap(True)
        slay.addWidget(self.map_note)
        slay.addStretch(1)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)

        self.count = _count_label()
        lay.addWidget(self.count)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Use these")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self._apply_filter()

    def _apply_filter(self) -> None:
        text = self.search.text().strip().lower()
        self.list.clear()
        groups = tracklib.group(self._all)
        shown = 0
        for circuit, names in groups.items():
            keep = [n for n in names if not text or text in n.lower()
                    or text in circuit.lower()]
            if not keep:
                continue
            head = QListWidgetItem(circuit)
            head.setFlags(Qt.ItemIsEnabled)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            self.list.addItem(head)
            for name in keep:
                item = QListWidgetItem("    " + (tracklib.time_of_day(name) or name))
                item.setData(Qt.UserRole, name)
                item.setToolTip(name)
                if name in self._selected:
                    item.setSelected(True)
                self.list.addItem(item)
                shown += 1
        total = len(self._all)
        self.count.setText(f"{total} tracks on {len(groups)} circuits"
                           if shown == total else
                           f"{shown} of {total} tracks")
        self._update_ok()

    def _current_name(self) -> str:
        item = self.list.currentItem()
        if item is None:
            return ""
        return item.data(Qt.UserRole) or ""

    def _show(self) -> None:
        name = self._current_name()
        if not name:
            self.picture.setPixmap(QPixmap())
            self.picture.setText("(no picture)")
            self.facts.clear()
            return
        pixmap = self._picture_for(name)
        if pixmap.isNull():
            self.picture.setPixmap(QPixmap())
            self.picture.setText("(the game has no card for this one)")
        else:
            self.picture.setPixmap(_scale(pixmap, 380))
        self.facts.update_all({
            "Track": name,
            "Circuit": tracklib.circuit_of(name),
            "Time of day": tracklib.time_of_day(name) or "-",
            "Map picture": _map_source(self.depot, name),
        })
        self.map_btn.setEnabled(bool(self.depot))

    def _choose_map(self) -> None:
        """Let the user hand in a picture for this circuit's layout."""
        name = self._current_name()
        if not name or not self.depot:
            return
        start = os.path.dirname(maplib.stored(self.depot, name)) or ""
        path, _filter = QFileDialog.getOpenFileName(
            self, f"Picture for {tracklib.circuit_of(name)}", start,
            "Pictures (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)")
        if not path:
            return
        try:
            made = maplib.store(self.depot, name, path)
        except maplib.MapError as exc:
            QMessageBox.warning(self, "Give it a picture", str(exc))
            return
        self._pixmap.pop(name, None)
        self.map_note.setText(
            f"{os.path.basename(made['path'])} now stands in for "
            f"{made['circuit']} ({made['bytes']:,} bytes).")
        self._show()

    def _picture_for(self, name: str) -> QPixmap:
        if name in self._pixmap:
            return self._pixmap[name]
        mine = maplib.stored(self.depot, name) if self.depot else ""
        if mine:
            out = QPixmap(mine)
            if not out.isNull():
                self._pixmap[name] = out
                return out
        out = QPixmap()
        for folder, image in tracklib.picture_names(name):
            if not atlaslib.has(self.depot, folder, image):
                continue
            try:
                w, h, channels, pixels = atlaslib.sprite_at(self.depot, folder, image)
            except Exception:                    # noqa: BLE001 - blank tile is fine
                continue
            path = os.path.join(self._state, "tracks", f"{image}")
            try:
                thumbs.write_png_bytes(path, w, h, channels, pixels)
                out = QPixmap(path)
            except Exception:                    # noqa: BLE001
                out = QPixmap()
            if not out.isNull():
                break
        self._pixmap[name] = out
        return out

    def _update_ok(self) -> None:
        n = len(self.list.selectedItems())
        ok = self.buttons.button(QDialogButtonBox.Ok)
        ok.setEnabled(n > 0)
        ok.setText("Use this track" if n <= 1 else f"Use these {n} tracks")

    def chosen(self) -> list:
        return [item.data(Qt.UserRole) for item in self.list.selectedItems()
                if item.data(Qt.UserRole)]
