"""The car list: vanilla on one side, ours on the other, details underneath.

Two tables rather than one, because the two halves have different permissions -
the game's own cars may be modified but never deleted, ours may be deleted - and
because that is how the user asked for it.  A third, normally empty table catches
cars that are neither: they were put there by some other tool and the manager
refuses to guess which side they belong to until told.

Nothing here writes to the install.  Every action that does goes through
:mod:`rrmod.edit`, and every one of those asks first.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import depot as depotlib
from .. import edit as editlib
from .. import share as sharelib
from . import animui, materialui, paintui, suspui, texpane
from . import settings as settingslib
from . import thumbcache
from . import widgets as W
from .worker import Task

COLUMNS = ("Car", "Id", "Class", "LODs", "Paints", "Size")

#: starting width of each column, in the order of COLUMNS.  The user can drag
#: them afterwards; these only decide what the first window looks like.
WIDTHS = (330, 50, 55, 110, 55, 80)


def _mm_pair(pair) -> str:
    """``(0.010, 0.015)`` -> ``"10 / 15 mm"``; the game shows these in millimetres."""
    if not pair:
        return ""
    return f"{pair[0] * 1000:.0f} / {pair[1] * 1000:.0f} mm"


def _number_item(value: int) -> QTableWidgetItem:
    """A cell that shows a number but sorts by it, not by its text."""
    item = QTableWidgetItem()
    item.setData(Qt.DisplayRole, int(value))
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


class CarTable(QTableWidget):
    """A read only table of :class:`CarEntry`, sorted by car name."""

    picked = Signal(object)                       # CarEntry or None
    widths_changed = Signal(list)                 # the user dragged a column

    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.setHorizontalHeaderLabels(COLUMNS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        # Interactive, not Stretch/ResizeToContents: the car names are long and a
        # fixed layout either clips them or leaves no room for the numbers.  The
        # header menu offers the two automatic layouts for when dragging is
        # tedious.
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(False)
        h.setSectionsMovable(False)
        h.setContextMenuPolicy(Qt.CustomContextMenu)
        h.customContextMenuRequested.connect(self._header_menu)
        for index, width in enumerate(WIDTHS):
            self.setColumnWidth(index, width)
        h.sectionResized.connect(lambda *_: self.widths_changed.emit(self.widths()))
        self._entries = []
        self.itemSelectionChanged.connect(self._emit)

    # ---- column layout ------------------------------------------------
    def _header_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction("Fit to contents", self.fit_contents)
        menu.addAction("Widen the car column", self.widen_name)
        menu.addAction("Reset column widths", self.reset_widths)
        menu.exec(self.horizontalHeader().mapToGlobal(pos))

    def fit_contents(self) -> None:
        self.resizeColumnsToContents()

    def widen_name(self) -> None:
        """Give the name column whatever the others do not need."""
        spare = self.viewport().width() - sum(
            self.columnWidth(i) for i in range(1, self.columnCount()))
        self.setColumnWidth(0, max(160, spare - 4))

    def reset_widths(self) -> None:
        for index, width in enumerate(WIDTHS):
            self.setColumnWidth(index, width)

    def widths(self) -> list:
        return [self.columnWidth(i) for i in range(self.columnCount())]

    def set_widths(self, widths) -> None:
        for index, width in enumerate(list(widths)[:self.columnCount()]):
            if isinstance(width, int) and width > 20:
                self.setColumnWidth(index, width)

    def set_entries(self, entries) -> None:
        keep = self.selected_name()
        self.setSortingEnabled(False)
        self.setRowCount(0)
        self._entries = list(entries)
        self.setRowCount(len(self._entries))
        for row, e in enumerate(self._entries):
            self.setItem(row, 0, QTableWidgetItem(e.label))
            # A QTableWidgetItem sorts by whatever sits in DisplayRole, and a
            # string sorts "10" before "9".  Storing the number itself keeps the
            # id and paint columns in numeric order while still showing text.
            self.setItem(row, 1, _number_item(e.car_id))
            self.setItem(row, 2, QTableWidgetItem(getattr(e, "car_class", "") or "-"))
            self.setItem(row, 3, QTableWidgetItem("".join(e.lods) or "-"))
            self.setItem(row, 4, _number_item(e.liveries))
            size = QTableWidgetItem(f"{e.body_bytes / 1048576:.1f} MB")
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            size.setData(Qt.DisplayRole, e.body_bytes)
            self.setItem(row, 5, size)
            item = self.item(row, 0)
            item.setData(Qt.UserRole, e.name)
            if e.modified:
                item.setText(e.label + "  (changed)")
                f = QFont()
                f.setItalic(True)
                item.setFont(f)
            if not e.has_body:
                item.setForeground(Qt.gray)
                item.setToolTip("No body model in the depot - nothing to edit")
            else:
                item.setToolTip(e.name)
        self.setSortingEnabled(True)
        if keep:
            self.select_name(keep)

    def selected_name(self) -> str:
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        if not rows:
            return ""
        item = self.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item else ""

    def select_name(self, name: str) -> None:
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item and item.data(Qt.UserRole) == name:
                self.selectRow(row)
                return

    def _emit(self):
        name = self.selected_name()
        hit = next((e for e in self._entries if e.name == name), None)
        self.picked.emit(hit)


class DetailPane(QWidget):
    """Everything known about the selected car."""

    changed = Signal()
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inv = None
        self._entry = None
        self.editor = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # The game draws every car it sells, so the picture costs nothing to
        # find: ``car_sales_car_<id>.png`` in the car_sales atlas.  It sits
        # beside the name rather than in a tab, because "is this the car I
        # think it is" is the first question the pane has to answer.
        head = QHBoxLayout()
        head.setSpacing(10)
        # The picture gets a column of its own: the game's own tile for a car
        # this program did not build, and a button under it for one it did - a
        # car with no sprite falls back to a placeholder in the showroom, which
        # is the one thing a mod car cannot fake.
        pic_col = QVBoxLayout()
        pic_col.setSpacing(4)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setFixedWidth(240)
        self.picture.setMinimumHeight(108)
        self.picture.setMaximumHeight(130)
        self.picture.setStyleSheet(
            "background:#f4f4f6; border:1px solid #e2e2e6; border-radius:4px")
        pic_col.addWidget(self.picture)
        self.pic_btn = W.button(
            "Set the preview picture...", self._set_picture,
            tip="Draw a picture of this car into the showroom atlases")
        pic_col.addWidget(self.pic_btn)
        head.addLayout(pic_col)

        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.title = QLabel("No car selected")
        f = self.title.font()
        f.setPointSize(13)
        f.setWeight(QFont.DemiBold)
        self.title.setFont(f)
        titles.addWidget(self.title)

        self.pills = QHBoxLayout()
        self.pills.setSpacing(6)
        self.pills.addStretch(1)
        titles.addLayout(self.pills)
        titles.addStretch(1)
        head.addLayout(titles, 1)
        lay.addLayout(head)
        self._pill_widgets = []

        self.tabs = QTabWidget()
        self.kv = W.KeyValue()
        self.lods = QTableWidget(0, 2)
        self.lods.setHorizontalHeaderLabels(("File", "Size"))
        self.lods.verticalHeader().setVisible(False)
        self.lods.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lods.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.lods.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)

        for title, widget in (("Overview", self.kv), ("Files", self.lods)):
            wrap = QWidget()
            v = QVBoxLayout(wrap)
            v.setContentsMargins(0, 4, 0, 0)
            v.addWidget(widget)
            self.tabs.addTab(wrap, title)

        self.paints = paintui.PaintsPane()
        self.paints.changed.connect(self.changed)
        self.paints.status.connect(self.status)
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 4, 0, 0)
        v.addWidget(self.paints)
        self.tabs.addTab(wrap, "Paints")

        # The car's own pages - calipers, wheels, lights, the paint mask - are
        # named the way its models are, so they get the same kind of table the
        # Build dialog has.  A picture is converted on Save here, on Build
        # there; the same function does both.
        self.textures = texpane.CarTexturePane()
        self.textures.changed.connect(self.changed)
        self.textures.status.connect(self.status)
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 4, 0, 0)
        v.addWidget(self.textures)
        self.tabs.addTab(wrap, "Textures")

        self.parts = materialui.PartsPane()
        self.parts.changed.connect(self.changed)
        self.parts.status.connect(self.status)
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 4, 0, 0)
        v.addWidget(self.parts)
        self.tabs.addTab(wrap, "Parts")

        self.anim = animui.AnimPane()
        self.anim.changed.connect(self.changed)
        self.anim.status.connect(self.status)
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 4, 0, 0)
        v.addWidget(self.anim)
        self.tabs.addTab(wrap, "Animation")

        # Ride height sits beside the animation tab rather than in the Build
        # dialog: the up half is a per-car number in a shared table, and this is
        # the only page that already knows which car is selected.
        self.ride = suspui.SuspensionPane()
        self.ride.changed.connect(self.changed)
        self.ride.status.connect(self.status)
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 4, 0, 0)
        v.addWidget(self.ride)
        self.tabs.addTab(wrap, "Ride height")
        lay.addWidget(self.tabs, 1)

    changed = Signal()
    status = Signal(str)

    # ---- content ------------------------------------------------------
    def show_entry(self, inv, entry) -> None:
        self._inv = inv
        self._entry = entry
        for w in self._pill_widgets:
            w.setParent(None)
        self._pill_widgets = []
        if entry is None:
            self.title.setText("No car selected")
            self.picture.setPixmap(QPixmap())
            self.picture.setText("")
            self.kv.clear()
            self.lods.setRowCount(0)
            self.paints.load(self.editor, "")
            self.textures.load(self.editor, "")
            self.parts.load(self.editor, "")
            self.anim.load("", "")
            self.ride.load("", "")
            return
        self.title.setText(entry.label)
        self._show_picture(inv, entry)
        self._add_pill(entry.name, "vanilla")
        if entry.status == "mod":
            self._add_pill("MOD", "mod")
        elif entry.status == "unknown":
            self._add_pill("unmanaged", "unknown")
        if entry.modified:
            self._add_pill("files changed", "modified")
        if entry.aero_flag:
            self._add_pill("aero: " + entry.aero_flag.split(",")[0].strip(), "mod")
        if entry.shares_body:
            self._add_pill("borrows a body", "unknown")

        detail = {}
        try:
            detail = depotlib.car_detail(inv, entry)
        except Exception as exc:                 # noqa: BLE001
            detail = {"error": str(exc)}
        rows = {
            "Car id": entry.car_id,
            "Folder": entry.name,
            "Spec": entry.spec_stem,
            "Appearance": f"#{entry.appearance_id}",
            "Display key": entry.display_key,
            "LODs": ", ".join(entry.lods) or "none",
            "Body from": (entry.model_folder
                          if entry.shares_body else "(this car's own folder)"),
            "Body size": f"{entry.body_bytes / 1048576:.2f} MB" if entry.body_bytes else "",
            "Paint schemes": entry.liveries,
            "Livery textures": entry.livery_textures,
            "Tyre diameter": detail.get("tyre_diameter"),
            "Tyre radius": detail.get("tyre_radius"),
            "Ride height up": _mm_pair(detail.get("suspension_travel")),
            "Ride height down": _mm_pair(detail.get("suspension_down")),
            "Wheel sizes": detail.get("wheel_sizes"),
            "Paint colour": detail.get("paint"),
            "Material overrides": detail.get("material_overrides"),
            "Aero": entry.aero_flag,
            "Note": entry.note,
            "Error": detail.get("error") or detail.get("livery_error"),
        }
        self.kv.update_all(rows)

        files = sorted(entry.sizes.items())
        self.lods.setRowCount(len(files))
        for i, (lod, size) in enumerate(files):
            self.lods.setItem(i, 0, QTableWidgetItem(f"{entry.name}_{lod.lower()}.m3g"))
            item = QTableWidgetItem(f"{size / 1048576:.2f} MB")
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.lods.setItem(i, 1, item)

        self.paints.load(self.editor, entry.name)
        self.textures.load(self.editor, entry.name)
        self.parts.load(self.editor, entry.name)
        self.anim.load(inv.root if inv else "", entry.name)
        self.ride.load(inv.root if inv else "", entry.name, entry.car_id)

    def _show_picture(self, inv, entry) -> None:
        """Put the game's own picture of this car beside its name."""
        self.picture.setPixmap(QPixmap())
        self.picture.setText("")
        if inv is None or entry is None:
            return
        try:
            state = depotlib.state_dir(inv.depot)
            pixmap = thumbcache.pixmap(inv.depot, entry.car_id,
                                       thumbcache.cache_dir(state))
        except Exception:                        # noqa: BLE001 - a missing tile is fine
            pixmap = QPixmap()
        if pixmap.isNull():
            self.picture.setText("no picture")
            return
        self.picture.setPixmap(pixmap.scaled(
            self.picture.width() - 4, self.picture.maximumHeight() - 4,
            Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _set_picture(self) -> None:
        """Draw the user's own picture into the showroom atlases for this car.

        The game cuts ``car_sales_car_<id>.png`` out of the car sales sheets, so
        a car this program built has no tile until one is written.  A car that
        already has one keeps its place: the new picture is drawn into the same
        rectangle of the same page, so nothing else in the atlas moves.
        """
        if self.editor is None or self._entry is None:
            QMessageBox.information(
                self, "Preview picture",
                "Select a car and open a game folder first.")
            return
        name = self._entry.name
        got, _ = QFileDialog.getOpenFileName(
            self, f"Choose a preview picture for {name}",
            os.path.expanduser("~"),
            "Pictures (*.png *.jpg *.jpeg *.bmp *.tga);;All files (*)")
        if not got:
            return
        ok = QMessageBox.question(
            self, "Preview picture",
            f"Draw {os.path.basename(got)} as {name}'s showroom picture, in "
            f"every screen size the install carries?\n\n"
            "It is written into the game folder, and every file it replaces is "
            "copied to the undo history first. The Test tab pushes it.")
        if ok != QMessageBox.Yes:
            return
        from .. import edit as editlib
        from .. import thumbs as thumbslib

        # One undo step for the whole picture, not one per page: the atlases and
        # the pages they name have to come back together or the showroom shows a
        # sprite nothing points at.
        editlib.begin(f"Set the preview picture of {name}")
        try:
            done = thumbslib.set_picture(
                self.editor.root, self._entry.car_id, got,
                backup=lambda path: editlib.backup_before_write(
                    self.editor.root, path))
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Preview picture", str(exc)[:1500])
            return
        # The atlases and the pages they name are claimed by the gui_assets asset
        # list.  A page the list does not mention is a page the game decides to
        # download again, which is what the logo writer had to learn too.
        try:
            for local, rel in done["files"]:
                editlib.sync_file(self.editor.root, name="", rel_path=rel,
                                  local=local, create=True)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(
                self, "Preview picture",
                f"The picture was written but its asset list could not be "
                f"updated, so the game would want to download it again:\n\n"
                f"{str(exc)[:1200]}")
            return
        skipped = done.get("skipped") or []
        self.status.emit(
            f"{name}: picture written for {done['sizes']} screen size(s)"
            + (f", {len(skipped)} skipped" if skipped else ""))
        self.changed.emit()
        self._show_picture(self._inv, self._entry)

    def _add_pill(self, text: str, kind: str) -> None:
        p = W.pill(text, kind)
        self.pills.insertWidget(self.pills.count() - 1, p)
        self._pill_widgets.append(p)


class CarsPage(QWidget):
    """The whole cars tab."""

    changed = Signal()                            # something on disk changed
    status = Signal(str)
    #: The car now selected, by name; empty when the selection was cleared.
    #: The Test page scans one car at a time, and this is how it learns which.
    picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.inv = None
        self._task = None
        self.editor = None
        self._refreshing = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name, make or model")
        self.search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.search, 1)
        self.only_editable = QCheckBox("Only cars with a body model")
        self.only_editable.toggled.connect(self._apply_filter)
        bar.addWidget(self.only_editable)
        self.own_geometry = QCheckBox("Only cars with their own geometry")
        self.own_geometry.setToolTip(
            "Hide the 76 cars that borrow another car's body through "
            "appearances.link.nct - editing their geometry means editing the "
            "car they borrow from")
        self.own_geometry.toggled.connect(self._apply_filter)
        bar.addWidget(self.own_geometry)
        self.refresh_btn = W.button("Rescan", self.rescan, tip="Read the install again")
        bar.addWidget(self.refresh_btn)
        lay.addLayout(bar)

        # a second row of drop downs: 540 cars is too many to find by typing a
        # name when you only know the maker, or the class you want to race in
        bar2 = QHBoxLayout()
        bar2.addWidget(W.muted("Make"))
        self.make_box = QComboBox()
        self.make_box.setMinimumWidth(150)
        self.make_box.currentIndexChanged.connect(self._apply_filter)
        bar2.addWidget(self.make_box)
        bar2.addWidget(W.muted("Class"))
        self.class_box = QComboBox()
        self.class_box.setMinimumWidth(90)
        self.class_box.currentIndexChanged.connect(self._apply_filter)
        bar2.addWidget(self.class_box)
        bar2.addWidget(W.muted("Show"))
        self.status_box = QComboBox()
        self.status_box.addItem("Everything", "")
        self.status_box.addItem("Cars the game shipped", "vanilla")
        self.status_box.addItem("Cars this program installed", "mod")
        self.status_box.addItem("Cars it has not decided about", "unknown")
        self.status_box.currentIndexChanged.connect(self._apply_filter)
        bar2.addWidget(self.status_box)
        self.clear_btn = W.button("Clear filters", self.clear_filters)
        bar2.addWidget(self.clear_btn)
        bar2.addStretch(1)
        self.count_label = W.muted("")
        bar2.addWidget(self.count_label)
        lay.addLayout(bar2)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        lists = QWidget()
        lv = QVBoxLayout(lists)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)

        # One list, not "the game's cars" beside "my mods".  The program has no
        # use for the difference any more: everything here is a car you can look
        # at, edit, publish whole or delete, and where a car came from is a
        # sentence in its detail pane rather than a separate table to hunt
        # through.  ``self.cars`` keeps the old ``vanilla`` name as an alias so
        # the rest of the file and the tests do not have to care.
        self.cars = CarTable()
        self.cars.picked.connect(self._picked)
        self.vanilla = self.cars
        lv.addWidget(self.cars, 1)

        # Kept as empty, hidden widgets: ``mods`` and ``unknown`` are still
        # assigned to by nothing, but the tests and a few call sites reach for
        # them, and an empty table costs nothing.
        self.mods = CarTable()
        self.mods.setVisible(False)
        self.mods.picked.connect(self._picked)
        self.unknown = CarTable()
        self.unknown.setVisible(False)
        self.unknown.picked.connect(self._picked)
        self.unknown_label = W.heading("Unmanaged", 3)
        self.unknown_label.setVisible(False)
        for table in (self.vanilla, self.mods, self.unknown):
            table.widths_changed.connect(self._save_widths)

        split.addWidget(lists)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(6)
        self.detail = DetailPane()
        self.detail.changed.connect(self.changed)
        self.detail.status.connect(self.status)
        rv.addWidget(self.detail, 1)
        actions = QHBoxLayout()
        self.backup_btn = W.button(
            "Back up this car...", self._backup,
            tip="Write a zip holding this car's files and its parameters, so it "
                "can be put back exactly as it is now")
        self.backup_btn.setEnabled(False)
        actions.addWidget(self.backup_btn)
        self.rollback_btn = W.button(
            "Roll back from backup...", self._rollback,
            tip="Put a car back from one of those zips - every file it holds, "
                "replacing what is there now")
        actions.addWidget(self.rollback_btn)
        actions.addStretch(1)
        self.adopt_btn = W.button("Adopt as mod", self._adopt,
                                  tip="Treat an unmanaged car as mine, so it can be edited or deleted")
        self.adopt_btn.setEnabled(False)
        actions.addWidget(self.adopt_btn)
        self.delete_btn = W.button("Delete mod", self._delete,
                                   tip="Remove the car, its spec, its paint schemes and its manifests")
        self.delete_btn.setEnabled(False)
        actions.addWidget(self.delete_btn)
        rv.addLayout(actions)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 4)
        lay.addWidget(split, 1)

        self.summary = W.muted("No install loaded.")
        lay.addWidget(self.summary)
        self._restore_widths()

    # ---- column widths ------------------------------------------------
    def _save_widths(self, widths) -> None:
        """Remember the layout so the next start looks the way it was left."""
        settingslib.set("car_columns", ",".join(str(int(w)) for w in widths))

    def _restore_widths(self) -> None:
        raw = str(settingslib.get("car_columns", "") or "")
        if not raw:
            return
        try:
            widths = [int(part) for part in raw.split(",")]
        except ValueError:
            return
        for table in (self.vanilla, self.mods, self.unknown):
            table.set_widths(widths)

    def _wire_editor(self) -> None:
        """Hand the working copy to every pane that can write through it."""
        self.detail.editor = self.editor
        self.detail.paints.editor = self.editor
        self.detail.parts.editor = self.editor
        self.detail.anim.editor = self.editor

    # ---- loading ------------------------------------------------------
    def load(self, inv) -> None:
        self.inv = inv
        self._wire_editor()
        self._fill_boxes()
        self._apply_filter()
        self.summary.setText(
            f"{inv.summary()}  |  scanned in {inv.scan_seconds:.2f} s  |  "
            f"next free id {inv.free_id()}")
        if inv.warnings:
            self.status.emit(f"{len(inv.warnings)} warning(s) while scanning")

    def rescan(self) -> None:
        if self.inv is None:
            return
        root = self.inv.root
        self.refresh_btn.setEnabled(False)
        self.status.emit("Scanning...")
        self._task = Task(depotlib.scan, root, parent=self)
        self._task.done.connect(self._rescanned)
        self._task.fail.connect(self._scan_failed)
        self._task.start()

    def _rescanned(self, inv) -> None:
        self.refresh_btn.setEnabled(True)
        self.load(inv)
        self.status.emit("Rescan finished")
        self.changed.emit()

    def refresh_detail(self) -> None:
        """Re-read the selected car, because what is on disk may have changed.

        Undo throws the working copy away, and every pane below the car list
        reads through that copy: the paint list, the parts list and the
        animation page.  Without this the detail page kept showing the edit that
        had just been discarded, which is what made undo look like it had only
        half worked.
        """
        if self._refreshing:
            return
        entry = self.detail._entry
        if entry is None or self.inv is None:
            return
        self._refreshing = True
        try:
            self._wire_editor()
            self.detail.show_entry(self.inv, entry)
        finally:
            self._refreshing = False

    def _scan_failed(self, text: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status.emit("Scan failed")
        QMessageBox.critical(self, "Scan failed", text[:2000])

    # ---- filtering ----------------------------------------------------
    def _fill_boxes(self) -> None:
        """Fill the make and class drop downs from the inventory, keeping choice."""
        if self.inv is None:
            return
        keep_make = self.make_box.currentData() or ""
        keep_class = self.class_box.currentData() or ""
        self.make_box.blockSignals(True)
        self.class_box.blockSignals(True)
        self.make_box.clear()
        self.make_box.addItem("All makes", "")
        for make in self.inv.makes():
            self.make_box.addItem(make, make)
        self.class_box.clear()
        self.class_box.addItem("All classes", "")
        for name in self.inv.classes():
            self.class_box.addItem(name, name)
        for box, wanted in ((self.make_box, keep_make), (self.class_box, keep_class)):
            index = box.findData(wanted)
            box.setCurrentIndex(index if index >= 0 else 0)
        self.make_box.blockSignals(False)
        self.class_box.blockSignals(False)

    def clear_filters(self) -> None:
        for box in (self.make_box, self.class_box, self.status_box):
            box.blockSignals(True)
            box.setCurrentIndex(0)
            box.blockSignals(False)
        for check in (self.only_editable, self.own_geometry):
            check.blockSignals(True)
            check.setChecked(False)
            check.blockSignals(False)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self) -> None:
        if self.inv is None:
            return
        text = self.search.text().strip().lower()
        need_body = self.only_editable.isChecked()
        own_only = self.own_geometry.isChecked()
        make = self.make_box.currentData() or ""
        car_class = self.class_box.currentData() or ""
        only = self.status_box.currentData() or ""

        def keep(e):
            if need_body and not e.has_body:
                return False
            if own_only and e.shares_body:
                return False
            if make and e.make != make:
                return False
            if car_class and getattr(e, "car_class", "") != car_class:
                return False
            if not text:
                return True
            return (text in e.name.lower() or text in e.make.lower()
                    or text in e.model.lower() or text in e.label.lower()
                    or text in (getattr(e, "display_name", "") or "").lower())

        vanilla = [e for e in self.inv.vanilla if keep(e)]
        mods = [e for e in self.inv.mods if keep(e)]
        unknown = [e for e in self.inv.unknown if keep(e)]

        show_vanilla = not only or only == "vanilla"
        show_mods = not only or only == "mod"
        show_unknown = not only or only == "unknown"

        shown_list = ((vanilla if show_vanilla else [])
                      + (mods if show_mods else [])
                      + (unknown if show_unknown else []))
        shown_list.sort(key=lambda e: e.name)
        self.cars.set_entries(shown_list)

        shown = len(shown_list)
        total = len(self.inv.cars)
        self.count_label.setText(
            f"{shown} of {total} cars" if shown != total else f"{total} cars")

    # ---- selection ----------------------------------------------------
    def _picked(self, entry) -> None:
        if entry is None:
            return
        for table in (self.cars, self.mods, self.unknown):
            if table is not self.sender():
                table.blockSignals(True)
                table.clearSelection()
                table.blockSignals(False)
        self._wire_editor()
        self.detail.show_entry(self.inv, entry)
        # Every car can be deleted now: the program no longer keeps a list of
        # which ones are the game's own, so "is this mine" is not a question it
        # can answer, and refusing to delete half the list would be arbitrary.
        # Deleting copies the files to _rrmod_backup first, and a reinstall
        # brings a shipped car straight back.
        self.delete_btn.setEnabled(True)
        self.adopt_btn.setEnabled(entry.status == "unknown")
        self.backup_btn.setEnabled(True)
        self.picked.emit(entry.name)

    # ---- actions ------------------------------------------------------
    def _adopt(self) -> None:
        entry = self.detail._entry
        if entry is None or self.inv is None:
            return
        ok = QMessageBox.question(
            self, "Adopt car",
            f"Treat {entry.name} as one of your mods?\n\n"
            "It was not installed by this program. Adopting lets you edit and "
            "delete it; the files themselves are not touched.")
        if ok != QMessageBox.Yes:
            return
        try:
            editlib.adopt(self.inv.root, entry.name)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Adopt failed", str(exc))
            return
        self.status.emit(f"Adopted {entry.name}")
        self.changed.emit()
        self.rescan()

    def _delete(self) -> None:
        entry = self.detail._entry
        if entry is None or self.inv is None:
            return
        ok = QMessageBox.warning(
            self, "Delete mod",
            f"Delete {entry.name} (id {entry.car_id})?\n\n"
            "The car folder, its spec, its appearance record, its paint schemes "
            "and its manifest rows all go. Everything is copied to "
            f"{editlib.BACKUP_DIR} first, so this can be undone by hand.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if ok != QMessageBox.Yes:
            return
        try:
            info = editlib.remove_car(self.inv.root, entry.name)
        except PermissionError:
            # Deleting a car means taking files away, which cannot be staged as a
            # push: an unpacked install that is mounted read-only has to be
            # cleaned up by hand.
            QMessageBox.critical(
                self, "Delete failed",
                f"{self.inv.root} is read-only, so the car cannot be removed "
                "in place.\n\nDelete its folder, spec, paint schemes and "
                "manifest rows by hand, or point the manager at a writable copy "
                "of the game files.")
            return
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self.status.emit(f"Deleted {entry.name} (backup in {info.get('folder', '')}")
        self.detail.show_entry(None, None)
        self.backup_btn.setEnabled(False)
        self.picked.emit("")
        self.changed.emit()
        self.rescan()

    # ---- backup / rollback ---------------------------------------------
    def _read_root(self, name: str) -> str:
        """Where the selected car's current state lives.

        Edits are written straight into the game folder now, so this is the
        install - but it stays a method because the day a page wants to read a
        different copy is the day every caller would otherwise have to change.
        """
        if self.editor is not None:
            return self.editor.read_root(name)
        return self.inv.root

    def _backup(self) -> None:
        """Write the selected car out as a zip that can be put back later.

        This is the button the whole in-place way of working rests on: an edit
        lands in the game folder immediately, so the only thing between a bad
        build and a reinstall is having said "here is how it was" beforehand.
        """
        entry = self.detail._entry
        if entry is None or self.inv is None:
            return
        root = self._read_root(entry.name)
        try:
            info = sharelib.describe(root, entry.name)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Back up this car", str(exc))
            return
        start = os.path.join(os.path.expanduser("~"),
                             f"{entry.name} backup.zip")
        path, _filter = QFileDialog.getSaveFileName(
            self, "Back up this car", start, "Backups (*.zip)")
        if not path:
            return
        try:
            made = sharelib.backup_car(root, entry.name, path,
                                       note=f"backup of {entry.name}",
                                       log=self.status.emit)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Backup failed", str(exc))
            return
        self.status.emit(
            f"Backed up {info['count']} file(s), {made['bytes']:,} bytes -> "
            f"{os.path.basename(path)}")

    def _rollback(self) -> None:
        """Put a car back from one of those zips."""
        if self.inv is None:
            return
        start = os.path.expanduser("~")
        path, _filter = QFileDialog.getOpenFileName(
            self, "Roll back from backup", start, "Backups (*.zip)")
        if not path:
            return
        try:
            info = sharelib.inspect_backup(self.inv.root, path)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Roll back from backup", str(exc))
            return
        if info["problems"]:
            QMessageBox.warning(
                self, "Roll back from backup",
                "This zip cannot be put back:\n\n  "
                + "\n  ".join(info["problems"]))
            return
        lines = [f"{info['name']}: {len(info['replace'])} file(s) would be "
                 f"replaced, {len(info['add'])} created."]
        if info["made_at"]:
            lines.append(f"Made {info['made_at']}"
                         + (f" with {info['made_by']}" if info["made_by"] else "")
                         + ".")
        if info["note"]:
            lines.append(f"Note: {info['note']}")
        if not info["installed"]:
            lines.append(
                "\nThis car is not in the install any more - the backup puts its "
                "files back, but a car the game no longer lists may still need a "
                "rebuild to appear in the menus.")
        elif info["id_moved"]:
            lines.append(
                f"\nThe car is id {info['now_id']} here but the backup was taken "
                f"at id {info['car_id']}; the spec and the paint schemes are "
                f"written back as they were, so the two may stop agreeing.")
        lines.append("\nEvery file the rollback touches is copied to the undo "
                     "history first, so Ctrl+Z can take the rollback back.")
        ok = QMessageBox.question(self, "Roll back from backup", "\n".join(lines))
        if ok != QMessageBox.Yes:
            return
        root = self.inv.root
        if self.editor is not None:
            root = self.editor.for_car(info["name"])
        try:
            got = sharelib.rollback(root, path, log=self.status.emit)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Roll back failed", str(exc))
            return
        self.status.emit(
            f"Put {got['written']} file(s) back for {got['name']}, "
            f"{got['booked']} manifest row(s) re-booked")
        if got["failed"]:
            QMessageBox.warning(
                self, "Roll back",
                f"{len(got['failed'])} file(s) went back but their manifest row "
                "could not be re-booked:\n\n  "
                + "\n  ".join(f"{rel}: {why}" for rel, why in got["failed"][:10])
                + "\n\nRun Verify manifests to see what the lists think.")
        self.changed.emit()
        self.rescan()
