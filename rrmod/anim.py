"""Animation editing: the ``_wing.banim`` tracks and the ``_animations.xml`` clips.

The game binds a moving part to a track **by name order** - the parts of a car
sorted by their base mesh name take tracks 0, 1, 2 in that order.  Nothing in
the file says which part a track drives, and three separate attempts to find
such a field came up empty, so this module does not try to be clever.  It shows
the name order, shows what each track actually does, and lets the two be
swapped by hand.

The second half is the XML.  It is a list of named transitions, each a frame
range of the banim, and the frame numbers are the banim's own 33 ms frames.
Editing it is safe; the game looks clips up by name.
"""

from __future__ import annotations

import os
import re
import shutil

from rr3lib import animxml as animxmllib
from rr3lib import banim as banimlib
from rr3lib import banim_write as bwlib
from rr3lib import m3g as m3glib

#: One banim frame, matching :data:`rr3lib.animxml.FRAME_MS`.
FRAME_MS = animxmllib.FRAME_MS

#: Files this module edits inside a car folder.
BANIM_SUFFIX = "_wing.banim"
XML_SUFFIX = "_animations.xml"


class AnimError(Exception):
    pass


#: The four behaviours the shipped specs use, as ``(label, token)``.
#:
#: ``DeployWhenBraking`` (35 cars) lifts the wing under braking; ``DeployAtSpeed``
#: (11) flattens it above a speed for drag reduction; ``BrakeAndSpeedCombo`` (7)
#: does both, which is what the Senna, the Jesko and the Battistas use;
#: ``NascarAirBrake`` (42) is the NASCAR flap and takes no numbers.
AERO_CHOICES = (
    ("Braking only - wing up to slow down", b"DeployWhenBraking"),
    ("Speed only - wing flattens for less drag", b"DeployAtSpeed"),
    ("Both - drag reduction and air brake", b"BrakeAndSpeedCombo"),
    ("NASCAR air brake", b"NascarAirBrake"),
)

#: The behaviours that carry two speeds after the name.
AERO_PARAMETRIC = (b"DeployAtSpeed", b"BrakeAndSpeedCombo")


# ------------------------------------------------------------------- reading
def banim_path(root: str, car: str) -> str:
    return os.path.join(root, ".depot", "vehicles", car, f"{car}{BANIM_SUFFIX}")


def xml_path(root: str, car: str) -> str:
    return os.path.join(root, ".depot", "vehicles", car, f"{car}{XML_SUFFIX}")


def body_path(root: str, car: str, lod: str = "A") -> str:
    return os.path.join(root, ".depot", "vehicles", car, f"{car}_{lod.lower()}.m3g")


def has_animation(root: str, car: str) -> bool:
    return os.path.isfile(banim_path(root, car))


def moving_parts(root: str, car: str, lod: str = "A") -> list:
    """Base names of the wing meshes in the body LOD, in **name order**.

    This is the order the game uses to hand out track numbers, so index ``i`` of
    the returned list is the part that plays track ``i`` - unless the car is one
    of the ones where that is wrong, which is exactly what the swap is for.
    """
    path = body_path(root, car, lod)
    if not os.path.isfile(path):
        return []
    model = m3glib.M3G(path)
    bases = set()
    for obj in model.of_type(14):
        name = obj.data.get("name") or ""
        if "WING" not in name.upper():
            continue
        cut = name.find("_mm_")
        bases.add(name[:cut] if cut >= 0 else name)
    return sorted(bases)


def _curve_keys(track, channel: int):
    for c in track.curves:
        if c.channel == channel and c.slot == 0 and c.keys:
            return c.keys
    return []


