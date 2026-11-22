"""``liveries/<car>.liveries.bin.nct``: read, edit and write the paint tables.

This is the file that decides **which material each part of a car uses**, and
therefore which fresnel/specular LUT the engine binds when it draws that part.
Getting it wrong is why a custom part can come out flat and dark while the rest
of the car looks painted - see the note at the bottom.

FOUR TABLES
-----------
::

    str   car name (a liveryStringTable token)
    u32 n; n x (u32 slot, str path)          textures   - atlas per slot
    u32 n; n x (u32 meshSlot, u32 matSlot)   materials  - part -> material
    u32 n; n x (u32, u32, u32)               extra      - unknown, copied as is
    u32 n                                     liveries  - the paint schemes
      per livery:
        str file        e.g. "01_2012_lexus_lfa.livery"
        str display
        8 bytes
        str swatch
        str logo
        u8  flag
        str arms
        str driver
        4 bytes
        3 bytes RGB
        u32 m; m x (u32 slot, str path)      texture overrides
        u32 k; k x (u32 meshSlot, u32 matSlot)  material overrides

Every slot id is an index into ``liveryStringTable.bin.nct``, a flat string
table of 2068 entries that mixes part names (``LOD_A_BODY_mm_ext``), material
names (``car_paint_metallic_white``) and a few region markers (``ext_ext``,
``int_int``, ...).

HOW A PART GETS ITS MATERIAL
----------------------------
Three levels, first hit wins:

1. the livery's own **material override** table  (per paint scheme)
2. the car's **materials** table                 (per car, all schemes)
3. ``default.liveries.bin.nct``'s table          (all cars)

Level 1 is the only one that can differ per paint scheme, so it is the only
place a "body-coloured wing" can be expressed.  The shipped cars do exactly
that: ``LOD_A_WING_REAR_mm_ext`` (slot 745) is mapped in 59 paint schemes
across 25 cars, and the target is *always* the same material as
``LOD_A_BODY_mm_ext`` (slot 30) in that scheme.

A part whose name is **not** in ``liveryStringTable`` has no slot at all, so no
level can reach it and the engine falls back to a hard coded material.  That is
why renaming a mesh is never the fix for a dark part: it just removes the name
from the system.
"""

from __future__ import annotations

import copy
import glob
import os
import struct
from dataclasses import dataclass, field

from . import catalog, nct

#: Path of the string table, relative to the depot root.
SLOT_TABLE = "vehicles/data/liveries/liveryStringTable.bin.nct"
#: Directory holding one ``<car>.liveries.bin.nct`` per car.
LIVERY_DIR = "vehicles/data/liveries"
#: The all-cars fallback table (two tables, no car name, no paint schemes).
DEFAULT_LIVERY = "vehicles/data/liveries/default.liveries.bin.nct"

#: Slot ids that matter when painting parts.
SLOT_BODY_EXT = 30          # LOD_A_BODY_mm_ext
SLOT_WING_REAR_EXT = 745    # LOD_A_WING_REAR_mm_ext
SLOT_WING_REAR_MISC = 747   # LOD_A_WING_REAR_mm_misc
SLOT_WING_REAR_LEFT = 738
SLOT_WING_REAR_RIGHT = 742
SLOT_WING_STRUT_REAR = 750
SLOT_WING_STRUT = 753
SLOT_WING_EXT = 757


class LiveryError(Exception):
    pass


