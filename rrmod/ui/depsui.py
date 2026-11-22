"""The Dependencies page: which shared pages exist, and who needs each one.

Two questions get confused with each other, and this page keeps them apart:

* **who names it now** - answered by reading all 540 livery tables, which takes
  a third of a second and is therefore never cached.  A page that something names
  cannot be deleted, whatever brought it here.
* **who brought it** - answered by ``deps.json``, because nothing on disk records
  that.  A page this program added and nothing names any more is an orphan, and
  an orphan is the only thing on this page that may be deleted.

A page the game itself ships is never a candidate, even when no car uses it: 51
of the 298 pages in ``vehicles/common`` are unused by the shipped cars, and they
are still the game's own files.

**The game has two shared folders, not one**, and they are managed separately
because they are found in completely different ways:

* ``vehicles/common`` - 298 pages, each named by whichever livery tables point at
  it.  Four rows per page in one asset list, and the answer to "who needs this"
  is a list of cars.
* ``Tracks/common`` - 2,313 files in twenty-three folders, named by nothing at
  all except the absolute artist paths baked into each track's own ``.m3g``.
  Four rows per page across *nineteen* asset lists, one per top folder, and the
  answer to "who needs this" is a list of tracks.

They share the same rules - four rows, shipped pages are never deleted, an
orphan is the only thing that may go - but nothing else, so the tab has a tab of
its own for each.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QHBoxLayout, QHeaderView, QLineEdit,
                               QMessageBox, QTabWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import deps as depslib
from . import widgets as W
from .worker import Task

COLUMNS = ("Page", "Named by", "Shipped", "Brought by", "Files")

#: Widths the header starts at; every one is draggable afterwards.
WIDTHS = (320, 90, 90, 190, 300)

#: The track side's "Named by" counts tracks rather than cars, so it says so.
TRACK_COLUMNS = ("Page", "Named by", "Shipped", "Brought by", "Files")


def _table(columns, widths) -> QTableWidget:
    """One sortable, read-only table with draggable columns."""
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(True)
    head = table.horizontalHeader()
    head.setSectionResizeMode(QHeaderView.Interactive)
    head.setStretchLastSection(True)
    for column, width in enumerate(widths):
        table.setColumnWidth(column, width)
    return table


def _orphan_table() -> QTableWidget:
    table = QTableWidget(0, 2)
    table.setHorizontalHeaderLabels(("Page", "Files"))
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    head = table.horizontalHeader()
    head.setSectionResizeMode(QHeaderView.Interactive)
    head.setStretchLastSection(True)
    table.setColumnWidth(0, 320)
    table.setMaximumHeight(120)
    return table


class _Half(QWidget):
    """One shared folder: a table, its orphans, and the pages that are missing.

    Both halves behave identically - they differ only in which functions answer
    the questions - so the layout lives here once and the two subclasses below
    supply the four calls.
    """

    status = Signal(str)
    changed = Signal()

    #: What this half calls the things that name a page (``car``/``track``).
    owner_word = "car"
    #: The heading over the whole half.
    title = "Shared pages"
    #: One sentence explaining what this folder is.
    blurb = ""
    #: The label on the delete button.
    delete_label = "Delete this page"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.depot = ""
        self.root = ""
        self.rows = []
        self.report_info = {}
        self.orphan_rows = []
        self.missing_rows = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lay.addWidget(W.heading(self.title, 2))
        self.note = W.muted(self.blurb)
        lay.addWidget(self.note)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by page name")
        self.search.textChanged.connect(self._fill)
        bar.addWidget(self.search, 1)
        self.only_shared = QCheckBox("Only the ones in use")
        self.only_shared.setToolTip(
            f"Hide the pages no {self.owner_word} names")
        self.only_shared.toggled.connect(self._fill)
        bar.addWidget(self.only_shared)
        self.add_btn = W.button(
            "Add a texture...", self._add_page,
            tip="Encode a picture and put it in this shared folder")
        self.add_btn.setVisible(bool(getattr(self, "can_add", False)))
        bar.addWidget(self.add_btn)
        self.reload_btn = W.button("Reload", self.reload)
        bar.addWidget(self.reload_btn)
        lay.addLayout(bar)

        self.table = _table(COLUMNS, WIDTHS)
        self.table.itemSelectionChanged.connect(self._picked)
        lay.addWidget(self.table, 1)

        lay.addWidget(W.heading("This program's own pages", 3))
        self.orphan_note = W.muted("")
        lay.addWidget(self.orphan_note)
        self.orphans = _orphan_table()
        self.orphans.itemSelectionChanged.connect(self._orphan_picked)
        lay.addWidget(self.orphans)

        orow = QHBoxLayout()
        self.forget_btn = W.button(
            self.delete_label, self._forget,
            tip="Only a page this program added, and that nothing names any "
                "more, can be deleted")
        self.forget_btn.setEnabled(False)
        orow.addWidget(self.forget_btn)
        orow.addStretch(1)
        lay.addLayout(orow)

        lay.addWidget(W.heading("Pages that are named but not here", 3))
        self.missing_note = W.muted("")
        lay.addWidget(self.missing_note)

        self.summary = W.muted("")
        lay.addWidget(self.summary)
        self.log = W.LogPane()
        self.log.setMaximumHeight(80)
        lay.addWidget(self.log)

    # ---- the four questions each half answers --------------------------
    def _report(self) -> dict:
        raise NotImplementedError

    def _used(self) -> dict:
        raise NotImplementedError

    def _game(self) -> set:
        raise NotImplementedError

    def _orphan_list(self) -> list:
        raise NotImplementedError

    def _missing_list(self) -> list:
        raise NotImplementedError

    def _delete(self, stem: str) -> dict:
        raise NotImplementedError

    # ---- loading -------------------------------------------------------
    def load(self, depot: str, root: str = "") -> None:
        self.install_depot = depot or ""
        self.root = root or depot or ""
        # Read the working copy once it holds the shared folder, so a page this
        # program added shows up as a file and not only as a note in deps.json.
        # Until the first edit the working copy is empty, and the install is the
        # truth.
        self.depot = self.install_depot
        if self.root and self.root != self.install_depot:
            if os.path.isdir(os.path.join(self.root, ".depot",
                                          *self.folder.split("/"))):
                self.depot = os.path.join(self.root, ".depot")
        if not self.depot:
            self.rows = []
            self._fill()
            return
        self.summary.setText("Reading...")
        self._task = Task(self._gather, parent=self)
        self._task.done.connect(self._loaded)
        self._task.fail.connect(self._failed)
        self._task.start()

    #: Which folder this half is about, relative to ``.depot``.
    folder = "vehicles/common"

    def reload(self) -> None:
        if getattr(self, "install_depot", ""):
            self.load(self.install_depot, self.root)

    def _gather(self):
        # Everything below reads the same scan, so it is done once here rather
        # than four times on the GUI thread.
        depslib.forget()
        info = self._report()
        used = self._used()
        game = self._game()
        recorded = {k: v for k, v in depslib.load(self.depot)["pages"].items()
                    if self._mine(k)}
        rows = []
        # Only this half's own folder: a car's ``<car>_misc`` page is a page of
        # that car, managed on the Cars page, and listing it here made the
        # table look like it could delete it.
        for stem in sorted(s for s in (set(used) | game | set(recorded))
                           if self._mine(s)):
            owners = used.get(stem) or []
            row = recorded.get(stem) or {}
            rows.append({
                "stem": stem,
                "live": list(owners),
                "count": len(owners),
                "shipped": stem in game,
                "brought_by": list(row.get("owners") or []),
                "files": list(row.get("files") or []),
                "source": row.get("source", ""),
            })
        return {"report": info, "rows": rows,
                "orphans": self._orphan_list(),
                "missing": self._missing_list()}

    def _mine(self, stem: str) -> bool:
        """Is this stem one of the pages this half is about?"""
        raise NotImplementedError

    def _loaded(self, payload) -> None:
        self.report_info = payload["report"]
        self.rows = payload["rows"]
        self.orphan_rows = payload["orphans"]
        self.missing_rows = payload["missing"]
        self.summary.setText(self._summary_text(self.report_info))
        self._fill()
        self._fill_orphans()
        self._fill_missing()

    def _summary_text(self, info: dict) -> str:
        raise NotImplementedError

    def _failed(self, text: str) -> None:
        self.summary.setText("Could not read the shared pages.")
        self.log.error(text[:2000])

    # ---- the tables ----------------------------------------------------
    def _shown(self) -> list:
        text = self.search.text().strip().lower()
        out = []
        for row in self.rows:
            if self.only_shared.isChecked() and not row["count"]:
                continue
            if text and text not in row["stem"].lower():
                continue
            out.append(row)
        return out

    def _fill(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for row in self._shown():
            r = self.table.rowCount()
            self.table.insertRow(r)
            page = QTableWidgetItem(row["stem"])
            page.setData(Qt.UserRole, row["stem"])
            if row["shipped"]:
                page.setToolTip("One of the game's own pages")
            self.table.setItem(r, 0, page)
            count = QTableWidgetItem()
            count.setData(Qt.DisplayRole, int(row["count"]))
            count.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if row["live"]:
                count.setToolTip("\n".join(row["live"][:20]))
            self.table.setItem(r, 1, count)
            shipped = QTableWidgetItem("yes" if row["shipped"] else "no")
            shipped.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.table.setItem(r, 2, shipped)
            who = QTableWidgetItem(", ".join(row["brought_by"]) or "-")
            if row["source"]:
                who.setToolTip(row["source"])
            self.table.setItem(r, 3, who)
            files = QTableWidgetItem(", ".join(row["files"]) or "-")
            files.setToolTip("\n".join(row["files"]))
            self.table.setItem(r, 4, files)
        self.table.setSortingEnabled(True)
        self._picked()

    def _fill_orphans(self) -> None:
        self.orphans.setRowCount(len(self.orphan_rows))
        for i, row in enumerate(self.orphan_rows):
            page = QTableWidgetItem(row["stem"])
            page.setData(Qt.UserRole, row["stem"])
            if row.get("source"):
                page.setToolTip(row["source"])
            self.orphans.setItem(i, 0, page)
            files = QTableWidgetItem(", ".join(row["files"]) or "-")
            files.setToolTip("\n".join(row["files"]))
            self.orphans.setItem(i, 1, files)
        if self.orphan_rows:
            self.orphan_note.setText(
                "Nothing names these any more, so deleting them frees the bytes "
                "without changing how anything looks. The four rows each one "
                "has in its asset list go with it.")
        else:
            self.orphan_note.setText(
                "Nothing to clean up: every page this program added is still "
                "named.")
        self._orphan_picked()

    def _fill_missing(self) -> None:
        if self.missing_rows:
            self.missing_note.setText(
                f"{len(self.missing_rows)} page(s) are named but are not in this "
                f"install: {', '.join(self.missing_rows[:6])}"
                f"{' ...' if len(self.missing_rows) > 6 else ''}. The game copes "
                "with this, and a mod that supplies one is doing the game a "
                "favour rather than fixing a fault.")
        else:
            self.missing_note.setText("Every page that is named is in this "
                                      "install.")

    # ---- acting --------------------------------------------------------
    def _picked(self) -> None:
        rows = self.table.selectionModel().selectedRows() if \
            self.table.selectionModel() else []
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return
        stem = item.data(Qt.UserRole) or item.text()
        row = next((r for r in self.rows if r["stem"] == stem), None)
        if row is None:
            return
        if not row["count"] and not row["shipped"] and not row["brought_by"]:
            self.status.emit(f"{stem} is not named by anything and was not added "
                             f"by this program")

    def _orphan_picked(self) -> None:
        rows = self.orphans.selectionModel().selectedRows() if \
            self.orphans.selectionModel() else []
        self.forget_btn.setEnabled(bool(rows))

    def _forget(self) -> None:
        rows = self.orphans.selectionModel().selectedRows() if \
            self.orphans.selectionModel() else []
        if not rows:
            return
        item = self.orphans.item(rows[0].row(), 0)
        if item is None:
            return
        stem = item.data(Qt.UserRole) or item.text()
        ok = QMessageBox.question(
            self, "Delete the page",
            f"Delete {stem} and its rows in the asset list?\n\n"
            "Nothing names it any more, so nothing changes. The copy on the "
            "device is only removed when the Deploy tab pushes the change.")
        if ok != QMessageBox.Yes:
            return
        try:
            got = self._delete(stem)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Delete the page", str(exc))
            return
        self.log.ok(f"deleted {stem}: {len(got['files'])} file(s), "
                    f"{len(got['rows'])} row(s), {got['registry']} registry "
                    f"row(s)")
        self.status.emit(f"Deleted {stem}")
        self.changed.emit()
        self.reload()

    def attach_root(self, root: str) -> None:
        """Where the working copy is, once an install has been opened."""
        self.root = root or getattr(self, "install_depot", "")

    def _add_page(self) -> None:
        """A picture and a label, encoded into this half's folder."""
        raise NotImplementedError


