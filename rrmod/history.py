"""The undo history: one folder per edit, plus the note that says what it was.

``rrmod.edit`` has been writing ``_rrmod_backup/<stamp>/<rel>`` before every
write since the beginning, and ``restore_backup`` could put one of those folders
back.  What was missing is everything that makes a history *usable*:

* **A name.**  A folder called ``20261111-001432-3`` says nothing.  Each step now
  has a sidecar ``<stamp>.json`` carrying a title the caller supplies ("Built the
  LFA body"), the time, the files it touched, and whether it is pinned.
* **A limit.**  Nothing ever deleted an old step, so the folder grew for ever.
  Twenty steps are kept, oldest dropped first, and a pinned step is never
  dropped - that is the "this one was hard to get right" escape hatch.
* **A place of its own.**  The folder used to be nailed to the working copy.  A
  user who wants history on a faster disk, or next to a project, can point it
  somewhere else; ``set_dir`` is what the settings page writes.

The sidecar lives *next to* the step folder rather than inside it on purpose:
``restore_backup`` walks the folder and copies back every file it finds, so a
metadata file inside would be "restored" onto the working copy as a stray file.

Nothing here imports Qt - the dock in ``rrmod/ui/historyui.py`` is a thin shell
over this module, and the tests exercise this half head-less.
"""

from __future__ import annotations

import json
import os
import shutil
import time

#: How many steps to keep when nobody says otherwise.
DEFAULT_KEEP = 20

#: Where steps go when the user has not chosen a folder.  Same name the rest of
#: the program already used, so an existing history keeps working.
BACKUP_DIR = "_rrmod_backup"

STEP_SUFFIX = ".json"

#: Scratch space (merge output, share staging, build mirrors) stays in the
#: working copy whatever the history folder is - it is not history.
SCRATCH = BACKUP_DIR

_SEQ = {"last": "", "n": 0}
_BASE = {"dir": ""}


# ------------------------------------------------------------------- the place
def set_dir(path: str) -> None:
    """Point the history at ``path``.  Empty means "inside the working copy"."""
    _BASE["dir"] = str(path or "")


def dir_for(root: str) -> str:
    """Where steps for this working copy live."""
    chosen = _BASE["dir"]
    if not chosen:
        return os.path.join(root, BACKUP_DIR)
    # A folder shared by several working copies would mix their steps, so the
    # working copy's own name is appended when the folder is outside it.
    if os.path.abspath(chosen).startswith(os.path.abspath(root) + os.sep):
        return chosen
    return os.path.join(chosen, _tag(root))


def scratch(root: str) -> str:
    """Scratch space for one working copy - never moved by :func:`set_dir`."""
    return os.path.join(root, SCRATCH)


def _tag(root: str) -> str:
    import hashlib

    h = hashlib.md5(os.path.abspath(root).encode("utf-8")).hexdigest()
    return h[:10]


def _meta_path(root: str, stamp: str) -> str:
    return os.path.join(dir_for(root), stamp + STEP_SUFFIX)


# ------------------------------------------------------------------- writing
def next_stamp() -> str:
    """A fresh folder name.  Two edits in one second get ``-2``, ``-3``.

    ``rrmod.edit`` hands this out before it knows which working copy the edit is
    for (``_begin()`` is called at the top of every edit function), so the name
    and the folder are made in two steps: the name here, the folder in
    :func:`begin` once the root is known.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if stamp == _SEQ["last"]:
        _SEQ["n"] += 1
        # Zero padded, because these names are sorted as text: "-10" sorts
        # before "-2" otherwise, and the oldest step would then be pruned as if
        # it were the newest.  Measured, not guessed: a run that made eleven
        # steps in one second dropped the wrong folder.
        stamp = f"{stamp}-{_SEQ['n']:03d}"
    else:
        _SEQ["last"], _SEQ["n"] = stamp, 1
    return stamp


def begin(root: str, title: str = "", *, stamp: str = "") -> str:
    """Open a step and return its stamp.  Safe to call twice with one stamp."""
    stamp = stamp or next_stamp()
    base = dir_for(root)
    os.makedirs(os.path.join(base, stamp), exist_ok=True)
    if not os.path.isfile(_meta_path(root, stamp)):
        _write(root, stamp, {"stamp": stamp, "title": str(title or ""),
                             "when": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "files": [], "pinned": False})
    elif title:
        set_title(root, stamp, title)
    prune(root)
    return stamp


def note(root: str, stamp: str, rel: str, *, size: int = 0) -> None:
    """Record that ``rel`` was touched by this step."""
    data = read(root, stamp)
    rows = data.setdefault("files", [])
    for row in rows:
        if row and row[0] == rel:
            row[1] = size
            break
    else:
        rows.append([rel, size])
    _write(root, stamp, data)


def set_title(root: str, stamp: str, title: str) -> dict:
    data = read(root, stamp)
    data["title"] = str(title or "")
    return _write(root, stamp, data)


def pin(root: str, stamp: str, on: bool = True) -> dict:
    """Keep this step out of the way of the limit.  Never deletes anything."""
    data = read(root, stamp)
    data["pinned"] = bool(on)
    return _write(root, stamp, data)


# ------------------------------------------------------------------- reading
def _write(root: str, stamp: str, data: dict) -> dict:
    path = _meta_path(root, stamp)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return data


def write_step(root: str, stamp: str, data: dict) -> dict:
    """Rewrite one step's sidecar.  Same as :func:`_write`, public name."""
    return _write(root, stamp, data)


