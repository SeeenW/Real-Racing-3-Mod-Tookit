"""Blender scene -> RR3 files: ``.points``, ``.banim`` and ``_animations.xml``.

The importers live in ``__init__.py``; this module is their mirror image.  Three
facts make the round trip exact:

**The animation basis is already Blender's basis.**  The game stores a part pose
in *animation* space (x right, y forward, z up) and the mesh in *model* space
(Y up).  The two are related by ``ANIM_TO_MODEL = (x, z, -y)``, and the importer
maps model space to Blender with ``cm = (x, -z, y)``.  Those two cancel exactly
(``cm @ ANIM_TO_MODEL == identity``), which is why an ``AERO_*`` empty's
``location``/``rotation_euler`` *are* the engine values in metres and radians.
No conversion is needed on the way out.

**Anchors are not in that basis.**  ``.points`` positions are engine metres and
the importer puts them at ``Rot180Z @ engine`` (it applies ``(x, -y, z)`` and
then mirrors X).  So exporting is ``engine = Rot180Z @ blender`` - the same
rotation, because a 180 deg turn about Z is its own inverse.

**A ``.banim`` track is one part, not one bone.**  Each track holds six channels
(position XYZ, Euler XYZ) and the meshes are modelled at their rest pose, so the
stored angles are a delta the engine adds.  Whatever the empty does between
frame 1 and the last frame is what gets written.
"""

from __future__ import annotations

import math
import os
import struct

import bpy
from mathutils import Euler, Matrix, Vector

from .rr3lib import animxml as animxmllib
from .rr3lib import banim as banimlib
from .rr3lib import banim_write as banimw
from .rr3lib import points_write as pointsw

#: ``.points`` positions are authored in a frame turned 180 deg about Z.
POINTS_E2B = Matrix.Rotation(math.pi, 3, "Z")

#: Frame numbers are 1 based in Blender, 0 ms in the file.
FRAME_BASE = 1


class ExportError(Exception):
    pass


# ---------------------------------------------------------------- properties
def _prop(ob, key, default=None):
    try:
        return ob[key]
    except (KeyError, TypeError):
        return default


def _has(ob, key) -> bool:
    try:
        ob[key]
        return True
    except (KeyError, TypeError):
        return False


def _meshes(objects=None):
    if objects is None:
        objects = bpy.context.scene.objects
    return [ob for ob in objects if ob.type == "MESH"]


def _empties(objects=None):
    if objects is None:
        objects = bpy.context.scene.objects
    return [ob for ob in objects if ob.type == "EMPTY"]


# --------------------------------------------------------------------- points
def _anchor_position(ob) -> Vector:
    """Where an anchor goes in the file, in the file's own units.

    A ``.points`` position is metres in *animation* space (x right, y forward,
    z up) times 32, and animation space and Blender's axes agree - the same
    identity that lets a ``.banim`` track be written without a conversion.  So
    a Blender rig in the ``.m3g`` convention (nose towards +Y, which is what
    ``_M3G_AXIS`` writes out) maps straight through: no rotation.

    Two things have to be handled before that:

    * An anchor that came from a file carries ``rr3_point_raw``, the numbers it
      was read from.  Writing those back is the only way a round trip is exact,
      and it is also the only way to keep a file authored in the older FBX
      convention (nose towards -Y) intact - the importer places those rotated,
      and rotating them again on the way out would put the front-left anchor on
      the back-right.
    * ``ANCHOR_*`` empties the vehicle importer parents to the rig are already
      in the model frame, so they need nothing either.

    **Unless the anchor has been moved.**  Keeping the original numbers is
    right for an untouched anchor and wrong for a nudged one, so the importer
    also records where it put the empty (``rr3_point_loc``).  If the empty is
    still there the file's own numbers win; if it is not, the empty's location
    is what the user just dragged and it is what gets written.

    This only holds for the default *Model space* import, which is the frame
    the exporter writes back.  Anchors imported against an FBX rig are placed
    in that rig's frame, so moving one there and exporting would land it
    somewhere else - the original numbers are kept instead.
    """
    raw = str(_prop(ob, "rr3_point_raw", "") or "")
    if raw:
        try:
            vals = [float(v) for v in raw.split()]
        except ValueError:
            vals = []
        if len(vals) == 3:
            # the property holds the file's own numbers (1/32 m); ``Anchor``
            # wants metres and multiplies by ``SCALE`` on the way out
            kept = Vector(vals) / pointsw.SCALE
            where = str(_prop(ob, "rr3_point_loc", "") or "")
            try:
                placed = [float(v) for v in where.split()]
            except ValueError:
                placed = []
            if len(placed) == 3 and (Vector(placed) - Vector(ob.location)).length > 1e-5:
                return Vector(ob.location)      # the user moved it
            return kept
    return Vector(ob.location)


