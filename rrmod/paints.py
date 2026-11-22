"""The paint finishes the game itself offers, read from ``custom.paints.nct``.

The livery file says *which material* a paint scheme uses (slot 30 is the body,
slot 745 the rear wing), but it says nothing about what those materials look
like.  The game's own customiser is what knows: ``custom.paints.nct`` lists 31
ready-made finishes - gloss, matte, metallic, chrome, gold and five candy
colours - each naming the material to use and the colour it starts as.

That table is the safe list to offer.  The material library has 71 names with
"paint" in them, including ``car_bumper_paint_*`` and map surfaces; picking one
of those for a car body gives a car that looks like a wall.  Everything in this
table is a finish the game ships on a real car.

The colours in ``custom.colours.nct`` are the 42 swatches the game puts in its
colour picker.  Offering them means a custom paint can start from a colour the
game is known to render well, with the free-form picker still available.
"""

from __future__ import annotations

import os
import struct

from rr3lib import gamematerial as gamematerial
from rr3lib import livery as liverylib
from rr3lib import nct as nctlib

#: Where the tables live, relative to the depot.
DATA_DIR = "vehicles/data"
PAINTS = "custom.paints.nct"
COLOURS = "custom.colours.nct"

#: The material the game puts on a car body when nothing says otherwise.
DEFAULT_MATERIAL = "car_paint_gloss"

#: Human labels for the finish families, in the order the table groups them.
FAMILIES = (
    ("gloss", "Gloss"),
    ("matte", "Matte"),
    ("metallic", "Metallic"),
    ("chrome", "Chrome"),
    ("gold", "Gold"),
    ("candy", "Candy"),
)


class PaintError(Exception):
    """Raised when a paint table cannot be read or written."""


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def _plain(path: str) -> bytes:
    """The table's bytes, decrypted when the file on disk is encrypted."""
    with open(path, "rb") as fh:
        blob = fh.read()
    return nctlib.crypt(blob) if nctlib.looks_encrypted(blob) else blob


def _str(data: bytes, pos: int) -> tuple[str, int]:
    length = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    if length > 4096 or pos + length > len(data):
        raise PaintError(f"a string at {pos - 4} claims {length} bytes")
    return data[pos:pos + length].decode("ascii", "replace"), pos + length


def _put_str(out: bytearray, text: str) -> None:
    raw = text.encode("ascii")
    out += struct.pack("<I", len(raw))
    out += raw


class Finish:
    """One row of ``custom.paints.nct``: a material, a colour and a name."""

    __slots__ = ("id", "name_key", "colour_key", "rgb", "material", "texture",
                 "tail", "flag")

    def __init__(self, id, name_key, colour_key, rgb, material, texture, tail, flag):
        self.id = id
        self.name_key = name_key
        self.colour_key = colour_key
        self.rgb = rgb
        self.material = material
        self.texture = texture
        self.tail = tail
        self.flag = flag

    @property
    def family(self) -> str:
        """``gloss`` / ``matte`` / ``metallic`` / ``chrome`` / ``gold`` / ``candy``."""
        key = self.name_key.upper()
        for token, _label in FAMILIES:
            if f"_{token.upper()}_" in key:
                return token
        if "CHROME" in key:
            return "chrome"
        if "GOLD" in key:
            return "gold"
        return ""

    @property
    def label(self) -> str:
        """``Metallic white`` - the family plus the colour name, for a menu."""
        word = self.colour_key.rsplit("_", 1)[-1].replace("_", " ").lower()
        family = self.family.capitalize() or "Paint"
        return f"{family} {word}"

    def __repr__(self) -> str:                                # pragma: no cover
        return f"<Finish {self.label} {self.material}>"


def parse_paints(data: bytes) -> list:
    """Every finish in ``custom.paints.nct``, in file order."""
    return parse_paints_with_tail(data)[0]


