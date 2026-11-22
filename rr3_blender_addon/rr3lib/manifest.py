"""The asset manifests: what the engine checks before it will load anything.

The game does not just read files from disk - it compares every file against a
manifest and downloads/aborts when something is missing or has the wrong size.
Adding a car therefore means touching three text files:

``asset_list_base.txtCache.txt``
    The master registry: a 13 byte header then one ``/path<TAB>md5`` line per
    file in the whole depot (47,090 lines).  Sorted by path bytes.

``apk/res/asset_list_vehicle_data.txt``
    Sizes and md5 for the files under ``vehicles/data``.  Not alphabetical: the
    first 525 lines follow car id, the rest are other assets, so a new spec must
    be inserted where its id belongs rather than appended.

``apk/res/asset_list_vehicle_<car>.txt``
    Per car: ``path<TAB>md5<TAB>packed<TAB>raw`` for every file in that car's
    folder.  A new car needs one of these files, named after the car.

The header of the registry is ``[u32 0xA4F6F39D][u32 4][u32 7469][LF]``; 7469 is
a format version.  Keep it byte for byte.
"""

from __future__ import annotations

import bisect
import glob
import hashlib
import os
import struct

REGISTRY = "asset_list_base.txtCache.txt"
REGISTRY_HEADER_LEN = 13
VEHICLE_DATA_LIST = "apk/res/asset_list_vehicle_data.txt"
VEHICLE_LIST_DIR = "apk/res"


class ManifestError(Exception):
    pass


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------- registry
class Registry:
    """``asset_list_base.txtCache.txt``: path -> md5 for the whole depot."""

    def __init__(self, header: bytes, entries: dict[str, str]):
        self.header = header
        self.entries = entries

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, path: str) -> str | None:
        return self.entries.get(path)

    def set(self, path: str, md5: str) -> bool:
        if self.entries.get(path) == md5:
            return False
        self.entries[path] = md5
        return True

    def set_file(self, path: str, local: str) -> bool:
        return self.set(path, md5_file(local))

    def remove(self, path: str) -> bool:
        return self.entries.pop(path, None) is not None

    def to_bytes(self) -> bytes:
        lines = [f"{p}\t{m}" for p, m in sorted(self.entries.items())]
        return self.header + ("\n".join(lines) + "\n").encode("utf-8")

    def summary(self) -> str:
        return f"registry: {len(self.entries)} files, {len(self.header)} byte header"


def parse_registry(data: bytes) -> Registry:
    head = data[:REGISTRY_HEADER_LEN]
    body = data[REGISTRY_HEADER_LEN:].decode("utf-8")
    entries = {}
    for line in body.split("\n"):
        if not line:
            continue
        if "\t" not in line:
            raise ManifestError(f"bad registry line: {line[:60]!r}")
        p, m = line.rsplit("\t", 1)
        entries[p] = m
    return Registry(head, entries)


def load_registry(depot: str) -> Registry:
    return parse_registry(open(os.path.join(depot, REGISTRY), "rb").read())


def save_registry(r: Registry, path: str) -> int:
    blob = r.to_bytes()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)


