"""The career editor: every series the game has, and a way to add one.

The list on the left is the career file's 1600-odd series, grouped by the menu
they live under.  The panel on the right shows the chosen series - its tiers,
the cars each tier allows, and the events each tier holds.

Adding a series copies a template's shape (its requirement curves, its tier
layout, its event types) and then rewrites the parts that matter: the ids, the
title and description keys, the cars, the tracks and the lap counts.  That is
exactly what the game's own tool does, and the only reason a hand-made series
loads at all: the career menu indexes series by position in a table the format
documents nowhere, so inventing a shape from scratch is not an option.

Nothing is written in place.  An unpacked install is read-only, so Save writes
``events.dat.nct`` and the fourteen text files into a staging folder next to the
mods file, and Push copies them to the device.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import deploy as deploylib
from .. import depot as depotlib
from .. import series as serieslib
from . import picker
from . import widgets as W
from .worker import Task


def _pretty(key: str) -> str:
    """``STREAM_GROUP_PRO_AM`` -> ``Pro Am``; ``Career`` stays ``Career``."""
    text = key
    if text.startswith("STREAM_GROUP_"):
        text = text[len("STREAM_GROUP_"):]
    if text.startswith("SEASON_"):
        return "Season " + text[len("SEASON_"):].replace("_", " ")
    words = [w for w in text.split("_") if w]
    out = []
    for word in words:
        if word.isupper() and len(word) > 1:
            out.append(word)                 # GT3, IMSA, NASCAR, WRC, F1
        else:
            out.append(word.capitalize())
    return " ".join(out) or key


def _row_title(row: dict) -> str:
    """The name to show for a series row.

    One series in the shipped file (443, the McLaren Shadow demo) has neither a
    title key nor a name key - its head holds a zero-length string - so falling
    back to the key alone still leaves an empty label.  Showing the id is better
    than showing nothing at all.
    """
    return row["title"] or row["key"] or f"(series {row['id']})"


class SeriesPage(QWidget):
    """The career's series on the left, the chosen one on the right."""

    status = Signal(str)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.depot = ""
        self._root = ""
        #: Set once the career has been read off the device: the staging folder
        #: then becomes both the thing being edited and where Save writes.
        self._career_root = ""
        self.career = None
        self.texts = None
        self.rows = []
        self.device = None
        self.editor = None
        self._written = None
        self._cards = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter series")
        self.search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.search, 1)
        self.only_mine = QCheckBox("Only series I made")
        self.only_mine.setToolTip(
            "A series whose id is above the highest id the game shipped with")
        self.only_mine.toggled.connect(self._apply_filter)
        bar.addWidget(self.only_mine)
        self.new_btn = W.button("Add a series...", self.add_series, primary=True,
                                tip="Copy a template's shape and give it your own "
                                    "title, cars, tracks and laps")
        bar.addWidget(self.new_btn)
        self.reload_btn = W.button("Reload", self.reload)
        bar.addWidget(self.reload_btn)
        lay.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(("Series", "Id", "Tiers", "Events"))
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        th = self.tree.header()
        th.setSectionResizeMode(0, QHeaderView.Interactive)
        for i in (1, 2, 3):
            th.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.tree.setColumnWidth(0, 330)
        self.tree.itemSelectionChanged.connect(self._picked)
        split.addWidget(self.tree)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(6)
        self.title = W.heading("No series selected", 2)
        rv.addWidget(self.title)
        self.key_label = W.muted("")
        rv.addWidget(self.key_label)

        self.tabs = QTabWidget()
        self.overview = QWidget()
        ov = QVBoxLayout(self.overview)
        ov.setContentsMargins(6, 6, 6, 6)
        self.kv = W.KeyValue()
        ov.addWidget(self.kv)
        ov.addStretch(1)
        self.tabs.addTab(self.overview, "Overview")

        self.detail = QTableWidget(0, 6)
        self.detail.setHorizontalHeaderLabels(
            ("Tier", "Event", "Track", "Laps", "Fame", "Reward"))
        self.detail.verticalHeader().setVisible(False)
        self.detail.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.detail.setAlternatingRowColors(True)
        dh = self.detail.horizontalHeader()
        dh.setSectionResizeMode(2, QHeaderView.Stretch)
        for i in (0, 1, 3, 4, 5):
            dh.setSectionResizeMode(i, QHeaderView.Interactive)
        self.detail.setColumnWidth(0, 50)
        self.detail.setColumnWidth(1, 150)
        self.detail.setColumnWidth(3, 60)
        self.detail.setColumnWidth(4, 90)
        self.detail.setColumnWidth(5, 90)
        self.detail.doubleClicked.connect(self._event_double_clicked)
        self.tabs.addTab(self.detail, "Tiers and events")
        rv.addWidget(self.tabs, 1)
        self.detail_note = W.muted(
            "Double-click an event to change it. Changing one event leaves the "
            "other events and every tier id where they are.")
        self.detail_note.setWordWrap(True)
        rv.addWidget(self.detail_note)

        row = QHBoxLayout()
        self.pull_btn = W.button(
            "Read from device", self.pull_from_device,
            tip="Load the career out of the device. Use this before editing once "
                "a series has been added there - the local copy of the game does "
                "not have it, and pushing that copy would delete it.")
        self.pull_btn.setEnabled(False)
        row.addWidget(self.pull_btn)
        self.edit_btn = W.button("Change this series...", self.edit_series)
        self.del_btn = W.button("Delete...", self.delete_series)
        row.addWidget(self.edit_btn)
        row.addWidget(self.del_btn)
        self.add_tier_btn = W.button(
            "Add a tier", self.add_tier,
            tip="Copy the last tier of this series and put it on the end; every "
                "existing tier keeps its id")
        self.del_tier_btn = W.button(
            "Remove a tier", self.remove_tier,
            tip="Drop the tier of the selected row; a series must keep at least "
                "one")
        self.event_btn = W.button(
            "Change event...", self.edit_event,
            tip="Change one event in place - its track, type, laps, fame or "
                "reward - without rebuilding the tiers")
        row.addWidget(self.add_tier_btn)
        row.addWidget(self.del_tier_btn)
        row.addWidget(self.event_btn)
        row.addStretch(1)
        self.save_btn = W.button("Save to staging", self.save, primary=True,
                                 tip="Write events.dat.nct and the text files to a "
                                     "staging folder; nothing reaches the device yet")
        self.save_btn.setEnabled(False)
        row.addWidget(self.save_btn)
        self.push_btn = W.button("Push to device", self.push)
        self.push_btn.setEnabled(False)
        row.addWidget(self.push_btn)
        rv.addLayout(row)

        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 4)
        lay.addWidget(split, 1)

        self.log = W.LogPane()
        self.log.setMaximumHeight(120)
        lay.addWidget(self.log)
        self.summary = W.muted("No install loaded.")
        lay.addWidget(self.summary)

        self._idle()

    # ---- loading ------------------------------------------------------
    def load(self, depot: str) -> None:
        self.depot = depot
        # The picker wants the install root, not the depot, because the car list
        # is read from vehicles/data and the pictures from gui_assets.
        self._root = (os.path.dirname(os.path.abspath(depot))
                      if os.path.basename(os.path.abspath(depot)) == ".depot"
                      else os.path.abspath(depot))
        self._career_root = ""
        self.reload()

    def career_root(self) -> str:
        """The folder whose career file is being edited.

        Normally the install's own ``.depot``; after *Read from device* it is the
        staging folder, because that is the copy holding the device's series and
        the one Save overwrites.
        """
        return self._career_root or self.depot

    def reload(self) -> None:
        if not self.depot:
            return
        self.reload_btn.setEnabled(False)
        self.status.emit("Reading the career file...")
        # Once the career has been read off the device, the staging folder - not
        # the pristine depot - is the copy being edited, and it is also where
        # Save writes.  Reading both from the same place keeps them in step.
        source = self._career_root or self.depot

        def work():
            c = serieslib.load(source)
            t = serieslib.load_texts(source)
            return c, t, serieslib.list_series(c, t)

        self._task = Task(work, parent=self)
        self._task.done.connect(self._loaded)
        self._task.fail.connect(self._failed)
        self._task.start()

    def _loaded(self, payload) -> None:
        self.reload_btn.setEnabled(True)
        self.career, self.texts, rows = payload
        self.rows = rows
        self._written = None
        self.push_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self._apply_filter()
        info = self.career.summary()
        self.summary.setText(
            f"{info['series']} series, {info['tiers']} tiers, "
            f"{info['events']} events, {info['groups']} menu groups")
        self.log.ok(f"career loaded: {len(self.texts)} text files, "
                    f"{len(rows)} series")
        self.status.emit("Career loaded")

    def _failed(self, text: str) -> None:
        self.reload_btn.setEnabled(True)
        self.status.emit("Could not read the career file")
        QMessageBox.critical(self, "Career", text[:2000])

    # ---- table --------------------------------------------------------
    def _refresh_rows(self) -> None:
        """Rebuild the list from the career held in memory.

        Reloading would re-read the file and throw away the edit that was just
        made, so an added or deleted series refreshes the table from the object
        instead.  Only Save writes anything.
        """
        self.rows = serieslib.list_series(self.career, self.texts)
        self._apply_filter()
        info = self.career.summary()
        self.summary.setText(
            f"{info['series']} series, {info['tiers']} tiers, "
            f"{info['events']} events, {info['groups']} menu groups")

    def _apply_filter(self) -> None:
        """Rebuild the tree: super group, then menu group, then the series.

        The career menu is two levels deep - ``Career`` and ``Motorsports`` hold
        the groups, the groups hold the series - so a flat list of 1600 rows
        hides the only thing that makes the list navigable.  Series that are in
        no menu at all (the 1109 limited-time ones) go under a last node, because
        they exist in the file but the game never shows them.
        """
        text = self.search.text().strip().lower()
        mine = self._mine()
        rows = []
        for row in self.rows:
            title = _row_title(row)
            if text and (text not in title.lower()
                         and text not in row["key"].lower()
                         and text not in (row["group_path"] or "").lower()):
                continue
            if self.only_mine.isChecked() and row["id"] not in mine:
                continue
            rows.append(row)

        self.tree.setSortingEnabled(False)
        self.tree.clear()
        groups: dict = {}
        for row in rows:
            path = row["group_path"] or ""
            if path:
                top, _, rest = path.partition("/")
                leaf = rest or top
            else:
                top, leaf = "Not in any menu", "Not in any menu"
            groups.setdefault(top, {}).setdefault(leaf, []).append(row)

        for top in sorted(groups, key=lambda n: (n == "Not in any menu", n.lower())):
            leaves = groups[top]
            count = sum(len(v) for v in leaves.values())
            top_item = QTreeWidgetItem([f"{_pretty(top)}   ({count})", "", "", ""])
            font = top_item.font(0)
            font.setBold(True)
            top_item.setFont(0, font)
            top_item.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(top_item)
            for leaf in sorted(leaves, key=str.lower):
                rows_here = leaves[leaf]
                if leaf != top:
                    leaf_item = QTreeWidgetItem(
                        [f"{_pretty(leaf)}   ({len(rows_here)})", "", "", ""])
                    lf = leaf_item.font(0)
                    lf.setBold(True)
                    leaf_item.setFont(0, lf)
                    leaf_item.setFlags(Qt.ItemIsEnabled)
                    top_item.addChild(leaf_item)
                else:
                    leaf_item = top_item
                for row in sorted(rows_here, key=lambda r: _row_title(r).lower()):
                    item = QTreeWidgetItem([
                        _row_title(row),
                        str(row["id"]),
                        str(row["tiers"]),
                        str(row["events"])])
                    item.setData(0, Qt.UserRole, row["id"])
                    item.setToolTip(0, f"{row['key']}\n{row['group_path'] or '(no menu)'}")
                    for column in (1, 2, 3):
                        item.setTextAlignment(column, Qt.AlignRight | Qt.AlignVCenter)
                    if row["id"] in mine:
                        for column in range(4):
                            item.setForeground(column, Qt.darkMagenta)
                    leaf_item.addChild(item)
            top_item.setExpanded(count <= 60)

        self.tree.setSortingEnabled(True)
        self._shown = rows
        first = self._first_series_item()
        if first is not None:
            self.tree.setCurrentItem(first)

    def _first_series_item(self):
        """The first leaf that actually is a series (not a group heading)."""
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            if item is None:
                continue
            if item.data(0, Qt.UserRole) is not None:
                return item
            stack.extend(item.child(i) for i in range(item.childCount()))
        return None

    def _mine(self) -> set:
        """The series this program added, from ``rr3mods.json``."""
        if not self.depot:
            return set()
        try:
            return depotlib.series_ids(self.depot)
        except Exception:                        # noqa: BLE001
            return set()

    def _picked(self) -> None:
        item = self.tree.currentItem()
        if item is None or item.data(0, Qt.UserRole) is None:
            self._idle()
            return
        series_id = item.data(0, Qt.UserRole)
        try:
            info = serieslib.describe(self.career, series_id, self.texts)
        except serieslib.SeriesError as exc:
            self._idle()
            self.log.error(str(exc))
            return
        self._show(info)

    def _show(self, info: dict) -> None:
        self.title.setText(info["title"] or info["key"])
        self.key_label.setText(f"{info['key']}  -  {info['desc_key']}")
        self.kv.update_all({
            "Series id": info["id"],
            "Type": f"{info['type']}"
                    + ("  (limited time)" if info["is_lts"] else ""),
            "Menu group": info["group"] or "(not in any menu)",
            "Tiers": len(info["tiers"]),
            "Events": sum(len(t["events"]) for t in info["tiers"]),
            "Requirements": info["requirements"],
            "Completion reward": info["completion_reward"] or "(none)",
            "Reward id": info["reward_id"] or "(none",
            "Description": info["desc"] or "(none)",
        })
        rows = []
        for tier in info["tiers"]:
            if not tier["events"]:
                rows.append((tier["index"], "(no events)", "", "", "", "",
                             tier["cars"], 0))
                continue
            for event in tier["events"]:
                rows.append((tier["index"], event["type_name"], event["track"],
                             event["laps"], event["fame"], event["reward"],
                             tier["cars"], event["id"]))
        self.detail.setRowCount(len(rows))
        for i, (index, name, track, laps, fame, reward, _cars, event_id) in \
                enumerate(rows):
            cells = (str(index), name, track, str(laps), str(fame), str(reward))
            for j, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if j >= 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if j == 0 and event_id:
                    item.setData(Qt.UserRole, event_id)
                self.detail.setItem(i, j, item)
        self.edit_btn.setEnabled(True)
        self.del_btn.setEnabled(True)
        self.add_tier_btn.setEnabled(True)
        self.del_tier_btn.setEnabled(True)
        self.event_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.push_btn.setEnabled(bool(self._written))

    def _idle(self) -> None:
        self.title.setText("No series selected")
        self.key_label.setText("")
        self.kv.clear()
        self.detail.setRowCount(0)
        self.edit_btn.setEnabled(False)
        self.del_btn.setEnabled(False)
        self.add_tier_btn.setEnabled(False)
        self.del_tier_btn.setEnabled(False)
        self.event_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.push_btn.setEnabled(bool(self._written))

    # ---- actions ------------------------------------------------------
    def add_series(self) -> None:
        if self.career is None:
            QMessageBox.information(self, "Add a series", "Open an install first.")
            return
        dlg = SeriesDialog(self.career, self.texts, self, root=self._root)
        if dlg.exec() != QDialog.Accepted:
            return
        info = dlg.result_info()
        card_rel = ""
        if info.get("card"):
            if not info["new_group"]:
                QMessageBox.information(
                    self, "The picture",
                    "A picture only goes on a group's card, so it needs a new "
                    "group. Fill in 'New group', or clear the picture.")
                return
            try:
                made_card = serieslib.add_card(
                    self.depot, info["card"],
                    serieslib.card_name(info["title"]),
                    out_dir=serieslib.stage_dir(self.depot),
                    log=self.log.note)
            except serieslib.SeriesError as exc:
                QMessageBox.critical(self, "The picture", str(exc))
                return
            card_rel = made_card["card"]
            self._cards = made_card["files"]
        try:
            made = serieslib.build(
                self.career, self.texts, template=info["template"],
                title=info["title"], description=info["description"],
                cars=info["cars"], events=info["events"],
                group=info["group"], new_group=info["new_group"],
                group_card=card_rel)
        except serieslib.SeriesError as exc:
            QMessageBox.critical(self, "Add a series", str(exc))
            return
        for warning in made["warnings"]:
            self.log.note(warning)
        try:
            depotlib.register_series(self.depot, made["id"], title=made["title"],
                                     group=made["group"],
                                     template=made["template"])
        except Exception as exc:                 # noqa: BLE001
            self.log.error(f"could not record the new series: {exc}")
        self.log.ok(f"made series {made['id']} '{made['title']}' - "
                    f"{made['tiers']} tier(s), {made['events']} event(s) in "
                    f"{made['group']}")
        self.changed.emit()
        self._refresh_rows()

    def _picked_id(self):
        """The series id under the cursor, or ``None`` on a group heading."""
        item = self.tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.UserRole)

    def _picked_title(self) -> str:
        item = self.tree.currentItem()
        return item.text(0) if item is not None else ""

    def edit_series(self) -> None:
        series_id = self._picked_id()
        if series_id is None or self.career is None:
            return
        dlg = SeriesDialog(self.career, self.texts, self, series_id=series_id,
                           root=self._root)
        if dlg.exec() != QDialog.Accepted:
            return
        info = dlg.result_info()
        try:
            out = serieslib.retitle(
                self.career, self.texts, series_id, title=info["title"],
                description=info["description"], cars=info["cars"],
                events=info["events"] if info.get("events_changed") else None,
                group=info["group"])
        except serieslib.SeriesError as exc:
            QMessageBox.critical(self, "Change a series", str(exc))
            return
        self.log.ok(f"series {series_id}: changed {', '.join(out['changed']) or 'nothing'}")
        self.changed.emit()
        self._refresh_rows()

    def delete_series(self) -> None:
        series_id = self._picked_id()
        if series_id is None or self.career is None:
            return
        title = self._picked_title()
        ok = QMessageBox.question(
            self, "Delete a series",
            f"Take series {series_id} '{title}' out of the career?\n\n"
            "Its tiers, its events and its menu page go with it, and its text "
            "entries are removed from all fourteen text files. Nothing is written "
            "until you save.")
        if ok != QMessageBox.Yes:
            return
        try:
            serieslib.remove(self.career, self.texts, series_id)
        except serieslib.SeriesError as exc:
            QMessageBox.critical(self, "Delete a series", str(exc))
            return
        try:
            depotlib.unregister_series(self.depot, series_id)
        except Exception:                        # noqa: BLE001
            pass
        self.log.ok(f"removed series {series_id}")
        self.changed.emit()
        self._refresh_rows()

    # ---- one tier, one event ------------------------------------------
    def _picked_event(self):
        """``(series id, event id)`` of the event row under the cursor."""
        series_id = self._picked_id()
        if series_id is None:
            return None, None
        row = self.detail.currentRow()
        if row < 0:
            return series_id, None
        item = self.detail.item(row, 0)
        if item is None:
            return series_id, None
        return series_id, item.data(Qt.UserRole) or None

    def _picked_tier(self):
        """``(series id, tier id)`` of the tier holding the selected row."""
        series_id, event_id = self._picked_event()
        if series_id is None or event_id is None:
            return series_id, None
        for tier in serieslib.describe(self.career, series_id)["tiers"]:
            if any(e["id"] == event_id for e in tier["events"]):
                return series_id, tier["id"]
        return series_id, None

    def add_tier(self) -> None:
        series_id = self._picked_id()
        if series_id is None or self.career is None:
            return
        try:
            made = serieslib.add_tier(self.career, series_id)
        except serieslib.SeriesError as exc:
            QMessageBox.critical(self, "Add a tier", str(exc))
            return
        self.log.ok(f"series {series_id}: added tier {made['index']} "
                    f"(id {made['tier']}) with {made['events']} event(s) - the "
                    f"other tiers are untouched")
        self.changed.emit()
        self._refresh_rows()
        self._picked()

    def remove_tier(self) -> None:
        series_id, tier_id = self._picked_tier()
        if series_id is None:
            return
        if tier_id is None:
            QMessageBox.information(
                self, "Remove a tier",
                "Pick a row in the event table first - the tier it belongs to is "
                "the one that goes.")
            return
        ok = QMessageBox.question(
            self, "Remove a tier",
            f"Remove tier {tier_id} from series {series_id}?\n\n"
            "Its events go with it. The tiers after it are renumbered so the "
            "indices stay 0..n-1; no tier id changes. Nothing is written until "
            "you save.")
        if ok != QMessageBox.Yes:
            return
        try:
            out = serieslib.remove_tier(self.career, series_id, tier_id)
        except serieslib.SeriesError as exc:
            QMessageBox.critical(self, "Remove a tier", str(exc))
            return
        self.log.ok(f"series {series_id}: removed tier {tier_id}; "
                    f"{out['tiers']} tier(s) and {out['events']} event(s) left")
        self.changed.emit()
        self._refresh_rows()
        self._picked()

    def edit_event(self) -> None:
        series_id, event_id = self._picked_event()
        if series_id is None:
            return
        if event_id is None:
            QMessageBox.information(
                self, "Change an event",
                "Pick a row in the event table first.")
            return
        info = serieslib.describe(self.career, series_id, self.texts)
        found = next((e for tier in info["tiers"] for e in tier["events"]
                      if e["id"] == event_id), None)
        if found is None:
            QMessageBox.information(self, "Change an event",
                                    f"series {series_id} has no event {event_id}")
            return
        dlg = EventDialog(found, self._track_names(), self)
        if dlg.exec() != QDialog.Accepted:
            return
        changes = dlg.result_info()
        try:
            out = serieslib.set_event(self.career, series_id, event_id, **changes)
        except serieslib.SeriesError as exc:
            QMessageBox.critical(self, "Change an event", str(exc))
            return
        self.log.ok(f"series {series_id} event {event_id}: changed "
                    f"{', '.join(out['changed']) or 'nothing'} - "
                    f"{out['track']}, {out['laps']} lap(s)")
        self.changed.emit()
        self._refresh_rows()
        self._picked()

    def _event_double_clicked(self, _index) -> None:
        self.edit_event()

    # ---- saving -------------------------------------------------------
    def save(self) -> None:
        if self.career is None:
            return
        # Everything lands in the game folder: the Test tab is what decides
        # whether it ever reaches the device.  Without an editor the old staging
        # folder is still used so the page works alone.
        if self.editor is not None:
            target = self.editor.for_career()
        else:
            target = self._career_root or serieslib.stage_dir(self.depot)
        self.save_btn.setEnabled(False)
        self.status.emit("Writing the career file...")
        career, texts = self.career, self.texts

        def work():
            return serieslib.write(career, texts, out_dir=target,
                                   log=lambda m: None)

        self._task = Task(work, parent=self)
        self._task.done.connect(self._saved)
        self._task.fail.connect(self._save_failed)
        self._task.start()

    def _saved(self, written) -> None:
        self.save_btn.setEnabled(True)
        # Card pages are written when the series is added, not when the career
        # is saved, so they are carried across here rather than regenerated.
        written["files"] = list(getattr(self, "_cards", []) or [])
        self._written = written
        for item in written.get("texts") or ():
            self.log.ok(f"wrote {item['leaf']} ({item['bytes']:,} bytes)")
        for local, remote in written["files"]:
            self.log.ok(f"wrote {remote} ({os.path.getsize(local):,} bytes)")
        career = written.get("career") or {}
        self.log.ok(f"wrote events.dat.nct ({career.get('bytes', 0):,} bytes "
                    f"to {os.path.dirname(career.get('path', ''))})")
        self.push_btn.setEnabled(True)
        self.status.emit("Career written to the game folder - the Test tab "
                         "pushes it")
        self.changed.emit()

    def _save_failed(self, text: str) -> None:
        self.save_btn.setEnabled(True)
        self.log.error(text)
        self.status.emit("Could not write the career file")
        QMessageBox.critical(self, "Save", text[:2000])

    def attach_device(self, device) -> None:
        self.device = device
        self.pull_btn.setEnabled(True)

    def pull_from_device(self) -> None:
        """Read the career out of the device instead of the local backup.

        The local depot is a pristine copy of the game, so it does not have the
        series added on the device.  Editing it and pushing the result would
        delete them, so this is the way to edit a career that already has mods.
        """
        dev = self.device
        if dev is None:
            QMessageBox.information(self, "No device",
                                    "Connect the emulator first (Deploy tab).")
            return
        ok = QMessageBox.question(
            self, "Read from the device",
            "Read the career and the text files out of the device?\n\n"
            "This replaces what is shown here with the device's own copy, which "
            "is the only safe starting point once a series has been added there.")
        if ok != QMessageBox.Yes:
            return
        self.pull_btn.setEnabled(False)
        self.reload_btn.setEnabled(False)
        self.status.emit("Reading the career from the device...")

        def work():
            return serieslib.pull_from_device(dev, self.depot,
                                              log=lambda m: None)

        self._task = Task(work, parent=self)
        self._task.done.connect(self._pulled)
        self._task.fail.connect(self._pull_failed)
        self._task.start()

    def _pulled(self, payload) -> None:
        self.pull_btn.setEnabled(True)
        self.reload_btn.setEnabled(True)
        self.career = payload["career"]
        self.texts = payload["texts"]
        # From here on the staging folder is the working copy: it holds the
        # device's series, and Save writes back into it.
        self._career_root = payload["dir"]
        self._written = None
        self.push_btn.setEnabled(False)
        self.save_btn.setEnabled(True)
        for item in payload["files"]:
            self.log.ok(f"read {item['leaf']} ({item['bytes']:,} bytes)")
        for rel in payload["missing"]:
            self.log.note(f"not on the device: {rel}")
        self._refresh_rows()
        self.log.ok("career read from the device - this is now the copy being edited")
        self.status.emit("Career read from the device")

    def _pull_failed(self, text: str) -> None:
        self.pull_btn.setEnabled(True)
        self.reload_btn.setEnabled(True)
        self.log.error(text)
        self.status.emit("Could not read the career from the device")
        QMessageBox.critical(self, "Read", text[:2000])

    def push(self) -> None:
        if not self._written:
            QMessageBox.information(self, "Push", "Save first.")
            return
        items = serieslib.plan(self._written)
        if not items:
            QMessageBox.information(self, "Push", "Nothing to push.")
            return
        dev = self.device
        if dev is None:
            try:
                dev = deploylib.connect()
            except Exception as exc:             # noqa: BLE001
                QMessageBox.critical(self, "No device", str(exc))
                return
        ok = QMessageBox.question(
            self, "Push the career",
            f"Copy {len(items)} file(s) to the device and restart the game?\n\n"
            "The career file and the text files are large; the registry entries "
            "are merged with the device's own copy. Undo does not cover this.")
        if ok != QMessageBox.Yes:
            return
        self.push_btn.setEnabled(False)
        self.status.emit("Pushing...")

        def work():
            dev.stop()
            # Merge against the working copy, not the install: the manifests in
            # there are the ones the Deploy tab keeps in step with the device.
            root = self.editor.root if self.editor is not None else self.depot
            merged = deploylib.merge_manifests(dev, root, items)
            out = deploylib.deploy_files(dev, merged["items"])
            out["report"] = merged["report"]
            return out

        self._task = Task(work, parent=self)
        self._task.done.connect(self._pushed)
        self._task.fail.connect(self._push_failed)
        self._task.start()

    def _pushed(self, info) -> None:
        self.push_btn.setEnabled(True)
        self.log.ok(f"pushed {info.get('pushed', 0)} file(s)")
        reg = (info.get("report") or {}).get("registry") or {}
        if reg:
            self.log.note(f"registry: {reg.get('changed', 0)} rewritten, "
                          f"{reg.get('added', 0)} new, {reg.get('rows', 0)} rows")
        self.status.emit("Career pushed - start the game and look for the series")


