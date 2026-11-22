"""``carappearances.appearances.nct``: wheel sizes, gearing and exhaust per car.

This table is the one that decides how big the wheels are drawn, and it is
indexed separately from the car list: a car's spec file points at one record
here, and the record's **name** is the asset folder name the engine then loads
(``vehicles/<name>/<name>_a.m3g``).  So adding a car means adding a record here
as well as a spec.

LAYOUT
------
::

    u32 magic = 23
    u32 count
    per record:
        u32  id          (0 .. 563, strictly increasing, 24 is missing)
        u32  nameLen
        char name[]      asset folder name, e.g. "2012_lexus_lfa"
        block            variable length, 234 .. 327 bytes

The block is self describing but only partly understood.  Rather than risk
breaking a field nobody has mapped, this module copies a donor block verbatim
and only rewrites what is known:

+0   8 x f32  wheel sizes, front (f0..f3) then rear (f4..f7).
     **f1 and f5 are the loaded tyre radius** - verified against
     ``suspensiondata`` (free radius minus 1.7 cm of tyre deflection) for 188
     cars.  f0/f4 look like rim radius, f3/f7 like tyre width, f2/f6 unknown.
+32  u32     25000 / 29000
+36  u32     1 (433 cars) / 0 (107)
+40  u16     256 (537 cars)
+74  u32     400 / 50 / 0 / 100
+78  str     "m:ss.f"  (gear ratio display format)
+88  u32 n; n x str  gear labels ("R", "N", "1".."8")
    3 x u32 flags; when the third is 1 a fixed 32 byte block follows
    str "ABCDEFGH", str "AB"
    str exhaust effect name  ("exhaust_race", "exhaust_road", ...)
    str exhaust texture path
    46 byte tail: +4 is the paint colour (0x00FFFFFF white, 0x00A7FAFF pale
    blue), +26 a u16 (95 for open wheel cars, 79 otherwise), +38 always 2,
    +42 2 or 1
"""

from __future__ import annotations

import os
import struct

from . import nct

#: Path relative to the depot root.
APPEARANCES = "vehicles/data/carappearances.appearances.nct"
MAGIC = 23
TAIL_LEN = 46
GEAR_CHARS = set(b"RN0123456789")

#: The 32 byte constant block that follows the flags when their third word is 1.
BLOB_CONST = bytes.fromhex(
    "3333534000c05a450000284200000000000060c1000040420000cc4285eb513f")


class AppearanceError(Exception):
    pass


class Record:
    """One car's appearance record."""

    __slots__ = ("id", "name", "block")

    def __init__(self, rid: int, name: bytes, block: bytes):
        self.id = rid
        self.name = name
        self.block = block

    @property
    def size(self) -> int:
        return 8 + len(self.name) + len(self.block)

    def clone(self, *, new_id: int | None = None,
              new_name: bytes | None = None) -> "Record":
        return Record(self.id if new_id is None else new_id,
                      self.name if new_name is None else new_name,
                      self.block)

    # ---- the fields we do understand -----------------------------------
    def wheel_sizes(self) -> tuple[float, ...]:
        return struct.unpack_from("<8f", self.block, 0)

    def set_wheel_sizes(self, values) -> None:
        if len(values) != 8:
            raise AppearanceError("wheel_sizes takes exactly 8 floats")
        b = bytearray(self.block)
        struct.pack_into("<8f", b, 0, *[float(v) for v in values])
        self.block = bytes(b)

    def tyre_radius(self) -> tuple[float, float]:
        """Loaded tyre radius, front and rear (the values that matter)."""
        v = self.wheel_sizes()
        return v[1], v[5]

    def set_tyre_radius(self, front: float | None = None,
                        rear: float | None = None) -> None:
        v = list(self.wheel_sizes())
        if front is not None:
            v[1] = float(front)
        if rear is not None:
            v[5] = float(rear)
        self.set_wheel_sizes(v)

    def paint_colour(self) -> bytes:
        return self.block[len(self.block) - TAIL_LEN + 4:
                        len(self.block) - TAIL_LEN + 8]

    def set_paint_colour(self, rgb: bytes) -> None:
        if len(rgb) != 4:
            raise AppearanceError("paint colour must be 4 bytes (BGRA/ARGB word)")
        at = len(self.block) - TAIL_LEN + 4
        b = bytearray(self.block)
        b[at:at + 4] = rgb
        self.block = bytes(b)