# ------------------------------------------------------- per car manifest
def read_car_manifest(path: str) -> list[tuple[str, str, int, int]]:
    """``[(path, md5, packed, raw), ...]`` from an ``asset_list_vehicle_*``."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 4:
                raise ManifestError(f"bad manifest line: {line[:60]!r}")
            p, m, packed, raw = parts
            rows.append((p, m, int(packed), int(raw)))
    return rows


def write_car_manifest(rows, path: str) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for p, m, packed, raw in rows:
            fh.write(f"{p}\t{m}\t{packed}\t{raw}\n")
    return len(rows)


def rename_car_manifest(rows, old: str, new: str,
                        extra: list[str] | None = None,
                        extra_prefix: str = "/vehicles/") -> list[tuple]:
    """Rewrite a donor's manifest for a new car name.

    Files copied byte for byte keep their md5 and sizes; ``extra`` files (the
    ``.banim`` / ``.xml`` we author ourselves) are not in the donor list, so
    they are appended with their real md5 and size.  Both are stored, not
    compressed, so ``packed == raw``.
    """
    out = []
    for p, m, packed, raw in rows:
        out.append((p.replace(old, new), m, packed, raw))
    for f in extra or []:
        name = os.path.basename(f)
        if old and old in name:
            name = name.replace(old, new, 1)
        blob = open(f, "rb").read()
        out.append((f"{extra_prefix}{new}/{name}", hashlib.md5(blob).hexdigest(),
                    len(blob), len(blob)))
    return out


# ----------------------------------------------------- vehicle data manifest
class DataList:
    """``asset_list_vehicle_data.txt``: path, md5, packed, raw per data file."""

    def __init__(self, rows: list[tuple[str, str, int, int]]):
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def paths(self) -> list[str]:
        return [r[0] for r in self.rows]

    def update(self, path: str, md5: str, packed: int, raw: int) -> bool:
        for i, (p, m, _pk, _r) in enumerate(self.rows):
            if p == path:
                if m == md5 and _pk == packed and _r == raw:
                    return False
                self.rows[i] = (path, md5, packed, raw)
                return True
        raise ManifestError(f"{path} is not in the vehicle data list")

    def update_file(self, path: str, local: str) -> bool:
        n = os.path.getsize(local)
        return self.update(path, md5_file(local), n, n)

    def insert(self, path: str, md5: str, packed: int, raw: int) -> int:
        """Insert keeping the file's own ordering (ids first, then the rest)."""
        keys = self.paths()
        if path in keys:
            raise ManifestError(f"{path} is already listed")
        if keys != sorted(keys):
            raise ManifestError("vehicle data list is not sorted by path")
        pos = bisect.bisect_left(keys, path)
        self.rows.insert(pos, (path, md5, packed, raw))
        return pos

    def remove(self, path: str) -> int:
        keys = self.paths()
        i = keys.index(path)
        self.rows.pop(i)
        return i

    def to_bytes(self) -> bytes:
        return ("\n".join(f"{p}\t{m}\t{pk}\t{r}"
                          for p, m, pk, r in self.rows) + "\n").encode("utf-8")

    def summary(self) -> str:
        return f"vehicle data list: {len(self.rows)} rows"


def parse_data_list(data: bytes) -> DataList:
    rows = []
    for line in data.decode("utf-8").split("\n"):
        if not line:
            continue
        p, m, packed, raw = line.split("\t")
        rows.append((p, m, int(packed), int(raw)))
    return DataList(rows)


def load_data_list(pkg: str) -> DataList:
    """``pkg`` is the ``files`` folder, i.e. the parent of ``.depot``."""
    return parse_data_list(open(os.path.join(pkg, *VEHICLE_DATA_LIST.split("/")),
                                "rb").read())


def save_data_list(dl: DataList, path: str) -> int:
    blob = dl.to_bytes()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)


# --------------------------------------------------- the other asset lists
#
# ``asset_list_base.txtCache.txt`` is the registry and is keyed differently, so
# it is not one of these.  Everything else under ``apk/res`` that starts with
# ``asset_list`` is a list of ``path<TAB>md5<TAB>packed<TAB>raw`` rows, and
# between them the 1,236 of them claim every path in the depot exactly once -
# no path appears in two lists.  That makes "which list owns this file" a lookup
# rather than a guess, which is what :func:`owner_of` answers.
ASSET_DIR = "apk/res"
LIST_GLOB = "asset_list*.txt"

#: The four GPU families a texture is written for, in the order the game groups
#: them.  A texture gets one row per family and each family is a contiguous run
#: sorted by path.  That single rule reproduces 1,227 of the 1,233 shipped lists
#: byte for byte; the six that differ were appended to after the fact and keep a
#: second run of an earlier family at the end (see :func:`insert_row`).
FAMILIES = (".atc.dds.z", ".dxt.dds.z", ".etc.dds.z", ".ptc.pvr.z")


def family_of(path: str) -> int:
    """1..4 for a texture row, 0 for everything else (the "no family" run)."""
    for i, suffix in enumerate(FAMILIES):
        if suffix in path:
            return i + 1
    return 0


