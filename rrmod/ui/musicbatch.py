"""Batch edits for the BGM playlists.

Editing 167 events one at a time is the wrong shape of work: what people
actually want is "give every Bathurst event the same three songs" or "spread
these five songs across the whole race calendar".  This dialog builds a plan
with :mod:`rrmod.music` and hands it back to the page, which stages it exactly
like a hand edit - nothing is written until Save.

The dialog never touches the disk.  It also previews how many slot values would
really change, so a plan that happens to match the current data is obvious
before it is applied.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QGroupBox,
                               QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QRadioButton,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import music as musiclib
from . import widgets as W

#: what the batch can do
ACTIONS = (
    ("assign", "Set the three slots to these songs"),
    ("cycle", "Cycle these songs across the playlists"),
    ("shuffle", "Pick three songs at random for each playlist"),
    ("rotate", "Rotate the existing slots"),
    ("replace", "Replace one song with another"),
    ("clear", "Clear one slot"),
)


class BatchDialog(QDialog):
    """Builds a plan for many playlists at once."""

    def __init__(self, playlists, songs, *, selected=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch edit playlists")
        self.resize(640, 660)
        self.playlists = list(playlists)
        self.songs = list(songs)
        self.selected = selected
        self.plan = {}
        self._ticked = []
        self._shown = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # ---- scope -----------------------------------------------------
        scope = QGroupBox("Which playlists")
        sv = QVBoxLayout(scope)
        self.scope_all = QRadioButton(f"All {len(self.playlists)} playlists")
        self.scope_all.setChecked(True)
        sv.addWidget(self.scope_all)
        self.scope_ticked = QRadioButton("Only the ticked ones")
        self.scope_ticked.setEnabled(False)
        sv.addWidget(self.scope_ticked)
        self.scope_shown = QRadioButton("Only the ones the filter is showing")
        self.scope_shown.setEnabled(False)
        sv.addWidget(self.scope_shown)
        self.scope_one = QRadioButton("Only the selected playlist")
        self.scope_one.setEnabled(bool(selected))
        if selected and not self.playlists:
            self.scope_one.setChecked(True)
        sv.addWidget(self.scope_one)
        lay.addWidget(scope)

        # ---- action ----------------------------------------------------
        action = QGroupBox("What to do")
        av = QVBoxLayout(action)
        self.action = QComboBox()
        for key, label in ACTIONS:
            self.action.addItem(label, key)
        self.action.currentIndexChanged.connect(self._action_changed)
        av.addWidget(self.action)

        self.assign_box = self._song_picker("Slots", 3)
        av.addWidget(self.assign_box)

        self.cycle_box = QWidget()
        cv = QVBoxLayout(self.cycle_box)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(4)
        cv.addWidget(W.muted(
            "Pick two or more songs.  Each playlist takes a different window of "
            "them, so neighbouring events share two of three tracks."))
        self.cycle_list = QListWidget()
        self.cycle_list.setSelectionMode(QListWidget.MultiSelection)
        for s in self.songs:
            item = QListWidgetItem(s)
            if musiclib.is_menu_song(s):
                item.setForeground(Qt.gray)
                item.setToolTip("front-end cue, not a race track")
            self.cycle_list.addItem(item)
        self.cycle_list.setMaximumHeight(150)
        cv.addWidget(self.cycle_list)
        row = QHBoxLayout()
        row.addWidget(QLabel("Start at"))
        self.cycle_start = QSpinBox()
        self.cycle_start.setRange(0, 32)
        row.addWidget(self.cycle_start)
        self.cycle_keep = QRadioButton("Leave slot 1 alone")
        row.addWidget(self.cycle_keep)
        row.addStretch(1)
        cv.addLayout(row)
        av.addWidget(self.cycle_box)

        self.shuffle_box = QWidget()
        shv = QVBoxLayout(self.shuffle_box)
        shv.setContentsMargins(0, 0, 0, 0)
        shv.setSpacing(4)
        shv.addWidget(W.muted(
            "Three songs per playlist, drawn from the pool below.  No playlist "
            "repeats a track inside itself and no two neighbours get the same "
            "triple.  Change the seed for a different draw."))
        self.shuffle_list = QListWidget()
        self.shuffle_list.setSelectionMode(QListWidget.MultiSelection)
        for s in self.songs:
            item = QListWidgetItem(s)
            if musiclib.is_menu_song(s):
                item.setForeground(Qt.gray)
                item.setToolTip("front-end cue, not a race track")
            else:
                item.setSelected(True)
            self.shuffle_list.addItem(item)
        self.shuffle_list.setMaximumHeight(150)
        shv.addWidget(self.shuffle_list)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Seed"))
        self.shuffle_seed = QSpinBox()
        self.shuffle_seed.setRange(0, 99999)
        self.shuffle_seed.setValue(1)
        self.shuffle_seed.valueChanged.connect(self._preview)
        srow.addWidget(self.shuffle_seed)
        self.shuffle_keep = QRadioButton("Leave slot 1 alone")
        self.shuffle_keep.toggled.connect(self._preview)
        srow.addWidget(self.shuffle_keep)
        srow.addStretch(1)
        shv.addLayout(srow)
        av.addWidget(self.shuffle_box)

        self.rotate_box = QWidget()
        rv = QHBoxLayout(self.rotate_box)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("Shift the slots by"))
        self.rotate_steps = QComboBox()
        self.rotate_steps.addItem("one slot (1 -> 2 -> 3 -> 1)", 1)
        self.rotate_steps.addItem("two slots (1 <-> 2 <-> 3)", 2)
        self.rotate_steps.currentIndexChanged.connect(self._preview)
        rv.addWidget(self.rotate_steps, 1)
        av.addWidget(self.rotate_box)

        self.replace_box = QWidget()
        pv = QHBoxLayout(self.replace_box)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(QLabel("Replace"))
        self.replace_old = QComboBox()
        for s in self.songs:
            self.replace_old.addItem(s, s)
        self.replace_old.currentIndexChanged.connect(self._preview)
        pv.addWidget(self.replace_old, 1)
        pv.addWidget(QLabel("with"))
        self.replace_new = QComboBox()
        for s in self.songs:
            self.replace_new.addItem(s, s)
        self.replace_new.currentIndexChanged.connect(self._preview)
        pv.addWidget(self.replace_new, 1)
        av.addWidget(self.replace_box)

        self.clear_box = QWidget()
        lv = QHBoxLayout(self.clear_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Clear"))
        self.clear_slot = QComboBox()
        for label in musiclib.LABELS:
            self.clear_slot.addItem(label, label)
        self.clear_slot.currentIndexChanged.connect(self._preview)
        lv.addWidget(self.clear_slot, 1)
        av.addWidget(self.clear_box)

        lay.addWidget(action)
        lay.addWidget(W.muted(
            "Nothing is written here.  Apply stages the plan as unsaved "
            "changes; Save on the main page writes the .nct files."))
        self.preview = W.muted("")
        lay.addWidget(self.preview)
        lay.addStretch(1)

        buttons = QDialogButtonBox()
        self.apply_btn = buttons.addButton("Apply", QDialogButtonBox.AcceptRole)
        self.apply_btn.setDefault(True)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        for box in (self.assign_box, self.cycle_box, self.shuffle_box,
                    self.rotate_box, self.replace_box, self.clear_box):
            box.setVisible(False)
        self._action_changed()

    # ---- helpers ------------------------------------------------------
    def _song_picker(self, caption: str, count: int) -> QWidget:
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        outer.addWidget(W.muted(caption))
        self.assign_combos = []
        for i in range(count):
            row = QHBoxLayout()
            tag = QLabel(musiclib.LABELS[i])
            tag.setFixedWidth(104)
            tag.setStyleSheet("color:#666;")
            row.addWidget(tag)
            combo = QComboBox()
            combo.addItem("(none)", "")
            for s in self.songs:
                combo.addItem(s, s)
            combo.currentIndexChanged.connect(self._preview)
            row.addWidget(combo, 1)
            outer.addLayout(row)
            self.assign_combos.append(combo)
        return box

    def set_scope_choices(self, *, shown: int) -> None:
        """The page tells us how many rows the filter currently shows."""
        self.scope_shown.setEnabled(shown > 0)
        self.scope_shown.setText(
            f"Only the {shown} playlist(s) the filter is showing")

    def set_shown(self, playlists) -> None:
        self._shown = list(playlists)
        self.set_scope_choices(shown=len(self._shown))

    def set_ticked(self, names) -> None:
        """The page tells us which events carry a tick."""
        self._ticked = list(names)
        self.scope_ticked.setEnabled(bool(self._ticked))
        self.scope_ticked.setText(
            f"Only the {len(self._ticked)} ticked playlist(s)")

    def prefer_ticked(self) -> None:
        """Called when the dialog was opened from the ticked rows."""
        if self._ticked:
            self.scope_ticked.setChecked(True)
        self._preview()

    def _action_changed(self) -> None:
        key = self.action.currentData()
        self.assign_box.setVisible(key == "assign")
        self.cycle_box.setVisible(key == "cycle")
        self.shuffle_box.setVisible(key == "shuffle")
        self.rotate_box.setVisible(key == "rotate")
        self.replace_box.setVisible(key == "replace")
        self.clear_box.setVisible(key == "clear")
        self._preview()

    def _chosen(self) -> list:
        if self.scope_one.isChecked() and self.selected:
            return [pl for pl in self.playlists if pl.name == self.selected]
        if self.scope_ticked.isChecked() and self._ticked:
            wanted = set(self._ticked)
            return [pl for pl in self.playlists if pl.name in wanted]
        if self.scope_shown.isChecked():
            return list(getattr(self, "_shown", []))
        return list(self.playlists)

    def _build(self) -> dict:
        key = self.action.currentData()
        chosen = self._chosen()
        if not chosen:
            raise musiclib.MusicError("no playlists in that scope")
        if key == "assign":
            values = {}
            for label, combo in zip(musiclib.LABELS, self.assign_combos):
                values[label] = combo.currentData() or ""
            return {pl.name: musiclib.assign(pl, values) for pl in chosen}
        if key == "cycle":
            songs = [i.text() for i in self.cycle_list.selectedItems()]
            return musiclib.cycle(chosen, songs,
                                  start=self.cycle_start.value(),
                                  keep_first=self.cycle_keep.isChecked())
        if key == "shuffle":
            songs = [i.text() for i in self.shuffle_list.selectedItems()]
            return musiclib.shuffle(chosen, songs,
                                    seed=self.shuffle_seed.value(),
                                    keep_first=self.shuffle_keep.isChecked())
        if key == "rotate":
            return musiclib.rotate(chosen, self.rotate_steps.currentData())
        if key == "replace":
            return musiclib.replace_song(chosen, self.replace_old.currentData(),
                                         self.replace_new.currentData())
        if key == "clear":
            return musiclib.clear_slot(chosen, self.clear_slot.currentData())
        raise musiclib.MusicError(f"unknown action {key!r}")

    def _preview(self) -> None:
        try:
            plan = self._build()
        except Exception as exc:                 # noqa: BLE001
            self.preview.setText(str(exc))
            self.apply_btn.setEnabled(False)
            return
        n = musiclib.diff(self.playlists, plan)
        self.preview.setText(
            f"{len(plan)} playlist(s) in scope, {n} slot value(s) would change")
        self.apply_btn.setEnabled(True)

    def _apply(self) -> None:
        try:
            plan = self._build()
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.warning(self, "Batch edit", str(exc))
            return
        n = musiclib.diff(self.playlists, plan)
        if not n:
            QMessageBox.information(
                self, "Batch edit",
                "That plan matches what the playlists already say, so there is "
                "nothing to change.")
            return
        self.plan = plan
        self.accept()