# ------------------------------------------------------------------ slot table
class SlotTable:
    """``liveryStringTable.bin.nct`` as a name <-> id mapping."""

    def __init__(self, names: list[str]):
        self.names = names
        self._by_name = {}
        for i, n in enumerate(names):
            self._by_name.setdefault(n, i)

    def __len__(self) -> int:
        return len(self.names)

    def __getitem__(self, i: int) -> str:
        return self.names[i]

    def name(self, slot: int) -> str:
        """Slot id -> name, or a ``?<id>`` placeholder when out of range."""
        if 0 <= slot < len(self.names):
            return self.names[slot]
        return f"?{slot}"

    def slot(self, name: str) -> int | None:
        return self._by_name.get(name)

    def part_slot(self, part: str) -> int | None:
        """Slot for a part (mesh) name."""
        return self.slot(part)

    def material_slot(self, material: str) -> int | None:
        """Slot for a material name."""
        return self.slot(material)

    def parts(self) -> list[str]:
        return [n for n in self.names if n.startswith("LOD_")]

    def materials(self) -> list[str]:
        return [n for n in self.names if n.startswith("car_") or n == "add"]

    def append(self, name: str) -> int:
        """Add a name at the end; returns its new slot id.

        Slots are positions, so appending is the only safe change: inserting in
        the middle would renumber every slot above it and every livery table in
        the game would then point at the wrong part.  A name that is already
        there returns its existing slot and changes nothing, which is what makes
        the caller's "add this part" idempotent.
        """
        name = str(name)
        if not name:
            raise LiveryError("a slot name cannot be empty")
        got = self._by_name.get(name)
        if got is not None:
            return got
        self.names.append(name)
        self._by_name[name] = len(self.names) - 1
        return len(self.names) - 1

    def append_all(self, names) -> list[int]:
        """Append several names, in order, and return their slots."""
        return [self.append(n) for n in names]


def load_slot_table(depot: str) -> SlotTable:
    """Read and decrypt the string table under ``depot``."""
    path = os.path.join(depot, *SLOT_TABLE.split("/"))
    if not os.path.isfile(path):
        raise LiveryError(f"no livery string table at {path}")
    data = nct.read(path)
    count = struct.unpack_from("<I", data, 0)[0]
    pos = 4
    names = []
    for _ in range(count):
        ln = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        names.append(data[pos:pos + ln].decode("ascii", "replace"))
        pos += ln
    if pos != len(data):
        raise LiveryError(
            f"string table has {len(data) - pos} trailing bytes - layout changed?"
        )
    return SlotTable(names)


def serialize_slot_table(T: SlotTable) -> bytes:
    """The table's bytes: a count, then a length and the text for each name."""
    out = [struct.pack("<I", len(T.names))]
    for name in T.names:
        raw = name.encode("ascii", "replace")
        out.append(struct.pack("<I", len(raw)))
        out.append(raw)
    return b"".join(out)


def save_slot_table(T: SlotTable, path: str) -> int:
    """Write the table back, encrypted the way the game expects."""
    blob = serialize_slot_table(T)
    nct.write(path, blob)
    return len(blob)


def slot_table_path(depot: str) -> str:
    return os.path.join(depot, *SLOT_TABLE.split("/"))


# ---------------------------------------------------------------------- model
@dataclass
class Paint:
    """One paint scheme (one row in the game's livery list)."""

    file: bytes = b""
    display: bytes = b""
    a: bytes = b"\0" * 8
    swatch: bytes = b""
    logo: bytes = b""
    flag: int = 0
    arms: bytes = b""
    driver: bytes = b""
    c: bytes = b"\0" * 4
    rgb: bytes = b"\0\0\0"
    #: ``(slot, path)`` atlas replacements for this scheme
    overrides: list[tuple[int, bytes]] = field(default_factory=list)
    #: ``(meshSlot, matSlot)`` material replacements for this scheme
    materials: list[tuple[int, int]] = field(default_factory=list)

    def name(self) -> str:
        return self.file.decode("utf-8", "replace")

    def material_of(self, mesh_slot: int) -> int | None:
        for m, t in self.materials:
            if m == mesh_slot:
                return t
        return None

    def set_material(self, mesh_slot: int, mat_slot: int) -> bool:
        """Set or add a material override; keeps the table sorted by mesh slot."""
        for i, (m, _t) in enumerate(self.materials):
            if m == mesh_slot:
                if self.materials[i][1] == mat_slot:
                    return False
                self.materials[i] = (mesh_slot, mat_slot)
                return True
        self.materials.append((mesh_slot, mat_slot))
        self.materials.sort(key=lambda x: x[0])
        return True

    def remove_material(self, mesh_slot: int) -> bool:
        for i, (m, _t) in enumerate(self.materials):
            if m == mesh_slot:
                del self.materials[i]
                return True
        return False

    def texture_of(self, slot: int) -> bytes | None:
        for s, p in self.overrides:
            if s == slot:
                return p
        return None

    def set_texture(self, slot: int, path: bytes) -> bool:
        for i, (s, _p) in enumerate(self.overrides):
            if s == slot:
                if self.overrides[i][1] == path:
                    return False
                self.overrides[i] = (slot, path)
                return True
        self.overrides.append((slot, path))
        self.overrides.sort(key=lambda x: x[0])
        return True


