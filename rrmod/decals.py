"""What the vinyl editor offers: the decal list, its font, and its categories.

``rr3lib.decals`` reads and writes ``custom.decals.nct``.  This module answers
the questions a page needs on top of that: what each record is called in the
player's language, whether the glyph it draws is actually in the font, and which
of the two halves of the list a record belongs to.

Three facts drive the whole page and are worth stating once:

* **A record draws either a glyph or a page, never both.**  187 of the 229
  records draw a glyph out of ``r3_decals.ttf``; the other 42 draw a ``.pvr``
  picture under ``vehicles/decals/``.  Nothing in the file marks which is which,
  so it is decided by which field is filled in.

* **The font is the list's other half.**  Every glyph record names a code point,
  and the shape only appears in the game if that code point is in the font.  All
  163 code points the shipped list uses are in the shipped font, so a missing one
  means somebody added a record without adding a shape.

* **The names are not in the text files.**  Only 30 of the 229 name keys exist in
  ``gametext.txt`` - the two event categories, where every record in the group
  shares one name.  The rest are silently absent and the game shows the shape
  itself, so the page has to fall back to something readable rather than show a
  blank row.
"""

from __future__ import annotations

import os

from rr3lib import decals as decallib
from rr3lib import texts as textlib

#: Where the font lives, relative to the depot.
FONT = decallib.FONT

#: The prefix every category key carries; the middle is what the page shows.
CATEGORY_PREFIX = "GAMETEXT_CUSTOMISATION_DECALS_"
CATEGORY_SUFFIX = "_NAME"


class DecalError(Exception):
    """The list or the font could not be read."""


# ---------------------------------------------------------------------------
# the font
# ---------------------------------------------------------------------------

def font_path(depot: str) -> str:
    return os.path.join(depot, FONT)


def _cmap4(raw: bytes, sub: int) -> dict:
    """One format 4 subtable as ``{code point: glyph id}``."""
    import struct

    seg_x2 = struct.unpack_from(">H", raw, sub + 6)[0]
    seg = seg_x2 // 2
    ends = struct.unpack_from(f">{seg}H", raw, sub + 14)
    starts = struct.unpack_from(f">{seg}H", raw, sub + 16 + seg_x2)
    deltas = struct.unpack_from(f">{seg}h", raw, sub + 16 + 2 * seg_x2)
    offsets = struct.unpack_from(f">{seg}H", raw, sub + 16 + 3 * seg_x2)
    out = {}
    for index in range(seg):
        for code in range(starts[index], ends[index] + 1):
            if code == 0xFFFF:
                continue
            if offsets[index] == 0:
                got = (code + deltas[index]) & 0xFFFF
            else:
                at = (sub + 16 + 3 * seg_x2 + 2 * seg + offsets[index]
                      + 2 * (code - starts[index]))
                if at + 2 > len(raw):
                    continue
                got = struct.unpack_from(">H", raw, at)[0]
                if got:
                    got = (got + deltas[index]) & 0xFFFF
            out[code] = got
    return out


def font_code_points(path: str) -> dict:
    """``{code point: glyph id}`` from a TrueType file's ``cmap``.

    Only format 4 is read, because that is what the game's own font uses for
    both of its encodings.  A font with only format 12 raises rather than
    returning an empty map, since "no code points" and "cannot read this" would
    otherwise look the same to the page.
    """
    import struct

    if not os.path.isfile(path):
        raise DecalError(f"there is no font at {path}")
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) < 12:
        raise DecalError(f"{os.path.basename(path)} is {len(raw)} bytes, too short "
                         f"to be a font")
    tag, count = struct.unpack_from(">IH", raw, 0)
    if tag not in (0x00010000, 0x74727565):
        raise DecalError(f"{os.path.basename(path)} does not start with a font "
                         f"signature (found {tag:#010x})")
    table = None
    for index in range(count):
        at = 12 + index * 16
        if raw[at:at + 4] == b"cmap":
            table = struct.unpack_from(">I", raw, at + 8)[0]
            break
    if table is None:
        raise DecalError(f"{os.path.basename(path)} has no cmap table")
    seen = {}
    subtables = struct.unpack_from(">H", raw, table + 2)[0]
    for index in range(subtables):
        at = table + 4 + index * 8
        offset = struct.unpack_from(">I", raw, at + 4)[0]
        sub = table + offset
        if sub + 2 > len(raw):
            continue
        if struct.unpack_from(">H", raw, sub)[0] != 4:
            continue
        for code, glyph in _cmap4(raw, sub).items():
            seen.setdefault(code, glyph)
    if not seen:
        raise DecalError(f"{os.path.basename(path)} has no format 4 cmap, so its "
                         f"shapes cannot be looked up by code point")
    return seen


def font_glyphs(path: str) -> int:
    """How many glyphs the font declares."""
    import struct

    with open(path, "rb") as fh:
        raw = fh.read()
    tag, count = struct.unpack_from(">IH", raw, 0)
    for index in range(count):
        at = 12 + index * 16
        if raw[at:at + 4] == b"maxp":
            offset = struct.unpack_from(">I", raw, at + 8)[0]
            return struct.unpack_from(">H", raw, offset + 4)[0]
    return 0


