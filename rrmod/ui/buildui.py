"""Build a car: the two branches the user asked for, plus the pack preview.

Branch 1 - *modify a car that is already installed*.  The car keeps its id; the
files in the pack replace the matching ones and the three manifests learn the new
sizes.  This is the cheap path, and the one "the studio forgot the active wing"
needs.

Branch 2 - *a new car*.  A donor is cloned (its id, its tables, its paint
schemes) and the pack's files are dropped in.  A donor is mandatory because every
game table row is keyed by a car id that has to already exist somewhere.

The dialog never builds by itself: it validates the pack, shows exactly what will
happen, and hands the job back to the caller, which runs it on a worker thread.

The numbers (weight, top speed, 0-60, braking, grip) come from the donor's spec
file, because that is where the game reads them.  They are shown next to what the
donor itself has so a new car can be given its own figures without leaving the
dialog - see :mod:`rrmod.stats` for why PR and the engine block are read-only.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog,
                               QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QRadioButton,
                               QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import depot as depotlib
from .. import anim as animlib
from .. import modpack as packlib
from .. import paints as paintslib
from .. import series as serieslib
from .. import slots as slotlib
from .. import stats as statlib
from .. import texslots as texlib
from rr3lib import livery as liverylib
from rr3lib import wheelsize as wheelsizelib
from . import settings as settingslib
from . import paintui
from . import widgets as W
from .worker import Task

def _price_words(changes: dict, cash: int, gold: int) -> str:
    """The price half of a plan sentence, naming only the prices that moved.

    A car that keeps the donor's gold price should not read as though the build
    were about to set it, which is why this looks at ``changes`` rather than at
    the two boxes.
    """
    cash_moved = "cash" in changes
    gold_moved = "gold" in changes
    if cash_moved and gold_moved:
        return f"sold for {cash} R$ and {gold} gold"
    if cash_moved:
        return f"sold for {cash} R$" + ("" if cash else " (not for sale)")
    if gold_moved:
        return f"sold for {gold} gold" + ("" if gold else " (not for sale)")
    return ""


#: The aero behaviours, in the order the dialog offers them.  ``None`` means
#: "leave the donor's own behaviour alone".
AERO_ITEMS = (
    ("leave as it is", None),
    ("Braking only - the wing rises to slow the car", b"DeployWhenBraking"),
    ("Speed only - the wing flattens to cut drag", b"DeployAtSpeed"),
    ("Both - drag reduction and air brake", b"BrakeAndSpeedCombo"),
    ("NASCAR air brake", b"NascarAirBrake"),
    ("No active aero", b""),
)

#: What a field means, where the name alone is not enough.  The two PRs and the
#: gear count are the ones a builder asks about.
_FIELD_NOTES = {
    "pr": "The PR the showroom starts at. The game derives it from the figures "
          "above, so a value that does not match them is a car whose card "
          "disagrees with what it drives like.",
    "pr_max": "The PR once everything on the car's upgrade route is bought. The "
              "game derives it from the figures after the route's percentages, "
              "so this is an override - a car with a hand-written maximum can "
              "end up above or below what its parts add up to.",
    "gears": "How many ratios the gearbox has. Changing it rebuilds the ratio "
             "list behind the number (a new gear is interpolated between the "
             "two it is squeezed into), because the count decides how many "
             "floats follow it - and everything after it is re-read to prove "
             "the file still parses.",
}

#: How a number is shown in the table; ``None`` means "as the file has it".
_NUMBER_FORMAT = {
    "weight_lb": "{:.0f}",
    "top_speed": "{:.0f}",
    "top_speed_max": "{:.0f}",
    "accel": "{:.2f}",
    "accel_max": "{:.2f}",
    "braking": "{:.1f}",
    "braking_max": "{:.1f}",
    "grip": "{:.2f}",
    "grip_max": "{:.2f}",
    "pr": "{:.1f}",
    "final_drive": "{:.2f}",
    "power_hp": "{:.0f}",
    "power_rpm": "{:.0f}",
    "torque": "{:.0f}",
    "torque_rpm": "{:.0f}",
    "redline": "{:.0f}",
    "limiter": "{:.0f}",
    "shift_up": "{:.0f}",
    "shift_down": "{:.0f}",
    "gears": "{:.0f}",
}


def _colour(rgb) -> "QColor":
    """A paint swatch colour from the paint's RGB bytes."""
    from PySide6.QtGui import QColor
    r, g, b = (max(0, min(255, int(v))) for v in rgb)
    return QColor(r, g, b)