def _hinge_orientation(ob) -> tuple:
    """The 3x3 the file stores for a hinge, from the empty's own rotation.

    A hinge record is a position plus an orientation, and the orientation is
    what decides which way the door swings.  The importer writes that matrix
    onto the empty's ``rotation_euler`` so it is visible and can be dragged, and
    this converts it back.

    The file's own numbers are kept when the empty still carries the rotation
    they produced - nine floats through a euler round trip are not guaranteed to
    land on the same last bit, and a file that changes every time it is opened
    and saved is a file nobody can diff.

    The rotation is read from ``matrix_basis`` rather than
    ``rotation_euler``, so an empty whose rotation mode is Quaternion or Axis
    Angle still exports the angle you see in the viewport instead of a stale
    euler.
    """
    r_bl = ob.matrix_basis.to_quaternion().to_matrix()
    r_e = POINTS_E2B.transposed() @ r_bl @ POINTS_E2B
    got = tuple(r_e[r][c] for r in range(3) for c in range(3))
    stored = str(_prop(ob, "rr3_orientation", "") or "")
    if stored:
        try:
            vals = [float(v) for v in stored.split()]
        except ValueError:
            vals = []
        if len(vals) == 9 and max(abs(a - b) for a, b in zip(vals, got)) < 1e-4:
            return tuple(vals)
    return got


def _basis_to_file(m) -> tuple:
    """A Blender 4x4 as the 16 floats a ``transform`` record stores.

    The two are *not* the same layout.  The file keeps the rotation in the top
    left 3x3 - the same way round as Blender - but puts the translation in the
    **bottom row** (``t[12..14]``), which is a row-vector convention, while
    Blender keeps it in the last column.  Handing the file's matrix straight to
    ``matrix_basis`` therefore loses the translation (the bottom row is not read
    as a translation at all), and reading ``matrix_basis`` back row by row would
    put it at ``t[3], t[7], t[11]``.
    """
    out = []
    for r in range(3):
        out += [m[r][0], m[r][1], m[r][2], 0.0]
    out += [m[0][3], m[1][3], m[2][3], 1.0]
    return tuple(out)


def _transform_matrix(ob) -> tuple:
    """The 16 floats of a ``transform`` record, row major, translation last row.

    ``transform`` exists because a type 0 point cannot express an orientation:
    exhaust and effect anchors use it to say which way the plume points.  The
    matrix is taken from the empty's basis (its own location and rotation, no
    parent), which is the same thing the position comes from, and again the
    file's own numbers win while the empty is untouched.
    """
    got = _basis_to_file(ob.matrix_basis)
    stored = str(_prop(ob, "rr3_transform", "") or "")
    if stored:
        try:
            vals = [float(v) for v in stored.split()]
        except ValueError:
            vals = []
        if len(vals) == 16 and max(abs(a - b) for a, b in zip(vals, got)) < 1e-5:
            return tuple(vals)
    return got


def _file_to_basis(vals) -> Matrix:
    """The inverse of :func:`_basis_to_file`: 16 record floats -> a Blender 4x4.

    The importer needs it as well; it lives here so the two layouts are
    described in one place.
    """
    m = Matrix.Identity(4)
    for r in range(3):
        for c in range(3):
            m[r][c] = float(vals[r * 4 + c])
    m[0][3] = float(vals[12])
    m[1][3] = float(vals[13])
    m[2][3] = float(vals[14])
    return m



