"""Project files: ``.rr3proj``, the "save what I have so far" of a mod.

The undo history answers "put that back" for the last twenty seconds' worth of
work.  It cannot answer the other question - "keep this, I want to try a
different wing from here" - because it is bound to one working copy, it expires,
and it holds only bytes.  A mod is not only bytes: the id a car was given, its
appearance record, the paint slots, the aero behaviour, the prices are scattered
across eight `.nct` tables, and a project has to remember the *answers* as well
as the files.

So a project is a zip holding two things side by side:

* ``files/<path inside .depot>`` - the contents of every file the project owns,
  exactly as they were, plus whether each one is new or a replacement.
* ``project.json`` - the name, who made it, when, a fingerprint of the install it
  was made against, the parameters the build dialog was filled in with, and the
  list of files.

Compression is level 1 on purpose.  Measured on a real car (33 files, 7.37 MB):
level 1 gives 4.90 MB in 0.23 s, level 9 gives 4.84 MB in 0.33 s.  The 1.2% is
not worth the time, and most of the bytes are `.dds.z` and `.bin` that are
already compressed - they come out at 100%, so the only thing being squeezed is
the `.m3g`, at 46%.

Opening a project puts its files back into the working copy and stages them, so
the Deploy tab offers exactly what the project holds.  It never touches the
install or the device.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import zipfile

from . import edit as editlib
from . import history as historylib

MANIFEST = "project.json"
FORMAT = 1
PREFIX = "files/"
HISTORY_PREFIX = "history/"
COMPRESS_LEVEL = 1
#: Files bigger than this are stored rather than deflated - they are already
#: compressed and the attempt only costs time.
STORE_ABOVE = 4 << 20

#: The ``-p1`` / ``-p2`` suffixes this module adds when a step name is taken.
_PN_RE = re.compile(r"-p\d+$")

#: Appended to a step title that came out of a project rather than this session.
FROM_PROJECT = " (from a project)"


class ProjectError(Exception):
    pass


def _version() -> str:
    from . import __version__

    return __version__


# ------------------------------------------------------------------ fingerprint
def fingerprint(install: str) -> dict:
    """A cheap, stable description of the install a project was made against.

    The registry file is the right thing to hash: it is the one list that names
    every asset, it is never written by this program (only the working copy's
    copy is), and it changes whenever the game itself changes.  The car count
    comes along as a second opinion for the case where a different build happens
    to ship a registry of the same size.
    """
    import hashlib

    reg = os.path.join(install, ".depot", "asset_list_base.txtCache.txt")
    md5 = ""
    if os.path.isfile(reg):
        h = hashlib.md5()
        with open(reg, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        md5 = h.hexdigest()
    cars = 0
    folder = os.path.join(install, ".depot", "vehicles")
    if os.path.isdir(folder):
        cars = sum(1 for d in os.listdir(folder)
                   if os.path.isdir(os.path.join(folder, d)))
    return {"md5": md5, "cars": cars}


# ------------------------------------------------------------------ writing
def _file_rows(root: str, *, car: str = "", staged: bool = True) -> list:
    """``[(path inside .depot, kind)]`` for what the project should hold.

    ``staged`` means "what this session changed", which now comes from the undo
    history: every file an edit touches is copied aside before it is written, so
    the steps are an exact list of what has been worked on.  ``car`` widens it to
    every file that car owns, which is what a project meant to be handed to
    someone else needs.  Both can be asked for at once and the union is taken.
    """
    rows = {}
    if staged:
        for stamp in historylib.stamps(root):
            for rel in historylib.files(root, stamp):
                rows.setdefault(rel, "replace")
    if car:
        folder = os.path.join(root, ".depot", "vehicles", car)
        if os.path.isdir(folder):
            for dirpath, _dirs, files in os.walk(folder):
                sub = os.path.relpath(dirpath, folder).replace(os.sep, "/")
                for f in sorted(files):
                    rel = (f".depot/vehicles/{car}/{f}" if sub == "."
                           else f".depot/vehicles/{car}/{sub}/{f}")
                    rows.setdefault(rel, "replace")
    out = []
    for rel in sorted(rows):
        if not os.path.isfile(os.path.join(root, *rel.split("/"))):
            continue
        out.append((rel, rows[rel]))
    return out


def _install_of(root: str) -> str:
    return editlib._install_of(root)


def _kind(root: str, rel: str) -> str:
    """``"new"`` when the install has no such file, else ``"replace"``."""
    install = _install_of(root)
    if not install:
        return "replace"
    return ("replace" if os.path.isfile(os.path.join(install, *rel.split("/")))
            else "new")


def save(root: str, out_path: str, *, name: str = "", params=None, car: str = "",
         include_history: bool = False, note: str = "", log=print) -> dict:
    """Write a project zip.  Returns a summary of what went in."""
    rows = _file_rows(root, car=car)
    if not rows:
        raise ProjectError(
            "nothing has been changed yet, so there is nothing to save - edit a "
            "file or name a car to take whole")
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    files = []
    total = 0
    for rel, _action in rows:
        local = os.path.join(root, *rel.split("/"))
        game = rel[len(".depot/"):] if rel.startswith(".depot/") else rel
        files.append([game, _kind(root, rel), os.path.getsize(local)])
        total += os.path.getsize(local)
    install = _install_of(root)
    manifest = {
        "format": FORMAT,
        "name": name or os.path.splitext(os.path.basename(out_path))[0],
        "made_by": f"RR3 Mod Manager {_version()}",
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "note": note,
        "install_md5": fingerprint(install)["md5"] if install else "",
        "install_cars": fingerprint(install)["cars"] if install else 0,
        "params": params or {},
        "files": files,
    }
    tmp = out_path + ".part"
    written = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=COMPRESS_LEVEL) as zf:
        zf.writestr(MANIFEST,
                    json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
        for rel, _action in rows:
            local = os.path.join(root, *rel.split("/"))
            game = rel[len(".depot/"):] if rel.startswith(".depot/") else rel
            if os.path.getsize(local) > STORE_ABOVE:
                info = zipfile.ZipInfo.from_file(local, PREFIX + game)
                info.compress_type = zipfile.ZIP_STORED
                with open(local, "rb") as fh:
                    zf.writestr(info, fh.read())
            else:
                zf.write(local, PREFIX + game)
            written += 1
        steps = 0
        if include_history:
            steps = _write_history(root, zf)
    os.replace(tmp, out_path)
    size = os.path.getsize(out_path)
    log(f"  {os.path.basename(out_path)}: {written} file(s), "
        f"{total:,} bytes -> {size:,} bytes")
    return {"path": out_path, "bytes": size, "raw": total, "files": written,
            "name": manifest["name"], "steps": steps,
            "manifest": manifest}


def _write_history(root: str, zf: zipfile.ZipFile) -> int:
    """Copy the undo steps into the zip, so a project carries its way back."""
    base = historylib.dir_for(root)
    n = 0
    for step in historylib.steps(root):
        stamp = step["stamp"]
        folder = os.path.join(base, stamp)
        if not os.path.isdir(folder):
            continue
        for dirpath, _dirs, files in os.walk(folder):
            for f in files:
                local = os.path.join(dirpath, f)
                sub = os.path.relpath(local, folder).replace(os.sep, "/")
                zf.write(local, f"{HISTORY_PREFIX}{stamp}/{sub}")
        meta = os.path.join(base, stamp + historylib.STEP_SUFFIX)
        if os.path.isfile(meta):
            zf.write(meta, f"{HISTORY_PREFIX}{stamp}{historylib.STEP_SUFFIX}")
        n += 1
    return n


# ------------------------------------------------------------------ reading
def read(path: str) -> dict:
    """The ``project.json`` inside a project zip."""
    if not os.path.isfile(path):
        raise ProjectError(f"{path} is not there")
    try:
        with zipfile.ZipFile(path) as zf:
            data = json.loads(zf.read(MANIFEST).decode("utf-8"))
    except KeyError as exc:
        raise ProjectError(
            f"{os.path.basename(path)} has no {MANIFEST}, so it is not a project"
        ) from exc
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ProjectError(f"{os.path.basename(path)}: {exc}") from exc
    fmt = data.get("format", FORMAT)
    if fmt != FORMAT:
        raise ProjectError(f"project format {fmt}, this program speaks {FORMAT}")
    return data


def describe(path: str, *, install: str = "") -> dict:
    """What a project holds and whether it was made against this install."""
    data = read(path)
    files = data.get("files") or []
    out = {
        "path": path,
        "name": data.get("name", ""),
        "made_by": data.get("made_by", ""),
        "created": data.get("created", ""),
        "note": data.get("note", ""),
        "count": len(files),
        "bytes": sum(int(f[2]) for f in files if len(f) > 2),
        "new": sum(1 for f in files if len(f) > 1 and f[1] == "new"),
        "params": data.get("params") or {},
        "cars": sorted({_car_of(f[0]) for f in files if f and _car_of(f[0])}),
        "same_install": None,
        "steps": 0,
    }
    if install:
        here = fingerprint(install)
        out["same_install"] = (not data.get("install_md5")
                               or data["install_md5"] == here["md5"])
        out["install_md5"] = data.get("install_md5", "")
        out["here_md5"] = here["md5"]
    with zipfile.ZipFile(path) as zf:
        out["steps"] = len(_steps_in(zf.namelist()))
    return out


def _steps_in(names) -> set:
    """The step stamps a project zip carries, sidecars included."""
    found = set()
    for name in names:
        if not name.startswith(HISTORY_PREFIX):
            continue
        head = name[len(HISTORY_PREFIX):].split("/")[0]
        if head.endswith(historylib.STEP_SUFFIX):
            head = head[:-len(historylib.STEP_SUFFIX)]
        if head:
            found.add(head)
    return found


def _car_of(game_path: str) -> str:
    parts = [p for p in str(game_path).split("/") if p]
    if len(parts) >= 3 and parts[0] == "vehicles" and parts[1] != "data":
        return parts[1]
    return ""


def params_from(info: dict) -> dict:
    """The build dialog's answers, in a form ``json`` can hold.

    ``result_info()`` returns three dozen keys, and three of them are not JSON:
    ``aero_kind`` is a byte string, ``aero_params`` is a tuple and ``pack`` is a
    path that will not exist on another machine.  Everything else is a string, a
    number, a dict of those or a list of those, so it survives as it is.  The path
    is dropped rather than rewritten - a project records what was *asked for*, and
    the file it was built from is a separate matter that the files list covers.
    """
    out = {}
    for key, value in (info or {}).items():
        if key in ("pack", "slots"):
            continue
        out[key] = _plain(value)
    return out


def _plain(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode("latin-1")
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    return str(value)


# ------------------------------------------------------------------ opening
def open_project(root: str, path: str, *, log=print) -> dict:
    """Put a project's files back into the working copy and stage them.

    Only files that the project actually holds are written, so a project made
    from three files does not silently overwrite a car that has been rebuilt
    since.  Nothing is written outside ``.depot/``; the manifests are rebuilt
    from what is on disk when the Deploy tab pushes.
    """
    data = read(path)
    files = [f for f in (data.get("files") or []) if f and f[0]]
    if not files:
        raise ProjectError(f"{os.path.basename(path)} holds no files")
    written = []
    created = 0
    # Opening a project is an edit like any other: the files land in the game
    # folder, so the state they replace has to be in the history first or the
    # "open a project" would be the one action Ctrl+Z cannot take back.  The
    # backup has to happen *before* each file is written - taking it afterwards
    # would copy the project's own bytes into the history and undo would restore
    # the very edit it is supposed to take back.
    editlib.begin(f"Open the project {os.path.basename(path)}")
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        for game, _kind_, _size in files:
            member = PREFIX + game
            if member not in names:
                continue
            target = os.path.join(root, ".depot", *game.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if not os.path.isfile(target):
                created += 1
            editlib.backup_for_undo(root, target)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written.append(".depot/" + game)
        steps = _read_history(root, zf)
    log(f"  {os.path.basename(path)}: {len(written)} file(s) restored, "
        f"{created} of them new")
    return {"path": path, "name": data.get("name", ""), "files": len(written),
            "new": created, "written": len(written),
            "params": data.get("params") or {}, "steps": steps}


def _read_history(root: str, zf: zipfile.ZipFile) -> int:
    """Put the project's steps into the history folder, without overwriting."""
    base = historylib.dir_for(root)
    os.makedirs(base, exist_ok=True)
    names = zf.namelist()
    found = _steps_in(names)
    n = 0
    for old in sorted(found):
        # A project opened twice must not grow a chain of suffixes: the second
        # import of "20261111-191609-p1" becomes "20261111-191609-p2", not
        # "20261111-191609-p1-p1", which is unreadable and unbounded.
        stem = _PN_RE.sub("", old) or old
        stamp = old
        bump = 0
        while os.path.isdir(os.path.join(base, stamp)):
            bump += 1
            stamp = f"{stem}-p{bump}"
        os.makedirs(os.path.join(base, stamp), exist_ok=True)
        for name in names:
            if not name.startswith(f"{HISTORY_PREFIX}{old}/"):
                continue
            sub = name[len(f"{HISTORY_PREFIX}{old}/"):]
            if not sub or name.endswith("/"):
                continue
            target = os.path.join(base, stamp, *sub.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        meta_name = f"{HISTORY_PREFIX}{old}{historylib.STEP_SUFFIX}"
        meta = {"stamp": stamp, "title": "A step from a project", "files": [],
                "pinned": False}
        if meta_name in names:
            try:
                with zf.open(meta_name) as src:
                    meta.update(json.loads(src.read().decode("utf-8")))
            except (OSError, ValueError):
                pass
        meta["stamp"] = stamp
        title = meta.get("title") or "A step from a project"
        if not title.endswith(FROM_PROJECT):
            title += FROM_PROJECT
        meta["title"] = title
        historylib.write_step(root, stamp, meta)
        n += 1
    return n
