"""The career file: ``data/events.dat.nct``, the whole race calendar.

This is the one file that holds every series in the game.  ``RRCE`` magic, a
version word (``0x82`` for the 14.x builds in this depot), then six counted
blocks: the per-track AI scales, the track list, the series, the tiers, the menu
super-groups, and a tail that is kept as bytes because nothing here edits it.

Layout, all little endian, all counts ``i32``::

    "RRCE" u32 version
    i32 3*17                     -- 51 counted lists of u32 (the AI scales)
    i32 count, count * "sfb"     -- tracks: name, ?, ?
    i32 count, series...
    i32 count, tiers...
    i32 count, super groups...
    ... tail, kept verbatim

A series is ``"isis"`` (id, title key, type, description key), three lists of
``(u32, u32)`` curves, a list of requirement groups of ``"siis"`` records, then
``"ibbssib"`` (the completion reward lives at index 3).

A tier is ``"ssiiiiib"`` (name key, display key, index in the series, tier id,
series id, unlock, trophies, flag), a list of ``(i32 car id, u8 flags)``, three
banner strings, then its events.

An event is a fixed run of fields (``_EVENT_A``), a byte saying whether an extra
block follows (``"bff"`` when it does), then ``_EVENT_B``.  Only a handful of
those fields mean anything to us: type, id, track name, laps, fame, reward.

The menu tree is a forest of ``Rr3GroupNode``.  Type 0 and 1 nodes carry
``pages`` - lists of series ids, which is what decides where a series shows up.
Type 2 nodes are hubs with a large opaque block that is kept as bytes.

Why this module exists
----------------------
``events.dat`` is 14 MB and the game rewrites it whenever the career advances,
so it is never safe to hand a stale copy back.  Everything here round trips:
``parse(plain).to_bytes() == plain`` for the depot's own file, which is the
guard the caller must check before writing anything.
"""

from __future__ import annotations

import os
import struct

from rr3lib import nct

EVENTS = "data/events.dat.nct"
MAGIC = b"RRCE"
VERSION = 0x82
MAX_STRING = 0x800
MAX_COUNT = 10_000_000

_EVENT_A = "iisiiiiiiisbisiififsifsbbi"
_EVENT_B = "iifibbibbiiiib"
_SERIES_HEAD = "isis"
_SERIES_TAIL = "ibbssib"
_TIER_HEAD = "ssiiiiib"
_NODE_BASE = "ssssss"
_NODE_BASE2 = "ssssss"


class CareerError(Exception):
    pass


# ---------------------------------------------------------------- primitives
class _Reader:
    """The C++ ``Rd``: little endian reads that latch the first failure."""

    __slots__ = ("p", "n", "i", "bad", "why")

    def __init__(self, data: bytes):
        self.p = data
        self.n = len(data)
        self.i = 0
        self.bad = False
        self.why = ""

    def _fail(self, why: str) -> None:
        if not self.bad:
            self.bad = True
            self.why = f"{why} at byte {self.i}"
        self.i = self.n

    def u32(self) -> int:
        if self.i + 4 > self.n:
            self._fail("ran past the end")
            return 0
        v = struct.unpack_from("<I", self.p, self.i)[0]
        self.i += 4
        return v

    def i32(self) -> int:
        if self.i + 4 > self.n:
            self._fail("ran past the end")
            return 0
        v = struct.unpack_from("<i", self.p, self.i)[0]
        self.i += 4
        return v

    def u8(self) -> int:
        if self.i + 1 > self.n:
            self._fail("ran past the end")
            return 0
        v = self.p[self.i]
        self.i += 1
        return v

    def string(self) -> str:
        ln = self.u32()
        if self.bad:
            return ""
        if ln > MAX_STRING or ln > self.n - self.i:
            self._fail("a string longer than the game allows")
            return ""
        raw = self.p[self.i:self.i + ln]
        self.i += ln
        return raw.decode("latin-1")

    def count(self) -> int:
        c = self.i32()
        if c < 0 or c > MAX_COUNT:
            self._fail("an impossible count")
            return 0
        return c

    def take(self, start: int) -> bytes:
        """Everything read since ``start`` - the C++ ``type2.assign(p + from, p + i)``."""
        return self.p[start:self.i]