def _splines_of(ob):
    """A spline anchor's geometry, parsed back out of ``rr3_splines``.

    The importer stores it as ``list ; point | list ; point`` in the file's own
    1/32 m units, which is lossless; here it becomes metres for
    :class:`points_write.Anchor`, whose writer multiplies by 32 again.
    """
    raw = str(_prop(ob, "rr3_splines", "") or "")
    if not raw.strip():
        return []
    out = []
    for lst in raw.split("|"):
        pts = []
        for chunk in lst.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                vals = [float(v) for v in chunk.replace(",", " ").split()]
            except ValueError:
                continue
            if len(vals) == 3:
                pts.append(tuple(v / pointsw.SCALE for v in vals))
        if pts:
            out.append(pts)
    return out


def points_from_scene(objects=None, *, only_tagged: bool = True,
                      only_selected: bool = False):
    """Collect anchor empties into a :class:`points_write.PointsDoc`.

    An anchor is an empty named ``POINT_*`` / ``HINGE_*`` / ``SPLINE_*`` /
    ``TRANSFORM_*`` or one carrying the ``rr3_point_type`` property the importer
    writes.  The type comes from that property, from the name prefix, or from
    ``rr3_point_type_name``; the *name* comes from ``rr3_point_name`` first, so
    a record that Blender had to rename (``.001`` on a name collision) still
    goes back under its own name.

    Records keep the order they had in the file: the importer stamps
    ``rr3_point_index`` on each empty and the sort below is stable, so anchors
    you add by hand land after the imported ones in the order you made them.

    ``only_selected`` narrows the collection to the selection.  The default is
    the whole scene, because a car's anchors are scattered and nobody selects
    142 empties before every export - but a scene holding two cars' anchors at
    once has no other way to export one of them.
    """
    if objects is None and only_selected:
        objects = bpy.context.selected_objects
    doc = pointsw.PointsDoc()
    scene = bpy.context.scene
    version = _prop(scene, "rr3_points_version", None)
    doc.version = 2 if version is None else int(version)
    # 0 is a real value here ("this file has no override count field"), so it
    # cannot be folded into the default with ``or`` - that turned every such
    # file into a two-byte-longer copy of itself.
    field = _prop(scene, "rr3_points_override_field", None)
    doc.override_field = True if field is None else bool(int(field))
    anchors = []
    for order, ob in enumerate(_empties(objects)):
        tagged = _has(ob, "rr3_point_type")
        named = ob.name.upper().startswith(("POINT_", "HINGE_", "SPLINE_",
                                            "TRANSFORM_"))
        if only_tagged and not (tagged or named):
            continue
        if not (tagged or named):
            continue

        kind = None
        tname = str(_prop(ob, "rr3_point_type_name", "") or "").lower()
        if tname in ("point", "hinge", "spline", "transform"):
            kind = tname
        if kind is None:
            up = ob.name.upper()
            kind = ("hinge" if up.startswith("HINGE_") else
                    "transform" if up.startswith("TRANSFORM_") else
                    "spline" if up.startswith("SPLINE_") else "point")

        name = str(_prop(ob, "rr3_point_name", "") or ob.name)
        if name.startswith("ANCHOR_"):
            name = name[len("ANCHOR_"):]

        pos = _anchor_position(ob)
        a = pointsw.Anchor(name=name, kind=kind, position=tuple(pos))

        if kind == "hinge":
            a.orientation = _hinge_orientation(ob)
        elif kind == "transform":
            a.transform = _transform_matrix(ob)
        elif kind == "spline":
            a.splines = _splines_of(ob)

        index = _prop(ob, "rr3_point_index", None)
        key = int(index) if isinstance(index, int) and index >= 0 else 10 ** 6 + order
        anchors.append((key, order, a, ob))

    anchors.sort(key=lambda row: (row[0], row[1]))
    for _key, _order, a, ob in anchors:
        doc.add(a)
        # the override table (light scale / colour) rides on the record.  Append
        # rather than set_override: a file can override the same *name* twice
        # (four cars ship two POINT_HEADLIGHT_LEFT records and override both),
        # and collapsing those into one entry lost 97 bytes off the end of
        # 2013_astonmartin_gte.points.
        value = _prop(ob, "rr3_override", None)
        if value is not None:
            doc.overrides.append((a.name, str(value)))

    # and anything the file overrode that has no record of its own
    known = {n for n, _v in doc.overrides}
    raw = _prop(scene, "rr3_overrides", "")
    for line in str(raw or "").splitlines():
        if "\t" in line:
            n, v = line.split("\t", 1)
            if n.strip() not in known:
                doc.overrides.append((n.strip(), v))
                known.add(n.strip())
    return doc