def parse_paints_with_tail(data: bytes) -> tuple:
    """``(finishes, trailing_bytes)``.

    ``custom.paints.nct`` is the only one of the ``custom.*`` tables with a
    trailer: 102 bytes reading ``Author:@depot`` and a URL.  Nothing in the game
    seems to read it, but it is part of the file, so it is carried through
    untouched rather than silently dropped on the first save.
    """
    if len(data) < 8:
        raise PaintError("custom.paints.nct is too short to be a table")
    count = struct.unpack_from("<I", data, 4)[0]
    pos = 8
    out = []
    for index in range(count):
        if pos + 4 > len(data):
            raise PaintError(f"record {index} runs past the end of the table")
        ident = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        name_key, pos = _str(data, pos)
        colour_key, pos = _str(data, pos)
        rgb, pos = _str(data, pos)
        material, pos = _str(data, pos)
        texture, pos = _str(data, pos)
        if pos + 28 > len(data):
            raise PaintError(f"record {index} is missing its tail")
        tail = struct.unpack_from("<6I", data, pos)
        pos += 24
        flag = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        out.append(Finish(ident, name_key, colour_key, rgb, material, texture,
                          tail, flag))
    return out, data[pos:]


def build_paints(finishes: list, tail: bytes = b"") -> bytes:
    """The table's bytes, from a list of :class:`Finish`."""
    out = bytearray()
    out += struct.pack("<II", 10, len(finishes))
    for f in finishes:
        out += struct.pack("<i", f.id)
        _put_str(out, f.name_key)
        _put_str(out, f.colour_key)
        _put_str(out, f.rgb)
        _put_str(out, f.material)
        _put_str(out, f.texture)
        out += struct.pack("<6I", *f.tail)
        out += struct.pack("<I", f.flag)
    out += tail
    return bytes(out)


def paints_path(depot: str) -> str:
    return os.path.join(depot, DATA_DIR, PAINTS)


def colours_path(depot: str) -> str:
    return os.path.join(depot, DATA_DIR, COLOURS)


def load(depot: str) -> list:
    """Read the finishes out of an install."""
    path = paints_path(depot)
    if not os.path.isfile(path):
        raise PaintError(f"this install has no {PAINTS}")
    return parse_paints(_plain(path))


def save(depot: str, finishes: list, *, path: str = "", tail: bytes = b"") -> str:
    """Write the table back, verifying it reads the same way first.

    ``tail`` is the 102-byte ``Author:@depot`` trailer the shipped file carries;
    pass it back or it is dropped.
    """
    blob = build_paints(finishes, tail)
    again = parse_paints(blob)
    if len(again) != len(finishes):
        raise PaintError("the paint table did not read back - not written")
    target = path or paints_path(depot)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(blob)
    return target


def load_with_tail(depot: str) -> tuple:
    """``(finishes, tail)`` for a save that keeps the trailer."""
    path = paints_path(depot)
    if not os.path.isfile(path):
        raise PaintError(f"this install has no {PAINTS}")
    return parse_paints_with_tail(_plain(path))


# ---------------------------------------------------------------------------
# the swatches
# ---------------------------------------------------------------------------

def parse_colours(data: bytes) -> list:
    """The game's own colour picker, as ``[(r, g, b), ...]``."""
    if len(data) < 8:
        raise PaintError("custom.colours.nct is too short to be a table")
    count = struct.unpack_from("<I", data, 4)[0]
    pos = 8
    out = []
    for _ in range(count):
        text, pos = _str(data, pos)
        parts = [int(v) for v in text.split(",")[:3]]
        while len(parts) < 3:
            parts.append(0)
        out.append(tuple(max(0, min(255, v)) for v in parts))
    return out


def build_colours(colours: list) -> bytes:
    out = bytearray()
    out += struct.pack("<II", 2, len(colours))
    for rgb in colours:
        _put_str(out, "%d,%d,%d" % tuple(rgb[:3]))
    return bytes(out)


