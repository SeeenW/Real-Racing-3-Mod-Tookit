"""``appearances.link.nct`` and the per car ``.link`` files: shared car bodies.

Most cars ship their own geometry in ``vehicles/<name>/``.  The rest borrow
another car's body and only replace a few files - the 63 Formula 1 entries all
draw the same monocoque, every Formula E team shares one chassis, and the
NASCAR liveries share three body shells.  The engine finds those through two
mechanisms:

``vehicles/data/appearances.link.nct``
    The global table.  ``u32 version = 1``, ``u32 count = 82``, then one record
    per redirected model::

        u32 len; char model_name[]      the folder that does NOT have geometry
        u32 n_items                     how many entries follow
        u32 reserved                    always 0 in all 82 records
        n_items x string                either a folder name (redirect) or
                                        a file name followed by its replacement

    A *string* here is ``u32 len + chars``.  A folder entry is one string; a
    file entry is two (the name to match, then the replacement path).  Telling
    them apart by "does it end in a known asset extension" is what makes the
    parse land exactly on the end of the file - the other orderings (treating
    the counts as folder/file tallies) all desynchronise within the first few
    records.  68 of the 82 records are a plain one-folder redirect; the other 14
    also swap individual files (``2020_chevrolet_camaro_nascar`` replaces 9).

``vehicles/<name>/<name>.link``
    Per car, **plain text with comments**, and it documents the format::

        # the game looks in the car's own folder first, then follows the
        # redirects; /livery and the .liveries file itself are exempt
        dir:2014_maserati_granturismo

    Only one shipped car has this file (``2014_maserati_granturismo_r3``); it
    is kept readable here because it is the format's own documentation.

RESOLUTION ORDER
----------------
The engine searches ``vehicles/<name>/`` for the requested file, then walks the
redirects.  For "which folder holds this car's geometry" that collapses to:

1. ``vehicles/<car>/`` if it contains a ``.m3g``;
2. otherwise the global table's ``dirs[0]`` for ``<car>``;
3. otherwise the appearance record name (``Spec.appearance_id()``);
4. repeat from 1 with the new name, at most :data:`MAX_HOPS` times.

Verified on the shipped data: 540/540 cars resolve, 172 directly, 308 in one
hop, 60 in two.  29 shared folders cover 168 cars.
"""

from __future__ import annotations

import os
import struct

from . import nct

#: Path relative to the depot root.
LINK_TABLE = "vehicles/data/appearances.link.nct"
LINK_VERSION = 1

#: How many redirects to follow before giving up.  The deepest chain in the
#: shipped data is two (``..._gt-r_gt1`` -> ``..._sumo_gtr_gt1`` -> its folder),
#: so this is generous.
MAX_HOPS = 8

#: Suffixes that mark the first string of a file redirect.  A folder name never
#: ends in one of these, which is what makes the record parse unambiguous.
FILE_SUFFIXES = (
    ".m3g", ".dds.z", ".pvr.z", ".nct", ".points", ".banim", ".xml", ".atlas",
    ".bin", ".dashplanes", ".decomp", ".dds", ".pvr", ".png",
)

#: A string longer than this inside the table is not a name; it means the parse
#: has slipped and is reading payload as a length.
MAX_STRING = 400


class LinkError(Exception):
    pass


class Entry:
    """One redirected model: its folder redirects plus any file overrides."""

    __slots__ = ("name", "dirs", "files")

    def __init__(self, name: str, dirs: list[str], files: list[tuple[str, str]]):
        self.name = name
        self.dirs = dirs
        self.files = files

    def __repr__(self) -> str:
        return f"Entry({self.name!r}, dirs={self.dirs!r}, files={len(self.files)})"

    def as_dict(self) -> dict:
        return {"name": self.name, "dirs": list(self.dirs),
                "files": [list(p) for p in self.files]}


class LinkTable:
    """The parsed ``appearances.link.nct``."""

    def __init__(self, version: int, entries: list[Entry], raw_len: int):
        self.version = version
        self.entries = entries
        self.raw_len = raw_len
        self._by_name = {e.name: e for e in entries}

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, name: str) -> Entry | None:
        return self._by_name.get(name)

    def target(self, name: str) -> str:
        """The first folder redirect for ``name``, or "" when there is none."""
        entry = self._by_name.get(name)
        if entry is None or not entry.dirs:
            return ""
        return entry.dirs[0]

    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    def summary(self) -> dict:
        return {
            "version": self.version,
            "entries": len(self.entries),
            "with_dir": sum(1 for e in self.entries if e.dirs),
            "with_files": sum(1 for e in self.entries if e.files),
            "file_overrides": sum(len(e.files) for e in self.entries),
        }