class BuildDialog(QDialog):
    """Collect a pack, a branch and (for a new car) an identity."""

    def __init__(self, inv, parent=None):
        super().__init__(parent)
        self.inv = inv
        self.pack = None
        self._original_colours: list = []
        #: the source car's own figures, so a word box knows what "unchanged" is
        self._stat_values: dict = {}
        #: spec key -> the dropdown showing it (class, drivetrain)
        self._word_boxes: dict = {}
        #: paint schemes to add after the build, and (for an installed car) to
        #: remove - nothing is written until Build is pressed
        self._paint_adds: list = []
        self._paint_removes: list = []
        #: the paint table's rows as they were drawn, so a handler can map a
        #: selected row back to a scheme index
        self._shown_paints: list = []
        #: slot key -> source path; filled from the folder, correctable by hand
        self._mapping: dict = {}
        self.setWindowTitle("Build a car")
        self.resize(760, 620)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # Everything above the buttons lives in a scroll area: four sections with
        # two tables do not fit a laptop screen, and the window refused to grow.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        inner = QVBoxLayout(body)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(8)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

        # ---- the pack ------------------------------------------------
        inner.addWidget(W.heading(
            "1. The exported folder  (optional when changing a car)", 2))
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText(
            "Folder of exported .m3g files - leave empty to keep the car's own")
        self.path.editingFinished.connect(self._load_pack)
        row.addWidget(self.path, 1)
        row.addWidget(W.button("Browse...", self._browse))
        row.addWidget(W.button("Check", self._load_pack))
        inner.addLayout(row)
        self.pack_info = W.muted("No folder chosen.")
        inner.addWidget(self.pack_info)

        self.slot_note = W.muted(
            "Every slot the game has, and which file fills it. The names are "
            "worked out from the files themselves - LOD_A.m3g is the A body LOD, "
            "SHARED.m3g the shared model, INT_A.m3g the cockpit - so the folder "
            "needs nothing but the exports. Select a row and press Set file... "
            "to correct a guess, or to replace that one file of a car that is "
            "already installed without choosing a folder at all.")
        self.slot_note.setWordWrap(True)
        inner.addWidget(self.slot_note)

        self.files = QTableWidget(0, 3)
        self.files.setHorizontalHeaderLabels(("Slot", "File", "Becomes"))
        self.files.verticalHeader().setVisible(False)
        self.files.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.files.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.files.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.files.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.files.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.files.setMaximumHeight(240)
        inner.addWidget(self.files)
        slot_row = QHBoxLayout()
        slot_row.addWidget(W.button(
            "Set file...", self._set_slot_file,
            tip="Use this file for the selected slot instead of the one guessed"))
        slot_row.addWidget(W.button(
            "Clear slot", self._clear_slot,
            tip="Leave this slot alone - the donor's own file stays"))
        slot_row.addStretch(1)
        inner.addLayout(slot_row)

        # ---- the textures --------------------------------------------
        #
        # The pages of the car's own folder are the other half of an export: the
        # models are renamed to ``<car>_a.m3g`` and the pictures have to be
        # renamed to ``<car>_misc.dxt.dds.z``.  The slot names come from the
        # car's livery table, not from a list in this file, so a car that has no
        # wheel_blur page is never offered one.
        inner.addWidget(W.heading("1b. The textures in the folder", 3))
        self.tex_note = W.muted(
            "The pages a car keeps in its own folder - calipers, wheels, lights, "
            "the paint mask - are named the way the models are: misc.png becomes "
            "<car>_misc, exactly as LOD_A.m3g becomes <car>_a.m3g. A picture is "
            "converted to the texture format chosen in Settings when you press "
            "Build, not when the folder is read, so a build you cancel writes "
            "nothing.")
        self.tex_note.setWordWrap(True)
        inner.addWidget(self.tex_note)

        self.tex_table = QTableWidget(0, 3)
        self.tex_table.setHorizontalHeaderLabels(("Slot", "File", "Becomes"))
        self.tex_table.verticalHeader().setVisible(False)
        self.tex_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tex_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tex_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.tex_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.tex_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        self.tex_table.setMaximumHeight(200)
        inner.addWidget(self.tex_table)
        tex_row = QHBoxLayout()
        tex_row.addWidget(W.button(
            "Set file...", self._set_tex_file,
            tip="Use this picture for the selected slot instead of the one "
                "guessed from the folder"))
        tex_row.addWidget(W.button(
            "Clear slot", self._clear_tex,
            tip="Leave this page alone - the car keeps the one it has"))
        tex_row.addStretch(1)
        inner.addLayout(tex_row)

        self.livery_note = W.muted(
            "A file called ext_<something>, or one in the folder's livery/ "
            "subfolder, is a paint scheme's own body picture rather than a page "
            "of the car's. They are recognised here so you can pick one when you "
            "add a paint scheme below.")
        self.livery_note.setWordWrap(True)
        inner.addWidget(self.livery_note)
        self.livery_table = QTableWidget(0, 2)
        self.livery_table.setHorizontalHeaderLabels(
            ("Picture in the folder", "Will be written as"))
        self.livery_table.verticalHeader().setVisible(False)
        self.livery_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.livery_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.livery_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.livery_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.livery_table.setMaximumHeight(120)
        inner.addWidget(self.livery_table)

        #: ``{stem: file row}`` for the slots the user pointed at a file by hand.
        #: A refill keeps them, because the folder is not the only answer.
        self._tex_override: dict = {}

        # ---- the branch ----------------------------------------------
        inner.addWidget(W.heading("2. What to do with it", 2))
        self.branch_modify = QRadioButton(
            "Modify a car that is already installed  (keeps its id, tables and paints)")
        self.branch_new = QRadioButton(
            "Create a new car  (clone a donor's id and tables, then swap in these files)")
        self.branch_modify.setChecked(True)
        self.branch_modify.toggled.connect(self._branch_changed)
        inner.addWidget(self.branch_modify)
        inner.addWidget(self.branch_new)

        form = QFormLayout()
        form.setContentsMargins(18, 4, 0, 0)
        self.car = QComboBox()
        self.car.setEditable(True)
        form.addRow("Car", self._with_picker(self.car, False))
        self.donor = QComboBox()
        self.donor.setEditable(True)
        form.addRow("Donor", self._with_picker(self.donor, False))
        self.new_id = QSpinBox()
        self.new_id.setRange(0, 100000)
        self.new_id.setSpecialValueText("auto")
        self.new_id.setToolTip(
            "Every game table row is keyed by this number. Press Auto to take the "
            "next free one; a number already in use is refused before anything "
            "is written, because a duplicate would overwrite that car's rows.")
        self.auto_id = QCheckBox("Auto")
        self.auto_id.setChecked(True)
        self.auto_id.setToolTip(
            "Take the next free id and keep it in step with the install")
        self.auto_id.toggled.connect(self._auto_id_changed)
        id_row = QHBoxLayout()
        id_row.addWidget(self.new_id, 1)
        id_row.addWidget(self.auto_id)
        form.addRow("New car id", id_row)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("2012_lexus_lfa_wing  (must start with a number)")
        form.addRow("New folder name", self.new_name)
        self.appearance_id = QSpinBox()
        self.appearance_id.setRange(0, 100000)
        self.appearance_id.setSpecialValueText("auto")
        self.appearance_id.setToolTip(
            "The appearance record is what the game actually looks cars up by; "
            "leave it on auto to take the next free one")
        form.addRow("Appearance id", self.appearance_id)
        self.display_key = QLineEdit()
        self.display_key.setPlaceholderText(
            "empty: derived for a new car, kept for an installed one")
        self.display_key.setToolTip(
            "What the game calls the car, on the line under the brand.  The brand "
            "is shown above it on its own line, so the name here is normally the "
            "model alone - ``LFA``, not ``Lexus LFA``; 526 of the 541 shipped "
            "cars are named that way, and the fifteen that are not are the NASCAR "
            "stock cars.  A car this program builds has the string written into "
            "its spec; a shipped car's spec holds a key (``CAR_NAME_LFA``) into "
            "gametext.txt and the twelve text_<lang>.txt files instead, and "
            "changing it here rewrites that text entry in every language while "
            "the key itself stays put.")
        form.addRow("Display key", self.display_key)
        self.model_token = QLineEdit()
        self.model_token.setPlaceholderText(
            "empty: derived from the folder name, or kept as it is")
        self.model_token.setToolTip(
            "The model name written into the spec - the game's own internal name "
            "for the car, and what a car with no display name of its own is "
            "called.  The folder name gives it for free on a new build; on an "
            "installed car it is shown as it is and only a changed value is "
            "written.")
        form.addRow("Model token", self.model_token)
        # ---- what it is called ----------------------------------------
        #
        # The display key, the model token and the make all work on both
        # branches, because a car that is already installed can be renamed and
        # re-branded: the display name is a text-table key, the model is the
        # spec's own string, and the brand is a string in the spec (plus the
        # manufacturer key 502 specs carry).  For a new car they are the answers
        # the build uses; for an installed one they are prefilled from the car
        # and only what differs is written.
        self.make = QComboBox()
        self.make.setEditable(True)
        self.make.setInsertPolicy(QComboBox.NoInsert)
        self.make.setToolTip(
            "The manufacturer, as a string in the spec. Pick one the game ships "
            "or type a new one - a brand needs no record anywhere else. The "
            "Brands tab is where its logo goes.")
        form.addRow("Make", self.make)
        self.aero = QComboBox()
        for label, _kind in AERO_ITEMS:
            self.aero.addItem(label)
        self.aero.setToolTip(
            "What the active aero does, when the car has any. A car without this "
            "never plays its _wing.banim however good the curves are, so adding a "
            "wing to a car the studio left out needs the flag as well.")
        form.addRow("Active aero", self.aero)
        aero_row = QHBoxLayout()
        self.aero_high = QSpinBox()
        self.aero_high.setRange(0, 600)
        self.aero_high.setValue(180)
        self.aero_high.setSuffix(" km/h")
        self.aero_high.setToolTip("The speed the wing flattens at")
        self.aero_low = QSpinBox()
        self.aero_low.setRange(0, 600)
        self.aero_low.setValue(170)
        self.aero_low.setSuffix(" km/h")
        self.aero_low.setToolTip("The speed it comes back at")
        aero_row.addWidget(QLabel("at"))
        aero_row.addWidget(self.aero_high)
        aero_row.addWidget(QLabel("back at"))
        aero_row.addWidget(self.aero_low)
        aero_row.addStretch(1)
        form.addRow("Speeds", aero_row)
        self.aero.currentIndexChanged.connect(self._aero_changed)
        self.aero_high.setEnabled(False)
        self.aero_low.setEnabled(False)
        self.aliases = QCheckBox(
            "Also write the donor's file names next to the new ones")
        self.aliases.setChecked(True)
        self.aliases.setToolTip(
            "Some builds look a car's files up under the old name; keeping both "
            "costs disk space and makes the car load either way")
        form.addRow("", self.aliases)
        inner.addLayout(form)

        # ---- the wheels ----------------------------------------------
        inner.addWidget(W.heading("3. Its wheels", 2))
        self.wheel_note = W.muted(
            "Type one number per axle: how much bigger than the exported mesh "
            "the wheel should be drawn. The mesh supplies the proportions (and "
            "the rim/tyre ratio, so no ring of daylight opens up); the "
            "appearance record is written for you. Export the wheel normalised "
            "to the shared template and one model serves both axles - the "
            "front and rear only differ in the number you type here.")
        self.wheel_note.setWordWrap(True)
        inner.addWidget(self.wheel_note)

        wheel_form = QFormLayout()
        wheel_form.setContentsMargins(18, 4, 0, 0)
        self.wheel_front = QDoubleSpinBox()
        self.wheel_rear = QDoubleSpinBox()
        for box, label in ((self.wheel_front, "Front scale"),
                           (self.wheel_rear, "Rear scale")):
            box.setRange(0.0, 3.0)
            box.setDecimals(3)
            box.setSingleStep(0.005)
            box.setSuffix(" x")
            box.setSpecialValueText("donor's")
            box.setToolTip(
                "How much bigger than the exported mesh this axle is drawn. "
                "The tyre and the rim are both multiplied by it, so the ring "
                "of daylight between them keeps the model's own proportions. "
                "The record gets the square root of this number, because the "
                "engine draws the mesh at record²/mesh. "
                "0.000 keeps whatever the donor record says.")
            box.valueChanged.connect(self._wheel_changed)
        wheel_form.addRow("Front scale", self.wheel_front)
        wheel_form.addRow("Rear scale", self.wheel_rear)
        inner.addLayout(wheel_form)

        wheel_row = QHBoxLayout()
        wheel_row.setContentsMargins(18, 0, 0, 0)
        wheel_row.addWidget(W.button(
            "From the wheel points", self._wheels_from_points,
            tip="Take the scale from POINT_WHEEL_* in the exported .points - "
                "the hub height is the tyre radius when the wheel sits on the "
                "ground. This is the scale that made our own car sit right."))
        wheel_row.addWidget(W.button(
            "Match the mesh (1:1)", self._wheels_from_mesh,
            tip="Draw the wheel at exactly the size it was modelled at"))
        wheel_row.addStretch(1)
        inner.addLayout(wheel_row)

        self.wheel_info = W.muted("No exported folder yet.")
        self.wheel_info.setWordWrap(True)
        inner.addWidget(self.wheel_info)
        #: (tyre radius, rim radius, bore) of the folder's shared model
        self._mesh_measure: tuple | None = None

        # ---- the numbers ---------------------------------------------
        inner.addWidget(W.heading("4. What it drives like", 2))
        self.tune_box = QCheckBox("Also change what it drives like")
        self.tune_box.setToolTip(
            "A new car gets its own figures whether or not you tick this. When "
            "modifying a car that is already installed the numbers are left "
            "alone unless you ask, because a spec edit is easy to make and hard "
            "to notice afterwards.")
        self.tune_box.toggled.connect(self._tune_changed)
        inner.addWidget(self.tune_box)
        self.stats_note = W.muted(
            "These come from the donor's spec file. Change any of them to give "
            "the new car its own figures; leave a cell empty to keep the donor's.")
        self.stats_note.setWordWrap(True)
        inner.addWidget(self.stats_note)
        self.stats = QTableWidget(0, 4)
        self.stats.setHorizontalHeaderLabels(("Stat", "Donor", "New car", "Unit"))
        self.stats.verticalHeader().setVisible(False)
        # Every column is draggable.  Two of them used to be sized to their
        # contents, which makes a column impossible to widen - and the labels
        # here are long enough to want it.
        head = self.stats.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setStretchLastSection(False)
        for column, width in enumerate((190, 110, 150, 60)):
            self.stats.setColumnWidth(column, width)
        self.stats.setMaximumHeight(210)
        inner.addWidget(self.stats)

        # ---- the engine sound ----------------------------------------
        sound_row = QHBoxLayout()
        sound_row.addWidget(QLabel("Engine sound"))
        self.sound = QComboBox()
        self.sound.setMinimumWidth(200)
        self.sound.setToolTip(
            "Which audio folder the game plays for this car. The three file "
            "names are rebuilt from the car's own id, so a car keeps its own "
            "take if the family ships one.")
        sound_row.addWidget(self.sound)
        self.sound_note = W.muted("")
        sound_row.addWidget(self.sound_note, 1)
        inner.addLayout(sound_row)

        # ---- the upgrade route ---------------------------------------
        route_row = QHBoxLayout()
        route_row.addWidget(QLabel("Upgrade route"))
        self.route = QComboBox()
        self.route.setMinimumWidth(200)
        self.route.setToolTip(
            "Which tuning tree the car gets. The ten PROD/SUPER/RACE blocks are "
            "the game's own templates; the rest are trees a shipped car or a "
            "racing class already uses. Only the name is written - the tree "
            "itself lives in carupgrade.upgrades.nct and is never edited.")
        route_row.addWidget(self.route)
        self.route_note = W.muted("")
        route_row.addWidget(self.route_note, 1)
        inner.addLayout(route_row)

        # ---- what it is, and what it costs ----------------------------
        #
        # These five live at the tail of the spec, after the engine block and
        # the two variable-length strings that follow it.  They are not table
        # rows like the figures above: two are words from a closed list and two
        # are money, so each gets the control its own type deserves.
        self.tail_note = W.muted(
            "How the showroom lists the car. The aspiration and the layout are "
            "the two words the game filters on, so only its own values are "
            "offered; the unlock rule is what a player has to do before it can be "
            "bought, and the two prices are what it costs.")
        self.tail_note.setWordWrap(True)
        inner.addWidget(self.tail_note)
        tail_form = QFormLayout()
        tail_form.setContentsMargins(0, 0, 0, 0)
        self.aspiration = QComboBox()
        self.aspiration.setToolTip(
            "The induction word the game shows and filters on. Only the six the "
            "game knows are listed: an unknown word hides the whole engine block "
            "from every reader, because that block is found by this word.")
        tail_form.addRow(QLabel("Aspiration"), self.aspiration)
        self.layout = QComboBox()
        self.layout.setToolTip(
            "Which wheels are driven: F, M, R or FM. Same rule as the aspiration "
            "- the engine block is found by the word after it.")
        tail_form.addRow(QLabel("Layout"), self.layout)
        self.unlock = QLineEdit()
        self.unlock.setPlaceholderText("leave empty for a car with no rule")
        self.unlock.setToolTip(
            "NOTLOCKED, or ROUND:... / QUEST:... / LTS:... / PRIZEONLY:... to "
            "gate the car behind something. Empty means no rule at all, which is "
            "what 160 shipped cars do.")
        tail_form.addRow(QLabel("Unlock rule"), self.unlock)
        money_row = QHBoxLayout()
        self.cash = QSpinBox()
        self.cash.setRange(0, 2_000_000_000)
        self.cash.setSingleStep(5000)
        self.cash.setGroupSeparatorShown(True)
        self.cash.setToolTip(
            "The price in R$. Zero means it cannot be bought with cash; the gold "
            "price is then the only way in.")
        money_row.addWidget(self.cash, 1)
        money_row.addWidget(QLabel("R$"))
        money_row.addSpacing(12)
        self.gold = QSpinBox()
        self.gold.setRange(0, 100_000)
        self.gold.setSingleStep(5)
        self.gold.setGroupSeparatorShown(True)
        self.gold.setToolTip(
            "The price in gold. Zero means it cannot be bought with gold.")
        money_row.addWidget(self.gold, 1)
        money_row.addWidget(QLabel("gold"))
        tail_form.addRow(QLabel("Price"), money_row)
        inner.addLayout(tail_form)

        # ---- the paints ----------------------------------------------
        inner.addWidget(W.heading("4. Which paints it comes with", 2))
        self.paints_note = W.muted(
            "A new car starts with every paint scheme the donor has. Untick the "
            "ones it should not come with; the order is the order the game shows "
            "them in, so unticking from the end is the usual choice.")
        self.paints_note.setWordWrap(True)
        inner.addWidget(self.paints_note)
        self.paints = QTableWidget(0, 6)
        self.paints.setHorizontalHeaderLabels(
            ("Keep", "Paint scheme", "Colour", "Finish", "Atlas", ""))
        self.paints.verticalHeader().setVisible(False)
        self.paints.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.paints.setSelectionMode(QAbstractItemView.ExtendedSelection)
        head = self.paints.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Interactive)
        head.setStretchLastSection(False)
        head.setSectionResizeMode(5, QHeaderView.Fixed)
        for column, width in enumerate((50, 240, 90, 170, 210, 34)):
            self.paints.setColumnWidth(column, width)
        self.paints.setMaximumHeight(170)
        self.paints.itemChanged.connect(self._paint_edited)
        inner.addWidget(self.paints)

        paint_row = QHBoxLayout()
        self.add_paint_btn = W.button(
            "Add a scheme...", self._add_paint, primary=True,
            tip="Copy a scheme into a new paint preset and give it its own body "
                "atlas - the same thing the Cars page's paint section does")
        paint_row.addWidget(self.add_paint_btn)
        self.del_paint_btn = W.button(
            "Delete scheme(s)...", self._remove_paints,
            tip="Remove the selected schemes. A car needs at least one, so the "
                "last one is refused")
        paint_row.addWidget(self.del_paint_btn)
        paint_row.addStretch(1)
        inner.addLayout(paint_row)

        finish_row = QHBoxLayout()
        finish_row.addWidget(QLabel("Finish for all of them"))
        self.finish = QComboBox()
        self.finish.setToolTip(
            "Only the finishes the game's own customiser offers: gloss, matte, "
            "metallic, chrome, gold and candy. Nothing else in the material "
            "library is a car paint, whatever its name suggests.")
        finish_row.addWidget(self.finish, 1)
        finish_row.addWidget(W.button(
            "Apply to all", self._apply_finish,
            tip="Point every scheme's body and wing at this finish"))
        finish_row.addWidget(W.button(
            "Pick a colour...", self._pick_colour,
            tip="The colour the customiser starts this scheme from"))
        finish_row.addWidget(W.button(
            "Reset colours", self._reset_colours,
            tip="Go back to the colours the donor shipped with"))
        inner.addLayout(finish_row)

        self.finish_note = W.muted(
            "The ... button on a row opens every picture that scheme loads - the "
            "body and any page it overrides - so a scheme's atlas, wheels and "
            "badges are all set in one place. A picture is converted when you "
            "press Build.")
        self.finish_note.setWordWrap(True)
        inner.addWidget(self.finish_note)

        # ---- the aero clips ------------------------------------------
        inner.addWidget(W.heading("5. When the wing moves", 2))
        self.clips_note = W.muted(
            "The game looks clips up by name and plays a frame range of the "
            "animation. A car with an active wing needs at least wing_initial; "
            "the rest are the transitions. Leave the table empty to keep the "
            "donor's file, or write one from scratch here.")
        self.clips_note.setWordWrap(True)
        inner.addWidget(self.clips_note)
        self.clips_table = QTableWidget(0, 4)
        self.clips_table.setHorizontalHeaderLabels(
            ("Clip", "Start", "End", "Note"))
        self.clips_table.verticalHeader().setVisible(False)
        self.clips_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.clips_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        self.clips_table.setMaximumHeight(150)
        self.clips_table.itemChanged.connect(self._clip_edited)
        inner.addWidget(self.clips_table)

        clip_row = QHBoxLayout()
        clip_row.addWidget(QLabel("Add"))
        self.clip_name = QComboBox()
        self.clip_name.setEditable(True)
        self.clip_name.addItems(list(animlib.animxmllib.CLIP_ORDER))
        self.clip_name.setToolTip("The names the game asks for")
        clip_row.addWidget(self.clip_name, 1)
        self.clip_start = QSpinBox()
        self.clip_start.setRange(0, 100000)
        clip_row.addWidget(self.clip_start)
        clip_row.addWidget(QLabel("to"))
        self.clip_end = QSpinBox()
        self.clip_end.setRange(0, 100000)
        clip_row.addWidget(self.clip_end)
        self.add_clip_btn = W.button("Add clip", self._add_clip)
        clip_row.addWidget(self.add_clip_btn)
        self.del_clip_btn = W.button("Remove", self._remove_clip,
                                     tip="Drop the selected clip")
        clip_row.addWidget(self.del_clip_btn)
        self.suggest_clip_btn = W.button(
            "Use a default set", self._default_clips,
            tip="Rest, up and down over the whole animation")
        clip_row.addWidget(self.suggest_clip_btn)
        inner.addLayout(clip_row)

        # ---- the seated driver ---------------------------------------
        # The pose is not an animation file of the car's: it is a field in the
        # car's data record naming one of the ``driver/driver_<x>.banim`` files
        # the game ships, which is why it is here rather than in the pack.
        driver_row = QHBoxLayout()
        driver_row.addWidget(QLabel("Seated driver"))
        self.driver_pose = QComboBox()
        self.driver_pose.setToolTip(
            "Which driver_<x>.banim the game seats this car with. Only twelve of "
            "the poses have a low-poly model of their own.")
        self.driver_pose.currentIndexChanged.connect(self._driver_changed)
        driver_row.addWidget(self.driver_pose, 1)
        inner.addLayout(driver_row)
        self.driver_note = W.muted("")
        self.driver_note.setWordWrap(True)
        inner.addWidget(self.driver_note)

        # ---- 6. a place in the career --------------------------------
        inner.addWidget(W.heading("6. Where it races", 2))
        self.series_note = W.muted(
            "A new car with no series is a car the game cannot offer you: it "
            "sits in the showroom and nothing runs it. Tick the box to have one "
            "made for it in a menu group of its own, running the same races as "
            "the template. Leave it alone to add the car without touching the "
            "career file.")
        self.series_note.setWordWrap(True)
        inner.addWidget(self.series_note)
        self.series_box = QCheckBox("Make a series for it")
        self.series_box.setToolTip(
            "Writes a new series into data/events.dat.nct. The career file is "
            "checked by reading it back byte for byte before anything is "
            "written, so a mistake here cannot reach the game.")
        inner.addWidget(self.series_box)
        series_form = QFormLayout()
        self.series_title = QLineEdit()
        self.series_title.setPlaceholderText("leave empty to name it after the car")
        series_form.addRow("Series title", self.series_title)
        self.series_template = QComboBox()
        self.series_template.setToolTip(
            "The series whose races are copied. Only career series that already "
            "live in a menu group are offered: their tiers, event types and "
            "requirement curves are the ones the career menu expects.")
        series_form.addRow("Copy races from", self.series_template)
        self.series_group = QComboBox()
        self.series_group.setEditable(True)
        self.series_group.setToolTip(
            "Which menu group the new series goes in. The list is the groups the "
            "career already has; type a new name to have one made.")
        series_form.addRow("Menu group", self.series_group)
        inner.addLayout(series_form)
        self.series_info = W.muted("")
        self.series_info.setWordWrap(True)
        inner.addWidget(self.series_info)

        self.plan = W.muted("")
        self.plan.setWordWrap(True)
        # The plan is a sentence this dialog composes out of the donor's name,
        # an id, a count of files and a dozen other answers, so there is no one
        # English string to translate: marking it keeps generated text out of
        # the translation table, where every different car would be a new entry.
        self.plan.setProperty("rr3_skip_translate", True)
        inner.addWidget(self.plan)
        inner.addStretch(1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Build")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        # The career file is 14 MB and takes seconds to parse, so it is only
        # read once the user asks for a series - most builds do not want one.
        self._career = None
        self._career_texts = None
        self._series_task = None
        self.series_box.toggled.connect(self._series_changed)

        self._fill_cars()
        self._fill_finishes()
        self._branch_changed()
        self._refresh_slots()          # the slot table is shown before a folder is
        self.new_id.setEnabled(not self.auto_id.isChecked())
        self.donor.currentTextChanged.connect(self._fill_stats)
        # a donor change also moves the make, unless the user has typed one
        self.donor.currentTextChanged.connect(self._donor_changed)
        # the texture table follows whichever car it is about, and the name a
        # new car will carry is what the files become
        self.donor.currentTextChanged.connect(self._fill_textures)
        self.car.currentTextChanged.connect(self._fill_textures)
        self.new_name.textChanged.connect(self._fill_textures)
        # in the modify branch the car itself is the source of the figures and
        # the clips, so both have to follow it
        self.car.currentTextChanged.connect(self._fill_stats)
        self.car.currentTextChanged.connect(self._fill_clips)
        self.car.currentTextChanged.connect(self._fill_identity)
        # the paint table follows whichever car it is about, and the queues it
        # holds name that car's schemes - so a change of car clears them
        self.donor.currentTextChanged.connect(self._paint_source_changed)
        self.car.currentTextChanged.connect(self._paint_source_changed)
        self.branch_modify.toggled.connect(self._fill_identity)
        # the connections were made after the first fill, so the boxes start
        # empty unless this runs once here
        self._fill_identity()

    def _paint_source_changed(self) -> None:
        """The car the paint table is about changed: drop what was queued.

        A queued scheme names a row of one particular car's livery table, so it
        cannot be carried across to another car - the index would land on a
        different scheme, or on none.
        """
        self._paint_adds = []
        self._paint_removes = []
        #: ``{livery index: {slot key: picture}}`` - pictures chosen per scheme.
        #: Keyed by the scheme's index in the table it was read from, not by the
        #: table row: the row moves when a scheme above it is unticked, and the
        #: index is what the build's own translation map speaks.
        self._paint_pictures: dict = {}
        self._fill_paints()
        self._update_plan()

    def _edit_paint_textures(self, row_index: int) -> None:
        """Open the picture table of one scheme, queued or already installed."""
        if not (0 <= row_index < len(self._shown_paints)):
            return
        row = self._shown_paints[row_index]
        car = self._paint_car()
        if not car:
            return
        if row["kind"] == "add":
            current = dict(row.get("pictures") or {})
            tag = row.get("tag") or texlib.colour_word(row["rgb"])
        else:
            try:
                current = paintui.effective_pictures(self.inv.depot, car,
                                                     row["index"])
            except Exception as exc:             # noqa: BLE001
                QMessageBox.critical(self, "The pictures of a paint scheme",
                                     str(exc))
                return
            current.update(self._paint_pictures.get(row["index"]) or {})
            tag = texlib.colour_word(row["rgb"])
        dlg = paintui.TextureSlotsDialog(
            self, self.inv.depot, car, current,
            pictures=self.livery_pictures(), tag=tag,
            title=f"{row['name']} - what it loads")
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = dlg.values()
        if not chosen:
            return
        if row["kind"] == "add":
            for add in self._paint_adds:
                if add["name"] == row["name"]:
                    add.setdefault("pictures", {}).update(chosen)
                    if chosen.get("body"):
                        add["atlas"] = chosen["body"]
                    break
        else:
            self._paint_pictures.setdefault(row["index"], {}).update(chosen)
        self._fill_paints()
        self._update_plan()

    def _fill_identity(self) -> None:
        """Show the display name, model token and make the car already has.

        The boxes are prefilled rather than empty so that a build that changes
        none of them writes none of them - ``set_identity`` compares before it
        touches anything - and so that the three are visible before they are
        edited.  A new car has none of them yet (its folder name gives the
        display key and the model token), so the boxes start empty and the make
        follows the donor.
        """
        if self.branch_new.isChecked():
            self.display_key.clear()
            self.model_token.clear()
            return
        car = self.car.currentText().strip()
        entry = next((e for e in self.inv.cars if e.name == car), None)
        if entry is None:
            return
        # The display name is what the game shows, not the key behind it: a
        # shipped car's spec holds ``CAR_NAME_LFA`` and the showroom shows the
        # text that key points at, and it is that text the box is for.
        self.display_key.setText(getattr(entry, "display_name", "") or "")
        self.model_token.setText(entry.model or "")
        if entry.make:
            self.make.setCurrentText(entry.make)
        self._update_plan()

    # ---- filling ------------------------------------------------------
    def _with_picker(self, combo: QComboBox, multiple: bool) -> QWidget:
        """Wrap a name combo in a row with a button that opens the car picker."""
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(combo, 1)
        row.addWidget(W.button(
            "Pick...", lambda: self._pick_into(combo, multiple),
            tip="Choose by manufacturer, with pictures"))
        return wrap

    def _pick_into(self, combo: QComboBox, multiple: bool) -> None:
        from . import picker

        try:
            dlg = picker.CarPickerDialog(self.inv, self, multiple=multiple)
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.critical(self, "Pick a car", str(exc))
            return
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = dlg.chosen()
        if not chosen:
            return
        names = []
        for car_id in chosen:
            entry = next((e for e in self.inv.cars if e.car_id == car_id), None)
            if entry is not None:
                names.append(entry.name)
        if names:
            combo.setCurrentText(names[0])

    def _fill_cars(self) -> None:
        names = [e.name for e in self.inv.cars if e.has_body]
        for combo in (self.car, self.donor):
            combo.clear()
            combo.addItems(names)
        self._fill_makes()

    def _fill_makes(self) -> None:
        """Every make the install ships, plus any brand of our own."""
        current = self.make.currentText().strip()
        makes = []
        for entry in self.inv.cars:
            make = (entry.make or "").strip()
            if make and make not in makes:
                makes.append(make)
        for name in sorted(depotlib.brand_names(self.inv.depot)):
            if name not in makes:
                makes.append(name)
        makes.sort(key=lambda m: m.lower())
        self.make.clear()
        for make in makes:
            self.make.addItem(make, make)
        if current:
            self.make.setCurrentText(current)
        elif self.donor.currentText().strip():
            self.make.setCurrentText(self._donor_make())

    def _donor_changed(self) -> None:
        """Follow the donor's make, but only while the box still matches it.

        Typing a brand of your own and then picking a donor is the normal way to
        make "the first car of a new brand"; overwriting what was typed would
        make that impossible.
        """
        if not self.branch_new.isChecked():
            return
        typed = self.make.currentText().strip()
        if not typed or typed in self._donor_makes():
            wanted = self._donor_make()
            if wanted:
                self.make.setCurrentText(wanted)

    def _donor_makes(self) -> list:
        return [self.make.itemText(i) for i in range(self.make.count())]

    # ---- the numbers --------------------------------------------------
    def _donor_make(self) -> str:
        donor = self.donor.currentText().strip()
        if not donor:
            return ""
        for entry in self.inv.cars:
            if entry.name == donor:
                return (entry.make or "").strip()
        return ""

    def _stat_source(self) -> str:
        """Whose figures to show: the donor when cloning, the car when editing."""
        if self.branch_new.isChecked():
            return self.donor.currentText().strip()
        return self.car.currentText().strip()

    def _fill_stats(self) -> None:
        """Show the figures, with an empty column to override them."""
        source = self._stat_source()
        rows = list(statlib.ALL_FIELDS)
        self.stats.setRowCount(len(rows))
        values = {}
        if source:
            try:
                values = statlib.read(self.inv.root, source)["fields"]
            except Exception:                     # noqa: BLE001
                values = {}
        #: the source car's own figures, so a word box can tell "changed" from
        #: "still what the donor had" without reading the spec twice
        self._stat_values = values
        self._word_boxes = {}
        for i, (key, label, unit) in enumerate(rows):
            self.stats.setItem(i, 0, QTableWidgetItem(label))
            got = values.get(key, {}).get("value")
            writable = values.get(key, {}).get("writable", False)
            if got is None:
                shown = ""
            elif isinstance(got, str):
                # the class and the drivetrain are words, not numbers
                shown = got
            else:
                shown = _NUMBER_FORMAT.get(key, "{:.2f}").format(got)
            donor_cell = QTableWidgetItem(shown)
            donor_cell.setFlags(Qt.ItemIsEnabled)
            note = _FIELD_NOTES.get(key)
            if note:
                donor_cell.setToolTip(note)
            elif not writable:
                donor_cell.setToolTip("shown for reference; this one cannot be written")
            self.stats.setItem(i, 1, donor_cell)
            if key in statlib.WORD_KEYS:
                self.stats.setCellWidget(i, 2, self._word_box(key, got))
            else:
                override = QTableWidgetItem("")
                if not writable:
                    override.setFlags(Qt.ItemIsEnabled)
                    override.setToolTip("shown for reference; this one cannot be written")
                elif note:
                    override.setToolTip(note)
                self.stats.setItem(i, 2, override)
            unit_cell = QTableWidgetItem(unit)
            unit_cell.setFlags(Qt.ItemIsEnabled)
            self.stats.setItem(i, 3, unit_cell)
        if not source:
            self.stats_note.setText(
                "Pick a car to see what it drives like; a new car starts with "
                "the donor's figures.")
        self._tune_changed()
        self._fill_paints()
        self._fill_clips()
        self._fill_driver()
        self._fill_sound()
        self._fill_route()
        self._fill_tail()

    def _word_box(self, key: str, current) -> QComboBox:
        """A dropdown for a field that is a word rather than a number.

        The class and the drivetrain are the two things on this table that used
        to be "shown for reference" - and a car whose drivetrain is wrong drives
        wrong, so they are the two a builder actually wants to change.  Only the
        words the game ships are offered; a spec holding something else shows it
        with a note rather than being silently replaced.
        """
        box = QComboBox()
        words = statlib.classes() if key == "car_class" else statlib.drivetrains()
        for word in words:
            box.addItem(word, word)
        word = str(current or "")
        at = box.findData(word)
        if at < 0 and word:
            box.addItem(f"{word}  (not one the game knows)", word)
            at = box.count() - 1
        if at >= 0:
            box.setCurrentIndex(at)
        box.setToolTip(
            "The class the game files it under" if key == "car_class"
            else "Which wheels are driven. RWD, AWD, FWD - or RLY, which the "
                 "three rally cars use for their own handling model.")
        box.currentIndexChanged.connect(lambda _i: self._update_plan())
        # remembered so ``stat_changes`` can read what each word box holds
        self._word_boxes[key] = box
        return box

    def _tune_on(self) -> bool:
        """Whether the figures column is allowed to change anything.

        A new car always takes its own numbers.  A car that is already installed
        only does so when the box is ticked: the spec is one file with a dozen
        unrelated fields in it and a changed figure is invisible afterwards.
        """
        return self.branch_new.isChecked() or self.tune_box.isChecked()

    def _tune_changed(self) -> None:
        on = self._tune_on()
        editable = self.branch_new.isChecked()
        self.stats.setEnabled(on)
        self.stats_note.setEnabled(on)
        self.sound.setEnabled(on)
        self.sound_note.setEnabled(on)
        self.route.setEnabled(on)
        self.route_note.setEnabled(on)
        for widget in (self.aspiration, self.layout, self.unlock, self.cash,
                       self.gold, self.tail_note):
            widget.setEnabled(on)
        self.tune_box.setEnabled(not editable)
        if editable:
            self.tune_box.setChecked(True)
        self._update_plan()

    # ---- the engine sound ---------------------------------------------
    def _sound_source(self) -> str:
        """Whose sound to show: the donor when cloning, the car when editing."""
        return self._stat_source()

    def _fill_sound(self) -> None:
        """List the audio families, with the current one selected."""
        source = self._sound_source()
        self.sound.blockSignals(True)
        self.sound.clear()
        try:
            got = statlib.sound(self.inv.root, source) if source else {
                "families": statlib.families(self.inv.root), "family": ""}
        except Exception:                         # noqa: BLE001
            got = {"families": [], "family": ""}
        for name in got.get("families") or []:
            self.sound.addItem(name, name)
        current = got.get("family") or ""
        if current:
            at = self.sound.findData(current)
            if at < 0:
                self.sound.addItem(current, current)
                at = self.sound.count() - 1
            self.sound.setCurrentIndex(at)
        self.sound.blockSignals(False)
        if not current and source:
            self.sound_note.setText(
                "This car has no engine sound fields, so there is nothing to point "
                "at another family.")
        else:
            self.sound_note.setText("")
        self._update_plan()

    def sound_family(self) -> str:
        """The family the user picked, or "" to leave the donor's alone."""
        if not self._tune_on():
            return ""
        return self.sound.currentData() or ""

    # ---- the upgrade route ---------------------------------------------
    def _fill_route(self) -> None:
        """List the upgrade routes, with the source car's own one selected.

        Templates first, because they are the ones worth copying; a car that
        follows a class tree (``2022_FORMULA_1``) can still be shown as itself.
        """
        source = self._stat_source()
        self.route.blockSignals(True)
        self.route.clear()
        try:
            got = statlib.route(self.inv.root, source) if source else {
                "routes": [], "key": ""}
        except Exception:                         # noqa: BLE001
            got = {"routes": [], "key": ""}
        rows = got.get("routes") or []
        for row in rows:
            label = row["name"]
            if row.get("template"):
                label = f"{label}  ({row['areas']} areas, {row['steps']} steps)"
            self.route.addItem(label, row["name"])
        current = got.get("key") or ""
        if current:
            at = self.route.findData(current)
            if at < 0:
                self.route.addItem(f"{current}  (not in this install)", current)
                at = self.route.count() - 1
            self.route.setCurrentIndex(at)
        self.route.blockSignals(False)
        if not rows:
            self.route_note.setText(
                "This install has no carupgrade.upgrades.nct, so there is nothing "
                "to point the car at.")
        elif not current and source:
            self.route_note.setText(
                "This car follows no upgrade route; pick one to give it a tuning "
                "tree.")
        else:
            self.route_note.setText("")
        self._update_plan()

    def route_key(self) -> str:
        """The route the user picked, or "" to leave the source car's alone."""
        if not self._tune_on():
            return ""
        return self.route.currentData() or ""

    # ---- what it is, and what it costs ----------------------------------
    def _fill_tail(self) -> None:
        """Show the source car's words and prices in the controls.

        The boxes start at the source car's own values rather than at zero, so a
        build that changes nothing writes nothing: every setter in the spec
        compares before it splices, and the whole batch comes back unchanged.
        """
        source = self._stat_source()
        got = {}
        if source:
            try:
                got = statlib.tail(self.inv.root, source)
            except Exception:                     # noqa: BLE001
                got = {}
        for box, key, words in ((self.aspiration, "aspiration", got.get("aspirations")),
                                (self.layout, "layout", got.get("layouts"))):
            box.blockSignals(True)
            box.clear()
            for word in words or ():
                box.addItem(word, word)
            current = got.get(key) or ""
            if current:
                at = box.findData(current)
                if at < 0:
                    box.addItem(f"{current}  (not one the game knows)", current)
                    at = box.count() - 1
                box.setCurrentIndex(at)
            box.blockSignals(False)
        self.unlock.setText(got.get("unlock") or "")
        self.cash.blockSignals(True)
        self.gold.blockSignals(True)
        self.cash.setValue(int(got.get("cash") or 0))
        self.gold.setValue(int(got.get("gold") or 0))
        self.cash.blockSignals(False)
        self.gold.blockSignals(False)
        if not source:
            self.tail_note.setText(
                "Pick a car to see how the showroom lists it; a new car starts "
                "with the donor's words and prices.")
        elif got.get("extra"):
            # only the eight R3 specials carry this, and it is not writable here
            self.tail_note.setText(
                f"This car also carries {got['extra']} in its spec, which is left "
                "as it is.")
        self._update_plan()

    def tail_changes(self) -> dict:
        """Whatever differs from the source car, as ``set_tail`` keyword names.

        Only the differences are returned: a build that touches none of these
        controls hands back an empty dict, and the caller then writes nothing.
        """
        if not self._tune_on():
            return {}
        source = self._stat_source()
        if not source:
            return {}
        try:
            got = statlib.tail(self.inv.root, source)
        except Exception:                         # noqa: BLE001
            return {}
        out = {}
        aspiration = self.aspiration.currentData() or ""
        if aspiration and aspiration != (got.get("aspiration") or ""):
            out["aspiration"] = aspiration
        layout = self.layout.currentData() or ""
        if layout and layout != (got.get("layout") or ""):
            out["layout"] = layout
        unlock = self.unlock.text().strip()
        if unlock != (got.get("unlock") or ""):
            out["unlock"] = unlock
        if self.cash.value() != int(got.get("cash") or 0):
            out["cash"] = self.cash.value()
        if self.gold.value() != int(got.get("gold") or 0):
            out["gold"] = self.gold.value()
        return out

    # ---- where it races -----------------------------------------------
    def _series_changed(self) -> None:
        """Enable the form, and read the career the first time it is wanted."""
        on = self.series_box.isChecked()
        for widget in (self.series_title, self.series_template, self.series_group,
                       self.series_info):
            widget.setEnabled(on)
        if on and self._career is None and self._series_task is None:
            self._read_career()
        self._update_plan()

    def _read_career(self) -> None:
        """Parse the career file off the UI thread - it is 14 MB."""
        self.series_info.setText("Reading the career file...")
        root = self.inv.root

        def work():
            c = serieslib.load(root)
            t = serieslib.load_texts(root)
            return c, t, serieslib.templates(c), sorted(serieslib.group_keys(c))

        self._series_task = Task(work, parent=self)
        self._series_task.done.connect(self._career_loaded)
        self._series_task.fail.connect(self._career_failed)
        self._series_task.start()

    def _career_loaded(self, payload) -> None:
        self._series_task = None
        self._career, self._career_texts, rows, groups = payload
        self.series_template.clear()
        for row in rows[:200]:
            label = (f"{row['id']}  {row['key']}  ({row['tiers']} tier(s), "
                     f"{row['events']} event(s)")
            if row["group_key"]:
                label += f", {row['group_key']}"
            label += ")"
            self.series_template.addItem(label, row["id"])
        self.series_group.clear()
        for key in groups:
            self.series_group.addItem(key, key)
        self.series_info.setText(
            f"{len(rows)} series can be copied from, in {len(groups)} menu "
            f"groups. The new series gets the template's races and only the new "
            f"car on the grid.")
        self._update_plan()

    def _career_failed(self, text: str) -> None:
        self._series_task = None
        self.series_info.setText(f"The career file could not be read: {text[:200]}")
        self.series_box.setChecked(False)

    def series_placement(self) -> dict:
        """What to place, or ``{}`` when the box is unticked."""
        if not self.series_box.isChecked():
            return {}
        return {
            "title": self.series_title.text().strip(),
            "template": self.series_template.currentData() or 0,
            "group": self.series_group.currentText().strip(),
        }

    # ---- the paints ---------------------------------------------------
    def _fill_finishes(self) -> None:
        """List the finishes the game's own customiser offers."""
        self.finish.blockSignals(True)
        self.finish.clear()
        self.finish.addItem("leave as it is", "")
        try:
            rows = paintslib.choices(self.inv.depot)
        except Exception as exc:                  # noqa: BLE001
            self.finish_note.setText(f"Could not read the paint table: {exc}")
            rows = []
        for label, material in rows:
            self.finish.addItem(label, material)
        self.finish.blockSignals(False)

    def _apply_finish(self) -> None:
        material = self.finish.currentData() or ""
        if not material:
            return
        rgb = paintslib.starting_colour(self.inv.depot, material)
        self.paints.blockSignals(True)
        for i in range(self.paints.rowCount()):
            swatch = self.paints.item(i, 2)
            if swatch is not None:
                swatch.setText("#%02x%02x%02x" % rgb)
                swatch.setBackground(_colour(rgb))
        self.paints.blockSignals(False)
        self.finish_note.setText(
            f"Every scheme will use {material}, starting from "
            f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}. Pick a colour per scheme "
            f"afterwards if you want them to differ.")
        self._update_plan()

    def _pick_colour(self) -> None:
        rows = self.paints.selectionModel().selectedRows() if \
            self.paints.selectionModel() else []
        index = rows[0].row() if rows else 0
        current = (0, 0, 0)
        swatch = self.paints.item(index, 2)
        if swatch is not None and swatch.text().startswith("#"):
            text = swatch.text().lstrip("#")
            try:
                current = tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                current = (0, 0, 0)
        got = QColorDialog.getColor(_colour(current), self, "Colour")
        if not got.isValid():
            return
        rgb = (got.red(), got.green(), got.blue())
        self.paints.blockSignals(True)
        for row in rows or [self.paints.model().index(index, 2)]:
            item = self.paints.item(row.row() if hasattr(row, "row") else index, 2)
            if item is not None:
                item.setText("#%02x%02x%02x" % rgb)
                item.setBackground(_colour(rgb))
        self.paints.blockSignals(False)
        self._update_plan()

    def _reset_colours(self) -> None:
        self._fill_paints()

    def _paint_edited(self, item) -> None:
        if item.column() != 2:
            return
        text = item.text().strip().lstrip("#")
        try:
            rgb = tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
        except (ValueError, IndexError):
            return
        item.setBackground(_colour(rgb))

    def _final_indexes(self) -> dict:
        """``{table row: index in the livery table the build writes}``.

        The table is not the file.  A new car keeps only the ticked schemes, and
        they are renumbered from zero; a modify build drops the queued deletions
        and the same renumbering happens; the queued additions are appended after
        whatever survives.  Everything the paint controls return is keyed by the
        row the user touched, so it has to be translated before it is written -
        otherwise recolouring row 2 of five after unticking row 0 paints the
        wrong scheme.
        """
        new = self.branch_new.isChecked()
        removing = set(self._paint_removes)
        keep = []
        for i, row in enumerate(self._shown_paints):
            if row["kind"] != "car":
                continue
            if new:
                item = self.paints.item(i, 0)
                if item is not None and item.checkState() != Qt.Checked:
                    continue
            elif row["index"] in removing:
                continue
            keep.append(i)
        out = {row: n for n, row in enumerate(keep)}
        adds = [i for i, row in enumerate(self._shown_paints)
                if row["kind"] == "add"]
        for n, row in enumerate(adds):
            out[row] = len(keep) + n
        return out

    def paint_colours(self) -> dict:
        """``{paint index: (r, g, b)}`` for the schemes whose colour changed."""
        mapping = self._final_indexes()
        out = {}
        for i in range(self.paints.rowCount()):
            if i not in mapping:
                continue
            item = self.paints.item(i, 2)
            if item is None:
                continue
            text = item.text().strip().lstrip("#")
            try:
                rgb = tuple(int(text[j:j + 2], 16) for j in (0, 2, 4))
            except (ValueError, IndexError):
                continue
            if i < len(self._original_colours) and rgb != self._original_colours[i]:
                out[mapping[i]] = rgb
        return out

    # ---- the paints ---------------------------------------------------
    def _paint_car(self) -> str:
        """Whose schemes the paint table is about.

        A new car starts from the donor's schemes; an installed car's paint
        section is about its own, because that is the table the game reads for
        that car - the donor has nothing to do with it.
        """
        if self.branch_new.isChecked():
            return self.donor.currentText().strip()
        return self.car.currentText().strip()

    def _paint_rows(self) -> tuple:
        """``(car, [(row, ...)])`` - the schemes the table should show.

        A row is a dict: ``kind`` is ``"car"`` for a scheme the car already has
        and ``"add"`` for one queued here; ``index`` is the row's index in the
        car's own livery table (``None`` for a queued addition).
        """
        car = self._paint_car()
        if not car:
            return "", []
        L = liverylib.load_car(self.inv.depot, car)
        table = liverylib.load_slot_table(self.inv.depot)
        rows = []
        for i, paint in enumerate(L.paints):
            got = paint.material_of(30)
            if got is None:
                got = L.material_of(30)
            finish_text = ""
            if got is not None:
                try:
                    finish_text = table.name(got)
                except Exception:                 # noqa: BLE001
                    finish_text = ""
            atlas = paint.texture_of(1932)
            rows.append({
                "kind": "car",
                "index": i,
                "name": paint.name(),
                "rgb": tuple(paint.rgb[:3]) if paint.rgb else (0, 0, 0),
                "finish": finish_text,
                "atlas": atlas.decode("utf-8", "replace") if atlas else "",
            })
        # The queued additions are shown in the same table: a scheme that will
        # exist only after Build is still something the user asked for, and
        # hiding it would make the delete button look like it did nothing.
        for add in self._paint_adds:
            rows.append({"kind": "add", "index": None, "name": add["name"],
                         "rgb": add["rgb"], "finish": add["finish"],
                         "atlas": add["atlas"], "removed": False})
        return car, rows

    def _fill_paints(self) -> None:
        """Draw the paint table from the car's own schemes plus the queues.

        New branch: every scheme of the donor, ticked, and unticking one leaves
        it out of the car that gets built.  Modify branch: the installed car's
        own schemes, with the first column reporting what will happen to each -
        ``kept``, ``new``, or ``delete`` - because there is nothing to untick
        there; deleting is a queued edit like everything else in this dialog.
        """
        new = self.branch_new.isChecked()
        # A redraw would otherwise drop the selection, and deleting or
        # recolouring several schemes is several presses on the same rows.
        keep = self._picked_paint_rows()
        self.paints.blockSignals(True)
        self.paints.setRowCount(0)
        self._original_colours = []
        car = self._paint_car()
        if not car:
            self.paints.blockSignals(False)
            self.paints_note.setText(
                "Pick a donor to see the paint schemes the new car would start "
                "with." if new else "Pick a car to see its paint schemes.")
            return
        try:
            car, rows = self._paint_rows()
        except Exception as exc:                  # noqa: BLE001
            self.paints.blockSignals(False)
            self.paints_note.setText(f"Could not read {car}'s paints: {exc}")
            return
        removing = set(self._paint_removes)
        self._shown_paints = rows
        self.paints.setRowCount(len(rows))
        for i, row in enumerate(rows):
            gone = row["kind"] == "car" and row["index"] in removing
            if row["kind"] == "add":
                cell = QTableWidgetItem("new")
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                cell.setToolTip("Queued here - copied in when you press Build.")
                self.paints.setItem(i, 0, cell)
            elif new:
                tick = QTableWidgetItem()
                tick.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                              | Qt.ItemIsSelectable)
                tick.setCheckState(Qt.Unchecked if gone else Qt.Checked)
                self.paints.setItem(i, 0, tick)
            else:
                state = "delete" if gone else "kept"
                cell = QTableWidgetItem(state)
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                cell.setToolTip(
                    "This scheme will be deleted when you press Build - press "
                    "Delete scheme(s) again on it to put it back."
                    if gone else "The car keeps this scheme.")
                self.paints.setItem(i, 0, cell)
            name = QTableWidgetItem(row["name"])
            name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.paints.setItem(i, 1, name)
            rgb = row["rgb"]
            self._original_colours.append(rgb)
            swatch = QTableWidgetItem("#%02x%02x%02x" % rgb)
            swatch.setBackground(_colour(rgb))
            if new:
                swatch.setToolTip("Type a colour or use 'Pick a colour...'")
            else:
                swatch.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                swatch.setToolTip("Change a scheme's colour in the Cars page's "
                                  "paint section")
            self.paints.setItem(i, 2, swatch)
            finish = QTableWidgetItem(row["finish"])
            if new:
                finish.setToolTip(
                    "The car paint this scheme uses. Type a name or pick one "
                    "below; leave it empty to keep the donor's.")
            else:
                finish.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                finish.setToolTip("The car paint this scheme uses")
            self.paints.setItem(i, 3, finish)
            atlas = QTableWidgetItem(row["atlas"])
            atlas.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            atlas.setToolTip("The body picture this scheme draws with")
            self.paints.setItem(i, 4, atlas)
            self.paints.setCellWidget(
                i, 5, paintui._dots(
                    lambda r=i: self._edit_paint_textures(r),
                    "Every picture this scheme loads - the body and any page it "
                    "overrides"))
            if gone:
                # Grey the whole row so a queued deletion reads as one thing.
                grey = _colour((138, 138, 138))
                for column in range(5):
                    cell = self.paints.item(i, column)
                    if cell is not None:
                        cell.setForeground(grey)
        self.paints.blockSignals(False)
        if keep:
            # One select() for the whole set - selectRow() clears the rest, so
            # calling it per row would keep only the last one.
            model = self.paints.model()
            span = QItemSelection()
            for i in keep:
                if 0 <= i < self.paints.rowCount():
                    span.select(model.index(i, 0), model.index(i, 4))
            self.paints.selectionModel().select(
                span, QItemSelectionModel.ClearAndSelect
                | QItemSelectionModel.Rows)
        if new:
            # Static copy on purpose: a sentence with a count in it changes every
            # time the table does, and the translation table is keyed by the
            # whole sentence.  What was added is spelled out in the plan below.
            self.paints_note.setText(
                "Untick the paint schemes the new car should not come with; the "
                "order is the order the game shows them in, so unticking from "
                "the end is the usual choice. Schemes added below are appended "
                "after the ones kept.")
        else:
            self.paints_note.setText(
                "These are the car's own paint schemes, in the order the game "
                "shows them. Add a scheme to copy one into a new preset, or "
                "select one and delete it - a car needs at least one, so the "
                "last one is refused. A row marked delete goes when you press "
                "Build, and pressing the button on it again puts it back.")

    def _picked_paint(self):
        """The selected row of the paint table, or ``None``."""
        model = self.paints.selectionModel() if self.paints.selectionModel() else None
        if model is None:
            return None
        rows = sorted(r.row() for r in model.selectedRows())
        if not rows:
            return None
        return self._shown_paints[rows[0]] if rows[0] < len(self._shown_paints) \
            else None

    def _picked_paint_rows(self) -> list:
        model = self.paints.selectionModel() if self.paints.selectionModel() else None
        if model is None:
            return []
        return sorted(r.row() for r in model.selectedRows())

    def _add_paint(self) -> None:
        """Queue one more scheme, copied from the selected one."""
        new = self.branch_new.isChecked()
        car = self._paint_car()
        if not car:
            QMessageBox.information(
                self, "Add a paint scheme",
                "Pick a donor first." if new else "Pick a car first.")
            return
        picked = self._picked_paint()
        copy_row = next((i for i, row in enumerate(self._shown_paints)
                         if row is picked), None)
        copy_from = picked["index"] if picked and picked["kind"] == "car" else 0
        try:
            L = liverylib.load_car(self.inv.depot, car)
            suggestion = L.next_paint_name()
            source_name = L.paints[copy_from].name() if L.paints else ""
        except Exception as exc:                  # noqa: BLE001
            QMessageBox.critical(self, "Add a paint scheme", str(exc))
            return
        # the paint table's dialogs live with the paint pane
        dlg = paintui.NewPaintDialog(
            self, car, suggestion, copy_from=source_name,
            depot=self.inv.depot, colour=(picked["rgb"] if picked else None),
            pictures=self.livery_pictures())
        if dlg.exec() != QDialog.Accepted:
            return
        livery_name, rgb, pictures, tag = dlg.values()
        if not livery_name:
            QMessageBox.information(self, "Add a paint scheme",
                                    "The new scheme needs a name.")
            return
        if any(add["name"] == livery_name for add in self._paint_adds):
            QMessageBox.information(
                self, "Add a paint scheme",
                f"{livery_name} is already queued for this build.")
            return
        # The colour and finish the copy starts from, so the new row shows what
        # it will look like before anything is written.
        row = picked if picked and picked["kind"] == "car" else None
        self._paint_adds.append({
            "name": livery_name,
            "copy_from": copy_from,
            "copy_row": copy_row,
            "atlas": pictures.get("body", ""),
            "pictures": dict(pictures),
            "tag": tag,
            "rgb": tuple(rgb) if rgb else (row["rgb"] if row else (0, 0, 0)),
            "finish": row["finish"] if row else "",
        })
        self._fill_paints()
        self._update_plan()

    def _remove_paints(self) -> None:
        """Queue schemes for deletion, but never the last one.

        Pressing the button on a row that is already queued puts it back, so a
        deletion is reversible without cancelling the whole build.
        """
        rows = self._picked_paint_rows()
        if not rows:
            QMessageBox.information(
                self, "Delete paint schemes",
                "Select a paint scheme in the table first - Ctrl+click to take "
                "several.")
            return
        shown = [self._shown_paints[i] for i in rows
                 if i < len(self._shown_paints)]
        # A queued addition is dropped from the queue; it never existed on disk,
        # so there is nothing to delete and nothing to be careful about.
        adds = [r for r in shown if r["kind"] == "add"]
        if adds:
            names = {r["name"] for r in adds}
            self._paint_adds = [a for a in self._paint_adds
                                if a["name"] not in names]
            self._fill_paints()
            self._update_plan()
            return
        existing = [r["index"] for r in shown if r["kind"] == "car"]
        if not existing:
            return
        car = self._paint_car()
        total = len(self._shown_paints)
        queued = set(self._paint_removes)
        putting_back = [i for i in existing if i in queued]
        if putting_back:
            self._paint_removes = [i for i in self._paint_removes
                                   if i not in set(putting_back)]
            self._fill_paints()
            self._update_plan()
            return
        if len(queued | set(existing)) >= total:
            QMessageBox.warning(
                self, "Delete paint schemes",
                f"{car} has {total} paint scheme(s) and all of them would be "
                "deleted.\n\nA car needs at least one - with none it comes out "
                "of the showroom unpainted - so nothing was queued. Leave one "
                "out and try again.")
            return
        names = [self._shown_paints[i]["name"] for i in existing]
        preview = "\n".join("  " + n for n in names[:8])
        if len(names) > 8:
            preview += f"\n  ... and {len(names) - 8} more"
        ok = QMessageBox.question(
            self, "Delete paint schemes",
            f"Delete {len(names)} paint scheme(s) from {car}?\n\n{preview}\n\n"
            f"{total - len(queued) - len(existing)} would be left. Nothing is "
            "written until you press Build, and the body atlases they point at "
            "stay on disk.")
        if ok != QMessageBox.Yes:
            return
        self._paint_removes = sorted(queued | set(existing))
        self._fill_paints()
        self._update_plan()

    def paint_adds(self) -> list:
        """The schemes to add after the build, in the order they were queued.

        ``copy_from`` is the index in the livery table the build leaves behind,
        not the row the user copied: a scheme added to a car that just lost two
        of its own has to be copied from the row that is actually there.
        """
        mapping = self._final_indexes()
        out = []
        for add in self._paint_adds:
            source = add.get("copy_from", 0)
            if add.get("copy_row") is not None:
                # ``0`` when the scheme it was copied from is not going into the
                # car at all - there is always a first kept scheme to copy.
                source = mapping.get(add["copy_row"], 0)
            out.append({"name": add["name"], "copy_from": source,
                        "atlas": add.get("atlas", ""),
                        "pictures": dict(add.get("pictures") or {}),
                        "tag": add.get("tag", "")})
        return out

    def paint_pictures(self) -> dict:
        """``{index the build writes: {slot key: picture}}``.

        A picture chosen for a scheme that the build does not keep is dropped,
        and one chosen for a scheme above a deletion moves down with it - which
        is exactly what :meth:`_final_indexes` is for.
        """
        mapping = self._final_indexes()
        by_index = {}
        for row, final in mapping.items():
            if row >= len(self._shown_paints):
                continue
            info = self._shown_paints[row]
            if info["kind"] != "car":
                continue
            chosen = self._paint_pictures.get(info["index"])
            if chosen:
                by_index[final] = dict(chosen)
        return by_index

    def paint_removes(self) -> list:
        """The car's own scheme indices to delete after the build."""
        return list(self._paint_removes)

    def _auto_id_changed(self, on: bool) -> None:
        """Keep the id in step with the install while Auto is ticked."""
        if on:
            self.new_id.setValue(self.inv.free_id())
        self.new_id.setEnabled(not on)
        self._update_plan()

    # ---- the aero clips -----------------------------------------------
    def _clip_rows(self) -> list:
        """``[(name, start, end)]`` as the table shows them."""
        out = []
        for i in range(self.clips_table.rowCount()):
            name = self.clips_table.item(i, 0)
            start = self.clips_table.item(i, 1)
            end = self.clips_table.item(i, 2)
            if name is None:
                continue
            try:
                out.append((name.text(), int(start.text()), int(end.text())))
            except (AttributeError, ValueError):
                continue
        return out

    def clip_list(self) -> list:
        """The clip set to write, as :class:`rr3lib.animxml.Clip` objects.

        Empty means "keep whatever the donor has", which is why a build with no
        animation in the pack still produces a car.
        """
        return [animlib.animxmllib.Clip(n, s, e) for n, s, e in self._clip_rows()]

    def _anim_source(self) -> str:
        """Whose animation we are looking at: the car, or the donor of a new one."""
        if self.branch_new.isChecked():
            return self.donor.currentText().strip()
        return (self.car.currentText().strip()
                or self.donor.currentText().strip())

    def _fill_clips(self) -> None:
        """Show the donor's clips, or nothing when it has no animation."""
        self.clips_table.blockSignals(True)
        self.clips_table.setRowCount(0)
        source = self._anim_source()
        if source:
            path = animlib.xml_path(self.inv.root, source)
            if os.path.isfile(path):
                try:
                    clips = animlib.animxmllib.load(path)
                except Exception:                # noqa: BLE001
                    clips = []
                self.clips_table.setRowCount(len(clips))
                for i, clip in enumerate(clips):
                    self.clips_table.setItem(i, 0, QTableWidgetItem(clip.name))
                    for column, value in ((1, clip.start), (2, clip.end)):
                        cell = QTableWidgetItem(str(value))
                        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        self.clips_table.setItem(i, column, cell)
                    note = QTableWidgetItem(clip.doc())
                    note.setFlags(Qt.ItemIsEnabled)
                    self.clips_table.setItem(i, 3, note)
                if clips:
                    self.clips_note.setText(
                        f"{len(clips)} clip(s). Edit a frame number, add or "
                        "remove rows, or clear the table to keep the file as it "
                        "is.")
                else:
                    self.clips_note.setText("This car has no animation file.")
            else:
                self.clips_note.setText(
                    "No _animations.xml yet; add clips below if the car's wing "
                    "is meant to move.")
        self.clips_table.blockSignals(False)
        self._clip_defaults()

    def _fill_driver(self) -> None:
        """Show which seated pose the source car uses, without writing anything."""
        self.driver_pose.blockSignals(True)
        self.driver_pose.clear()
        self.driver_pose.addItem("The generic driver.banim", "")
        source = self._anim_source()
        state = {"choices": [], "banim": "", "own_low_poly": "", "record": ""}
        if source:
            try:
                state = animlib.driver_state(self.inv.root, source)
            except Exception as exc:             # noqa: BLE001
                self.driver_note.setText(f"Could not read the data record: {exc}")
                self.driver_pose.blockSignals(False)
                self.driver_pose.setEnabled(False)
                return
        for stem in state["choices"]:
            if stem != "driver":
                self.driver_pose.addItem(stem, stem + ".banim")
        at = self.driver_pose.findData(state["banim"])
        self.driver_pose.setCurrentIndex(at if at >= 0 else 0)
        self.driver_pose.blockSignals(False)

        enabled = bool(state["record"])
        self.driver_pose.setEnabled(enabled)
        if not source:
            self.driver_note.setText(
                "Pick a car to see how it seats its driver; a new car keeps the "
                "donor's pose.")
        elif not enabled:
            self.driver_note.setText(
                "This car has no data record in this install, so there is no pose "
                "field to change.")
        elif state["own_low_poly"]:
            self.driver_note.setText(
                f"This pose has its own low-poly model, "
                f"{os.path.basename(state['own_low_poly'])}, so the figure seen "
                f"from outside is shaped for it.")
        elif state["banim"]:
            self.driver_note.setText(
                "This pose has no low-poly model of its own, so the outside view "
                "uses the generic driver_lod_c.m3g. The game copes; it just looks "
                "approximate.")
        else:
            self.driver_note.setText(
                "The record names no pose, so the game seats this car with "
                "driver.banim.")
        self._driver_before = state["banim"]
        self._update_plan()

    def _driver_changed(self) -> None:
        """Say what picking this pose would change, without doing it."""
        want = self.driver_pose.currentData() or ""
        before = getattr(self, "_driver_before", "")
        if want == before:
            self._fill_driver()
            return
        self._update_plan()

    def driver_pose_choice(self) -> dict:
        """The pose to write, or ``{}`` when the box still says "as it was"."""
        want = self.driver_pose.currentData() or ""
        before = getattr(self, "_driver_before", "")
        if not self.driver_pose.isEnabled() or want == before:
            return {}
        return {"before": before, "after": want}

    def _clip_defaults(self) -> None:
        """Point the spin boxes at the end of the animation, if we know it."""
        source = self._anim_source()
        frames = 0
        if source:
            path = animlib.banim_path(self.inv.root, source)
            if os.path.isfile(path):
                try:
                    frames = animlib.animxmllib.frames_for(
                        animlib.banimlib.load(path).duration_ms)
                except Exception:                # noqa: BLE001
                    frames = 0
        self.clip_start.setValue(0)
        self.clip_end.setValue(frames)

    def _clip_edited(self, item) -> None:
        """Refuse a frame number that is not one."""
        if item.column() not in (1, 2):
            return
        try:
            int(item.text())
        except ValueError:
            QMessageBox.warning(self, "Aero clip",
                                f"{item.text()!r} is not a frame number.")
            self._fill_clips()
            return
        self._update_plan()

    def _add_clip(self) -> None:
        name = self.clip_name.currentText().strip()
        if not name:
            return
        self.clips_table.blockSignals(True)
        row = self.clips_table.rowCount()
        self.clips_table.insertRow(row)
        self.clips_table.setItem(row, 0, QTableWidgetItem(name))
        for column, value in ((1, self.clip_start.value()),
                              (2, self.clip_end.value())):
            cell = QTableWidgetItem(str(value))
            cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.clips_table.setItem(row, column, cell)
        note = QTableWidgetItem(animlib.animxmllib.CLIP_DOC.get(name, ""))
        note.setFlags(Qt.ItemIsEnabled)
        self.clips_table.setItem(row, 3, note)
        self.clips_table.blockSignals(False)
        self._update_plan()

    def _remove_clip(self) -> None:
        rows = self.clips_table.selectionModel().selectedRows() if \
            self.clips_table.selectionModel() else []
        if not rows:
            return
        self.clips_table.removeRow(rows[0].row())
        self._update_plan()

    def _default_clips(self) -> None:
        """Rest, up and down, over the whole animation."""
        frames = self.clip_end.value()
        clips = animlib.suggest_clips(frames * animlib.FRAME_MS)
        self.clips_table.blockSignals(True)
        self.clips_table.setRowCount(0)
        for i, clip in enumerate(clips):
            self.clips_table.insertRow(i)
            self.clips_table.setItem(i, 0, QTableWidgetItem(clip.name))
            for column, value in ((1, clip.start), (2, clip.end)):
                cell = QTableWidgetItem(str(value))
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.clips_table.setItem(i, column, cell)
            note = QTableWidgetItem(clip.doc())
            note.setFlags(Qt.ItemIsEnabled)
            self.clips_table.setItem(i, 3, note)
        self.clips_table.blockSignals(False)
        self._update_plan()

    def _aero_changed(self) -> None:
        wants = self._aero_kind() in (b"DeployAtSpeed", b"BrakeAndSpeedCombo")
        self.aero_high.setEnabled(wants)
        self.aero_low.setEnabled(wants)
        self._update_plan()

    def _aero_kind(self) -> bytes:
        """The behaviour to write, or ``b""`` to keep the donor's own."""
        row = AERO_ITEMS[self.aero.currentIndex()] if AERO_ITEMS else ("", None)
        kind = row[1]
        return b"" if kind is None else kind

    def _aero_mode(self) -> int:
        """0 keep, 1 enable, 2 disable - the shape ``install_pack`` takes."""
        kind = self._aero_kind()
        if self.aero.currentIndex() == 0:
            return 0
        return 2 if kind == b"" else 1

    def _aero_params(self) -> tuple:
        kind = self._aero_kind()
        if kind not in (b"DeployAtSpeed", b"BrakeAndSpeedCombo"):
            return ()
        high = float(self.aero_high.value())
        low = float(self.aero_low.value())
        return (high, low)

    def paint_finishes(self) -> dict:
        """``{paint index: material}`` for the schemes whose finish was changed."""
        mapping = self._final_indexes()
        out = {}
        for i in range(self.paints.rowCount()):
            if i not in mapping:
                continue
            item = self.paints.item(i, 3)
            text = (item.text() if item is not None else "").strip()
            if text:
                out[mapping[i]] = text
        return out

    def _set_slot_file(self) -> None:
        rows = self.files.selectionModel().selectedRows() if \
            self.files.selectionModel() else []
        if not rows:
            QMessageBox.information(self, "Set file",
                                    "Select a slot in the table first.")
            return
        key = self.files.item(rows[0].row(), 0).text().split("  ")[0]
        folder = self.path.text().strip() or os.path.expanduser("~")
        got, _filter = QFileDialog.getOpenFileName(
            self, f"File for {key}", folder,
            "Game files (*.m3g *.banim *.xml *.points *.dashplanes);;All files (*)")
        if not got:
            return
        self._mapping[key] = got
        self._refresh_slots()

    def _clear_slot(self) -> None:
        rows = self.files.selectionModel().selectedRows() if \
            self.files.selectionModel() else []
        if not rows:
            return
        key = self.files.item(rows[0].row(), 0).text().split("  ")[0]
        self._mapping.pop(key, None)
        self._refresh_slots()

    def _refresh_slots(self) -> None:
        """Redraw the slot table from ``self._mapping``.

        In the modify branch a slot with nothing mapped is not empty: it keeps
        the file the car already has, so the table reads as "here is what it has,
        replace whichever one you like".  A new car has no files of its own yet,
        which is why the same column says ``(none)`` there.
        """
        new = self.branch_new.isChecked()
        car = self.new_name.text().strip() or self.car.currentText().strip()
        self.files.setRowCount(len(slotlib.SLOTS))
        for i, (key, label, template, _required) in enumerate(slotlib.SLOTS):
            source = self._mapping.get(key, "")
            head = QTableWidgetItem(key)
            head.setToolTip(label)
            self.files.setItem(i, 0, head)
            becomes = slotlib.target_name(key, car) if car else template
            if source:
                shown = os.path.basename(source)
            elif not new and self._car_has(car, becomes):
                shown = f"(keeps {becomes})"
            else:
                shown = "(none)"
            cell = QTableWidgetItem(shown)
            if source:
                cell.setToolTip(source)
            self.files.setItem(i, 1, cell)
            target = QTableWidgetItem(becomes)
            target.setFlags(Qt.ItemIsEnabled)
            self.files.setItem(i, 2, target)
        self._update_plan()

    def _car_has(self, car: str, filename: str) -> bool:
        """Whether the installed car already carries ``filename``."""
        if not car:
            return False
        folder = os.path.join(self.inv.depot, "vehicles", car)
        return os.path.isfile(os.path.join(folder, filename))

    def slot_mapping(self) -> dict:
        """The slot table as the build will use it."""
        return dict(self._mapping)

    # ---- the textures -------------------------------------------------
    def _tex_car(self) -> str:
        """Whose pages the texture table is about.

        A new car's pages come from the donor - that is the table the build
        copies - and an installed car's from itself.
        """
        if self.branch_new.isChecked():
            return self.donor.currentText().strip()
        return self.car.currentText().strip()

    def _tex_target_car(self) -> str:
        """The name the files will carry."""
        if self.branch_new.isChecked():
            return self.new_name.text().strip() or self._tex_car()
        return self.car.currentText().strip()

    def _tex_rows(self) -> list:
        """The car's own texture slots, each with the file that would fill it."""
        car = self._tex_car()
        if not car:
            return []
        try:
            rows = texlib.car_pages(self.inv.depot, car)
        except Exception:                        # noqa: BLE001
            rows = []
        folder = self.path.text().strip()
        found = texlib.guess(folder, car, rows) if folder else {}
        out = []
        for row in rows:
            source = self._tex_override.get(row["stem"])
            if source is None:
                source = found.get(row["stem"], {}).get("path", "")
            out.append(dict(row, source=source or ""))
        return out

    def _tex_suffix(self, row) -> str:
        """The suffix a converted picture would be written with."""
        source = row.get("source") or ""
        if source and not texlib.is_picture(source):
            return texlib.page_suffix(source) or row.get("suffix", "")
        return texlib.family_suffix(
            self.inv.root, prefer=row.get("suffix", ""),
            key=settingslib.texture_family())

    def _fill_textures(self) -> None:
        """Draw the texture table and the paint pictures found in the folder."""
        rows = self._tex_rows()
        car = self._tex_target_car()
        self.tex_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            head = QTableWidgetItem(row["stem"])
            head.setToolTip(f"{row['name'] or 'a page of its own'} - "
                            f"{dict(texlib.STANDARD).get(row['stem'], '')}".strip(" -"))
            self.tex_table.setItem(i, 0, head)
            source = row.get("source") or ""
            if source:
                shown = os.path.basename(source)
            elif row.get("path"):
                shown = f"(keeps {os.path.basename(row['path'])})"
            else:
                shown = "(none)"
            cell = QTableWidgetItem(shown)
            if source:
                cell.setToolTip(source)
            self.tex_table.setItem(i, 1, cell)
            suffix = self._tex_suffix(row)
            becomes = texlib.target_rel(car, row["stem"], suffix) if car \
                else f"{row['stem']}{suffix}"
            target = QTableWidgetItem(becomes)
            target.setFlags(Qt.ItemIsEnabled)
            if source and texlib.is_picture(source):
                target.setToolTip(
                    "A picture is encoded into this page when you press Build.")
            self.tex_table.setItem(i, 2, target)

        # A picture of a paint scheme, not of the car: listed so it is visible
        # that it was recognised, and offered in the Add a scheme dialog.
        pictures = self._livery_found()
        self.livery_table.setRowCount(len(pictures))
        for i, item in enumerate(pictures):
            head = QTableWidgetItem(item["leaf"])
            head.setToolTip(item["path"])
            self.livery_table.setItem(i, 0, head)
            self.livery_table.setItem(
                i, 1, QTableWidgetItem(self._livery_name(item)))
        self.livery_note.setText(
            "A file called ext_<something>, or one in the folder's livery/ "
            "subfolder, is a paint scheme's own body picture rather than a page "
            "of the car's. They are recognised here so you can pick one when you "
            "add a paint scheme below."
            if pictures else
            "No paint scheme pictures in this folder. A file called ext_<colour> "
            "- or one in a livery/ subfolder - would be recognised as one, and "
            "offered when you add a paint scheme below.")
        self._update_plan()

    def _livery_found(self) -> list:
        folder = self.path.text().strip()
        car = self._tex_car()
        if not folder or not car:
            return []
        try:
            return texlib.livery_pictures(folder, car)
        except Exception:                        # noqa: BLE001
            return []

    def _livery_name(self, item) -> str:
        car = self._tex_target_car() or self._tex_car()
        tag = item.get("tag") or "colour"
        stem = "ext" if int(item.get("slot") or 0) == texlib.BODY_SLOT else "int"
        suffix = texlib.page_suffix(item["path"]) if not item["picture"] \
            else texlib.family_suffix(
                self.inv.root,
                key=settingslib.texture_family())
        return texlib.target_rel(car, f"{stem}_{tag}", suffix, place="livery")

    def livery_pictures(self) -> list:
        """``[{path, leaf, name, tag, slot}]`` - the pictures a scheme may use."""
        out = []
        for item in self._livery_found():
            out.append({"path": item["path"], "leaf": item["leaf"],
                        "tag": item.get("tag") or "",
                        "slot": item.get("slot"),
                        "name": self._livery_name(item)})
        return out

    def texture_items(self) -> list:
        """The texture rows the build would write, as ``edit`` wants them."""
        out = []
        for row in self._tex_rows():
            source = row.get("source") or ""
            if not source:
                continue
            out.append({"slot": row.get("slot"), "stem": row["stem"],
                        "source": source, "place": "car"})
        return out

    def _set_tex_file(self) -> None:
        rows = self.tex_table.selectionModel().selectedRows() if \
            self.tex_table.selectionModel() else []
        if not rows:
            QMessageBox.information(self, "Set a texture",
                                    "Select a slot in the texture table first.")
            return
        stem = self.tex_table.item(rows[0].row(), 0).text()
        folder = self.path.text().strip() or os.path.expanduser("~")
        got, _filter = QFileDialog.getOpenFileName(
            self, f"Picture for {stem}", folder,
            "Pictures and textures (*.png *.jpg *.jpeg *.bmp *.webp *.tga "
            "*.dxt.dds.z *.etc.dds.z *.atc.dds.z *.ptc.pvr.z *.dds.z *.pvr.z);;"
            "All files (*)")
        if not got:
            return
        self._tex_override[stem] = got
        self._fill_textures()

    def _clear_tex(self) -> None:
        rows = self.tex_table.selectionModel().selectedRows() if \
            self.tex_table.selectionModel() else []
        if not rows:
            return
        stem = self.tex_table.item(rows[0].row(), 0).text()
        self._tex_override.pop(stem, None)
        self._fill_textures()


    def paint_choices(self) -> list:
        """The donor scheme indices still ticked, in the order shown.

        Only schemes the donor already has: a queued addition has no donor index
        and is copied in by :meth:`paint_adds` after the build.
        """
        out = []
        for i, row in enumerate(self._shown_paints):
            if row["kind"] != "car":
                continue
            item = self.paints.item(i, 0)
            if item is not None and item.checkState() == Qt.Checked:
                out.append(row["index"])
        return out

    def stat_changes(self) -> dict:
        """Whatever the user changed in the New car column, as spec keys.

        Numbers are typed; the class and the drivetrain are picked from a list
        and are only written when they differ from the source car's own word, so
        a build that touches neither writes neither.
        """
        if not self._tune_on():
            return {}
        out = {}
        for key in statlib.WORD_KEYS:
            box = self._word_boxes.get(key)
            if box is None:
                continue
            word = box.currentData() or ""
            was = str((self._stat_values.get(key) or {}).get("value") or "")
            if word and word != was:
                out[key] = word
        for i, (key, _label, _unit) in enumerate(statlib.ALL_FIELDS):
            if key in statlib.WORD_KEYS:
                continue
            item = self.stats.item(i, 2)
            text = (item.text() if item is not None else "").strip()
            if text:
                out[key] = text
        return out

    def _stat_problems(self) -> list:
        return statlib.validate(self.stat_changes())

    def _tail_problems(self) -> list:
        """Problems with the five tail controls.

        The words are picked from a list and the money comes out of spin boxes,
        so the only thing that can be wrong is the unlock rule - and it is wrong
        in the way the spec refuses: not ASCII, or longer than a rule can be.
        """
        changes = self.tail_changes()
        unlock = changes.get("unlock")
        if unlock is None:
            return []
        problems = []
        try:
            unlock.encode("ascii")
        except UnicodeEncodeError:
            problems.append("the unlock rule has to be plain ASCII")
        if len(unlock) > 200:
            problems.append(f"the unlock rule is {len(unlock)} characters long; "
                            "a rule cannot be longer than 200")
        return problems

    def _browse(self) -> None:
        start = self.path.text() or os.path.expanduser("~")
        got = QFileDialog.getExistingDirectory(self, "Choose the exported folder", start)
        if got:
            self.path.setText(got)
            self._load_pack()

    def _load_pack(self) -> None:
        folder = self.path.text().strip()
        if not folder:
            # The box was cleared: forget the folder, and with it the slots it
            # filled.  In the modify branch that is the "change nothing about
            # the files, only the settings" case rather than an error.
            self._mapping = {}
            self.pack = None
            self.pack_info.setText(
                "No folder chosen - the car keeps the files it has."
                if not self.branch_new.isChecked() else "No folder chosen.")
            self._refresh_slots()
            self._fill_textures()
            return
        if not os.path.isdir(folder):
            self.pack_info.setText(f"{folder} is not a folder")
            return
        # The folder is the truth and car.json is a convenience: the slot table
        # is read from the files' names, and the manifest only supplies the
        # identity strings a file name cannot express.
        self._mapping = slotlib.read_folder(folder)
        pack = None
        if packlib.find(folder):
            try:
                pack = packlib.load(folder)
            except packlib.PackError as exc:
                self.pack_info.setText(f"car.json is not readable: {exc}")
        self.pack = pack
        problems = slotlib.problems(folder, self._mapping)
        filled = len(self._mapping)
        self.pack_info.setText(
            f"{os.path.basename(folder)}: {filled} of {len(slotlib.KEYS)} slots "
            "filled from the files"
            + ("" if not problems else "  |  " + "; ".join(problems)))
        if pack is not None:
            if pack.kind == "new":
                self.branch_new.setChecked(True)
                self.new_name.setText(pack.name)
                if pack.donor:
                    self.donor.setCurrentText(pack.donor)
                ident = pack.identity
                if ident.get("display_key"):
                    self.display_key.setText(str(ident["display_key"]))
                if ident.get("model_token"):
                    self.model_token.setText(str(ident["model_token"]))
            else:
                self.branch_modify.setChecked(True)
                self.car.setCurrentText(pack.name)
        self._refresh_slots()
        self._branch_changed()
        self._fill_textures()
        # The scale is relative to the exported mesh, so it can only be offered
        # once a folder is chosen.  A folder that has never been sized starts
        # from the wheel points, which is the scale that put our own car's
        # wheels on the ground; the user can still type over it.
        self._measure_mesh()
        if self._mesh_measure and not (self.wheel_front.value()
                                       or self.wheel_rear.value()):
            self._wheels_from_points()
        self._refresh_wheel_info()

    # ---- wheels -------------------------------------------------------
    def _wheel_mesh(self) -> str:
        """The exported shared model, which is what the scale is relative to."""
        for key in ("shared", "A"):
            path = self._mapping.get(key)
            if path and os.path.isfile(path):
                return path
        return ""

    def _measure_mesh(self) -> None:
        """Measure the folder's wheel once, so typing a scale is not a reparse."""
        self._mesh_measure = None
        path = self._wheel_mesh()
        if not path:
            return
        try:
            self._mesh_measure = wheelsizelib.mesh_tyre_rim(path)
        except Exception:                      # noqa: BLE001
            self._mesh_measure = None

    def _wheels_from_points(self) -> None:
        points = self._mapping.get("points") or ""
        if not points or not os.path.isfile(points):
            self.wheel_info.setText(
                "The folder has no .points, so there is no hub height to take "
                "the scale from. Export the .points, or type a scale by hand.")
            return
        front, rear = wheelsizelib.axle_heights(points)
        if front is None and rear is None:
            self.wheel_info.setText(
                "The .points carries no POINT_WHEEL_*, so it cannot give the "
                "hub height. Type a scale by hand.")
            return
        tyre = (self._mesh_measure or (wheelsizelib.MESH_TYRE_RADIUS,) * 3)[0]
        for box, height in ((self.wheel_front, front), (self.wheel_rear, rear)):
            if height:
                box.setValue(round(height / tyre, 3))

    def _wheels_from_mesh(self) -> None:
        self.wheel_front.setValue(1.0)
        self.wheel_rear.setValue(1.0)

    def wheel_sizes(self) -> dict:
        """The floats to write, keyed by their index in the appearance record.

        ``1``/``2`` are the front tyre and rim radius, ``5``/``6`` the rear.
        A box left at zero contributes nothing, so the donor's value survives -
        which is what a build that only wants to fix the rear wants.

        The box holds the multiple of the exported mesh, but the record does not
        take that number directly: the engine draws ``f ** 2 / mesh``, so the
        record gets ``mesh * sqrt(scale)`` and the screen gets ``mesh * scale``.
        ``wheelsizelib.record_values`` is the one place that conversion lives,
        because getting it wrong here inflates the wheel by exactly the factor
        the user typed - the bug that took three in-game launches to pin down.
        """
        if not self._mesh_measure:
            return {}
        tyre, rim, _bore = self._mesh_measure
        out = {}
        for box, i_tyre, i_rim in ((self.wheel_front, 1, 2),
                                   (self.wheel_rear, 5, 6)):
            scale = box.value()
            if scale <= 0:
                continue
            f_tyre, f_rim = wheelsizelib.record_values(tyre, rim, scale)
            out[i_tyre] = round(f_tyre, 4)
            out[i_rim] = round(f_rim, 4)
        return out

    def _wheel_changed(self) -> None:
        self._refresh_wheel_info()
        self._update_plan()

    def _refresh_wheel_info(self) -> None:
        if not self._mesh_measure:
            self.wheel_info.setText(
                "Choose an exported folder to measure its wheel: the scale is a "
                "multiple of the mesh, so there is nothing to multiply yet."
                if not self._mapping else
                "The folder carries no shared model, so the scale cannot be "
                "measured here. Type it by hand: it is the multiple of the mesh "
                "the game should draw.")
            return
        tyre, rim, bore = self._mesh_measure
        bits = [f"Mesh: tyre {2 * tyre:.3f} m across, rim {2 * rim:.3f} m, so "
                f"the rim laps the tyre's bore by {1000 * (rim - bore):+.1f} mm "
                "(negative would show a ring of daylight)."]
        drawn = []
        for box, name, i_tyre in ((self.wheel_front, "front", 1),
                                  (self.wheel_rear, "rear", 5)):
            scale = box.value()
            if scale <= 0:
                drawn.append(f"{name} keeps the donor's")
            else:
                f_tyre, _f_rim = wheelsizelib.record_values(tyre, rim, scale)
                drawn.append(f"{name} {2 * tyre * scale:.3f} m across "
                             f"(record {f_tyre:.4f})")
        bits.append("Drawn: " + ", ".join(drawn) + ".")
        bits.append("The record gets the square root of the scale, because the "
                    "engine draws the mesh at record² / mesh - so the number "
                    "written is not the radius on screen.")
        template = 2 * wheelsizelib.MESH_TYRE_RADIUS
        if abs(2 * tyre - template) > 0.02:
            bits.append(f"The mesh is {2 * tyre:.3f} m across, not the "
                        f"{template:.3f} m shared template - the scale is still "
                        "relative to it, but one model no longer serves both "
                        "axles at one size.")
        bits.append("The rotor and the caliper are not multiplied by this: "
                    "author them at the size they end up.")
        self.wheel_info.setText(" ".join(bits))

    def _wheel_words(self) -> str:
        """``"0.719 m / 0.733 m across"``, or "" when nothing is set."""
        if not self._mesh_measure:
            return ""
        tyre = self._mesh_measure[0]
        front = self.wheel_front.value() * tyre
        rear = self.wheel_rear.value() * tyre
        if front and rear:
            return f"{2 * front:.3f} m / {2 * rear:.3f} m across"
        if not (front or rear):
            return ""
        which = "front" if front else "rear"
        return f"its {which} wheels {2 * (front or rear):.3f} m across"

    # ---- branch -------------------------------------------------------
    def _branch_changed(self) -> None:
        new = self.branch_new.isChecked()
        # The paint queues name schemes of one particular car, so switching what
        # the dialog is about drops them: an index queued for the donor's table
        # means nothing for an installed car's.
        self._paint_adds = []
        self._paint_removes = []
        self._paint_pictures = {}
        for widget in (self.donor, self.new_id, self.new_name, self.appearance_id,
                       self.aliases):
            widget.setEnabled(new)
        self.car.setEnabled(not new)
        # The three names apply to both branches: renaming a car that is already
        # installed is exactly what the modify branch is for, and each box is
        # prefilled with the car's own value so an untouched build writes nothing.
        for widget in (self.display_key, self.model_token, self.make):
            widget.setEnabled(True)
        # Model files and animation behaviour apply to both branches: replacing
        # the geometry of a car that is already installed, or giving it a wing
        # the studio left out, are exactly what the modify branch is for.
        for widget in (self.aero, self.aero_high, self.aero_low,
                       self.clips_table, self.clip_name, self.clip_start,
                       self.clip_end, self.add_clip_btn, self.del_clip_btn,
                       self.suggest_clip_btn):
            widget.setEnabled(True)
        self._aero_changed()
        # The paints are editable on both branches now: a new car decides which
        # of the donor's schemes it comes with, and an installed car can have one
        # added or removed here instead of going to the Cars page for it.
        for widget in (self.paints, self.paints_note, self.finish,
                       self.finish_note, self.add_paint_btn, self.del_paint_btn):
            widget.setEnabled(True)
        self.auto_id.setEnabled(new)
        # A series names the cars allowed to enter, so it can only be written
        # for a car that is about to exist.  An installed car already has
        # whatever the studio gave it, and that is the Career tab's job.
        self.series_box.setEnabled(new)
        if not new:
            self.series_box.setChecked(False)
        self._series_changed()
        if new and self.auto_id.isChecked():
            self.new_id.setValue(self.inv.free_id())
        self._fill_stats()
        self._fill_paints()
        self._fill_textures()
        self._update_plan()

    def identity_changes(self) -> dict:
        """The display name, model token and make that differ from the car's own.

        Empty means "nothing was touched", and the build then writes no spec and
        no text file at all - which matters, because a rename rewrites thirteen
        text files and there is no reason to touch them for a geometry swap.
        """
        if self.branch_new.isChecked():
            return {}
        car = self.car.currentText().strip()
        entry = next((e for e in self.inv.cars if e.name == car), None)
        if entry is None:
            return {}
        out = {}
        name = self.display_key.text().strip()
        if name and name != (getattr(entry, "display_name", "") or ""):
            out["display_name"] = name
        make = self.make.currentText().strip()
        if make and make != (entry.make or ""):
            out["make"] = make
        model = self.model_token.text().strip()
        if model and model != (entry.model or ""):
            out["model"] = model
        return out

    def _update_plan(self) -> None:
        new = self.branch_new.isChecked()
        if not self._mapping and new:
            self.plan.setText("Choose an exported folder first.")
            return
        files = len(self._mapping)
        pages = self.texture_items()
        pictures = [p for p in pages if texlib.is_picture(p["source"])]
        textured = (f", write {len(pages)} texture page(s)"
                    + (f" ({len(pictures)} of them converted from pictures)"
                       if pictures else "")
                    if pages else "")
        if new:
            appearance = (f"appearance {self.appearance_id.value()}"
                          if self.appearance_id.value() else "the next free appearance record")
            token = self.model_token.text().strip() or "derived from the folder name"
            changes = self.stat_changes()
            numbers = (f", and give it {len(changes)} figure(s) of its own"
                       if changes else "")
            paints = self.paint_choices()
            total = len([r for r in self._shown_paints if r["kind"] == "car"])
            kept = (f", keep {len(paints)} of its {total} paint scheme(s)"
                    if total and len(paints) != total else "")
            extra = (f", and add {len(self._paint_adds)} scheme(s) of its own"
                     if self._paint_adds else "")
            klass = self.stat_changes().get("car_class", "")
            filed = f", file it as {klass}" if klass else ""
            finish = self.finish.currentData() or ""
            painted = f", paint it {finish}" if finish else ""
            recoloured = self.paint_colours()
            tinted = (f", recolour {len(recoloured)} scheme(s)"
                      if recoloured else "")
            clips = self.clip_list()
            timed = (f", and write {len(clips)} aero clip(s)" if clips else "")
            sound = self.sound_family()
            voiced = f", sound like {sound}" if sound else ""
            route = self.route_key()
            routed = f", follow the {route} upgrade route" if route else ""
            tail = self.tail_changes()
            sold = ""
            if tail:
                bits = []
                if "aspiration" in tail:
                    bits.append(f"as a {tail['aspiration']}")
                if "layout" in tail:
                    bits.append(f"driven through the {tail['layout']}")
                if "unlock" in tail:
                    bits.append(f"unlocked by {tail['unlock'] or 'nothing'}")
                price = _price_words(tail, self.cash.value(), self.gold.value())
                if price:
                    bits.append(price)
                sold = ", " + ", ".join(bits)
            placed = self.series_placement()
            racing = ""
            if placed:
                where = placed.get("group") or "a group of its own"
                racing = f", and race it in {where}"
            words = self._wheel_words()
            wheeled = f", drawing its wheels {words}" if words else ""
            pose = self.driver_pose_choice()
            seated = ""
            if pose:
                seated = (", seat the driver with "
                          + (f"{pose['after']}" if pose["after"]
                             else "the generic driver.banim"))
            self.plan.setText(
                f"Will clone {self.donor.currentText()} as id {self.new_id.value()}, "
                f"{appearance}, model token {token}, "
                f"named {self.new_name.text() or '(no name)'}, add a spec, an "
                "appearance record, a row in the suspension and damage tables and "
                f"{files} file(s) of geometry{numbers}{kept}{extra}{wheeled}"
                f"{painted}{tinted}{filed}{routed}{sold}{racing}{timed}{voiced}"
                f"{textured}{seated}.")
        else:
            clips = self.clip_list()
            timed = (f" It also writes {len(clips)} aero clip(s)." if clips else "")
            sound = self.sound_family()
            voiced = f" Its engine sound becomes {sound}." if sound else ""
            route = self.route_key()
            routed = f" It moves to the {route} upgrade route." if route else ""
            tail = self.tail_changes()
            sold = ""
            if tail:
                bits = []
                if "aspiration" in tail:
                    bits.append(f"becomes a {tail['aspiration']}")
                if "layout" in tail:
                    bits.append(f"drives through the {tail['layout']}")
                if "unlock" in tail:
                    bits.append(f"unlocks by {tail['unlock'] or 'nothing'}")
                price = _price_words(tail, self.cash.value(), self.gold.value())
                if price:
                    bits.append(price.replace("sold for", "sells for"))
                sold = " It " + ", ".join(bits) + "."
            words = self._wheel_words()
            wheeled = f" Its wheels are drawn {words}." if words else ""
            identity = self.identity_changes()
            renamed = ""
            if identity:
                bits = []
                if "display_name" in identity:
                    bits.append(f"be called {identity['display_name']}")
                if "make" in identity:
                    bits.append(f"be filed under {identity['make']}")
                if "model" in identity:
                    bits.append(f"be a {identity['model']}")
                renamed = " It will " + ", ".join(bits) + "."
            added = len(self._paint_adds)
            gone = len(self._paint_removes)
            repainted = ""
            if added or gone:
                bits = []
                if added:
                    bits.append(f"gain {added} paint scheme(s)")
                if gone:
                    bits.append(f"lose {gone} paint scheme(s)")
                repainted = " It will " + " and ".join(bits) + "."
            pose = self.driver_pose_choice()
            seated = ""
            if pose:
                seated = (" The driver is seated with "
                          + (f"{pose['after']}" if pose["after"]
                             else "the generic driver.banim") + ".")
            car = self.car.currentText() or "(no car)"
            if files:
                opening = (
                    f"Will put {files} file(s) into {car}'s folder under the "
                    "names the game expects, and update the three manifests. "
                    "Files the table does not mention are left alone.")
            else:
                # No folder is not an error here: changing what a car is called,
                # what it drives like or which schemes it carries touches no
                # file of its own, and any single file can still be swapped in
                # from the slot table above.
                opening = (
                    f"Will change {car} without touching its files: no folder was "
                    "chosen, so every model, animation and anchor stays as it is.")
            self.plan.setText(
                f"{opening}{wheeled}{renamed}{repainted}{routed}{sold}{timed}"
                f"{voiced}{seated}"
                + (f" It also writes {len(pages)} texture page(s)"
                   + (f", converting {len(pictures)} picture(s) into the format "
                      "chosen in Settings" if pictures else "")
                   + "." if pages else ""))

    # ---- accept -------------------------------------------------------
    def _accept(self) -> None:
        folder = self.path.text().strip()
        new = self.branch_new.isChecked()
        if new:
            if not self._mapping:
                QMessageBox.warning(self, "Build a car",
                                    "Choose an exported folder first.")
                return
            problems = slotlib.problems(folder, self._mapping)
        else:
            # A car that is already installed does not need a folder: its own
            # files stay unless one is mapped, and every setting on this page
            # (the name, the figures, the paints, the clips) is written on its
            # own.  Only the slots that were actually filled are checked, so
            # swapping in one wing file is a build like any other.
            problems = slotlib.problems(folder, self._mapping, required=False)
            if not self._modify_work():
                problems.append(
                    "nothing to do - choose a folder of files, or change "
                    "something on this page")
        problems = [p for p in problems if not p.startswith("not used:")]
        if new:
            name = self.new_name.text().strip()
            if not name:
                problems.append("the new car needs a folder name")
            else:
                try:
                    from rr3lib import car as carlib
                    carlib.check_name(name)
                except Exception as exc:         # noqa: BLE001
                    problems.append(str(exc))
            if not self.donor.currentText().strip():
                problems.append("a new car needs a donor")
            if not self.paint_choices():
                problems.append("a new car needs at least one paint scheme")
            placed = self.series_placement()
            if placed:
                if not placed.get("template"):
                    problems.append(
                        "choose the series whose races the new one should copy")
                if self._career is None:
                    problems.append(
                        "the career file has not been read yet - untick the "
                        "series box or wait for it to finish")
        # Both branches write figures and the tail, so both check them.
        problems.extend(self._stat_problems())
        problems.extend(self._tail_problems())
        if problems:
            QMessageBox.warning(self, "Build a car", "\n".join(problems))
            return
        self.accept()

    def _modify_work(self) -> bool:
        """Whether a modify build would change anything at all."""
        pose = self.driver_pose_choice() or {}
        return bool(
            self._mapping
            or self.texture_items()
            or self.identity_changes()
            or self.stat_changes()
            or self.tail_changes()
            or self.paint_adds()
            or self.paint_removes()
            or self.paint_colours()
            or self.clip_list()
            or self.sound_family()
            or self.route_key()
            or self.wheel_sizes()
            or self._aero_mode()
            or pose.get("after") != pose.get("before"))

    # ---- results ------------------------------------------------------
    def result_info(self) -> dict:
        new = self.branch_new.isChecked()
        return {
            "pack": self.pack,
            "slots": self.slot_mapping(),
            "new": new,
            "car": self.car.currentText().strip(),
            "donor": self.donor.currentText().strip(),
            "new_id": self.new_id.value() if new else 0,
            "new_name": self.new_name.text().strip(),
            "appearance_id": self.appearance_id.value() if new else 0,
            "display_key": self.display_key.text().strip(),
            "model_token": self.model_token.text().strip(),
            "aero": self._aero_mode(),
            "aero_kind": self._aero_kind(),
            "aero_params": self._aero_params(),
            "paint_finishes": self.paint_finishes() if new else {},
            "paint_pictures": self.paint_pictures(),
            "aliases": self.aliases.isChecked(),
            "stats": self.stat_changes(),
            "paints": self.paint_choices() if new else None,
            # The class and the drivetrain live in the figures table now, so the
            # spec writer takes them from there like every other word.
            "car_class": self.stat_changes().get("car_class", ""),
            "make": self.make.currentText().strip() if new else "",
            "paint_finish": (self.finish.currentData() or "") if new else "",
            "paint_colours": self.paint_colours() if new else {},
            "clips": self._clip_rows(),
            "driver_pose": self.driver_pose_choice(),
            "sound": self.sound_family(),
            "route": self.route_key(),
            "tail": self.tail_changes(),
            "series": self.series_placement(),
            "wheel_sizes": self.wheel_sizes(),
            # The modify branch's own work: renaming what is already installed,
            # and changing which schemes it has.  Both are empty for a new car -
            # a new car is named by its folder and starts from the donor.
            "identity": {} if new else self.identity_changes(),
            "paint_adds": self.paint_adds(),
            "paint_removes": [] if new else self.paint_removes(),
            # The pages of the car's own folder that this build fills, already
            # resolved to the file the game will load.  A picture in here is
            # encoded when the build runs, not before.
            "textures": self.texture_items(),
        }
