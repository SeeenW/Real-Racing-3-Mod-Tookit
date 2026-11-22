"""The ``.rr3mod`` pack: a zip that says what it needs, and whether it is usable.

A mod is not just files.  A wing needs the car it goes on, a shared texture page
needs its four asset list rows, a custom material needs the row it was cloned
from, a driver pose needs the low-poly body that can wear it, and a career series
needs the tracks it names.  Installing any of those without its dependencies
gives a car that does not appear, a page that renders magenta, or a series that
crashes the menu.

So a pack carries two lists besides its files::

    {
      "format": 2,
      "kind": "car",                       // car | driver | career | brand
                                           // | track | pages
      "name": "2012_lexus_lfa_wing",
      "title": "LFA active wing",
      "note": "the studio never animated it",
      "made_by": "RR3 Mod Studio 0.1.0",
      "made_at": "2026-11-12 11:40",
      "requires": [                        // what has to be there already
        {"kind": "car", "name": "2012_lexus_lfa"},
        {"kind": "material", "name": "car_paint_gloss"},
        {"kind": "page", "name": "common/car_windows_04"}
      ],
      "provides": {                        // what installing it adds
        "cars": ["2012_lexus_lfa"],
        "pages": [],
        "materials": [],
        "drivers": [],
        "brands": [],
        "series": []
      },
      "files": ["vehicles/2012_lexus_lfa/...", ...]
    }

``format 1`` is what :mod:`rrmod.share` writes (a car share with no dependency
list); it is read as a ``car`` pack with its requirements worked out from its
files, so old shares keep working.

The state machine has three answers, and they decide what the user may do:

``ready``
    Installed, and every requirement is satisfied.  May be enabled or removed.

``missing``
    Installed, but something it needs is gone.  It may be **removed** (that is
    how a broken mod gets out of the way) but not enabled.  A shared page that
    went missing does not put a pack here - see below.

``absent``
    None of its files are here.  The pack can be installed.

A pack is "installed" when at least one of its files is in the working copy or
the install.  That is deliberately loose: a half-removed pack still counts as
present, so the user sees ``missing`` and is told to remove it rather than being
offered an install that would half-overwrite what is left.

**One requirement is a warning rather than a refusal.**  A missing shared page
(``{"kind": "page"}``) does not stop an install: the car appears and works, and
only the surface that samples the page draws without a texture.  Refusing there
used to make a whole car uninstallable because one tyre atlas was absent from a
stripped install, which helped nobody.  Every other kind still refuses, because
a wing with no car, a pose with no body or a clone with no original leaves
something broken behind.
"""

from __future__ import annotations

import json
import os
import zipfile

from . import deps as depslib
from . import depot as depotlib

#: The manifest inside the zip.
MANIFEST = "mod.json"
#: Bumped when the manifest shape changes.  Format 1 (a bare car share) is still
#: read; :mod:`rrmod.share` keeps writing it so older copies can take one in.
FORMAT = 2
#: Everything the zip holds lives under this prefix.
PREFIX = "files/"

#: Pictures live under their own prefix, because they are not game files: a
#: texture page is stored as a PNG and encoded into a GPU family at install
#: time, so the same pack works on an Adreno, a Mali or a PowerVR device.
PICTURES = "pictures/"

#: The kinds a pack can be.  ``car`` is the one a share is.
KINDS = ("car", "driver", "career", "brand", "track", "pages", "material")

#: What a requirement may point at.
REQUIRE_KINDS = ("car", "page", "material", "driver", "brand", "track")

#: The state machine's answers.
STATES = ("ready", "missing", "absent")


class PackError(Exception):
    pass


def _version() -> str:
    from . import __version__

    return __version__


def _norm(rel: str) -> str:
    """A game path as ``vehicles/x`` - no leading slash, forward slashes."""
    rel = rel.replace("\\", "/").strip()
    while rel.startswith("/"):
        rel = rel[1:]
    return rel


