"""``carupgrade.upgrades.nct``: the upgrade routes, and which one a car follows.

A car does not carry its upgrade tree.  Its spec carries one *key* - a short
ASCII string such as ``PROD_03`` or ``2022_FORMULA_1`` - and this table holds
the block that key names.  Two consequences that matter for the manager:

* reading is cheap and safe: the key is a length-prefixed string in the spec at
  a fixed offset from the gear count (see :func:`route_offset`), and the block is
  found by its name in this table;
* **pointing an existing car at a different route is a one-string edit of the
  spec.**  Nothing in this file has to change, which is why
  :meth:`rr3lib.spec.Spec.set_upgrade_route` is a writer and this module is not.

Layout of the file (RC4-encrypted like every ``.nct``; 603,513 B decrypted)::

    u32       1005              a count, but not of the routes - see below
    u32       5                 curve names follow
    5 x str   FAST SLOW SLOWER LINEAR ANTISLOWER
    ...        a long run of plain u32: per-area step counts, then the price and
               cost tables for each upgrade area.  Nothing here is per-car.
    route blocks, back to back, to the end of the file

A route block is found by shape rather than by an offset table, because the file
has none: the block's name string is immediately followed by a run of at least
three area names that begins with ``Engine``.  That shape is unambiguous - the
327 blocks it finds are exactly the 327 the game uses, and the 459 cars that
name one all resolve.

Inside a block (offsets are from the name)::

    str      the name, e.g. ``PROD_01``
    str[]    the areas this route upgrades, in order (3 to 7 of the seven)
    u32[]    one per area, then
    str[]    one curve name per area (``SLOW``/``FAST``/...)
    u32[]
    str[]    one ``"Top Speed; 100"`` style effect per area
    u32[]
    str[]    one more effect group per area
    ...      then the steps: one name per area for the first level, more per
             level after that, with the cost units (``" L"``, ``" G"``) between
             them

The 1,005 at offset 0 does not count routes (there are 327) and does not count
area records (2,241) or steps (9,148); it is left alone.  Appending a block is
therefore *not* implemented - see ``docs/RRMOD-BACKLOG.md``.
"""

import os
import struct

from . import nct as nctlib

#: The seven upgrade areas, spelled as the file spells them.
AREAS = ("Engine", "Drivetrain", "Body", "Suspension", "Exhaust", "Brakes",
         "Tires & Wheels")

#: The five curves a step can follow, in the order the file lists them.
CURVES = ("FAST", "SLOW", "SLOWER", "LINEAR", "ANTISLOWER")

#: Where the file lives, relative to the depot.
TABLE = "vehicles/data/carupgrade.upgrades.nct"

#: A key longer than this is not a route key; it is a mis-read offset.
MAX_KEY = 48


class UpgradesError(Exception):
    pass


def _depot(root: str) -> str:
    """Accept either an install root or a depot folder."""
    root = os.path.abspath(root)
    if os.path.isdir(os.path.join(root, "vehicles")):
        return root
    return os.path.join(root, ".depot")


def _strings(plain: bytes) -> list:
    """Every ``u32``-length-prefixed printable string, as ``(offset, size, text)``.

    Same shape as :func:`rr3lib.spec.tokenize` uses, but with a wider length cap
    because a step name can run past 200 characters in the odd block.
    """
    out = []
    at = 0
    size = len(plain)
    while at < size - 4:
        length = struct.unpack_from("<I", plain, at)[0]
        if 1 <= length <= 400 and at + 4 + length <= size:
            chunk = plain[at + 4:at + 4 + length]
            if all(32 <= c < 127 for c in chunk):
                out.append((at, length, chunk.decode("ascii")))
                at += 4 + length
                continue
        at += 1
    return out


class Route:
    """One upgrade route: the block a car's key names."""

    __slots__ = ("name", "offset", "length", "areas", "curves", "effects",
                 "steps")

    def __init__(self, name, offset, length, areas, curves, effects, steps):
        self.name = name
        self.offset = offset
        self.length = length
        self.areas = tuple(areas)
        self.curves = tuple(curves)
        self.effects = tuple(effects)
        self.steps = tuple(steps)

    def __repr__(self) -> str:
        return (f"<Route {self.name} {len(self.areas)} areas "
                f"{len(self.steps)} steps {self.length} B>")

    def to_dict(self) -> dict:
        return {"name": self.name, "offset": self.offset, "length": self.length,
                "areas": list(self.areas), "curves": list(self.curves),
                "effects": list(self.effects), "steps": list(self.steps)}


