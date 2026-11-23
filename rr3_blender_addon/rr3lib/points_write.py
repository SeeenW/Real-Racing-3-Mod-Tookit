"""RR3 ``.points`` writer: build a file from anchors, or edit one in place.

The reader is :mod:`rr3lib.points`; this module is its mirror.  Everything it
emits was validated by round-tripping all 927 shipped files byte for byte
(:func:`selftest`), so a rebuilt file is indistinguishable from the original.

Layout (little endian, nothing padded)::

    u16  version          2
    u16  recordCount
    recordCount x record:
        u16 type          0 point, 1 spline, 2 hinge, 3 transform
        u16 size          payload length (name + extra), NOT counting these 4 bytes
        cstr name
        extra             type dependent, see below
    u16  overrideCount
    overrideCount x (cstr name, cstr value)

Extra data per type::

    0 point      3 f32  position, engine units (1 m = 32)
    1 spline     u16 count, count x (u16 npts, npts x 3 f32)
    2 hinge      3 f32 position + 9 f32 row-major 3x3 orientation
    3 transform  16 f32 row-major 4x4, last column = translation (w = 1)

UNITS AND AXES
--------------
Everything in the file is *engine space*: metres x 32, axes
``(x right, y forward, z up)``, origin on the ground at the car's centreline.

Blender space is ``(x right, y forward, z up)`` too, but with the nose along
-Y for imported .m3g models - the importer applies ``_anchor_to_blender``
``(x, -y, z)`` plus a rig level 180 deg turn.  The exporter therefore undoes
exactly that: see :func:`blender_to_engine` / :func:`engine_to_blender`.

OVERRIDES
---------
The trailing table carries free-form text per anchor name.  Known keys:

    SCALE 0.7                 light sprite size
    RGB 255,248,192           light colour
    INTENSITY 0.4             light intensity
    MapChannel:1 = UVChannel_1   wheel texture channel mapping
    LastPose = undefined      (only seen on POINT_DRIVER style anchors)
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

from . import points as pointslib

#: 1 metre == 32 engine units.
SCALE = pointslib.POINT_SCALE


class PointsWriteError(Exception):
    pass


# --------------------------------------------------------------------- axes
def engine_to_blender(p, convert: bool = True):
    """Engine space metres -> Blender metres (matches the addon importer)."""
    x, y, z = p
    return (x, -y, z) if convert else (x, y, z)


def blender_to_engine(p, convert: bool = True):
    """Blender metres -> engine space metres (inverse of the above)."""
    x, y, z = p
    return (x, -y, z) if convert else (x, y, z)


def _euler_to_matrix(rot):
    """``(rx, ry, rz)`` radians, ``Rz @ Ry @ Rx`` - same order as Blender XYZ."""
    rx, ry, rz = rot
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )


def matrix_to_euler(m):
    """Row-major 3x3 -> ``(rx, ry, rz)`` radians, inverse of the above."""
    sy = -m[2][0]
    sy = max(-1.0, min(1.0, sy))
    ry = math.asin(sy)
    if abs(m[2][0]) < 0.999999:
        rx = math.atan2(m[2][1], m[2][2])
        rz = math.atan2(m[1][0], m[0][0])
    else:  # gimbal lock
        rx = math.atan2(-m[1][2], m[1][1])
        rz = 0.0
    return (rx, ry, rz)


# ------------------------------------------------------------------- records
@dataclass
class Anchor:
    """One record of a ``.points`` file, in engine space metres."""

    name: str
    #: "point" | "hinge" | "spline" | "transform"
    kind: str = "point"
    #: engine space metres ``(x right, y forward, z up)``
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: hinge only: row-major 3x3, rows are the local axes
    orientation: tuple[float, ...] | None = None
    #: hinge only: rotation in radians, converted to ``orientation`` on write
    rotation: tuple[float, float, float] | None = None
    #: spline only: list of vertex lists, each in engine space metres
    splines: list[list[tuple[float, float, float]]] = field(default_factory=list)
    #: transform only: 16 floats row-major, translation in metres
    transform: tuple[float, ...] | None = None
    #: keep an unknown payload verbatim (never written unless the type is unknown)
    raw: bytes = b""

    def resolved_orientation(self):
        if self.orientation is not None:
            return tuple(float(v) for v in self.orientation)
        if self.rotation is not None:
            m = _euler_to_matrix(self.rotation)
            return tuple(v for row in m for v in row)
        return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


@dataclass
class PointsDoc:
    """A whole ``.points`` file: records plus the override table."""

    records: list[Anchor] = field(default_factory=list)
    overrides: list[tuple[str, str]] = field(default_factory=list)
    version: int = 2
    #: Whether the trailing ``u16 overrideCount`` is present at all.  The
    #: shipped data is inconsistent: 769 files end with a ``0`` count, but 44
    #: (all the 0-record ``wheel_*.points``) simply stop after the records.
    #: Kept so a round trip is byte exact; new files always write the field.
    override_field: bool = True

    # ---- convenience ---------------------------------------------------
    def add(self, anchor: Anchor) -> Anchor:
        self.records.append(anchor)
        return anchor

    def find(self, name: str) -> Anchor | None:
        for a in self.records:
            if a.name == name:
                return a
        return None

    def remove(self, name: str) -> bool:
        for i, a in enumerate(self.records):
            if a.name == name:
                del self.records[i]
                return True
        return False

    def names(self) -> list[str]:
        return [a.name for a in self.records]

    def set_override(self, name: str, value: str) -> None:
        for i, (n, _v) in enumerate(self.overrides):
            if n == name:
                self.overrides[i] = (name, value)
                return
        self.overrides.append((name, value))

    # ---- conversion ----------------------------------------------------
    def to_bytes(self) -> bytes:
        return build(self)


# ------------------------------------------------------------------ building
_TYPE_ID = {"point": 0, "spline": 1, "hinge": 2, "transform": 3}


def _cstr(text: str) -> bytes:
    b = text.encode("ascii", "replace")
    if b"\0" in b:
        raise PointsWriteError(f"name contains NUL: {text!r}")
    return b + b"\0"


def _pack_extra(a: Anchor) -> bytes:
    kind = a.kind.lower()
    if kind not in _TYPE_ID:
        if not a.raw:
            raise PointsWriteError(f"unknown anchor kind {a.kind!r}")
        return a.raw
    if kind == "point":
        x, y, z = a.position
        return struct.pack("<3f", x * SCALE, y * SCALE, z * SCALE)
    if kind == "hinge":
        x, y, z = a.position
        m = a.resolved_orientation()
        if len(m) != 9:
            raise PointsWriteError(f"{a.name}: hinge needs 9 orientation floats")
        return struct.pack("<12f", x * SCALE, y * SCALE, z * SCALE, *m)
    if kind == "spline":
        out = bytearray(struct.pack("<H", len(a.splines)))
        for pts in a.splines:
            out += struct.pack("<H", len(pts))
            for p in pts:
                out += struct.pack("<3f", p[0] * SCALE, p[1] * SCALE, p[2] * SCALE)
        return bytes(out)
    # transform
    t = a.transform
    if t is None:
        x, y, z = a.position
        t = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0,
             x * SCALE, y * SCALE, z * SCALE, 1.0)
    if len(t) != 16:
        raise PointsWriteError(f"{a.name}: transform needs 16 floats")
    t = list(t)
    t[12] *= SCALE
    t[13] *= SCALE
    t[14] *= SCALE
    return struct.pack("<16f", *t)


def build(doc: PointsDoc) -> bytes:
    """Serialise a :class:`PointsDoc` to ``.points`` bytes."""
    out = bytearray(struct.pack("<HH", doc.version, len(doc.records)))
    for a in doc.records:
        extra = _pack_extra(a)
        payload = _cstr(a.name) + extra
        if len(payload) > 0xFFFF:
            raise PointsWriteError(f"{a.name}: record payload {len(payload)} > 65535")
        out += struct.pack("<HH", _TYPE_ID.get(a.kind.lower(), 255), len(payload))
        out += payload
    if doc.override_field or doc.overrides:
        out += struct.pack("<H", len(doc.overrides))
        for name, value in doc.overrides:
            out += _cstr(name) + _cstr(value)
    return bytes(out)


# ------------------------------------------------------------------- reading
def from_points(pf: pointslib.PointsFile) -> PointsDoc:
    """Convert a parsed file into an editable :class:`PointsDoc` (metres)."""
    doc = PointsDoc(version=pf.version, override_field=pf.override_field)
    for r in pf.records:
        kind = pointslib.TYPE_NAMES.get(r.type, "unknown")
        a = Anchor(name=r.name, kind=kind if kind != "unknown" else "unknown")
        if r.position is not None:
            a.position = tuple(v / SCALE for v in r.position)
        if r.matrix is not None:
            a.orientation = tuple(r.matrix)
        if r.splines:
            a.splines = [[tuple(v / SCALE for v in p) for p in lst] for lst in r.splines]
        if r.transform is not None:
            t = list(r.transform)
            t[12] /= SCALE
            t[13] /= SCALE
            t[14] /= SCALE
            a.transform = tuple(t)
        if kind == "unknown":
            a.raw = r.raw
        doc.records.append(a)
    doc.overrides = [(o.name, o.value) for o in pf.overrides]
    return doc


def load(path: str) -> PointsDoc:
    """Read a ``.points`` file into an editable document."""
    return from_points(pointslib.load(path))


def save(doc: PointsDoc, path: str) -> int:
    """Write a document to ``path``; returns the byte size."""
    blob = build(doc)
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)


# --------------------------------------------------------------- validation
#: The 79 anchor names the engine actually knows (``0x01EEB458`` in the .so).
#: Anything else is silently ignored at runtime - see docs/points-格式.md.
ENGINE_POINTS = (
    "POINT_WHEEL_FL", "POINT_WHEEL_FR", "POINT_WHEEL_BL", "POINT_WHEEL_BR",
    "POINT_WHEEL_FL_PIVOT", "POINT_WHEEL_FR_PIVOT", "POINT_STEERING_WHEEL",
    "POINT_DRIVER", "POINT_NEEDLE_SPEED", "POINT_NEEDLE_RPM",
    "POINT_STEERING_WHEEL_NEEDLE_SPEED", "POINT_STEERING_WHEEL_NEEDLE_RPM",
    "POINT_BRAKELIGHT_LEFT", "POINT_BRAKELIGHT_RIGHT", "POINT_BRAKELIGHT_CENTER",
    "POINT_HEADLIGHT_LEFT", "POINT_HEADLIGHT_RIGHT", "POINT_GEARSTICK",
    "POINT_GEARSTICK_HAND", "POINT_INTERIOR_HUD", "POINT_EXHAUST",
    "POINT_STEERING_ARM_ANCHOR_PIVOT_LEFT", "POINT_STEERING_ARM_ANCHOR_PIVOT_RIGHT",
    "POINT_STEERING_STRUT_LEFT_END", "POINT_STEERING_STRUT_RIGHT_END",
    "POINT_NET_CENTER", "POINT_UNDERBODY_SPARKS", "POINT_NEEDLE_LINEAR_SPEED",
    "POINT_NEEDLE_LINEAR_RPM", "POINT_STEERING_WHEEL_NEEDLE_LINEAR_SPEED",
    "POINT_STEERING_WHEEL_NEEDLE_LINEAR_RPM", "POINT_LIGHTBAR_FRONT",
    "POINT_LIGHTBAR_REAR", "POINT_LIGHTBAR_LEFT", "POINT_LIGHTBAR_RIGHT",
    "POINT_LIGHTBAR_CENTER_FRONT", "POINT_LIGHTBAR_CENTER_REAR",
    "HINGE_REARBUMPER_LEFT", "HINGE_REARBUMPER_RIGHT",
    "HINGE_FRONTBUMPER_LEFT", "HINGE_FRONTBUMPER_RIGHT",
    "HINGE_MIRROR_LEFT", "HINGE_MIRROR_RIGHT", "HINGE_HOOD_LEFT",
    "HINGE_HOOD_RIGHT", "HINGE_BOOT_LEFT", "HINGE_BOOT_RIGHT",
    "HINGE_DOOR_LEFT", "HINGE_DOOR_RIGHT", "HINGE_GULLDOOR_LEFT",
    "HINGE_GULLDOOR_RIGHT", "HINGE_DOOR_LEFT_REAR", "HINGE_DOOR_RIGHT_REAR",
    "HINGE_NEEDLE_SPEED", "HINGE_NEEDLE_RPM",
    "HINGE_STEERING_WHEEL_NEEDLE_SPEED", "HINGE_STEERING_WHEEL_NEEDLE_RPM",
    "HINGE_STEERING_WHEEL", "HINGE_STRUT_LOWER_FRONT_LEFT",
    "HINGE_STRUT_UPPER_FRONT_LEFT", "HINGE_STRUT_LOWER_FRONT_RIGHT",
    "HINGE_STRUT_UPPER_FRONT_RIGHT", "HINGE_STRUT_LOWER_REAR_RIGHT",
    "HINGE_STRUT_UPPER_REAR_RIGHT", "HINGE_STRUT_LOWER_REAR_LEFT",
    "HINGE_STRUT_UPPER_REAR_LEFT", "HINGE_AXEL_REAR_RIGHT",
    "HINGE_AXEL_REAR_LEFT", "HINGE_STEERING_ARM_LEFT", "HINGE_STEERING_ARM_RIGHT",
    "HINGE_STEERING_ARM_ANCHOR_LEFT", "HINGE_STEERING_ARM_ANCHOR_RIGHT",
    "HINGE_HOOD_WING_LEFT", "HINGE_HOOD_WING_RIGHT",
    "HINGE_WING_REAR_LEFT", "HINGE_WING_REAR_RIGHT", "HINGE_WING_REAR",
    "HINGE_DRIVER", "HINGE_FAN",
)


def engine_name(name: str) -> str | None:
    """Match ``name`` against the engine table using the prefix+index rule.

    The engine accepts ``POINT_HEADLIGHT_LEFT_01`` .. ``_09`` for the single
    known anchor ``POINT_HEADLIGHT_LEFT``, so a trailing run of digits (and a
    separating ``_``) is stripped before the lookup.
    """
    if name in ENGINE_POINTS:
        return name
    base = name.rstrip("0123456789").rstrip("_")
    if base in ENGINE_POINTS:
        return base
    return None


def validate(doc: PointsDoc) -> list[str]:
    """Return human readable warnings about a document."""
    out: list[str] = []
    seen = set()
    for a in doc.records:
        if a.name in seen:
            out.append(f"duplicate anchor name {a.name!r} (last one wins in game)")
        seen.add(a.name)
        if engine_name(a.name) is None:
            out.append(
                f"{a.name!r} is not one of the 79 engine anchors - "
                f"the game will ignore it"
            )
        if a.kind == "hinge" and a.orientation is None and a.rotation is None:
            out.append(f"{a.name}: hinge without orientation, using identity")
        if a.kind == "spline" and not a.splines:
            out.append(f"{a.name}: spline with no points")
    for n, _v in doc.overrides:
        if engine_name(n) is None:
            out.append(f"override for unknown anchor {n!r}")
    return out


# ----------------------------------------------------------------- self test
def selftest(depot: str | None = None, limit: int = 0) -> int:
    """Round-trip every shipped ``.points`` file and report mismatches."""
    import glob
    import os

    if not depot:
        depot = os.environ.get("RR3_DEPOT", "")
    if not depot or not os.path.isdir(depot):
        print("points_write selftest: no depot (set RR3_DEPOT)")
        return 2
    files = sorted(glob.glob(os.path.join(depot, "**", "*.points"), recursive=True))
    if limit:
        files = files[:limit]
    bad = 0
    for p in files:
        raw = open(p, "rb").read()
        try:
            doc = load(p)
            back = build(doc)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {os.path.basename(p)}: {exc}")
            bad += 1
            continue
        if back != raw:
            n = min(len(back), len(raw))
            at = next((i for i in range(n) if back[i] != raw[i]), n)
            print(f"FAIL {os.path.basename(p)}: {len(raw)} -> {len(back)}, "
                  f"first diff at {at}")
            bad += 1
    print(f"points_write selftest: {len(files)} files, {bad} failures")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
