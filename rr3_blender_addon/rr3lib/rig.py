"""Decode what a ``.banim`` track actually animates.

Field semantics recovered from the shipped data (see ``README.md``):

* every track owns **six channels**;
* channel *i* lives in curve ``2*i`` (``i = 0..5``);
* channels 0..2 are a **joint position** in metres (raw ``/65536``), in the
  animation space ``x = right, y = forward, z = up``;
* channels 3..5 are a **rotation**: a 16-bit fixed-point angle where
 * ``32768`` counts = 180 degrees (``deg = raw * 180/32768``,
 * ``rad = raw * pi/32768``), interpreted as
  Euler XYZ.  A channel that is not used by the animation holds a constant
  sentinel (``0`` or ``±1.0``), which is why unused tracks read back as
  exactly ``0.0`` or ``±1.0``.

The 15 tracks of the driver bind to the 15 mesh parts of ``driver_lod_*.m3g``
**by index** - the assets store no name binding (the trailer words are not a
hash of any part name, verified).  The binding is confirmed by anatomy: the
tracks form a mirrored, correctly proportioned seated figure whose segment
lengths equal the mesh part lengths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import banim as banimlib

#: Metres per raw position unit.  The same 1/65536 as the wing files - MonkeyTool
#: divides every banim's translation channels by 65536 in ``nodeMatrix``, and the
#: geometry agrees: at 1/65536 the driver is 1.09 m tall (a seated figure) and his
#: hands sit 0.18 m from the steering wheel's centre, i.e. on a rim of radius
#: 0.168-0.178 m.  At 1/32768 he would be 2.17 m tall with his hands 0.35 m
#: outside the wheel.  (``driver.banim`` was documented as 1/32768 for a long
#: time; that was wrong.)
POS_SCALE = 1.0 / 65536.0
ROT_SCALE = math.pi / 32768.0   # rad per raw unit (32768 counts = 180 deg)
CHANNELS = 6

# animation space -> description
AXIS_DOC = "x = right, y = forward, z = up (metres, left-handed in the game)"

# human-readable role of each track index, derived from the driver mesh names
DRIVER_ROLES = [
    "helmet (head)",
    "chest (torso)",
    "pelvis / groin",
    "left upper arm",
    "left forearm",
    "left hand",
    "right upper arm",
    "right forearm",
    "right hand",
    "left thigh",
    "left shin",
    "left foot",
    "right thigh",
    "right shin",
    "right foot",
]

# wing / generic files: roles are unknown beyond the track count
GENERIC_ROLE = "track {i}"

# parent, child, longest mesh axis, is_limb  (driver rig only)
DRIVER_RIG = {
    0: (1, None, "Z", False),    # helmet
    1: (2, 0, "Y", False),       # chest
    2: (None, 1, "Z", False),    # pelvis
    3: (1, 4, "Z", True),        # left upper arm
    4: (3, 5, "Z", True),        # left forearm
    5: (4, None, "Z", False),    # left hand
    6: (1, 7, "Z", True),        # right upper arm
    7: (6, 8, "Z", True),        # right forearm
    8: (7, None, "Z", False),    # right hand
    9: (2, 10, "Z", True),       # left thigh
    10: (9, 11, "Z", True),      # left shin
    11: (10, None, "Y", False),  # left foot
    12: (2, 13, "Z", True),      # right thigh
    13: (12, 14, "Z", True),     # right shin
    14: (13, None, "Y", False),  # right foot
}


@dataclass
class Frame:
    time_ms: float
    parts: list["PartState"] = field(default_factory=list)


@dataclass
class PartState:
    index: int
    name: str
    role: str
    position: tuple[float, float, float]
    rotation_rad: tuple[float, float, float]
    rotation_deg: tuple[float, float, float]
    matrix: list[list[float]]


def channel_curve(track: banimlib.Track, channel: int) -> banimlib.Curve | None:
    idx = channel * 2
    if idx < len(track.curves):
        return track.curves[idx]
    return None


def channel_keys(b: banimlib.Banim, track: banimlib.Track, channel: int):
    c = channel_curve(track, channel)
    if c is None or c.num_keys == 0:
        return []
    return b.keys[c.start_key : c.start_key + c.num_keys]


def sample(keys, t: float) -> float:
    """Linear sample of ``[(time, value)]``; clamps outside the key range."""
    if not keys:
        return 0.0
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    lo, hi = 0, len(keys) - 1
    while lo + 1 < hi:
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


def sample_track(b: banimlib.Banim, track: banimlib.Track, t: float) -> list[float]:
    return [sample(channel_keys(b, track, ch), t) for ch in range(CHANNELS)]


def euler_matrix(rx: float, ry: float, rz: float) -> list[list[float]]:
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return [
        [cy * cz, -cy * sz, sy],
        [sx * sy * cz + cx * sz, -sx * sy * sz + cx * cz, -sx * cy],
        [-cx * sy * cz + sx * sz, cx * sy * sz + sx * cz, cx * cy],
    ]


def part_matrix(pos, rot) -> list[list[float]]:
    r = euler_matrix(*rot)
    return [
        [r[0][0], r[0][1], r[0][2], pos[0]],
        [r[1][0], r[1][1], r[1][2], pos[1]],
        [r[2][0], r[2][1], r[2][2], pos[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def track_names(b: banimlib.Banim, mesh_names: list[str] | None = None) -> list[str]:
    """Part name per track.  Uses the model's mesh names when available."""
    if mesh_names:
        names = sorted(mesh_names)
        if len(names) >= b.num_tracks:
            return names[: b.num_tracks]
    return [f"track{i:02d}" for i in range(b.num_tracks)]


