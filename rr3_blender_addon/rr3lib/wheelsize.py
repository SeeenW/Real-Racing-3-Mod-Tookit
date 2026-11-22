r"""How the game sizes a car's wheels, and how to reproduce it.

WHY THIS MODULE EXISTS
----------------------
Every car in the game shares one wheel-and-tyre template.  The
``LOD_A_TYRE_mm_tyre`` mesh inside ``<car>_shared.m3g`` is the *same* tyre for
all 463 cars that ship one: its radius is 0.2940 .. 0.3024 m (median 0.2993,
coefficient of variation **0.46 %**), i.e. a 0.60 m tyre, while the real cars
in the game wear 0.54 .. 0.77 m tyres.  That is why every imported car looks
like it has the same wheels: it does.

The game scales that template at load time.  The rule, taken from the game's
own numbers and confirmed against Monkey Tool's independent implementation
(``src/nfsnl_rr3.cpp``, ``attachSharedCorners``):

* **the factor is radial only.**  The mesh is stretched in its own y and z (the
  round plane) and *not* along x (the axle), so the tyre gets taller but never
  wider - the width is already modelled per car and stretching it would push
  the tyre into the suspension.
* **the target is the tyre diameter in ``suspensionbehaviour.suspensiondata``**
  (floats 21 and 22, front and rear, in metres), so
  ``k = diameter / 2 / mesh_tyre_radius``.
* if the car has no suspension row, the fallbacks are, in order: fill the wheel
  arch (``(arch - 0.035) / mesh_tyre_radius``), then the axle height from
  ``.points``, then 1.0.

WHERE THE NUMBERS LIVE
----------------------
``suspensionbehaviour.suspensiondata.nct`` holds a 140-byte record per car;
``struct.unpack_from("<f", rec, 4 + 4*21)`` is the front tyre **diameter** and
``4 + 4*22`` the rear.  Only 172 of the 540 cars have a row there.

For the other 368 the appearance record's first 32 bytes carry the same
information: eight floats, front four then rear four, and

* ``f1`` / ``f5`` = **loaded** tyre radius (median 0.9498 x the free radius,
  i.e. a 5 % static sag),
* ``f0`` / ``f4`` = the rim radius the car wears,
* ``f2`` / ``f6`` = the same rim radius again for the cars that state it (165
  cars, matches the rim mesh within 1 %),
* ``f3`` / ``f7`` = a sidewall-ish width, still undecided.

``f1`` agrees with ``POINT_WHEEL_*``'s height above the ground to 13 mm on
average, which is what a tyre does under load, so the appearance block is a
usable fallback.

WHICH FACTOR TO USE
-------------------
Two are defensible and they differ by ~5 %:

``"engine"``
    ``k = suspension_diameter / 2 / mesh_radius``.  Exactly what the game
    computes.  The tyre then reaches the *free* radius, which is 15 mm more
    than the hub height, so it sinks slightly into the ground - the game hides
    that with suspension travel.
``"ground"``
    ``k = axle_height / mesh_radius`` (equivalently ``f1 / mesh_radius``).  The
    tyre sits exactly on the ground under a static car, which is what a
    rendered still wants.
"""
from __future__ import annotations

import glob
import os
import struct
from dataclasses import dataclass, field

from . import appearance as appearlib
from . import parts as partslib
from . import spec as speclib

#: Radius of the shared tyre template, used when a car has no ``_shared.m3g``.
MESH_TYRE_RADIUS = 0.2993

#: The game rejects a suspension diameter outside this range (metres).
DIAMETER_MIN = 0.2
DIAMETER_MAX = 2.0

#: Scale factors the game refuses to believe (a shared file from another car).
SCALE_MIN = 0.5
SCALE_MAX = 2.0

#: Rim lip clearance used by the wheel-arch fallback, in metres.
ARCH_CLEARANCE = 0.035

MODES = ("engine", "ground")


class WheelSizeError(Exception):
    pass