class CarPages(_Half):
    """``vehicles/common``: the pages a car's livery table names."""

    owner_word = "car"
    title = "Shared car pages"
    folder = "vehicles/common"
    #: A page can be added here: it is the one shared folder a car's own table
    #: can point at, so "I need a tyre nobody ships" has somewhere to go.
    can_add = True
    blurb = (
        "A page in vehicles/common is shared: the tyres, discs, glass and "
        "interior weaves every car can point at. Changing one changes every car "
        "that names it, so a page is only deleted when this program brought it "
        "and nothing names it any more.")

    def _add_page(self):
        """Ask for the picture and the label, then encode it into common/."""
        from . import materialui

        if not self.root:
            QMessageBox.information(
                self, "Add a texture",
                "Open a game folder first: a page has to be written into the "
                "working copy.")
            return
        # The dialog that already knows how to encode a picture and book the
        # four asset-list rows, with the label question turned on: a shared page
        # is named after what it is, because nothing else records that.
        dlg = materialui.ImportPageDialog(
            self.root, "a car", self, where="common", labels=True)
        dlg.setWindowTitle("Add a texture to vehicles/common")
        if dlg.exec() != QDialog.Accepted:
            return
        got = dlg.result or {}
        self.log.ok(f"added {got.get('rel') or got.get('stem')} "
                    f"({got.get('width')}x{got.get('height')})")
        self.status.emit(f"Added {got.get('stem') or 'the page'} to "
                         f"vehicles/common")
        self.changed.emit()
        self.reload()

    def _report(self):
        return depslib.report(self.depot)

    def _used(self):
        return depslib.scan(self.depot)

    def _game(self):
        return depslib.shipped(self.depot)

    def _orphan_list(self):
        return depslib.orphans(self.depot)

    def _missing_list(self):
        return depslib.missing(self.depot)

    def _mine(self, stem):
        return depslib.is_shared(stem)

    def _summary_text(self, info):
        return (f"{info['pages']} page(s) named by a car, {info['shared']} of "
                f"them shared, {info['shipped']} shipped with the game "
                f"({info['unreferenced']} of those unused). "
                f"{info['orphans']} page(s) this program added are no longer "
                f"named.")

    def _delete(self, stem):
        from .. import edit as editlib

        return editlib.remove_common_page(self.root or self.depot, stem)


