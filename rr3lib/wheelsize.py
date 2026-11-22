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
* **the target is the car's appearance record**, not the suspension table:
  eight floats at ``+0`` of the ``carappearances.appearances.nct`` record,
  front four then rear four.

WHAT THE EIGHT FLOATS ARE (in-game, settled by experiment)
---------------------------------------------------------
``f1`` / ``f5``
    front / rear **tyre radius in metres** - but *not* drawn 1:1.  The record
    value is a **scale reference**: the wheel is drawn at ``f1 / mesh tyre
    radius`` times the mesh, and the mesh it multiplies has already been through
    that same factor, so the two collapse into a square::

        drawn tyre = mesh * (f1 / mesh) ** 2 = f1 ** 2 / mesh

    It only *looks* 1:1 on a shipped car, because a shipped mesh is at the size
    the record was written for.  Measured three times on one car, one launch
    each: mesh 0.3599 + f1 0.3595 = right; mesh 0.2863 + f1 0.3595 = 1.25x too
    big; mesh 0.2863 + f1 0.2860 = 0.8x too small.  Only the square fits all
    three.  :func:`record_value` is the inverse of it, and it is the only place
    a record value should be computed.
``f2`` / ``f6``
    front / rear **rim radius in metres**, with the same square law and
    *independent* of ``f1``: ``drawn rim = f2 ** 2 / mesh rim``.  It is not a
    multiple of anything, so a record copied from a donor keeps the donor's rim
    size.
``f0`` / ``f4``
    unknown - *not* the rim radius (median ``f0/rim`` is 1.196 and 47 cars have
    ``f0 > f1``, i.e. a rim taller than its tyre).  Left alone.
``f3`` / ``f7``
    unknown, probably tyre width.  Left alone.

The mesh supplies proportions only.  Two scalings therefore act at once, and
they can disagree:

    drawn bore = mesh bore x (f1 / mesh tyre radius)
    gap        = f2 - drawn bore

A negative gap is the "small rim, fat tyre" ring of daylight.  Our own car had
``f2 = 0.2400`` against a drawn bore of ``0.2708`` - a 31 mm ring, inherited
from the donor record, not from the mesh.  ``f2 = mesh rim x f1 / mesh tyre``
closes it, which is what :func:`plan` and ``wheelsize_set.py --fit`` do.

``suspensionbehaviour.suspensiondata.nct`` floats 21 / 22 hold a tyre diameter
per axle and *look* authoritative, but changing them moves nothing on screen;
they are what Monkey Tool's previewer reads.  :func:`suspension_diameters` is
kept for that comparison and for cars whose appearance block is empty.