class _Writer:
    """The C++ ``Wr``."""

    __slots__ = ("b",)

    def __init__(self):
        self.b = bytearray()

    def u32(self, v: int) -> None:
        self.b += struct.pack("<I", v & 0xFFFFFFFF)

    def i32(self, v: int) -> None:
        self.b += struct.pack("<i", v)

    def u8(self, v: int) -> None:
        self.b.append(v & 0xFF)

    def string(self, s: str) -> None:
        raw = s.encode("latin-1", "replace")
        self.u32(len(raw))
        self.b += raw

    def raw(self, data: bytes) -> None:
        self.b += data


class Field:
    """One field of a schema record: ``t`` is ``i`` (u32), ``f`` (f32), ``b``, ``s``."""

    __slots__ = ("t", "u", "s")

    def __init__(self, t: str = "i", u: int = 0, s: str = ""):
        self.t = t
        self.u = u
        self.s = s

    def __repr__(self) -> str:
        return f"Field({self.t!r}, {self.u!r}, {self.s!r})"

    def __eq__(self, other) -> bool:
        return (isinstance(other, Field) and self.t == other.t
                and self.u == other.u and self.s == other.s)

    def copy(self) -> "Field":
        return Field(self.t, self.u, self.s)


def _read_rec(r: _Reader, schema: str) -> list[Field]:
    out = []
    for k in schema:
        if k == "s":
            out.append(Field("s", 0, r.string()))
        elif k == "b":
            out.append(Field("b", r.u8()))
        else:
            # 'i' and 'f' both read four bytes; f keeps the raw word so a
            # rebuild is exact even for values that are not finite
            out.append(Field(k, r.u32()))
    return out


def _write_rec(w: _Writer, rec: list[Field]) -> None:
    for v in rec:
        if v.t == "s":
            w.string(v.s)
        elif v.t == "b":
            w.u8(v.u)
        else:
            w.u32(v.u)


def _u(rec: list[Field], i: int) -> int:
    return rec[i].u if i < len(rec) else 0


def _s(rec: list[Field], i: int) -> str:
    return rec[i].s if i < len(rec) else ""


# --------------------------------------------------------------------- event
class Event:
    """One race inside a tier."""

    __slots__ = ("a", "extra_present", "extra", "b")

    def __init__(self, a=None, extra_present=0, extra=None, b=None):
        self.a = a or []
        self.extra_present = extra_present
        self.extra = extra or []
        self.b = b or []

    # what the game and the tools care about
    @property
    def type(self) -> int:
        return _u(self.a, 0)

    @type.setter
    def type(self, v: int) -> None:
        self.a[0].u = v & 0xFFFFFFFF

    @property
    def id(self) -> int:
        return _u(self.a, 1)

    @id.setter
    def id(self, v: int) -> None:
        self.a[1].u = v & 0xFFFFFFFF

    @property
    def track(self) -> str:
        return _s(self.a, 2)

    @track.setter
    def track(self, v: str) -> None:
        self.a[2].s = v

    @property
    def laps(self) -> int:
        return _u(self.a, 3)

    @laps.setter
    def laps(self, v: int) -> None:
        self.a[3].u = v & 0xFFFFFFFF

    @property
    def fame(self) -> int:
        return _u(self.a, 7)

    @fame.setter
    def fame(self, v: int) -> None:
        self.a[7].u = v & 0xFFFFFFFF

    @property
    def reward(self) -> int:
        return _u(self.a, 8)

    @reward.setter
    def reward(self, v: int) -> None:
        self.a[8].u = v & 0xFFFFFFFF

    def copy(self) -> "Event":
        return Event([f.copy() for f in self.a], self.extra_present,
                     [f.copy() for f in self.extra], [f.copy() for f in self.b])

    def describe(self) -> str:
        return f"{self.track} type {self.type}, {self.laps} lap(s), fame {self.fame}"

    def __repr__(self) -> str:
        return f"Event({self.id}, {self.describe()!r})"


