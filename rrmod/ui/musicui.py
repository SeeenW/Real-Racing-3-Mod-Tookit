"""The BGM editor: three song slots per event, grouped by circuit.

167 playlists, each naming up to three tracks under ``audio/music``.  Every
event is one circuit at one time of day, so the list is a tree: the circuits are
the parents and their events the children.  That is the shape the work actually
has - "give every Bathurst race the same three songs" is one tick on the parent.

Two tabs:

* **Tracks** - the tree, the three slots of whichever event is selected, and the
  batch dialog for the ticked rows.
* **Audio files** - what is in ``audio/music``, how often each one is used, and
  which ones no event plays at all.  A song can be imported here; it is copied
  into the folder and becomes selectable everywhere.

Changes stay in memory until Save, and Save writes the ``.nct`` back through the
same RC4 the game reads - no external tool involved.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QSplitter, QTabWidget,
                               QTableWidget, QTableWidgetItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import music as musiclib
from . import widgets as W
from .musicbatch import BatchDialog
from .worker import Task


class MusicPage(QWidget):
    """Circuits and their events on the left, the three slots on the right."""

    status = Signal(str)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.depot = ""
        self.editor = None
        self.playlists = []
        self.songs = []
        self._dirty = {}
        self._rows = []
        self._by_name = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter circuits and events")
        self.search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.search, 1)
        self.batch_btn = W.button(
            "Batch edit...", self.batch,
            tip="Set, cycle, rotate or replace the songs of many events at once")
        bar.addWidget(self.batch_btn)
        self.tick_all_btn = W.button("Tick everything", self.tick_all,
                                     tip="Tick every event the filter is showing")
        bar.addWidget(self.tick_all_btn)
        self.tick_none_btn = W.button("Untick", self.tick_none)
        bar.addWidget(self.tick_none_btn)
        self.reload_btn = W.button("Reload", self.reload)
        bar.addWidget(self.reload_btn)
        lay.addLayout(bar)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        # ---- tracks tab -------------------------------------------------
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(4)
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(("Circuit / event", "Slot 1", "Slot 2", "Slot 3"))
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.setSectionResizeMode(3, QHeaderView.Interactive)
        h.setStretchLastSection(True)
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 220)
        self.tree.setColumnWidth(2, 220)
        self.tree.itemSelectionChanged.connect(self._picked)
        self.tree.itemChanged.connect(self._ticked)
        split.addWidget(self.tree)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(6)
        self.title = W.heading("No event selected", 2)
        rv.addWidget(self.title)
        self.file_label = W.muted("")
        rv.addWidget(self.file_label)

        self.slots = []
        for key, label in musiclib.SLOTS:
            box = QWidget()
            bh = QHBoxLayout(box)
            bh.setContentsMargins(0, 0, 0, 0)
            bh.setSpacing(6)
            tag = QLabel(label)
            tag.setFixedWidth(104)
            tag.setStyleSheet("color:#666;")
            bh.addWidget(tag)
            combo = QComboBox()
            combo.setEditable(False)
            combo.currentIndexChanged.connect(
                lambda _i, l=label: self._slot_changed(l))
            bh.addWidget(combo, 1)
            clear = W.button("Clear", lambda _c=False, l=label: self._clear_slot(l))
            bh.addWidget(clear)
            rv.addWidget(box)
            self.slots.append((label, combo))
        rv.addWidget(W.muted(
            "Songs come from audio/music. Saving rewrites the .nct; the engine "
            "reads it on the next start."))
        rv.addStretch(1)
        self.ticked_label = W.muted("")
        rv.addWidget(self.ticked_label)
        self.batch_ticked = W.button(
            "Batch edit the ticked events", self.batch_ticked_events,
            tip="Open the batch dialog with the ticked events as the scope")
        rv.addWidget(self.batch_ticked)
        self.save_btn = W.button("Save changes", self.save, primary=True)
        self.save_btn.setEnabled(False)
        rv.addWidget(self.save_btn)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        pv.addWidget(split, 1)
        self.tabs.addTab(page, "Tracks")

        # ---- audio tab --------------------------------------------------
        audio = QWidget()
        av = QVBoxLayout(audio)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(4)
        arow = QHBoxLayout()
        self.only_unused = QCheckBox("Only the ones no event plays")
        self.only_unused.toggled.connect(self._fill_audio)
        arow.addWidget(self.only_unused)
        arow.addStretch(1)
        self.import_btn = W.button("Import a song...", self.import_song,
                                   tip="Copy an .mp3 into audio/music")
        arow.addWidget(self.import_btn)
        self.folder_btn = W.button("Open the folder", self.open_folder,
                                   tip="Show audio/music in Explorer")
        arow.addWidget(self.folder_btn)
        av.addLayout(arow)
        # The user asked for a switch that makes the game pick three random
        # tracks per race instead of reading the playlists.  That needs code
        # inside libRealRacing3.so (the playlist read is a few instructions in
        # the middle of the track loader), which is a different job from
        # rewriting .nct files - so it is a placeholder for now, and it says so.
        self.patch_btn = W.button(
            "Patch the game for random music...", self.patch_random,
            tip="Not built yet: this one needs a change inside the game's own "
                "library, not in its data files")
        av.addWidget(self.patch_btn)
        self.audio = QTableWidget(0, 3)
        self.audio.setHorizontalHeaderLabels(("File", "Used by", "Kind"))
        self.audio.verticalHeader().setVisible(False)
        self.audio.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.audio.setSelectionBehavior(QAbstractItemView.SelectRows)
        ah = self.audio.horizontalHeader()
        ah.setSectionResizeMode(0, QHeaderView.Stretch)
        ah.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        ah.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        av.addWidget(self.audio, 1)
        self.audio_summary = W.muted("")
        av.addWidget(self.audio_summary)
        self.tabs.addTab(audio, "Audio files")

        self.summary = W.muted("No install loaded.")
        lay.addWidget(self.summary)

    # ---- loading ------------------------------------------------------
    def load(self, depot: str) -> None:
        self.depot = depot
        self.reload()

    def _scan_root(self) -> str:
        """Where to read the playlists from.

        Once the workspace has a copy of ``Tracks/data`` that copy is the newer
        one, so the list has to come from there - otherwise an edited playlist
        would still show its old songs.
        """
        if self.editor is not None and self.editor.has_music():
            return self.editor.music_root()
        return self.depot

    def _write_playlist(self, pl) -> int:
        """Write one playlist back, to the workspace when there is one."""
        if self.editor is None:
            return musiclib.save(pl)
        target = os.path.join(self.editor.for_music(), pl.name)
        n = musiclib.save(pl, target)
        self.editor.capture_music()
        return n

    def reload(self) -> None:
        if not self.depot:
            return
        self.reload_btn.setEnabled(False)
        self.status.emit("Reading playlists...")

        def work():
            root = self._scan_root()
            return musiclib.scan(root), musiclib.available_music(self.depot)

        self._task = Task(work, parent=self)
        self._task.done.connect(self._loaded)
        self._task.fail.connect(self._failed)
        self._task.start()

    def _loaded(self, payload) -> None:
        self.reload_btn.setEnabled(True)
        self.playlists, self.songs = payload
        self._dirty = {}
        self._by_name = {pl.name: pl for pl in self.playlists}
        self.save_btn.setEnabled(False)
        self._fill_songs()
        self._apply_filter()
        self._fill_audio()
        info = musiclib.summary(self.playlists)
        self.summary.setText(
            f"{info['playlists']} events on "
            f"{len(musiclib.group_by_track(self.playlists))} circuits, "
            f"{info['songs_used']} songs in use, "
            f"{len(self.songs)} files in audio/music")
        self.status.emit("Playlists loaded")

    def _failed(self, text: str) -> None:
        self.reload_btn.setEnabled(True)
        self.status.emit("Could not read the playlists")
        QMessageBox.critical(self, "Playlists", text[:2000])

    def _fill_songs(self) -> None:
        for _label, combo in self.slots:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(none)", "")
            for s in self.songs:
                combo.addItem(s, s)
            combo.blockSignals(False)

    # ---- the tree -----------------------------------------------------
    def _apply_filter(self) -> None:
        text = self.search.text().strip().lower()
        groups = musiclib.group_by_track(self.playlists)
        self.tree.blockSignals(True)
        self.tree.clear()
        self._rows = []
        shown = 0
        for key, pls in groups.items():
            title = musiclib.track_title(key)
            keep = [pl for pl in pls
                    if not text or text in title.lower()
                    or text in musiclib.playlist_title(pl).lower()
                    or text in pl.name.lower()]
            if not keep:
                continue
            parent = QTreeWidgetItem([title, "", "", ""])
            parent.setFlags(parent.flags() | Qt.ItemIsUserCheckable
                            | Qt.ItemIsAutoTristate)
            parent.setCheckState(0, Qt.Unchecked)
            parent.setData(0, Qt.UserRole, ("track", key))
            parent.setToolTip(0, f"{len(keep)} event(s) on {title}")
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            self.tree.addTopLevelItem(parent)
            for pl in keep:
                songs = self._songs_of(pl)
                cells = [musiclib.playlist_title(pl)]
                for label in musiclib.LABELS:
                    cells.append(songs.get(label, "") or "-")
                child = QTreeWidgetItem(cells)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)
                child.setData(0, Qt.UserRole, ("event", pl.name))
                child.setToolTip(0, pl.name)
                for j, label in enumerate(musiclib.LABELS):
                    value = songs.get(label, "")
                    if value:
                        child.setToolTip(1 + j, value)
                    else:
                        child.setForeground(1 + j, Qt.gray)
                parent.addChild(child)
                self._rows.append((pl, title, songs))
                shown += 1
            parent.setExpanded(shown <= 40)
        self.tree.blockSignals(False)
        self._shown = shown
        if self._rows:
            self._select_name(self._rows[0][0].name)
        else:
            self._idle()
        self._update_ticked()

    def _songs_of(self, pl) -> dict:
        """Slots as they stand *including* unsaved edits."""
        out = dict(pl.songs())
        for (name, label), value in self._dirty.items():
            if name == pl.name:
                if value:
                    out[label] = value
                else:
                    out.pop(label, None)
        return out

    def _item_of(self, name: str):
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                data = child.data(0, Qt.UserRole)
                if data and data[1] == name:
                    return child
        return None

    def _select_name(self, name: str) -> None:
        item = self._item_of(name)
        if item is None:
            return
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)
        self._show_playlist(self._by_name.get(name))

    def _picked(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        data = item.data(0, Qt.UserRole) or ("", "")
        if data[0] == "event":
            self._show_playlist(self._by_name.get(data[1]))

    def _show_playlist(self, pl) -> None:
        if pl is None:
            self._idle()
            return
        self._current = pl
        self.title.setText(f"{musiclib.track_title(musiclib.track_key(pl))}"
                           f" - {musiclib.time_of_day(pl) or 'event'}")
        self.file_label.setText(pl.name)
        songs = self._songs_of(pl)
        for label, combo in self.slots:
            combo.blockSignals(True)
            want = songs.get(label, "")
            pos = combo.findData(want) if want else 0
            combo.setCurrentIndex(pos if pos >= 0 else 0)
            combo.blockSignals(False)

    def _idle(self) -> None:
        self._current = None
        self.title.setText("No event selected")
        self.file_label.setText("")
        for _label, combo in self.slots:
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)

    # ---- ticking ------------------------------------------------------
    def _ticked(self, item, column: int) -> None:
        if column != 0:
            return
        self._update_ticked()

    def ticked(self) -> list:
        """The playlists whose box is ticked."""
        out = []
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.Checked:
                    data = child.data(0, Qt.UserRole) or ("", "")
                    pl = self._by_name.get(data[1])
                    if pl is not None:
                        out.append(pl)
        return out

    def _update_ticked(self) -> None:
        n = len(self.ticked())
        self.ticked_label.setText(
            f"{n} event(s) ticked" if n else "No events ticked")
        self.batch_ticked.setEnabled(bool(n))
        self.tick_none_btn.setEnabled(bool(n))

    def tick_all(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            parent.setCheckState(0, Qt.Checked)

    def tick_none(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            parent.setCheckState(0, Qt.Unchecked)

    # ---- editing ------------------------------------------------------
    def _slot_changed(self, label: str) -> None:
        pl = getattr(self, "_current", None)
        if pl is None:
            return
        combo = dict(self.slots)[label]
        value = combo.currentData() or ""
        self._dirty[(pl.name, label)] = value
        self._mark_dirty()
        item = self._item_of(pl.name)
        if item is not None:
            col = musiclib.LABELS.index(label) + 1
            item.setText(col, value or "-")
            item.setForeground(col, Qt.black if value else Qt.gray)
            item.setToolTip(col, value)

    def _clear_slot(self, label: str) -> None:
        combo = dict(self.slots)[label]
        combo.setCurrentIndex(0)

    def _mark_dirty(self) -> None:
        n = len(self._dirty)
        self.save_btn.setEnabled(bool(n))
        self.save_btn.setText(f"Save {n} change(s)" if n else "Save changes")

    # ---- batch --------------------------------------------------------
    def batch(self) -> None:
        """Stage a plan that touches many playlists at once."""
        if not self.playlists:
            return
        current = getattr(self, "_current", None)
        dialog = BatchDialog(self.playlists, self.songs,
                             selected=current.name if current else "",
                             parent=self)
        dialog.set_shown([row[0].name for row in getattr(self, "_rows", [])])
        dialog.set_ticked([pl.name for pl in self.ticked()])
        if dialog.exec() != BatchDialog.Accepted or not dialog.plan:
            return
        self._stage(dialog.plan, len(dialog.plan))

    def batch_ticked_events(self) -> None:
        ticked = self.ticked()
        if not ticked:
            return
        current = getattr(self, "_current", None)
        dialog = BatchDialog(ticked, self.songs,
                             selected=current.name if current else "",
                             parent=self)
        dialog.set_shown([pl.name for pl in ticked])
        dialog.set_ticked([pl.name for pl in ticked])
        dialog.prefer_ticked()
        if dialog.exec() != BatchDialog.Accepted or not dialog.plan:
            return
        self._stage(dialog.plan, len(ticked))

    def _stage(self, plan: dict, scope: int) -> None:
        edits = musiclib.plan_to_edits(plan, self.playlists)
        self._dirty.update(edits)
        self._mark_dirty()
        current = getattr(self, "_current", None)
        self._apply_filter()
        if current is not None:
            self._select_name(current.name)
        self.status.emit(
            f"Staged {len(edits)} slot change(s) across {scope} event(s) - "
            f"press Save to write them")

    def select_playlist(self, name: str) -> None:
        self._select_name(name)

    def save(self) -> None:
        if not self._dirty:
            return
        by_playlist = {}
        for (name, label), value in self._dirty.items():
            by_playlist.setdefault(name, []).append((label, value))
        written = 0
        try:
            for pl in self.playlists:
                edits = by_playlist.get(pl.name)
                if not edits:
                    continue
                for label, value in edits:
                    if value:
                        pl.set_song(label, value)
                    else:
                        pl.clear(label)
                self._write_playlist(pl)
                written += 1
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))
            self.status.emit("Saving the playlists failed")
            return
        self._dirty = {}
        self._mark_dirty()
        self.status.emit(f"Wrote {written} playlist(s)")
        self.changed.emit()
        self._apply_filter()
        self._fill_audio()

    # ---- audio files --------------------------------------------------
    def _music_dir(self) -> str:
        if not self.depot:
            return ""
        return os.path.join(self.depot, *musiclib.MUSIC_DIR.split("/"))

    def _fill_audio(self) -> None:
        if not self.depot:
            return
        used = musiclib.usage(self.playlists)
        only = self.only_unused.isChecked()
        rows = []
        for song in self.songs:
            count = used.get(song, 0)
            if only and count:
                continue
            rows.append((song, count, "Front end" if musiclib.is_menu_song(song)
                         else "Race"))
        self.audio.setRowCount(len(rows))
        for i, (song, count, kind) in enumerate(rows):
            name = QTableWidgetItem(song)
            name.setToolTip(song)
            self.audio.setItem(i, 0, name)
            cell = QTableWidgetItem(str(count) if count else "-")
            cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if not count:
                cell.setForeground(Qt.gray)
            self.audio.setItem(i, 1, cell)
            kind_cell = QTableWidgetItem(kind)
            if kind == "Front end":
                kind_cell.setForeground(Qt.darkGray)
            self.audio.setItem(i, 2, kind_cell)
        race = len(musiclib.race_songs(self.songs))
        self.audio_summary.setText(
            f"{len(self.songs)} files: {race} race track(s) and "
            f"{len(self.songs) - race} front-end cue(s).  "
            f"{len(musiclib.unused(self.playlists, self.songs))} not played by "
            f"any event.")

    def import_song(self) -> None:
        folder = self._music_dir()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Import a song",
                                "There is no audio/music folder in this install.")
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import a song", "", "Audio files (*.mp3);;All files (*)")
        if not path:
            return
        name = os.path.basename(path)
        target = os.path.join(folder, name)
        if os.path.exists(target):
            QMessageBox.information(self, "Import a song",
                                    f"{name} is already in audio/music.")
            return
        try:
            import shutil
            shutil.copyfile(path, target)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Import a song", str(exc))
            return
        self.songs = musiclib.available_music(self.depot)
        self._fill_songs()
        self._fill_audio()
        self.log_status(f"Copied {name} into audio/music")

    def patch_random(self) -> None:
        """Placeholder for the random-music patch.

        Doing this for real means editing ``libRealRacing3.so``: the loader picks
        ``Music_Track_1..3`` out of the playlist record and hands them to the
        audio engine, so a random pick has to be planted there.  The workspace
        already has ``analysis/so_patch.py`` (the ``.so`` is stored, not deflated,
        so it can be patched in place without resigning the apk) and the offsets
        for a few builds, but the code cave itself is not written.  Until it is,
        say so rather than pretending.
        """
        QMessageBox.information(
            self, "Random music",
            "This one is not built yet.\n\n"
            "Making the game choose three random tracks per race means changing "
            "libRealRacing3.so, not its data files: the loader reads "
            "Music_Track_1..3 out of the playlist record and passes them to the "
            "audio engine, so a random choice has to be planted there.\n\n"
            "What does work today: pick the songs yourself, one event at a time "
            "or in bulk. Select the events, then use Batch edit and choose "
            "\"Pick three songs at random for each playlist\" - that writes real "
            "playlists, which the game then plays as usual.")

    def open_folder(self) -> None:
        folder = self._music_dir()
        if folder and os.path.isdir(folder):
            os.startfile(folder)                 # noqa: S606 - Windows only
        else:
            QMessageBox.information(self, "Open the folder",
                                    "There is no audio/music folder here.")

    def log_status(self, text: str) -> None:
        self.status.emit(text)