THE TWO SCALINGS DO NOT EXTEND TO THE BRAKES
--------------------------------------------
The rotor and the caliper are **not** multiplied by ``f1 / mesh tyre``: a stock
car authors them at their real size and the engine leaves them there.  Either
author the whole wheel assembly at final size, or normalise tyre + rim to the
shared template and author rotor + caliper at final size - never half of each.
"""
from __future__ import annotations

import glob
import os
import struct
from dataclasses import dataclass, field

from . import appearance as appearlib
from . import geometry as geomlib
from . import m3g as m3glib
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


def mesh_tyre_rim(shared_m3g: str, lod: str = "A") -> tuple[float, float, float]:
    """``(tyre radius, rim radius, tyre bore)`` in metres, from one shared model.

    Measured from the vertices, not the bounding box: a tyre's box cannot give
    the bore (the outer wall spans -R..+R on both axes), and the bore is what
    decides whether the rim shows a ring of daylight.

    The meshes are found by :func:`rr3lib.parts.shared_role`, not by their full
    name, because the ``_mm_<tag>`` suffix is a material hint that does not
    always agree with the part: 230 cars tag a low-LOD tyre ``_mm_wheel`` and 53
    tag their LOD F rim ``_mm_tyre``.  A rear-only mesh is used only when the
    axle has no front one, so a model that ships both still reports the front.
    """
    model = m3glib.M3G(shared_m3g)
    found = {"tyre": 0.0, "rim": 0.0, "tyre_rear": 0.0, "rim_rear": 0.0}
    bore = 0.0
    for obj in model.of_type(m3glib.T_MESH):
        letter, role = partslib.shared_role(obj.data.get("name") or "")
        if letter and letter != lod:
            continue
        if role not in ("TYRE", "WHEEL", "TYRE_REAR", "WHEEL_REAR"):
            continue
        md = geomlib.extract_mesh(model, obj)
        if not md.positions:
            continue
        radii = [(y * y + z * z) ** 0.5 for _x, y, z in md.positions]
        if role in ("TYRE", "TYRE_REAR"):
            key = "tyre" if role == "TYRE" else "tyre_rear"
            if max(radii) > found[key]:
                found[key] = max(radii)
            if role == "TYRE" and (not bore or min(radii) < bore):
                bore = min(radii)
        else:
            key = "rim" if role == "WHEEL" else "rim_rear"
            found[key] = max(found[key], max(radii))
    tyre = found["tyre"] or found["tyre_rear"]
    rim = found["rim"] or found["rim_rear"]
    if tyre <= 0:
        raise WheelSizeError(f"no LOD_{lod} tyre mesh in {shared_m3g}")
    return tyre, (rim or tyre), (bore or tyre)


def record_value(target: float, mesh: float) -> float:
    """The appearance-record float that draws ``mesh`` at radius ``target``.

    Inverts the engine's rule (module docstring)::

        drawn = f ** 2 / mesh          ->      f = sqrt(target * mesh)

    ``target == mesh`` returns ``mesh``, which is why a mesh authored at its
    final size can still be matched 1:1 - and why the square only shows up once
    the mesh has been rescaled away from the record.
    """
    if mesh <= 0:
        raise WheelSizeError(f"mesh radius must be positive, not {mesh!r}")
    if target <= 0:
        raise WheelSizeError(f"target radius must be positive, not {target!r}")
    return (target * mesh) ** 0.5


def record_values(mesh_tyre: float, mesh_rim: float, scale: float, *,
                  rim_scale: float | None = None) -> tuple[float, float]:
    """``(f_tyre, f_rim)`` for one axle drawn ``scale`` times its own mesh.

    ``scale`` is the number a modder actually knows: *how much bigger than the
    exported mesh this axle should be*.  Both parts are drawn at ``mesh * scale``
    (the rim keeps the model's own rim/tyre ratio, so no ring of daylight opens
    up), and the record gets the square root of that::

        f_tyre = sqrt(mesh_tyre * scale * mesh_tyre) = mesh_tyre * sqrt(scale)
        f_rim  = sqrt(mesh_rim  * scale * mesh_rim)  = mesh_rim  * sqrt(scale)

    The record therefore moves by ``sqrt(scale)`` while the screen moves by
    ``scale``.  Multiplying the record by ``scale`` instead - which is what this
    workbench used to do - draws the wheel ``scale`` times too big, which is
    exactly the "I typed the factor and the wheels exploded" report.

    ``rim_scale`` overrides the rim's factor when a model wants a rim that does
    not follow its tyre (a low-profile swap), and is rarely needed.
    """
    if scale <= 0:
        raise WheelSizeError(f"scale must be positive, not {scale!r}")
    rim_k = scale if rim_scale is None else rim_scale
    return (record_value(mesh_tyre * scale, mesh_tyre),
            record_value(mesh_rim * rim_k, mesh_rim))


def appearance_wheel_block(depot: str, car: str) -> tuple[float, ...] | None:
    """The eight wheel floats of a car's appearance record.

    Looked up by the **appearance id in the spec**, not by the car id or the
    folder name: the three id spaces differ for most cars (ours is car 611,
    appearance 564), and matching on the wrong one silently reports "no record".
    """
    try:
        cid = _car_id(depot, car)
        want = speclib.load_spec(depot, cid).appearance_id() if cid else 0
        _count, records = appearlib.load(depot)
    except Exception:  # noqa: BLE001
        return None
    if want:
        for rec in records:
            if rec.id == want:
                return rec.wheel_sizes()
    name = car.encode("ascii", "replace")
    for rec in records:
        if rec.name == name:
            return rec.wheel_sizes()
    return None


def write_appearance_wheel_block(depot: str, car: str, values: dict) -> dict:
    """Write wheel floats into a car's appearance record, in place.

    ``values`` maps float index (0..7) to a new value; anything left out keeps
    what the record already has, so a caller can set only ``f1``/``f2`` and
    leave the four unknowns untouched.  A zero or negative value is skipped for
    the same reason: it means "no opinion", never "set it to nothing".

    Returns ``{"name", "id", "from", "to", "changed"}`` so a caller can log what
    actually moved rather than what it asked for.
    """
    cid = _car_id(depot, car)
    if not cid:
        raise WheelSizeError(f"no spec for {car}, so no appearance id to look up")
    want = speclib.load_spec(depot, cid).appearance_id()
    if not want:
        raise WheelSizeError(f"{car}'s spec names no appearance record")
    path = os.path.join(depot, *appearlib.APPEARANCES.split("/"))
    count, records = appearlib.load(depot)
    rec = next((r for r in records if r.id == want), None)
    if rec is None:
        raise WheelSizeError(f"appearance record {want} is not in the table")
    before = list(rec.wheel_sizes())
    after = list(before)
    for index, value in values.items():
        index = int(index)
        if not (0 <= index < 8) or value is None:
            continue
        value = float(value)
        if value > 0:
            after[index] = value
    # The record stores float32, so a value that came back out of it never
    # compares equal to the same number written as a Python float.  A tolerance
    # is what keeps "write 0.3596 again" from being reported as a change.
    changed = [i for i, (a, b) in enumerate(zip(before, after))
               if abs(a - b) > 1e-6]
    if changed:
        rec.set_wheel_sizes(after)
        appearlib.save(count, records, path)
    return {
        "name": car, "id": want,
        "from": before, "to": after,
        "changed": changed,
    }


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
