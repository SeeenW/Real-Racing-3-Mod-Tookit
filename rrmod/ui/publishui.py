"""The Publish page: one file out, with its needs written on the outside.

The page is deliberately a form rather than a wizard.  A pack is five decisions -
what kind, which one, where to put it, what to call it, what to say about it -
and a single screen shows all five at once, which is what you want when you are
publishing the third version of the same car and only the note changed.

The lower half is the other direction: open a ``.rr3mod`` somebody sent you and
see what it needs *before* installing it.  The dependency check runs on the
game folder, so it answers "would this work here" rather than "is this file
well formed", and an unsatisfied row names the exact thing that is missing.

Installing is a separate button on purpose.  Reading a pack is safe and should
be free to do; installing it rewrites files, so it gets its own click and its
own undo step.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLineEdit, QPlainTextEdit,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from rr3lib import driver as driverlib

from .. import depot as depotlib
from .. import maps as maplib
from .. import pack as packlib
from .. import publish as publishlib
from . import settings as settingslib
from . import widgets as W
from .worker import Task

#: What each kind is called in the menu, and what the "which one" control means.
KIND_LABELS = (
    ("car", "A car"),
    ("pages", "Shared texture pages"),
    ("driver", "A driver pose"),
    ("brand", "A manufacturer's logo"),
    ("material", "A material of your own"),
    ("career", "The career"),
    ("track", "A circuit picture"),
)

#: How each GPU family reads in the "install its pictures as" menu.
FAMILY_LABELS = {
    "auto": "Whatever this install already holds",
    "dxt": "DXT (Adreno, desktop)",
    "etc": "ETC1 (Mali)",
    "atc": "ATC (Adreno, older)",
}


def _family_label(key: str) -> str:
    return FAMILY_LABELS.get(key, key.upper())

#: Kinds where more than one thing can be picked.
MULTI = ("pages",)

#: The four texture families, tried in turn for a shared page.
FAMILIES = (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z")


def _page_on_disk(depot: str, stem: str) -> str:
    """The file a shared page stem points at, or ``""``.

    ``.dxt.dds.z`` is three parts, so ``os.path.splitext`` is no use; each
    family is tried instead.
    """
    base = os.path.join(depot, "vehicles", *stem.split("/"))
    for suffix in FAMILIES:
        if os.path.isfile(base + suffix):
            return base + suffix
    return ""


class PublishPage(QWidget):
    """Pick a kind, pick the thing, write a file."""

    status = Signal(str)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.inv = None
        self.root = ""
        self.depot = ""
        self._task = None
        self._made = None
        self._info = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lay.addWidget(W.heading("What to publish", 2))
        self.note = W.muted(
            "A pack is one file holding the files and the list of what has to "
            "be there before they work. The list is checked when someone opens "
            "the pack, not when they install it, so a missing driver pose is a "
            "sentence rather than a car with no driver in it.")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.kind = QComboBox()
        for key, label in KIND_LABELS:
            self.kind.addItem(label, key)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        form.addRow("Kind", self.kind)

        self.which = QComboBox()
        self.which.setEditable(False)
        self.which.setMinimumWidth(320)
        form.addRow("Which", self.which)

        self.what = W.muted("")
        self.what.setWordWrap(True)
        form.addRow("", self.what)

        outrow = QHBoxLayout()
        self.out = QLineEdit()
        self.out.setPlaceholderText("the file to write")
        outrow.addWidget(self.out, 1)
        self.browse_btn = QPushButton("...")
        self.browse_btn.setFixedWidth(32)
        self.browse_btn.clicked.connect(self._browse)
        outrow.addWidget(self.browse_btn)
        form.addRow("Save as", outrow)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText(
            "one line the person installing it will read")
        form.addRow("Note", self.note_edit)
        lay.addLayout(form)

        bar = QHBoxLayout()
        self.publish_btn = W.button("Publish...", self.publish, primary=True,
                                    tip="Write the pack file")
        bar.addWidget(self.publish_btn)
        self.open_btn = W.button("Open a pack...", self.open_pack,
                                 tip="Read a .rr3mod and see what it needs")
        bar.addWidget(self.open_btn)
        bar.addStretch(1)
        lay.addLayout(bar)

        lay.addWidget(W.heading("What the last pack holds", 3))
        self.log = W.LogPane()
        self.log.setMinimumHeight(120)
        lay.addWidget(self.log, 1)

        lay.addWidget(W.heading("A pack somebody sent you", 3))
        self.pack_note = W.muted(
            "Open one to see what it carries and what it needs. Nothing is "
            "written until you press Install.")
        self.pack_note.setWordWrap(True)
        lay.addWidget(self.pack_note)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(("What", "Kind", "Where it is"))
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setStretchLastSection(True)
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 90)
        self.table.setMaximumHeight(140)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table)

        self.family = QComboBox()
        self.family.setMinimumWidth(260)
        for key in publishlib.TEXTURE_FAMILIES:
            self.family.addItem(_family_label(key), key)
        self.family.setCurrentIndex(
            max(0, self.family.findData(settingslib.texture_family() or "auto")))
        self.family.currentIndexChanged.connect(self._family_changed)
        self.family_note = W.muted("")
        self.family_note.setWordWrap(True)
        frow = QFormLayout()
        frow.addRow("Install its pictures as", self.family)
        lay.addLayout(frow)
        lay.addWidget(self.family_note)

        ibar = QHBoxLayout()
        self.install_btn = W.button(
            "Install this pack", self.install,
            tip="Copy its files into the game folder; one undo step takes it back")
        self.install_btn.setEnabled(False)
        ibar.addWidget(self.install_btn)
        ibar.addStretch(1)
        lay.addLayout(ibar)
        self._family_changed()

    def _family_changed(self, *_args) -> None:
        key = self.family.currentData() or "auto"
        if key == "auto":
            self.family_note.setText(
                "Each page is written in whichever family this install already "
                "holds for it. That is the safe choice: the GPU only reads the "
                "family its data package was built for.")
        elif key == "pvrtc":
            self.family_note.setText(
                "PVRTC cannot be written - its blocks interpolate colours "
                "across block edges, which a block encoder cannot reproduce.")
        else:
            self.family_note.setText(
                f"Every picture is encoded as {key.upper()}. Pick this only if "
                f"you know the device reads {key.upper()} pages - a page the GPU "
                f"cannot decode draws as nothing.")
        settingslib.set_texture_family(key)

    def set_family(self, key: str) -> None:
        """Point the picture-format menu at ``key``.

        Called when the game folder is re-picked: the format is answered in that
        dialog, and this page must not go on showing the previous install's
        answer - a stale menu here is exactly how a page gets written in the
        family the new install does not use.
        """
        at = self.family.findData(key or "auto")
        if at >= 0 and at != self.family.currentIndex():
            self.family.setCurrentIndex(at)

    # ------------------------------------------------------------ wiring
    def load(self, inv, root: str = "") -> None:
        """Fill the pickers from a game folder."""
        self.inv = inv
        self.root = root or getattr(inv, "root", "")
        self.depot = getattr(inv, "depot", "") or os.path.join(self.root, ".depot")
        self._kind_changed()

    def _kind(self) -> str:
        return self.kind.currentData() or "car"

    def _kind_changed(self, *_args) -> None:
        kind = self._kind()
        self.which.clear()
        self.which.setEditable(False)
        self.which.setEnabled(kind != "career")
        if kind == "car":
            for car in sorted(self.inv.cars, key=lambda c: c.name) if self.inv else []:
                self.which.addItem(car.name, car.name)
        elif kind == "pages":
            for stem in self._shared_pages():
                self.which.addItem(stem, stem)
        elif kind == "driver":
            for stem in self._poses():
                self.which.addItem(stem, stem)
        elif kind == "brand":
            for name in depotlib.brand_names(self.depot):
                self.which.addItem(name, name)
        elif kind == "material":
            for name in self._materials():
                self.which.addItem(name, name)
        elif kind == "track":
            for name in self._tracks():
                self.which.addItem(name, name)
        self._describe()

    def _shared_pages(self) -> list:
        """Every shared page the depot on screen actually holds.

        This walks the folder rather than asking :mod:`rrmod.deps` which pages
        the *install* ships, because the point of publishing is to hand on a
        page a mod added - and that page is on disk here but not in the install.
        """
        folder = os.path.join(self.depot, "vehicles", "common")
        out = set()
        if not os.path.isdir(folder):
            return out
        for leaf in sorted(os.listdir(folder)):
            for suffix in FAMILIES:
                if leaf.endswith(suffix):
                    out.add("common/" + leaf[:-len(suffix)])
                    break
        return sorted(out)

    def _poses(self) -> list:
        """The driver poses the game ships, as bare stems.

        ``driver.banim`` is the default and is not a pack of its own, so it is
        left out; every other ``driver_<x>.banim`` is a pose a car can name.
        """
        folder = driverlib.driver_dir(self.depot)
        out = []
        if not os.path.isdir(folder):
            return out
        for leaf in sorted(os.listdir(folder)):
            if not leaf.endswith(".banim"):
                continue
            bare = leaf[:-len(".banim")]
            if bare == "driver":
                continue
            out.append(bare[len("driver_"):] if bare.startswith("driver_")
                       else bare)
        return out

    def _materials(self) -> list:
        """Materials this game folder added, which are the only ones worth packing.

        The game's own 296 ship with every install, so a pack of them would be
        135 KB of nothing; :func:`rrmod.publish.cloned_materials` answers by
        comparing the library against the stock one.
        """
        try:
            return publishlib.cloned_materials(self.root)
        except Exception:                          # noqa: BLE001 - no library, no list
            return []

    def _tracks(self) -> list:
        """Tracks this program has a picture for.

        A picture of the game's own is on every install already, so only the
        ones stored here are worth publishing.
        """
        from .. import tracks as tracklib

        out = set()
        for name in tracklib.CIRCUITS:
            if maplib.stored(self.depot, name):
                out.add(name)
        return sorted(out)
    def _describe(self, *_args) -> None:
        kind = self._kind()
        got = self.which.currentData() or ""
        if kind == "car" and got:
            self._task = Task(lambda: publishlib.car_plan(self.root, got),
                              parent=self)
            self._task.done.connect(self._plan_ready)
            self._task.fail.connect(lambda t: self.what.setText(t))
            self._task.start()
            self.what.setText(f"Reading {got}...")
        elif kind == "career":
            self.what.setText(
                "The fourteen career files. A career pack is merged on the "
                "receiving side, so nobody loses the series they added.")
        elif kind == "pages" and got:
            self.what.setText(
                "The page file plus its four rows in "
                "asset_list_vehicle_common.txt, so the game finds it.")
        elif kind == "driver" and got:
            self.what.setText(
                "The pose and the low-poly body that can wear it, if the game "
                "has one for it.")
        elif kind == "material" and got:
            self.what.setText(
                "The whole library with the blocks you added named in the list. "
                "Installing merges those blocks into the receiver's library, so "
                "a material they already have is left as they tuned it.")
        else:
            self.what.setText("")

    def _plan_ready(self, plan) -> None:
        self.what.setText(
            f"{plan['count']} file(s), {plan['bytes'] / 1048576:.1f} MB. "
            f"{len(plan['carried_pages'])} shared page(s) travel with it, "
            f"{len(plan['requires'])} thing(s) it needs.")

    # ------------------------------------------------------------ publish
    def _browse(self) -> None:
        start = self.out.text().strip() or os.path.join(
            os.path.expanduser("~"), f"{self._suggest()}.rr3mod")
        got, _pick = QFileDialog.getSaveFileName(
            self, "Save the pack as", start, "RR3 mod pack (*.rr3mod)")
        if got:
            self.out.setText(got)

    def _suggest(self) -> str:
        kind = self._kind()
        got = self.which.currentData() or ""
        if kind == "career":
            return "career"
        return (got or kind).replace("/", "_").replace("\\", "_")

    def publish(self) -> None:
        out = self.out.text().strip()
        if not out:
            self._browse()
            out = self.out.text().strip()
            if not out:
                return
        kind = self._kind()
        which = self.which.currentData() or ""
        note = self.note_edit.text().strip()
        root = self.root
        picked = ([self.which.itemData(i) for i in range(self.which.count())]
                  if kind in MULTI else [])

        def work():
            if kind == "car":
                return publishlib.car(root, which, out, note=note,
                                      log=lambda m: None)
            if kind == "pages":
                return publishlib.pages(root, picked or [which], out,
                                        note=note, log=lambda m: None)
            if kind == "driver":
                return publishlib.drivers(root, which, out, note=note,
                                          log=lambda m: None)
            if kind == "brand":
                return publishlib.brands(root, which, out, note=note,
                                         log=lambda m: None)
            if kind == "material":
                return publishlib.materials(root, [which], out, note=note,
                                            log=lambda m: None)
            if kind == "career":
                return publishlib.career(root, out, note=note,
                                         log=lambda m: None)
            return publishlib.track(root, which, out, note=note,
                                    log=lambda m: None)

        self.publish_btn.setEnabled(False)
        self.log.note(f"writing {out}...")
        self._task = Task(work, parent=self)
        self._task.done.connect(self._published)
        self._task.fail.connect(self._failed)
        self._task.start()

    def _published(self, made) -> None:
        self.publish_btn.setEnabled(True)
        self._made = made
        info = made.get("manifest") or {}
        self.log.ok(f"{os.path.basename(made['path'])}: {made['files']} file(s), "
                    f"{made['bytes'] / 1048576:.2f} MB")
        for req in info.get("requires") or []:
            self.log.note(f"  needs {req.get('kind')} {req.get('name')}")
        for stem in made.get("missing") or []:
            self.log.error(f"  {stem} is not on disk, so it was left out")
        self.status.emit(f"Published {os.path.basename(made['path'])}")

    def _failed(self, text: str) -> None:
        self.publish_btn.setEnabled(True)
        self.log.error(text)

    # ------------------------------------------------------------ reading
    def open_pack(self) -> None:
        got, _pick = QFileDialog.getOpenFileName(
            self, "Open a pack", os.path.dirname(self.out.text().strip()),
            "RR3 mod pack (*.rr3mod *.zip)")
        if not got:
            return
        self.pack_note.setText(f"Reading {os.path.basename(got)}...")
        self._task = Task(lambda: packlib.check(self.root, got), parent=self)
        self._task.done.connect(self._opened)
        self._task.fail.connect(lambda t: self.pack_note.setText(t))
        self._task.start()

    def _opened(self, info: dict) -> None:
        self._info = info
        self._fill(info)
        state = info["state"]
        warns = len(info.get("warnings") or [])
        if state == "ready":
            said = (f"{info['title'] or info['name']}: a {info['kind']} pack with "
                    f"{len(info['files'])} file(s). Everything it needs is here.")
            if warns:
                # A missing shared page does not stop the install, so the pack is
                # still ready - but saying "everything is here" would be a lie.
                said = (f"{info['title'] or info['name']}: a {info['kind']} pack "
                        f"with {len(info['files'])} file(s). It can be installed, "
                        f"with {warns} page(s) missing - see the log below.")
            self.pack_note.setText(said)
        elif state == "missing":
            self.pack_note.setText(
                f"{info['title'] or info['name']}: a {info['kind']} pack with "
                f"{len(info['files'])} file(s), and it needs "
                f"{len(info['unsatisfied'])} thing(s) this install does not have.")
        else:
            self.pack_note.setText(
                f"{info['title'] or info['name']}: a {info['kind']} pack with "
                f"{len(info['files'])} file(s). Nothing in it is installed yet.")
        self.install_btn.setEnabled(not info["problems"])
        for problem in info["problems"]:
            self.log.error(problem)
        for warning in info.get("warnings") or []:
            self.log.note(warning)
        if info.get("note"):
            self.log.note(info["note"])

    def _fill(self, info: dict) -> None:
        rows = []
        for req in info.get("unsatisfied") or []:
            rows.append((req.get("name", ""), req.get("kind", ""),
                         req.get("note") or "not here"))
        for rel in info.get("files") or []:
            rows.append((rel, "file", "in the pack"))
        self.table.setRowCount(len(rows))
        for r, (what, kind, where) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(str(what)))
            self.table.setItem(r, 1, QTableWidgetItem(str(kind)))
            self.table.setItem(r, 2, QTableWidgetItem(str(where)))

    def install(self) -> None:
        if not self._info:
            return
        info = self._info
        path = info["path"]
        family = self.family.currentData() or "auto"
        if family == "auto":
            family = ""

        # Ask about the safety net before writing anything, because the answer
        # decides what the install has to do - and because a question asked
        # afterwards would be a question about work already done.
        going = info.get("changes") or []
        box = QMessageBox(self)
        box.setWindowTitle("Install")
        box.setIcon(QMessageBox.Question)
        box.setText(f"Install {info.get('title') or info['name']}?")
        box.setInformativeText(
            f"{len(going)} file(s) of yours would be replaced.\n\n"
            "A copy of the ones it replaces can be kept, so the install can be "
            "walked back later. That costs only the size of those files.")
        keep_box = box.addButton("Keep a copy, then install",
                                 QMessageBox.AcceptRole)
        box.addButton("Install, no copy", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(keep_box)
        box.exec()
        clicked = box.clickedButton()
        keep = clicked is keep_box
        if not keep and box.buttonRole(clicked) != QMessageBox.DestructiveRole:
            return                            # Cancel, or the window was closed

        def work():
            return publishlib.install(self.root, path, family=family, keep=keep,
                                      log=lambda m: None)

        self.install_btn.setEnabled(False)
        self._task = Task(work, parent=self)
        self._task.done.connect(self._installed)
        self._task.fail.connect(self._failed)
        self._task.start()

    def _installed(self, done: dict) -> None:
        self.install_btn.setEnabled(True)
        if done.get("materials"):
            self.log.ok(f"installed {done['name']}: "
                        f"{len(done['materials'])} material(s) - "
                        f"{', '.join(done['materials'])}")
        else:
            self.log.ok(f"installed {done['name']}: {done['written']} file(s)")
        for page in done.get("pages") or []:
            self.log.note(f"  {page['rel']} as {page['family'].upper()}, "
                          f"{page['bytes']:,} bytes")
        self.status.emit(f"Installed {done['name']}")
        self.changed.emit()