@dataclass
class LiveryFile:
    """A whole ``<car>.liveries.bin.nct``."""

    car: bytes = b""
    textures: list[tuple[int, bytes]] = field(default_factory=list)
    materials: list[tuple[int, int]] = field(default_factory=list)
    extra: list[tuple[int, int, int]] = field(default_factory=list)
    paints: list[Paint] = field(default_factory=list)

    # ---- lookup --------------------------------------------------------
    def material_of(self, mesh_slot: int) -> int | None:
        for m, t in self.materials:
            if m == mesh_slot:
                return t
        return None

    def set_material(self, mesh_slot: int, mat_slot: int) -> bool:
        for i, (m, _t) in enumerate(self.materials):
            if m == mesh_slot:
                if self.materials[i][1] == mat_slot:
                    return False
                self.materials[i] = (mesh_slot, mat_slot)
                return True
        self.materials.append((mesh_slot, mat_slot))
        self.materials.sort(key=lambda x: x[0])
        return True

    def texture_of(self, slot: int) -> bytes | None:
        """The page this car loads for a texture slot, if it names one."""
        for s, p in self.textures:
            if s == slot:
                return p
        return None

    def set_texture(self, slot: int, path: bytes) -> bool:
        """Point a texture slot at a page; keeps the table sorted by slot.

        This is the car-wide row: every paint scheme that does not override the
        slot itself loads this page.  ``Paint.set_texture`` is the per-scheme
        version, which is how the body atlas differs between schemes.
        """
        for i, (s, _p) in enumerate(self.textures):
            if s == slot:
                if self.textures[i][1] == path:
                    return False
                self.textures[i] = (slot, path)
                return True
        self.textures.append((slot, path))
        self.textures.sort(key=lambda x: x[0])
        return True

    def paint(self, index: int) -> Paint:
        return self.paints[index]

    def find_paint(self, text: str) -> Paint | None:
        for p in self.paints:
            if text in p.name():
                return p
        return None

    # ---- adding and removing a scheme ----------------------------------
    def next_paint_name(self) -> str:
        """The next free ``NN_<car>.livery`` name for a new scheme.

        The frontend orders the paint list by the leading number, so a new row
        continues the numbering rather than inventing a name - a scheme called
        ``extra`` would sort after every numbered one and look like a bug in the
        colour list.  Two digits are enough for the 541 shipped cars; a car with
        more than 99 schemes keeps counting, just with three.
        """
        car = self.car.decode("utf-8", "replace")
        highest = 0
        for paint in self.paints:
            head = paint.name().split("_", 1)[0]
            if head.isdigit():
                highest = max(highest, int(head))
        return f"{highest + 1:02d}_{car}.livery"

    def clone_paint(self, index: int = 0, *, name: str = "") -> Paint:
        """Copy one scheme, give the copy a name and append it.

        Everything the scheme carries - colour, finish, materials, its own
        atlases - comes along, because a new preset that is not a copy of an
        existing one is a preset the game cannot draw: the body materials and the
        body atlas are what make a row a picture rather than a blank.
        """
        if not 0 <= int(index) < len(self.paints):
            raise IndexError(f"paint scheme {index} does not exist "
                             f"({len(self.paints)} in the table)")
        paint = copy.deepcopy(self.paints[int(index)])
        if name:
            paint.file = name.encode("utf-8")
        self.paints.append(paint)
        return paint

    # ---- painting ------------------------------------------------------
    def paint_part(self, part: str, material: str, *,
                   table: SlotTable | None = None,
                   paints: list[int] | None = None) -> dict:
        """Give ``part`` the material ``material`` in every paint scheme.

        Both names are looked up in the string table, so a typo raises instead
        of silently writing a slot the engine ignores.  ``paints`` limits the
        change to some scheme indexes; the default is all of them.
        """
        if table is None:
            raise LiveryError("paint_part needs the slot table (pass table=...)")
        mesh_slot = table.part_slot(part)
        if mesh_slot is None:
            raise LiveryError(
                f"part {part!r} is not in liveryStringTable - the engine has no "
                f"material slot for it, so it cannot be painted.  Use an "
                f"existing part name (see rr3lib.catalog.part_names())."
            )
        mat_slot = table.material_slot(material)
        if mat_slot is None:
            raise LiveryError(
                f"material {material!r} is not in liveryStringTable - use a name "
                f"from rr3lib.catalog.material_names()."
            )
        targets = self.paints if paints is None else [self.paints[i] for i in paints]
        changed = []
        for p in targets:
            if p.set_material(mesh_slot, mat_slot):
                changed.append(p.name())
        return {"mesh_slot": mesh_slot, "material_slot": mat_slot,
                "changed": changed}

    def copy_body_paint(self, part: str, *, body_part: str = "LOD_A_BODY_mm_ext",
                        table: SlotTable | None = None) -> dict:
        """Make ``part`` use whatever material the body uses in each scheme.

        This is the pattern every shipped car with a body coloured wing uses:
        the wing's material override equals the body's, scheme by scheme.  It
        works even when different schemes use different paints.
        """
        if table is None:
            raise LiveryError("copy_body_paint needs the slot table")
        mesh_slot = table.part_slot(part)
        body_slot = table.part_slot(body_part)
        if mesh_slot is None:
            raise LiveryError(f"part {part!r} has no slot in liveryStringTable")
        if body_slot is None:
            raise LiveryError(f"body part {body_part!r} has no slot")
        changed = []
        skipped = []
        for p in self.paints:
            target = p.material_of(body_slot)
            if target is None:
                skipped.append(p.name())
                continue
            if p.set_material(mesh_slot, target):
                changed.append(p.name())
        return {"mesh_slot": mesh_slot, "body_slot": body_slot,
                "changed": changed, "skipped": skipped}

    # ---- (de)serialise -------------------------------------------------
    def to_bytes(self) -> bytes:
        return serialize(self)


