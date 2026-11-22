"""The Animation tab of the car detail pane.

Two things live here, and they answer the two questions the game leaves open:

* **which track drives which part** - the game pairs them by name order and
  nothing in the file says otherwise, so when a car comes out wrong the fix is
  to renumber the tracks.  The table shows what each track actually does (its
  pivot and how far it rotates) next to the part name order says it belongs to,
  which is usually enough to spot the mistake by eye: the strut that does not
  move is sitting on the track with 40 degrees of travel.
* **when each transition plays** - ``_animations.xml`` is a list of frame
  ranges.  Editing it is safe; the game looks the clips up by name.

Nothing is written until Save, and Save writes both files in one go so the two
cannot disagree about how many frames the animation has.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QScrollArea,
                               QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import anim as animlib
from .. import edit as editlib
from . import widgets as W

#: clips a car with active aero normally has, in the order the game lists them
CLIP_NAMES = animlib.animxmllib.CLIP_ORDER


def stretchable(table: QTableWidget, widths) -> None:
    """Let the user drag every column, with a sensible width to start from.

    ``ResizeToContents`` looks tidy but takes the choice away, and this pane has
    columns whose text is a whole material or mesh name - the one that has to be
    readable is the one the user is looking for.  Interactive plus a starting
    width gives both.
    """
    head = table.horizontalHeader()
    head.setSectionResizeMode(QHeaderView.Interactive)
    head.setStretchLastSection(True)
    for column, width in enumerate(widths):
        table.setColumnWidth(column, width)


class AnimPane(QWidget):
    """Track numbering and clip timing for one car."""

    changed = Signal()          # something was written to disk
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = ""
        self.car = ""
        self.info = None
        self.editor = None          # rrmod.ui.editing.Editor, set by the detail pane
        self._mapping = {}
        self._clips = []

        # The whole pane scrolls: a car with six clips and four tracks needs more
        # room than a detail pane usually gets, and squeezing the tables down to
        # one visible row is worse than scrolling.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(6)

        self.header = W.muted("No car selected.")
        lay.addWidget(self.header)

        # ---- the behaviour flag ---------------------------------------
        row = QHBoxLayout()
        self.aero_box = QCheckBox("The game moves this wing")
        self.aero_box.setToolTip(
            "Without a behaviour in the car's spec the game never plays the "
            "animation, however good the curves are. Adding a wing to a car "
            "the studio left out needs this, the banim, the xml and the "
            "livery rows.")
        self.aero_box.setEnabled(False)
        self.aero_box.clicked.connect(self._aero_clicked)
        row.addWidget(self.aero_box)
        row.addWidget(QLabel("Behaviour"))
        self.aero_kind = QComboBox()
        for label, value in animlib.AERO_CHOICES:
            self.aero_kind.addItem(label, value)
        self.aero_kind.setToolTip(
            "DeployWhenBraking lifts the wing under braking (air brake). "
            "DeployAtSpeed flattens it above a speed (drag reduction). "
            "BrakeAndSpeedCombo does both - that is what the Senna, the Jesko "
            "and the Battistas use. NascarAirBrake is the NASCAR flap.")
        self.aero_kind.setEnabled(False)
        self.aero_kind.currentIndexChanged.connect(self._aero_kind_changed)
        row.addWidget(self.aero_kind)
        row.addWidget(QLabel("at"))
        self.aero_high = QDoubleSpinBox()
        self.aero_high.setRange(0.0, 600.0)
        self.aero_high.setDecimals(1)
        self.aero_high.setSuffix(" km/h")
        self.aero_high.setToolTip(
            "The speed the wing flattens at. The shipped cars put the higher "
            "number first, and only DeployAtSpeed and BrakeAndSpeedCombo use "
            "these two.")
        row.addWidget(self.aero_high)
        row.addWidget(QLabel("back at"))
        self.aero_low = QDoubleSpinBox()
        self.aero_low.setRange(0.0, 600.0)
        self.aero_low.setDecimals(1)
        self.aero_low.setSuffix(" km/h")
        row.addWidget(self.aero_low)
        row.addStretch(1)
        lay.addLayout(row)
        self.aero_note = W.muted("")
        lay.addWidget(self.aero_note)

        # ---- the driver's pose ----------------------------------------
        lay.addWidget(W.heading("Driver pose", 3))
        self.driver_note = W.muted("")
        lay.addWidget(self.driver_note)
        row = QHBoxLayout()
        self.driver_pose = QComboBox()
        self.driver_pose.setMinimumWidth(280)
        self.driver_pose.setToolTip(
            "The seated pose the game puts a driver in for this car. The game "
            "names it in the car's own data record; a car that names none uses "
            "the generic driver.banim.")
        self.driver_pose.setEnabled(False)
        self.driver_pose.currentIndexChanged.connect(self._driver_changed)
        row.addWidget(self.driver_pose, 1)
        row.addStretch(1)
        lay.addLayout(row)
        self.driver_low = W.muted("")
        lay.addWidget(self.driver_low)

        # ---- tracks ----------------------------------------------------
        lay.addWidget(W.heading("Tracks", 3))
        lay.addWidget(W.muted(
            "The game hands out track numbers in name order: the first part "
            "alphabetically plays track 0. If a car animates the wrong part, "
            "swap two tracks here."))
        self.tracks = QTableWidget(0, 5)
        self.tracks.setHorizontalHeaderLabels(
            ("Track", "Plays the part", "Pivot (x, y, z)", "Rotates", "Keys"))
        self.tracks.verticalHeader().setVisible(False)
        self.tracks.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tracks.setSelectionBehavior(QAbstractItemView.SelectRows)
        stretchable(self.tracks, (64, 260, 200, 130, 70))
        self.tracks.setMinimumHeight(120)
        lay.addWidget(self.tracks)

        row = QHBoxLayout()
        self.swap_a = QComboBox()
        self.swap_b = QComboBox()
        row.addWidget(QLabel("Swap track"))
        row.addWidget(self.swap_a)
        row.addWidget(QLabel("with"))
        row.addWidget(self.swap_b)
        self.swap_btn = W.button("Swap", self._swap, tip="Renumber these two tracks")
        self.swap_btn.setEnabled(False)
        row.addWidget(self.swap_btn)
        self.reset_btn = W.button("Reset numbering", self._reset)
        self.reset_btn.setEnabled(False)
        row.addWidget(self.reset_btn)
        row.addStretch(1)
        lay.addLayout(row)

        # ---- clips -----------------------------------------------------
        lay.addWidget(W.heading("Clips", 3))
        self.clip_note = W.muted("")
        lay.addWidget(self.clip_note)
        self.clips = QTableWidget(0, 4)
        self.clips.setHorizontalHeaderLabels(("Clip", "Start", "End", "Note"))
        self.clips.verticalHeader().setVisible(False)
        stretchable(self.clips, (180, 70, 70, 420))
        self.clips.setMinimumHeight(150)
        self.clips.itemChanged.connect(self._clip_edited)
        lay.addWidget(self.clips, 1)

        row = QHBoxLayout()
        self.new_clip = QComboBox()
        self.new_clip.setEditable(True)
        for name in CLIP_NAMES:
            self.new_clip.addItem(name)
        row.addWidget(QLabel("Add clip"))
        row.addWidget(self.new_clip, 1)
        self.new_start = QSpinBox()
        self.new_start.setRange(0, 9999)
        self.new_end = QSpinBox()
        self.new_end.setRange(0, 9999)
        row.addWidget(QLabel("from"))
        row.addWidget(self.new_start)
        row.addWidget(QLabel("to"))
        row.addWidget(self.new_end)
        self.add_btn = W.button("Add", self._add_clip)
        row.addWidget(self.add_btn)
        self.del_btn = W.button("Remove selected", self._remove_clip)
        row.addWidget(self.del_btn)
        row.addStretch(1)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addStretch(1)
        self.suggest_btn = W.button(
            "Use a default set", self._suggest,
            tip="Rest / up / down spanning the whole banim")
        row.addWidget(self.suggest_btn)
        self.save_btn = W.button("Save animation", self._save, primary=True,
                                 tip="Write the banim and the xml back into the install")
        self.save_btn.setEnabled(False)
        row.addWidget(self.save_btn)
        lay.addLayout(row)

        self.log = W.LogPane()
        self.log.setMinimumHeight(60)
        lay.addWidget(self.log)
        lay.addStretch(1)

        self._scroll.setWidget(body)
        outer.addWidget(self._scroll)

    def _idle(self) -> None:
        """Put every control into the "nothing to edit" state."""
        self.tracks.setRowCount(0)
        self.clips.setRowCount(0)
        self.swap_a.clear()
        self.swap_b.clear()
        for w in (self.swap_a, self.swap_b, self.swap_btn, self.reset_btn,
                  self.add_btn, self.del_btn, self.suggest_btn, self.save_btn,
                  self.aero_box, self.driver_pose):
            w.setEnabled(False)
        self.aero_note.setText("")
        self.driver_note.setText("")
        self.driver_low.setText("")

    def _read_root(self) -> str:
        """Read from the game folder the editor is on, else from the install."""
        if self.editor is not None:
            return self.editor.read_root(self.car)
        return self.root

    def _edit_root(self) -> str:
        """Where an edit should be written, and a place it can be written to."""
        if self.editor is not None:
            return self.editor.for_car(self.car)
        return self.root

    def _load_aero(self) -> None:
        """Show the spec's behaviour, without writing anything."""
        try:
            state = animlib.aero_state(self._read_root(), self.car)
        except Exception as exc:                 # noqa: BLE001
            self.aero_note.setText(f"Could not read the spec: {exc}")
            return
        for widget in (self.aero_box, self.aero_kind, self.aero_high,
                       self.aero_low):
            widget.blockSignals(True)
        self.aero_box.setChecked(state["enabled"])
        if state["kind"]:
            at = self.aero_kind.findData(state["kind"].encode())
            if at >= 0:
                self.aero_kind.setCurrentIndex(at)
        params = state["params"]
        self.aero_high.setValue(float(params[0]) if params else 0.0)
        self.aero_low.setValue(float(params[1]) if len(params) > 1 else 0.0)
        for widget in (self.aero_box, self.aero_kind, self.aero_high,
                       self.aero_low):
            widget.blockSignals(False)
        self.aero_box.setEnabled(bool(state["spec"]))
        self._aero_enable_rest(bool(state["spec"]))
        if not state["spec"]:
            self.aero_note.setText("This car has no spec file - cannot set the behaviour.")
        elif state["enabled"]:
            self.aero_note.setText(f"Behaviour: {state['flag']}")
        elif not (self.info and self.info.get("banim")):
            # The flag and the animation are two different things.  A car with
            # the flag but no _wing.banim has nothing for the game to play, and a
            # car with the banim but no flag never gets played at all - so say
            # which half is missing instead of letting the user find out in game.
            self.aero_note.setText(
                "Behaviour: none. This car has no wing animation, so the game has "
                "nothing to move - set the behaviour anyway if a banim is on its way.")
        else:
            self.aero_note.setText(
                "Behaviour: none. The game will never play this animation until "
                "one is picked.")

    def _aero_enable_rest(self, on: bool) -> None:
        """Numbers only matter for the two behaviours that take them."""
        value = self.aero_kind.currentData()
        numeric = on and value in animlib.AERO_PARAMETRIC
        self.aero_kind.setEnabled(on)
        self.aero_high.setEnabled(numeric)
        self.aero_low.setEnabled(numeric)

    def _aero_kind_changed(self) -> None:
        self._aero_enable_rest(self.aero_box.isEnabled())

    def _aero_clicked(self) -> None:
        want = self.aero_box.isChecked()
        kind = self.aero_kind.currentData() or b""
        params = ()
        if kind in animlib.AERO_PARAMETRIC:
            params = (self.aero_high.value(), self.aero_low.value())
        label = self.aero_kind.currentText()
        ok = QMessageBox.question(
            self, "Active aero",
            f"Set the wing behaviour of {self.car} to "
            f"{'nothing' if not want else label}?\n\n"
            "This rewrites the car's spec. File > Undo last edit puts the "
            "previous file back.")
        if ok != QMessageBox.Yes:
            self._load_aero()
            return
        try:
            got = editlib.set_aero_flag(self._edit_root(), self.car, want,
                                        kind=kind if want else b"",
                                        params=params if want else ())
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Active aero", str(exc))
            self._load_aero()
            return
        self.log.ok(f"spec: {got['before'] or '(none)'} -> {got['after'] or '(none)'}")
        self.changed.emit()
        self.status.emit(f"Wing behaviour of {self.car} updated")
        self._load_aero()

    # ---- the driver's pose ---------------------------------------------
    def _load_driver(self) -> None:
        """Show which seated pose the car uses, without writing anything."""
        self.driver_pose.blockSignals(True)
        self.driver_pose.clear()
        self.driver_pose.addItem("The generic driver.banim", "")
        try:
            state = animlib.driver_state(self._read_root(), self.car)
        except Exception as exc:                 # noqa: BLE001
            self.driver_note.setText(f"Could not read the data record: {exc}")
            self.driver_pose.blockSignals(False)
            self.driver_pose.setEnabled(False)
            self.driver_low.setText("")
            return
        for stem in state["choices"]:
            if stem == "driver":
                continue                         # the generic one is the first row
            self.driver_pose.addItem(stem, stem + ".banim")
        at = self.driver_pose.findData(state["banim"])
        self.driver_pose.setCurrentIndex(at if at >= 0 else 0)
        self.driver_pose.blockSignals(False)

        enabled = bool(state["record"])
        self.driver_pose.setEnabled(enabled)
        if not enabled:
            self.driver_note.setText(
                "This car has no data record in this install, so there is no "
                "pose field to change.")
            self.driver_low.setText("")
            return
        if state["banim"]:
            self.driver_note.setText(f"Pose: {state['banim']}")
        else:
            self.driver_note.setText(
                "Pose: none named, so the game seats this car with driver.banim.")
        if state["own_low_poly"]:
            self.driver_low.setText(
                f"This pose has its own low-poly model, "
                f"{os.path.basename(state['own_low_poly'])}, so the figure seen "
                f"from outside is shaped for it.")
        elif state["banim"]:
            self.driver_low.setText(
                f"This pose has no low-poly model of its own, so the outside view "
                f"uses the generic driver_lod_c.m3g and the figure holds a pose "
                f"nothing modelled for it. The game copes; it just looks approximate.")
        else:
            self.driver_low.setText("")

    def _driver_changed(self) -> None:
        want = self.driver_pose.currentData() or ""
        label = self.driver_pose.currentText()
        ok = QMessageBox.question(
            self, "Driver pose",
            f"Seat the driver of {self.car} with "
            f"{'the generic driver.banim' if not want else label}?\n\n"
            "This rewrites the car's data record, not its spec. File > Undo last "
            "edit puts the previous file back.")
        if ok != QMessageBox.Yes:
            self._load_driver()
            return
        try:
            got = editlib.set_driver_pose(self._edit_root(), self.car, want)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Driver pose", str(exc))
            self._load_driver()
            return
        if got["changed"]:
            self.log.ok(f"pose: {got['before'] or '(generic)'} -> "
                        f"{got['after'] or '(generic)'}")
            self.changed.emit()
            self.status.emit(f"Driver pose of {self.car} updated")
        self._load_driver()

    # ---- loading ------------------------------------------------------
    def load(self, root: str, car: str) -> None:
        self.root = root
        self.car = car
        self._mapping = {}
        self._clips = []
        if not root or not car:
            self.info = None
            self.header.setText("No car selected.")
            self._idle()
            return
        try:
            self.info = animlib.read(self._read_root(), car)
        except Exception as exc:                 # noqa: BLE001
            self.info = None
            self.header.setText(f"Could not read the animation: {exc}")
            self._idle()
            self._load_aero()                    # _idle() clears the note, so last
            self._load_driver()                  # the pose is a separate file
            return
        info = self.info
        if not info["banim"]:
            self.header.setText(f"{car} has no {animlib.BANIM_SUFFIX} - nothing to edit.")
            self._idle()
            self._load_aero()                    # the flag still matters on its own
            self._load_driver()                  # so does the driver's pose
            return
        self.header.setText(
            f"{info['duration_ms']:.0f} ms = {info['frames']} frames at "
            f"{animlib.FRAME_MS:g} ms each, variant 0x{info['variant']:02x}. "
            f"{len(info['tracks'])} track(s), {len(info['parts'])} wing part(s).")
        self._clips = list(info["clips"])
        self._fill_tracks()
        self._fill_clips()
        self._load_aero()
        self._load_driver()
        self.save_btn.setEnabled(True)
        for w in info["warnings"]:
            self.log.note(w)

    def _fill_tracks(self) -> None:
        tracks = self.info["tracks"]
        self.tracks.setRowCount(len(tracks))
        self.swap_a.clear()
        self.swap_b.clear()
        for t in tracks:
            i = t["index"]
            self.tracks.setItem(i, 0, QTableWidgetItem(str(i)))
            self.tracks.setItem(i, 1, QTableWidgetItem(t["part"] or "(no name)"))
            self.tracks.setItem(i, 2, QTableWidgetItem(
                ", ".join(f"{v:.3f}" for v in t["pivot"])))
            item = QTableWidgetItem(f"{t['travel']:.1f} deg")
            if t["travel"] == 0:
                item.setForeground(Qt.gray)
            self.tracks.setItem(i, 3, item)
            self.tracks.setItem(i, 4, QTableWidgetItem(str(t["keys"])))
            self.swap_a.addItem(f"{i} - {t['part'] or 'unnamed'}", i)
            self.swap_b.addItem(f"{i} - {t['part'] or 'unnamed'}", i)
        has_two = len(tracks) > 1
        self.swap_btn.setEnabled(has_two)
        self.swap_a.setEnabled(has_two)
        self.swap_b.setEnabled(has_two)
        if has_two:
            self.swap_b.setCurrentIndex(1)
        self.reset_btn.setEnabled(bool(self._mapping))
        for w in (self.add_btn, self.del_btn, self.suggest_btn):
            w.setEnabled(True)

    def _fill_clips(self) -> None:
        self.clips.blockSignals(True)
        self.clips.setRowCount(len(self._clips))
        for i, c in enumerate(self._clips):
            name = QTableWidgetItem(c.name)
            name.setData(Qt.UserRole, i)
            self.clips.setItem(i, 0, name)
            for col, value in ((1, c.start), (2, c.end)):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.clips.setItem(i, col, item)
            note = "backwards" if c.reversed else ""
            doc = c.doc()
            if doc:
                note = f"{note}; {doc}" if note else doc
            self.clips.setItem(i, 3, QTableWidgetItem(note))
        self.clips.blockSignals(False)
        warn = animlib.validate(self._clips, self.info["duration_ms"]) \
            if self.info else []
        self.clip_note.setText(
            "  ".join(warn) if warn else
            f"{len(self._clips)} clip(s); a clip whose end is below its start "
            f"plays backwards.")

    # ---- track swaps --------------------------------------------------
    def _swap(self) -> None:
        a = self.swap_a.currentData()
        b = self.swap_b.currentData()
        if a is None or b is None or a == b:
            return
        mapping = dict(self._mapping)
        for i in range(len(self.info["tracks"])):
            mapping.setdefault(i, i)
        mapping[a], mapping[b] = mapping[b], mapping[a]
        self._mapping = mapping
        # show the effect immediately, using the source tracks
        src = {t["index"]: t for t in self.info["tracks"]}
        shown = []
        for i in range(len(self.info["tracks"])):
            t = dict(src[mapping[i]])
            t["index"] = i
            shown.append(t)
        self.info["tracks"] = shown
        self._fill_tracks()
        self.save_btn.setEnabled(True)
        self.log.ok(f"track {a} <-> {b} (not saved yet")
        self.status.emit(f"Swapped tracks {a} and {b} - press Save animation")

    def _reset(self) -> None:
        self._mapping = {}
        self.load(self.root, self.car)

    # ---- clip edits ---------------------------------------------------
    def _clip_edited(self, item) -> None:
        row = item.row()
        if row >= len(self._clips) or item.column() not in (1, 2):
            return
        c = self._clips[row]
        try:
            value = int(item.text())
        except ValueError:
            self.log.error(f"{item.text()!r} is not a frame number")
            self._fill_clips()
            return
        if item.column() == 1:
            self._clips[row] = animlib.animxmllib.Clip(c.name, value, c.end)
        else:
            self._clips[row] = animlib.animxmllib.Clip(c.name, c.start, value)
        self._fill_clips()
        self.save_btn.setEnabled(True)

    def _add_clip(self) -> None:
        name = self.new_clip.currentText().strip()
        if not name:
            return
        self._clips = animlib.set_clip(self._clips, name,
                                       self.new_start.value(), self.new_end.value())
        self._fill_clips()
        self.save_btn.setEnabled(True)

    def _remove_clip(self) -> None:
        row = self.clips.currentRow()
        if row < 0 or row >= len(self._clips):
            return
        self._clips = animlib.remove_clip(self._clips, self._clips[row].name)
        self._fill_clips()
        self.save_btn.setEnabled(True)

    def _suggest(self) -> None:
        if not self.info:
            return
        self._clips = animlib.suggest_clips(self.info["duration_ms"])
        self._fill_clips()
        self.save_btn.setEnabled(True)
        self.log.note("rest / up / down across the whole banim")

    # ---- saving -------------------------------------------------------
    def _save(self) -> None:
        if not self.info or not self.root:
            return
        what = []
        if self._mapping:
            what.append("the track numbering")
        if self._clips != self.info["clips"]:
            what.append(f"{len(self._clips)} clip(s)")
        if not what:
            QMessageBox.information(self, "Save animation",
                                    "Nothing has changed.")
            return
        ok = QMessageBox.question(
            self, "Save animation",
            f"Write {' and '.join(what)} for {self.car}?\n\n"
            "The banim and the xml are written together, and the manifests are "
            "updated. File > Undo last edit puts the previous files back.")
        if ok != QMessageBox.Yes:
            return
        try:
            if self._mapping:
                got = animlib.apply_swap(self._edit_root(), self.car, self._mapping)
                self.log.ok(f"banim: {got['bytes']} bytes")
            if self._clips != self.info["clips"]:
                got = animlib.apply_xml(self._edit_root(), self.car, self._clips)
                self.log.ok(f"xml: {got['clips']} clip(s)")
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Save animation", str(exc))
            return
        self._mapping = {}
        self.changed.emit()
        self.status.emit(f"Animation written for {self.car} - the Test tab "
                         f"pushes it to the device")
        self.load(self.root, self.car)
