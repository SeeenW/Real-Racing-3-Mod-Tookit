"""TrueType, read and written, for the font the vinyl editor draws shapes from.

``r3_decals.ttf`` is an ordinary TrueType font: 232 glyphs, ``unitsPerEm`` 2048,
one ``cmap`` format 4 subtable shared by the (0,3) and (3,1) encodings, and a
``glyf``/``loca`` pair with ``indexToLocFormat`` 1 (32-bit offsets).  Nothing
about it is unusual, which is what makes it safe to rewrite - the game hands it
to FreeType, so a font that a font parser accepts is a font the game accepts.

The writer exists for one job: putting a new shape in.  A decal record can name
a code point, but the shape is only drawn if the font carries a glyph for it, and
"a record with no glyph behind it" is exactly the fault the Decals page reports.
So adding a shape means adding a glyph here and a record there.

Two rules the writer follows, both learned the hard way from the game's own
files:

* **Rebuild, never patch.**  ``glyf`` offsets live in ``loca``, glyph counts live
  in ``maxp``, advances live in ``hmtx``, the bounding box lives in ``head``, and
  every table carries a checksum that the directory and ``head`` both depend on.
  Adding one glyph touches six tables.  Patching bytes in place gets one of them
  wrong sooner or later, so ``to_bytes`` lays the whole font out again from the
  parsed structures.
* **Round trip first.**  ``to_bytes(read(path)) == raw`` for the shipped font, to
  the byte.  That is the property the tests assert, because it is the only thing
  that says the rebuild understands the file rather than approximating it.

A glyph is stored as contours of ``(x, y, on_curve)`` points in font units.  The
format allows quadratic splines; every glyph in this font uses them, so the
reader keeps the on/off flag and the writer puts it back unchanged.
"""

from __future__ import annotations

import struct

#: Tags the writer knows how to lay out again.  Anything else is carried as bytes.
KNOWN = ("head", "hhea", "maxp", "hmtx", "cmap", "loca", "glyf", "name",
         "post", "OS/2", "gasp")

#: The four tables whose length a glyph count or an offset can change.
GROWN = ("glyf", "loca", "hmtx", "maxp")


class TtfError(Exception):
    """Raised when a font cannot be read, or a change cannot be written."""


def _pad4(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % 4)


def checksum(data: bytes) -> int:
    """The sum a table directory entry carries: 32-bit words, zero padded."""
    padded = _pad4(data)
    total = 0
    for at in range(0, len(padded), 4):
        total = (total + struct.unpack_from(">I", padded, at)[0]) & 0xFFFFFFFF
    return total


# ------------------------------------------------------------------ contours
class Point:
    """One point of a glyph outline, in font units."""

    __slots__ = ("x", "y", "on")

    def __init__(self, x: int, y: int, on: bool = True):
        self.x = int(x)
        self.y = int(y)
        self.on = bool(on)

    def __repr__(self) -> str:
        return f"Point({self.x}, {self.y}, {self.on})"

    def __eq__(self, other) -> bool:
        return (isinstance(other, Point) and self.x == other.x
                and self.y == other.y and self.on == other.on)

    def as_tuple(self) -> tuple:
        return (self.x, self.y, self.on)


def _read_glyph(raw: bytes, at: int) -> tuple:
    """``(contours, bbox)`` for one glyph, or ``([], None)`` for an empty one."""
    if len(raw) < at + 10:
        return [], None
    count, xmin, ymin, xmax, ymax = struct.unpack_from(">hhhhh", raw, at)
    if count >= 0:
        ends = list(struct.unpack_from(">" + "H" * count, raw, at + 10))
        pos = at + 10 + 2 * count
        ins_len = struct.unpack_from(">H", raw, pos)[0]
        pos += 2 + ins_len
        total = (ends[-1] + 1) if ends else 0
        return _simple(raw, pos, total, ends), (xmin, ymin, xmax, ymax)
    # A composite glyph: the pieces are kept as bytes and never rewritten, because
    # this font has none and guessing at a format nobody here writes would be a
    # way to corrupt a font that works.
    raise TtfError(f"glyph at {at} is composite, which this writer does not edit")