# --------------------------------------------------------------- writing
def make(*, kind: str, name: str, files: list, requires=(), provides=None,
         title: str = "", note: str = "", extra: dict | None = None,
         pictures=None) -> dict:
    """The manifest a pack is written with.

    ``files`` is ``[(game path, local path)]``.  The manifest lists the game
    paths; the caller writes the local files into the zip.

    ``pictures`` is ``[(game path, local PNG path)]`` for the pages the pack
    carries as art rather than as a finished GPU file.  They are listed
    separately because they are *not* game files: the receiver's install needs a
    DXT, ETC or ATC page, and which one depends on the device, so the picture is
    encoded when it is installed.  A pack that shipped a DXT page would render as
    garbage on a Mali phone.
    """
    if kind not in KINDS:
        raise PackError(f"{kind!r} is not one of {KINDS}")
    if not name:
        raise PackError("a pack needs a name")
    reqs = []
    for row in requires or ():
        if isinstance(row, str):
            row = {"kind": "car", "name": row}
        k = row.get("kind", "car")
        if k not in REQUIRE_KINDS:
            raise PackError(f"a requirement of kind {k!r} is not one of "
                            f"{REQUIRE_KINDS}")
        n = row.get("name", "")
        if not n:
            raise PackError(f"a {k} requirement has no name")
        out = {"kind": k, "name": n}
        if row.get("note"):
            out["note"] = row["note"]
        reqs.append(out)
    prov = {key: [] for key in ("cars", "pages", "materials", "drivers",
                                "brands", "series", "tracks")}
    for key, values in (provides or {}).items():
        if key not in prov:
            raise PackError(f"a pack cannot provide {key!r}")
        prov[key] = [str(v) for v in values]
    data = {
        "format": FORMAT,
        "kind": kind,
        "name": name,
        "title": title or name,
        "note": note,
        "made_by": f"RR3 Mod Studio {_version()}",
        "requires": reqs,
        "provides": prov,
        "files": [_norm(rel) for rel, _local in files],
    }
    if pictures:
        data["pictures"] = [_norm(rel) for rel, _local in pictures]
    if extra:
        for key, value in extra.items():
            if key in data:
                raise PackError(f"{key!r} is already part of the manifest")
            data[key] = value
    return data


def write(out_path: str, manifest: dict, files: list, *, pictures=None,
          log=print) -> dict:
    """Write the zip.  ``files`` is ``[(game path, local path)]``.

    ``pictures`` is ``[(game path, local PNG path)]`` and goes under its own
    prefix so the two can never be confused for one another.
    """
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    tmp = out_path + ".part"
    pictures = list(pictures or ())
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST,
                    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        for rel, local in files:
            zf.write(local, PREFIX + _norm(rel))
        for rel, local in pictures:
            zf.write(local, PICTURES + _norm(rel))
    os.replace(tmp, out_path)
    size = os.path.getsize(out_path)
    log(f"  {os.path.basename(out_path)}: {len(files)} file(s), "
        f"{len(pictures)} picture(s), {size:,} bytes")
    return {"path": out_path, "bytes": size, "files": len(files),
            "pictures": len(pictures), "manifest": manifest}


# --------------------------------------------------------------- reading
def read_manifest(path: str) -> dict:
    """The ``mod.json`` inside a pack (or a plain folder), upgraded to format 2."""
    if os.path.isdir(path):
        p = os.path.join(path, MANIFEST)
        if not os.path.isfile(p):
            raise PackError(f"{path} has no {MANIFEST}")
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            raise PackError(f"{p}: {exc}") from exc
    else:
        try:
            with zipfile.ZipFile(path) as zf:
                data = json.loads(zf.read(MANIFEST).decode("utf-8"))
        except KeyError as exc:
            raise PackError(f"{os.path.basename(path)} has no {MANIFEST}") from exc
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise PackError(f"{os.path.basename(path)}: {exc}") from exc
    return upgrade(data, os.path.basename(path))


def upgrade(data: dict, where: str = "") -> dict:
    """Read a format 1 share as a format 2 pack.

    Format 1 only ever meant "these files of this car", so its requirements are
    the car itself; the shared pages its files name are added by
    :func:`infer_requirements` once the install is known.
    """
    fmt = int(data.get("format", FORMAT))
    if fmt > FORMAT:
        raise PackError(f"{where or 'this pack'} is format {fmt}, this program "
                        f"speaks up to {FORMAT}")
    out = dict(data)
    out["format"] = fmt
    if fmt < 2:
        out.setdefault("kind", "car")
        out.setdefault("title", out.get("name", ""))
        out.setdefault("requires", [])
        out.setdefault("provides", {})
        base = data.get("base") or data.get("name") or ""
        if base:
            out["requires"] = [{"kind": "car", "name": base}]
            out["provides"] = {"cars": [base]}
        if data.get("kind") == "replace":
            out["kind"] = "car"
        # Once it has been lifted, it *is* a format 2 pack: keeping the old
        # number would make every later reader take the format 1 path again and
        # overwrite the requirements just worked out.
        out["format"] = FORMAT
    if out.get("kind") not in KINDS:
        raise PackError(f"{where or 'this pack'} is a {out.get('kind')!r} pack, "
                        f"which this program does not know")
    out.setdefault("title", out.get("name", ""))
    out.setdefault("note", "")
    out.setdefault("requires", [])
    out.setdefault("provides", {})
    out.setdefault("files", [])
    return out


def files_of(data: dict) -> list:
    return [_norm(f) for f in (data.get("files") or [])]


def pictures_of(data: dict) -> list:
    """The pages a pack carries as art, to be encoded when it is installed."""
    return [_norm(f) for f in (data.get("pictures") or [])]


