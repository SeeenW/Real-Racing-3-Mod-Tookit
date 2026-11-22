"""The main window: pick an install, then work in one of four tabs.

The first thing the program does is ask where the game is - nothing else works
until that is answered, and the answer is remembered.  After that the window is a
plain tabbed shell; every tab is independent and reads from the same
:class:`rrmod.depot.Inventory`.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import (QAction, QActionGroup, QIcon, QKeySequence,
                           QPixmap)
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog,
                               QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import __version__
from .. import anim as animlib
from .. import depot as depotlib
from .. import edit as editlib
from .. import history as historylib
from .. import i18n
from .. import modpack as packlib
from .. import profile as profilelib
from .. import stats as statlib
from .. import texslots as texslotslib
from . import brandsui, buildui, cars, decalui, depsui, deployui, gfxui, matui, musicui
from . import publishui
from . import seriesui
from . import editing
from . import historyui
from . import settings as settingslib
from . import texui
from . import translate
from . import widgets as W
from . import worker as workerlib
from .worker import Task


def _clips(info: dict) -> list:
    """The aero clips the dialog collected, as ``animxml.Clip`` objects.

    Empty means "leave the donor's file alone", which is the right answer for a
    car that has no animation at all.
    """
    rows = info.get("clips") or []
    return [animlib.animxmllib.Clip(name, int(start), int(end))
            for name, start, end in rows]


#: What the "texture format" picker offers, in the order it offers them.  The
#: keys are what :func:`rrmod.ui.settings.set_texture_family` stores; ``auto``
#: means "read it off the page being replaced", which is right when the answer
#: is unknown and wrong only when the install holds two families at once.
FAMILY_LABELS = (
    ("auto", "Work it out from the files (recommended)"),
    ("dxt", "DXT - .dxt.dds.z (NVIDIA / Adreno)"),
    ("etc", "ETC - .etc.dds.z (Mali)"),
    ("atc", "ATC - .atc.dds.z (Adreno, older)"),
)


class WelcomeDialog(QDialog):
    """Ask for the game folder before anything else."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Where is Real Racing 3?")
        self.resize(640, 440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)

        lay.addWidget(W.heading("Choose the game's data folder", 1))
        lay.addWidget(W.muted(
            "Point at the extracted data package: the folder that contains "
            ".depot and apk. If you point at a folder above it, the manager "
            "looks down one level for files."))
        self.picker = W.PathPicker("Install", caption="Choose the folder holding .depot and apk")
        self.picker.add_history(settingslib.recent("recent_install"))
        self.picker.set_text(settingslib.install() or depotlib.default_install())
        lay.addWidget(self.picker)

        lay.addWidget(W.heading("Optional: a pristine copy", 2))
        lay.addWidget(W.muted(
            "A second, untouched install lets the manager tell the game's own "
            "cars from yours exactly. Without it the first scan is taken as the "
            "baseline."))
        self.reference = W.PathPicker("Reference", caption="Choose the untouched install")
        self.reference.add_history(settingslib.recent("recent_reference"))
        self.reference.set_text(settingslib.reference())
        lay.addWidget(self.reference)

        # The texture format is asked here rather than guessed per file later.
        # The game ships one GPU family per install and every page it carries
        # says which; a livery row copied from a mod made for another family
        # then names a file this install does not have, and the part draws as
        # nothing.  Answering once, up front, is what stops that.
        lay.addWidget(W.heading("Texture format", 2))
        lay.addWidget(W.muted(
            "Which texture set this install was unpacked for. Picking the right "
            "one keeps a new page in the family the rest of the install uses; "
            "\"work it out from the files\" is right when you are not sure."))
        self.family = QComboBox()
        for key, label in FAMILY_LABELS:
            self.family.addItem(label, key)
        self.family.setCurrentIndex(
            max(0, self.family.findData(settingslib.texture_family() or "auto")))
        self.family.setToolTip(
            "vehicles/common is the cheapest place to see this: every page there "
            "carries the family in its name")
        lay.addWidget(self.family)
        lay.addStretch(1)

        self.problem = W.muted("")
        lay.addWidget(self.problem)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(W.button("Quit", self.reject))
        self.go = W.button("Open", self._accept, primary=True)
        row.addWidget(self.go)
        lay.addLayout(row)

    def _accept(self) -> None:
        path = depotlib.find_install(self.picker.text())
        if not path:
            self.problem.setText(
                "That folder has no .depot and apk. Pick the folder that holds both.")
            return
        self.picker.set_text(path)
        # The folder is known now, so the format can be read off it.  This runs
        # on the first launch *and* every time the folder is chosen again,
        # because a second install can be a different unpack - DXT one day, ETC
        # the next - and a setting carried over in silence is how a page ends up
        # in a family the GPU cannot decode.
        got = depotlib.detect_texture_family(path)
        chosen = self.family.currentData() or "auto"
        if chosen == "auto":
            # Fill the answer in for the user: this is the commonest case and it
            # needs no thought.  A folder holding PVRTC pages (an iOS unpack) has
            # no writable family to offer, so the choice stays on "work it out"
            # and the note says why.
            if got in depotlib.WRITABLE_FAMILIES:
                at = self.family.findData(got)
                if at >= 0:
                    self.family.setCurrentIndex(at)
                    self.problem.setText(
                        f"This install's shared pages are {got.upper()}; the "
                        f"format is set to match.")
            elif got:
                self.problem.setText(
                    f"This install's shared pages are {got.upper()}, which cannot "
                    f"be written from a picture - a new page will use the family "
                    f"the sheet it goes into already has.")
        elif got and got != chosen:
            # An answer given earlier for a different install.  Say so rather
            # than quietly overriding it or quietly keeping it: both are ways to
            # write a page the device draws as nothing.
            self.problem.setText(
                f"This install's shared pages are {got.upper()}, but the format "
                f"is set to {chosen.upper()}. Change it above unless you know "
                f"this install reads {chosen.upper()}.")
        self.accept()

    def values(self) -> dict:
        return {"install": self.picker.text(), "reference": self.reference.text(),
                "family": self.family.currentData() or "auto"}