def track_info(track) -> dict:
    """Pivot, rotation travel and key count for one track, in metres/degrees.

    ``track`` is a :class:`rr3lib.banim_write.TrackData`, whose curves are
    already in metres and degrees.
    """
    pos = []
    for ch in range(3):
        keys = _curve_keys(track, ch)
        pos.append(keys[0][1] if keys else 0.0)
    pitch = [v for _t, v in _curve_keys(track, 3)]
    yaw = [v for _t, v in _curve_keys(track, 4)]
    roll = [v for _t, v in _curve_keys(track, 5)]
    return {
        "index": track.index,
        "pivot": tuple(round(v, 4) for v in pos),
        "pitch": (round(min(pitch), 2), round(max(pitch), 2)) if pitch else (0.0, 0.0),
        "yaw": (round(min(yaw), 2), round(max(yaw), 2)) if yaw else (0.0, 0.0),
        "roll": (round(min(roll), 2), round(max(roll), 2)) if roll else (0.0, 0.0),
        "keys": max((len(c.keys) for c in track.curves), default=0),
    }


def travel(info: dict) -> float:
    """How much the track actually moves: the largest rotation span, in degrees."""
    return max(info["pitch"][1] - info["pitch"][0],
               info["yaw"][1] - info["yaw"][0],
               info["roll"][1] - info["roll"][0])


def read(root: str, car: str, lod: str = "A") -> dict:
    """Everything the animation panel needs about one car.

    Returns ``{"car", "duration_ms", "frames", "variant", "tracks", "parts",
    "clips", "banim", "xml", "warnings"}``.  ``tracks[i]["part"]`` is the part
    the *game* would drive with track ``i`` under name order, or ``""`` when the
    car has more tracks than named parts.
    """
    out = {"car": car, "duration_ms": 0.0, "frames": 0, "variant": 0,
           "tracks": [], "parts": [], "clips": [], "banim": "", "xml": "",
           "warnings": []}
    bp = banim_path(root, car)
    if not os.path.isfile(bp):
        out["warnings"].append(f"{car} has no {BANIM_SUFFIX}")
        return out
    out["banim"] = bp
    b = banimlib.load(bp)
    doc = bwlib.load(bp)
    out["duration_ms"] = b.duration_ms
    out["frames"] = animxmllib.frames_for(b.duration_ms)
    out["variant"] = b.variant
    parts = moving_parts(root, car, lod)
    out["parts"] = parts
    for track in doc.tracks:
        info = track_info(track)
        info["part"] = parts[track.index] if track.index < len(parts) else ""
        info["travel"] = round(travel(info), 2)
        out["tracks"].append(info)
    if parts and len(parts) != len(b.tracks):
        out["warnings"].append(
            f"{len(parts)} wing part(s) but {len(b.tracks)} track(s) - the game "
            f"pairs them in name order, so the last part(s) may not move")
    if not b.trailer_words:
        # Every one of the 53 shipped wing files ends with one hash word per
        # track.  Without them the engine loads the clip and then never applies
        # it: the wing stays at its modelled origin and the car looks as if the
        # part has been deleted.  This is the difference between a working export
        # and a broken one, so it is reported as an error, not a note.
        out["warnings"].append(
            f"{BANIM_SUFFIX} has no trailer - the game will load it and then "
            f"never move anything, so the wing will look as if it is missing. "
            f"Re-export it from Blender (the exporter now writes the trailer "
            f"itself) or copy the trailer from a shipped _wing.banim")
    xp = xml_path(root, car)
    if os.path.isfile(xp):
        out["xml"] = xp
        out["clips"] = animxmllib.load(xp)
    else:
        out["warnings"].append(f"{car} has no {XML_SUFFIX}")
    return out


# -------------------------------------------------------------------- swaps
def swap_tracks(blob: bytes, mapping: dict) -> bytes:
    """Rebuild a banim with the tracks renumbered.

    ``mapping`` maps a new track number to the old one - ``{0: 1, 1: 0}`` swaps
    the first two.  The curves move; the track numbers are rewritten to be
    sequential, because a file whose ``trackIndex`` words are a permutation of
    0..n-1 is what the shipped files all look like.
    """
    doc = _load_blob(blob)
    old = {t.index: t for t in doc.tracks}
    missing = [i for i in range(len(doc.tracks)) if i not in mapping]
    if missing:
        raise AnimError(f"mapping is missing track(s) {missing}")
    extra = [i for i in mapping if i not in old]
    if extra:
        raise AnimError(f"mapping names track(s) that do not exist: {extra}")
    seen = set()
    new_tracks = []
    for new_index in range(len(doc.tracks)):
        src = mapping[new_index]
        if src in seen:
            raise AnimError(f"track {src} is used twice in the mapping")
        seen.add(src)
        t = old[src]
        t.index = new_index
        t.index_raw = None
        new_tracks.append(t)
    doc.tracks = new_tracks
    return bwlib.build(doc)