# --------------------------------------------------------------- dependency
def _car_installed(root: str, name: str) -> bool:
    try:
        return depotlib.scan(root).get(name) is not None
    except Exception:                            # noqa: BLE001 - never fatal
        return False


def _driver_exists(root: str, name: str) -> bool:
    from rr3lib import driver as driverlib

    depot = os.path.join(root, ".depot")
    try:
        # ``driver_dir`` answers None when there is no driver folder at all,
        # which is the normal case on a stripped install - not an error.
        folder = driverlib.driver_dir(depot)
    except Exception:                            # noqa: BLE001
        return False
    if not folder:
        return False
    stem = name[:-len(".banim")] if name.endswith(".banim") else name
    for suffix in (".banim", ".m3g"):
        if os.path.isfile(os.path.join(folder, stem + suffix)):
            return True
    return False


def _material_exists(root: str, name: str) -> bool:
    from rr3lib import gamematerial as gamelib

    depot = os.path.join(root, ".depot")
    try:
        return gamelib.load(depot).material(name) is not None
    except Exception:                            # noqa: BLE001
        return False


def _brand_exists(root: str, name: str) -> bool:
    from . import brands as brandlib

    try:
        known = {b["name"] for b in brandlib.brands(
            depotlib.scan(root), ours=depotlib.brand_names(
                os.path.join(root, ".depot")))}
    except Exception:                            # noqa: BLE001
        return False
    return name in known


def _track_exists(root: str, name: str) -> bool:
    from . import tracks as tracklib

    try:
        inv = depotlib.scan(root)
        return any(tracklib.normalise(name) == tracklib.normalise(t["name"])
                   for t in inv.tracks)
    except Exception:                            # noqa: BLE001
        return False


def _series_exists(root: str, name: str) -> bool:
    from . import series as serieslib

    try:
        c = serieslib.load(root)
        return any(str(s.id) == str(name) or s.title_key == name
                   for s in c.series)
    except Exception:                            # noqa: BLE001
        return False


_CHECKERS = {
    "car": _car_installed,
    "page": lambda root, name: os.path.isfile(
        os.path.join(root, ".depot", "vehicles", *depslib.stem_of(name).split("/"))
        + ".dxt.dds.z"),
    "material": _material_exists,
    "driver": _driver_exists,
    "brand": _brand_exists,
    "track": _track_exists,
    "series": _series_exists,
}