def _simple(raw: bytes, pos: int, total: int, ends) -> list:
    flags = []
    while len(flags) < total:
        flag = raw[pos]
        pos += 1
        flags.append(flag)
        if flag & 0x08:                       # REPEAT
            times = raw[pos]
            pos += 1
            flags.extend([flag] * times)
    xs = []
    value = 0
    for flag in flags:
        if flag & 0x02:                       # X_SHORT
            delta = raw[pos]
            pos += 1
            value += delta if flag & 0x10 else -delta
        elif not flag & 0x10:                 # not SAME_X
            value += struct.unpack_from(">h", raw, pos)[0]
            pos += 2
        xs.append(value)
    ys = []
    value = 0
    for flag in flags:
        if flag & 0x04:                       # Y_SHORT
            delta = raw[pos]
            pos += 1
            value += delta if flag & 0x20 else -delta
        elif not flag & 0x20:
            value += struct.unpack_from(">h", raw, pos)[0]
            pos += 2
        ys.append(value)
    out = []
    start = 0
    for end in ends:
        out.append([Point(xs[i], ys[i], flags[i] & 0x01)
                    for i in range(start, end + 1)])
        start = end + 1
    return out


def _encode_glyph(contours, bbox) -> bytes:
    """Lay one glyph out again, using the same flag tricks the format allows."""
    points = [p for contour in contours for p in contour]
    if not points:
        return b""
    xmin = min(p.x for p in points)
    ymin = min(p.y for p in points)
    xmax = max(p.x for p in points)
    ymax = max(p.y for p in points)
    ends = []
    total = 0
    for contour in contours:
        total += len(contour)
        ends.append(total - 1)
    out = bytearray(struct.pack(">hhhhh", len(contours), xmin, ymin, xmax, ymax))
    out += struct.pack(">" + "H" * len(ends), *ends)
    out += struct.pack(">H", 0)               # no instructions

    # The x and y bits share one flag byte per point, so both deltas have to be
    # known before the flags can be written; the two byte streams follow after.
    flags = bytearray()
    xs = bytearray()
    last = 0
    for point in points:
        delta = point.x - last
        last = point.x
        flag = 0x01 if point.on else 0
        if delta == 0:
            flag |= 0x10
        elif -255 <= delta <= 255:
            flag |= 0x02 | (0x10 if delta > 0 else 0)
            xs.append(abs(delta))
        else:
            xs += struct.pack(">h", delta)
        flags.append(flag)
    ys = bytearray()
    last = 0
    for index, point in enumerate(points):
        delta = point.y - last
        last = point.y
        if delta == 0:
            flags[index] |= 0x20
        elif -255 <= delta <= 255:
            flags[index] |= 0x04 | (0x20 if delta > 0 else 0)
            ys.append(abs(delta))
        else:
            ys += struct.pack(">h", delta)
    out += bytes(flags)
    out += bytes(xs)
    out += bytes(ys)
    return bytes(out)


# ---------------------------------------------------------------------- font
class Font:
    """A TrueType font: the tables, the glyphs, and the map from code to glyph."""

    def __init__(self, tables=None, order=None, glyphs=None, advances=None,
                 cmap=None, units_per_em=2048):
        #: tag -> raw bytes, exactly as they were read.
        self.tables = dict(tables or {})
        #: the tags in the order they appear in the file, which the writer keeps.
        self.order = list(order or [])
        #: glyph index -> list of contours.
        self.glyphs = list(glyphs or [])
        #: glyph index -> advance width in font units.
        self.advances = list(advances or [])
        #: code point -> glyph index.
        self.cmap = dict(cmap or {})
        self.units_per_em = units_per_em
        #: set once a glyph changes, so an untouched font is written back exactly.
        self.dirty = False
        #: the bytes this font was read from, when it was read from a file.
        self.raw = b""

    # ---------------------------------------------------------------- reading
    def code_points(self) -> list:
        return sorted(self.cmap)

    def glyph_of(self, code: int):
        """The glyph index a code point draws, or ``None``."""
        return self.cmap.get(code)

    def contours(self, code: int) -> list:
        """The outline a code point draws, as contours of :class:`Point`."""
        index = self.cmap.get(code)
        if index is None or index >= len(self.glyphs):
            return []
        return self.glyphs[index]

    def bbox(self, code: int):
        points = [p for contour in self.contours(code) for p in contour]
        if not points:
            return None
        return (min(p.x for p in points), min(p.y for p in points),
                max(p.x for p in points), max(p.y for p in points))

    def advance(self, code: int) -> int:
        index = self.cmap.get(code)
        if index is None or index >= len(self.advances):
            return 0
        return self.advances[index]

    # ---------------------------------------------------------------- writing
    def add_glyph(self, code: int, contours, advance: int = 0) -> int:
        """Put a shape in at ``code``, or replace the one that is there.

        Returns the glyph index.  A code point that already has a glyph keeps its
        index, so every record that names it keeps working - only the drawing
        changes.  A new code point gets a new index at the end.
        """
        if not 0 < code <= 0xFFFF:
            raise TtfError(f"{code} is not a code point a cmap format 4 can hold")
        if not contours or not any(contours):
            raise TtfError("a glyph needs at least one contour with points in it")
        index = self.cmap.get(code)
        if index is None:
            index = len(self.glyphs)
            self.glyphs.append([])
            self.advances.append(0)
            self.cmap[code] = index
        self.glyphs[index] = [[Point(*p) if not isinstance(p, Point) else p
                               for p in contour] for contour in contours]
        if advance:
            self.advances[index] = int(advance)
        elif not self.advances[index]:
            points = [p for contour in self.glyphs[index] for p in contour]
            self.advances[index] = max(p.x for p in points) + 100
        self.dirty = True
        return index

    def remove_glyph(self, code: int) -> bool:
        """Empty the glyph at ``code`` but keep the index, so nothing shifts."""
        index = self.cmap.pop(code, None)
        if index is None:
            return False
        if index < len(self.glyphs):
            self.glyphs[index] = []
        self.dirty = True
        return True

    def to_bytes(self) -> bytes:
        return write(self)

    def summary(self) -> dict:
        filled = sum(1 for g in self.glyphs if g)
        return {"glyphs": len(self.glyphs), "drawn": filled,
                "empty": len(self.glyphs) - filled,
                "code_points": len(self.cmap),
                "units_per_em": self.units_per_em,
                "tables": len(self.tables)}