def export_points(path: str, objects=None, *, only_tagged: bool = True,
                  only_selected: bool = False):
    """Write a ``.points`` file.  Returns ``(count, warnings)``."""
    doc = points_from_scene(objects, only_tagged=only_tagged,
                            only_selected=only_selected)
    if not doc.records:
        raise ExportError("no anchor empties in the scene - nothing to write")
    warnings = pointsw.validate(doc)
    pointsw.save(doc, path)
    return len(doc.records), warnings


def points_from_file(path: str):
    """Load a ``.points`` file so an operator can edit it in place."""
    return pointsw.load(path)


# ---------------------------------------------------------------------- banim
def _key_times(ob) -> list[float]:
    """Every frame number that has a key on ``ob`` (location or rotation)."""
    times: set[float] = set()
    ad = ob.animation_data
    if not ad or not ad.action:
        return []
    try:
        curves = ad.action.fcurves
    except AttributeError:                        # Blender 4.4 slotted actions
        curves = []
        for layer in getattr(ad.action, "layers", []):
            for strip in getattr(layer, "strips", []):
                for bag in getattr(strip, "channelbags", []):
                    curves.extend(bag.fcurves)
    for fc in curves:
        for kp in fc.keyframe_points:
            times.add(float(kp.co[0]))
    return sorted(times)


def _fps() -> float:
    fps = bpy.context.scene.render.fps
    return float(fps) if fps else 30.0


# ------------------------------------------------------- part names and tracks
def part_base(name: str) -> str:
    """``LOD_A_WING_REAR_mm_ext`` -> ``WING_REAR``.

    A wing is modelled as several meshes, one per material tag (``_mm_ext``,
    ``_mm_misc``, ``_mm_chassis`` ...), all sharing one name stem.  The game
    animates the *part*, not each mesh, so the stem is what a track is named
    after.  The ``LOD_<letter>_`` prefix goes too, so the same part in LOD B
    lands on the same name as in LOD A.
    """
    base = name
    marker = base.find("_mm_")
    if marker >= 0:
        base = base[:marker]
    bits = base.split("_")
    for i in range(len(bits) - 2):
        if bits[i] == "LOD" and len(bits[i + 1]) == 1:
            return "_".join(bits[i + 2:])
    return base


def _rides_on_another(base: str) -> bool:
    """True for a part that is modelled separately but moves with its parent.

    A wing brake light (``WING_REAR_BRAKES``) is its own mesh but has no track
    of its own in any shipped car - it rides on the wing.  Giving it a track
    would shift every later track by one and the wing would follow the brake
    light's (constant) track instead of its own.
    """
    return base.upper().endswith("_BRAKES")


#: The per-track trailer word each wing part carries in the shipped files.
#:
#: A wing ``.banim`` ends with ``u32 n`` followed by ``n`` hash words, one per
#: track, and the engine will not play the clip without them - a file that stops
#: after the key data loads without complaint and then never moves anything, so
#: the wing simply stays at its modelled origin and the car appears to have lost
#: it.  The words are not derivable: crc32, adler32, fnv1/fnv1a, djb2, sdbm,
#: elf, oaat, java, murmur3 and xxh32 over every spelling of the part name
#: (with and without ``LOD_A_``, ``AERO_``, ``_mm_ext``, in ascii and utf-16)
#: produce none of them.  They are constants of the *part*, though: across the
#: 52 cars whose track count matches their part count, the multiset of trailer
#: words equals the multiset of these constants every time.
TRAILER_WORDS = {
    "WING": 0x6C8C2CFD,
    "WING_REAR": 0xAD45C13F,
    "WING_REAR_LEFT": 0x4202CB14,
    "WING_REAR_RIGHT": 0x344991DE,
    "WING_STRUT": 0x89CEF5E4,
    "WING_STRUT_REAR": 0x57529DC8,
}

