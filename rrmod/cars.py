"""Per-car reference data: PR, class, price, which events a car belongs to.

The numbers come from a community-maintained table of the retail game
(``data/cars.csv``, shipped with the manager).  It is *reference* data only -
nothing here is written to the install, and a car missing from the table is not
an error, it just has fewer columns to sort by.

Matching is the interesting part.  The table is keyed by manufacturer and model
as the game's own UI spells them ("Datsun 240Z"), while our folders are keyed by
a lower-case slug built from the same words in a different order
("1970_datsun_240z").  There is no id column in the table, so a match is a
guess; the rules below are ordered from safest to loosest and the caller is
told which rule fired so the UI can show "matched" differently from "guessed".
"""

from __future__ import annotations

import csv
import os
import re
import unicodedata

#: Columns we actually use.  The rest is kept so the UI can show it verbatim.
COLUMNS = ("manufacturer", "model", "pr", "top_speed", "acceleration", "braking",
           "grip", "car_class", "type", "series", "price", "service_time",
           "service_cost", "available", "exclusive", "motorsports", "road",
           "career", "seasons")

_TRUE = ("yes", "true", "1", "y")

_HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_HERE, "data", "cars.csv")

_cache: dict = {}


def _num(text: str):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _yes(text: str) -> bool:
    return str(text or "").strip().lower() in _TRUE


def _norm(text: str) -> str:
    """Lower case, no punctuation, single spaces - the shape both sides share."""
    text = unicodedata.normalize("NFKD", text or "")
    text = text.lower()
    text = re.sub(r"\([^)]*\)", " ", text)          # "(2017)" carries no meaning
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _slug_words(name: str) -> str:
    """``2012_lexus_lfa`` -> ``lexus lfa`` (the year is handled separately)."""
    parts = name.split("_")
    if parts and parts[0].isdigit():
        parts = parts[1:]
    return _norm(" ".join(parts))


#: Spellings our folders use that the table spells differently.  Kept short on
#: purpose: every entry is a claim we can check, and a wrong entry silently
#: attaches the wrong PR to a car, which is worse than showing no PR at all.
ALIASES = {
    "commondre": "commodore",       # typo in the game's own folder name
    "boxter": "boxster",
    "vipersrt": "viper srt",
    "cgtspeed": "continental gt speed",
    "silvias15": "silvia s15",
    "lancer": "lancer evolution",
}


def _compact(text: str) -> str:
    """Letters and digits only - folds ``Aston Martin`` into ``astonmartin``.

    Our folders squash multi-word manufacturers into one token
    (``2013_astonmartin_vanquish``) while the table keeps the space, so a
    whitespace-sensitive comparison alone loses 30-odd cars.
    """
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


class CarRef:
    """One row of the reference table."""

    __slots__ = COLUMNS + ("raw", "key", "words", "compact", "model_compact")

    def __init__(self, row: dict):
        self.raw = row
        self.manufacturer = (row.get("Manufacturer") or "").strip()
        self.model = (row.get("Model") or "").strip()
        self.pr = _num(row.get("PR"))
        self.top_speed = _num(row.get("Top Speed"))
        self.acceleration = _num(row.get("Acceleration"))
        self.braking = _num(row.get("Braking"))
        self.grip = _num(row.get("Grip"))
        self.car_class = (row.get("Class") or "").strip()
        self.type = (row.get("Type") or "").strip()
        self.series = (row.get("Series") or "").strip()
        self.price = (row.get("Price") or "").strip()
        self.service_time = _num(row.get("Service Time"))
        self.service_cost = _num(row.get("Service Cost"))
        self.available = _yes(row.get("Is Available"))
        self.exclusive = _yes(row.get("Has Exclusive Events"))
        self.motorsports = _yes(row.get("In Motorsports"))
        self.road = _yes(row.get("In Road Collection"))
        self.career = _yes(row.get("In Main Career"))
        self.seasons = tuple(i for i in range(1, 6) if _yes(row.get(f"In Season {i}")))
        self.key = _norm(f"{self.manufacturer} {self.model}")
        self.words = set(self.key.split())
        self.compact = _compact(self.key)
        self.model_compact = _compact(self.model)

    @property
    def label(self) -> str:
        return f"{self.manufacturer} {self.model}".strip()

    def __repr__(self) -> str:                       # pragma: no cover - debug
        return f"<CarRef {self.label!r} PR={self.pr}>"


def load(path: str = "") -> list:
    """Every row of the reference table (parsed once, then cached)."""
    path = path or CSV_PATH
    if path in _cache:
        return _cache[path]
    rows = []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            for raw in csv.DictReader(fh):
                if (raw.get("Manufacturer") or "").strip():
                    rows.append(CarRef(raw))
    except OSError:
        rows = []
    _cache[path] = rows
    return rows