def _load_blob(blob: bytes):
    """Parse banim bytes straight into an editable document."""
    b = banimlib.parse(blob)
    return bwlib.from_banim(b, blob)


def swap_file(root: str, car: str, mapping: dict, *, out: str = "") -> dict:
    """Write a renumbered banim.  Returns ``{"path", "bytes", "before", "after"}``.

    Nothing is written into the install: the caller decides whether to apply it
    with :func:`rrmod.edit.add_file`.
    """
    src = banim_path(root, car)
    if not os.path.isfile(src):
        raise AnimError(f"{car} has no {BANIM_SUFFIX}")
    with open(src, "rb") as fh:
        blob = fh.read()
    new = swap_tracks(blob, mapping)
    out = out or os.path.join(os.path.dirname(src), f"{car}_wing.swapped.banim")
    with open(out, "wb") as fh:
        fh.write(new)
    return {"path": out, "bytes": len(new), "before": len(blob),
            "mapping": dict(mapping)}


def spec_path(root: str, car: str) -> str:
    """The car's spec file, or ``""``.

    The spec keeps the full model name while the folder often does not: the
    folder is ``2013_bugatti_veyron_gsv`` but the spec is
    ``140_2013_bugatti_veyron_16.4_grand_sport_vitesse.bin.nct``, so the name
    alone cannot find it.  The manager already knows the answer - the folder is
    reached through the car's appearance record - so this asks the same table
    rather than guessing a second way.

    The lookup goes through :func:`rrmod.depot.spec_stems`, not ``scan``: this
    function is called from ``stats.load``, which every panel of the Build a car
    dialog calls several times per car, and a full scan there cost two seconds
    a time.
    """
    folder = os.path.join(root, ".depot", "vehicles", "data")
    if not os.path.isdir(folder):
        return ""
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".bin.nct") or not f.split("_")[0].isdigit():
            continue
        if f.split("_", 1)[1] == f"{car}.bin.nct":
            return os.path.join(folder, f)
    from . import depot as depotlib

    stem = depotlib.spec_stems(root).get(car, "")
    if not stem:
        return ""
    path = os.path.join(folder, f"{stem}.bin.nct")
    return path if os.path.isfile(path) else ""


def aero_state(root: str, car: str) -> dict:
    """What the car's spec asks the game to do with its wing.

    Returns ``{"spec", "flag", "kind", "params", "enabled"}``.  ``flag`` is the
    whole behaviour token (``"BrakeAndSpeedCombo, 180, 170"``), ``kind`` just the
    behaviour word and ``params`` the two speeds after it, high one first.  A car
    can carry numbers after the name, which is why this reports the token rather
    than a bool alone.
    """
    from rr3lib import spec as speclib

    path = spec_path(root, car)
    out = {"spec": path, "flag": "", "kind": "", "params": (), "enabled": False}
    if not path:
        return out
    try:
        spec = speclib.load_spec(os.path.join(root, ".depot"),
                                 os.path.basename(path))
    except Exception:                            # noqa: BLE001
        return out
    out["flag"] = spec.aero_text()
    out["kind"] = spec.aero_kind().decode("ascii", "replace")
    out["params"] = spec.aero_params()
    out["enabled"] = bool(out["flag"])
    return out