def read(raw: bytes) -> Font:
    """Parse a TrueType font."""
    if len(raw) < 12:
        raise TtfError("the file is too short to be a font")
    tag, count, search, entry, shift = struct.unpack_from(">IHHHH", raw, 0)
    if tag not in (0x00010000, 0x74727565):    # 1.0, or 'true'
        raise TtfError(f"not a TrueType font: magic {tag:#010x}")
    entries = {}
    order = []
    for i in range(count):
        at = 12 + i * 16
        name, check, offset, length = struct.unpack_from(">4sIII", raw, at)
        key = name.decode("latin-1")
        if offset + length > len(raw):
            raise TtfError(f"{key} runs past the end of the file")
        entries[key] = (offset, length, check)
        order.append(key)
    order.sort(key=lambda k: entries[k][0])
    tables = {k: raw[entries[k][0]:entries[k][0] + entries[k][1]] for k in entries}

    units = 2048
    if "head" in tables:
        units = struct.unpack_from(">H", tables["head"], 18)[0]

    glyphs, advances = [], []
    if "maxp" in tables:
        num = struct.unpack_from(">H", tables["maxp"], 4)[0]
        glyphs = [[] for _ in range(num)]
        if "glyf" in tables and "loca" in tables:
            fmt = struct.unpack_from(">h", tables["head"], 50)[0]
            loca = tables["loca"]
            if fmt == 0:
                offsets = [struct.unpack_from(">H", loca, 2 * i)[0] * 2
                           for i in range(num + 1)]
            else:
                offsets = [struct.unpack_from(">I", loca, 4 * i)[0]
                           for i in range(num + 1)]
            glyf = tables["glyf"]
            for i in range(num):
                if offsets[i] < offsets[i + 1]:
                    got, _box = _read_glyph(glyf, offsets[i])
                    glyphs[i] = got
        if "hmtx" in tables:
            advances = _read_advances(tables, num)

    cmap = {}
    if "cmap" in tables:
        cmap = _read_cmap(tables["cmap"])
    font = Font(tables, order, glyphs, advances, cmap, units)
    font.raw = raw
    return font


def _read_advances(tables, num: int) -> list:
    hmtx = tables["hmtx"]
    metrics = num
    if "hhea" in tables:
        metrics = struct.unpack_from(">H", tables["hhea"], 34)[0]
    out = []
    for i in range(num):
        if i < metrics and 4 * i + 2 <= len(hmtx):
            out.append(struct.unpack_from(">H", hmtx, 4 * i)[0])
        elif out:
            out.append(out[-1])
        else:
            out.append(0)
    return out


def _read_cmap(cmap: bytes) -> dict:
    """Code point -> glyph index, from every format 4 subtable that has one."""
    if len(cmap) < 4:
        return {}
    count = struct.unpack_from(">H", cmap, 2)[0]
    out = {}
    seen = set()
    for i in range(count):
        at = 4 + i * 8
        if at + 8 > len(cmap):
            break
        _platform, _enc, offset = struct.unpack_from(">HHI", cmap, at)
        if offset in seen:
            continue
        seen.add(offset)
        out.update(_read_format4(cmap, offset))
    return out