class MainWindow(QMainWindow):
    def __init__(self, install: str = "", reference: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{profilelib.title(settingslib.profile())} "
                            f"{__version__}")
        self.resize(1240, 800)
        self.inv = None
        self.reference = reference
        self._closing = False
        self.editor = None

        self.tabs = QTabWidget()
        self.cars = cars.CarsPage()
        self.music = musicui.MusicPage()
        self.gfx = gfxui.GfxPage()
        self.career = seriesui.SeriesPage()
        self.brands = brandsui.BrandsPage()
        self.materials = matui.MaterialsPage()
        self.deps = depsui.DepsPage()
        self.decals = decalui.DecalsPage()
        self.publish = publishui.PublishPage()
        self.deploy = deployui.DeployPage()
        self.tabs.addTab(self.cars, "Cars")
        self.tabs.addTab(self.music, "Music")
        self.tabs.addTab(self.gfx, "Graphics")
        self.tabs.addTab(self.career, "Career")
        self.tabs.addTab(self.brands, "Brands")
        self.tabs.addTab(self.materials, "Materials")
        self.tabs.addTab(self.deps, "Dependencies")
        self.tabs.addTab(self.decals, "Decals")
        self.tabs.addTab(self.publish, "Publish")
        self.tabs.addTab(self.deploy, "Test")
        self.about = self._about_page()
        self.tabs.addTab(self.about, "About")
        self.setCentralWidget(self.tabs)
        #: Page key -> widget, so the profile menu can hide one without
        #: knowing which attribute it lives on.
        self.pages = {"cars": self.cars, "music": self.music, "gfx": self.gfx,
                      "career": self.career, "brands": self.brands,
                      "materials": self.materials, "deps": self.deps,
                      "decals": self.decals,
                      "publish": self.publish, "deploy": self.deploy,
                      "about": self.about}
        # Which of the ten pages this program is showing.  The studio and the
        # manager are the same build with different pages visible, so a page is
        # hidden rather than left out: switching profile never rebuilds a page,
        # and a page that was in the middle of something keeps its state.
        self.profile_name = settingslib.profile()
        # The history dock floats: it can be dragged out and left beside the
        # window while the rest of the program keeps being used, the way an
        # equaliser panel does.  It is a dock rather than a dialog so that
        # dragging it back in re-attaches it instead of hiding it.
        self.history = historyui.HistoryDock(self)
        self.history.setFloating(False)
        self.addDockWidget(Qt.RightDockWidgetArea, self.history)
        self.history.hide()
        self.history.status.connect(self.message)
        self.history.undo_requested.connect(self.undo_steps)

        self.cars.status.connect(self.message)
        self.cars.picked.connect(self.deploy.set_car)
        self.cars.changed.connect(self._reload_music)
        self.cars.changed.connect(self._staged_changed)
        self.music.status.connect(self.message)
        self.gfx.status.connect(self.message)
        self.career.status.connect(self.message)
        self.brands.status.connect(self.message)
        self.materials.status.connect(self.message)
        self.materials.changed.connect(self._staged_changed)
        self.deps.status.connect(self.message)
        self.deps.changed.connect(self._staged_changed)
        self.decals.status.connect(self.message)
        self.decals.changed.connect(self._staged_changed)
        self.publish.status.connect(self.message)
        self.publish.changed.connect(self._staged_changed)
        self.brands.changed.connect(self._staged_changed)
        self.deploy.device_ready.connect(self.brands.attach_device)
        self.deploy.device_ready.connect(self.gfx.attach_device)
        self.deploy.device_ready.connect(self.career.attach_device)
        self.deploy.device_ready.connect(self._device_ready)
        self.deploy.discarded.connect(self._staged_cleared)

        self._make_menu()
        self.apply_icon()
        self.statusBar().showMessage("Ready")
        # Applied after the menu exists, so the tick next to the profile is right
        # from the first frame.  It only hides pages, so nothing is built twice.
        self.set_profile(self.profile_name)

        if install:
            self.open_install(install)

    def convert_textures(self) -> None:
        """Open the converter, starting where the last one finished."""
        start = settingslib.get("texture_tool_dir", "") or os.path.expanduser("~")
        dlg = texui.TextureTool(self, start_dir=start)
        dlg.status.connect(self.message)
        dlg.exec()
        # The folder the user ended up in is where the next one should start.
        chosen = dlg.out_dir.text().strip()
        if chosen and os.path.isdir(chosen):
            settingslib.set("texture_tool_dir", chosen)

    # ---- menu ---------------------------------------------------------
    def _make_menu(self) -> None:
        m = self.menuBar().addMenu("&File")
        a = QAction("Open install...", self)
        a.setShortcut(QKeySequence.Open)
        a.triggered.connect(self.choose_install)
        m.addAction(a)
        a = QAction("Rescan", self)
        a.setShortcut(QKeySequence.Refresh)
        a.triggered.connect(self.cars.rescan)
        m.addAction(a)
        m.addSeparator()
        a = QAction("Build a car...", self)
        a.setShortcut("Ctrl+B")
        a.triggered.connect(self.build_car)
        m.addAction(a)
        a = QAction("Verify manifests", self)
        a.triggered.connect(self.verify)
        m.addAction(a)
        a = QAction("Undo last edit", self)
        a.setShortcut("Ctrl+Z")
        a.triggered.connect(self.undo_last)
        m.addAction(a)
        a = QAction("Take a change back...", self)
        a.triggered.connect(self.discard_staged)
        m.addAction(a)
        m.addSeparator()
        self.history_action = QAction("History panel", self)
        self.history_action.setCheckable(True)
        self.history_action.setShortcut("Ctrl+H")
        self.history_action.toggled.connect(self.history.setVisible)
        m.addAction(self.history_action)
        a = QAction("Where undo copies are kept...", self)
        a.triggered.connect(self.history.choose_folder)
        m.addAction(a)
        m.addSeparator()
        a = QAction("Quit", self)
        a.setShortcut(QKeySequence.Quit)
        a.triggered.connect(self.close)
        m.addAction(a)

        m = self.menuBar().addMenu("&View")
        self._make_profile_menu(m)

        m = self.menuBar().addMenu("&Tools")
        a = QAction("Convert textures...", self)
        a.setToolTip(
            "PNG to DDS, DDS to PNG, or either one to a texture the game loads - "
            "and back again")
        a.triggered.connect(self.convert_textures)
        m.addAction(a)
        m.addSeparator()
        a = QAction("Find device", self)
        a.triggered.connect(self.deploy._connect)
        m.addAction(a)
        a = QAction("Set adb path...", self)
        a.triggered.connect(self.set_adb)
        m.addAction(a)
        a = QAction("Set window icon...", self)
        a.triggered.connect(self.choose_icon)
        m.addAction(a)
        m.addSeparator()
        self._make_language_menu(m)

    # ---- which program this is ----------------------------------------
    def _make_profile_menu(self, menu) -> None:
        """View -> the pages of one program, or all of them.

        The profile is stored on the action as data rather than compared through
        its text: the labels are translated, so a comparison against
        ``profilelib.label(name)`` stops matching the moment the interface is in
        Chinese and the tick disappears from every entry.
        """
        self._profile_group = QActionGroup(self)
        self._profile_group.setExclusive(True)
        for name in profilelib.PROFILES:
            a = QAction(profilelib.label(name), self)
            a.setCheckable(True)
            a.setData(name)
            a.setChecked(name == self.profile_name)
            a.triggered.connect(lambda _on=False, got=name: self.set_profile(got))
            self._profile_group.addAction(a)
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self.history_action)

    def set_profile(self, name: str) -> None:
        """Show only the pages of one program; keep every page alive."""
        name = profilelib.check(name)
        self.profile_name = name
        shown = set(profilelib.pages(name))
        for key in profilelib.ORDER:
            page = self.pages.get(key)
            if page is None:
                continue
            index = self.tabs.indexOf(page)
            if index < 0:
                continue
            self.tabs.setTabVisible(index, key in shown)
        self.setWindowTitle(f"{profilelib.title(name)} {__version__}"
                            + (f" - {self.inv.root}" if self.inv else ""))
        for action in self._profile_group.actions():
            action.setChecked(action.data() == name)
        self.message(f"{profilelib.label(name)}: "
                     f"{len(shown)} page(s) of {len(profilelib.ORDER)}")
        settingslib.set_profile(name)

    def choose_icon(self) -> None:
        """Let the user pick the picture in the title bar and the task bar."""
        start = os.path.dirname(settingslib.icon()) or ""
        path, _filter = QFileDialog.getOpenFileName(
            self, "Window icon", start,
            "Pictures (*.png *.ico *.jpg *.bmp *.svg);;All files (*)")
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Set window icon",
                                f"{os.path.basename(path)} could not be read as a picture.")
            return
        settingslib.set_icon(path)
        self.apply_icon()
        self.message(f"The window icon is now {os.path.basename(path)}. "
                     "The file's own icon in Explorer needs a rebuild.")

    def apply_icon(self) -> None:
        """Show the remembered icon, if there is one."""
        path = settingslib.icon()
        if not path or not os.path.isfile(path):
            return
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(QIcon(pixmap))
            self.setWindowIcon(QIcon(pixmap))

    def _make_language_menu(self, parent) -> None:
        """One entry per translation file, plus English."""
        self.language_menu = parent.addMenu("Language")
        self.language_group = QActionGroup(self)
        self.language_group.setExclusive(True)
        self.language_actions = {}
        codes = list(i18n.available().items())
        for code, label in sorted(codes, key=lambda item: item[1]):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(code == i18n.language())
            act.triggered.connect(lambda _checked=False, c=code: self.set_language(c))
            self.language_group.addAction(act)
            self.language_menu.addAction(act)
            self.language_actions[code] = act

    def set_language(self, code: str) -> None:
        """Switch the interface language and repaint every visible string."""
        i18n.set_language(code)
        settingslib.set_language(code)
        self.retranslate()

    def retranslate(self) -> None:
        """Re-apply the current language to the whole window."""
        translate.window_title(self)
        translate.apply(self)
        act = getattr(self, "language_actions", {}).get(i18n.language())
        if act is not None:
            act.setChecked(True)

    def _about_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addWidget(W.heading("What this is", 1))
        lay.addWidget(W.muted(
            "A manager for Real Racing 3 car mods: it reads the game's own tables "
            "so it can tell a car you made from one that shipped, keeps the three "
            "asset manifests honest after every edit, and pushes the result to a "
            "device over adb."))
        lay.addWidget(W.heading("Two kinds of car", 2))
        lay.addWidget(W.muted(
            "The game's cars may be modified but not deleted. Yours may be both. "
            "A car that neither list knows about is left alone until you adopt it."))
        lay.addWidget(W.heading("Where the truth lives", 2))
        lay.addWidget(W.muted(
            "A car is identified by its appearance record, not its file name - 352 "
            "of 540 cars differ between the two. rr3mods.json remembers which side "
            "each car is on; the path is below, because the game folder itself is "
            "usually read-only and the file cannot live there."))
        lay.addWidget(W.heading("This install", 2))
        self._about_paths = W.KeyValue()
        lay.addWidget(self._about_paths)
        lay.addWidget(W.muted(
            "Backups of every file the manager rewrites go to _rrmod_backup in the "
            "game folder; File > Undo last edit puts them back."))
        lay.addStretch(1)
        return page

    def _refresh_about(self) -> None:
        if self.inv is None:
            return
        self._about_paths.update_all({
            "Install": self.inv.root,
            "Mods file": depotlib.mods_path(self.inv.depot) or "(nowhere writable)",
            "Backups": depotlib.state_dir(self.inv.depot) or "(nowhere writable)",
            "Settings": settingslib.path(),
        })

    # ---- install ------------------------------------------------------
    def choose_install(self) -> None:
        dlg = WelcomeDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        settingslib.set_install(v["install"])
        # Asked every time the folder is chosen, not only on the first run: a
        # second install can be a different unpack (DXT one day, ETC the next),
        # and a setting carried over silently is how the wrong family gets
        # written into a page nobody notices until the part draws as nothing.
        settingslib.set_texture_family(v.get("family") or "auto")
        self.publish.set_family(v.get("family") or "auto")
        if v["reference"]:
            settingslib.set_reference(v["reference"])
            settingslib.remember("recent_reference", v["reference"])
            self.reference = v["reference"]
        self.open_install(v["install"])

    def open_install(self, path: str) -> None:
        self.message("Scanning the install...")
        self._task = Task(depotlib.scan, path, parent=self)
        self._task.done.connect(self._scanned)
        self._task.fail.connect(self._scan_failed)
        self._task.start()

    def _scanned(self, inv) -> None:
        if getattr(self, "_closing", False):
            # The window is on its way out; filling six pages now would start more
            # worker threads than the close handler can wait for.
            return
        self.inv = inv
        # Edits are written straight into the install from here on.  There is no
        # staging step any more: the safety net is the per-car backup button and
        # the undo history, both of which copy a file aside before it is written.
        self.editor = editing.Editor(inv.root)
        self.cars.editor = self.editor
        self.gfx.editor = self.editor
        self.music.editor = self.editor
        self.career.editor = self.editor
        self.brands.editor = self.editor
        self.materials.depot = inv.depot
        self.materials.editor = self.editor
        self.deps.attach_root(self.editor.root)
        self.decals.attach_root(self.editor.root)
        self.decals.attach_editor(self.editor)
        self.deploy.attach(inv)
        self.history.attach(self.editor)
        # First run on this install: nothing knows which cars are the game's own.
        # Ask once, then keep the answer in rr3mods.json.
        if not depotlib.mods_path(inv.depot, create=False):
            if self._take_baseline(inv):
                return
        self.cars.load(inv)
        self.music.load(inv.depot)
        self.gfx.load(inv.depot)
        self.career.load(inv.depot)
        self.brands.load(inv)
        self.materials.load(inv.depot)
        self.deps.load(inv.depot, self.editor.root)
        self.decals.load(inv.depot, self.editor.root)
        self.publish.load(inv, self.editor.root)
        self.deploy.load(inv)
        self.setWindowTitle(f"{profilelib.title(self.profile_name)} "
                            f"{__version__} - {inv.root}")
        self._refresh_about()
        self.message(inv.summary())
        if inv.unknown:
            self.message(f"{len(inv.unknown)} unmanaged car(s) - see the Cars tab")
        if inv.missing:
            self.message(f"{len(inv.missing)} car(s) in the baseline have no folder")

    def _take_baseline(self, inv) -> bool:
        """Write rr3mods.json for the first time.  True when a rescan is needed."""
        text = (f"This is the first time this program has seen this install.\n\n"
                f"It found {len(inv.cars)} cars and does not yet know which of them "
                "are the game's own. Take the current state as the baseline?")
        if self.reference:
            text += f"\n\nThe pristine copy at {self.reference} will be used instead, " \
                    "which is exact."
        ok = QMessageBox.question(self, "First run", text,
                                  QMessageBox.Yes | QMessageBox.No)
        if ok != QMessageBox.Yes:
            self.message("No baseline written - every car stays unmanaged")
            return False
        try:
            depotlib.bootstrap(inv, reference_depot=self.reference)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Baseline", str(exc))
            return False
        self.open_install(inv.root)
        return True

    def _scan_failed(self, text: str) -> None:
        self.message("Scan failed")
        QMessageBox.critical(self, "Scan failed", text[:2000])

    def _device_ready(self, device) -> None:
        if self.editor is not None:
            self.editor.set_device(device)

    def _staged_changed(self) -> None:
        """Something changed on disk: refresh the test page and the history."""
        self.deploy.refresh()
        self.history.refresh()
        self.message("Written to the game folder - check it in the Test tab")

    def _staged_cleared(self) -> None:
        """Files were put back: re-read every pane that was showing them.

        An undo rewrites the files the edit touched, and every pane under the car
        list reads from disk, so refreshing the test list alone is not enough -
        the car page kept showing the edit that had just been taken back.  This
        runs only on an undo, not on every edit: a refresh reloads the paint and
        parts panes, which would wipe out a half-typed value in a pane the user
        has not saved yet.
        """
        self._staged_changed()
        self.cars.refresh_detail()

    def _reload_music(self) -> None:
        if self.inv:
            self.music.load(self.inv.depot)

    # ---- actions ------------------------------------------------------
    @staticmethod
    def _slot_targets(info: dict, car: str) -> dict:
        """``{the name the game expects: source path}`` for the new-car branch."""
        from .. import slots as slotlib

        mapping = info.get("slots") or {}
        return slotlib.rename_plan(mapping, car) if mapping else {}

    def build_car(self) -> None:
        if self.inv is None:
            QMessageBox.information(self, "Build a car", "Open an install first.")
            return
        dlg = buildui.BuildDialog(self.inv, self)
        if dlg.exec() != QDialog.Accepted:
            return
        info = dlg.result_info()
        self.tabs.setCurrentWidget(self.cars)

        if info["new"]:
            ok = QMessageBox.question(
                self, "Build a car",
                f"Create {info['new_name']} as id {info['new_id']}, "
                f"cloned from {info['donor']}?\n\n"
                "The spec, appearance record, suspension and damage rows are all "
                "written straight into the game folder, and every file it touches "
                "is copied to the undo history first. The Test tab compares the "
                "folder with the device when you want to push it.")
            if ok != QMessageBox.Yes:
                return

            def work():
                # The build writes into the install directly.  That is safe
                # because ``edit`` copies each file aside before it is written,
                # so a build that fails half way is one Undo away from gone - and
                # because the device is a separate copy that nothing here touches.
                root = self.editor.for_tables(info["donor"])
                # The wings the donor already carries keep whatever paint the
                # donor gave them; only a wing the pack brings needs new rows.
                donor_wing = editlib.wing_parts(root, info["donor"])
                out = editlib.install_pack(
                    root, info["pack"],
                    new_id=info["new_id"], donor=info["donor"],
                    name=info["new_name"],
                    appearance_id=info.get("appearance_id", 0),
                    model_token=info.get("model_token", ""),
                    aliases=info.get("aliases", True),
                    paints=info.get("paints"),
                    car_class=info.get("car_class", ""),
                    make=info.get("make", ""),
                    aero=info["aero"] != 2,
                    aero_kind=info.get("aero_kind") or b"",
                    aero_params=info.get("aero_params") or (),
                    slot_files=_slot_targets(info, info["new_name"]),
                    wheel_sizes=info.get("wheel_sizes"),
                    log=lambda m: None)
                # The pages of the car's own folder, written after the folder is
                # copied: the donor's copies are already there under the new
                # name, and these replace the ones the pack brings.  A picture
                # is encoded here, which is what "converted when you press
                # Build" means.
                if info.get("textures"):
                    out["textures"] = editlib.install_textures(
                        root, info["new_name"], info["textures"],
                        family_key=settingslib.texture_family(),
                        log=lambda m: None)
                # A wing the pack brings needs a paint row of its own: a wing slot
                # with none falls back to car_flat, which has no specular colour,
                # so the part renders almost black.  This runs before the finish
                # is written, so a new finish reaches the wing too.
                arrived = [p for p in editlib.wing_parts(root, info["new_name"])
                           if p not in donor_wing]
                if arrived:
                    wing = editlib.sync_wing_paint(
                        root, info["new_name"], parts=arrived,
                        log=lambda m: None)
                    if wing.get("added"):
                        out["wing_paint"] = wing
                # the figures come last: the spec only exists once the build has
                # cloned the donor's
                if info.get("stats"):
                    out["stats"] = statlib.write(root, info["new_name"],
                                                 info["stats"])
                # Schemes queued in the dialog are appended to the livery table
                # the build just copied, before the colours are written: the
                # indices the colour map carries count the added rows.
                for add in info.get("paint_adds") or []:
                    out.setdefault("paints_added", []).append(
                        editlib.add_paint_scheme(
                            root, info["new_name"],
                            livery_name=add["name"],
                            copy_from=add.get("copy_from", 0),
                            source=add.get("atlas", ""),
                            pictures=add.get("pictures") or None,
                            tag=add.get("tag", ""),
                            family_key=settingslib.texture_family()))
                # The finish and the colours are written after the build, because
                # the livery file they change is the one the build just copied
                # from the donor.
                finish = info.get("paint_finish") or ""
                colours = info.get("paint_colours") or {}
                per_paint = info.get("paint_finishes") or {}
                if finish or colours or per_paint:
                    out["paint"] = editlib.set_paint_finish(
                        root, info["new_name"], material=finish, colours=colours,
                        per_paint=per_paint)
                # a scheme given its own pictures keeps them; this runs after the
                # build because it rewrites the livery the build just copied
                for index, pictures in (info.get("paint_pictures") or {}).items():
                    out.setdefault("atlases", []).append(
                        editlib.set_paint_pictures(
                            root, info["new_name"], int(index), pictures,
                            family_key=settingslib.texture_family()))
                clips = _clips(info)
                if clips:
                    out["clips"] = animlib.apply_xml(root, info["new_name"], clips)
                # The seated pose is a field in the data record, which the build
                # has just cloned from the donor, so it waits for the record.
                pose = info.get("driver_pose") or {}
                if pose.get("after") != pose.get("before"):
                    out["pose"] = editlib.set_driver_pose(
                        root, info["new_name"], pose.get("after") or "")
                # The engine sound is three strings in the spec, so it is written
                # after the build for the same reason as the figures above.
                if info.get("sound"):
                    out["sound"] = statlib.set_sound(
                        root, info["new_name"], info["sound"])
                # The upgrade route is one string in the spec, so it waits for
                # the spec to exist, same as the figures and the sound above.
                if info.get("route"):
                    out["route"] = statlib.set_route(
                        root, info["new_name"], info["route"])
                # The aspiration, the layout, the unlock rule and the two prices
                # are also spec bytes, so they wait for the cloned spec too.
                if info.get("tail"):
                    out["tail"] = statlib.set_tail(
                        root, info["new_name"], **info["tail"])
                # A car with no series is a car the game never offers, so the
                # placement runs here - after the spec exists, because the series
                # names the cars allowed to enter by id.
                placed = info.get("series") or {}
                if placed.get("template"):
                    from .. import series as serieslib
                    career_root = self.editor.for_career()
                    title = (placed.get("title")
                             or serieslib.title_from(info["new_name"]))
                    out["series"] = serieslib.place(
                        career_root, template=placed["template"], title=title,
                        cars=[info["new_id"]],
                        group=placed.get("group", ""),
                        register_in=self.inv.depot,
                        log=lambda m: None)
                    # The career files live outside vehicles/, so a car capture
                    # cannot see them; the undo step already recorded them,
                    # because ``series.place`` writes through ``edit``.
                    out["series"]["career"] = len(serieslib.career_leaves())
                return out

            self.message("Building...")
            self._task = Task(work, parent=self)
            self._task.done.connect(self._built)
            self._task.fail.connect(self._build_failed)
            self._task.start()
            return

        # branch 1: replace files of an existing car
        car_name = info["car"]
        mapping = info.get("slots") or {}
        # Everything the dialog queued is spelled out here, because a rename is
        # not visible in the file count and a deletion is not reversible by
        # looking at the folder.
        extra = []
        identity = info.get("identity") or {}
        if identity.get("display_name"):
            extra.append(f"be called {identity['display_name']}")
        if identity.get("make"):
            extra.append(f"be filed under {identity['make']}")
        if identity.get("model"):
            extra.append(f"be a {identity['model']}")
        if info.get("paint_adds"):
            extra.append(f"gain {len(info['paint_adds'])} paint scheme(s)")
        if info.get("paint_removes"):
            extra.append(f"lose {len(info['paint_removes'])} paint scheme(s)")
        if info.get("textures"):
            pictures = [t for t in info["textures"]
                        if texslotslib.is_picture(str(t.get("source") or ""))]
            extra.append(f"replace {len(info['textures'])} texture page(s)"
                         + (f", converting {len(pictures)} picture(s)"
                            if pictures else ""))
        repainted = sum(len(p) for p in (info.get("paint_pictures") or {}).values())
        if repainted:
            extra.append(f"repaint {repainted} slot(s) of the schemes it keeps")
        also = ("\n\nIt will also " + ", ".join(extra) + ".") if extra else ""
        if mapping:
            opening = (f"Put {len(mapping)} file(s) into {car_name}'s folder?\n\n"
                       "They go straight into the game folder; every file they "
                       "replace is copied to the undo history first, so Ctrl+Z "
                       "takes the build back.")
        else:
            opening = (f"Change {car_name} without touching its files?\n\n"
                       "No folder was chosen, so every model, animation and "
                       "anchor stays exactly as it is; only what this dialog "
                       "asked for is written, and the undo history keeps a copy "
                       "of every file that changes.")
        ok = QMessageBox.question(self, "Modify a car", opening + also)
        if ok != QMessageBox.Yes:
            return

        def work():
            root = self.editor.for_car(car_name)
            # What the car carried before the pack lands, so a wing the pack
            # brings can be told apart from one the studio already painted.
            before = editlib.wing_parts(root, car_name)
            # A build that brings no files is a settings-only edit: the spec,
            # the livery table and the text tables are all written on their own,
            # and there is nothing to copy into the car's folder.
            out = (editlib.install_slots(root, car_name, mapping,
                                         log=lambda m: None)
                   if mapping else {})
            # The car's own texture pages, for the same reason and at the same
            # moment as the models: a picture is encoded when the build runs.
            if info.get("textures"):
                out["textures"] = editlib.install_textures(
                    root, car_name, info["textures"],
                    family_key=settingslib.texture_family(), log=lambda m: None)
            # The wheel size is a record field, not a file, so it is written
            # after the files land: a pack that ships a correctly proportioned
            # wheel still draws at the donor's radii until this runs.
            if info.get("wheel_sizes"):
                out["wheels"] = editlib.set_wheel_sizes(
                    root, car_name, info["wheel_sizes"], log=lambda m: None)
            # A pack that brings wing meshes needs paint rows for them, or the
            # game draws the wing through car_flat and it comes out black.  The
            # rows are only added where the car has none, so a wing with its own
            # paint keeps it.
            arrived = [p for p in editlib.wing_parts(root, car_name)
                       if p not in before]
            if arrived:
                wing = editlib.sync_wing_paint(root, car_name, parts=arrived,
                                               log=lambda m: None)
                if wing.get("added"):
                    out["wing_paint"] = wing
            # Only when the dialog's "also change what it drives like" box was
            # ticked - it returns nothing otherwise, so an untouched spec stays
            # untouched.
            if info.get("stats"):
                out["stats"] = statlib.write(root, car_name, info["stats"])
            # "leave as it is" is 0; anything else sets or clears the behaviour
            # in the spec, which is what makes the game play the wing at all.
            if info.get("aero"):
                out["aero"] = editlib.set_aero_flag(
                    root, car_name, info["aero"] != 2,
                    kind=info.get("aero_kind") or b"",
                    params=info.get("aero_params") or ())
            clips = _clips(info)
            if clips:
                out["clips"] = animlib.apply_xml(root, car_name, clips)
            pose = info.get("driver_pose") or {}
            if pose.get("after") != pose.get("before"):
                out["pose"] = editlib.set_driver_pose(
                    root, car_name, pose.get("after") or "")
            if info.get("sound"):
                out["sound"] = statlib.set_sound(root, car_name, info["sound"])
            if info.get("route"):
                out["route"] = statlib.set_route(root, car_name, info["route"])
            if info.get("tail"):
                out["tail"] = statlib.set_tail(root, car_name, **info["tail"])
            # What the car is called, who makes it and which model it is.  The
            # name of a shipped car is a key into the text tables, so this
            # rewrites thirteen text files when it is touched - and nothing at
            # all when the boxes were left as they were, which is the usual case.
            identity = info.get("identity") or {}
            if identity:
                out["identity"] = editlib.set_identity(
                    root, car_name,
                    display_name=identity.get("display_name", ""),
                    make=identity.get("make", ""),
                    model=identity.get("model", ""))
            # Deletions first: a scheme queued for deletion must be gone before
            # an addition is copied in, or the copy can land on a row that is
            # about to disappear.
            if info.get("paint_removes"):
                out["paints_removed"] = editlib.remove_paint_scheme(
                    root, car_name, info["paint_removes"])
            for add in info.get("paint_adds") or []:
                out.setdefault("paints_added", []).append(
                    editlib.add_paint_scheme(
                        root, car_name, livery_name=add["name"],
                        copy_from=add.get("copy_from", 0),
                        source=add.get("atlas", ""),
                        pictures=add.get("pictures") or None,
                        tag=add.get("tag", ""),
                        family_key=settingslib.texture_family()))
            # A picture given to a scheme the dialog keeps is written after the
            # additions, so the row indices the dialog counted still line up.
            # The colour and the finish are read-only here - the dialog sends
            # those to the Cars page's paint section - so they are not written.
            for index, pictures in (info.get("paint_pictures") or {}).items():
                out.setdefault("atlases", []).append(
                    editlib.set_paint_pictures(
                        root, car_name, int(index), pictures,
                        family_key=settingslib.texture_family()))
            return out

        self.message("Writing...")
        self._task = Task(work, parent=self)
        self._task.done.connect(self._built)
        self._task.fail.connect(self._build_failed)
        self._task.start()

    def _built(self, info) -> None:
        changed = 0
        if isinstance(info, dict) and info.get("stats"):
            changed = len(info["stats"].get("changed") or [])
        placed = info.get("series") if isinstance(info, dict) else None
        made = (placed or {}).get("made") or {}
        wing = (info.get("wing_paint") if isinstance(info, dict) else None) or {}
        if made:
            self.message(
                f"Built, and put it in {made.get('group') or 'its own group'} "
                f"as series {made.get('id')} - rescanning")
        elif changed:
            self.message(f"Built with {changed} figure(s) of its own - rescanning")
        else:
            self.message("Done - rescanning")
        if wing.get("added"):
            names = ", ".join(w.replace("LOD_A_", "") for w in wing["added"])
            self.message(f"Wing paint rows added for {names} - rescanning")
        renamed = (info.get("identity") if isinstance(info, dict) else None) or {}
        after = renamed.get("after") or {}
        if after.get("name") and after.get("name") != renamed.get("before", {}).get("name"):
            self.message(f"Renamed to {after['name']} - rescanning")
        if renamed.get("note"):
            # A car with no name field of its own is named from its model, so a
            # rename there changes nothing - say so instead of writing silently.
            self.message(renamed["note"])
        added = len((info.get("paints_added") if isinstance(info, dict) else None) or [])
        gone = (info.get("paints_removed") if isinstance(info, dict) else None) or {}
        if added or gone:
            bits = []
            if added:
                bits.append(f"{added} scheme(s) added")
            if gone.get("removed"):
                bits.append(f"{len(gone['removed'])} deleted")
            self.message(", ".join(bits).capitalize() + " - rescanning")
        self.cars.rescan()

    def _build_failed(self, text: str) -> None:
        self.message("Build failed")
        QMessageBox.critical(self, "Build failed", text[:3000])

    def verify(self) -> None:
        """Check that the staged manifests agree with the staged files."""
        if self.inv is None:
            return
        root = self.editor.root if self.editor else self.inv.root
        try:
            problems = editlib.verify(root)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Verify", str(exc))
            return
        if not problems:
            QMessageBox.information(
                self, "Verify",
                "Every asset list agrees with the files on disk. Nothing the "
                "engine would want to download again.")
            return
        QMessageBox.warning(self, "Verify",
                            f"{len(problems)} problem(s):\n\n" +
                            "\n".join(problems[:30]))

    def undo_last(self) -> None:
        """Put back the files of the last edit, and only those.

        Every edit copies each file it is about to change into
        ``_rrmod_backup/<stamp>/`` first, so the newest folder is the last edit -
        undoing it leaves every earlier edit alone, which is the whole reason the
        history is kept per step rather than as one pile.
        """
        if self.inv is None or self.editor is None:
            return
        steps = editlib.backups(self.editor.root)
        if not steps:
            QMessageBox.information(
                self, "Undo",
                "Nothing has been edited yet on this install, so there is nothing "
                "to put back.")
            return
        newest = steps[0]
        step = historylib.read(self.editor.root, newest)
        count = len(step.get("files") or [])
        ok = QMessageBox.question(
            self, "Undo the last edit",
            f"Put back the {count} file(s) the edit of {newest} "
            f"({historylib.label(step)}) touched?\n\n"
            "Only those files are restored; every other edit stays as it is.",
            QMessageBox.Yes | QMessageBox.No)
        if ok != QMessageBox.Yes:
            return
        self.undo_steps([newest])

    def undo_steps(self, stamps_) -> None:
        """Put back the files of the given steps, oldest first."""
        if self.inv is None or self.editor is None:
            return
        wanted = [s for s in (stamps_ or []) if s]
        if not wanted:
            return
        try:
            done = historylib.restore(self.inv.root, wanted)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Undo", str(exc)[:2000])
            return
        if not done["files"]:
            self.message("Those steps had nothing left to put back")
        else:
            self.message(f"Undid {len(wanted)} edit(s): {len(done['files'])} "
                         f"file(s) restored in the game folder")
        self._staged_cleared()

    def discard_staged(self) -> None:
        """There is nothing staged any more - point at the two things that undo."""
        QMessageBox.information(
            self, "Nothing to discard",
            "Edits go straight into the game folder now, so there is no staging "
            "area to throw away.\n\n"
            "To take a change back: Undo last edit (Ctrl+Z) in this menu, or "
            "restore the car from its backup on the Cars page.")

    def set_adb(self) -> None:
        start = settingslib.adb() or os.path.expanduser("~")
        got, _ = QFileDialog.getOpenFileName(self, "Choose adb.exe", start,
                                             "adb (adb.exe);;All files (*)")
        if got:
            settingslib.set_adb(got)
            self.message(f"adb: {got}")

    # ---- shutting down -------------------------------------------------
    def closeEvent(self, event) -> None:
        """Let the worker finish before the window (and its children) go away.

        A ``QThread`` that is still running when its parent is destroyed takes the
        process down with ``QThread: Destroyed while thread is still running``, and
        a scan or a deploy takes long enough for the user to close the window in
        the middle of one.  Cancelling only skips the result signal, so the wait is
        bounded by the job that is already running.  The career parse alone takes
        six seconds on the retail file, hence the generous timeout.

        Every ``QThread`` child is waited on, not just the ones a page happens to
        keep in ``_task``: a page can start a second job and overwrite the first
        reference, and the one that leaks is exactly the one that crashes.

        The flag also stops the scan handler from filling six pages - each of which
        starts its own worker - after the user has already asked to quit.

        Anything still staged is mentioned before the window goes: the working
        copy survives the process, so the changes are not lost, but a user who
        edited six cars and forgot to push deserves to be told rather than
        discovering it on the next launch.
        """
        if not self._confirmed_quit():
            event.ignore()
            return
        self._closing = True
        workerlib.shutdown()
        stuck = workerlib.wait_all(30000)
        if stuck:
            self.statusBar().showMessage(
                f"{len(stuck)} background job(s) did not stop; quitting anyway")
        super().closeEvent(event)

    def _confirmed_quit(self) -> bool:
        """Ask nothing: an edit is already in the game folder.

        This used to warn about files waiting in the working copy.  There is no
        working copy any more, so the honest answer is always "go ahead" - a
        warning here would be describing a staging area that no longer exists.
        """
        return True

    def message(self, text: str) -> None:
        self.statusBar().showMessage(str(text), 8000)