def colours(depot: str) -> list:
    """The 42 swatches the game offers, or an empty list if the table is gone."""
    path = colours_path(depot)
    if not os.path.isfile(path):
        return []
    try:
        return parse_colours(_plain(path))
    except PaintError:
        return []


# ---------------------------------------------------------------------------
# what a car may be painted with
# ---------------------------------------------------------------------------

def materials(depot: str) -> list:
    """The distinct materials the game's own finishes use, in file order."""
    seen = []
    for finish in load(depot):
        if finish.material not in seen:
            seen.append(finish.material)
    return seen


def finishes_for(depot: str, material: str) -> list:
    """The finishes that use one material - what its colour list should be."""
    return [f for f in load(depot) if f.material == material]


def label_for(material: str) -> str:
    """``car_paint_metallic_white`` -> ``Metallic white``.

    The material name is the better label: eight rows of the table share
    ``car_paint_gloss`` and each starts from a different colour, so the first
    row's colour name would be wrong for the other seven.

    The ``car_bumper_paint_*`` family gets a "Bumper" prefix, because it is the
    same 22 finishes aimed at a bumper rather than a body and the two would
    otherwise read identically in the list.
    """
    stem = material
    bumper = False
    if stem.startswith("car_paint_"):
        stem = stem[len("car_paint_"):]
    elif stem.startswith("car_bumper_paint_"):
        stem = stem[len("car_bumper_paint_"):]
        bumper = True
    words = stem.replace("_", " ").strip()
    if not words:
        return material
    head, _, rest = words.partition(" ")
    if head in {token for token, _label in FAMILIES}:
        words = f"{head.capitalize()} {rest}".strip()
    else:
        words = words.capitalize()
    return f"Bumper {words}" if bumper else words


def writable(depot: str) -> list:
    """Every paint material a car can actually be pointed at.

    There are two lists, and they are not the same one:

    * the finishes ``custom.paints.nct`` offers the player - 15 materials;
    * the paint materials the *shipped cars* use, which is what
      ``liveryStringTable`` carries slots for - 24 ``car_paint_*`` and 26
      ``car_bumper_paint_*``.

    Only the second list can be written, because a livery override is a slot
    number and a material with no slot has nothing to write.  Six of the
    customiser's own finishes (``car_paint_gold`` and the five candies) are in
    that position: they exist in ``materials.bin`` and the game can paint a car
    with them in its own customiser, but no shipped car ever did, so there is no
    slot for a livery file to name.  They are left out rather than offered and
    then refused.

    What *is* worth having beyond the customiser's menu is the rest of what the
    factory cars use: the 18 extra ``car_paint_metallic_*`` variants (including
    the four ``_spec_`` flake ones), ``car_paint_matte_high``,
    ``car_paint_pearl_blue``, ``car_paint_carbon_fibre``, and the whole bumper
    family.  Those are ordinary livery slots and work exactly like the others.
    """
    try:
        table = liverylib.load_slot_table(depot)
    except Exception:                            # noqa: BLE001
        return []
    try:
        have = set(gamematerial.load(depot).materials)
    except Exception:                            # noqa: BLE001
        # Without the material library there is nothing to check against, so
        # fall back to the livery table alone rather than offering nothing.
        have = None
    out = []
    for name in table.materials():
        if have is not None and name not in have:
            continue
        if not (name.startswith("car_paint_")
                or name.startswith("car_bumper_paint_")):
            continue
        out.append(name)
    return out


def table_slot(depot: str, material: str):
    """The livery slot number a material is known by, or ``None``.

    A material with no slot cannot be named by a livery file, which is the whole
    reason :func:`writable` exists.
    """
    try:
        return liverylib.load_slot_table(depot).material_slot(material)
    except Exception:                            # noqa: BLE001
        return None