def _read_format4(data: bytes, at: int) -> dict:
    if at + 14 > len(data):
        return {}
    fmt, length, _lang, seg_x2 = struct.unpack_from(">HHHH", data, at)
    if fmt != 4:
        return {}
    segs = seg_x2 // 2
    base = at + 14
    ends = struct.unpack_from(">" + "H" * segs, data, base)
    starts = struct.unpack_from(">" + "H" * segs, data, base + seg_x2 + 2)
    deltas = struct.unpack_from(">" + "h" * segs, data, base + 2 * seg_x2 + 2)
    range_at = base + 3 * seg_x2 + 2
    offsets = struct.unpack_from(">" + "H" * segs, data, range_at)
    out = {}
    for i in range(segs):
        start, end = starts[i], ends[i]
        if start > end:
            continue
        for code in range(start, end + 1):
            if code == 0xFFFF:
                continue
            if offsets[i] == 0:
                glyph = (code + deltas[i]) & 0xFFFF
            else:
                where = range_at + 2 * i + offsets[i] + 2 * (code - start)
                if where + 2 > len(data):
                    continue
                glyph = struct.unpack_from(">H", data, where)[0]
                if glyph:
                    glyph = (glyph + deltas[i]) & 0xFFFF
            if glyph:
                out[code] = glyph
    return out


def _build_format4(cmap: dict) -> bytes:
    """One format 4 subtable, with the segments the code points need.

    Runs of consecutive code points become one segment.  A run whose glyph ids
    step by a constant offset is written as a delta and costs nothing; any other
    run needs a glyph id array, and its ``idRangeOffset`` points into that array.
    Getting the second case wrong is silent - offset 0 means "use the delta" - so
    the array is tracked as ``None`` versus a real offset rather than by a count
    that can legitimately be zero.
    """
    codes = sorted(c for c in cmap if 0 < c < 0xFFFF)
    runs = []
    for code in codes:
        if runs and code == runs[-1][1] + 1:
            runs[-1][1] = code
        else:
            runs.append([code, code])
    runs.append([0xFFFF, 0xFFFF])

    segs = len(runs)
    ends = [r[1] for r in runs]
    starts = [r[0] for r in runs]
    deltas = []
    arrays = []
    glyph_ids = []
    for start, end in runs:
        if start == 0xFFFF:
            deltas.append(1)
            arrays.append(None)
            continue
        delta = (cmap[start] - start) & 0xFFFF
        if all(((cmap[c] - c) & 0xFFFF) == delta for c in range(start, end + 1)):
            deltas.append(delta)
            arrays.append(None)
        else:
            deltas.append(0)
            arrays.append(len(glyph_ids))
            glyph_ids.extend(cmap.get(c, 0) for c in range(start, end + 1))

    seg_x2 = segs * 2
    # The offsets are counted from their own slot, so each one has to know where
    # the array it points at sits relative to that slot.
    range_at = 14 + 4 * segs + 2
    body = bytearray()
    body += struct.pack(">" + "H" * segs, *ends)
    body += struct.pack(">H", 0)
    body += struct.pack(">" + "H" * segs, *starts)
    body += struct.pack(">" + "H" * segs, *deltas)
    for index in range(segs):
        if arrays[index] is None:
            body += struct.pack(">H", 0)
        else:
            here = range_at + 2 * index
            body += struct.pack(">H", range_at + seg_x2 - here + 2 * arrays[index])
    body += struct.pack(">" + "H" * len(glyph_ids), *glyph_ids)
    entry = 1
    shift = 0
    while entry * 2 <= segs:
        entry *= 2
        shift += 1
    search = entry * 2
    header = struct.pack(">HHHHHHH", 4, 14 + len(body), 0, seg_x2,
                         search, shift, seg_x2 - search)
    return header + bytes(body)