#: Fallback for a part name that is not in the table.
TRAILER_DEFAULT = 0xAD45C13F


def trailer_words_for(bases) -> list[int]:
    """The trailer word for each part base, in track order.

    The order inside a shipped file does not always follow the alphabetical part
    order (five of the 52 cars store the words in another order), so only the
    multiset is guaranteed - but the engine reads the word belonging to the
    track it is about to play, and a part whose word is a different part's
    constant still animates.  Keeping the pairing exact where the table has the
    name is what matters, so the words are emitted per part rather than sorted.
    """
    out = []
    for base in bases:
        key = str(base).upper()
        # An ``AERO_0_WING_REAR`` empty carries the part, it is not its name.
        if key.startswith("AERO_"):
            key = key.split("_", 2)[2] if key.count("_") >= 2 else key[5:]
        out.append(TRAILER_WORDS.get(key, TRAILER_DEFAULT))
    return out



def _part_carrier(ob):
    """The object that actually carries this part's motion.

    The vehicle importer parents each wing mesh to an ``AERO_*`` empty and
    animates the empty; a part the user split out by hand is animated itself.
    """
    cur = ob
    for _ in range(8):
        if cur.animation_data is not None and cur.animation_data.action is not None:
            return cur
        parent = cur.parent
        if parent is None or not parent.name.startswith("AERO_"):
            break
        cur = parent
    return ob


def _groups_by_part_base(objects, name_filter: str = "WING"):
    """``[(base, carrier)]`` in the order the game numbers the tracks.

    The order is the alphabetical order of the part base name, which is what the
    shipped files use: across the 52 cars that have a wing ``.banim``, the number
    of distinct base names (minus the ``_BRAKES`` riders) equals the number of
    tracks 52 times out of 52, and on the three cars that have a ``_LEFT`` and a
    ``_RIGHT`` part the alphabetical order is the one that puts the left flap on
    the left.

    A part split over several material tags (``WING_REAR_mm_ext`` and
    ``WING_REAR_mm_misc``) is one part to the game and gets **one** track: the
    two meshes move together, so writing both would put two identical tracks in
    the file and shift every track after them.

    The importer's own ``AERO_<n>_<PART>`` empties are skipped: their name
    contains the part name but they *carry* the mesh, so counting them would put
    two tracks on one part and push the real parts out of their numbers.
    """
    groups: dict[str, list] = {}
    needle = (name_filter or "").upper()
    for ob in objects:
        if ob.name.startswith("AERO_"):
            continue
        base = part_base(ob.name)
        if not base or (needle and needle not in base.upper()):
            continue
        groups.setdefault(base, []).append(ob)
    out = []
    for base in sorted(groups):
        if _rides_on_another(base):
            continue
        members = sorted(groups[base], key=lambda o: o.name)
        carrier = next((o for o in members if _part_carrier(o) is not o), None)
        if carrier is None:
            carrier = next(
                (o for o in members
                 if o.animation_data is not None and o.animation_data.action is not None),
                members[0])
        out.append((base, _part_carrier(carrier)))
    return out


def _inherit_container(doc, donor_path: str, tracks: int, bases=()) -> str:
    """Copy a shipped file's container onto ``doc``.  Returns a note or "".

    The magic word, the variant, the version word, the per-track trailer and the
    event-name table cannot be computed from the curves.  With a donor they are
    copied from it.  Without one the trailer is still written, built from
    :data:`TRAILER_WORDS`, because a wing file with no trailer is silently
    ignored by the engine - that is the difference between "the wing animates"
    and "the wing is gone", not a cosmetic one.

    A donor with a different track count cannot supply the trailer (it holds one
    word per track), so in that case the synthesized one is used instead of
    dropping it.
    """
    if donor_path:
        try:
            raw = open(donor_path, "rb").read()
            # The *parser* gives the offsets; ``banim_write.load`` returns a doc.
            donor = banimlib.load(donor_path)
        except Exception as exc:  # noqa: BLE001
            return _synthesize_container(doc, tracks, bases,
                                         f"could not read the donor "
                                         f"{donor_path}: {exc}")
        doc.magic = donor.magic
        doc.variant = donor.variant
        if donor.version is not None:
            doc.version = donor.version
        doc.field_a = donor.field_a
        doc.names = list(donor.names)
        doc.properties = list(donor.properties)
        end = donor.names_offset or len(raw)
        doc.tail_raw = raw[donor.key_end:end]
        if donor.num_tracks == tracks:
            return ""
        note = (f"the donor has {donor.num_tracks} track(s) but this scene has "
                f"{tracks}, so its trailer could not be used")
        return _synthesize_container(doc, tracks, bases, note)
    return _synthesize_container(doc, tracks, bases, "")


