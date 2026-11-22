"""The texture converter window: a toolbar button's worth of "png to dds, please".

Nothing here decides anything - :mod:`rrmod.texconv` does the work and this is a
form over it.  The one thing the form adds is the *batch*: a page is never one
file, a car's paint is a folder, and converting forty textures one dialog at a
time is how a tool goes unused.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import texconv as convlib
from . import widgets as W
from .worker import Task


class TextureTool(QDialog):
    """Convert pictures and game textures between PNG, DDS and the game's own."""

    status = Signal(str)

    def __init__(self, parent=None, *, start_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Convert textures")
        self.resize(900, 620)
        self._files = []
        self._start = start_dir or os.path.expanduser("~")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        lay.addWidget(W.heading("Files", 2))
        lay.addWidget(W.muted(
            "PNG and JPEG are ordinary pictures.  DDS is a plain DirectDraw "
            "surface.  The three 'game texture' formats are what the engine "
            "loads, and only they can be dropped into a car's folder - the game "
            "picks its decoder from the file name, so the name has to keep its "
            "suffix."))
        row = QHBoxLayout()
        self.add_btn = W.button("Add files...", self._add_files)
        row.addWidget(self.add_btn)
        self.add_dir_btn = W.button("Add a folder...", self._add_dir,
                                    tip="Every picture and texture under it")
        row.addWidget(self.add_dir_btn)
        self.drop_btn = W.button("Clear", self._clear)
        row.addWidget(self.drop_btn)
        row.addStretch(1)
        self.count_label = W.muted("no files yet")
        row.addWidget(self.count_label)
        lay.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("File", "Kind", "Size", "Format"))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            head.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        lay.addWidget(self.table, 1)

        lay.addWidget(W.heading("Convert to", 2))
        out = QHBoxLayout()
        self.format_box = QComboBox()
        for key, label in convlib.FORMATS.items():
            self.format_box.addItem(label, key)
        self.format_box.setCurrentIndex(
            self.format_box.findData("game-dxt"))
        self.format_box.currentIndexChanged.connect(self._format_changed)
        out.addWidget(self.format_box, 1)
        lay.addLayout(out)

        self.flip_box = QCheckBox("Turn the picture over on the way through")
        self.flip_box.setToolTip(
            "The game stores every texture bottom-up and a PNG is top-down, so "
            "this is on for a game texture and off for a plain picture. Untick it "
            "to keep the rows exactly as they are - which is what you want when "
            "converting a game texture to a DDS and back.")
        self.flip_box.setChecked(True)
        lay.addWidget(self.flip_box)

        self.alpha_box = QCheckBox("Keep the alpha channel (DXT5 rather than DXT1)")
        self.alpha_box.setChecked(True)
        self.alpha_box.setToolTip(
            "A four channel picture always keeps it. Untick this to force DXT1 "
            "for a page whose alpha is not used, which is half the size.")
        lay.addWidget(self.alpha_box)

        where = QHBoxLayout()
        where.addWidget(QLabel("Into"))
        self.out_dir = QLineEdit(self._start)
        where.addWidget(self.out_dir, 1)
        self.pick_btn = W.button("Choose...", self._pick_dir)
        where.addWidget(self.pick_btn)
        lay.addLayout(where)

        self.log = W.LogPane()
        lay.addWidget(self.log, 1)

        bottom = QHBoxLayout()
        self.same_dir = QCheckBox("Write next to each source file")
        self.same_dir.setToolTip(
            "A game texture would then be written over itself if you convert to "
            "the same format; the converter refuses that rather than corrupting "
            "a file.")
        self.same_dir.toggled.connect(self._same_dir)
        bottom.addWidget(self.same_dir)
        bottom.addStretch(1)
        bottom.addWidget(W.button("Close", self.reject))
        self.go = W.button("Convert", self._convert, primary=True)
        self.go.setEnabled(False)
        bottom.addWidget(self.go)
        lay.addLayout(bottom)

        self._format_changed()

    # ---- the list -----------------------------------------------------
    def _add_files(self) -> None:
        patterns = " ".join("*" + s for s in convlib.PICTURES)
        patterns += " *.dds " + " ".join("*" + s for s in convlib.texlib.ALL_SUFFIXES)
        got, _f = QFileDialog.getOpenFileNames(
            self, "Add textures", self._start,
            f"Pictures and textures ({patterns});;All files (*)")
        if got:
            self._start = os.path.dirname(got[0])
            self._add(got)

    def _add_dir(self) -> None:
        got = QFileDialog.getExistingDirectory(self, "Add every texture under", self._start)
        if not got:
            return
        self._start = got
        found = convlib.files_in(got)
        if not found:
            self.log.note(f"nothing convertible under {got}")
            return
        self._add(found)

    def _add(self, paths) -> None:
        known = {p for p in self._files}
        for path in paths:
            if path not in known:
                self._files.append(path)
                known.add(path)
        self._fill()

    def _clear(self) -> None:
        self._files = []
        self._fill()

    def _fill(self) -> None:
        self.table.setRowCount(len(self._files))
        for i, path in enumerate(self._files):
            info = convlib.describe(path)
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(path)))
            self.table.item(i, 0).setToolTip(path)
            kind = {"game": "game texture", "dds": "DDS",
                    "picture": "picture", "":"?"}[info["kind"]]
            self.table.setItem(i, 1, QTableWidgetItem(kind))
            size = QTableWidgetItem(f"{info['bytes'] / 1024:,.0f} KB")
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 2, size)
            self.table.setItem(i, 3, QTableWidgetItem(
                info.get("error") or
                (f"{info['format']} {info['width']}x{info['height']}"
                 if info["width"] else info["format"] or "")))
        self.count_label.setText(
            f"{len(self._files)} file(s)" if self._files else "no files yet")
        self.go.setEnabled(bool(self._files))

    def _format_changed(self) -> None:
        """Say what the output will be called, and set the flip sensibly."""
        fmt = self.format_box.currentData()
        self.flip_box.setChecked(fmt in convlib.GAME_FORMATS)
        self.alpha_box.setEnabled(fmt in ("dds", "game-dxt"))
        self.log.note(f"output suffix: {convlib.SUFFIXES[fmt]}")

    def _same_dir(self, on: bool) -> None:
        self.out_dir.setEnabled(not on)
        self.pick_btn.setEnabled(not on)

    def _pick_dir(self) -> None:
        got = QFileDialog.getExistingDirectory(self, "Write into", self.out_dir.text())
        if got:
            self.out_dir.setText(got)

    # ---- converting ---------------------------------------------------
    def _convert(self) -> None:
        if not self._files:
            return
        fmt = self.format_box.currentData()
        flip = self.flip_box.isChecked()
        alpha = self.alpha_box.isChecked() if self.alpha_box.isEnabled() else None
        same = self.same_dir.isChecked()
        out_dir = "" if same else self.out_dir.text().strip()
        if not same and not out_dir:
            self.log.error("choose a folder to write into first")
            return
        files = list(self._files)
        self.go.setEnabled(False)
        self.status.emit("Converting...")
        self.log.note(f"converting {len(files)} file(s) to {convlib.SUFFIXES[fmt]}")

        def work():
            if same:
                done, failed = [], []
                for path in files:
                    try:
                        got = convlib.convert(
                            path, os.path.dirname(path), fmt, flip=flip,
                            alpha=alpha,
                            out_path=convlib.target_for(
                                path, os.path.dirname(path), fmt))
                        done.append(got)
                    except Exception as exc:     # noqa: BLE001 - one bad file only
                        failed.append((path, str(exc)[:200]))
                return {"done": done, "failed": failed, "format": fmt}
            return convlib.convert_many(files, out_dir, fmt, flip=flip,
                                        alpha=alpha, log=lambda _m: None)

        self._task = Task(work, parent=self)
        self._task.done.connect(self._converted)
        self._task.fail.connect(self._failed)
        self._task.start()

    def _converted(self, info) -> None:
        self.go.setEnabled(True)
        for got in info["done"]:
            self.log.ok(f"{os.path.basename(got['source'])} -> "
                        f"{os.path.basename(got['path'])} "
                        f"({got['width']}x{got['height']}, {got['bytes']:,} bytes)")
        for path, why in info["failed"]:
            self.log.error(f"{os.path.basename(path)}: {why}")
        n = len(info["done"])
        self.status.emit(f"Converted {n} file(s)"
                         + (f", {len(info['failed'])} failed"
                            if info["failed"] else ""))
        if n:
            self.log.note("nothing was written into the game folder: this window "
                          "only converts files")

    def _failed(self, text: str) -> None:
        self.go.setEnabled(True)
        self.log.error(text)
        self.status.emit("Conversion failed")


def open_tool(parent=None, *, start_dir: str = "") -> "TextureTool":
    """Build and show the window, so the menu and the toolbar share one call."""
    dlg = TextureTool(parent, start_dir=start_dir)
    dlg.show()
    return dlg