def parse(raw: bytes) -> LinkTable:
    """Parse the decrypted table.  Raises :class:`LinkError` on any slip."""
    if len(raw) < 8:
        raise LinkError(f"table is only {len(raw)} bytes")
    version, count = struct.unpack_from("<II", raw, 0)
    if version != LINK_VERSION:
        raise LinkError(f"unexpected version {version}")
    at = 8

    def read_string(pos: int) -> tuple[str, int]:
        if pos + 4 > len(raw):
            raise LinkError(f"ran off the end reading a length at {pos}")
        length = struct.unpack_from("<I", raw, pos)[0]
        if length > MAX_STRING or pos + 4 + length > len(raw):
            raise LinkError(f"bad string length {length} at {pos}")
        text = raw[pos + 4:pos + 4 + length]
        try:
            name = text.decode("ascii")
        except UnicodeDecodeError as exc:
            raise LinkError(f"non ascii name at {pos}: {exc}") from None
        return name, pos + 4 + length

    entries: list[Entry] = []
    for _ in range(count):
        name, at = read_string(at)
        if at + 8 > len(raw):
            raise LinkError(f"ran off the end after {name!r}")
        items, reserved = struct.unpack_from("<II", raw, at)
        at += 8
        if reserved:
            raise LinkError(f"{name!r}: reserved word is {reserved}, not 0")
        dirs: list[str] = []
        files: list[tuple[str, str]] = []
        for _ in range(items):
            text, at = read_string(at)
            if text.lower().endswith(FILE_SUFFIXES):
                replacement, at = read_string(at)
                files.append((text, replacement))
            else:
                dirs.append(text)
        entries.append(Entry(name, dirs, files))
    if at != len(raw):
        raise LinkError(f"parsed {at} of {len(raw)} bytes")
    return LinkTable(version, entries, len(raw))


def load(depot: str) -> LinkTable:
    """Read and parse ``<depot>/vehicles/data/appearances.link.nct``."""
    path = os.path.join(depot, LINK_TABLE)
    if not os.path.isfile(path):
        raise LinkError(f"no link table at {path}")
    return parse(nct.read(path))


def build(table: LinkTable) -> bytes:
    """Serialise a table back to plaintext bytes (for round trip checks)."""
    out = bytearray(struct.pack("<II", table.version, len(table.entries)))
    for entry in table.entries:
        payload = entry.name.encode("ascii")
        out += struct.pack("<I", len(payload)) + payload
        out += struct.pack("<II", len(entry.dirs) + len(entry.files), 0)
        for name in entry.dirs:
            payload = name.encode("ascii")
            out += struct.pack("<I", len(payload)) + payload
        for name, replacement in entry.files:
            for text in (name, replacement):
                payload = text.encode("ascii")
                out += struct.pack("<I", len(payload)) + payload
    return bytes(out)


# ------------------------------------------------------------ per car .link
def parse_text(text: str) -> dict:
    """Parse a plain text ``.link`` file into ``{"dirs": [...], "files": [...]}``.

    The syntax is one directive per line, ``#`` starts a comment::

        dir:<modelname>                        replace the model name in a path
        file:<filename>:<replacement>          swap one file

    Only ``2014_maserati_granturismo_r3`` ships one, and it is a single ``dir:``
    line; the rest of the grammar comes from the comments inside that file.
    """
    dirs: list[str] = []
    files: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("dir:"):
            dirs.append(line[4:].strip())
        elif line.startswith("file:"):
            body = line[5:]
            if ":" not in body:
                raise LinkError(f"file directive needs a replacement: {line!r}")
            name, replacement = body.split(":", 1)
            files.append((name.strip(), replacement.strip()))
        else:
            raise LinkError(f"unknown directive: {line!r}")
    return {"dirs": dirs, "files": files}


def read_text_file(path: str) -> dict:
    """Read a plain text ``.link`` file.  Empty result when it is missing."""
    if not os.path.isfile(path):
        return {"dirs": [], "files": []}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return parse_text(fh.read())


# --------------------------------------------------------------- resolution
def has_geometry(depot: str, name: str) -> bool:
    """Does ``vehicles/<name>/`` hold at least one ``.m3g``?"""
    folder = os.path.join(depot, "vehicles", name)
    try:
        return any(f.endswith(".m3g") for f in os.listdir(folder))
    except OSError:
        return False


def resolve(depot: str, name: str, *, table: LinkTable | None = None,
            appearance_of=None) -> tuple[str, list[str]]:
    """Find the folder that actually holds ``name``'s geometry.

    Returns ``(model_folder, chain)`` where ``chain`` lists the names tried
    before the hit, so the caller can show "uses X's body (2 hops)".

    ``appearance_of`` is an optional ``name -> appearance record name`` callable
    used as the last resort before giving up; pass a closure over the spec
    table when you have one.  Without it, a car that has neither its own folder
    nor a table entry resolves to ``("", chain)``.
    """
    if table is None:
        try:
            table = load(depot)
        except LinkError:
            table = LinkTable(LINK_VERSION, [], 0)

    chain: list[str] = []
    current = name
    seen: set[str] = set()
    for _ in range(MAX_HOPS):
        if not current or current in seen:
            break
        seen.add(current)
        if has_geometry(depot, current):
            return current, chain
        chain.append(current)
        nxt = table.target(current)
        if not nxt and appearance_of is not None:
            nxt = appearance_of(current) or ""
        if not nxt or nxt == current:
            break
        current = nxt
    return "", chain


def resolve_all(depot: str, names, *, table: LinkTable | None = None,
                appearance_of=None) -> dict[str, tuple[str, list[str]]]:
    """Resolve many names at once, loading the table only once."""
    if table is None:
        try:
            table = load(depot)
        except LinkError:
            table = LinkTable(LINK_VERSION, [], 0)
    return {n: resolve(depot, n, table=table, appearance_of=appearance_of)
            for n in names}


def selftest(depot: str) -> int:
    """Parse, round trip and resolve every car; print a one line verdict."""
    table = load(depot)
    if build(table) != nct.read(os.path.join(depot, LINK_TABLE)):
        print("link selftest: rebuild does not match the decrypted table")
        return 1
    print(f"link selftest: {table.summary()}")
    return 0