def _synthesize_container(doc, tracks: int, bases=(), note: str = "") -> str:
    """Give ``doc`` the container a wing file needs, without a donor.

    The magic is fixed at ``0x7F7F7F00`` (all 53 shipped wing files carry it, and
    the engine rejects a wing clip whose third byte is 0x00), the variant is the
    plain one, and the trailer is one word per track taken from
    :data:`TRAILER_WORDS`.  Nothing else is needed: the ``AE_*`` event-name table
    is empty in every wing file.
    """
    doc.magic = 0x7F7F7F00
    doc.variant = 0x00
    words = trailer_words_for(bases) if bases else []
    while len(words) < tracks:
        words.append(TRAILER_DEFAULT)
    doc.tail_raw = struct.pack("<I", tracks) + b"".join(
        struct.pack("<I", w) for w in words[:tracks])
    if note:
        return note + "; the trailer was built from the part names instead"
    return ""



def _span_frames(objects=None):
    """``(first, last)`` frame the clip spans, or None when nothing is animated.

    The start is the scene's own start when that is earlier than the first
    keyframe: a wing that only starts moving at frame 23 still has to hold its
    rest pose from frame 1, and sampling from the first keyframe instead would
    make the part jump into place when the animation starts.

    The end is the *last keyframe*, not the scene's end.  A fresh scene runs to
    frame 250 whatever the artist does, and honouring that would append seven
    seconds of the part sitting still - the clip would then take seven seconds
    to play and the frame numbers in ``_animations.xml`` would no longer line up
    with the ones the artist wrote.
    """
    scene = bpy.context.scene
    times = []
    for ob in objects or ():
        times.extend(_key_times(ob))
    if not times:
        first, last = float(scene.frame_start), float(scene.frame_end)
        return [first, last] if last > first else None
    return [min(float(scene.frame_start), min(times)), max(times)]


def _pose_at(ob, frame: float):
    """``(location, euler)`` of ``ob`` at ``frame``, drivers included."""
    bpy.context.scene.frame_set(int(frame), subframe=float(frame) - int(frame))
    loc = Vector(ob.location)
    if ob.rotation_mode == "QUATERNION":
        eul = ob.rotation_quaternion.to_euler("XYZ")
    else:
        eul = Euler(ob.rotation_euler, "XYZ")
    return loc, eul