@dataclass
class WheelSize:
    """One car's wheel scaling, front and rear."""

    car: str = ""
    front: float = 1.0
    rear: float = 1.0
    front_radius: float = MESH_TYRE_RADIUS
    rear_radius: float = MESH_TYRE_RADIUS
    source: str = "none"
    mesh_radius: float = MESH_TYRE_RADIUS
    mesh_radius_rear: float = MESH_TYRE_RADIUS
    notes: list[str] = field(default_factory=list)

    def factor(self, rear: bool = False) -> float:
        return self.rear if rear else self.front

    def radius(self, rear: bool = False) -> float:
        return self.rear_radius if rear else self.front_radius

    def summary(self) -> str:
        return (f"{self.car}: wheel scale x{self.front:.3f} front, "
                f"x{self.rear:.3f} rear ({self.source}; tyre "
                f"{self.front_radius * 2:.3f} m / {self.rear_radius * 2:.3f} m across)")


# ------------------------------------------------------------------ lookups
def depot_for(car_dir: str) -> str | None:
    """The ``.depot`` folder a car folder belongs to, if it looks like one."""
    car_dir = os.path.abspath(car_dir)
    parent = os.path.dirname(car_dir)
    if os.path.basename(parent).lower() == "vehicles":
        depot = os.path.dirname(parent)
        if os.path.isdir(os.path.join(depot, "vehicles", "data")):
            return depot
    return None


def _car_id(depot: str, car: str) -> int | None:
    """The spec file's number for a car folder name, or None."""
    for path in glob.glob(os.path.join(depot, "vehicles", "data", "*.bin.nct")):
        stem = os.path.basename(path)[: -len(".bin.nct")]
        num, _, name = stem.partition("_")
        if name == car and num.isdigit():
            return int(num)
    return None


def suspension_diameters(depot: str, car: str) -> tuple[float, float] | None:
    """Front and rear tyre diameter in metres, from the suspension table."""
    cid = _car_id(depot, car)
    if cid is None:
        return None
    try:
        table = speclib.load_suspension(depot)
    except Exception:  # noqa: BLE001 - a missing table is not fatal
        return None
    for rec in table.records:
        if int.from_bytes(rec[:4], "little") != cid:
            continue
        front, rear = speclib.suspension_tyre_diameter(rec)
        if not (DIAMETER_MIN < front < DIAMETER_MAX):
            return None
        if not (DIAMETER_MIN < rear < DIAMETER_MAX):
            return None
        return front, rear
    return None


def appearance_sizes(depot: str, car: str) -> tuple[float, float] | None:
    """Loaded tyre radius, front and rear, from the appearance block."""
    try:
        _count, records = appearlib.load(depot)
    except Exception:  # noqa: BLE001
        return None
    for rec in records:
        if rec.name.decode("utf-8", "replace") != car:
            continue
        v = rec.wheel_sizes()
        if v[1] <= 0.05 or v[5] <= 0.05:
            return None
        return v[1], v[5]
    return None


def mesh_radii(shared_m3g: str, lod: str = "A") -> tuple[float, float]:
    """Radius of the tyre template in a ``_shared.m3g``, front and rear."""
    wheels = partslib.wheel_set(shared_m3g, lod)
    front = partslib.wheel_radius(shared_m3g, wheels.front_tyre) if wheels.front_tyre else None
    rear = partslib.wheel_radius(shared_m3g, wheels.rear_tyre) if wheels.rear_tyre else None
    if front is None and wheels.front_wheel:
        front = partslib.wheel_radius(shared_m3g, wheels.front_wheel)
    if rear is None:
        rear = front
    return (front or MESH_TYRE_RADIUS, rear or front or MESH_TYRE_RADIUS)


def axle_heights(points_file: str) -> tuple[float | None, float | None]:
    """Height of the front and rear hub above the ground, in metres."""
    try:
        mounts = partslib.wheel_mounts(points_file)
    except Exception:  # noqa: BLE001
        return None, None
    front = next((m.position[1] for m in mounts if m.corner == "FL"), None)
    rear = next((m.position[1] for m in mounts if m.corner == "BL"), None)
    return front, rear