def read(root: str, stamp: str) -> dict:
    path = _meta_path(root, stamp)
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("stamp", stamp)
    data.setdefault("title", "")
    data.setdefault("when", "")
    data.setdefault("files", [])
    data.setdefault("pinned", False)
    if not data["when"]:
        data["when"] = _when_from_stamp(stamp)
    return data


def _when_from_stamp(stamp: str) -> str:
    """A readable time out of a folder name, for steps older than the sidecar."""
    head = stamp.split("-")
    if len(head) < 2 or len(head[0]) != 8:
        return ""
    try:
        t = time.strptime(head[0] + head[1][:6], "%Y%m%d%H%M%S")
    except ValueError:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", t)


def steps(root: str) -> list:
    """Every step, newest first, as dicts.  Steps without a sidecar still show."""
    base = dir_for(root)
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base), reverse=True):
        folder = os.path.join(base, name)
        if not os.path.isdir(folder) or name.startswith("_"):
            continue
        data = read(root, name)
        data["folder"] = folder
        if not data["files"]:
            data["files"] = [[rel, 0] for rel in _files_in(folder)]
        out.append(data)
    return out


def stamps(root: str) -> list:
    return [s["stamp"] for s in steps(root)]


def _files_in(folder: str) -> list:
    """The files a step folder holds, with the ``.absent`` suffix stripped."""
    from . import edit as editlib

    out = []
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), folder)
            rel = rel.replace(os.sep, "/")
            if rel.endswith(editlib.ABSENT):
                rel = rel[:-len(editlib.ABSENT)]
            out.append(rel)
    return sorted(set(out))


def files(root: str, stamp: str) -> list:
    data = read(root, stamp)
    rows = [r[0] for r in data.get("files") or [] if r]
    return rows or _files_in(os.path.join(dir_for(root), stamp))


def label(step: dict) -> str:
    """The one line a history panel shows for a step."""
    title = (step.get("title") or "").strip()
    if title:
        return title
    count = len(step.get("files") or [])
    return f"An unnamed edit of {count} file(s)"


def summary(root: str) -> dict:
    rows = steps(root)
    return {"steps": len(rows), "pinned": sum(1 for r in rows if r["pinned"]),
            "files": sum(len(r.get("files") or []) for r in rows),
            "folder": dir_for(root)}


# ------------------------------------------------------------------- pruning
def prune(root: str, keep: int = DEFAULT_KEEP) -> list:
    """Drop the oldest steps beyond ``keep``, never a pinned one.

    Returns the stamps that went.  A pinned step still counts towards the limit,
    so pinning does not quietly grow the folder without bound - it just means
    "this one is the last to go".
    """
    rows = steps(root)
    if keep <= 0 or len(rows) <= keep:
        return []
    gone = []
    for row in rows[keep:]:
        if row["pinned"]:
            continue
        _remove(root, row["stamp"])
        gone.append(row["stamp"])
    return gone


def _remove(root: str, stamp: str) -> None:
    shutil.rmtree(os.path.join(dir_for(root), stamp), ignore_errors=True)
    try:
        os.remove(_meta_path(root, stamp))
    except OSError:
        pass


def drop(root: str, stamps_) -> int:
    """Forget these steps on purpose.  Returns how many went."""
    n = 0
    for stamp in stamps_:
        if os.path.isdir(os.path.join(dir_for(root), stamp)):
            _remove(root, stamp)
            n += 1
    return n


# ------------------------------------------------------------------- restoring
def restore(root: str, stamps_) -> dict:
    """Put back the files of the given steps, oldest last so the oldest wins.

    A file can appear in several selected steps (build the body, then give it a
    wing).  Walking the list newest-first means the final copy is the one the
    *oldest* selected step saved, which is the state the user is asking for:
    "as it was before any of these edits".
    """
    from . import edit as editlib

    wanted = [s for s in stamps_ if os.path.isdir(
        os.path.join(dir_for(root), s))]
    touched = []
    for stamp in sorted(wanted, reverse=True):
        touched.extend(files(root, stamp))
        editlib.restore_backup(root, stamp, base=dir_for(root))
    out = []
    for rel in touched:
        if rel not in out:
            out.append(rel)
    return {"stamps": sorted(wanted), "files": out}