def banim_from_scene(objects=None, *, fps: float = 0.0,
                     tracks_from: str = "AERO", duration_ms: float = 0.0,
                     part_filter: str = "WING", donor: str = ""):
    """Collect the animated parts into a :class:`banim_write.BanimDoc`.

    ``donor`` is a shipped ``.banim`` of the same shape (same track count).  The
    container around the curves is copied from it: the magic word, the variant,
    the version, the per-track trailer of hash words and the ``AE_*`` name
    table.  None of that is derivable - the trailer words are not any hash of
    the part names, of the track index or of the file, and the game will not
    play a wing animation whose magic is 0x7F7F0000 instead of 0x7F7F7F00 - so
    a file built from scratch has to borrow a container.

    ``tracks_from`` selects what becomes a track:

    * ``"AERO"`` - the ``AERO_*`` pivots the vehicle importer creates;
    * ``"TAGGED"`` - any empty carrying an ``rr3_track`` property;
    * ``"SELECTED"`` - the current selection;
    * ``"PARTS"`` - any *mesh* carrying ``rr3_track``, which is what a driver rig
      is: fifteen body parts animated one per track, not empties driving a car;
    * ``"NAME"`` - the meshes whose name contains ``part_filter``, grouped by
      their part base name and numbered in alphabetical order.  This is how a
      wing is authored when it has been split out of the body by hand: no tags
      to set, no empties to make, and the track numbers come out the way the
      game expects them.

    Track order follows ``rr3_track`` when it is present, because the game binds
    the animation by index - the driver's ``00_helmet`` has to stay track 0 even
    though ``10_arm_l`` sorts before it alphabetically.  ``"NAME"`` ignores the
    tag on purpose: there the name *is* the number.

    The pose is *evaluated at each key time*, not read off the current frame -
    reading the object directly would write the same pose to every key.

    No axis conversion happens here: the file's animation space (x right, y
    fore, z up) and Blender's axes agree, which is why the importer can write
    ``cm @ anim_to_model(p)`` and get ``p`` back.  See ``_anim_matrix``.
    """
    fps = fps or _fps()
    if tracks_from == "SELECTED":
        cands = [ob for ob in bpy.context.selected_objects if ob.type == "EMPTY"]
    elif tracks_from == "PARTS":
        cands = [ob for ob in _meshes(objects) if _has(ob, "rr3_track")]
    elif tracks_from == "NAME":
        cands = [carrier for _base, carrier in
                 _groups_by_part_base(_meshes(objects), part_filter)]
        if not cands:
            raise ExportError(
                f"no mesh has {part_filter or 'a part name'} in its name - name "
                f"the parts LOD_A_<PART>_mm_<tag> and they will be picked up")
    else:
        cands = _empties(objects)
        if tracks_from == "AERO":
            cands = [ob for ob in cands if ob.name.startswith("AERO_")]
        else:
            cands = [ob for ob in cands if _has(ob, "rr3_track")]
    if not cands:
        raise ExportError(f"no {tracks_from} objects to export")

    def order(ob):
        tag = _prop(ob, "rr3_track")
        if isinstance(tag, (int, float)):
            return (0, int(tag), ob.name)
        return (1, 0, ob.name)

    if tracks_from == "NAME":
        # ``_groups_by_part_base`` already numbered these by part base name, and
        # that is the numbering the game uses.  Sorting them again by object name
        # would undo it: ``LOD_A_WING_STRUT_REAR_mm_misc`` sorts before
        # ``LOD_A_WING_STRUT_mm_misc`` (capital R is below lower case m), so the
        # two struts would swap tracks and each flap would follow the other's
        # motion.
        ordered = list(cands)
    else:
        ordered = sorted(cands, key=order)

    scene = bpy.context.scene
    keep = scene.frame_current
    doc = banimw.BanimDoc(duration_ms=duration_ms)
    # The trailer needs one word per track, and the word depends on which part
    # the track drives - so the part names have to be known before the curves are
    # written.  In ``NAME`` mode the grouping already knows them; elsewhere the
    # object's own name carries the part name.
    bases = [part_base(ob.name) for ob in ordered]
    _inherit_container(doc, donor, len(ordered), bases)
    last_ms = 0.0
    try:
        for ti, ob in enumerate(ordered):
            track = doc.add_track(ti)
            # One knot per frame in slot 0, two Bezier control points per
            # segment in slot 1.
            #
            # The two slots are *not* one key list split in half.  Every one of
            # the 96 shipped wing tracks has ``slot1 == 2 * (slot0 - 1)`` keys
            # (95 of 96 exactly) and the slot-1 timestamps sit at 1/3 and 2/3 of
            # each slot-0 segment: slot 0 holds the knots, slot 1 holds the two
            # control points that shape the segment between consecutive knots.
            # Writing samples into slot 1 instead makes the engine read each
            # sample as a control point, and the part hitches wherever the two
            # readings disagree - on the LFA that was a visible stutter at the
            # artist's middle keyframe.
            #
            # Sampling only at the object's own keyframes is not enough either:
            # Blender interpolates between them with Bezier handles, so a wing
            # whose three poses are evenly spaced still eases in and out, and a
            # file holding just the three poses moves in straight lines and
            # snaps at each one.
            span = _span_frames(ordered)
            if span is None:
                span = _key_times(ob) or [float(scene.frame_start)]
            first, last = min(span), max(span)
            n = max(2, int(round(last - first)) + 1)
            frames = [first + (last - first) * k / (n - 1) for k in range(n)]
            times = [max(0.0, (fr - FRAME_BASE) / fps * 1000.0) for fr in frames]

            def channel_of(pose, ch):
                loc, rot = pose
                if ch < 3:
                    return float(loc[ch])
                return math.degrees(float(rot[ch - 3]))

            knots = [_pose_at(ob, fr) for fr in frames]
            for ch in range(6):
                slot0 = track.curve(ch, 0)
                for t_ms, pose in zip(times, knots):
                    slot0.add(t_ms, channel_of(pose, ch))
                    last_ms = max(last_ms, t_ms)
                if n < 2:
                    continue
                slot1 = track.curve(ch, 1)
                for i in range(n - 1):
                    t0, t1 = times[i], times[i + 1]
                    if t1 <= t0:
                        continue
                    f0, f1 = frames[i], frames[i + 1]
                    v0 = channel_of(knots[i], ch)
                    v3 = channel_of(knots[i + 1], ch)
                    # The pose Blender's own curve passes through at the 1/3 and
                    # 2/3 marks of this segment.
                    q1 = channel_of(_pose_at(ob, f0 + (f1 - f0) / 3.0), ch)
                    q2 = channel_of(_pose_at(ob, f0 + 2.0 * (f1 - f0) / 3.0), ch)
                    # Solve the two Bezier equations B(1/3) = q1 and
                    # B(2/3) = q2 for the control points p1, p2, so the exported
                    # cubic goes through exactly those poses and keeps the ease.
                    a = 27.0 * q1 - 8.0 * v0 - v3
                    b = 27.0 * q2 - v0 - 8.0 * v3
                    span_ms = t1 - t0
                    slot1.add(t0 + span_ms / 3.0, (2.0 * a - b) / 18.0)
                    slot1.add(t0 + 2.0 * span_ms / 3.0, (2.0 * b - a) / 18.0)
    finally:
        scene.frame_set(keep)
    if not doc.duration_ms:
        doc.duration_ms = last_ms
    return doc


