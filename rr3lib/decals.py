"""``custom.decals.nct``: the list of shapes and pictures the vinyl editor offers.

The file is a plain count-prefixed list, and it round trips byte for byte, which
is the only reason editing it is safe at all.  Two things about it are not
obvious and are worth stating once:

* A record names its glyph **by code point**, not by an index into the font.
  ``b"0x0029"`` and ``b"0"`` are both code points written as text - the first in
  hex, the second as the character itself.  148 of the 229 records use the hex
  form and 81 use the character.  Reading them as one or the other loses most of
  the list.
* The picture and the glyph are alternatives, not both required: 187 records
  point at a ``.pvr`` page under ``vehicles/decals/`` and carry no glyph text,
  while 42 carry a glyph and no page.

The 162 bytes after the last record are an author trailer.  It is not part of
the list - the count says where the list ends - and it must be carried through
unchanged, the same way ``custom.paints.nct`` keeps its trailer.
"""

from __future__ import annotations

import struct

from . import nct

DECALS = "vehicles/data/custom.decals.nct"
DECALPACKS = "vehicles/data/custom.decalpacks.nct"
FONT = "r3_decals.ttf"

#: ``version`` at the head of the file.  Written back as found rather than
#: forced, so a future file is not silently downgraded.
VERSION = 11

#: A code point written as ``0x0029`` (lower case, four digits, always this
#: shape in the shipped file) or as the character itself.
_HEX_PREFIX = b"0x"

_MAX_STRING = 512
_MAX_COUNT = 100_000


class DecalError(Exception):
    """The file is not the shape this module understands, or a write was refused."""


class Decal:
    """One entry of the vinyl editor's list."""

    __slots__ = ("id", "category", "name", "glyph", "page", "three", "extra",
                 "tail")

    def __init__(self, id: int, category: bytes, name: bytes, glyph: bytes,
                 page: bytes, three, extra: bytes, tail: bytes):
        self.id = id
        self.category = category
        self.name = name
        self.glyph = glyph
        self.page = page
        self.three = three
        self.extra = extra
        self.tail = tail

    # ---- what the interface asks -------------------------------------
    @property
    def category_key(self) -> str:
        return self.category.decode("latin-1")

    @property
    def name_key(self) -> str:
        return self.name.decode("latin-1")

    @property
    def code_point(self):
        """The code point this record draws, or ``None`` when it draws a page.

        ``b"0x0029"`` is parsed as hex and ``b"0"`` as the character itself;
        anything else is not a code point at all.
        """
        text = self.glyph
        if not text:
            return None
        if text.startswith(_HEX_PREFIX):
            try:
                return int(text[2:], 16)
            except ValueError:
                return None
        if len(text) == 1:
            return text[0]
        return None

    @property
    def picture(self) -> str:
        return self.page.decode("latin-1")

    def describe(self) -> dict:
        return {"id": self.id, "category": self.category_key,
                "name": self.name_key, "glyph": self.glyph.decode("latin-1"),
                "code_point": self.code_point, "page": self.picture,
                "has_page": bool(self.page)}