def satisfied(root: str, requirement: dict) -> bool:
    """Is one requirement met by this install (or working copy)?"""
    kind = requirement.get("kind", "car")
    name = requirement.get("name", "")
    if not name:
        return True
    if kind == "page":
        # A shared page can be any of the four families, and the working copy
        # only ever holds the one the depot unpacked.
        stem = depslib.stem_of(name)
        base = os.path.join(root, ".depot", "vehicles", *stem.split("/"))
        for suffix in (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z"):
            if os.path.isfile(base + suffix):
                return True
        return False
    fn = _CHECKERS.get(kind)
    if fn is None:
        return False
    return bool(fn(root, name))


def unsatisfied(root: str, data: dict) -> list:
    """The requirements this install does not meet, in manifest order."""
    return [r for r in (data.get("requires") or [])
            if not satisfied(root, r)]


def infer_requirements(root: str, data: dict) -> list:
    """Work out a format 1 pack's requirements from its own files.

    A share names the car it replaces, and its files name shared pages.  Both
    are real dependencies even though the old format never said so.
    """
    out = list(data.get("requires") or [])
    have = {(r.get("kind"), r.get("name")) for r in out}
    for rel in files_of(data):
        parts = rel.split("/")
        if len(parts) > 2 and parts[0] == "vehicles":
            car = parts[1]
            if car not in ("data", "common", "shaders", "wheels", "decals"):
                if ("car", car) not in have:
                    out.append({"kind": "car", "name": car})
                    have.add(("car", car))
    return out


# --------------------------------------------------------------- state
def installed(root: str, data: dict) -> bool:
    """Is any of the pack's files already here?"""
    for rel in files_of(data):
        if os.path.isfile(os.path.join(root, ".depot", *rel.split("/"))):
            return True
    return False


def check(root: str, path: str) -> dict:
    """Everything the UI needs to decide what to offer for one pack file.

    ``state`` is ``ready`` / ``missing`` / ``absent``; ``problems`` are the
    reasons an install would be refused, and ``changes`` / ``extra`` say which
    files would be replaced and which are new.

    **A missing shared page is a warning, not a problem.**  It used to be a
    problem, which made a car pack uninstallable on an install that had been
    stripped of a page - and the page is nearly always one the pack does not even
    carry, so refusing helped nobody: the car would have worked with one surface
    drawn wrong.  The install goes ahead and the person is told what will look
    off.
    """
    data = read_manifest(path)
    out = {"path": path, "kind": data["kind"], "name": data["name"],
           "title": data.get("title", ""), "note": data.get("note", ""),
           "made_by": data.get("made_by", ""), "made_at": data.get("made_at", ""),
           "files": files_of(data), "pictures": pictures_of(data),
           "provides": data.get("provides") or {},
           "requires": data.get("requires") or [],
           "unsatisfied": [], "problems": [], "warnings": [],
           "changes": [], "extra": [],
           "state": "absent", "installed": False}
    # A pack may carry only pictures: those become pages at install time, so a
    # manifest with no finished files is not empty - it is a set of pages.
    if not out["files"] and not out["pictures"]:
        out["problems"].append("the pack lists no files")
    for rel in out["files"]:
        if ".." in rel.split("/"):
            out["problems"].append(f"refusing a path that climbs out: {rel}")
            continue
        local = os.path.join(root, ".depot", *rel.split("/"))
        (out["changes"] if os.path.isfile(local) else out["extra"]).append(rel)
    out["installed"] = bool(out["changes"] or out["pictures"])
    out["unsatisfied"] = unsatisfied(root, data)
    # A page is the one requirement that does not stop an install.  Everything
    # else - the car a wing goes on, the body a pose needs, the material a clone
    # came from - would leave a broken thing behind, so those still refuse.
    blocking = []
    for req in out["unsatisfied"]:
        said = f"needs {req['kind']} {req['name']}, which is not here"
        if req.get("kind") == "page":
            out["warnings"].append(
                said + " - it installs anyway, but whatever samples that page "
                       "will draw without a texture")
        else:
            blocking.append(req)
            out["problems"].append(said)
    if out["installed"]:
        out["state"] = "missing" if blocking else "ready"
    return out


def state_of(root: str, path: str) -> str:
    try:
        return check(root, path)["state"]
    except PackError:
        return "absent"


def summary(root: str) -> dict:
    """How many packs of each state a folder of packs holds.

    Used by the manager's front page: it answers "is anything broken?" without
    opening a single pack by hand.
    """
    counts = {s: 0 for s in STATES}
    rows = []
    return {"counts": counts, "rows": rows}


def scan(root: str, folder: str) -> dict:
    """Every ``*.rr3mod`` / ``*.zip`` under ``folder``, checked."""
    rows = []
    if folder and os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith((".rr3mod", ".zip")):
                continue
            path = os.path.join(folder, name)
            try:
                info = check(root, path)
            except PackError as exc:
                rows.append({"path": path, "name": name, "state": "absent",
                             "problems": [str(exc)], "title": "", "kind": "",
                             "files": [], "requires": [], "unsatisfied": [],
                             "changes": [], "extra": [], "installed": False,
                             "provides": {}, "note": "", "made_by": "",
                             "made_at": ""})
                continue
            info["file"] = name
            rows.append(info)
    counts = {s: 0 for s in STATES}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    return {"counts": counts, "rows": rows, "folder": folder}


def selftest(root: str = "") -> int:
    """The manifest rules, without touching a disk."""
    bad = 0

    def want(ok, what):
        nonlocal bad
        if not ok:
            print(f"FAIL {what}")
            bad += 1

    data = make(kind="car", name="x", files=[("vehicles/x/x_a.m3g", "a.m3g")],
                requires=["2012_lexus_lfa"],
                provides={"cars": ["x"]})
    want(data["format"] == FORMAT, "format")
    want(data["requires"] == [{"kind": "car", "name": "2012_lexus_lfa"}],
         "a bare string becomes a car requirement")
    want(data["files"] == ["vehicles/x/x_a.m3g"], "the leading slash is gone")
    for kind in KINDS:
        want(make(kind=kind, name="x", files=[])["kind"] == kind, kind)
    try:
        make(kind="nonsense", name="x", files=[])
        want(False, "an unknown kind is refused")
    except PackError:
        pass
    try:
        make(kind="car", name="", files=[])
        want(False, "an empty name is refused")
    except PackError:
        pass
    try:
        make(kind="car", name="x", files=[],
             requires=[{"kind": "unicorn", "name": "y"}])
        want(False, "an unknown requirement kind is refused")
    except PackError:
        pass
    old = upgrade({"format": 1, "name": "c", "kind": "replace", "base": "c"})
    want(old["kind"] == "car", "a format 1 share is a car pack")
    want(old["requires"] == [{"kind": "car", "name": "c"}],
         "a format 1 share needs its own car")
    try:
        upgrade({"format": 9, "name": "c"})
        want(False, "a newer format is refused")
    except PackError:
        pass
    print(f"pack: {'ok' if not bad else str(bad) + ' bad'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