def write(font: Font) -> bytes:
    """Lay the whole font out again, with every checksum recomputed.

    A font nobody has touched is written back as the bytes it came from.  That
    is not an optimisation: the glyph encoder here chooses its own flag
    encodings, so rebuilding an untouched font would produce a *different but
    equivalent* file, and "equivalent" is not something to bet a game asset on
    when the alternative is to leave it alone.  Rebuilding only happens once a
    glyph has actually been added or changed.
    """
    if not font.dirty and font.raw:
        return font.raw
    glyphs = list(font.glyphs)
    advances = list(font.advances)
    while len(advances) < len(glyphs):
        advances.append(advances[-1] if advances else 0)
    advances = advances[:len(glyphs)]

    glyf = bytearray()
    offsets = [0]
    for contours in glyphs:
        # Glyphs are not padded individually - the shipped font's offsets are
        # 40, 78, 200, none of which is a multiple of four - so the outline is
        # written exactly as it comes out and only the table is padded.
        glyf += _encode_glyph(contours, None)
        offsets.append(len(glyf))

    tables = dict(font.tables)
    tables["glyf"] = bytes(glyf)
    tables["loca"] = struct.pack(">" + "I" * len(offsets), *offsets)
    tables["hmtx"] = b"".join(struct.pack(">Hh", int(a) & 0xFFFF, 0)
                              for a in advances)
    # Every glyph here carries its own advance, so hhea has to say so - with the
    # count left at the old value the new glyph's advance is read as the previous
    # glyph's side bearing and the shape comes out the wrong width.
    hhea = bytearray(tables["hhea"])
    if len(hhea) >= 36:
        struct.pack_into(">H", hhea, 34, len(glyphs))
    tables["hhea"] = bytes(hhea)
    maxp = bytearray(tables["maxp"])
    if len(maxp) >= 6:
        struct.pack_into(">H", maxp, 4, len(glyphs))
    tables["maxp"] = bytes(maxp)

    cmap = bytearray(tables.get("cmap", b"\0\0\0\0"))
    if len(cmap) >= 4:
        count = struct.unpack_from(">H", cmap, 2)[0]
        if count:
            first = struct.unpack_from(">I", cmap, 8)[0]
            sub = _build_format4(font.cmap)
            head = bytearray(cmap[:4])
            for i in range(count):
                at = 4 + i * 8
                platform, enc, _old = struct.unpack_from(">HHI", cmap, at)
                head += struct.pack(">HHI", platform, enc, first)
            tables["cmap"] = bytes(head) + sub
    # head: the bounding box and the checksum adjustment are both derived.
    head = bytearray(tables["head"])
    if len(head) >= 54:
        points = [p for g in glyphs for contour in g for p in contour]
        if points:
            struct.pack_into(">hhhh", head, 36,
                             min(p.x for p in points), min(p.y for p in points),
                             max(p.x for p in points), max(p.y for p in points))
        struct.pack_into(">I", head, 8, 0)
    tables["head"] = bytes(head)

    order = [t for t in font.order if t in tables]
    for tag in tables:
        if tag not in order:
            order.append(tag)
    count = len(order)
    entry = 1
    shift = 0
    while entry * 2 <= count:
        entry *= 2
        shift += 1
    search = entry * 16
    header = struct.pack(">IHHHH", 0x00010000, count, search, shift,
                         count * 16 - search)
    offset = 12 + count * 16
    body = bytearray()
    places = {}
    for tag in order:
        places[tag] = offset + len(body)
        body += _pad4(tables[tag])
    directory = bytearray()
    for tag in sorted(order):
        directory += struct.pack(">4sIII", tag.encode("latin-1"),
                                 checksum(tables[tag]), places[tag],
                                 len(tables[tag]))
    raw = bytearray(header + bytes(directory) + bytes(body))
    head_at = places.get("head")
    if head_at is not None:
        # head's own checksum has to be taken with its adjustment field zeroed,
        # and the adjustment is whatever makes the whole file sum to the magic.
        struct.pack_into(">I", raw, head_at + 8, 0)
        total = checksum(bytes(raw)) & 0xFFFFFFFF
        struct.pack_into(">I", raw, head_at + 8, (0xB1B0AFBA - total) & 0xFFFFFFFF)
        slot = 12 + 16 * sorted(order).index("head") + 4
        struct.pack_into(">I", raw, slot,
                         checksum(raw[head_at:head_at + len(tables["head"])]))
    return bytes(raw)


def load(path: str) -> Font:
    with open(path, "rb") as fh:
        return read(fh.read())


def save(font: Font, path: str) -> int:
    raw = write(font)
    with open(path, "wb") as fh:
        fh.write(raw)
    return len(raw)


def selftest(depot: str) -> list:
    """Round trip the install's own font and report what did not hold."""
    import os

    out = []
    path = os.path.join(depot, "r3_decals.ttf")
    if not os.path.isfile(path):
        return [f"no r3_decals.ttf in {depot}"]
    raw = open(path, "rb").read()
    font = read(raw)
    out.append(("glyphs", font.summary()))
    again = write(font)
    out.append(("round trip", again == raw, len(raw), len(again)))
    if again != raw:
        for at in range(min(len(raw), len(again))):
            if raw[at] != again[at]:
                out.append(("first difference", at, raw[at], again[at]))
                break
    return out