def available() -> bool:
    return bool(load())


# ---------------------------------------------------------------------------
# matching a folder name to a table row
# ---------------------------------------------------------------------------
def _score(folder_compact: str, folder_words: list, year: str, ref: CarRef) -> float:
    """How well the folder name and the reference name describe each other.

    Both directions matter.  The folder is usually the *shorter* slug, so every
    folder word must appear in the reference (``audi tt`` must not lose to
    ``Audi R8``), and the share of the reference that the folder spells out
    decides between candidates (``Audi TT`` beats ``Audi TT RS Coupe`` only
    when the folder says ``rs`` too).  The two shares are averaged.

    Anything the folder spells out that the table does *not* (``r3``,
    ``nascar``, ``gt4``) is ignored rather than penalised: those are trim or
    series labels the table simply does not carry.
    """
    ref_words = [w for w in ref.key.split() if w]
    if not ref_words or not folder_words:
        return 0.0
    in_ref = sum(1 for w in folder_words if w in ref.compact)
    in_folder = sum(1 for w in ref_words if w in folder_compact)
    forward = in_ref / len(folder_words)
    backward = in_folder / len(ref_words)
    if forward < 1.0:
        # a folder word the table never mentions means this is a different car
        # (``190`` vs ``A 45``), not a looser spelling of the same one
        return 0.0
    score = 0.5 * (forward + backward)
    # a year the table also records for this model is a strong signal
    if year and year in (ref.raw.get("Model") or ""):
        score += 0.05
    # between two equally good candidates prefer the simpler name
    score -= 0.001 * len(ref_words)
    return score


def _match_words(words: str, year: str, refs: list) -> tuple:
    """Best reference row for an already-normalised name."""
    if not words:
        return None, ""
    for ref in refs:
        if ref.key == words:
            return ref, "exact"
    compact = _compact(words)
    tokens = words.split()
    best = None
    best_score = 0.0
    for ref in refs:
        s = _score(compact, tokens, year, ref)
        if s > best_score:
            best, best_score = ref, s
    if best is not None and best_score >= 0.72:
        return best, "model"
    return None, ""


def match(name: str, refs: list | None = None, *, display: str = "",
          make: str = "") -> tuple:
    """Best row for a car; returns ``(CarRef | None, rule)``.

    ``name`` is the folder slug, ``display`` the game's own name for the car
    (``CAR_NAME_BUGATTI_VITESSE`` -> *Veyron 16.4 Grand Sport Vitesse*) and
    ``make`` the manufacturer from the spec.  The display name is tried first
    because it is what the table is written in; the folder slug is the fallback
    for the ~100 cars whose spec has no display name.

    ``rule`` is ``"exact"``, ``"display"``, ``"model"`` or ``""``.
    """
    refs = refs if refs is not None else load()
    if not refs:
        return None, ""
    parts = name.split("_")
    year = parts[0] if parts and parts[0].isdigit() else ""
    if display:
        words = _norm(f"{make} {display}")
        ref, rule = _match_words(words, year, refs)
        if ref is not None:
            return ref, "display" if rule == "exact" else "display"
        # the table sometimes omits the manufacturer ("Veyron 16.4")
        ref, rule = _match_words(_norm(display), year, refs)
        if ref is not None:
            return ref, "display"
    words = _slug_words(name)
    return _match_words(words, year, refs)


def index_by_name(names) -> dict:
    """``{folder name: CarRef}`` for the names that could be matched."""
    refs = load()
    out = {}
    for name in names:
        ref, _rule = match(name, refs)
        if ref is not None:
            out[name] = ref
    return out


def manufacturers() -> list:
    return sorted({r.manufacturer for r in load() if r.manufacturer})


def classes() -> list:
    order = "X S R M1 M2 M3 M4".split()
    seen = {r.car_class for r in load() if r.car_class}
    return [c for c in order if c in seen] + sorted(seen - set(order))


def summary() -> dict:
    refs = load()
    return {
        "rows": len(refs),
        "manufacturers": len(manufacturers()),
        "classes": classes(),
        "path": CSV_PATH,
    }


def selftest() -> int:
    refs = load()
    if not refs:
        print("no reference table")
        return 1
    print(f"{len(refs)} rows, {len(manufacturers())} manufacturers, "
          f"classes {classes()}")
    for name in ("2012_lexus_lfa", "2014_mclaren_p1", "1970_datsun_240z"):
        ref, rule = match(name, refs)
        print(f"  {name:34s} -> {ref.label if ref else '(none)':30s} {rule}")
    return 0
