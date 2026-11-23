"""The Ride height tab of the car detail pane.

The slider the game shows has two halves and they do not come from the same
place:

* **up** is ``suspensiondata`` floats 23/24 for the car's id - a stored number;
* **down** is not stored anywhere.  The engine derives it as
  ``tyre diameter - 2 * loaded radius``, i.e. twice the tyre's static
  deflection, so writing a down range means solving for the tyre diameter.

Both are editable here because the page can do that arithmetic, and both are
written in one go: an up-only change would leave the two halves disagreeing,
which is exactly the state a build used to land in.

The numbers are millimetres because that is what the game prints.  It *prints*
by truncating (``int(metres * 1000)``), which is why a shipped car whose table
says 0.010 and 0.015 reads as ``+10 / -9`` and ``+15 / -14`` - the 9 and the 14
are the same numbers as the 10 and the 15, one float32 ulp lower.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDoubleSpinBox, QGridLayout, QHBoxLayout,
                               QLabel, QVBoxLayout, QWidget)

from rr3lib import appearance as appearlib
from rr3lib import spec as speclib

from .. import edit as editlib
from . import widgets as W

#: The shipped cars run 3 mm (a NASCAR) to 150 mm (a Cobra).  The Essenza SCV12
#: carries 632 mm of up travel and no down travel at all - that is a real car,
#: not a typo, so the boxes allow it.
MAX_MM = 700.0


class SuspensionPane(QWidget):
    """Ride height: both halves of the slider, in millimetres."""

    changed = Signal()          # something was written to disk
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = ""
        self.car = ""
        self.car_id = 0
        self._up = None
        self._down = None
        self._dia = None
        self._loaded = None
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(W.heading("Ride height", 3))
        lay.addWidget(W.muted(
            "How far this car can be raised and lowered from stock. The game "
            "keeps these as two unrelated things - the up half is a travel "
            "figure, the down half is worked out from the tyre - so both are "
            "written here and the tyre is solved for you."))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        # Two columns of numbers under a front/rear header, because every value
        # on this pane comes in a pair and a bare "rear" label beside a box is
        # read as belonging to the box before it.
        grid.addWidget(W.muted(""), 0, 0)
        grid.addWidget(W.muted("front"), 0, 1)
        grid.addWidget(W.muted("rear"), 0, 2)

        def box(tip: str) -> QDoubleSpinBox:
            b = QDoubleSpinBox()
            b.setRange(0.0, MAX_MM)
            b.setDecimals(0)
            b.setSingleStep(1.0)
            b.setSuffix(" mm")
            b.setMinimumWidth(110)
            b.setToolTip(tip)
            b.valueChanged.connect(self._edited)
            return b

        grid.addWidget(QLabel("Up"), 1, 0)
        self.up_front = box(
            "How far the front can be raised above stock. This is "
            "suspensiondata float 23 for this car.")
        grid.addWidget(self.up_front, 1, 1)
        self.up_rear = box("The same for float 24.")
        grid.addWidget(self.up_rear, 1, 2)

        grid.addWidget(QLabel("Down"), 2, 0)
        self.down_front = box(
            "How far the front can be lowered. Not a stored field: the engine "
            "works it out as tyre diameter minus twice the loaded radius, so "
            "saving this writes the diameter.")
        grid.addWidget(self.down_front, 2, 1)
        self.down_rear = box("The same, from the rear tyre.")
        grid.addWidget(self.down_rear, 2, 2)

        grid.setColumnStretch(3, 1)
        lay.addLayout(grid)

        self.stored = W.muted("")
        self.stored.setWordWrap(True)
        lay.addWidget(self.stored)

        row = QHBoxLayout()
        self.save_btn = W.button("Save the range", self._save, primary=True,
                                 tip="Write both halves and re-book the manifests")
        self.save_btn.setEnabled(False)
        row.addWidget(self.save_btn)
        self.reload_btn = W.button("Reload", self._reload,
                                   tip="Throw away unsaved changes")
        self.reload_btn.setEnabled(False)
        row.addWidget(self.reload_btn)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(W.heading("Where these numbers live", 3))
        self.where = W.muted("")
        self.where.setWordWrap(True)
        lay.addWidget(self.where)
        lay.addStretch(1)

    # ---- content -------------------------------------------------------
    def load(self, root: str, car: str, car_id: int = 0) -> None:
        """Read one car's numbers.  ``car_id`` comes from the inventory the page
        already has, so this never has to rescan the install."""
        self.root = root
        self.car = car
        self.car_id = int(car_id or 0)
        self._up = self._down = self._dia = self._loaded = None
        self._loading = True
        try:
            if not root or not car or not self.car_id:
                self._blank("No car selected.")
                return
            depot = os.path.join(root, ".depot")
            try:
                rec = speclib.load_suspension(depot).get(self.car_id)
            except Exception as exc:             # noqa: BLE001
                self._blank(f"Could not read the suspension table: {exc}")
                return
            self._up = speclib.suspension_travel(rec)
            self._dia = speclib.suspension_tyre_diameter(rec)
            try:
                _, recs = appearlib.load(depot)
                for r in recs:
                    if r.name.decode("ascii", "replace") == car:
                        self._loaded = r.tyre_radius()
                        break
            except Exception:                    # noqa: BLE001
                self._loaded = None
            if self._loaded is not None:
                self._down = speclib.suspension_down_travel(
                    rec, self._loaded[0], self._loaded[1])
            # The up box shows what the game prints, which is a rounded number;
            # the down box is exact, because the down half is solved to land on
            # a whole millimetre.
            self.up_front.setValue(round(self._up[0] * 1000.0))
            self.up_rear.setValue(round(self._up[1] * 1000.0))
            if self._down is not None:
                self.down_front.setValue(speclib.display_mm(self._down[0]))
                self.down_rear.setValue(speclib.display_mm(self._down[1]))
            else:
                self.down_front.setValue(0.0)
                self.down_rear.setValue(0.0)
            self.down_front.setEnabled(self._loaded is not None)
            self.down_rear.setEnabled(self._loaded is not None)
            self._show_stored()
            self.where.setText(
                f"Up: <code>.depot/vehicles/data/"
                f"suspensionbehaviour.suspensiondata.nct</code>, row id "
                f"{self.car_id}, floats 23 and 24 (metres).<br>"
                f"Down: computed, not stored - <code>tyre diameter minus twice "
                f"the loaded radius</code> - so saving a down range writes "
                f"floats 21 and 22 of the same row. The loaded radius comes "
                f"from this car's appearance block and is left alone.")
            self.save_btn.setEnabled(True)
            self.reload_btn.setEnabled(True)
            self.save_btn.setText("Save the range")
        finally:
            self._loading = False

    def _show_stored(self) -> None:
        if not self._up:
            self.stored.setText("")
            return
        bits = [f"stored: up {self._up[0]:.4f} / {self._up[1]:.4f} m"]
        if self._dia:
            bits.append(f"tyre {self._dia[0]:.4f} / {self._dia[1]:.4f} m")
        if self._loaded:
            bits.append(f"loaded radius {self._loaded[0]:.4f} / "
                        f"{self._loaded[1]:.4f} m")
        bits.append("the game prints these by truncating, so the upper half can "
                    "read one millimetre less than it is stored as")
        self.stored.setText("; ".join(bits) + ".")

    def _blank(self, text: str) -> None:
        for b in (self.up_front, self.up_rear, self.down_front, self.down_rear):
            b.setValue(0.0)
        self.stored.setText("")
        self.where.setText(text)
        self.save_btn.setEnabled(False)
        self.reload_btn.setEnabled(False)

    # ---- editing -------------------------------------------------------
    def _values(self) -> tuple:
        return (self.up_front.value(), self.up_rear.value(),
                self.down_front.value(), self.down_rear.value())

    def _edited(self) -> None:
        if self._loading or not self.car or not self._up:
            return
        stored = (round(self._up[0] * 1000.0), round(self._up[1] * 1000.0))
        if self._down is not None:
            stored += (speclib.display_mm(self._down[0]),
                       speclib.display_mm(self._down[1]))
        else:
            stored += (0, 0)
        dirty = any(abs(a - b) >= 0.5 for a, b in zip(self._values(), stored))
        self.save_btn.setText("Save the range" if not dirty
                              else "Save the range *")

    def _reload(self) -> None:
        self.load(self.root, self.car, self.car_id)

    def _save(self) -> None:
        if not self.car:
            return
        up_f, up_r, down_f, down_r = self._values()
        try:
            out = editlib.set_suspension_range(
                self.root, self.car,
                up_mm=(up_f, up_r), down_mm=(down_f, down_r))
        except Exception as exc:                 # noqa: BLE001
            self.status.emit(f"Could not save the range: {exc}")
            return
        if not out["changed"]:
            self.status.emit("The range was already what you asked for.")
            return
        before, after = out["before"], out["after"]
        synced = out.get("synced") or {}
        self.status.emit(
            f"Ride height: up {before[0]}/{before[1]} -> {after[0]}/{after[1]} mm, "
            f"down {before[2]}/{before[3]} -> {after[2]}/{after[3]} mm, "
            f"registry {synced.get('registry', '?')}, "
            f"data list {synced.get('data_list', '?')}")
        self.changed.emit()
        self.load(self.root, self.car, self.car_id)