# ---------------------------------------------------------------------- tier
class Tier:
    """A tier of a series: the allowed cars plus the events in it."""

    __slots__ = ("head", "cars", "banners", "events")

    def __init__(self, head=None, cars=None, banners=None, events=None):
        self.head = head or []
        self.cars = cars or []          # [(car id, flags)]
        self.banners = banners or []
        self.events = events or []

    @property
    def id(self) -> int:
        return _u(self.head, 3)

    @id.setter
    def id(self, v: int) -> None:
        self.head[3].u = v & 0xFFFFFFFF

    @property
    def series_id(self) -> int:
        return _u(self.head, 4)

    @series_id.setter
    def series_id(self, v: int) -> None:
        self.head[4].u = v & 0xFFFFFFFF

    @property
    def index(self) -> int:
        return _u(self.head, 2)

    @index.setter
    def index(self, v: int) -> None:
        self.head[2].u = v & 0xFFFFFFFF

    @property
    def name_key(self) -> str:
        return _s(self.head, 0)

    @property
    def display_key(self) -> str:
        return _s(self.head, 1)

    def copy(self) -> "Tier":
        return Tier([f.copy() for f in self.head], list(self.cars),
                    [f.copy() for f in self.banners],
                    [e.copy() for e in self.events])

    def describe(self) -> str:
        return (f"tier {self.id} (index {self.index}) of series {self.series_id}: "
                f"{len(self.cars)} car(s), {len(self.events)} event(s)")

    def __repr__(self) -> str:
        return f"Tier({self.describe()!r})"


# -------------------------------------------------------------------- series
class Series:
    """A championship: a title, a description, and tiers full of events."""

    __slots__ = ("head", "curves", "requirements", "tail")

    def __init__(self, head=None, curves=None, requirements=None, tail=None):
        self.head = head or []
        self.curves = curves or ([], [], [])     # three lists of (u32, u32)
        self.requirements = requirements or []   # [[Field x4], ...]
        self.tail = tail or []

    @property
    def id(self) -> int:
        return _u(self.head, 0)

    @id.setter
    def id(self, v: int) -> None:
        self.head[0].u = v & 0xFFFFFFFF

    @property
    def title_key(self) -> str:
        return _s(self.head, 1)

    @title_key.setter
    def title_key(self, v: str) -> None:
        self.head[1].s = v

    @property
    def type(self) -> int:
        return _u(self.head, 2)

    @property
    def desc_key(self) -> str:
        return _s(self.head, 3)

    @desc_key.setter
    def desc_key(self, v: str) -> None:
        self.head[3].s = v

    @property
    def completion_reward(self) -> str:
        return _s(self.tail, 3)

    @completion_reward.setter
    def completion_reward(self, v: str) -> None:
        self.tail[3].s = v

    @property
    def reward_id(self) -> str:
        return _s(self.tail, 4)

    @reward_id.setter
    def reward_id(self, v: str) -> None:
        self.tail[4].s = v

    def copy(self) -> "Series":
        return Series([f.copy() for f in self.head],
                      [list(c) for c in self.curves],
                      [[f.copy() for f in g] for g in self.requirements],
                      [f.copy() for f in self.tail])

    def describe(self) -> str:
        return (f"series {self.id} \"{self.title_key}\" type {self.type}, "
                f"{len(self.requirements)} requirement group(s)")

    def __repr__(self) -> str:
        return f"Series({self.describe()!r})"


