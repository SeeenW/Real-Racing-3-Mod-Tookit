"""Pictures for the track picker, including ones the user supplies.

The game draws a card for 126 of the 162 track names (:mod:`rrmod.tracks`); the
rest have no art at all, and none of them have a *layout* map - the minimap the
game draws while you drive is generated from the track mesh, not stored as a
picture, so there is nothing here to read.

This module is the placeholder for that: it keeps a folder of pictures the user
brings, one per track, keyed by circuit.  It is deliberately a plain folder of
PNGs next to ``rr3mods.json`` rather than anything inside the install, because
nothing is known yet about how a track map would have to be filed for the game
to draw it.  When that is worked out, :func:`store` is the one place that has to
learn about it.
"""

from __future__ import annotations

import os
import shutil

from . import depot as depotlib
from . import tracks as tracklib


#: Folder under the state directory that holds the user's pictures.
FOLDER = "track_maps"

#: What a picture is stored as.  PNG keeps alpha, which a track outline needs.
SUFFIX = ".png"

#: Formats the file dialog offers; Qt decodes all of them.
READABLE = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


class MapError(Exception):
    """A picture could not be read or stored."""


def state_dir(depot: str) -> str:
    """The folder this module writes into, created on demand."""
    return os.path.join(depotlib.state_dir(depot), FOLDER)


def key_of(track: str) -> str:
    """The file stem a track's picture is stored under.

    The circuit, not the whole track name: ``Spa``, ``Spa Sunset`` and
    ``Spa Night`` are the same layout and one picture serves all three.
    """
    circuit = tracklib.circuit_of(track)
    stem = tracklib.stem_of(track)
    if stem:
        return stem
    low = "".join(ch if ch.isalnum() else "_" for ch in circuit.lower())
    return "_".join(part for part in low.split("_") if part) or "track"


def stored(depot: str, track: str) -> str:
    """The picture already stored for a track, or ``""``."""
    path = os.path.join(state_dir(depot), key_of(track) + SUFFIX)
    return path if os.path.isfile(path) else ""


def store(depot: str, track: str, picture: str, *, log=None) -> dict:
    """Copy a picture in as this track's map.  Returns what it wrote."""
    if not os.path.isfile(picture):
        raise MapError(f"{os.path.basename(picture)} is not there any more")
    if os.path.splitext(picture)[1].lower() not in READABLE:
        raise MapError(f"{os.path.basename(picture)} is not a picture this can read "
                       f"({', '.join(READABLE)})")
    folder = state_dir(depot)
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, key_of(track) + SUFFIX)
    if os.path.abspath(picture) != os.path.abspath(target):
        shutil.copyfile(picture, target)
    if log:
        log(f"stored the map for {tracklib.circuit_of(track)} as "
            f"{os.path.basename(target)}")
    return {"path": target, "track": track, "circuit": tracklib.circuit_of(track),
            "bytes": os.path.getsize(target)}


def forget(depot: str, track: str) -> bool:
    """Delete the stored picture for a track.  True when one was there."""
    path = stored(depot, track)
    if not path:
        return False
    os.remove(path)
    return True


def picture_for(depot: str, track: str) -> tuple:
    """``(path, "mine" | "game" | "")`` for a track.

    A picture the user supplied wins over the game's own card, because they
    went to the trouble of picking it.
    """
    mine = stored(depot, track)
    if mine:
        return mine, "mine"
    from . import atlas as atlaslib
    for folder, image in tracklib.picture_names(track):
        if atlaslib.has(depot, folder, image):
            return f"atlas:{folder}/{image}", "game"
    return "", ""


def missing(depot: str, tracks) -> list:
    """Track names that have neither a stored picture nor a game card."""
    return [name for name in tracks if not picture_for(depot, name)[0]]


def summary(depot: str, tracks) -> dict:
    names = list(tracks)
    mine = sum(1 for name in names if stored(depot, name))
    game = 0
    for name in names:
        path, source = picture_for(depot, name)
        if source == "game":
            game += 1
    return {
        "tracks": len(names),
        "circuits": len(tracklib.group(names)),
        "with_picture": len(names) - len(missing(depot, names)),
        "mine": mine,
        "from_game": game,
        "without": len(missing(depot, names)),
        "folder": state_dir(depot),
    }


def selftest(depot: str, tracks) -> int:
    """Read back every stored picture; returns how many failed."""
    from . import series as serieslib
    bad = 0
    folder = state_dir(depot)
    if not os.path.isdir(folder):
        return 0
    for name in os.listdir(folder):
        if not name.lower().endswith(SUFFIX):
            continue
        try:
            serieslib.read_picture(os.path.join(folder, name))
        except Exception:                        # noqa: BLE001
            bad += 1
    return bad