class Decals:
    """The whole file: a version, the records, and the trailer behind them."""

    def __init__(self, version: int = VERSION, decals=None, trailer: bytes = b""):
        self.version = version
        self.decals = list(decals or [])
        self.trailer = trailer

    def __len__(self) -> int:
        return len(self.decals)

    def __iter__(self):
        return iter(self.decals)

    def by_id(self, wanted: int):
        for decal in self.decals:
            if decal.id == wanted:
                return decal
        return None

    def categories(self) -> list:
        """``[(key, count)]``, biggest group first, ties broken by key."""
        counts = {}
        for decal in self.decals:
            counts[decal.category_key] = counts.get(decal.category_key, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def code_points(self) -> set:
        return {d.code_point for d in self.decals if d.code_point is not None}

    def free_id(self) -> int:
        """The lowest positive id no record uses."""
        used = {d.id for d in self.decals}
        got = 1
        while got in used:
            got += 1
        return got

    def summary(self) -> dict:
        return {"version": self.version, "decals": len(self.decals),
                "categories": len(self.categories()),
                "with_page": sum(1 for d in self.decals if d.page),
                "with_glyph": sum(1 for d in self.decals if d.code_point is not None),
                "code_points": len(self.code_points()),
                "trailer": len(self.trailer)}

    def to_bytes(self) -> bytes:
        return serialize(self)


# --------------------------------------------------------------- reading
def _string(raw: bytes, at: int, what: str = "string"):
    if at + 4 > len(raw):
        raise DecalError(f"the file ends where {what} {at} should start")
    length = struct.unpack_from("<I", raw, at)[0]
    at += 4
    if length > _MAX_STRING:
        raise DecalError(f"{what} at {at - 4} claims {length} bytes, which is not "
                         f"a string in this file")
    if at + length > len(raw):
        raise DecalError(f"{what} at {at - 4} runs past the end of the file")
    return raw[at:at + length], at + length


def parse(raw: bytes) -> Decals:
    """Read the whole file.  Raises rather than guessing on a bad one."""
    if len(raw) < 8:
        raise DecalError(f"the file is {len(raw)} bytes, too short to hold a header")
    version, count = struct.unpack_from("<II", raw, 0)
    if count > _MAX_COUNT:
        raise DecalError(f"the header claims {count} decals, which is not a count "
                         f"this file can hold")
    at = 8
    out = []
    for index in range(count):
        try:
            got_id = struct.unpack_from("<i", raw, at)[0]
            at += 4
            category, at = _string(raw, at, f"category of decal {index}")
            name, at = _string(raw, at, f"name of decal {index}")
            glyph, at = _string(raw, at, f"glyph of decal {index}")
            page, at = _string(raw, at, f"page of decal {index}")
            if at + 12 > len(raw):
                raise DecalError(f"decal {index} ends inside its three numbers")
            three = struct.unpack_from("<3I", raw, at)
            at += 12
            extra, at = _string(raw, at, f"trailing name of decal {index}")
            if at + 12 > len(raw):
                raise DecalError(f"decal {index} ends inside its flags")
            tail = raw[at:at + 12]
            at += 12
        except struct.error as exc:
            raise DecalError(f"decal {index} at {at} does not fit: {exc}") from exc
        out.append(Decal(got_id, category, name, glyph, page, three, extra, tail))
    return Decals(version, out, raw[at:])


def load(depot: str) -> Decals:
    import os

    path = os.path.join(depot, *DECALS.split("/"))
    if not os.path.isfile(path):
        raise DecalError(f"no decal list at {path}")
    return parse(nct.read(path))


# --------------------------------------------------------------- writing
def _put_string(value: bytes) -> bytes:
    if len(value) > _MAX_STRING:
        raise DecalError(f"{value[:20]!r} is {len(value)} bytes, too long for this file")
    return struct.pack("<I", len(value)) + value


def serialize(d: Decals) -> bytes:
    """The whole file back, byte for byte when nothing was touched."""
    out = [struct.pack("<II", d.version, len(d.decals))]
    for decal in d.decals:
        out.append(struct.pack("<i", decal.id))
        for value in (decal.category, decal.name, decal.glyph, decal.page):
            out.append(_put_string(value))
        out.append(struct.pack("<3I", *decal.three))
        out.append(_put_string(decal.extra))
        if len(decal.tail) != 12:
            raise DecalError(f"decal {decal.id} has a {len(decal.tail)}-byte flag "
                             f"block; it has to be 12")
        out.append(decal.tail)
    out.append(d.trailer)
    return b"".join(out)


def save(d: Decals, path: str) -> int:
    """Write the file through ``nct``, keeping the encryption it had."""
    import os

    plain = serialize(d)
    was = b""
    if os.path.isfile(path):
        was = open(path, "rb").read()
    encrypted = nct.looks_encrypted(was) if was else False
    nct.write(path, plain, encrypt=encrypted)
    return len(plain)


def save_in(depot: str, d: Decals) -> int:
    import os

    return save(d, os.path.join(depot, *DECALS.split("/")))


# --------------------------------------------------------------- editing
def add(d: Decals, *, category: bytes, name: bytes, glyph: bytes = b"",
        page: bytes = b"", three=(0, 0, 0), extra: bytes = b"0",
        tail: bytes = b"\x00\x00\x00\x00\x01\x00\x00\x00\x01\x01\x01\x01",
        decal_id: int = 0) -> Decal:
    """Append one record.  Refuses anything the file cannot hold."""
    if not category or not name:
        raise DecalError("a decal needs a category and a name")
    if not glyph and not page:
        raise DecalError("a decal needs either a glyph or a picture page")
    if glyph and page:
        raise DecalError("a decal draws a glyph or a page, not both")
    if glyph:
        probe = Decal(0, category, name, glyph, page, three, extra, tail)
        if probe.code_point is None:
            raise DecalError(f"{glyph!r} is neither '0xNNNN' nor a single character")
    if page and not page.startswith(b"vehicles/decals/"):
        raise DecalError(f"{page!r} is not a page under vehicles/decals/")
    got = decal_id or d.free_id()
    if got <= 0:
        raise DecalError(f"{got} is not a usable decal id")
    if d.by_id(got) is not None:
        raise DecalError(f"decal {got} already exists")
    if len(tail) != 12:
        raise DecalError("the flag block has to be 12 bytes")
    decal = Decal(got, category, name, glyph, page, tuple(three), extra, tail)
    d.decals.append(decal)
    return decal


def remove(d: Decals, decal_id: int) -> Decal:
    """Drop one record by id."""
    decal = d.by_id(decal_id)
    if decal is None:
        raise DecalError(f"there is no decal {decal_id}")
    d.decals.remove(decal)
    return decal


def code_point_text(code: int) -> bytes:
    """How the shipped file writes a code point.

    The list uses two spellings and both are live: 148 records write
    ``b"0x0029"`` and 81 write the character itself (``b"0"``, ``b"A"``).  A
    printable ASCII code point is written as the character - that is what the
    shipped digits and letters do, and it keeps the file's own habit rather than
    introducing a third style - and everything else as ``0xNNNN``.
    """
    code = int(code)
    if not 0 <= code <= 0x10FFFF:
        raise DecalError(f"U+{code:04X} is not a code point")
    if 0x20 <= code < 0x7F:
        return bytes((code,))
    width = 4 if code <= 0xFFFF else 6
    return b"0x" + f"{code:0{width}X}".encode("ascii")


def set_record(d: Decals, decal_id: int, *, category=None, name=None,
               code_point=None, glyph=None, page=None, three=None, extra=None,
               tail=None) -> Decal:
    """Change the fields of one record in place, leaving the rest alone.

    ``None`` means "leave it as it is", so a caller that only wants to rename a
    record does not have to know its glyph.  ``page`` and ``code_point`` are
    mutually exclusive, as they are in the file: giving one clears the other.

    ``glyph`` sets the raw bytes of the glyph field instead of a code point,
    which is the only way to put back a spelling exactly as it was - the shipped
    list writes the same character two ways and neither is canonical.
    """
    decal = d.by_id(decal_id)
    if decal is None:
        raise DecalError(f"there is no decal {decal_id}")
    if category is not None:
        if not category:
            raise DecalError("a decal needs a category")
        decal.category = category
    if name is not None:
        if not name:
            raise DecalError("a decal needs a name")
        decal.name = name
    if glyph is not None:
        if glyph and Decal(0, b"x", b"y", glyph, b"", (0, 0, 0), b"0",
                           b"\x00" * 12).code_point is None:
            raise DecalError(f"{glyph!r} is neither '0xNNNN' nor a single "
                             f"character")
        decal.glyph = glyph
        decal.page = b""
    elif code_point is not None:
        if not 0 <= int(code_point) <= 0x10FFFF:
            raise DecalError(f"U+{int(code_point):04X} is not a code point")
        # Keep the record's own spelling when the code point has not moved:
        # 148 records write b"0x0029" and 81 write b")" for the same thing, and
        # rewriting the spelling would change bytes the caller never asked about.
        if decal.code_point != int(code_point):
            decal.glyph = code_point_text(code_point)
        decal.page = b""
    if page is not None:
        if page and not page.startswith(b"vehicles/decals/"):
            raise DecalError(f"{page!r} is not a page under vehicles/decals/")
        decal.page = page
        decal.glyph = b""
    if three is not None:
        decal.three = tuple(three)
    if extra is not None:
        decal.extra = extra
    if tail is not None:
        if len(tail) != 12:
            raise DecalError("the flag block has to be 12 bytes")
        decal.tail = tail
    if not decal.glyph and not decal.page:
        raise DecalError("a decal draws a glyph or a page, and this one would "
                         "draw neither")
    return decal


def move(d: Decals, decal_id: int, position: int) -> Decal:
    """Move a record to another place in the list.

    The order is the order the vinyl editor shows the shapes in, so moving a
    record is how a group is rearranged.  ``position`` is clamped into range.
    """
    decal = d.by_id(decal_id)
    if decal is None:
        raise DecalError(f"there is no decal {decal_id}")
    d.decals.remove(decal)
    at = max(0, min(int(position), len(d.decals)))
    d.decals.insert(at, decal)
    return decal


# --------------------------------------------------------------- self test
def selftest(depot: str) -> list:
    """Check the round trip and the shape of the shipped file."""
    out = []

    def check(name, ok, detail=""):
        out.append((name, bool(ok), detail))

    d = load(depot)
    check("the list reads", len(d) > 0, f"{len(d)} decals")
    check("it round trips", serialize(d) == nct.read(
        __import__("os").path.join(depot, *DECALS.split("/"))), "bytes differ")
    check("every record has a glyph or a page",
          all(bool(x.glyph) ^ bool(x.page) for x in d.decals),
          f"{sum(1 for x in d.decals if not (x.glyph or x.page))} with neither")
    check("the ids are unique", len({x.id for x in d.decals}) == len(d),
          "duplicate id")
    check("the code points parse",
          all(x.code_point is not None for x in d.decals if x.glyph),
          "an unparsable glyph")
    return out