class EventDialog(QDialog):
    """Change one event: its track, how it runs, and what it pays.

    Only the fields the user actually moved are handed back, because
    :func:`rrmod.series.set_event` treats ``-1`` and an empty track as "leave it
    alone" - that way the caller never has to know every value to change one.
    """

    #: ``QSpinBox`` is backed by a signed 32-bit int, so it cannot show a value
    #: above this.  Event numbers are unsigned, and a few in the wild sit above
    #: the signed range; those are shown as the maximum and their real value is
    #: put back untouched unless the user moves the box off it.
    WIDGET_MAX = 2**31 - 1

    def __init__(self, event: dict, tracks, parent=None):
        super().__init__(parent)
        # Not ``self.event``: QDialog has an ``event()`` method and overriding it
        # with a dict breaks every event the widget receives.
        self.source = dict(event)
        # key -> the real value, for numbers too big for the widget
        self._capped = {}
        self.setWindowTitle(f"Event {event.get('id', 0)}")
        self.resize(460, 260)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        form = QFormLayout()
        self.track = QComboBox()
        self.track.setEditable(True)
        for name in tracks or ():
            self.track.addItem(name, name)
        self.track.setCurrentText(event.get("track", ""))
        form.addRow("Track", self.track)

        self.type = QComboBox()
        for code, name in sorted(serieslib.EVENT_TYPES.items()):
            self.type.addItem(f"{name} ({code})", code)
        # A type the table does not name must still be selectable as itself.
        # Falling back to the first entry would report "type 0" as a change the
        # moment the dialog opened, and pressing OK would silently rewrite the
        # event - so the event's own type is added as a row of its own.
        want = int(event.get("type", 2))
        index = self.type.findData(want)
        if index < 0:
            self.type.addItem(f"{serieslib.type_name(want)} ({want}) - as it is", want)
            index = self.type.count() - 1
        self.type.setCurrentIndex(index)
        form.addRow("Runs as", self.type)

        self.laps = self._number("laps", event.get("laps", 1), 1)
        form.addRow("Laps", self.laps)

        self.fame = self._number("fame", event.get("fame", 0), 50)
        form.addRow("Fame", self.fame)

        self.reward = self._number("reward", event.get("reward", 0), 100)
        form.addRow("Reward (R$)", self.reward)
        lay.addLayout(form)

        self.note = W.muted(
            "Only what you change is written. The other events in this series and "
            "every tier id stay where they are.")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        lay.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _number(self, key: str, value, step: int) -> QSpinBox:
        """A spin box for one unsigned field, capped where the widget must be.

        ``QSpinBox`` holds a signed int, so a value above :data:`WIDGET_MAX`
        cannot be shown.  Showing the cap and remembering the real number means
        an untouched field is still written back exactly as it was - the
        alternative, clamping on read, would quietly lower the reward of every
        event that happened to sit above the ceiling.
        """
        box = QSpinBox()
        box.setRange(0, self.WIDGET_MAX)
        box.setSingleStep(step)
        if key == "reward":
            box.setGroupSeparatorShown(True)
        real = int(value or 0)
        if real > self.WIDGET_MAX:
            self._capped[key] = real
            box.setValue(self.WIDGET_MAX)
            box.setToolTip(
                f"This event really holds {real:,}, which is more than the box "
                f"can show. Leave it at {self.WIDGET_MAX:,} to keep it as it is.")
        else:
            box.setValue(real)
        return box

    def _value_of(self, key: str, box: QSpinBox) -> int:
        """The number in a box, or the real one when the box is still capped."""
        if key in self._capped and box.value() >= self.WIDGET_MAX:
            return self._capped[key]
        return int(box.value())

    def _accept(self) -> None:
        if not self.track.currentText().strip():
            QMessageBox.warning(self, "Event", "an event needs a track")
            return
        self.accept()

    def result_info(self) -> dict:
        """Only the fields that differ from what the event already had."""
        old = self.source
        out = {}
        track = self.track.currentText().strip()
        if track and track != old.get("track"):
            out["track"] = track
        boxes = (("type", self.type), ("laps", self.laps),
                 ("fame", self.fame), ("reward", self.reward))
        for key, widget in boxes:
            value = (int(widget.currentData()) if key == "type"
                     else self._value_of(key, widget))
            if value != int(old.get(key, 0)):
                out[key] = value
        return out