def export_banim(path: str, objects=None, **kw):
    """Write a ``.banim``.  Returns ``(tracks, keys, duration_ms)``."""
    doc = banim_from_scene(objects, **kw)
    banimw.save(doc, path)
    keys = sum(len(c.keys) for t in doc.tracks for c in t.curves)
    return len(doc.tracks), keys, doc.duration_ms


def banim_from_file(path: str):
    """Load a ``.banim`` for editing (keeps the opaque tail verbatim)."""
    return banimw.load(path)


# ------------------------------------------------------------------ anim xml
def clips_for(name: str, start: float, end: float) -> list:
    """One named clip, frames inclusive as the game writes them."""
    return [animxmllib.Clip(name, int(start), int(end))]


def wing_clips(start_frame: int = 0, end_frame: int = 30) -> list:
    """The three clips an active-aero car normally needs."""
    return animxmllib.wing_pair(int(start_frame), int(end_frame))


def export_animxml(path: str, clips):
    """Write an ``_animations.xml`` next to the ``.banim``."""
    problems = animxmllib.validate(clips)
    animxmllib.save(clips, path)
    return problems


def animxml_from_file(path: str):
    return animxmllib.load(path)


# ------------------------------------------------------------------- reports
def scene_summary() -> str:
    """What the exporter currently sees, for the panel / report operator."""
    pts = [ob.name for ob in _empties()
           if _has(ob, "rr3_point_type")
           or ob.name.upper().startswith(("POINT_", "HINGE_"))]
    aero = [ob.name for ob in _empties() if ob.name.startswith("AERO_")]
    lines = [
        f"anchor empties : {len(pts)}",
        f"aero pivots    : {len(aero)}",
        f"meshes         : {len(_meshes())}",
        f"fps            : {_fps():g}",
        f"frame range    : {bpy.context.scene.frame_start}"
        f" .. {bpy.context.scene.frame_end}",
    ]
    if aero:
        lines.append("")
        for name in aero[:12]:
            ob = bpy.data.objects.get(name)
            if ob is None:
                continue
            keys = len(_key_times(ob))
            lines.append(f"  {name:<34} {keys} key time(s)")
    return "\n".join(lines)