def runs(rows) -> list[tuple[int, int, int]]:
    """``[(family, first row, one past last row)]`` for a list's own layout."""
    out: list[tuple[int, int, int]] = []
    for i, row in enumerate(rows):
        f = family_of(row[0])
        if out and out[-1][0] == f:
            out[-1] = (f, out[-1][1], i + 1)
        else:
            out.append((f, i, i + 1))
    return out


def insert_row(rows, row) -> int:
    """Put one row where the game's own ordering would put it; returns the index.

    A new ``.dxt.dds.z`` belongs inside the list's ``dxt`` run, at its sorted
    place there - not at the end of the file, which is what appending does and
    what leaves a list with a run of the wrong family at the bottom.  A family
    the list has never had goes after the last run of a lower family.
    """
    f = family_of(row[0])
    found = runs(rows)
    same = [r for r in found if r[0] == f]
    if same:
        first, last = same[0][1], same[0][2]
        keys = [r[0] for r in rows[first:last]]
        pos = first + bisect.bisect_left(keys, row[0])
        rows.insert(pos, row)
        return pos
    lower = [r for r in found if r[0] < f]
    pos = lower[-1][2] if lower else 0
    rows.insert(pos, row)
    return pos


class AssetList:
    """One ``asset_list*.txt``: path, md5, packed, raw per row."""

    def __init__(self, leaf: str, rows: list[tuple[str, str, int, int]]):
        self.leaf = leaf
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def paths(self) -> list[str]:
        return [r[0] for r in self.rows]

    def get(self, path: str):
        for row in self.rows:
            if row[0] == path:
                return row
        return None

    def update(self, path: str, md5: str, packed: int, raw: int) -> bool:
        for i, row in enumerate(self.rows):
            if row[0] == path:
                if row[1:] == (md5, packed, raw):
                    return False
                self.rows[i] = (path, md5, packed, raw)
                return True
        raise ManifestError(f"{path} is not in {self.leaf}")

    def insert(self, path: str, md5: str, packed: int, raw: int) -> int:
        if self.get(path) is not None:
            raise ManifestError(f"{path} is already listed in {self.leaf}")
        return insert_row(self.rows, (path, md5, packed, raw))

    def remove(self, path: str) -> int:
        keys = self.paths()
        i = keys.index(path)
        self.rows.pop(i)
        return i

    def to_bytes(self) -> bytes:
        return ("\n".join(f"{p}\t{m}\t{pk}\t{r}"
                          for p, m, pk, r in self.rows) + "\n").encode("utf-8")

    def summary(self) -> str:
        return f"{self.leaf}: {len(self.rows)} rows"


def asset_list_path(pkg: str, leaf: str) -> str:
    return os.path.join(pkg, *ASSET_DIR.split("/"), leaf)


def parse_asset_list(leaf: str, data: bytes) -> AssetList:
    rows = []
    for line in data.decode("utf-8").split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            raise ManifestError(f"bad {leaf} line: {line[:60]!r}")
        p, m, packed, raw = parts
        rows.append((p, m, int(packed), int(raw)))
    return AssetList(leaf, rows)


def load_asset_list(pkg: str, leaf: str) -> AssetList:
    path = asset_list_path(pkg, leaf)
    return parse_asset_list(leaf, open(path, "rb").read())


def save_asset_list(al: AssetList, path: str) -> int:
    blob = al.to_bytes()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)


