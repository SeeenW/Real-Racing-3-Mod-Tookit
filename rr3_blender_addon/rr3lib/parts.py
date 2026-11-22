r"""Part assembly for Real Racing 3 vehicles: wheels and active-aero parts.

WHY THIS MODULE EXISTS
----------------------
A car is split over several ``.m3g`` files.  Static body panels are baked in
*car space* (they already sit where they belong), but every part that moves is
stored **local to its own pivot**: all ``*WHEEL*``/``*TYRE*`` meshes live in
``<car>_shared.m3g`` and are modelled around the origin, and every ``*WING*``
mesh in the body LOD is modelled around the origin too.  Only the game knows
where those pivots are, so the placement must be reconstructed from the two
side files:

* ``<car>.points``  - named anchors; ``POINT_WHEEL_*`` are the wheel mounts.
* ``<car>_wing.banim`` - one track per aero part: constant position + animated
  rotation.

UNITS
-----
* ``.points``            : 1/32 m, space ``(x right, y forward, z up)``
* ``*_wing.banim`` ch0..2: 1/65536 m, same space (verified: 96/96 tracks land
  on the car for every vehicle that ships a wing banim; 1/32768 puts them all
  several metres behind the tail)
* ``*_wing.banim`` ch3..5: 16-bit angle (32768 = 180 deg), Euler XYZ about the same axes
  (verified: the Veyron's airbrake track reads -74.8 deg, its neighbours
  -21.7 deg and -9.5 deg - exactly the real car's airbrake range)

MODEL SPACE
-----------
The ``.m3g`` meshes use ``(x right, y up, z forward)``, so animation space maps
to model space as ``(x, y, z) -> (x, z, -y)``.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from . import banim as banimlib
from . import geometry
from . import m3g as m3glib
from . import points as pointslib

POINT_SCALE = 1.0 / 32.0
POS_SCALE = 1.0 / 65536.0
ROT_SCALE = math.pi / 32768.0   # rad per raw unit (32768 counts = 180 deg)

# animation space (x right, y forward, z up) -> model space (x right, y up, z forward)
ANIM_TO_MODEL = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))


def anim_to_model(p):
    x, y, z = p
    return (x, z, -y)


def rotate_matrix(m, v):
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def transpose(m):
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))


def matmul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def euler_xyz(rx, ry, rz):
    """R = Rz * Ry * Rx, the usual Blender ``Euler('XYZ')`` matrix."""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    rx_m = ((1, 0, 0), (0, cx, -sx), (0, sx, cx))
    ry_m = ((cy, 0, sy), (0, 1, 0), (-sy, 0, cy))
    rz_m = ((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))
    return matmul(rz_m, matmul(ry_m, rx_m))


@dataclass
class WheelMount:
    name: str            # POINT_WHEEL_FL ...
    corner: str          # FL, FR, BL, BR
    position: tuple[float, float, float]   # model space, metres
    steer: bool          # front wheels steer
    raw: tuple[float, float, float] = (0.0, 0.0, 0.0)


def sample_channel(keys, t):
    """Linear interpolation of one channel's ``[(t_ms, raw value), ...]`` list."""
    if not keys:
        return 0.0
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    lo, hi = 0, len(keys) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if keys[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    t0, v0 = keys[lo]
    t1, v1 = keys[hi]
    if t1 == t0:
        return v0
    return v0 + (v1 - v0) * (t - t0) / (t1 - t0)


@dataclass
class AeroPart:
    index: int
    track: int
    mesh_names: list[str]
    pivot: tuple[float, float, float]       # model space, metres, at t = 0
    rest_rotation: tuple[float, float, float]  # radians, animation space, at t = 0
    duration_ms: float = 0.0
    part_name: str | None = None
    # six channels, each a list of (t_ms, raw int value); ch0..2 = pivot position,
    # ch3..5 = Euler XYZ.  Channels have independent key times, so the merged
    # frame list below is the union of all six.
    ch_keys: list[list[tuple[float, float]]] = field(default_factory=list)
    height_offset: float = 0.0

    def frames(self):
        """``[(t_ms, pivot_model_metres, rotation_rad), ...]`` over all key times."""
        times = sorted({t for keys in self.ch_keys for t, _v in keys}) or [0.0]
        out = []
        for t in times:
            v = [sample_channel(keys, t) for keys in self.ch_keys]
            p = anim_to_model(tuple(x * POS_SCALE for x in v[0:3]))
            out.append((t, (p[0], p[1] - self.height_offset, p[2]),
                        tuple(x * ROT_SCALE for x in v[3:6])))
        return out

    def spans(self):
        """``(pos_delta_metres, rot_delta_rad)`` between the first and last frame."""
        fr = self.frames()
        if len(fr) < 2:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        a, b = fr[0], fr[-1]
        pos = tuple(b[1][i] - a[1][i] for i in range(3))
        rot = tuple(b[2][i] - a[2][i] for i in range(3))
        return pos, rot


@dataclass
class WheelSet:
    front_wheel: str | None = None
    front_tyre: str | None = None
    rear_wheel: str | None = None
    rear_tyre: str | None = None
    front_wheel_blur: str | None = None
    rear_wheel_blur: str | None = None
    #: Brake disc; ``rotor_rear`` is the same mesh unless the car has a wider
    #: one of its own (31 cars).  The disc turns with the wheel.
    rotor: str | None = None
    rotor_rear: str | None = None
    #: One caliper mesh per corner, keyed ``FL``/``FR``/``BL``/``BR``.  Each is
    #: modelled in its own corner and does NOT turn with the wheel.
    calipers: dict[str, str] = field(default_factory=dict)
    #: True when ``rear_tyre`` is a mesh of its own (``TYRE_REAR``); False when
    #: the back shares the front tyre and only the rim is wider.
    rear_tyre_own: bool = False
    #: True when ``rear_wheel`` is a mesh of its own (``WHEEL_REAR``).
    rear_wheel_own: bool = False
    #: True when ``rotor_rear`` is a mesh of its own (``ROTOR_REAR``).
    rotor_rear_own: bool = False
    #: True when this LOD's wheel mesh is the whole car's wheels already
    #: assembled in car space (always LOD F: one mesh spanning both sides of the
    #: car, at the real size).  Such a mesh must not be scaled, turned or moved
    #: onto a ``.points`` anchor - it is already where it belongs.
    pre_assembled: bool = False


@dataclass
class Assembly:
    car_dir: str
    car: str
    lod: str
    body_file: str | None = None
    shared_file: str | None = None
    points_file: str | None = None
    wing_banim: str | None = None
    wheel_mounts: list[WheelMount] = field(default_factory=list)
    wheels: WheelSet = field(default_factory=WheelSet)
    aero_parts: list[AeroPart] = field(default_factory=list)
    body_meshes: list[str] = field(default_factory=list)
    aero_meshes: list[str] = field(default_factory=list)
    anchors: list[tuple[str, tuple[float, float, float]]] = field(default_factory=list)
    steering: tuple[float, float, float] | None = None
    height_offset: float = 0.0
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- wheels

WHEEL_ORDER = ("FL", "FR", "BL", "BR")

#: RR3 用 POINT_DRIVER 标记方向盘的位置（驾驶员 lod_c 的手正好落在方向盘上）。
STEERING_ANCHOR = "POINT_DRIVER"


def wheel_mounts(points_path):
    """Return the four wheel mounts, in model space metres."""
    pf = pointslib.load(points_path)
    out = []
    for rec in pf.records:
        if not rec.name.startswith("POINT_WHEEL") or rec.position is None:
            continue
        corner = rec.name.rsplit("_", 1)[-1]
        if corner not in WHEEL_ORDER:
            continue
        raw = tuple(float(v) for v in rec.position)
        pos = anim_to_model(tuple(v * POINT_SCALE for v in raw))
        out.append(WheelMount(rec.name, corner, pos, corner[0] == "F", raw))
    out.sort(key=lambda m: WHEEL_ORDER.index(m.corner))
    return out


def shared_role(name):
    """Role of a ``_shared.m3g`` mesh, and its LOD letter.

    Returns ``(letter, role)`` where ``letter`` is ``"A"``..``"F"`` (or ``None``)
    and ``role`` is one of ``TYRE``, ``TYRE_REAR``, ``WHEEL``, ``WHEEL_REAR``,
    ``ROTOR``, ``ROTOR_REAR``, ``CALIPER_FL``/``FR``/``RL``/``RR``, or ``None``.

    The role is the name with the ``LOD_x_`` prefix and the ``_mm_<tag>`` suffix
    both stripped, so it does not depend on which material tag a mesh happens to
    carry.  That matters: the tyre of a low LOD is often tagged ``_mm_wheel``
    (``LOD_E_TYRE_mm_wheel`` on 230 cars) and 53 cars tag their LOD F rim
    ``_mm_tyre``, so matching the full name - as this module used to - silently
    loses those meshes.  ``BLUR`` meshes are rotation stand-ins and have no role.
    """
    n = name or ""
    letter = None
    if len(n) > 6 and n.startswith("LOD_") and n[5] == "_":
        letter = n[4]
        n = n[6:]
    cut = n.find("_mm_")
    if cut >= 0:
        n = n[:cut]
    if "BLUR" in n:
        return letter, None
    if n in ("TYRE", "TIRE"):
        return letter, "TYRE"
    if n in ("TYRE_REAR", "TIRE_REAR"):
        return letter, "TYRE_REAR"
    if n in ("WHEEL", "WHEEL_REAR", "ROTOR", "ROTOR_REAR"):
        return letter, n
    if n.startswith("BRAKE_CALIPER_"):
        corner = n[len("BRAKE_CALIPER_"):]
        if corner == "FRONT_LEFT":
            return letter, "CALIPER_FL"
        if corner == "FRONT_RIGHT":
            return letter, "CALIPER_FR"
        if corner == "REAR_LEFT":
            return letter, "CALIPER_RL"
        if corner == "REAR_RIGHT":
            return letter, "CALIPER_RR"
    return letter, None


#: Body LODs whose wheels live in a different level of ``_shared.m3g``.
#: LOD G ships no wheel mesh of its own - measured over the 463 shared files,
#: not one has a ``LOD_G_*WHEEL*`` mesh - so it reuses LOD F's, which is the
#: whole car's wheels already assembled in car space.
WHEEL_LOD_FALLBACK = {"G": "F"}

#: Body LODs that ship no wheel at all.  LOD H is the last level (one
#: ``LOD_H_BODY`` mesh, no wheels anywhere in the shared file).
NO_WHEEL_LODS = ("H",)


def wheel_lod_for(lod):
    """Which ``_shared.m3g`` level holds the wheels of body LOD ``lod``."""
    return WHEEL_LOD_FALLBACK.get((lod or "A").upper(), lod)


def wheel_set(shared_m3g_path, lod="A"):
    """Pick the wheel/tyre/brake mesh names for one LOD out of ``_shared.m3g``.

    Matched by :func:`shared_role`, not by full name, so a mesh is found whatever
    material tag it carries.  Strictly per LOD, like the engine: only LOD A and B
    ship a brake disc and calipers, so LOD C and below import as rim and tyre
    only - that is the game's own content, not a missing part.  A few cars (the
    Caterham Seven, for one) have no separate tyre at LOD D or E either; their
    ``WHEEL`` mesh is the whole wheel there, which is why it is the fallback for
    the radius.

    ``pre_assembled`` is set for a LOD whose wheel mesh spans both sides of the
    car (LOD F on all 463 cars): that one is the whole car's wheels, already
    assembled and already at the real size.  ``lod`` is the *body* LOD; it is
    mapped through :func:`wheel_lod_for` first, so LOD G picks up LOD F's
    pre-assembled wheels, and :data:`NO_WHEEL_LODS` (LOD H) returns an empty set.
    """
    if (lod or "A").upper() in NO_WHEEL_LODS:
        return WheelSet()
    lod = wheel_lod_for(lod)
    model = m3glib.M3G(shared_m3g_path)
    roles = {}
    widths = {}
    for obj in model.of_type(14):
        name = obj.data.get("name") or ""
        letter, role = shared_role(name)
        if role is None or letter != lod:
            continue
        roles.setdefault(role, name)
        md = geometry.extract_mesh(model, obj)
        xs = [p[0] for p in md.positions] if md.positions else []
        if xs:
            widths[name] = (min(xs), max(xs))

    ws = WheelSet()
    ws.front_wheel = roles.get("WHEEL")
    ws.front_tyre = roles.get("TYRE")
    ws.rear_wheel_own = "WHEEL_REAR" in roles
    ws.rear_tyre_own = "TYRE_REAR" in roles
    ws.rotor_rear_own = "ROTOR_REAR" in roles
    ws.rear_wheel = roles.get("WHEEL_REAR") or ws.front_wheel
    ws.rear_tyre = roles.get("TYRE_REAR") or ws.front_tyre
    ws.rotor = roles.get("ROTOR")
    ws.rotor_rear = roles.get("ROTOR_REAR") or ws.rotor
    ws.calipers = {}
    for corner, role in (("FL", "CALIPER_FL"), ("FR", "CALIPER_FR"),
                         ("BL", "CALIPER_RL"), ("BR", "CALIPER_RR")):
        if role in roles:
            ws.calipers[corner] = roles[role]
    ws.front_wheel_blur = _blur_name(model, lod, "WHEEL")
    ws.rear_wheel_blur = _blur_name(model, lod, "WHEEL_REAR") or ws.front_wheel_blur
    # A pre-assembled LOD F wheel spans both sides of the car in one mesh.
    for cand in (ws.front_wheel, ws.front_tyre):
        span = widths.get(cand) if cand else None
        if span and span[0] < -0.05 and span[1] > 0.05:
            ws.pre_assembled = True
            break
    return ws


def _blur_name(model, lod, stem):
    """The ``*_BLUR_*`` mesh of one LOD, whatever its material tag is."""
    want = f"LOD_{lod}_{stem}_BLUR"
    for obj in model.of_type(14):
        name = obj.data.get("name") or ""
        if name.split("_mm_")[0] == want:
            return name
    return None


# ----------------------------------------------------------------------- aero parts

def _channel_values(b, track, ch):
    idx = 2 * ch
    if idx >= len(track.curves):
        return []
    curve = track.curves[idx]
    return list(b.keys[curve.start_key:curve.end_key])


def mesh_key_count(obj, model=None):
    """How many keyframes a mesh object carries, from its undecoded tail.

    Every ``.m3g`` mesh object ends with a small block the geometry parser does
    not consume (``obj.data["_unparsed"]``).  It is a keyframe table::

        u32 count
        count x { u32 time, u32 16384, u16 0, f32 value }      (14 bytes each)

    ``4 + count * 14 == _unparsed`` holds for all 106,399 shipped meshes, and
    the four byte form always reads zero.  A mesh with ``count > 0`` is one the
    engine animates; a mesh with no tail or an empty table is static.  This is
    the only per-mesh evidence in the files that says which part a wing track
    drives, so it is what :func:`aero_parts` pairs on.
    """
    import struct as _struct

    n = obj.data.get("_unparsed") or 0
    if n <= 4:
        return 0
    if model is None:
        return 1
    try:
        return _struct.unpack_from("<I", model.buf, obj.offset + obj.length - n)[0]
    except _struct.error:
        return 1


def _track_rotates(b, track):
    """True when any rotation channel of ``track`` actually changes."""
    for ch in (3, 4, 5):
        vals = [v for _t, v in _channel_values(b, track, ch)]
        if len(vals) > 1 and len({round(v, 6) for v in vals}) > 1:
            return True
    return False


def _pair_by_keyframes(part_names, moving, tracks, rotates):
    """Assign tracks to parts so "animated mesh" lands on "animated track".

    Name order alone is what the reference tool uses, and it is right for most
    cars - but not for all of them: the McLaren P1 keeps the blade's keyframes
    on ``WING_REAR`` and the strut's track is the constant one, while the banim
    happens to list the constant track first.  Pairing by name then swaps the
    two and the blade follows the strut's track (reported 2026-10-28).

    ``moving[i]`` says whether ``part_names[i]`` carries keyframes and
    ``rotates[j]`` whether ``tracks[j]`` animates its rotation.  Returns the
    permutation of track indexes with the highest number of agreeing pairs;
    ties keep name order, so a car where every part moves is unaffected.
    """
    import itertools

    order = list(range(len(tracks)))
    if len(order) < 2 or len(order) > 6:
        return order
    best, best_score = order, -1
    for perm in itertools.permutations(order):
        score = sum(1 for i, j in enumerate(perm) if moving[i] == rotates[j])
        if score > best_score:
            best, best_score = list(perm), score
    return best


def aero_parts(body_m3g_path, wing_banim_path, height_offset=0.0):
    """Pair every moving wing part of the body LOD with a track of the wing banim.

    A wing part is split over several meshes, one per material tag
    (``LOD_A_WING_REAR_LEFT_mm_ext``, ``..._mm_misc``, ``..._mm_chassis`` ...),
    so meshes are grouped by the name with the ``_mm_<tag>`` suffix removed.

    The groups then match the banim tracks 1:1, but **not reliably in name
    order**.  Each mesh object carries its own keyframe table (see
    :func:`mesh_key_count`), which tells us directly whether the engine animates
    that part, and each track tells us whether it animates its rotation.  Those
    two facts are matched up first; name order is the fallback and the tie
    breaker, so cars where every part moves are paired exactly as before.
    """
    model = m3glib.M3G(body_m3g_path)
    groups = {}
    moving = {}
    for obj in model.of_type(14):
        name = obj.data.get("name") or ""
        if "WING" not in name.upper():
            continue
        base = name
        marker = base.find("_mm_")
        if marker >= 0:
            base = base[:marker]
        groups.setdefault(base, []).append(name)
        if mesh_key_count(obj, model) > 0:
            moving[base] = True
        else:
            moving.setdefault(base, False)
    bases = sorted(groups)
    b = banimlib.load(wing_banim_path)
    tracks = b.tracks

    # Which base names are animation nodes?  The candidates, best first:
    #
    # 1. every base, when that already matches the track count - this is the
    #    normal case and keeps the Evija's four independent flaps apart;
    # 2. the roots only, when folding sub-parts gets us to the track count;
    # 3. every base except the "_BRAKES" riders - a wing brake light is modelled
    #    as its own part but rides on the wing, and some cars have one without
    #    the animation having a node for it (MP4-12C, 675LT, Ford GT);
    # 4. the roots again, letting the caller clamp (the reference tool's
    #    fallback: 2 roots against 3 nodes keeps the first two in name order).
    roots = [x for x in bases
             if not any(o != x and x.startswith(o + "_") for o in bases)]
    roots.sort()
    riders = [x for x in bases if not x.endswith("_BRAKES")]
    candidates = [bases, roots, riders]
    part_names = None
    for cand in candidates:
        if cand and len(cand) == len(tracks):
            part_names = cand
            break
    if part_names is None:
        if len(roots) < len(tracks) and len(bases) <= len(tracks):
            part_names = bases
        else:
            part_names = roots if roots else bases

    members = {}
    for x in bases:
        best, best_len = None, 0
        for r in part_names:
            if (x == r or x.startswith(r + "_")) and len(r) > best_len:
                best, best_len = r, len(r)
        if best is not None:
            members.setdefault(best, []).append(x)
    mesh_groups = {r: [n for x in members.get(r, []) for n in groups[x]]
                   for r in part_names}
    part_moving = {r: any(moving[x] for x in members.get(r, [])) for r in part_names}

    warn = None
    if len(part_names) == len(tracks):
        order = _pair_by_keyframes(
            part_names,
            [part_moving[r] for r in part_names],
            tracks,
            [_track_rotates(b, t) for t in tracks],
        )
    else:
        warn = (f"{len(bases)} wing parts {bases} vs "
                f"{len(tracks)} banim tracks")
        order = list(range(len(tracks)))

    parts = []
    for i in range(len(tracks)):
        # Part ``i`` (name order) takes track ``order[i]``; everything that
        # describes the motion - pivot, rest rotation, the six curves - comes
        # from that track, and the mesh names come from the part.
        tr = tracks[order[i]] if i < len(order) else tracks[i]
        ch_keys = [[(t, v) for t, v in _channel_values(b, tr, c)] for c in range(6)]

        def first(idx):
            return ch_keys[idx][0][1] if ch_keys[idx] else 0.0

        pivot = anim_to_model(tuple(first(c) * POS_SCALE for c in range(3)))
        pivot = (pivot[0], pivot[1] - height_offset, pivot[2])
        rest_rot = tuple(first(c) * ROT_SCALE for c in range(3, 6))
        names = mesh_groups.get(part_names[i], []) if i < len(part_names) else []
        parts.append(AeroPart(
            index=i,
            track=tr.index,
            mesh_names=list(names),
            pivot=pivot,
            rest_rotation=rest_rot,
            duration_ms=b.duration_ms,
            part_name=part_names[i] if i < len(part_names) else None,
            ch_keys=ch_keys,
            height_offset=height_offset,
        ))
    return parts, warn


# ---------------------------------------------------------------------- whole plan

def build_plan(car_dir, car, lod="A"):
    """Collect everything needed to assemble one car in Blender.

    ``lod`` is normally a body level (``A``..``H``).  ``shared``, ``int_a`` and
    ``int_b`` are complete models rather than body levels, so no wheels, aero or
    car anchors are planned for them - the importer assembles nothing around a
    model that is not a car.
    """
    a = Assembly(car_dir=car_dir, car=car, lod=lod)
    body = os.path.join(car_dir, f"{car}_{lod.lower()}.m3g")
    shared = os.path.join(car_dir, f"{car}_shared.m3g")
    pts = os.path.join(car_dir, f"{car}.points")
    wing = os.path.join(car_dir, f"{car}_wing.banim")
    a.body_file = body if os.path.exists(body) else None
    standalone = (lod or "").lower() in ("shared", "int_a", "int_b")
    a.shared_file = None if standalone else (shared if os.path.exists(shared) else None)
    a.points_file = pts if os.path.exists(pts) else None
    a.wing_banim = None if standalone else (wing if os.path.exists(wing) else None)
    if not a.body_file:
        a.warnings.append(f"missing body LOD {lod}")
        return a
    if standalone:
        a.points_file = None
        if lod.lower().startswith("int"):
            int_pts = os.path.join(car_dir, f"{car}_int.points")
            if os.path.exists(int_pts):
                a.points_file = int_pts

    model = m3glib.M3G(a.body_file)
    a.body_meshes = [obj.data.get("name") or "" for obj in model.of_type(14)]

    if a.points_file:
        a.wheel_mounts = wheel_mounts(a.points_file)
    elif not standalone:
        a.warnings.append("missing .points: wheel mounts unknown")

    # The .points file, the meshes and the wing banim all share ONE datum: the
    # model origin sits on the ground.  Measured over the body LODs, the lowest
    # body vertex is y = 0.10 .. 0.18 m and the hub heights from .points are
    # y = 0.32 .. 0.34 m, i.e. exactly a tyre radius above zero - the wheels
    # stand on y = 0.  So there is no height to subtract.
    #
    # Earlier versions subtracted the mean hub height here, which sank every
    # wheel pivot to y ~ 0 and lifted every anchor by the axle height; that is
    # the "wheels are in the wrong place" bug reported on 2026-10-27.
    a.height_offset = 0.0
    if a.points_file:
        pf = pointslib.load(a.points_file)
        for rec in pf.records:
            if rec.position is not None:
                p = anim_to_model(tuple(v * POINT_SCALE for v in rec.position))
                a.anchors.append((rec.name, p))
                if rec.name == STEERING_ANCHOR:
                    a.steering = p

    if a.shared_file:
        a.wheels = wheel_set(a.shared_file, lod)
        if not a.wheels.front_wheel and (lod or "A").upper() not in NO_WHEEL_LODS:
            a.warnings.append(f"no LOD_{lod} wheel mesh in _shared.m3g")
    elif not standalone:
        a.warnings.append("missing _shared.m3g: no wheel/tyre meshes")
    if a.wing_banim:
        # The wing banim pivots are already in model space, like the meshes and
        # the .points anchors, so no offset is applied anywhere any more.
        parts, warn = aero_parts(a.body_file, a.wing_banim, 0.0)
        a.aero_parts = parts
        for p in parts:
            a.aero_meshes.extend(p.mesh_names)
        if warn:
            a.warnings.append("aero pairing: " + warn)
    elif not standalone:
        a.warnings.append("missing _wing.banim: no active-aero animation")
    return a


def wheel_radius(shared_m3g_path, mesh_name):
    """Tyre radius in metres (half the larger of the two round dimensions)."""
    model = m3glib.M3G(shared_m3g_path)
    for obj in model.of_type(14):
        if (obj.data.get("name") or "") != mesh_name:
            continue
        md = geometry.extract_mesh(model, obj)
        bb = md.bbox
        if not bb:
            return None
        lo, hi = bb
        return max(hi[1] - lo[1], hi[2] - lo[2]) / 2.0
    return None


def format_report(a, show_keys=0):
    lines = [f"ASSEMBLY PLAN  {a.car}  LOD {a.lod}",
             f"  body   : {os.path.basename(a.body_file) if a.body_file else '-'}",
             f"  shared : {os.path.basename(a.shared_file) if a.shared_file else '-'}",
             f"  points : {os.path.basename(a.points_file) if a.points_file else '-'}",
             f"  banim  : {os.path.basename(a.wing_banim) if a.wing_banim else '-'}",
             "", "WHEELS"]
    for m in a.wheel_mounts:
        lines.append(f"  {m.corner}  {m.name:22s} model=({m.position[0]:7.3f},"
                     f" {m.position[1]:6.3f}, {m.position[2]:7.3f}) m"
                     f"{'   steers' if m.steer else ''}")
    ws = a.wheels
    lines.append(f"  meshes: wheel {ws.front_wheel} / rear {ws.rear_wheel} / "
                 f"tyre {ws.front_tyre} / blur {ws.front_wheel_blur}")
    lines.append("")
    lines.append("ACTIVE AERO")
    for p in a.aero_parts:
        dpos, drot = p.spans()
        lines.append(f"  track {p.track}  pivot=({p.pivot[0]:7.3f}, {p.pivot[1]:6.3f}, "
                     f"{p.pivot[2]:7.3f}) m  rest=({math.degrees(p.rest_rotation[0]):6.2f},"
                     f" {math.degrees(p.rest_rotation[1]):6.2f},"
                     f" {math.degrees(p.rest_rotation[2]):6.2f}) deg  meshes={p.mesh_names}")
        lines.append(f"      travel dpos=({dpos[0]:+.3f}, {dpos[1]:+.3f}, {dpos[2]:+.3f}) m"
                     f"  drot=({math.degrees(drot[0]):+.2f}, {math.degrees(drot[1]):+.2f},"
                     f" {math.degrees(drot[2]):+.2f}) deg  frames={len(p.frames())}")
        for t, pos, rot in p.frames()[:show_keys]:
            lines.append(f"      t={t:8.1f} ms  pos=({pos[0]:6.3f}, {pos[1]:6.3f}, {pos[2]:6.3f})"
                         f"  rot=({math.degrees(rot[0]):7.2f},"
                         f" {math.degrees(rot[1]):7.2f}, {math.degrees(rot[2]):7.2f}) deg")
    for w in a.warnings:
        lines.append(f"  ! {w}")
    return "\n".join(lines)