def _rs(v) -> bytes:
    b = v.encode("ascii") if isinstance(v, str) else v
    return struct.pack("<I", len(b)) + b


def _rd_str(data: bytes, pos: int) -> tuple[bytes, int]:
    ln = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    return data[pos:pos + ln], pos + ln


def parse(data: bytes) -> LiveryFile:
    """Parse plaintext ``.liveries.bin`` bytes."""
    pos = 0
    car, pos = _rd_str(data, pos)

    n = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    textures = []
    for _ in range(n):
        slot = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        path, pos = _rd_str(data, pos)
        textures.append((slot, path))

    n = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    materials = [struct.unpack_from("<II", data, pos + 8 * i) for i in range(n)]
    pos += 8 * n

    n = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    extra = [struct.unpack_from("<III", data, pos + 12 * i) for i in range(n)]
    pos += 12 * n

    n = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    paints = []
    for _ in range(n):
        p = Paint()
        p.file, pos = _rd_str(data, pos)
        p.display, pos = _rd_str(data, pos)
        p.a = data[pos:pos + 8]
        pos += 8
        p.swatch, pos = _rd_str(data, pos)
        p.logo, pos = _rd_str(data, pos)
        p.flag = data[pos]
        pos += 1
        p.arms, pos = _rd_str(data, pos)
        p.driver, pos = _rd_str(data, pos)
        p.c = data[pos:pos + 4]
        pos += 4
        p.rgb = data[pos:pos + 3]
        pos += 3
        m = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        for _i in range(m):
            slot = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            path, pos = _rd_str(data, pos)
            p.overrides.append((slot, path))
        k = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        p.materials = [struct.unpack_from("<II", data, pos + 8 * i) for i in range(k)]
        pos += 8 * k
        paints.append(p)

    if pos != len(data):
        raise LiveryError(
            f"parsed {pos} of {len(data)} bytes - {len(data) - pos} trailing"
        )
    return LiveryFile(car=car, textures=textures, materials=materials,
                      extra=extra, paints=paints)


