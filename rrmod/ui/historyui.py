"""The history dock: a floating list of the edits this session has made.

The model is "one folder per edit" and has been since the first version; what
this adds is a way to *see* it.  Three things a list buys that a bare Ctrl+Z does
not:

* **A name.**  "Built 2012_lexus_lfa" beats "20261111-174042-2" when the choice
  is which of twelve edits to walk back.
* **A choice of more than one.**  Ticking two steps and pressing Undo takes the
  files back to before either - which is what a user means by "take me back to
  before the wing".
* **A pin.**  A step that took an hour to get right should not be the one the
  twenty-step limit eats.

The dock is a ``QDockWidget``, so it can be dragged out of the window and left
floating beside it while the rest of the program keeps being used - the way an
equaliser panel or Photoshop's history palette behaves.  It is deliberately not
modal and holds no state of its own beyond what it reads back from
:mod:`rrmod.history` on every refresh.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDockWidget,
                               QFileDialog, QHBoxLayout, QHeaderView,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import history as historylib
from . import settings as settingslib
from . import widgets as W


class HistoryDock(QDockWidget):
    """A floating list of undo steps for the game folder that is open."""

    status = Signal(str)
    changed = Signal()
    undo_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__("History", parent)
        self.setObjectName("history_dock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
                             | Qt.BottomDockWidgetArea)
        self.root = ""

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)

        self.note = W.muted("No game folder is open yet.")
        lay.addWidget(self.note)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "When", "What it did", "Files"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setStretchLastSection(False)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 28)
        self.table.setColumnWidth(1, 118)
        self.table.setColumnWidth(3, 48)
        self.table.setMinimumHeight(120)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.undo_btn = QPushButton("Undo these")
        self.undo_btn.setToolTip("Put back the files as they were before the "
                                 "ticked steps, oldest first")
        self.undo_btn.clicked.connect(self.undo)
        row.addWidget(self.undo_btn)
        self.pin_btn = QPushButton("Pin")
        self.pin_btn.setToolTip("Keep this step when the limit starts dropping "
                                "the oldest ones")
        self.pin_btn.clicked.connect(self.toggle_pin)
        row.addWidget(self.pin_btn)
        self.forget_btn = QPushButton("Forget")
        self.forget_btn.setToolTip("Delete these steps and their saved copies")
        self.forget_btn.clicked.connect(self.forget)
        row.addWidget(self.forget_btn)
        row.addStretch(1)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.all_box = QCheckBox("Tick all")
        self.all_box.toggled.connect(self._tick_all)
        row.addWidget(self.all_box)
        row.addStretch(1)
        self.where_btn = QPushButton("Folder...")
        self.where_btn.setToolTip("Choose where the undo copies are kept")
        self.where_btn.clicked.connect(self.choose_folder)
        row.addWidget(self.where_btn)
        lay.addLayout(row)

        self.space = W.muted("")
        lay.addWidget(self.space)

        self.setWidget(body)
        self.setMinimumWidth(360)
        self._tick_guard = False
        self.table.itemChanged.connect(self._item_changed)
        self.table.doubleClicked.connect(self._double_clicked)

    def showEvent(self, event) -> None:      # noqa: N802 - Qt spelling
        super().showEvent(event)
        self.refresh()

    # ---- wiring -------------------------------------------------------
    def attach(self, editor) -> None:
        """Point the dock at the game folder the editor is holding."""
        self.root = getattr(editor, "root", "") if editor is not None else ""
        self.refresh()

    def refresh(self) -> None:
        """Read the steps back from disk.  Called after every edit."""
        if not self.root:
            self.note.setText("No game folder is open yet.")
            self.table.setRowCount(0)
            self.space.setText("")
            return
        historylib.set_dir(settingslib.history_dir())
        rows = historylib.steps(self.root)
        keep = settingslib.history_keep() or historylib.DEFAULT_KEEP
        folder = historylib.dir_for(self.root)

        self._tick_guard = True
        self.table.setRowCount(len(rows))
        for i, step in enumerate(rows):
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            tick.setCheckState(Qt.Unchecked)
            tick.setToolTip("Tick to include this step in Undo or Forget")
            self.table.setItem(i, 0, tick)
            when = QTableWidgetItem(step.get("when", ""))
            when.setToolTip(step.get("stamp", ""))
            self.table.setItem(i, 1, when)
            what = QTableWidgetItem(historylib.label(step))
            if step.get("pinned"):
                what.setText("\u2022 " + what.text())
                what.setToolTip("Pinned: the limit will not drop this one")
            self.table.setItem(i, 2, what)
            self.table.setItem(i, 3, QTableWidgetItem(
                str(len(step.get("files") or []))))
            if step.get("pinned"):
                for col in range(4):
                    cell = self.table.item(i, col)
                    if cell is not None:
                        cell.setBackground(QColor("#fff8e6"))
        self._tick_guard = False


        if rows:
            self.note.setText(
                f"{len(rows)} edit(s) can be walked back, keeping the newest "
                f"{keep}. Tick the ones to undo, or double-click a row to tick "
                f"just that one.")
        else:
            self.note.setText(
                "Nothing has been edited yet. Every change is copied aside "
                "before it is written, so this list is what Undo walks back.")
        self._say_space(folder)
        self._buttons()

    def _say_space(self, folder: str) -> None:
        """Show the folder and what is left on its disk."""
        free = ""
        try:
            probe = folder
            while probe and not os.path.isdir(probe):
                probe = os.path.dirname(probe)
            if probe:
                usage = os.statvfs(probe) if hasattr(os, "statvfs") else None
                if usage is not None:
                    free = f", {usage.f_bavail * usage.f_frsize / 2**30:.1f} GB free"
                else:
                    import shutil

                    total, _used, avail = shutil.disk_usage(probe)
                    free = f", {avail / 2**30:.1f} GB free"
        except OSError:
            free = ""
        inside = folder.startswith(os.path.abspath(self.root) + os.sep)
        self.space.setText(
            f"Copies are kept in {folder}{free}"
            + ("" if inside else " - on another disk, so every step is a real "
                                 "copy rather than a fast one."))

    def _buttons(self) -> None:
        picked = self._picked()
        self.undo_btn.setEnabled(bool(picked))
        self.forget_btn.setEnabled(bool(picked))
        self.pin_btn.setEnabled(len(picked) == 1)
        self.undo_btn.setText(f"Undo these ({len(picked)})" if picked
                              else "Undo these")

    # ---- reading the table --------------------------------------------
    def _picked(self) -> list:
        out = []
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is not None and item.checkState() == Qt.Checked:
                when = self.table.item(i, 1)
                if when is not None and when.toolTip():
                    out.append(when.toolTip())
        return out

    def _tick_all(self, on: bool) -> None:
        if self._tick_guard:
            return
        self._tick_guard = True
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is not None:
                item.setCheckState(Qt.Checked if on else Qt.Unchecked)
        self._tick_guard = False
        self._buttons()

    def _item_changed(self, _item) -> None:
        if not self._tick_guard:
            self._buttons()

    def _double_clicked(self, index) -> None:
        """Double-clicking a row ticks that row and nothing else."""
        if not index.isValid():
            return
        self._tick_guard = True
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is not None:
                item.setCheckState(Qt.Checked if i == index.row()
                                   else Qt.Unchecked)
        self._tick_guard = False
        self.all_box.setChecked(False)
        self._buttons()

    # ---- actions -------------------------------------------------------
    def undo(self) -> None:
        picked = self._picked()
        if not picked or not self.root:
            return
        # The window owns the working copy, so it does the restoring and asks
        # for a refresh when it is done; this dock only says which steps.
        self.undo_requested.emit(picked)

    def toggle_pin(self) -> None:
        picked = self._picked()
        if len(picked) != 1:
            return
        step = historylib.read(self.root, picked[0])
        on = not step.get("pinned")
        historylib.pin(self.root, picked[0], on)
        self.status.emit(f"{'Pinned' if on else 'Unpinned'} the edit of "
                         f"{step.get('when', picked[0])}")
        self.refresh()

    def forget(self) -> None:
        picked = self._picked()
        if not picked:
            return
        gone = historylib.drop(self.root, picked)
        self.status.emit(f"Forgot {gone} edit(s); the files themselves are "
                         f"left as they are")
        self.refresh()

    def choose_folder(self) -> None:
        start = settingslib.history_dir() or (
            historylib.dir_for(self.root) if self.root else "")
        path = QFileDialog.getExistingDirectory(
            self, "Where to keep the undo copies", start)
        if not path:
            return
        settingslib.set_history_dir(path)
        historylib.set_dir(path)
        self.status.emit(f"Undo copies now go to {path}")
        self.refresh()
