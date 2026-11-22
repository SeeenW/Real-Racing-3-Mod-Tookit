"""The graphics tab: choose a quality tier, tweak individual keys, push it.

Three things happen here and they are deliberately separate:

* **pick a profile** - low / mid / high / ultra / insane.  Each one is a set of
  overrides against the file the game ships with, so ``high`` changes nothing.
* **edit individual keys** - the plist has 113 keys, 53 of them on/off.  The
  table shows every one of them with its current value, so a switch the profile
  does not cover is still reachable.
* **deploy** - the two files are written to a folder next to the mods file and
  then pushed to ``.depot/eds`` and ``.depot/feats`` on the device.  The install
  itself is usually read-only, so it is never written in place.

The editor is built out of the values the game itself uses.  The install ships
42 plists, one per device family, and all of them carry the same 113 keys, so a
key can only ever be one of the handful of values some profile picked.  On/off
keys therefore get a tick box and enumerated keys get a drop down; only the few
keys that are free-form text fall back to a text box.  That is also why "start
from another profile" works: copying ``AndroidXtraHigh`` over the live file is
just a diff against it.

The preview before Deploy is the whole point: it says exactly which keys would
change and from what to what, because a profile that turns on HDR on a phone
that cannot do it looks like a crash, not a setting.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMenu, QMessageBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import bootlog as bootloglib
from .. import deploy as deploylib
from .. import gfx as gfxlib
from . import widgets as W
from .worker import Task

#: how each profile reads in the list
PROFILE_BLURB = {
    "low": "The weakest devices: no AA, no HDR, small cubemaps",
    "mid": "Middle of the road: no AA, no HDR, 512 cubemaps",
    "high": "Exactly what the game ships - changes nothing",
    "ultra": "Everything Android was denied: 4x AA, HDR, planar reflections",
    "insane": "Ultra plus 8x AA and 2048 cubemaps - for screenshots",
}

#: column order in the key table
COLUMNS = ("Key", "Now", "After")


class GfxPage(QWidget):
    """Profiles on the left, the key table in the middle, the plan at the bottom."""

    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.depot = ""
        self.result = None
        self.device = None
        self.editor = None
        self._overrides = {}
        self._base = ""
        self._choices = {"plist": {}, "feats": {}}
        self._filling = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.header = W.muted("No install loaded.")
        lay.addWidget(self.header)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # ---- profiles --------------------------------------------------
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)
        lv.addWidget(W.heading("Profile", 3))
        self.profile_list = QComboBox()
        for name in ("low", "mid", "high", "ultra", "insane"):
            self.profile_list.addItem(f"{name} - {PROFILE_BLURB[name]}", name)
        self.profile_list.setCurrentIndex(3)
        self.profile_list.currentIndexChanged.connect(self._profile_changed)
        lv.addWidget(self.profile_list)

        self.custom = QCheckBox("Keep my per-key changes")
        self.custom.setToolTip(
            "When off, applying a profile replaces every key it names. Keys it "
            "does not name are left alone either way.")
        self.custom.setChecked(True)
        lv.addWidget(self.custom)

        lv.addWidget(W.heading("Start from", 3))
        self.base_list = QComboBox()
        self.base_list.addItem("The file on disk", "")
        self.base_list.setToolTip(
            "Copy another device family's profile over this one before applying "
            "the tier. The install ships 42 of them; they all carry the same "
            "keys, so this is a straight copy.")
        lv.addWidget(self.base_list)
        base_row = QHBoxLayout()
        self.base_btn = W.button("Use this profile", self._use_base,
                                 tip="Start the plan from the profile above")
        base_row.addWidget(self.base_btn)
        self.base_clear = W.button("Clear", self._clear_base,
                                   tip="Go back to the file on disk")
        base_row.addWidget(self.base_clear)
        lv.addLayout(base_row)

        lv.addWidget(W.heading("What this install has", 3))
        self.current = W.KeyValue()
        lv.addWidget(self.current)

        lv.addWidget(W.heading("Plan", 3))
        self.plan_box = W.KeyValue()
        lv.addWidget(self.plan_box)
        lv.addStretch(1)

        self.preview_btn = W.button("Preview changes", self.preview,
                                    tip="Show which keys would change")
        lv.addWidget(self.preview_btn)
        self.write_btn = W.button("Write the files", self.write_files,
                                  tip="Write the two files next to the mods file")
        self.write_btn.setEnabled(False)
        lv.addWidget(self.write_btn)
        self.deploy_btn = W.button("Push to device", self.push, primary=True,
                                   tip="Copy the two files into .depot and restart")
        self.deploy_btn.setEnabled(False)
        lv.addWidget(self.deploy_btn)

        # The files are a wish list until the engine says otherwise.  This is
        # how you check: start the game once, pull the log, and diff it against
        # what is on disk now.
        self.check_btn = W.button(
            "Check a boot log", self.check_log,
            tip="Pick a logcat from a start-up and see which keys the engine "
                "actually ended up with")
        self.check_btn.setEnabled(False)
        lv.addWidget(self.check_btn)
        split.addWidget(left)

        # ---- key table -------------------------------------------------
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter keys")
        self.search.textChanged.connect(self._fill_table)
        bar.addWidget(self.search, 1)
        self.only_bools = QCheckBox("Only on/off switches")
        self.only_bools.setChecked(True)
        self.only_bools.toggled.connect(self._fill_table)
        bar.addWidget(self.only_bools)
        self.only_changed = QCheckBox("Only what the plan changes")
        self.only_changed.toggled.connect(self._fill_table)
        bar.addWidget(self.only_changed)
        rv.addLayout(bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.setStretchLastSection(True)
        self.table.setColumnWidth(0, 330)
        self.table.setColumnWidth(1, 150)
        self.table.itemChanged.connect(self._cell_edited)
        rv.addWidget(self.table, 1)
        rv.addWidget(W.muted(
            "Tick a switch or pick a value to override it for this profile. "
            "Right click a row to drop the override or go back to the shipped "
            "value."))
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        lay.addWidget(split, 1)

        self.log = W.LogPane()
        self.log.setMaximumHeight(120)
        lay.addWidget(self.log)

    # ---- loading ------------------------------------------------------
    def load(self, depot: str) -> None:
        self.depot = depot
        self.result = None
        self.write_btn.setEnabled(False)
        self.deploy_btn.setEnabled(False)
        self._overrides = {}
        self._base = ""
        try:
            info = gfxlib.describe(depot)
            match = gfxlib.match_profile(depot)
        except Exception as exc:                 # noqa: BLE001
            self.header.setText(f"Could not read the graphics files: {exc}")
            self.current.clear()
            self.plan_box.clear()
            self.table.setRowCount(0)
            return
        self._load_choices()
        rows = {}
        for kind in ("plist", "feats"):
            item = info.get(kind)
            if not item:
                rows[f"{kind}"] = "missing"
                continue
            rows[f"{kind}"] = (f"{item['keys']} keys, {item['bools']} switches, "
                               f"{item['bytes']} bytes")
        if info.get("plist"):
            rows["Identifier"] = info["plist"].get("identifier")
            rows["AA level"] = info["plist"].get("aa")
            rows["Mipmap bias"] = info["plist"].get("mipmap_bias")
            rows["Renderer"] = info["plist"].get("renderer")
        rows["Looks like"] = match or "unknown"
        self.current.update_all(rows)
        self.header.setText(
            "The engine reads .depot/eds/AndroidHigh.plist and "
            ".depot/feats/AndroidHigh.feats at start-up. apk/res holds the "
            "untouched source copies and is ignored.")
        self._fill_table()
        self.preview()
        self.check_btn.setEnabled(True)
        self.status.emit("Graphics profile loaded")

    def _load_choices(self) -> None:
        """Gather every value the shipped profiles use, for the drop downs."""
        self._choices = {"plist": {}, "feats": {}}
        try:
            self._choices["plist"] = gfxlib.choices(self.depot, "plist")
            self._choices["feats"] = gfxlib.choices(self.depot, "feats")
        except Exception:                        # noqa: BLE001
            pass
        self.base_list.blockSignals(True)
        self.base_list.clear()
        self.base_list.addItem("The file on disk", "")
        try:
            names = gfxlib.factory_profiles(self.depot)
        except Exception:                        # noqa: BLE001
            names = []
        for name in names:
            self.base_list.addItem(name, name)
        self.base_list.blockSignals(False)
        if self._base:
            index = self.base_list.findData(self._base)
            if index >= 0:
                self.base_list.setCurrentIndex(index)
        self.base_btn.setEnabled(bool(names))

    # ---- base profile -------------------------------------------------
    def _use_base(self) -> None:
        name = self.base_list.currentData() or ""
        if not name:
            self._clear_base()
            return
        self._base = name
        self.result = None
        self.write_btn.setEnabled(False)
        self.deploy_btn.setEnabled(False)
        self.preview()
        self.log.note(f"starting from eds/{name}.plist")

    def _clear_base(self) -> None:
        if not self._base:
            return
        self._base = ""
        self.base_list.setCurrentIndex(0)
        self.result = None
        self.preview()

    # ---- profiles -----------------------------------------------------
    def profile(self) -> str:
        return self.profile_list.currentData()

    def _profile_changed(self) -> None:
        if not self.custom.isChecked():
            self._overrides = {}
        self.result = None
        self.write_btn.setEnabled(False)
        self.deploy_btn.setEnabled(False)
        self.plan_box.update_all({"Profile": self.profile()})
        self._fill_table()
        self.preview()

    # ---- plan ---------------------------------------------------------
    def preview(self) -> None:
        if not self.depot:
            return
        custom = {}
        custom_feats = {}
        if self.custom.isChecked():
            for key, value in self._overrides.items():
                kind = "feats" if self._is_feat(key) else "plist"
                (custom_feats if kind == "feats" else custom)[key] = value
        try:
            result = gfxlib.plan(self.depot, self.profile(),
                                 custom=custom, custom_feats=custom_feats,
                                 base=self._base)
        except Exception as exc:                 # noqa: BLE001
            self.plan_box.update_all({"Error": str(exc)})
            self.write_btn.setEnabled(False)
            self.deploy_btn.setEnabled(False)
            return
        self.result = result
        self.write_btn.setEnabled(result["changes"] > 0)
        self.deploy_btn.setEnabled(result["changes"] > 0)
        self.plan_box.update_all({
            "Starting from": (f"eds/{self._base}.plist" if self._base
                              else "the file on disk"),
            "plist changes": len(result["plist"]),
            "feats changes": len(result["feats"]),
            "Overrides": len(self._overrides),
            "Warnings": "; ".join(result["warnings"]) or "",
        })
        self.log.note(
            f"{self.profile()}: {len(result['plist'])} plist key(s) and "
            f"{len(result['feats'])} shader switch(es) would change")
        self._fill_table()

    def _is_feat(self, key: str) -> bool:
        try:
            plist, feats = gfxlib.read_pair(self.depot)
        except Exception:                        # noqa: BLE001
            return False
        return feats is not None and key in feats.values

    def _after(self, key: str):
        if not self.result:
            return None
        for k, _before, after in self.result["plist"]:
            if k == key:
                return after
        for k, _before, after in self.result["feats"]:
            if k == key:
                return after
        return None

    # ---- the table ----------------------------------------------------
    def _fill_table(self) -> None:
        if not self.depot:
            return
        try:
            plist, feats = gfxlib.read_pair(self.depot)
        except Exception:                        # noqa: BLE001
            return
        text = self.search.text().strip().lower()
        bools = self.only_bools.isChecked()
        changed = self.only_changed.isChecked()
        rows = []
        for obj, kind in ((plist, "plist"), (feats, "feats")):
            if obj is None:
                continue
            for key, value in sorted(obj.values.items()):
                if bools and not isinstance(value, bool):
                    continue
                if text and text not in key.lower():
                    continue
                after = self._after(key)
                if changed and after is None:
                    continue
                rows.append((key, kind, value, after))
        self._filling = True
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for i, (key, kind, value, after) in enumerate(rows):
            name = QTableWidgetItem(key)
            name.setToolTip(f"{kind} key")
            name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if after is not None:
                name.setForeground(Qt.darkYellow)
            self.table.setItem(i, 0, name)

            now = QTableWidgetItem(_show(value))
            now.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(i, 1, now)

            self.table.setCellWidget(
                i, 2, self._editor(key, kind, value,
                                   after if after is not None else value))
        self.table.blockSignals(False)
        self._filling = False

    def _editor(self, key: str, kind: str, value, current):
        """One cell widget: a tick box, a drop down, or a text box."""
        if isinstance(value, bool):
            box = QCheckBox()
            box.setChecked(bool(current))
            box.setStyleSheet("margin-left: 6px;")
            box.setToolTip("tick to turn this on")
            box.toggled.connect(
                lambda on, k=key: self._set_override(k, bool(on)))
            return box
        options = self._choices.get(kind, {}).get(key) or []
        if options:
            combo = QComboBox()
            for option in options:
                combo.addItem(_show(option), option)
            if current not in options:
                combo.addItem(_show(current), current)
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.activated.connect(
                lambda _i, k=key, c=combo: self._set_override(k, c.currentData()))
            return combo
        # no profile ever used another value here, so there is nothing to offer:
        # fall back to a text box and coerce on Enter / focus out
        edit = QLineEdit(_show(current))
        if current != value:
            edit.setStyleSheet("color: #7bbf5a;")
        edit.editingFinished.connect(
            lambda k=key, e=edit: self._set_text(k, e.text()))
        return edit

    def _set_text(self, key: str, text: str) -> None:
        if self._filling or not key:
            return
        old = self._shipped(key)
        try:
            value = gfxlib.coerce(old, text)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.warning(self, "Not a value", f"{key}: {exc}")
            self._fill_table()
            return
        if value == old:
            self._overrides.pop(key, None)
            self.preview()
            return
        self._set_override(key, value)

    def _set_override(self, key: str, value) -> None:
        if self._filling or not key:
            return
        if value is None:
            return
        self._overrides[key] = value
        self.custom.setChecked(True)
        self.preview()

    def _cell_edited(self, item) -> None:
        """Only free-text cells land here; the rest are cell widgets."""
        if self._filling or item.column() != 2:
            return
        key = item.data(Qt.UserRole)
        if not key:
            return
        old = self._shipped(key)
        try:
            self._overrides[key] = gfxlib.coerce(old, item.text())
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.warning(self, "Not a value", f"{key}: {exc}")
            self._fill_table()
            return
        self.custom.setChecked(True)
        self.preview()

    def _shipped(self, key: str):
        try:
            plist, feats = gfxlib.read_pair(self.depot)
        except Exception:                        # noqa: BLE001
            return None
        for obj in (plist, feats):
            if obj is not None and key in obj.values:
                return obj.values[key]
        return None

    def _table_menu(self, pos) -> None:
        item = self.table.itemAt(pos)
        if item is None:
            return
        key = self.table.item(item.row(), 0).text()
        menu = QMenu(self)
        menu.addAction("Drop my override",
                       lambda: self._drop_override(key))
        menu.addAction("Go back to the shipped value",
                       lambda: self._set_override(key, self._shipped(key)))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _drop_override(self, key: str) -> None:
        if key in self._overrides:
            self._overrides.pop(key)
            self.preview()

    # ---- writing ------------------------------------------------------
    def write_files(self) -> None:
        if not self.result or not self.depot:
            return
        try:
            if self.editor is not None:
                # staged: written into the working copy, pushed from Deploy
                out_dir = self.editor.for_gfx()
                written = gfxlib.apply(self.depot, self.result, out_dir=out_dir)
                self.editor.capture("")
            else:
                written = gfxlib.apply(self.depot, self.result)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Write failed", str(exc))
            return
        for kind, item in written.items():
            self.log.ok(f"wrote {item['rel']} ({item['bytes']} bytes) -> "
                        f"{item['path']}")
        self.status.emit(f"Wrote {len(written)} graphics file(s)")
        self._written = written

    def attach_device(self, device) -> None:
        """The deploy page hands us a connected device."""
        self.device = device

    def push(self) -> None:
        if not self.depot:
            return
        if not getattr(self, "_written", None):
            self.write_files()
        written = getattr(self, "_written", None)
        if not written:
            return
        dev = self.device
        if dev is None:
            try:
                dev = deploylib.connect()
            except Exception as exc:             # noqa: BLE001
                QMessageBox.critical(self, "No device", str(exc))
                return
        items = deploylib.plan_gfx(written)
        if not items:
            QMessageBox.information(self, "Push", "Nothing to push.")
            return
        ok = QMessageBox.question(
            self, "Push the graphics profile",
            f"Copy {len(items)} file(s) into .depot on the device and restart "
            "the game?\n\n"
            "The registry already lists both files, so only their hashes change. "
            "Keep a note of the profile you had: Undo does not cover this.")
        if ok != QMessageBox.Yes:
            return

        def work():
            # the manifests are merged against the working copy, not the install:
            # the install may be read-only and its copy is not what is being pushed
            root = self.editor.root if self.editor is not None else self.depot
            merged = deploylib.merge_manifests(dev, root, items)
            report = deploylib.deploy_files(dev, merged["items"])
            return report, merged["report"]

        self.status.emit("Pushing...")
        self._task = Task(work, parent=self)
        self._task.done.connect(self._pushed)
        self._task.fail.connect(
            lambda t: QMessageBox.critical(self, "Push failed", t[:2000]))
        self._task.start()

    def _pushed(self, payload) -> None:
        report, merged = payload
        self.log.ok(f"pushed {report.get('files', 0)} file(s)")
        reg = merged.get("registry") or {}
        if reg:
            self.log.note(f"registry: {reg.get('changed', 0)} rewritten, "
                          f"{reg.get('added', 0)} new, {reg.get('rows', 0)} rows")
        self.status.emit("Graphics profile pushed - restart the game to see it")

    # ---- did it take? ---------------------------------------------------
    def _log_folder(self) -> str:
        """Where to start the picker: the archive of logs if there is one."""
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        for guess in (os.path.join(here, "re", "logs"), os.path.join(here, "logs")):
            if os.path.isdir(guess):
                return guess
        return os.path.expanduser("~")

    def check_log(self) -> None:
        """Compare a boot log with the profile that is on disk right now."""
        if not self.depot:
            return
        path, _flt = QFileDialog.getOpenFileName(
            self, "Pick a boot log", self._log_folder(),
            "Logs (*.log *.txt);;Everything (*)")
        if not path:
            return
        try:
            plist = gfxlib.read_pair(self.depot)[0]
            result = bootloglib.from_file(plist.path, path)
        except Exception as exc:                 # noqa: BLE001
            self.log.error(str(exc)[:400])
            QMessageBox.warning(self, "Could not read that log",
                                str(exc)[:1500])
            return
        self.log.ok(bootloglib.summarise(result))
        for note in dict.fromkeys(result["notes"]):
            self.log.note(note)
        dlg = BootLogDialog(result, self)
        dlg.exec()


def _show(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _short(value, limit: int = 48) -> str:
    """One line, short enough to keep the table's columns on screen.

    Plist values are not all short: the LOD mapping keys hold several lines of
    "name\\nLOD, distance" pairs, which would otherwise stretch their column
    until the verdict column scrolled out of view.  The full value goes in the
    tooltip.
    """
    text = " ".join(_show(value).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


#: how each verdict reads in the dialog
STATE_TEXT = {
    bootloglib.TOOK: "took",
    bootloglib.DIFFERS: "engine's own value",
    bootloglib.ABSENT: "not in the dump",
}


class BootLogDialog(QDialog):
    """What the engine resolved, key by key, against the file on disk.

    A dialog rather than a panel because it is a one-shot answer to a one-shot
    question, and because the interesting part - the handful of keys that did
    not take - is worth reading at a glance without hunting for it in a table
    of 113 rows.  Mismatches are listed first for that reason.
    """

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Did the profile take effect?")
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # Both of these are built from the report, so they are data: translating
        # them would put "111 of 113 keys took" in the table as a new string
        # every time the count changed.
        summary = QLabel(bootloglib.summarise(result))
        summary.setProperty("rr3_skip_translate", True)
        lay.addWidget(summary)
        where = " · ".join(x for x in (
            result.get("platform") or "",
            f"{result.get('keys', 0)} keys in the dump") if x)
        if where:
            line = W.muted(where)
            line.setProperty("rr3_skip_translate", True)
            lay.addWidget(line)

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(("Key", "Wanted", "Engine", "State"))
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
        head = table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        head.setSectionResizeMode(1, QHeaderView.Interactive)
        head.setSectionResizeMode(2, QHeaderView.Interactive)
        head.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.setColumnWidth(1, 170)
        table.setColumnWidth(2, 170)
        rows = result["rows"]
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            wanted = _show(row["wanted"])
            got = _show(row["got"])
            cells = (_show(row["key"]), _short(wanted), _short(got),
                     STATE_TEXT.get(row["state"], row["state"]))
            tips = (row["key"], wanted, got, "")
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if tips[column]:
                    item.setToolTip(tips[column])
                if row["state"] != bootloglib.TOOK:
                    item.setForeground(Qt.darkYellow if row["state"] ==
                                       bootloglib.DIFFERS else Qt.gray)
                table.setItem(index, column, item)
        lay.addWidget(table, 1)

        for note in dict.fromkeys(result["notes"]):
            label = W.muted(note)
            label.setWordWrap(True)
            lay.addWidget(label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)