# ------------------------------------------------------------------ parsing
def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _read_str(block: bytes, p: int, limit: int = 200) -> tuple[bytes, int]:
    if p + 4 > len(block):
        raise AppearanceError(f"string length out of bounds at +{p}")
    n = _u32(block, p)
    if n > limit:
        raise AppearanceError(f"implausible string length at +{p}: {n}")
    q = p + 4 + n
    if q > len(block):
        raise AppearanceError(f"string out of bounds at +{p} (len {n})")
    return block[p + 4:q], q


def block_len(block: bytes, strict: bool = True) -> int:
    """Walk one appearance block and return its byte length."""
    if len(block) < 88:
        raise AppearanceError(f"block too short: {len(block)}")
    p = 78
    s, p = _read_str(block, p, 32)
    if strict and s != b"m:ss.f":
        raise AppearanceError(f"expected 'm:ss.f' at +78, got {s!r}")
    n = _u32(block, p)
    p += 4
    if strict and n > 32:
        raise AppearanceError(f"implausible gear count: {n}")
    for _ in range(n):
        g, p = _read_str(block, p, 8)
        if strict and (not g or any(c not in GEAR_CHARS for c in g)):
            raise AppearanceError(f"bad gear label: {g!r}")
    if p + 12 > len(block):
        raise AppearanceError("flags out of bounds")
    a1, a2, a3 = _u32(block, p), _u32(block, p + 4), _u32(block, p + 8)
    p += 12
    if strict and (a1 > 4 or a2 > 8 or a3 > 1):
        raise AppearanceError(f"bad flags: {a1},{a2},{a3}")
    if a3 == 1:
        blob = block[p:p + 32]
        if strict and blob != BLOB_CONST:
            raise AppearanceError(f"constant block differs at +{p}: {blob.hex()}")
        p += 32
    s, p = _read_str(block, p, 16)
    if strict and s != b"ABCDEFGH":
        raise AppearanceError(f"expected 'ABCDEFGH', got {s!r}")
    s, p = _read_str(block, p, 8)
    if strict and s != b"AB":
        raise AppearanceError(f"expected 'AB', got {s!r}")
    s, p = _read_str(block, p, 64)
    if strict and not s.startswith(b"exhaust_"):
        raise AppearanceError(f"bad exhaust effect name: {s!r}")
    s, p = _read_str(block, p, 96)
    if strict and not (s.startswith(b"effects/exhaust_flame/")
                       and s.endswith(b".pvr")):
        raise AppearanceError(f"bad exhaust texture path: {s!r}")
    p += TAIL_LEN
    if p > len(block):
        raise AppearanceError(f"tail out of bounds: {p} > {len(block)}")
    return p


def parse(data: bytes, strict: bool = True) -> tuple[int, list[Record]]:
    """Parse a whole file; every byte must be accounted for."""
    if len(data) < 8:
        raise AppearanceError("file too short")
    magic, count = struct.unpack_from("<2I", data, 0)
    if strict and magic != MAGIC:
        raise AppearanceError(f"magic should be {MAGIC}, got {magic}")
    recs: list[Record] = []
    pos = 8
    prev = -1
    for i in range(count):
        if pos + 8 > len(data):
            raise AppearanceError(f"record {i} header out of bounds @{pos}")
        rid, nlen = struct.unpack_from("<2I", data, pos)
        if nlen == 0 or nlen > 64:
            raise AppearanceError(f"record {i} nameLen {nlen} @{pos}")
        nend = pos + 8 + nlen
        if nend > len(data):
            raise AppearanceError(f"record {i} name out of bounds @{pos}")
        name = data[pos + 8:nend]
        if strict:
            if rid <= prev:
                raise AppearanceError(
                    f"record {i} id not increasing: {prev} -> {rid} @{pos}")
            if not (name[0:4].isdigit() and 1950 <= int(name[0:4]) <= 2035):
                raise AppearanceError(f"record {i} name looks wrong: {name!r}")
            if any(c in b" \x00\r\n\t" for c in name):
                raise AppearanceError(f"record {i} name has whitespace: {name!r}")
        prev = rid
        blen = block_len(data[nend:], strict)
        recs.append(Record(rid, name, data[nend:nend + blen]))
        pos = nend + blen
    if strict and pos != len(data):
        raise AppearanceError(
            f"stopped at {pos} of {len(data)} ({len(data) - pos} trailing bytes)")
    return count, recs