def roles_for(b: banimlib.Banim) -> list[str]:
    if b.num_tracks == len(DRIVER_ROLES):
        return list(DRIVER_ROLES)
    return [GENERIC_ROLE.format(i=i) for i in range(b.num_tracks)]


def is_driver_rig(b: banimlib.Banim) -> bool:
    return b.num_tracks == len(DRIVER_ROLES)


def frame_times(b: banimlib.Banim, fps: float, max_frames: int = 0) -> list[float]:
    dur = b.duration_ms or 0.0
    if fps <= 0:
        return [0.0]
    step = 1000.0 / fps
    n = int(round(dur / step)) + 1
    if max_frames:
        n = min(n, max_frames)
    return [min(dur, i * step) for i in range(max(n, 1))]


def part_state(b: banimlib.Banim, track_idx: int, t: float, name: str, role: str) -> PartState:
    tr = b.tracks[track_idx]
    raw = sample_track(b, tr, t)
    pos = tuple(raw[i] * POS_SCALE for i in range(3))
    rot = tuple(raw[3 + i] * ROT_SCALE for i in range(3))
    return PartState(
        index=track_idx,
        name=name,
        role=role,
        position=pos,
        rotation_rad=rot,
        rotation_deg=tuple(math.degrees(a) for a in rot),
        matrix=part_matrix(pos, rot),
    )


def frames(
    b: banimlib.Banim,
    fps: float = 60.0,
    max_frames: int = 0,
    mesh_names: list[str] | None = None,
) -> list[Frame]:
    names = track_names(b, mesh_names)
    roles = roles_for(b)
    out = []
    for t in frame_times(b, fps, max_frames):
        out.append(
            Frame(
                time_ms=t,
                parts=[
                    part_state(b, i, t, names[i] if i < len(names) else f"track{i}",
                               roles[i] if i < len(roles) else "")
                    for i in range(b.num_tracks)
                ],
            )
        )
    return out


def bone_axis(b: banimlib.Banim, t: float, i: int) -> tuple[tuple, tuple, bool]:
    """Placement hint for part ``i`` at time ``t``.

    Returns ``(origin, direction, is_limb)`` where ``origin`` is where the mesh
    should be centred and ``direction`` is the bone axis the mesh's long side
    should follow.  For non-driver files the joint itself is returned with a
    ``+Z`` direction.
    """
    if not is_driver_rig(b):
        ps = part_state(b, i, t, "", "")
        return ps.position, (0.0, 0.0, 1.0), False
    parent, child, _axis, is_limb = DRIVER_RIG[i]
    cur = part_state(b, i, t, "", "").position
    if child is not None:
        # a part that continues into another joint sits between the two
        nxt = part_state(b, child, t, "", "").position
        origin = tuple((cur[k] + nxt[k]) * 0.5 for k in range(3))
        d = tuple(nxt[k] - cur[k] for k in range(3))
    elif parent is not None:
        prev = part_state(b, parent, t, "", "").position
        origin = cur
        d = tuple(cur[k] - prev[k] for k in range(3))
    else:
        origin = cur
        d = (0.0, 0.0, 1.0)
    n = math.sqrt(sum(v * v for v in d)) or 1.0
    return origin, tuple(v / n for v in d), is_limb