class AssetIndex:
    """``path -> the one list that claims it``, for every list under apk/res."""

    def __init__(self, owners: dict[str, str], leaves: list[str],
                 folders: dict[str, dict[str, int]] | None = None):
        self.owners = owners
        self.leaves = leaves
        self.folders = folders or {}

    def __len__(self) -> int:
        return len(self.owners)

    def owner_of(self, path: str) -> str:
        return self.owners.get(path, "")

    def list_for(self, path: str) -> str:
        """Which list a file *should* be in, new files included.

        A file that is already claimed answers for itself.  A new one is filed
        where its neighbours are: the nearest parent folder that holds claimed
        files votes, and the commonest list among them wins.  That is how a new
        ``sprites_3.rgb.pvr.z`` lands in the same list as ``sprites_0``..``2``
        without a table of folder names to keep up to date.
        """
        hit = self.owners.get(path)
        if hit:
            return hit
        folder = path.rsplit("/", 1)[0]
        while folder:
            votes = self.folders.get(folder)
            if votes:
                return max(sorted(votes), key=lambda leaf: votes[leaf])
            folder = folder.rsplit("/", 1)[0] if "/" in folder else ""
        return ""

    def summary(self) -> str:
        return (f"{len(self.leaves)} asset lists, {len(self.owners)} paths "
                f"claimed, {len(self.folders)} folders")


def build_asset_index(pkg: str) -> AssetIndex:
    """Read every list once and record who claims what.

    0.3 s for 1,236 files and 114,307 paths, so callers may build it at startup
    rather than caching it to disk.  Two lists claiming one path would be a
    broken install and is reported instead of silently resolved.
    """
    folder = os.path.join(pkg, *ASSET_DIR.split("/"))
    owners: dict[str, str] = {}
    folders: dict[str, dict[str, int]] = {}
    leaves = []
    dupe = []
    for path in sorted(glob.glob(os.path.join(folder, LIST_GLOB))):
        leaf = os.path.basename(path)
        leaves.append(leaf)
        try:
            rows = parse_asset_list(leaf, open(path, "rb").read()).rows
        except (OSError, ManifestError, UnicodeDecodeError):
            continue
        for row in rows:
            if row[0] in owners:
                dupe.append((row[0], owners[row[0]], leaf))
            else:
                owners[row[0]] = leaf
                parent = row[0].rsplit("/", 1)[0]
                votes = folders.setdefault(parent, {})
                votes[leaf] = votes.get(leaf, 0) + 1
    if dupe:
        raise ManifestError(
            f"{len(dupe)} path(s) are claimed by two asset lists, e.g. "
            f"{dupe[0][0]} in {dupe[0][1]} and {dupe[0][2]}")
    return AssetIndex(owners, leaves, folders)


_INDEX_CACHE: dict[str, AssetIndex] = {}


def asset_index(pkg: str, *, refresh: bool = False) -> AssetIndex:
    """The index for one install, built once per process."""
    key = os.path.abspath(pkg)
    if refresh or key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = build_asset_index(pkg)
    return _INDEX_CACHE[key]


def owner_of(pkg: str, path: str, *, refresh: bool = False) -> str:
    """Which ``asset_list*.txt`` claims ``path``; ``""`` when none does."""
    return asset_index(pkg, refresh=refresh).owner_of(path)


def forget() -> None:
    """Drop the cached index (call after adding a whole new list file)."""
    _INDEX_CACHE.clear()


# ------------------------------------------------------------------ selftest
def selftest(pkg: str | None = None) -> int:
    pkg = pkg or os.environ.get("RR3_PKG", "")
    if not pkg:
        print("manifest selftest: no package folder (set RR3_PKG)")
        return 2
    depot = os.path.join(pkg, ".depot")
    bad = 0
    reg = load_registry(depot)
    raw = open(os.path.join(depot, REGISTRY), "rb").read()
    print(reg.summary())
    if reg.to_bytes() != raw:
        print("FAIL registry round trip")
        bad += 1
    dl = load_data_list(pkg)
    raw2 = open(os.path.join(pkg, *VEHICLE_DATA_LIST.split("/")), "rb").read()
    print(dl.summary())
    if dl.to_bytes() != raw2:
        print("FAIL data list round trip")
        bad += 1
    car = os.path.join(pkg, *VEHICLE_LIST_DIR.split("/"),
                       "asset_list_vehicle_2012_lexus_lfa.txt")
    rows = read_car_manifest(car)
    print(f"per car manifest: {len(rows)} rows")
    if [f"{p}\t{m}\t{pk}\t{r}" for p, m, pk, r in rows] != [
            ln for ln in open(car, encoding="utf-8").read().split("\n") if ln]:
        print("FAIL per car manifest round trip")
        bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