def build(count: int, recs: list[Record], magic: int = MAGIC) -> bytes:
    out = bytearray(struct.pack("<2I", magic, count))
    for r in recs:
        out += struct.pack("<2I", r.id, len(r.name))
        out += r.name
        out += r.block
    return bytes(out)


# ------------------------------------------------------------------ editing
def find(recs: list[Record], key) -> int:
    """Index of the record with this id or name."""
    if isinstance(key, int):
        for i, r in enumerate(recs):
            if r.id == key:
                return i
        raise AppearanceError(f"no appearance record with id {key}")
    kb = key.encode("ascii") if isinstance(key, str) else key
    hits = [i for i, r in enumerate(recs) if r.name == kb]
    if not hits:
        raise AppearanceError(f"no appearance record named {kb!r}")
    if len(hits) > 1:
        raise AppearanceError(f"{len(hits)} records named {kb!r}")
    return hits[0]


def insert(recs: list[Record], rec: Record) -> int:
    """Insert keeping ids sorted; refuses a duplicate id."""
    lo, hi = 0, len(recs)
    while lo < hi:
        mid = (lo + hi) // 2
        if recs[mid].id < rec.id:
            lo = mid + 1
        else:
            hi = mid
    if lo < len(recs) and recs[lo].id == rec.id:
        raise AppearanceError(f"id {rec.id} already exists (index {lo})")
    recs.insert(lo, rec)
    return lo


def remove(recs: list[Record], rid: int) -> int:
    i = find(recs, rid)
    recs.pop(i)
    return i


def free_id(recs: list[Record], after: int | None = None) -> int:
    """The next unused id, by default one past the highest."""
    used = {r.id for r in recs}
    cand = (max(used) + 1) if after is None else after
    while cand in used:
        cand += 1
    return cand


def add_record(recs: list[Record], donor: int | str, *,
               new_id: int | None = None,
               new_name: str | bytes | None = None,
               tyre_radius: tuple[float, float] | None = None) -> Record:
    """Clone ``donor`` into a new record and insert it."""
    d = recs[find(recs, donor)]
    name = d.name if new_name is None else (
        new_name.encode("ascii") if isinstance(new_name, str) else new_name)
    if not name or any(c < 32 or c > 126 for c in name):
        raise AppearanceError("record name must be printable ASCII")
    rec = d.clone(new_id=free_id(recs) if new_id is None else new_id,
                  new_name=name)
    if tyre_radius:
        rec.set_tyre_radius(*tyre_radius)
    insert(recs, rec)
    return rec


# ------------------------------------------------------------------ file IO
def load(depot_or_path: str, *, is_depot: bool = True):
    """Read the table from a depot root (or from an explicit file path)."""
    path = (os.path.join(depot_or_path, *APPEARANCES.split("/"))
            if is_depot else depot_or_path)
    return parse(nct.read(path))


def save(count: int, recs: list[Record], path: str) -> int:
    blob = build(count, recs)
    nct.write(path, blob)
    return len(blob)


# ------------------------------------------------------------------ selftest
def selftest(depot: str | None = None) -> int:
    depot = depot or os.environ.get("RR3_DEPOT", "")
    if not depot:
        print("appearance selftest: no depot (set RR3_DEPOT)")
        return 2
    path = os.path.join(depot, *APPEARANCES.split("/"))
    plain = nct.read(path)
    count, recs = parse(plain)
    print(f"{count} records, {len(plain)} bytes, ids {recs[0].id}..{recs[-1].id}")
    if build(count, recs) != plain:
        print("FAIL: rebuild differs")
        return 1
    # insert then remove at every position must restore the file exactly
    for k in range(len(recs)):
        work = list(recs)
        victim = work.pop(k)
        back = insert(work, victim)
        if back != k or build(count, work) != plain:
            print(f"FAIL: delete/insert at {k} did not round-trip")
            return 1
    print("every position: delete then re-insert restores the file")
    # clone round-trip
    work = list(recs)
    new = add_record(work, recs[0].id, new_name="2025_test_clone")
    c2, r2 = parse(build(count + 1, work))
    if c2 != count + 1 or r2[find(r2, new.id)].name != b"2025_test_clone":
        print("FAIL: clone did not parse back")
        return 1
    print("clone: ok")
    print("appearance selftest: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
