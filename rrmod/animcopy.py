"""Copy the animation of one car onto another - the case the user asked for.

The wing banim names its tracks by number, not by part, so it is portable: a
finished animation for one car plays on another as long as the number of moving
parts matches.  That is how the animated LFA gets its aero, and it is also the
quickest way to give a car an active wing the studio never made.

Two things have to travel together and they are easy to forget:

* ``<car>_wing.banim`` - the curves;
* ``<car>_animations.xml`` - which frame range each named transition plays.
  Without it the game has no ``wing_up`` to ask for and the wing never moves.

The third thing - the ``DeployWhenBraking`` flag in the car's spec - is what
makes the game try at all.  It is set through :func:`rrmod.edit.set_aero_flag`.
"""

from __future__ import annotations

import os
import shutil

from rr3lib import animxml as animxmllib

from . import anim as animlib


class CopyError(Exception):
    pass


def _count_tracks(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    from rr3lib import banim as banimlib
    try:
        return len(banimlib.load(path).tracks)
    except Exception:                            # noqa: BLE001
        return 0


def compare(root: str, source: str, target: str) -> dict:
    """What copying ``source``'s animation onto ``target`` would involve.

    Returns ``{"source_tracks", "target_tracks", "source_parts",
    "target_parts", "warnings", "can_copy"}``.  A track count mismatch is not a
    hard error - the game pairs the parts in name order and simply ignores extra
    tracks - but it is almost always a mistake, so it is reported loudly.
    """
    out = {"source": source, "target": target,
           "source_tracks": 0, "target_tracks": 0,
           "source_parts": [], "target_parts": [], "warnings": [],
           "can_copy": False}
    src_banim = animlib.banim_path(root, source)
    if not os.path.isfile(src_banim):
        out["warnings"].append(f"{source} has no animation to copy")
        return out
    out["source_tracks"] = _count_tracks(src_banim)
    out["target_tracks"] = _count_tracks(animlib.banim_path(root, target))
    try:
        out["source_parts"] = animlib.moving_parts(root, source)
    except Exception:                            # noqa: BLE001
        pass
    try:
        out["target_parts"] = animlib.moving_parts(root, target)
    except Exception:                            # noqa: BLE001
        pass
    if not out["target_parts"]:
        out["warnings"].append(
            f"{target} has no WING meshes - the animation would have nothing "
            f"to move. Model a wing into its LOD A first.")
    if out["source_tracks"] != len(out["target_parts"]):
        out["warnings"].append(
            f"{source} has {out['source_tracks']} track(s) but {target} has "
            f"{len(out['target_parts'])} wing part(s); the game pairs them in "
            f"name order, so the counts should match")
    if not os.path.isfile(animlib.xml_path(root, source)):
        out["warnings"].append(
            f"{source} has no _animations.xml - the copy will get a default "
            f"rest/up/down set instead of the original transitions")
    out["can_copy"] = bool(out["source_tracks"])
    return out


def copy_animation(root: str, source: str, target: str, *,
                   rename_parts: bool = True) -> dict:
    """Copy the banim and the xml from one car folder to another.

    Returns ``{"banim", "xml", "tracks", "clips"}`` with the paths written.  The
    files are written into ``target``'s folder under ``target``'s name, because
    the engine looks the animation up by the car's own file name.
    """
    src_banim = animlib.banim_path(root, source)
    if not os.path.isfile(src_banim):
        raise CopyError(f"{source} has no {animlib.BANIM_SUFFIX}")
    folder = os.path.dirname(animlib.banim_path(root, target))
    if not os.path.isdir(folder):
        raise CopyError(f"{target} has no folder at {folder}")
    out = {"banim": "", "xml": "", "tracks": 0, "clips": 0}

    dst_banim = os.path.join(folder, f"{target}{animlib.BANIM_SUFFIX}")
    shutil.copyfile(src_banim, dst_banim)
    out["banim"] = dst_banim
    out["tracks"] = _count_tracks(dst_banim)

    src_xml = animlib.xml_path(root, source)
    dst_xml = os.path.join(folder, f"{target}{animlib.XML_SUFFIX}")
    if os.path.isfile(src_xml):
        clips = animxmllib.load(src_xml)
    else:
        from rr3lib import banim as banimlib
        duration = banimlib.load(dst_banim).duration_ms
        clips = animxmllib.wing_pair(0, animxmllib.frames_for(duration))
    animxmllib.save(clips, dst_xml)
    out["xml"] = dst_xml
    out["clips"] = len(clips)
    return out