# ----------------------------------------------------------------- group tree
class GroupNode:
    """One node of the menu tree.

    ``type`` 0 and 1 hold ``pages`` (lists of series ids); type 2 is a hub whose
    body is kept in ``type2`` as opaque bytes.
    """

    __slots__ = ("type", "base", "logos", "packs", "base2", "children",
                 "pages", "type2")

    def __init__(self, type=0, base=None, logos=None, packs=None, base2=None,
                 children=None, pages=None, type2=b""):
        self.type = type
        self.base = base or []
        self.logos = logos or []
        self.packs = packs or []
        self.base2 = base2 or []
        self.children = children or []
        self.pages = pages or []
        self.type2 = type2

    @property
    def key(self) -> str:
        return _s(self.base, 0)

    @key.setter
    def key(self, v: str) -> None:
        self.base[0].s = v

    @property
    def flavour_key(self) -> str:
        return _s(self.base, 1)

    @property
    def card(self) -> str:
        return _s(self.base, 3)

    @card.setter
    def card(self, v: str) -> None:
        self.base[3].s = v

    def copy(self) -> "GroupNode":
        return GroupNode(self.type, [f.copy() for f in self.base],
                         list(self.logos), list(self.packs),
                         [f.copy() for f in self.base2],
                         [c.copy() for c in self.children],
                         [list(p) for p in self.pages], self.type2)

    def walk(self, path: str = ""):
        """Yield ``(path, node)`` for this node and every descendant."""
        here = f"{path}/{self.key}" if path else self.key
        yield here, self
        for c in self.children:
            yield from c.walk(here)

    def has_series(self, series_id: int) -> bool:
        for page in self.pages:
            if series_id in page:
                return True
        return any(c.has_series(series_id) for c in self.children)

    def __repr__(self) -> str:
        return (f"GroupNode({self.key!r}, type {self.type}, "
                f"{len(self.children)} child(ren), {len(self.pages)} page(s))")


class SuperGroup:
    """A top-level menu: the career, the motorsports hub, and so on."""

    __slots__ = ("kind", "name", "card", "packs", "groups")

    def __init__(self, kind=0, name="", card="", packs=None, groups=None):
        self.kind = kind
        self.name = name
        self.card = card
        self.packs = packs or []
        self.groups = groups or []

    def copy(self) -> "SuperGroup":
        return SuperGroup(self.kind, self.name, self.card, list(self.packs),
                          [g.copy() for g in self.groups])

    def __repr__(self) -> str:
        return f"SuperGroup({self.name!r}, kind {self.kind}, {len(self.groups)} group(s))"


# -------------------------------------------------------------------- career
class Career:
    """The whole ``events.dat``."""

    __slots__ = ("version", "scales", "tracks", "series", "tiers",
                 "super_groups", "rest", "name_pools", "grids", "grid_names")

    def __init__(self):
        self.version = VERSION
        self.scales = b""
        self.tracks = []            # [[Field sfb], ...]
        self.series = []
        self.tiers = []
        self.super_groups = []
        self.rest = b""
        self.name_pools = 0
        self.grids = 0
        self.grid_names = []

    # ---- lookups
    def track_names(self) -> list[str]:
        return [_s(t, 0) for t in self.tracks]

    def series_by_id(self, series_id: int):
        for s in self.series:
            if s.id == series_id:
                return s
        return None

    def tiers_of(self, series_id: int) -> list[Tier]:
        out = [t for t in self.tiers if t.series_id == series_id]
        out.sort(key=lambda t: t.index)
        return out

    def max_series_id(self) -> int:
        return max((s.id for s in self.series), default=-1)

    def max_tier_id(self) -> int:
        return max((t.id for t in self.tiers), default=-1)

    def max_event_id(self) -> int:
        top = -1
        for t in self.tiers:
            for e in t.events:
                top = max(top, e.id)
        return top

    def groups(self) -> list[tuple[str, GroupNode, int]]:
        """``[(path, node, super group index)]`` for every node in the menu."""
        out = []
        for gi, g in enumerate(self.super_groups):
            for node in g.groups:
                for path, n in node.walk(g.name):
                    out.append((path, n, gi))
        return out

    def group_map(self) -> dict:
        """``{series id: "Super/Path"}`` built in one pass over the menu.

        Asking :meth:`group_of` once per series re-walks the whole tree each
        time, which is O(series x groups): 1602 series made that call take
        thirteen seconds.  Callers that want every series at once should use
        this instead.
        """
        out = {}
        for path, node, _gi in self.groups():
            for page in node.pages:
                for series_id in page:
                    out.setdefault(series_id, path)
        return out

    def tier_map(self) -> dict:
        """``{series id: [Tier, ...]}``, each list sorted by index."""
        out = {}
        for t in self.tiers:
            out.setdefault(t.series_id, []).append(t)
        for rows in out.values():
            rows.sort(key=lambda t: t.index)
        return out

    def group_of(self, series_id: int) -> str:
        for path, node, _gi in self.groups():
            if node.has_series(series_id):
                return path
        return ""

    def events_of(self, series_id: int) -> list[Event]:
        out = []
        for t in self.tiers_of(series_id):
            out.extend(t.events)
        return out

    def summary(self) -> dict:
        return {
            "version": hex(self.version),
            "tracks": len(self.tracks),
            "series": len(self.series),
            "tiers": len(self.tiers),
            "events": sum(len(t.events) for t in self.tiers),
            "super_groups": len(self.super_groups),
            "groups": len(self.groups()),
            "grids": self.grids,
        }

    # ---- serialisation
    def to_bytes(self) -> bytes:
        w = _Writer()
        w.raw(MAGIC)
        w.u32(self.version)
        w.raw(self.scales)
        w.u32(len(self.tracks))
        for t in self.tracks:
            _write_rec(w, t)
        w.u32(len(self.series))
        for s in self.series:
            _write_rec(w, s.head)
            for q in range(3):
                w.u32(len(s.curves[q]))
                for a, b in s.curves[q]:
                    w.u32(a)
                    w.u32(b)
            w.u32(len(s.requirements))
            for group in s.requirements:
                w.u32(len(group))
                for rec in group:
                    _write_rec(w, rec)
            _write_rec(w, s.tail)
        w.u32(len(self.tiers))
        for t in self.tiers:
            _write_rec(w, t.head)
            w.u32(len(t.cars))
            for car_id, flags in t.cars:
                w.i32(car_id)
                w.u8(flags)
            _write_rec(w, t.banners)
            w.u32(len(t.events))
            for e in t.events:
                _write_rec(w, e.a)
                w.u8(e.extra_present)
                if e.extra_present:
                    _write_rec(w, e.extra)
                _write_rec(w, e.b)
        w.u32(len(self.super_groups))
        for g in self.super_groups:
            w.i32(g.kind)
            w.string(g.name)
            w.string(g.card)
            w.u32(len(g.packs))
            for p in g.packs:
                w.string(p)
            w.u32(len(g.groups))
            for n in g.groups:
                _write_node(w, n)
        w.raw(self.rest)
        return bytes(w.b)