class TrackPages(_Half):
    """``Tracks/common``: the pages a track's own model names."""

    owner_word = "track"
    title = "Shared track pages"
    folder = "Tracks/common"
    delete_label = "Delete this page"
    blurb = (
        "Tracks/common is the track side's shared folder: 2,313 files of road "
        "surface, barriers, crowds and sky. No table names them - the only "
        "record is the artist's own path stored inside each track's model, which "
        "is where this page reads them from. Nineteen asset lists claim them, "
        "one per top folder.")

    def _report(self):
        return depslib.track_report(self.depot)

    def _used(self):
        return depslib.scan_tracks(self.depot)

    def _game(self):
        return depslib.shipped_tracks(self.depot)

    def _orphan_list(self):
        return depslib.track_orphans(self.depot)

    def _missing_list(self):
        return depslib.track_missing(self.depot)

    def _mine(self, stem):
        return depslib.is_track(stem)

    def _summary_text(self, info):
        return (f"{info['pages']} page(s) named by {info['models']} track "
                f"model(s), {info['on_disk']} on disk "
                f"({info['unreferenced']} of those unused), "
                f"{info['missing']} named but absent. "
                f"{info['orphans']} page(s) this program added are no longer "
                f"named.")

    def _delete(self, stem):
        from .. import edit as editlib

        return editlib.remove_track_page(self.root or self.depot, stem)