def driver_state(root: str, car: str) -> dict:
    """Which seated pose the car uses, and whether it has a low-poly model of it.

    ``banim`` is the file name (``""`` when the record names none, which means
    the game falls back to ``driver.banim``).  ``own_low_poly`` says whether a
    ``driver_lod_c_<x>.m3g`` exists for that pose: only 12 poses have one, so 24
    of the 33 poses the records name are played by the generic low-poly figure.
    The game copes - it just looks slightly wrong from outside - but a user
    choosing a pose deserves to be told.
    """
    from rr3lib import driver as driverlib

    depot = os.path.join(root, ".depot")
    out = {"record": "", "banim": "", "choices": [], "own_low_poly": "",
           "low_poly_stem": ""}
    from . import edit as editlib

    home = editlib._driver_dir(root) or depot
    folder = driverlib.driver_dir(home)
    if folder is None:
        return out
    out["choices"] = [stem for stem, _path in driverlib.banims(home)]
    record = driverlib.car_record(depot, car)
    out["record"] = record or ""
    if record:
        got = driverlib.field_in_record(record)
        out["banim"] = got or ""
    if out["banim"]:
        stem = out["banim"][: -len(driverlib.BANIM_SUFFIX)]
        short = stem[len(driverlib.SKIN_PREFIX):] if stem.startswith(
            driverlib.SKIN_PREFIX) else stem
        out["low_poly_stem"] = short
        own = os.path.join(folder, f"driver_lod_c_{short}.m3g")
        out["own_low_poly"] = own if os.path.isfile(own) else ""
    return out


def describe_blob(blob: bytes) -> list:
    """Track summaries for banim bytes, without touching the disk."""
    doc = _load_blob(blob)
    return [track_info(t) for t in doc.tracks]


# ---------------------------------------------------------------------- xml
def set_clip(clips: list, name: str, start: int, end: int) -> list:
    """Replace or add one clip, keeping the file order."""
    out = []
    found = False
    for c in clips:
        if c.name == name:
            out.append(animxmllib.Clip(name, int(start), int(end)))
            found = True
        else:
            out.append(c)
    if not found:
        out.append(animxmllib.Clip(name, int(start), int(end)))
    return out


def remove_clip(clips: list, name: str) -> list:
    return [c for c in clips if c.name != name]


def rename_clip(clips: list, old: str, new: str) -> list:
    return [animxmllib.Clip(new, c.start, c.end) if c.name == old else c
            for c in clips]


def clip_rows(clips: list) -> list:
    """``[(name, start, end, ms, direction, note)]`` for the table."""
    rows = []
    for c in clips:
        rows.append((c.name, c.start, c.end, round(c.duration_ms),
                     "backwards" if c.reversed else "forwards", c.doc()))
    return rows


def write_xml(clips: list, path: str, *, sort: bool = False) -> int:
    return animxmllib.save(clips, path, sort=sort)


def validate(clips: list, duration_ms: float) -> list:
    return animxmllib.validate(clips, duration_ms)


def suggest_clips(duration_ms: float) -> list:
    """A sane default set for a car that has none: rest, up, down."""
    return animxmllib.wing_pair(0, animxmllib.frames_for(duration_ms))


# ------------------------------------------------------------------ installs
def apply_swap(root: str, car: str, mapping: dict) -> dict:
    """Renumber the tracks of a car already in the install and sync manifests."""
    from . import edit as editlib

    got = swap_file(root, car, mapping)
    info = editlib.add_file(root, car, got["path"],
                            rename=f"{car}{BANIM_SUFFIX}")
    info.update(got)
    try:
        os.unlink(got["path"])
    except OSError:
        pass
    return info


def apply_xml(root: str, car: str, clips: list) -> dict:
    """Write an edited clip list back into the install."""
    from . import edit as editlib

    out = os.path.join(os.path.dirname(xml_path(root, car)),
                       f"{car}_animations.edited.xml")
    write_xml(clips, out)
    info = editlib.add_file(root, car, out, rename=f"{car}{XML_SUFFIX}")
    info["clips"] = len(clips)
    try:
        os.unlink(out)
    except OSError:
        pass
    return info


def copy_animation(root: str, car: str, *, to: str = "") -> dict:
    """Copy a car's banim + xml into a folder, ready to hand to another car."""
    to = to or os.path.join(os.path.dirname(banim_path(root, car)),
                            f"{car}_anim")
    os.makedirs(to, exist_ok=True)
    got = {}
    for src, name in ((banim_path(root, car), f"{car}{BANIM_SUFFIX}"),
                      (xml_path(root, car), f"{car}{XML_SUFFIX}")):
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(to, name))
            got[name] = os.path.join(to, name)
    return {"folder": to, "files": got}