def _read_node(r: _Reader, depth: int) -> GroupNode:
    if depth > 32:
        r._fail("group nodes nested too deep")
        return GroupNode()
    n = GroupNode()
    n.type = r.i32()
    n.base = _read_rec(r, _NODE_BASE)
    for _ in range(r.count()):
        n.logos.append(r.string())
        if r.bad:
            break
    for _ in range(r.count()):
        n.packs.append(r.string())
        if r.bad:
            break
    n.base2 = _read_rec(r, _NODE_BASE2)
    for _ in range(r.count()):
        n.children.append(_read_node(r, depth + 1))
        if r.bad:
            break
    if n.type in (0, 1):
        for _ in range(r.count()):
            page = []
            for _ in range(r.count()):
                page.append(r.i32())
                if r.bad:
                    break
            n.pages.append(page)
            if r.bad:
                break
    elif n.type == 2:
        from_at = r.i
        r.i32()
        for _ in range(3):
            for _ in range(r.count()):
                r.i32()
                if r.bad:
                    break
        r.i32()
        for _ in range(5):
            r.string()
        r.u8()
        r.i32()
        for _ in range(14):
            r.string()
        for _ in range(r.count()):
            r.i32()
            for _ in range(5):
                r.string()
            r.i32()
            r.string()
            if r.bad:
                break
        if not r.bad:
            n.type2 = r.take(from_at)
    else:
        r._fail("a group node of an unknown type")
    return n


def _write_node(w: _Writer, n: GroupNode) -> None:
    w.i32(n.type)
    _write_rec(w, n.base)
    w.u32(len(n.logos))
    for s in n.logos:
        w.string(s)
    w.u32(len(n.packs))
    for s in n.packs:
        w.string(s)
    _write_rec(w, n.base2)
    w.u32(len(n.children))
    for c in n.children:
        _write_node(w, c)
    if n.type in (0, 1):
        w.u32(len(n.pages))
        for page in n.pages:
            w.u32(len(page))
            for series_id in page:
                w.i32(series_id)
    else:
        w.raw(n.type2)