def parse(plain: bytes) -> list:
    """Every route block in ``plain``, in file order."""
    rows = _strings(plain)
    texts = [text for _offset, _length, text in rows]
    starts = []
    for index in range(len(rows) - 1):
        if texts[index + 1] != "Engine":
            continue
        run = 0
        cursor = index + 1
        while cursor < len(rows) and texts[cursor] in AREAS:
            run += 1
            cursor += 1
        if run >= 3:
            starts.append((index, run))
    out = []
    for position, (index, area_count) in enumerate(starts):
        offset, _length, name = rows[index]
        end = starts[position + 1][0] if position + 1 < len(starts) else len(rows)
        body = rows[index + 1:end]
        areas = [text for _o, _s, text in body[:area_count]]
        rest = body[area_count:]
        curves = [text for _o, _s, text in rest if text in CURVES]
        effects = [text for _o, _s, text in rest if ";" in text]
        steps = []
        for _offset, _size, text in rest:
            if text in AREAS or text in CURVES or ";" in text:
                continue
            if text.startswith("UPGRADE_AREA_") or text == name:
                continue
            if text.strip() in ("L", "G"):
                continue
            steps.append(text)
        next_offset = (rows[end][0] if end < len(rows) else len(plain))
        out.append(Route(name, offset, next_offset - offset, areas, curves,
                         effects, steps))
    return out


class Upgrades:
    """The whole table, indexed by route name."""

    def __init__(self, routes, path=""):
        self.routes = list(routes)
        self.path = path
        self._by_name = {}
        for route in self.routes:
            self._by_name.setdefault(route.name, route)

    def __len__(self) -> int:
        return len(self.routes)

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def names(self) -> list:
        return sorted(self._by_name)

    def get(self, name: str):
        """The route called ``name``, or ``None``."""
        return self._by_name.get(name or "")

    def packs(self) -> list:
        """The ten template routes (``PROD_01`` .. ``RACE_03``), in order."""
        return [self._by_name[n] for n in
                ("PROD_01", "PROD_02", "PROD_03", "PROD_04", "SUPER_01",
                 "SUPER_02", "SUPER_03", "RACE_01", "RACE_02", "RACE_03")
                if n in self._by_name]

    def summary(self) -> str:
        return (f"{len(self.routes)} upgrade route(s), "
                f"{len(self.packs())} of them templates, "
                f"{sum(len(r.steps) for r in self.routes)} step(s)")


def load(depot: str) -> Upgrades:
    """Read the table out of ``depot`` (an install root or a depot folder)."""
    folder = _depot(depot)
    path = os.path.join(folder, *TABLE.split("/"))
    if not os.path.isfile(path):
        raise UpgradesError(f"this install has no {TABLE}")
    raw = open(path, "rb").read()
    plain = nctlib.crypt(raw) if nctlib.looks_encrypted(raw) else raw
    return Upgrades(parse(plain), path)


def _flatten(tokens) -> bytes:
    """Rebuild the byte stream from a token list (``rr3lib.spec.detokenize``).

    Duplicated here rather than imported so this module stays usable on its own;
    the two must agree, and ``selftest`` checks that they do.
    """
    buf = bytearray()
    for kind, _offset, _length, payload in tokens:
        if kind == "s":
            buf += struct.pack("<I", len(payload)) + payload
        else:
            buf += payload
    return bytes(buf)


def route_offset(spec) -> int:
    """Byte offset of the route key in ``spec``, or -1.

    The engine block is twelve numbers, then one ratio per gear **plus reverse**,
    then the key - so ``4 * (13 + gears)`` past the gear count.  Checked against
    all 540 shipped specs: every one of them puts a readable string or an empty
    slot there.
    """
    index = spec._engine_index()
    if index < 0:
        return -1
    plain = _flatten(spec.tokens)
    base = spec.tokens[index][1]
    if base + 4 > len(plain):
        return -1
    gears = struct.unpack_from("<I", plain, base)[0]
    if not 1 <= gears <= 12:
        return -1
    at = base + 4 * (13 + gears)
    return at if at + 4 <= len(plain) else -1


def read_key(spec) -> str:
    """The route key a parsed spec asks for, or ``""``."""
    at = route_offset(spec)
    if at < 0:
        return ""
    plain = _flatten(spec.tokens)
    length = struct.unpack_from("<I", plain, at)[0]
    if length == 0 or length > MAX_KEY or at + 4 + length > len(plain):
        return ""
    chunk = plain[at + 4:at + 4 + length]
    if not all(32 <= c < 127 for c in chunk):
        return ""
    return chunk.decode("ascii")


def selftest(depot: str) -> int:
    """Quiet when the table parses and the templates are all there."""
    table = load(depot)
    problems = 0
    print(table.summary())
    if len(table) < 300:
        print(f"  only {len(table)} route(s) - expected about 327")
        problems += 1
    if len(table.packs()) != 10:
        print(f"  {len(table.packs())} template(s) - expected 10")
        problems += 1
    for route in table.packs():
        print(f"  {route.name}: {len(route.areas)} area(s), "
              f"{len(route.steps)} step(s), {route.length} B")
        if not route.steps:
            print(f"  {route.name} has no steps")
            problems += 1
    return problems
