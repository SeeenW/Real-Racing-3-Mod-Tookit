"""Track names, circuits and the pictures the game already draws for them.

The career file names 162 tracks: ``Spa``, ``Spa Sunset``, ``Bathurst Night``,
``Leipzig GroBer Kurs Dawn`` and so on.  They are one circuit plus a time of
day, and the picker wants them grouped that way.

Pictures: the game ships a card for most circuits, but in three different
folders and with three different naming schemes.  Nothing here downloads
anything - the game's own art is used where it exists, and a track without art
just shows a blank tile.  Missing today: Brazil, Lime Rock and Sebring, whose
only pictures live in quest banners rather than a track card.
"""

from __future__ import annotations

import re

#: Where track pictures live, best first.  The daily race cards are 1024x361 and
#: are a clean side view of the circuit; the time trial cards are portrait and
#: are the fallback.
FOLDERS = ("events/daily_race/regular",
           "events/daily_race/f1",
           "events/event_cards/time_trial_tournament",
           "porsche_build/track_select")

#: Circuit prefix -> the stem the art files use.  Longest prefix wins, so
#: ``Le Mans Bugatti Circuit`` matches ``le mans`` before anything shorter.
CIRCUITS = {
    "bathurst": "bathurst",
    "berlin": "r3berlin",
    "brands hatch": "brandshatch",
    "catalunya": "catalunya",
    "circuit of the americas": "cota",
    "daytona": "daytona",
    "dubai": "dubai",
    "hockenheim": "hockenheim",
    "hong kong": "hongkong",
    "indianapolis": "indianapolis",
    "laguna seca": "lagunaseca",
    "le mans": "lemans",
    "leipzig": "leipzig",
    "melbourne": "melbourne",
    "monaco": "monaco",
    "monza": "monza",
    "new york": "newyork",
    "nurburgring": "nuerburgring",
    "red bull ring": "redbull",
    "richmond": "richmond",
    "silverstone": "silverstone",
    "singapore": "singapore",
    "spa": "spa",
    "suzuka": "suzuka",
    "yas marina": "yasmarina",
}

#: How a picture for a circuit stem is spelled in each folder, in order.
#: ``{stem}_track_noon.png`` is the daily race card; ``ttt_track_card_{stem}.png``
#: is the time trial one; ``porsche_track_card_{stem}.png`` is the Porsche build
#: picker's.
PATTERNS = ("{stem}_track_noon.png",
            "{stem}_track_night.png",
            "{stem}_track_morning.png",
            "{stem}_track_afternoon.png",
            "{stem}_track_sunset.png",
            "{stem}_track_dawn.png",
            "ttt_track_card_{stem}.png",
            "porsche_track_card_{stem}.png")

#: Stems whose picture is spelled differently from the circuit stem.
STEM_ALIASES = {
    "nuerburgring": ("nuerburgring", "nurburgring"),
    "lagunaseca": ("lagunaseca", "seca"),
    "brandshatch": ("brandshatch", "hatch"),
}

#: Time of day suffixes a track name may end in, longest first so ``Sunset``
#: is not read as ``Sun``.
TIMES = ("afternoon", "morning", "sunset", "night", "dawn", "noon")


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def circuit_of(track: str) -> str:
    """The circuit part of a track name, as the career file spells it.

    ``Spa Sunset`` -> ``Spa``;  ``Lime rock South dawn`` -> ``Lime rock South``;
    ``Formula E - New York 2021 Morning`` -> ``Formula E - New York 2021``.
    """
    low = normalise(track)
    for when in TIMES:
        if low.endswith(" " + when):
            # Strip it from the original so the spelling survives.
            cut = len(track) - len(track.rstrip())
            body = track[:len(track) - cut]
            if normalise(body).endswith(" " + when):
                body = body[:body.lower().rfind(when)].rstrip(" -_")
                return body or track
    return track


def time_of_day(track: str) -> str:
    low = normalise(track)
    for when in TIMES:
        if low.endswith(" " + when):
            return when
    return ""


def stem_of(track: str) -> str:
    """The art stem for a track name, or ``""`` when the game has no picture."""
    low = normalise(track)
    # "Formula E - New York 2021" is drawn with the plain New York card.
    if low.startswith("formula e "):
        low = low[len("formula e "):].strip()
    # Longest matching circuit name wins.
    best = ""
    for name in CIRCUITS:
        if low == name or low.startswith(name + " ") or low.startswith(name):
            if len(name) > len(best):
                best = name
    if not best:
        return ""
    return CIRCUITS[best]


def picture_names(track: str) -> list:
    """Candidate image names for a track, most likely first.

    Returned as ``(folder, name)`` pairs; the caller tries them in order and
    stops at the first one the depot actually has.
    """
    stem = stem_of(track)
    if not stem:
        return []
    stems = STEM_ALIASES.get(stem, (stem,))
    out = []
    for folder in FOLDERS:
        for pattern in PATTERNS:
            for one in stems:
                out.append((folder, pattern.format(stem=one)))
    return out


def group(tracks) -> dict:
    """``{circuit: [track, ...]}`` with the tracks of a circuit in time order."""
    out = {}
    for track in tracks:
        out.setdefault(circuit_of(track), []).append(track)
    order = {when: i for i, when in enumerate(TIMES)}
    for circuit, names in out.items():
        names.sort(key=lambda t: (order.get(time_of_day(t), -1), t.lower()))
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


def summary(tracks) -> dict:
    grouped = group(tracks)
    return {
        "tracks": len(tracks),
        "circuits": len(grouped),
        "with_art": sum(1 for t in tracks if stem_of(t)),
    }