def choices(depot: str) -> list:
    """``[(label, material), ...]`` for a finish dropdown, one per material.

    Several rows of the table share a material (eight glosses all use
    ``car_paint_gloss``), so the label comes from the material and the rest only
    contribute their colours - see :func:`colours_for`.

    The customiser's own menu comes first, in the order it shows it, then the
    paint materials the shipped cars use that the menu does not offer - see
    :func:`writable` for why those are worth having.

    Entries the livery table has no slot for are left out.  Six of the
    customiser's finishes are in that position, so they are visible in the
    game's own customiser but cannot be written here; offering them and then
    failing on Save would be worse than not offering them.
    """
    usable = set(writable(depot))
    out = []
    seen = set()

    def take(material: str) -> None:
        if material in seen or material not in usable:
            return
        seen.add(material)
        out.append((label_for(material), material))

    for token, _label in FAMILIES:
        for finish in load(depot):
            if finish.family == token:
                take(finish.material)
    # Anything whose family we could not name still has to be selectable.
    for material in materials(depot):
        take(material)
    # Now the factory colours the customiser never lists, but which have slots.
    for material in writable(depot):
        take(material)
    return out


def colours_for(depot: str, material: str) -> list:
    """Every colour the game ships that finish in, as ``[(r, g, b), ...]``."""
    out = []
    for finish in finishes_for(depot, material):
        parts = [int(v) for v in finish.rgb.split(",")[:3]]
        while len(parts) < 3:
            parts.append(0)
        rgb = tuple(max(0, min(255, v)) for v in parts)
        if rgb not in out:
            out.append(rgb)
    return out


def starting_colour(depot: str, material: str) -> tuple:
    """The colour the game starts that finish from, or black."""
    for finish in finishes_for(depot, material):
        parts = [int(v) for v in finish.rgb.split(",")[:3]]
        while len(parts) < 3:
            parts.append(0)
        return tuple(max(0, min(255, v)) for v in parts)
    return (0, 0, 0)


def summary(depot: str) -> dict:
    """Counts for a status line."""
    try:
        rows = load(depot)
    except PaintError as exc:
        return {"finishes": 0, "materials": 0, "colours": 0, "error": str(exc)}
    return {
        "finishes": len(rows),
        "materials": len(materials(depot)),
        "colours": len(colours(depot)),
    }


def describe(depot: str) -> str:
    got = summary(depot)
    if got.get("error"):
        return got["error"]
    return (f"{got['finishes']} paint finishes over {got['materials']} materials, "
            f"{got['colours']} swatches")


# ---------------------------------------------------------------------------
# self test
# ---------------------------------------------------------------------------

def selftest(depot: str) -> int:
    """Round-trip both tables and check the obvious invariants. 0 = clean."""
    bad = 0

    def check(ok: bool, what: str) -> None:
        nonlocal bad
        if not ok:
            print(f"FAIL {what}")
            bad += 1

    try:
        rows = load(depot)
    except PaintError as exc:
        print(f"FAIL paints: {exc}")
        return 1
    check(len(rows) > 20, f"finishes ({len(rows)})")
    check(all(f.material.startswith("car_paint_") for f in rows),
          "every finish uses a car paint material")
    check(len(materials(depot)) >= 10, "materials")
    check(all(f.rgb.count(",") == 2 for f in rows), "every finish has an RGB")

    raw = _plain(paints_path(depot))
    rows, tail = parse_paints_with_tail(raw)
    check(build_paints(rows, tail) == raw, "custom.paints.nct round trip")
    check(tail == b"" or b"Author:" in tail,
          f"the trailer is carried through ({len(tail)} bytes)")
    if tail:
        check(build_paints(rows, tail)[-len(tail):] == tail,
              "the trailer lands at the end")

    if os.path.isfile(colours_path(depot)):
        craw = _plain(colours_path(depot))
        got = parse_colours(craw)
        check(len(got) > 20, f"colours ({len(got)})")
        check(build_colours(got) == craw, "custom.colours.nct round trip")
        check(all(0 <= v <= 255 for rgb in got for v in rgb), "colours are in range")

    check(len(choices(depot)) >= len(materials(depot)), "every material is offered")
    return bad