# ---------------------------------------------------------------------------
# the list
# ---------------------------------------------------------------------------

def load(depot: str):
    try:
        return decallib.load(depot)
    except decallib.DecalError as exc:
        raise DecalError(str(exc)) from exc


def category_label(key: str) -> str:
    """``GAMETEXT_CUSTOMISATION_DECALS_FLAGS_NAME`` -> ``FLAGS``."""
    text = key
    if text.startswith(CATEGORY_PREFIX):
        text = text[len(CATEGORY_PREFIX):]
    if text.endswith(CATEGORY_SUFFIX):
        text = text[:-len(CATEGORY_SUFFIX)]
    return text.replace("_", " ").title() or key


def _fallback_name(decal) -> str:
    """Something readable when the text table has no key for this record."""
    page = decal.picture
    if page:
        return os.path.splitext(os.path.basename(page))[0].replace("decal_", "").replace("_", " ").title()
    code = decal.code_point
    if code is not None:
        if 0x20 <= code < 0x7F:
            return f"Glyph {chr(code)!r}"
        return f"Glyph U+{code:04X}"
    return f"Decal {decal.id}"


def _texts(depot: str, texts=None):
    """The game's own strings, or nothing.

    The working copy holds the tables but not ``gametext.txt`` - that lives at
    the root of ``.depot`` and no car edit ever writes it, so it is not mirrored.
    Reading a working copy therefore has to be allowed to come up without the
    text table; the page then shows the shape's fallback name instead of failing
    outright, which is what it did the first time a car had been edited.
    """
    if texts is not None:
        return texts
    try:
        return textlib.Texts.load(depot)
    except Exception:                            # noqa: BLE001 - names are optional
        return None


def rows(depot: str, texts=None) -> list:
    """Every record as a dict, with the name the player sees resolved."""
    got = load(depot)
    table = _texts(depot, texts)
    font = {}
    path = font_path(depot)
    if os.path.isfile(path):
        try:
            font = font_code_points(path)
        except DecalError:
            font = {}
    out = []
    for position, decal in enumerate(got.decals):
        name_key = decal.name_key
        named = table.has(name_key) if table is not None else False
        shown = table.get(name_key) if named else ""
        code = decal.code_point
        out.append({
            "id": decal.id,
            "position": position,
            "category": decal.category_key,
            "category_label": category_label(decal.category_key),
            "name": name_key,
            "shown": shown or _fallback_name(decal),
            "has_name": named,
            "kind": "glyph" if decal.glyph else "page",
            "glyph": decal.glyph.decode("latin-1"),
            "code_point": code,
            "in_font": (code in font) if code is not None else None,
            "page": decal.picture,
            "decal": decal,
        })
    return out


def summary(depot: str, texts=None) -> dict:
    """Counts the page shows above the table."""
    got = load(depot)
    path = font_path(depot)
    codes = set()
    glyphs = 0
    if os.path.isfile(path):
        try:
            codes = set(font_code_points(path))
            glyphs = font_glyphs(path)
        except DecalError:
            pass
    used = got.code_points()
    table = _texts(depot, texts)
    named = 0
    if table is not None:
        named = sum(1 for d in got.decals if table.has(d.name_key))
    return {
        "version": got.version,
        "decals": len(got),
        "categories": len(got.categories()),
        "glyphs": sum(1 for d in got.decals if d.glyph),
        "pages": sum(1 for d in got.decals if d.page),
        "code_points": len(used),
        "font_code_points": len(codes),
        "font_glyphs": glyphs,
        "missing_from_font": len(used - codes),
        "named": named,
        "unnamed": len(got) - named,
        "trailer": len(got.trailer),
    }


def problems(depot: str, texts=None) -> list:
    """Things worth saying out loud, as ``(level, text)`` pairs."""
    got = summary(depot, texts)
    out = []
    if got["missing_from_font"]:
        out.append(("error",
                    f"{got['missing_from_font']} decal(s) draw a code point the "
                    f"font does not carry, so they show as nothing in the game"))
    if got["unnamed"]:
        out.append(("note",
                    f"{got['unnamed']} of {got['decals']} decal(s) have no entry "
                    f"in gametext.txt; the game shows the shape itself for those"))
    if not got["font_glyphs"]:
        out.append(("note",
                    f"{FONT} could not be read, so the page cannot say whether a "
                    f"glyph will appear"))
    return out


def selftest(depot: str) -> list:
    """Checks the page's own reading against the file."""
    out = []

    def check(name, ok, detail=""):
        out.append((name, bool(ok), detail))

    got = load(depot)
    rows_ = rows(depot)
    check("every record becomes a row", len(rows_) == len(got),
          f"{len(rows_)} rows for {len(got)} records")
    check("every row has something to show",
          all(r["shown"] for r in rows_), "a row with no text")
    check("the glyph rows name a code point",
          all(r["code_point"] is not None for r in rows_ if r["kind"] == "glyph"),
          "a glyph row without a code point")
    check("the page rows name a picture",
          all(r["page"] for r in rows_ if r["kind"] == "page"),
          "a page row without a picture")
    got_font = font_path(depot)
    if os.path.isfile(got_font):
        check("the shipped code points are all in the font",
              summary(depot)["missing_from_font"] == 0, "a missing glyph")
    return out