def serialize(L: LiveryFile) -> bytes:
    out = bytearray()
    out += _rs(L.car)
    out += struct.pack("<I", len(L.textures))
    for slot, path in L.textures:
        out += struct.pack("<I", slot) + _rs(path)
    out += struct.pack("<I", len(L.materials))
    for a, b in L.materials:
        out += struct.pack("<II", a, b)
    out += struct.pack("<I", len(L.extra))
    for t in L.extra:
        out += struct.pack("<III", *t)
    out += struct.pack("<I", len(L.paints))
    for p in L.paints:
        out += _rs(p.file)
        out += _rs(p.display)
        out += p.a
        out += _rs(p.swatch)
        out += _rs(p.logo)
        out += bytes([p.flag & 0xFF])
        out += _rs(p.arms)
        out += _rs(p.driver)
        out += p.c
        out += p.rgb
        out += struct.pack("<I", len(p.overrides))
        for slot, path in p.overrides:
            out += struct.pack("<I", slot) + _rs(path)
        out += struct.pack("<I", len(p.materials))
        for a, b in p.materials:
            out += struct.pack("<II", a, b)
    return bytes(out)


def load(path: str) -> LiveryFile:
    """Read a ``.liveries.bin.nct`` (encrypted or plain)."""
    return parse(nct.read(path))


def save(L: LiveryFile, path: str) -> int:
    """Write a livery file, encrypting it the way the game expects."""
    blob = serialize(L)
    nct.write(path, blob)
    return len(blob)


def load_car(depot: str, car: str) -> LiveryFile:
    """Load ``<depot>/vehicles/data/liveries/<car>.liveries.bin.nct``."""
    path = os.path.join(depot, *LIVERY_DIR.split("/"), car + ".liveries.bin.nct")
    return load(path)


# ------------------------------------------------------- default.liveries table
class DefaultTable:
    """The all-cars fallback: 22 texture rows and ~1867 part->material rows."""

    def __init__(self, textures: list[tuple[int, bytes]],
                 materials: list[tuple[int, int]]):
        self.textures = textures
        self.materials = materials

    def material_of(self, mesh_slot: int) -> int | None:
        for m, t in self.materials:
            if m == mesh_slot:
                return t
        return None

    def set_material(self, mesh_slot: int, mat_slot: int) -> bool:
        for i, (m, _t) in enumerate(self.materials):
            if m == mesh_slot:
                if self.materials[i][1] == mat_slot:
                    return False
                self.materials[i] = (mesh_slot, mat_slot)
                return True
        self.materials.append((mesh_slot, mat_slot))
        self.materials.sort(key=lambda x: x[0])
        return True


def parse_default(data: bytes) -> DefaultTable:
    pos = 0
    n = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    textures = []
    for _ in range(n):
        slot = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        path, pos = _rd_str(data, pos)
        textures.append((slot, path))
    n = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    materials = [struct.unpack_from("<II", data, pos + 8 * i) for i in range(n)]
    pos += 8 * n
    if pos != len(data):
        raise LiveryError(f"default table: {len(data) - pos} trailing bytes")
    return DefaultTable(textures, materials)


def serialize_default(T: DefaultTable) -> bytes:
    out = bytearray(struct.pack("<I", len(T.textures)))
    for slot, path in T.textures:
        out += struct.pack("<I", slot) + _rs(path)
    out += struct.pack("<I", len(T.materials))
    for a, b in T.materials:
        out += struct.pack("<II", a, b)
    return bytes(out)