class DepsPage(QWidget):
    """Both shared folders, one tab each."""

    status = Signal(str)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.depot = ""
        self.install_depot = ""
        self.root = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.tabs = QTabWidget()
        self.cars = CarPages()
        self.tracks = TrackPages()
        self.tabs.addTab(self.cars, "Car pages")
        self.tabs.addTab(self.tracks, "Track pages")
        lay.addWidget(self.tabs)

        for half in (self.cars, self.tracks):
            half.status.connect(self.status.emit)
            half.changed.connect(self.changed.emit)

    # ---- the attributes the rest of the program already uses -----------
    @property
    def table(self):
        return self.cars.table

    @property
    def rows(self):
        return self.cars.rows

    @property
    def summary(self):
        return self.cars.summary

    @property
    def orphans(self):
        return self.cars.orphans

    @property
    def orphan_rows(self):
        return self.cars.orphan_rows

    @property
    def forget_btn(self):
        return self.cars.forget_btn

    @property
    def log(self):
        return self.cars.log

    def load(self, depot: str, root: str = "") -> None:
        self.install_depot = depot or ""
        self.root = root or depot or ""
        self.depot = self.install_depot
        self.cars.load(depot, root)
        self.tracks.load(depot, root)

    def reload(self) -> None:
        if self.install_depot:
            self.load(self.install_depot, self.root)

    def attach_root(self, root: str) -> None:
        self.root = root or self.install_depot
        self.cars.attach_root(root)
        self.tracks.attach_root(root)

    # ---- the test drives these directly --------------------------------
    def _gather(self):
        return self.cars._gather()

    def _loaded(self, payload) -> None:
        self.cars._loaded(payload)
