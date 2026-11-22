"""The Test area: connect a device, compare it with the install, push the diffs.

Edits are written straight into the game folder now, so this page has a
different job from the one it had when a working copy existed: it *checks* what
is different between the install on disk and the copy the device is running, and
pushes only that.  Two scopes, because they answer two different questions - one
car (selected on the Cars page) or everything this program has edited.

Nothing in this module runs at import time: adb is located on the first press of
a button, so the window opens on a machine with no emulator running.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import backup as backuplib
from .. import deploy as deploylib
from . import settings as settingslib
from . import widgets as W
from .worker import Task


class DeployPage(QWidget):
    """Test area: connect a device, compare it with the install, push the diffs.

    Edits are written straight into the game folder now, so this page has a
    different job from the old one: it *checks* what is different between the
    install on disk and the copy the device is running, and pushes only that.
    """

    status = Signal(str)
    #: emitted with a live :class:`rrmod.deploy.Device` so other tabs can push
    device_ready = Signal(object)
    #: emitted after the list was cleared
    discarded = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.inv = None
        self.device = None
        self.car = ""
        self._plan = []
        self._rows = []
        self._sent = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        top = QHBoxLayout()
        self.conn_label = QLabel("Not connected")
        top.addWidget(self.conn_label, 1)
        self.adb_btn = W.button("Find device", self._connect)
        top.addWidget(self.adb_btn)
        lay.addLayout(top)

        # adb has to be told where to look: the serial is not always the
        # 127.0.0.1:16384 the MuMu install notes mention (this one answers as
        # emulator-5554), and the server port is a third thing again.  Both are
        # remembered, so it is typed once.
        addr = QHBoxLayout()
        addr.setSpacing(6)
        addr.addWidget(QLabel("Device"))
        self.address = QLineEdit()
        self.address.setPlaceholderText(
            "leave empty to look for one, or type host:port / emulator-5554")
        self.address.setText(settingslib.get("device_address", "") or "")
        addr.addWidget(self.address, 1)
        addr.addWidget(QLabel("adb port"))
        self.server_port = QLineEdit()
        self.server_port.setFixedWidth(70)
        self.server_port.setPlaceholderText("auto")
        self.server_port.setText(settingslib.get("adb_port", "") or "")
        addr.addWidget(self.server_port)
        self.list_btn = W.button("List devices", self._list_devices,
                                 tip="Ask adb what it can see, and fill the box above")
        addr.addWidget(self.list_btn)
        lay.addLayout(addr)

        self.devices_label = W.muted("")
        self.devices_label.setWordWrap(True)
        lay.addWidget(self.devices_label)

        bar = QHBoxLayout()
        self.car_label = QLabel("everything this install has edited")
        bar.addWidget(QLabel("Target"))
        bar.addWidget(self.car_label, 1)
        # Which of the differences to send.  Every row is ticked when the list is
        # built, so the ordinary case - push everything - stays one press.
        self.all_btn = W.button("All", lambda: self._tick_all(True),
                                tip="Tick every difference")
        self.all_btn.setEnabled(False)
        bar.addWidget(self.all_btn)
        self.none_btn = W.button("None", lambda: self._tick_all(False),
                                 tip="Untick every difference")
        self.none_btn.setEnabled(False)
        bar.addWidget(self.none_btn)
        self.prepare_btn = W.button(
            "Scan for differences", self.prepare,
            tip="Compare the files this install has changed against the device "
                "and list the ones that are not there or do not match")
        bar.addWidget(self.prepare_btn)
        self.push_btn = W.button("Push differences", self.push, primary=True)
        self.push_btn.setEnabled(False)
        bar.addWidget(self.push_btn)
        self.discard_btn = W.button(
            "Clear the list", self.discard,
            tip="Empty this list. Nothing on disk or on the device is touched")
        self.discard_btn.setEnabled(False)
        bar.addWidget(self.discard_btn)
        self.check_btn = W.button("Check log", self.check_log)
        self.check_btn.setEnabled(False)
        bar.addWidget(self.check_btn)
        lay.addLayout(bar)

        # What is on disk is live: the game reads the install directly.  The
        # device is a separate copy, which is why this page compares the two.
        self.where_label = W.muted("")
        self.where_label.setWordWrap(True)
        lay.addWidget(self.where_label)

        # The asset lists are not files you stage - they are rewritten during
        # Push, merged onto the device's own copies.  Without saying so, a plan
        # of three files looks like the lists were forgotten.
        self.follow_label = W.muted("")
        self.follow_label.setWordWrap(True)
        lay.addWidget(self.follow_label)

        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ("", "Local file", "Device path", "Status", "Size"))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 28)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        head.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._ticked)
        split.addWidget(self.table)
        self.log = W.LogPane()
        split.addWidget(self.log)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)

        self.warn = W.muted(
            "Pushing replaces files inside the game's data folder on the device. "
            "The asset lists are merged onto the device's own copies and made read "
            "only again afterwards, as the engine expects.")
        lay.addWidget(self.warn)

        # Taking a push back needs the device's own bytes, and a full copy of the
        # install is 10.43 GB while a car mod is a few dozen files - so only the
        # files a push is about to overwrite are kept, one folder per push.
        back = QHBoxLayout()
        self.backup_label = W.muted("")
        self.backup_label.setWordWrap(True)
        back.addWidget(self.backup_label, 1)
        self.undo_push_btn = W.button(
            "Take the last push back", self.undo_push,
            tip="Put the device's own files back from the copy kept before the "
                "most recent push")
        self.undo_push_btn.setEnabled(False)
        back.addWidget(self.undo_push_btn)
        lay.addLayout(back)

    # ---- wiring -------------------------------------------------------
    def attach(self, inv) -> None:
        """Point the page at an install (the game folder edits go into)."""
        self.inv = inv
        # A device was connected in an earlier run: hand the endpoint back to the
        # deploy layer so the other tabs do not have to rediscover it.
        serial = settingslib.get("device_address", "") or ""
        port = settingslib.get("adb_port", "") or ""
        if serial or port:
            deploylib.set_default_endpoint(serial, port)
        self.refresh()
        self._refresh_backup()

    #: Kept so an older caller still works.
    def load(self, inv) -> None:
        self.attach(inv)

    def set_car(self, name: str) -> None:
        """Remember which car the Cars page has selected.

        A car is a hundred files and comparing all of them is quick; comparing
        the whole install is not.  With a car selected the scan looks at that car
        (which is what "did my edit arrive" means in practice); with none it
        looks at the files this program has edited, taken from the undo history.
        """
        self.car = str(name or "")
        self.car_label.setText(
            f"{self.car} (all of its files)" if self.car
            else "everything this install has edited")

    def refresh(self) -> None:
        """Say where edits land and what the scan will look at."""
        if self.inv is None:
            return
        edited = len(self._edited_rels())
        self.where_label.setText(
            f"Edits are written straight into {self.inv.root}. "
            f"{edited} file(s) have been edited here (undo history); "
            "press Scan for differences to compare them with the device.")
        self.discard_btn.setEnabled(bool(self._plan))

    def _edited_rels(self) -> list:
        """Every install-relative file the undo history has a copy of.

        The history copies a file aside *before* it is written, so its folder is
        an exact list of what this program has touched - which is a far better
        candidate list than walking a 10 GB install.
        """
        from .. import history as historylib

        if self.inv is None:
            return []
        out = []
        seen = set()
        try:
            for stamp in historylib.stamps(self.inv.root):
                for rel in historylib.files(self.inv.root, stamp):
                    if rel not in seen:
                        seen.add(rel)
                        out.append(rel)
        except Exception:                        # noqa: BLE001
            return []
        return out

    def discard(self) -> None:
        self._plan = []
        self._rows = []
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        self.push_btn.setEnabled(False)
        self.all_btn.setEnabled(False)
        self.none_btn.setEnabled(False)
        self.log.note("list cleared - nothing was changed on disk")
        self.discarded.emit()

    def _endpoint(self) -> tuple:
        """``(serial, server_port)`` from the two boxes, remembering them."""
        serial, port = deploylib.parse_endpoint(self.address.text())
        port = port or self.server_port.text().strip()
        settingslib.set("device_address", serial)
        settingslib.set("adb_port", port)
        deploylib.set_default_endpoint(serial, port)
        return (serial, port)

    def _list_devices(self) -> None:
        self.list_btn.setEnabled(False)
        self.status.emit("Asking adb what it can see...")
        adb = settingslib.adb()
        port = self.server_port.text().strip()

        def work():
            return deploylib.devices(adb, port)

        self._task = Task(work, parent=self)
        self._task.done.connect(self._listed)
        self._task.fail.connect(lambda t: (self.list_btn.setEnabled(True),
                                           self.log.error(t)))
        self._task.start()

    def _listed(self, found) -> None:
        self.list_btn.setEnabled(True)
        self._remember_port()
        if not found:
            self.devices_label.setText(
                "adb sees no devices. Start the emulator, then try again - or "
                "type its address above (adb connect host:port).")
            self.log.note("adb devices: nothing")
            return
        ready = [serial for serial, state in found if state == "device"]
        self.devices_label.setText(
            "adb sees: " + ", ".join(f"{s} ({st})" for s, st in found))
        if ready and not self.address.text().strip():
            self.address.setText(ready[0])
        self.log.note("adb devices: " + ", ".join(f"{s} {st}" for s, st in found))

    def _remember_port(self) -> None:
        """Store the adb server port that actually answered, not the one asked for.

        A port in the box that does not answer (5555 is the emulator's own adbd
        port, not the server's) used to be saved straight back, so the setting
        stayed wrong for ever and every call paid the timeout again.
        ``deploy.effective_port`` knows what really worked; when it fell back to
        the default it answers with an empty string, which is the honest value
        for "whatever the environment says".
        """
        real = deploylib.effective_port(self.server_port.text().strip())
        if real != self.server_port.text().strip():
            self.server_port.setText(real)
            settingslib.set("adb_port", real)

    def _connect(self) -> None:
        self.status.emit("Looking for a device...")
        self.adb_btn.setEnabled(False)
        serial, port = self._endpoint()

        def work():
            return deploylib.probe(settingslib.adb(), serial=serial, port=port)

        self._task = Task(work, parent=self)
        self._task.done.connect(self._connected)
        self._task.fail.connect(lambda t: (self.adb_btn.setEnabled(True),
                                           QMessageBox.critical(self, "adb", t[:2000])))
        self._task.start()

    def _connected(self, info) -> None:
        self.adb_btn.setEnabled(True)
        if not info.get("ok"):
            self.device = None
            self.conn_label.setText("Not connected")
            self.log.error(info.get("error", "no device"))
            found = info.get("devices") or []
            if found:
                self.devices_label.setText(
                    "adb sees: " + ", ".join(f"{s} ({st})" for s, st in found))
            self.status.emit("No device")
            return
        self.conn_label.setText(
            f"Connected: {info['model']} at {info['serial']} "
            f"(port {info['port'] or 'default'}, root {info['root']})")
        self.log.ok(f"adb {info['adb']}")
        self.address.setText(info["serial"])
        settingslib.set("device_address", info["serial"])
        settingslib.set("adb_port", info["port"])
        if self.server_port.text().strip() != (info["port"] or ""):
            self.server_port.setText(info["port"] or "")
        found = info.get("devices") or []
        if found:
            self.devices_label.setText(
                "adb sees: " + ", ".join(f"{s} ({st})" for s, st in found))
        self.device = deploylib.Device(info["adb"], info["serial"], info["port"])
        # Remember it for every later push: the other tabs call connect() with no
        # arguments, and without this they would go back to guessing.
        deploylib.set_default_endpoint(info["serial"], info["port"])
        self._refresh_backup()
        self.device_ready.emit(self.device)
        self._ticked()
        self.check_btn.setEnabled(True)
        self.status.emit("Device connected")

    # ---- prepare ------------------------------------------------------
    def prepare(self) -> None:
        """Compare the install against the device and list what differs.

        Two scopes, because they answer two different questions:

        * a car selected on the Cars page - every file of that car (and its
          livery table and spec), which is "did the edit I just made arrive";
        * no car - the files this program has edited, from the undo history,
          which is "what have I changed since the last push".

        Comparing the whole 10 GB install is neither: it takes minutes and the
        answer is almost always the same list.
        """
        if self.inv is None:
            return
        if self.device is None:
            QMessageBox.information(
                self, "Test area",
                "Connect a device first - the point of this page is comparing the "
                "game folder with what the device is running.")
            return
        car = self.car
        rels = [] if car else self._edited_rels()
        if not car and not rels:
            QMessageBox.information(
                self, "Test area",
                "Nothing has been edited yet, so there is nothing to compare.\n\n"
                "Select a car on the Cars page to compare that car's files instead.")
            return
        self.prepare_btn.setEnabled(False)
        self.log.note(f"comparing {car or f'{len(rels)} edited file(s)'} with the device...")
        self.status.emit("Comparing...")
        dev = self.device
        root = self.inv.root

        def work():
            if car:
                return deploylib.compare_car(dev, root, car, log=lambda m: None)
            return deploylib.compare_files(dev, root, rels, log=lambda m: None)

        self._task = Task(work, parent=self)
        self._task.done.connect(self._scanned)
        self._task.fail.connect(self._scan_failed)
        self._task.start()

    def _scan_failed(self, text: str) -> None:
        self.prepare_btn.setEnabled(True)
        self.log.error(text[:2000])
        self.status.emit("Compare failed")

    def _scanned(self, rows) -> None:
        """Fill the table with the differences the compare found."""
        self.prepare_btn.setEnabled(True)
        self._rows = list(rows or [])
        diff = [r for r in self._rows if r.get("state") != "same"]
        same = len(self._rows) - len(diff)
        self._plan = [(r["local"], r["rel"], False) for r in diff]
        follows = deploylib.following_manifests(self._plan, root=self.inv.root)
        if follows:
            names = ", ".join(os.path.basename(f) for f in follows)
            self.follow_label.setText(
                f"Push also rewrites {len(follows)} asset list(s), merged onto the "
                f"device's own copies: {names}.")
        else:
            self.follow_label.setText("")
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._plan))
        for i, row in enumerate(diff):
            box = QTableWidgetItem()
            box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            box.setCheckState(Qt.Checked)
            self.table.setItem(i, 0, box)
            item = QTableWidgetItem(row["rel"])
            item.setToolTip(row["local"])
            self.table.setItem(i, 1, item)
            self.table.setItem(i, 2, QTableWidgetItem(row["rel"]))
            state = QTableWidgetItem(row["state"])
            state.setToolTip(
                "the device has no such file - pushing adds it"
                if row["state"] == "missing" else
                "the bytes differ - pushing replaces the device's copy")
            self.table.setItem(i, 3, state)
            size = QTableWidgetItem(f"{row.get('size', 0) / 1024:.0f} KB")
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 4, size)
        self.table.blockSignals(False)
        self.all_btn.setEnabled(bool(diff))
        self.none_btn.setEnabled(bool(diff))
        self.log.note(f"{len(diff)} difference(s), {same} file(s) already match")
        self._ticked()
        self.status.emit(f"{len(diff)} difference(s)")

    def _checked_rows(self) -> list:
        """``[(local, remote)]`` for the rows the user left ticked."""
        out = []
        for i in range(self.table.rowCount()):
            box = self.table.item(i, 0)
            if box is None or box.checkState() != Qt.Checked:
                continue
            if i >= len(self._plan):
                continue
            local, remote, _lock = self._plan[i]
            out.append((local, remote))
        return out

    def _ticked(self) -> None:
        """Enable Push only when at least one row is ticked."""
        n = len(self._checked_rows())
        self.push_btn.setEnabled(self.device is not None and n > 0)
        if self._plan:
            self.status.emit(f"{n} of {len(self._plan)} file(s) ticked")

    def _tick_all(self, on: bool) -> None:
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            box = self.table.item(i, 0)
            if box is not None:
                box.setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.table.blockSignals(False)
        self._ticked()

    # ---- push ---------------------------------------------------------
    def push(self) -> None:
        chosen = self._checked_rows()
        if not chosen or self.device is None:
            return
        ok = QMessageBox.question(
            self, "Push",
            f"Push {len(chosen)} file(s) to the device?\n\n"
            "The asset lists are merged with the device's own copies rather than "
            "overwritten, so cars installed by other tools survive. The game must "
            "be closed.")
        if ok != QMessageBox.Yes:
            return
        self.push_btn.setEnabled(False)
        items = [(local, remote, False) for local, remote in chosen]
        self._sent = [remote for _local, remote in chosen]
        dev = self.device
        # The merge reads the install's own manifests, rewrites the rows for what
        # is being pushed, and keeps every row the device knows that the install
        # does not.  Its output is staged next to the undo backups rather than in
        # the game folder.
        from .. import history as historylib

        root = self.inv.root
        dest = os.path.join(historylib.dir_for(root), "_merge")

        def work():
            dev.stop()
            merged = deploylib.merge_manifests(dev, root, items, dest=dest)
            # Remember the device's own bytes before they are overwritten.  The
            # list has to be the *merged* one: the asset lists are rewritten too,
            # and an uninstall that put the files back but left the lists pointing
            # at them would leave the device claiming rows for files it no longer
            # has.  Doing it here rather than in the window keeps the whole thing
            # on the worker thread, where a few hundred megabytes of pull cannot
            # freeze the interface.
            kept = None
            try:
                kept = backuplib.take(dev, self.inv.depot, merged["items"],
                                      title=self._title_for(chosen),
                                      log=lambda m: None)
            except Exception as exc:  # noqa: BLE001 - report, never lose the push
                kept = {"error": str(exc)}
            out = deploylib.deploy_files(dev, merged["items"], log=lambda m: None)
            # The registry is what the engine compares the lists against, and the
            # lists in ``apk/res`` are partly restored from ``res.zip`` behind our
            # back, so the promise is re-made last, from whatever the device
            # really holds.  Without this a push that edits a table leaves a
            # pending download and the game stops at ASSET DOWNLOAD ERROR.
            try:
                out["data_list"] = deploylib.ensure_data_list(
                    dev, root, dest=dest, log=lambda m: None)
                out["reconcile"] = deploylib.reconcile_registry(
                    dev, root, dest=dest, log=lambda m: None)
            except Exception as exc:  # noqa: BLE001 - never fail the push for this
                out["reconcile"] = {"error": str(exc)}
            out["report"] = merged["report"]
            out["backup"] = kept
            return out

        self._task = Task(work, parent=self)
        self._task.done.connect(self._pushed)
        self._task.fail.connect(self._push_failed)
        self._task.start()
        self.status.emit("Pushing...")

    def _title_for(self, chosen) -> str:
        """A short name for the push, taken from the cars it touches."""
        names = set()
        for _local, remote in chosen:
            if remote.startswith(".depot/vehicles/"):
                rest = remote[len(".depot/vehicles/"):]
                if "/" in rest:
                    names.add(rest.split("/", 1)[0])
        names.discard("data")
        names.discard("common")
        if not names:
            return "a push"
        if len(names) == 1:
            return next(iter(names))
        return f"{len(names)} cars"

    def _pushed(self, info) -> None:
        self._ticked()
        rep = info.get("report", {})
        reg = rep.get("registry", {})
        if reg:
            self.log.note(f"registry merged onto the device copy: {reg.get('changed', 0)} "
                          f"row(s) rewritten, {reg.get('added', 0)} added, "
                          f"{reg.get('rows', 0)} rows kept")
        for name, info_car in rep.get("car_lists", {}).items():
            self.log.note(f"{name}: {info_car['changed']} row(s) rewritten, "
                          f"{info_car['added']} added")
        self._sent = []
        self.refresh()
        self._plan = []
        self.follow_label.setText("")
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        self.push_btn.setEnabled(False)
        self.all_btn.setEnabled(False)
        self.none_btn.setEnabled(False)
        self.log.ok(f"pushed {info['pushed']} file(s)")
        kept = info.get("backup") or {}
        if kept.get("error"):
            self.log.error(
                f"the device's own files could not be remembered, so this push "
                f"cannot be taken back from here: {kept['error']}")
        elif kept.get("id"):
            self.log.note(f"kept {len(kept.get('files') or [])} file(s) of the "
                          f"device's own in {kept['folder']}")
        self._refresh_backup()
        self.status.emit("Push finished")

    def _refresh_backup(self) -> None:
        """Say what can be taken back, and enable the button when it is safe."""
        if self.inv is None:
            return
        try:
            got = backuplib.summary(self.inv.depot)
        except Exception as exc:                 # noqa: BLE001
            self.backup_label.setText(f"Remembered pushes: {exc}")
            self.undo_push_btn.setEnabled(False)
            return
        if not got["pushes"]:
            self.backup_label.setText(
                "Nothing to take back yet. Before a push overwrites a file, the "
                "device's own copy of it is kept - only those files, not the whole "
                "install.")
            self.undo_push_btn.setEnabled(False)
            return
        top = backuplib.top(self.inv.depot)
        size = got["bytes"] / 1024 / 1024
        self.backup_label.setText(
            f"{got['pushes']} push(es) remembered, {got['files']} file(s), "
            f"{size:.1f} MB. The newest is {top.get('id')} "
            f"({top.get('title') or 'a push'}, {len(top.get('files') or [])} "
            f"file(s)). They come off in the reverse order they went on.")
        self.undo_push_btn.setEnabled(self.device is not None)

    def undo_push(self) -> None:
        """Put the device back the way it was before the most recent push."""
        if self.inv is None or self.device is None:
            return
        top = backuplib.top(self.inv.depot)
        if not top:
            return
        ok = QMessageBox.question(
            self, "Take the last push back",
            f"Put the device's own files back from {top.get('id')} "
            f"({top.get('title') or 'a push'})?\n\n"
            f"{len(top.get('files') or [])} file(s) are put back and any file the "
            f"push created is deleted. The asset lists go back to the device's own "
            f"copies, so a car the push installed disappears from the menus again. "
            f"The game must be closed.")
        if ok != QMessageBox.Yes:
            return
        self.undo_push_btn.setEnabled(False)
        dev = self.device

        def work():
            dev.stop()
            return backuplib.restore(dev, self.inv.depot, log=lambda m: None)

        self._task = Task(work, parent=self)
        self._task.done.connect(self._undone)
        self._task.fail.connect(self._push_failed)
        self._task.start()
        self.status.emit("Putting the device back...")

    def _undone(self, info) -> None:
        self.log.ok(f"put back {info['restored']} file(s), removed "
                    f"{info['removed']}, {info['left']} push(es) still remembered")
        self._refresh_backup()
        self.refresh()
        self.status.emit("Device put back")

    def _push_failed(self, text: str) -> None:
        self._ticked()
        self.log.error(text)
        self.status.emit("Push failed")
        QMessageBox.critical(self, "Push failed", text[:2000])

    # ---- log ----------------------------------------------------------
    def check_log(self) -> None:
        if self.device is None:
            return
        dev = self.device

        def work():
            dev.clear_log()
            dev.launch()
            text = dev.logcat(40, path=os.path.join("work", "rrmod_logcat.txt"))
            return text

        self.check_btn.setEnabled(False)
        self.status.emit("Waiting for the game to start...")
        self._task = Task(work, parent=self)
        self._task.done.connect(self._checked)
        self._task.fail.connect(self._check_failed)
        self._task.start()

    def _checked(self, text: str) -> None:
        self.check_btn.setEnabled(True)
        info = deploylib.check_log(text)
        for marker, lines in info["markers"].items():
            for line in lines[:3]:
                self.log.add(line)
        if info["ok"]:
            self.log.ok(f"looks good: {info['start_list']} list fetch(es), "
                        f"{info['up_to_date']} up-to-date")
        else:
            self.log.error(f"{info['download_errors']} download error(s), "
                           f"{info['fatal']} fatal")
        self.status.emit("Log checked")

    def _check_failed(self, text: str) -> None:
        self.check_btn.setEnabled(True)
        self.log.error(text)
        self.status.emit("Log check failed")