# ------------------------------------------------------------------ the plan
def plan(car_dir: str, car: str, *, depot: str | None = None, lod: str = "A",
         mode: str = "engine") -> WheelSize:
    """Work out how much to stretch this car's wheel meshes.

    ``mode`` is ``"engine"`` (the factor the game itself computes, from the
    free tyre diameter) or ``"ground"`` (put the tyre exactly on the ground).
    """
    if mode not in MODES:
        raise WheelSizeError(f"mode must be one of {MODES}, not {mode!r}")
    out = WheelSize(car=car)

    shared = os.path.join(car_dir, f"{car}_shared.m3g")
    if os.path.exists(shared):
        out.mesh_radius, out.mesh_radius_rear = mesh_radii(shared, lod)
    else:
        out.notes.append("no _shared.m3g: assuming the 0.2993 m template")

    points = os.path.join(car_dir, f"{car}.points")
    axle_f, axle_r = axle_heights(points) if os.path.exists(points) else (None, None)

    diameters = suspension_diameters(depot, car) if depot else None
    sizes = appearance_sizes(depot, car) if depot else None

    if mode == "engine":
        if diameters:
            out.front_radius = diameters[0] / 2.0
            out.rear_radius = diameters[1] / 2.0
            out.source = "suspensionbehaviour"
        elif sizes:
            # The appearance block states the loaded radius; the free radius it
            # came from is about 5 % larger, which is what the game scales to.
            out.front_radius = sizes[0] / 0.95
            out.rear_radius = sizes[1] / 0.95
            out.source = "appearance (loaded radius / 0.95)"
        elif axle_f:
            out.front_radius = axle_f
            out.rear_radius = axle_r or axle_f
            out.source = "axle height"
        else:
            out.notes.append("no size data: leaving the template alone")
            out.source = "none"
    else:
        if axle_f and abs(axle_f - 0.31903) > 1e-4:
            out.front_radius = axle_f
            out.rear_radius = axle_r or axle_f
            out.source = "axle height"
        elif sizes:
            out.front_radius, out.rear_radius = sizes
            out.source = "appearance (loaded radius)"
        elif diameters:
            out.front_radius = diameters[0] / 2.0 * 0.95
            out.rear_radius = diameters[1] / 2.0 * 0.95
            out.source = "suspensionbehaviour x0.95"
        else:
            out.source = "none"
            out.notes.append("no size data: leaving the template alone")

    out.front = out.front_radius / out.mesh_radius
    out.rear = out.rear_radius / out.mesh_radius_rear
    if not (SCALE_MIN < out.front < SCALE_MAX):
        out.notes.append(f"front scale x{out.front:.3f} is outside the game's "
                         f"{SCALE_MIN}..{SCALE_MAX} band")
        out.front = 1.0
    if not (SCALE_MIN < out.rear < SCALE_MAX):
        out.notes.append(f"rear scale x{out.rear:.3f} is outside the game's "
                         f"{SCALE_MIN}..{SCALE_MAX} band")
        out.rear = 1.0
    return out


def format_report(ws: WheelSize) -> str:
    lines = [
        f"car            : {ws.car}",
        f"mesh tyre radius: {ws.mesh_radius:.4f} m front, {ws.mesh_radius_rear:.4f} m rear",
        f"wanted radius  : {ws.front_radius:.4f} m front, {ws.rear_radius:.4f} m rear"
        f"  ({ws.source})",
        f"scale          : x{ws.front:.4f} front, x{ws.rear:.4f} rear  (radial only)",
        f"tyre across    : {ws.front_radius * 2:.3f} m front, {ws.rear_radius * 2:.3f} m rear",
    ]
    for note in ws.notes:
        lines.append(f"note           : {note}")
    return "\n".join(lines)


def selftest(depot: str, cars: int = 0) -> int:
    """Print the plan for a few cars; returns the number of failures."""
    names = []
    for path in sorted(glob.glob(os.path.join(depot, "vehicles", "*"))):
        if os.path.isdir(path) and glob.glob(os.path.join(path, "*_shared.m3g")):
            names.append(os.path.basename(path))
    if cars:
        names = names[:cars]
    bad = 0
    for name in names:
        try:
            ws = plan(os.path.join(depot, "vehicles", name), name, depot=depot)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {name}: {exc}")
            bad += 1
            continue
        print(f"{name:<40} x{ws.front:.3f} / x{ws.rear:.3f}  {ws.source}")
    print(f"\n{len(names)} cars, {bad} failure(s)")
    return bad
