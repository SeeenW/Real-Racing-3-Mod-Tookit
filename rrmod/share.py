"""Handing a modded car to someone else, and taking one in.

A car is not one file.  Changing a car touches its folder (up to eleven LODs,
the shared model, the interior, the paint atlases under ``livery/``), its spec
under ``vehicles/data``, its livery table under ``vehicles/data/liveries``, and
the rows in three manifests that tell the engine what to load.  Copying the
folder alone gives the other person a car that either does not appear or comes
back as the stock one.

So a share is a zip with two parts::

    mod.json          what this is, which car it goes on, which ids it wants
    files/<game path> the files themselves, laid out exactly as the game has
                      them (``vehicles/<car>/...``, ``vehicles/data/...``)

``mod.json`` is deliberately the same shape as :mod:`rrmod.modpack`'s
``car.json`` where the two overlap, because the Blender add-on already writes
that and there is no reason for two vocabularies::

    {
      "format": 1,
      "name": "2012_lexus_lfa",
      "kind": "replace",                  // a share is always "replace"
      "car_id": 88,                       // the id it was made against
      "appearance_id": 25,
      "base": "2012_lexus_lfa",           // must exist on the receiving side
      "note": "carbon wing, painted",
      "made_by": "RR3 Mod Manager 0.1.0",
      "files": ["vehicles/2012_lexus_lfa/...", ...]
    }

Two rules make an import safe, and both are enforced rather than warned about:

* the base car has to be installed, because a share only ever replaces files
  that already exist there - it never invents a car;
* the ids in the zip have to match what the receiver's own spec says.  A car id
  is global: pasting a share made against id 88 onto a car that has since
  become id 611 would write the wrong spec and the wrong livery table.

Importing copies files with the usual per-edit backup, then re-hashes the rows
in the per-car manifest, the registry and the vehicle data list.  Undo covers
it like any other edit.

A **backup** is the same zip with a different intent, and the difference is not
cosmetic - it is what the buttons on the Cars page mean now that edits are
written straight into the game folder:

* :func:`backup_car` writes one car out *before* it is worked on, and records
  the parameters that are not files (the mods record: ids, status, display
  name), because those are exactly what a bad build changes and what no file in
  the car's folder can tell you afterwards.
* :func:`rollback` puts a backup back.  It is deliberately **lenient**: the
  import path refuses a zip whose base car is missing or whose ids have moved,
  and both of those are exactly the situation a rollback exists for - a build
  that renamed the spec, or a car that no longer appears at all.  A rollback
  writes the files it holds, re-books the manifest rows it can, and says what it
  could not do rather than refusing to start.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import zipfile

from . import depot as depotlib
from . import edit as editlib

#: The zip's own manifest.
MANIFEST = "mod.json"
FORMAT = 1
#: Everything the zip holds lives under this prefix.
PREFIX = "files/"
#: ``kind`` of a zip written by :func:`backup_car`.  A share is ``"replace"``.
BACKUP_KIND = "backup"


class ShareError(Exception):
    pass


def _version() -> str:
    from . import __version__

    return __version__


# ------------------------------------------------------------------ export
def car_files(root: str, name: str) -> list:
    """``[(game path, local path)]`` for everything a car owns.

    That is its folder (walked, so ``livery/`` comes along) plus its spec and
    its livery table.  The three manifests are not included: they are merged on
    the receiving side, because the receiver's copies have their own rows.
    """
    depot = os.path.join(root, ".depot")
    out = []
    folder = os.path.join(depot, "vehicles", name)
    if os.path.isdir(folder):
        for dirpath, _dirs, files in os.walk(folder):
            sub = os.path.relpath(dirpath, folder).replace(os.sep, "/")
            for f in sorted(files):
                local = os.path.join(dirpath, f)
                rel = (f"vehicles/{name}/{f}" if sub == "."
                       else f"vehicles/{name}/{sub}/{f}")
                out.append((rel, local))
    inv = depotlib.scan(root)
    entry = inv.get(name)
    if entry is not None:
        spec = os.path.join(depot, "vehicles", "data",
                            f"{entry.spec_stem}.bin.nct")
        if os.path.isfile(spec):
            out.append((f"vehicles/data/{entry.spec_stem}.bin.nct", spec))
    livery = os.path.join(depot, "vehicles", "data", "liveries",
                          f"{name}.liveries.bin.nct")
    if os.path.isfile(livery):
        out.append((f"vehicles/data/liveries/{name}.liveries.bin.nct", livery))
    return out


def describe(root: str, name: str) -> dict:
    """What a share of this car would contain, without writing anything."""
    inv = depotlib.scan(root)
    entry = inv.get(name)
    if entry is None:
        raise ShareError(f"{name} is not installed")
    files = car_files(root, name)
    total = sum(os.path.getsize(p) for _r, p in files)
    return {
        "name": name,
        "car_id": entry.car_id,
        "appearance_id": entry.appearance_id,
        "files": files,
        "count": len(files),
        "bytes": total,
        "status": entry.status,
    }


def export_car(root: str, name: str, out_path: str, *, note: str = "",
               log=print) -> dict:
    """Write a share zip for one car; returns a summary."""
    info = describe(root, name)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    manifest = {
        "format": FORMAT,
        "name": name,
        "kind": "replace",
        "car_id": info["car_id"],
        "appearance_id": info["appearance_id"],
        "base": name,
        "note": note,
        "made_by": f"RR3 Mod Manager {_version()}",
        "made_at": time.strftime("%Y-%m-%d %H:%M"),
        "files": [rel for rel, _p in info["files"]],
    }
    tmp = out_path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST,
                    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        for rel, local in info["files"]:
            zf.write(local, PREFIX + rel)
    os.replace(tmp, out_path)
    log(f"  {os.path.basename(out_path)}: {info['count']} file(s), "
        f"{os.path.getsize(out_path):,} bytes")
    return {"path": out_path, "bytes": os.path.getsize(out_path),
            "files": info["count"], "name": name, "manifest": manifest}


# ------------------------------------------------------------------ inspect
def read_manifest(path: str) -> dict:
    """The ``mod.json`` inside a share zip (or a plain folder)."""
    if os.path.isdir(path):
        p = os.path.join(path, MANIFEST)
        if not os.path.isfile(p):
            raise ShareError(f"{path} has no {MANIFEST}")
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        try:
            with zipfile.ZipFile(path) as zf:
                data = json.loads(zf.read(MANIFEST).decode("utf-8"))
        except KeyError as exc:
            raise ShareError(f"{os.path.basename(path)} has no {MANIFEST}") from exc
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise ShareError(f"{os.path.basename(path)}: {exc}") from exc
    fmt = data.get("format", FORMAT)
    if fmt != FORMAT:
        raise ShareError(f"share format {fmt}, this program speaks {FORMAT}")
    if data.get("kind", "replace") != "replace":
        raise ShareError(
            f"{os.path.basename(path)} is a '{data.get('kind')}' pack, not a share")
    return data


def inspect(root: str, path: str) -> dict:
    """Check a share against this install; returns what would happen.

    ``problems`` empty means the import can go ahead.  ``changes`` lists the
    files that would be replaced and ``extra`` the ones that do not exist yet.
    """
    data = read_manifest(path)
    name = data.get("name") or ""
    base = data.get("base") or name
    out = {"path": path, "name": name, "base": base, "note": data.get("note", ""),
           "made_by": data.get("made_by", ""), "made_at": data.get("made_at", ""),
           "files": [], "changes": [], "extra": [], "problems": []}
    if not name:
        out["problems"].append("the share does not name a car")
        return out
    inv = depotlib.scan(root)
    entry = inv.get(base)
    if entry is None:
        out["problems"].append(
            f"this install has no {base} - a share only replaces files of a car "
            f"that is already there")
        return out
    want_id = data.get("car_id")
    if want_id is not None and int(want_id) != entry.car_id:
        out["problems"].append(
            f"the share was made for car id {want_id} but {base} is id "
            f"{entry.car_id} here; the spec and the livery table would land "
            f"on the wrong car")
    want_app = data.get("appearance_id")
    if want_app is not None and int(want_app) != entry.appearance_id:
        out["problems"].append(
            f"the share expects appearance record {want_app} but {base} uses "
            f"{entry.appearance_id} here")

    listed = data.get("files") or []
    out["files"] = list(listed)
    if not listed:
        out["problems"].append("the share lists no files")
    for rel in listed:
        if ".." in rel.replace("\\", "/").split("/"):
            out["problems"].append(f"refusing a path that climbs out: {rel}")
            continue
        local = os.path.join(root, ".depot", *rel.split("/"))
        if os.path.isfile(local):
            out["changes"].append(rel)
        else:
            out["extra"].append(rel)
    return out


# ------------------------------------------------------------------- import
def import_car(root: str, path: str, *, log=print) -> dict:
    """Copy a share into this install and re-hash its manifest rows."""
    info = inspect(root, path)
    if info["problems"]:
        raise ShareError("; ".join(info["problems"]))
    name = info["base"]
    editlib._begin()
    written = []

    def land(rel: str, source: str) -> None:
        local = os.path.join(root, ".depot", *rel.split("/"))
        os.makedirs(os.path.dirname(local), exist_ok=True)
        if os.path.isfile(local):
            editlib._backup(root, local)
        shutil.copyfile(source, local)
        written.append((rel, local))

    if os.path.isdir(path):
        for rel in info["files"]:
            land(rel, os.path.join(path, PREFIX.replace("/", os.sep), *rel.split("/")))
    else:
        with zipfile.ZipFile(path) as zf:
            tmp = os.path.join(root, editlib.BACKUP_DIR, "_share")
            os.makedirs(tmp, exist_ok=True)
            try:
                for rel in info["files"]:
                    member = PREFIX + rel
                    try:
                        zf.extract(member, tmp)
                    except KeyError:
                        raise ShareError(
                            f"{os.path.basename(path)} is missing {rel}") from None
                    land(rel, os.path.join(tmp, *member.split("/")))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    for rel, local in written:
        game_path = "/" + rel
        editlib.sync_file(root, name=name, rel_path=game_path, local=local,
                          create=True)
    log(f"  {name}: {len(written)} file(s) written")
    return {"name": name, "written": len(written), "files": written,
            "note": info["note"]}


# ====================================================================== backup
# A backup is a share that is meant to come back here, not to travel.  The
# difference is in the parameters (a share carries the ids it was made with and
# refuses to land anywhere else; a backup carries the whole mods record so the
# install can be told what this car *was*) and in the rollback, which is
# forgiving on purpose.
def params_of(root: str, name: str, *, entry=None) -> dict:
    """The parameters of one car that are not files.

    Two sources, and both are needed.  ``rr3mods.json`` holds what the program
    decided (is this car a mod, what is its display name); the inventory holds
    what the files say *right now* (its ids, its spec stem).  A backup records
    both, because the failure a rollback has to survive is precisely the one
    where the two stopped agreeing.
    """
    depot = os.path.join(root, ".depot")
    out = {"status": "", "mods_record": {}}
    try:
        data = depotlib.load_mods(depot)
    except Exception:                            # noqa: BLE001 - never fail a backup
        data = {}
    for side in ("mods", "vanilla"):
        record = (data.get(side) or {}).get(name)
        if isinstance(record, dict) and record:
            out["status"] = side
            out["mods_record"] = record
            break
    if entry is None:
        try:
            entry = depotlib.scan(root).get(name)
        except Exception:                        # noqa: BLE001
            entry = None
    if entry is not None:
        out.setdefault("car_id", entry.car_id)
        out.setdefault("appearance_id", entry.appearance_id)
        out.setdefault("spec_stem", entry.spec_stem)
        out.setdefault("status", out["status"] or entry.status)
    return out


def backup_car(root: str, name: str, out_path: str, *, note: str = "",
               log=print) -> dict:
    """Write everything one car is into a zip, so it can be put back later.

    "Everything" is the car's folder (every LOD, the shared model, the interior,
    the paint atlases), its spec, its livery table, **and** the parameters that
    live in ``rr3mods.json`` - the ids, the status, the display name.  The three
    manifests are still left out: they are re-booked on the way back in, because
    the install's copies have rows for cars this backup knows nothing about.
    """
    info = describe(root, name)
    params = params_of(root, name)
    manifest = {
        "format": FORMAT,
        "kind": BACKUP_KIND,
        "name": name,
        "base": name,
        "car_id": info["car_id"],
        "appearance_id": info["appearance_id"],
        "note": note,
        "made_by": f"RR3 Mod Manager {_version()}",
        "made_at": time.strftime("%Y-%m-%d %H:%M"),
        "params": params,
        "files": [rel for rel, _p in info["files"]],
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = out_path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST,
                    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        for rel, local in info["files"]:
            zf.write(local, PREFIX + rel)
    os.replace(tmp, out_path)
    log(f"  {os.path.basename(out_path)}: {info['count']} file(s), "
        f"{os.path.getsize(out_path):,} bytes")
    return {"path": out_path, "bytes": os.path.getsize(out_path),
            "files": info["count"], "name": name, "manifest": manifest}


def read_backup(path: str) -> dict:
    """The ``mod.json`` of a backup, checked only for shape.

    A share is checked for *compatibility* here; a backup is not, because the
    reason to roll one back is usually that the install no longer agrees with
    it.  What is still refused is a zip that is not a backup at all, and one
    whose file list climbs out of the folder.
    """
    if os.path.isdir(path):
        p = os.path.join(path, MANIFEST)
        if not os.path.isfile(p):
            raise ShareError(f"{path} has no {MANIFEST}")
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        try:
            with zipfile.ZipFile(path) as zf:
                data = json.loads(zf.read(MANIFEST).decode("utf-8"))
        except KeyError as exc:
            raise ShareError(f"{os.path.basename(path)} has no {MANIFEST}") from exc
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise ShareError(f"{os.path.basename(path)}: {exc}") from exc
    fmt = data.get("format", FORMAT)
    if fmt != FORMAT:
        raise ShareError(f"backup format {fmt}, this program speaks {FORMAT}")
    kind = data.get("kind", "")
    if kind not in (BACKUP_KIND, "replace"):
        raise ShareError(
            f"{os.path.basename(path)} is a '{kind}' pack, not a car backup")
    return data


def inspect_backup(root: str, path: str) -> dict:
    """What a rollback of ``path`` would do here; writes nothing."""
    data = read_backup(path)
    name = data.get("name") or ""
    out = {"path": path, "name": name, "note": data.get("note", ""),
           "made_by": data.get("made_by", ""), "made_at": data.get("made_at", ""),
           "car_id": data.get("car_id"), "params": data.get("params") or {},
           "files": [], "replace": [], "add": [], "problems": []}
    if not name:
        out["problems"].append("the backup does not name a car")
        return out
    listed = data.get("files") or []
    out["files"] = list(listed)
    if not listed:
        out["problems"].append("the backup lists no files")
    depot = os.path.join(root, ".depot")
    for rel in listed:
        if ".." in rel.replace("\\", "/").split("/"):
            out["problems"].append(f"refusing a path that climbs out: {rel}")
            continue
        local = os.path.join(depot, *rel.split("/"))
        (out["replace"] if os.path.isfile(local) else out["add"]).append(rel)
    # Informational, not a problem: a rollback that finds the car gone is the
    # normal case, and putting the files back is how it comes back.
    try:
        entry = depotlib.scan(root).get(name)
    except Exception:                            # noqa: BLE001
        entry = None
    out["installed"] = entry is not None
    out["now_id"] = entry.car_id if entry is not None else None
    out["id_moved"] = bool(entry is not None and out["car_id"] is not None
                           and int(out["car_id"]) != int(entry.car_id))
    return out


def rollback(root: str, path: str, *, log=print) -> dict:
    """Put a backup back into this install.

    Every file the zip holds is written, replacing what is there and creating
    what is not; each one is copied aside first, so the rollback itself can be
    undone.  Then the manifest rows are re-booked, and the mods record is put
    back when the backup carries one.

    A row that cannot be booked is reported, not fatal: a car whose spec was
    renamed by a broken build still needs its meshes back, and stopping half way
    through would leave the install in a worse state than it started.
    """
    info = inspect_backup(root, path)
    if info["problems"]:
        raise ShareError("; ".join(info["problems"]))
    name = info["name"]
    depot = os.path.join(root, ".depot")
    editlib._begin(f"Roll back {name}")
    written = []

    def land(rel: str, source: str) -> None:
        local = os.path.join(depot, *rel.split("/"))
        os.makedirs(os.path.dirname(local), exist_ok=True)
        # Always record the state first - a file the rollback *creates* gets an
        # ``.absent`` marker, so undo deletes it rather than leaving it behind.
        editlib._backup(root, local)
        shutil.copyfile(source, local)
        written.append((rel, local))

    if os.path.isdir(path):
        for rel in info["files"]:
            land(rel, os.path.join(path, PREFIX.replace("/", os.sep), *rel.split("/")))
    else:
        with zipfile.ZipFile(path) as zf:
            tmp = os.path.join(history_scratch(root), "_rollback")
            os.makedirs(tmp, exist_ok=True)
            try:
                for rel in info["files"]:
                    member = PREFIX + rel
                    try:
                        zf.extract(member, tmp)
                    except KeyError:
                        raise ShareError(
                            f"{os.path.basename(path)} is missing {rel}") from None
                    land(rel, os.path.join(tmp, *member.split("/")))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    booked, failed = 0, []
    for rel, local in written:
        try:
            editlib.sync_file(root, name=name, rel_path="/" + rel, local=local,
                              create=True)
            booked += 1
        except Exception as exc:                 # noqa: BLE001 - report, keep going
            failed.append((rel, str(exc)[:160]))
    restored = restore_params(root, name, info["params"])
    log(f"  {name}: {len(written)} file(s) put back, {booked} row(s) re-booked")
    return {"name": name, "written": len(written), "booked": booked,
            "failed": failed, "params": restored,
            "added": info["add"], "replaced": info["replace"]}


def restore_params(root: str, name: str, params: dict) -> dict:
    """Put a backup's ``rr3mods.json`` record back.  Returns what changed."""
    if not params:
        return {"changed": False}
    depot = os.path.join(root, ".depot")
    try:
        data = depotlib.load_mods(depot)
    except Exception:                            # noqa: BLE001
        return {"changed": False, "error": "the mods file could not be read"}
    record = params.get("mods_record") or {}
    side = params.get("status") or ""
    if not record or side not in ("mods", "vanilla"):
        return {"changed": False}
    before = (data.get(side) or {}).get(name)
    if before == record:
        return {"changed": False}
    other = "vanilla" if side == "mods" else "mods"
    data.setdefault(side, {})[name] = record
    (data.get(other) or {}).pop(name, None)
    try:
        depotlib.save_mods(depot, data)
    except Exception as exc:                     # noqa: BLE001
        return {"changed": False, "error": str(exc)[:160]}
    return {"changed": True, "status": side}


def history_scratch(root: str) -> str:
    """Scratch space next to the undo steps, never inside the game folder."""
    from . import history as historylib

    return historylib.dir_for(root)