class SeriesDialog(QDialog):
    """Collect the shape of a new series, or the changes to an existing one."""

    def __init__(self, career, texts, parent=None, *, series_id: int = 0,
                 root: str = ""):
        super().__init__(parent)
        self.career = career
        self.texts = texts
        self.series_id = series_id
        self.editing = bool(series_id)
        self._root = root
        self._inv = None
        self._tracks = None
        self.setWindowTitle("Change a series" if self.editing else "Add a series")
        self.resize(760, 680)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # ---- identity ------------------------------------------------
        lay.addWidget(W.heading("1. What it is called", 2))
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("LFA Cup")
        form.addRow("Title", self.title)
        self.description = QLineEdit()
        self.description.setPlaceholderText("A test series for the Lexus LFA.")
        form.addRow("Description", self.description)
        lay.addLayout(form)

        # ---- shape ---------------------------------------------------
        self.shape_box = QWidget()
        sv = QVBoxLayout(self.shape_box)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(6)
        sv.addWidget(W.heading("2. What to copy", 2))
        sform = QFormLayout()
        self.template = QComboBox()
        self._templates = serieslib.templates(career)
        for row in self._templates[:200]:
            label = (f"{row['id']}  {row['key']}  ({row['type']}, "
                     f"{row['tiers']} tier(s), {row['events']} event(s)"
                     + (f", {row['group_key']}" if row["group_key"] else "")
                     + ")")
            self.template.addItem(label, row["id"])
        sform.addRow("Template", self.template)
        self.group = QComboBox()
        self.group.setEditable(True)
        for key in sorted(serieslib.group_keys(career)):
            self.group.addItem(key, key)
        sform.addRow("Menu group", self.group)
        self.new_group = QLineEdit()
        self.new_group.setPlaceholderText(
            "leave empty to use the group above, or name a new one to create it")
        sform.addRow("New group", self.new_group)
        sv.addLayout(sform)
        self.template_note = W.muted("")
        self.template_note.setWordWrap(True)
        sv.addWidget(self.template_note)

        # ---- the card ------------------------------------------------
        sv.addWidget(W.heading("3. The picture on the menu", 2))
        cardrow = QHBoxLayout()
        cardrow.setSpacing(6)
        self.card = QLineEdit()
        self.card.setPlaceholderText(
            "leave empty to keep the copied group's picture")
        cardrow.addWidget(self.card, 1)
        self.card_btn = W.button("Choose a picture...", self.pick_card,
                                 tip="A PNG or JPEG; it is resized to the "
                                     "size the game's own cards use")
        cardrow.addWidget(self.card_btn)
        sv.addLayout(cardrow)
        self.card_note = W.muted(
            "The picture becomes a page of its own in the menu atlas of every "
            "screen size, the same way the game's own cards are stored.")
        self.card_note.setWordWrap(True)
        sv.addWidget(self.card_note)
        self.template.currentIndexChanged.connect(self._template_changed)
        lay.addWidget(self.shape_box)

        # ---- cars ----------------------------------------------------
        lay.addWidget(W.heading("4. Which cars may enter", 2))
        carrow = QHBoxLayout()
        carrow.setSpacing(6)
        self.cars = QLineEdit()
        self.cars.setPlaceholderText("car ids separated by commas, e.g. 88,611")
        carrow.addWidget(self.cars, 1)
        self.cars_btn = W.button("Pick cars...", self.pick_cars,
                                 tip="Choose cars by manufacturer, with pictures")
        carrow.addWidget(self.cars_btn)
        lay.addLayout(carrow)
        self.cars_note = W.muted(
            "Leave empty to keep whatever the template allows. A car id is the "
            "number in front of its folder name in vehicles/data.")
        self.cars_note.setWordWrap(True)
        lay.addWidget(self.cars_note)

        # ---- events --------------------------------------------------
        lay.addWidget(W.heading("5. The events", 2))
        evrow = QHBoxLayout()
        evrow.setSpacing(6)
        self.events = QPlainTextEdit()
        self.events.setPlaceholderText(
            "One per line: Track:type:laps\n"
            "e.g.  Bathurst:2:2\n"
            "Types: " + ", ".join(f"{k}={v}" for k, v in
                                  sorted(serieslib.EVENT_TYPES.items())) +
            "\nTypes 3, 5, 6 and 8 have no name in the game itself; write the "
            "number alone if you want one.")
        self.events.setMaximumHeight(150)
        evrow.addWidget(self.events, 1)
        evcol = QVBoxLayout()
        evcol.setSpacing(4)
        self.track_btn = W.button("Add events...", self.pick_tracks,
                                  tip="Choose tracks and how each race runs")
        evcol.addWidget(self.track_btn)
        evcol.addStretch(1)
        evrow.addLayout(evcol)
        lay.addLayout(evrow)
        self.events_note = W.muted("")
        self.events_note.setWordWrap(True)
        lay.addWidget(self.events_note)

        defaults = QHBoxLayout()
        defaults.setSpacing(6)
        defaults.addWidget(QLabel("New events run as"))
        self.event_type = QComboBox()
        for code in self._event_type_choices():
            self.event_type.addItem(f"{serieslib.type_name(code)} ({code})", code)
        self.event_type.setCurrentIndex(max(0, self.event_type.findData(2)))
        defaults.addWidget(self.event_type, 1)
        defaults.addWidget(QLabel("for"))
        self.event_laps = QSpinBox()
        self.event_laps.setRange(1, 999)
        self.event_laps.setValue(2)
        defaults.addWidget(self.event_laps)
        defaults.addWidget(QLabel("laps"))
        defaults.addStretch(1)
        lay.addLayout(defaults)
        lay.addStretch(1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText(
            "Change" if self.editing else "Add")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        if self.editing:
            self._fill_from(series_id)
        self._template_changed()

    def _event_type_choices(self) -> list:
        """Named types plus whatever unnamed ones this career file uses.

        A Gauntlet series holds types 9 and 12, and neither has a name.  They
        are still offered, because a new event in that series is far more likely
        to want one of them than a Cup.
        """
        try:
            used = serieslib.types_in_use(self.career)
        except Exception:                        # noqa: BLE001
            used = []
        return sorted(set(serieslib.EVENT_TYPES) | set(used))

    def _fill_from(self, series_id: int) -> None:
        info = serieslib.describe(self.career, series_id, self.texts)
        self.title.setText(info["title"])
        self.description.setText(info["desc"])
        self.shape_box.setVisible(False)
        self.cars.setText(",".join(str(c) for c in
                                   (info["tiers"][0]["cars"] if info["tiers"] else [])))
        lines = []
        for tier in info["tiers"]:
            for event in tier["events"]:
                lines.append(f"{event['track']}:{event['type']}:{event['laps']}:"
                             f"{tier['index']}")
        self.events.setPlainText("\n".join(lines))
        self._original_events = list(lines)
        self.events_note.setText(
            f"{len(lines)} event(s) in {len(info['tiers'])} tier(s). Editing the "
            "lines rebuilds every tier from this series' own first tier, so the "
            "reward curve and the banners stay as they are. The last number on a "
            "line is the tier.")

    # -- the pickers ------------------------------------------------
    def _inventory(self):
        """The car inventory, built once, so the picker can show pictures."""
        if self._inv is not None:
            return self._inv
        root = getattr(self, "_root", "")
        if not root:
            return None
        try:
            self._inv = depotlib.scan(root)
        except Exception:                        # noqa: BLE001 - picker is optional
            self._inv = None
        return self._inv

    def pick_cars(self) -> None:
        inv = self._inventory()
        if inv is None:
            QMessageBox.information(
                self, "Pick cars",
                "The car list is not loaded, so type the ids instead.")
            return
        current = [int(x) for x in self.cars.text().replace(" ", "").split(",")
                   if x.strip().isdigit()]
        dlg = picker.CarPickerDialog(inv, self, selected=current, multiple=True)
        if dlg.exec() != QDialog.Accepted:
            return
        got = dlg.chosen()
        if got:
            self.cars.setText(",".join(str(c) for c in got))

    def pick_tracks(self) -> None:
        names = self._track_names()
        if not names:
            QMessageBox.information(
                self, "Add events",
                "The career file is not loaded, so type the lines instead.")
            return
        dlg = picker.TrackPickerDialog(self._depot(), names, self, multiple=True)
        if dlg.exec() != QDialog.Accepted:
            return
        got = dlg.chosen()
        if not got:
            return
        existing = [line for line in self.events.toPlainText().splitlines()
                    if line.strip()]
        for track in got:
            existing.append(f"{track}:{self.event_type.currentData()}:"
                            f"{self.event_laps.value()}")
        self.events.setPlainText("\n".join(existing))

    def pick_card(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Choose the menu picture", self.card.text(),
            "Pictures (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.card.setText(path)

    def _depot(self) -> str:
        root = getattr(self, "_root", "")
        return serieslib.depot_of(root) if root else ""

    def _track_names(self) -> list:
        if self._tracks is not None:
            return self._tracks
        try:
            self._tracks = serieslib.track_names(self.career)
        except Exception:                        # noqa: BLE001
            self._tracks = []
        return self._tracks

    def _template_changed(self) -> None:
        if self.editing:
            return
        template_id = self.template.currentData()
        row = next((r for r in self._templates if r["id"] == template_id), None)
        if row is None:
            self.template_note.setText("")
            return
        note = (f"Copies the shape of {row['key']}: its requirement curves, its "
                f"tier layout and its event types. Ids, keys, cars, tracks and "
                f"laps are rewritten.")
        if not row["good"]:
            note += ("  This template is not a career series, so the copy may not "
                     "show up where you expect. Prefer one from the group you are "
                     "putting it in.")
        self.template_note.setText(note)
        if row["group_key"]:
            index = self.group.findData(row["group_key"])
            if index >= 0:
                self.group.setCurrentIndex(index)

    def _accept(self) -> None:
        problems = []
        if not self.title.text().strip():
            problems.append("a series needs a title")
        if not self.editing and not self.events.toPlainText().strip():
            problems.append("a new series needs at least one event")
        if problems:
            QMessageBox.warning(self, "Series", "\n".join(problems))
            return
        try:
            self.result_info()
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.warning(self, "Series", str(exc))
            return
        self.accept()

    def result_info(self) -> dict:
        cars = [int(x) for x in self.cars.text().replace(" ", "").split(",") if x]
        lines = [line.strip() for line in self.events.toPlainText().splitlines()
                 if line.strip()]
        events = [serieslib.normalise_events([line])[0] for line in lines]
        # Only hand the events back when the user actually changed them: an
        # untouched list would rebuild every tier for nothing, and the rebuild
        # assigns new tier ids.
        edited = bool(events) and lines != list(getattr(self, "_original_events", ()))
        # The menu group only applies when adding: in edit mode the whole "what to
        # copy" box is hidden, so reading the combo would silently move the series
        # into whichever group happens to be first in the list.
        group = "" if self.editing else (self.group.currentData()
                                         or self.group.currentText().strip())
        return {
            "template": self.template.currentData() or 0,
            "title": self.title.text().strip(),
            "description": self.description.text().strip(),
            "cars": cars,
            "events": events,
            "events_changed": edited,
            "group": group,
            "new_group": "" if self.editing else self.new_group.text().strip(),
            "card": "" if self.editing else self.card.text().strip(),
        }