def find_model(banim_path, num_tracks: int | None = None):
    """Best-effort lookup of the ``.m3g`` model a ``.banim`` drives.

    The assets do not store a reference, so this only uses the file layout:
    same folder, same stem (``driver.banim`` -> ``driver_lod_a.m3g``) or a
    common prefix (``..._wing.banim`` -> ``2007_lamborghini_reventon_a.m3g``),
    and - when a track count is known - a model with exactly that many parts.
    """
    import os
    from pathlib import Path

    from . import geometry, m3g as m3glib

    p = Path(banim_path)
    folder = p.parent
    if not folder.is_dir():
        return None
    stem = p.stem
    candidates = sorted(folder.glob("*.m3g"))
    if not candidates:
        return None

    def score(c) -> int:
        s = 0
        cs = c.stem
        if cs == stem or cs.startswith(stem):
            s += 100
        common = 0
        for a, b in zip(stem, cs):
            if a != b:
                break
            common += 1
        s += common
        return s

    scored = sorted(candidates, key=score, reverse=True)
    if num_tracks:
        for c in scored:
            try:
                m = m3glib.M3G(c)
            except Exception:  # noqa: BLE001
                continue
            if len(geometry.all_meshes(m)) == num_tracks:
                return c
        return None
    for c in scored:
        if score(c) > 0:
            return c
    return None


def mesh_names_of(model_path) -> list[str]:
    from . import geometry, m3g as m3glib

    return [md.name for md in geometry.all_meshes(m3glib.M3G(model_path))]


def _fmt(v: float) -> str:
    return f"{v:+.4f}"


def format_report(
    b: banimlib.Banim,
    mesh_names: list[str] | None = None,
    fps: float = 60.0,
    max_frames: int = 0,
) -> str:
    """Human-readable per-part, per-frame position + rotation table."""
    out: list[str] = []
    names = track_names(b, mesh_names)
    roles = roles_for(b)
    out.append("PART ANIMATION (decoded)")
    out.append("=" * 78)
    out.append(f"file          : {b.path}")
    out.append(f"duration      : {b.duration_ms:g} ms")
    out.append(f"tracks        : {b.num_tracks}")
    out.append(f"space         : {AXIS_DOC}")
    out.append("position unit : metres  (raw value / 65536)")
    out.append("rotation unit : DEGREES (raw * 180/32768; 32768 counts = 180 deg),")
    out.append("                Euler XYZ ordered x, y, z")
    out.append("")
    out.append("channel map   : ch0..ch2 = position x/y/z, ch3..ch5 = rotation x/y/z")
    out.append("                (channel i is curve 2*i inside each track)")
    out.append("")
    if "_wing" in b.path.name.lower():
        out.append("NOTE: a *_wing.banim drives a vehicle aero part. Its position")
        out.append("      channels use the same 1/65536 m as everything else, so the")
        out.append("      table below is already the metres the add-on uses.")
        out.append("")
    out.append("track -> part binding")
    out.append("-" * 78)
    out.append(f"{'trk':>3}  {'part / mesh':<34} {'role':<20}")
    for i in range(b.num_tracks):
        out.append(f"{i:3d}  {names[i]:<34} {roles[i] if i < len(roles) else '':<20}")
    if is_driver_rig(b):
        out.append("")
        out.append("(the driver's 15 tracks bind to the 15 mesh parts by index: the")
        out.append(" assets store no name binding, and the mirrored, correctly")
        out.append(" proportioned joint positions confirm this order)")
    out.append("")

    sample_times = frame_times(b, fps, max_frames)
    out.append(f"per-frame values ({fps:g} fps, {len(sample_times)} frames)")
    out.append("-" * 78)
    out.append(f"{'t(ms)':>8}  {'trk':>3}  {'x':>8} {'y':>8} {'z':>8}"
               f"  {'rx°':>8} {'ry°':>8} {'rz°':>8}")
    for t in sample_times:
        for i in range(b.num_tracks):
            ps = part_state(b, i, t, names[i], roles[i])
            px, py, pz = ps.position
            dx, dy, dz = ps.rotation_deg
            out.append(f"{t:8.1f}  {i:3d}  {px:8.4f} {py:8.4f} {pz:8.4f}"
                       f"  {dx:8.2f} {dy:8.2f} {dz:8.2f}")
    out.append("")
    out.append("notes")
    out.append("-" * 78)
    out.append("* rotation channels are small (a few degrees); a channel that stays")
    out.append("  constant at exactly 0.0 or +/-1.0 is an unused sentinel.")
    out.append("* the mesh parts of the driver are stored bone-local, so the position")
    out.append("  above is the joint location the part must be attached to.")
    return "\n".join(out) + "\n"