def _read_event(r: _Reader) -> Event:
    e = Event()
    e.a = _read_rec(r, _EVENT_A)
    e.extra_present = r.u8()
    if e.extra_present:
        e.extra = _read_rec(r, "bff")
    e.b = _read_rec(r, _EVENT_B)
    return e


def parse(plain: bytes) -> Career:
    """Decode a decrypted ``events.dat``."""
    if len(plain) < 8 or plain[:4] != MAGIC:
        raise CareerError("not a career file (no RRCE)")
    c = Career()
    r = _Reader(plain)
    r.i = 4
    c.version = r.u32()
    if c.version != VERSION:
        raise CareerError(
            f"career file version 0x{c.version:X} - this reader handles 0x{VERSION:X} "
            f"(Real Racing 3 14.x)")
    from_at = r.i
    for _ in range(3 * 17):
        for _ in range(r.count()):
            r.u32()
            if r.bad:
                break
    c.scales = r.take(from_at)

    for _ in range(r.count()):
        c.tracks.append(_read_rec(r, "sfb"))
        if r.bad:
            break

    for _ in range(r.count()):
        s = Series()
        s.head = _read_rec(r, _SERIES_HEAD)
        for q in range(3):
            for _ in range(r.count()):
                s.curves[q].append((r.u32(), r.u32()))
                if r.bad:
                    break
        for _ in range(r.count()):
            group = []
            for _ in range(r.count()):
                group.append(_read_rec(r, "siis"))
                if r.bad:
                    break
            s.requirements.append(group)
            if r.bad:
                break
        s.tail = _read_rec(r, _SERIES_TAIL)
        c.series.append(s)
        if r.bad:
            break

    for _ in range(r.count()):
        t = Tier()
        t.head = _read_rec(r, _TIER_HEAD)
        for _ in range(r.count()):
            t.cars.append((r.i32(), r.u8()))
            if r.bad:
                break
        t.banners = _read_rec(r, "sss")
        for _ in range(r.count()):
            t.events.append(_read_event(r))
            if r.bad:
                break
        c.tiers.append(t)
        if r.bad:
            break

    for _ in range(r.count()):
        g = SuperGroup()
        g.kind = r.i32()
        g.name = r.string()
        g.card = r.string()
        for _ in range(r.count()):
            g.packs.append(r.string())
            if r.bad:
                break
        for _ in range(r.count()):
            g.groups.append(_read_node(r, 0))
            if r.bad:
                break
        c.super_groups.append(g)
        if r.bad:
            break

    rest_from = r.i
    c.name_pools = r.count()
    for _ in range(c.name_pools):
        n = r.count()
        r.string()
        for _ in range(n):
            r.string()
            if r.bad:
                break
    c.grids = r.count()
    for _ in range(c.grids):
        c.grid_names.append(r.string())
        r.u8()
        for _ in range(r.count()):
            if r.u8() == 0:
                r.string()
            if r.bad:
                break
    # the C++ keeps everything from restFrom to the end of the file, parsed or
    # not: the name pools and grids are only counted, never rebuilt
    c.rest = plain[rest_from:]
    if r.bad:
        raise CareerError(f"career file: {r.why}")
    if from_at >= r.i:
        raise CareerError("career file: nothing was read")
    return c


def load(depot: str) -> Career:
    """Read and decode ``<depot>/data/events.dat.nct``."""
    return parse(nct.read(os.path.join(depot, *EVENTS.split("/"))))


def encode(c: Career) -> bytes:
    """Serialise and encrypt, ready to write as ``events.dat.nct``."""
    return nct.crypt(c.to_bytes())


def save(c: Career, path: str) -> int:
    """Round trip check, then write the encrypted file."""
    plain = c.to_bytes()
    again = parse(plain)
    if again.to_bytes() != plain:
        raise CareerError("the career file did not read back byte for byte - not written")
    blob = nct.crypt(plain)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)


def roundtrip(depot: str) -> bool:
    """True when the depot's own file rebuilds byte for byte."""
    c = load(depot)
    return c.to_bytes() == nct.read(os.path.join(depot, *EVENTS.split("/")))