def load_default(depot: str) -> DefaultTable:
    path = os.path.join(depot, *DEFAULT_LIVERY.split("/"))
    return parse_default(nct.read(path))


# ------------------------------------------------------------ material lookup
def resolve_material(L: LiveryFile, mesh_slot: int, default: DefaultTable | None,
                     paint_index: int | None = None) -> tuple[int | None, str]:
    """Which material does ``mesh_slot`` get, and from which level?

    Returns ``(mat_slot, level)`` where level is ``"paint"``, ``"car"``,
    ``"default"`` or ``"none"``.
    """
    if paint_index is not None:
        hit = L.paints[paint_index].material_of(mesh_slot)
        if hit is not None:
            return hit, "paint"
    hit = L.material_of(mesh_slot)
    if hit is not None:
        return hit, "car"
    if default is not None:
        hit = default.material_of(mesh_slot)
        if hit is not None:
            return hit, "default"
    return None, "none"


def audit(L: LiveryFile, table: SlotTable, default: DefaultTable | None,
          meshes: list[str], paint_index: int | None = None) -> list[tuple]:
    """Resolve a material for every mesh name and report where it came from.

    ``meshes`` is the list of mesh names in the car's ``.m3g``.  The result is
    ``[(mesh, mesh_slot, mat_slot, level), ...]``; a level of ``"none"`` means
    the part will get a hard coded fallback material.
    """
    rows = []
    for name in meshes:
        slot = table.part_slot(name)
        if slot is None:
            rows.append((name, None, None, "no-slot"))
            continue
        mat, level = resolve_material(L, slot, default, paint_index)
        rows.append((name, slot, mat, level))
    return rows


# ----------------------------------------------------------------- self test
def selftest(depot: str | None = None, limit: int = 0) -> int:
    """Round-trip every shipped livery file and the default table."""
    if not depot:
        depot = os.environ.get("RR3_DEPOT", "")
    if not depot or not os.path.isdir(depot):
        print("livery selftest: no depot (set RR3_DEPOT)")
        return 2
    files = sorted(glob.glob(
        os.path.join(depot, *LIVERY_DIR.split("/"), "*.liveries.bin.nct")))
    if limit:
        files = files[:limit]
    bad = 0
    ok = 0
    for p in files:
        plain = nct.read(p)
        # default.liveries.bin.nct has a different shape on purpose: no car
        # name and no paint schemes, just two flat tables
        if os.path.basename(p) == "default.liveries.bin.nct":
            try:
                parse_default(plain)
                ok += 1
            except LiveryError as exc:
                print(f"FAIL {os.path.basename(p)}: {exc}")
                bad += 1
            continue
        try:
            L = parse(plain)
        except (LiveryError, Exception) as exc:  # noqa: BLE001
            print(f"FAIL {os.path.basename(p)}: {exc}")
            bad += 1
            continue
        back = serialize(L)
        if back != plain:
            n = min(len(back), len(plain))
            at = next((i for i in range(n) if back[i] != plain[i]), n)
            print(f"FAIL {os.path.basename(p)}: {len(plain)} -> {len(back)}, "
                  f"first diff at {at}")
            bad += 1
        else:
            ok += 1
    print(f"livery selftest: {len(files)} files, {ok} ok, {bad} failures")
    return 1 if bad else 0


def summary(L: LiveryFile, table: SlotTable) -> str:
    """A short human readable description of a livery file."""
    car = L.car.decode("utf-8", "replace")
    lines = [
        f"car        : {car}",
        f"textures   : {len(L.textures)}",
        f"materials  : {len(L.materials)} (car wide)",
        f"extra      : {len(L.extra)}",
        f"paints     : {len(L.paints)}",
    ]
    for i, p in enumerate(L.paints):
        lines.append(
            f"  [{i}] {p.name():<44} tex={len(p.overrides):<3} mat={len(p.materials)}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(selftest())
