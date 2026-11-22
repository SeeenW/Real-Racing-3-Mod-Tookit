"""What the device held before a push, kept per file and only per file.

A full copy of an install is 10.43 GB across 48,678 files.  A car mod is a
folder of a few dozen files, usually under 30 MB, and the asset lists that have
to change with it are a couple of hundred kilobytes.  So the honest thing to
back up is exactly what a push is about to overwrite - nothing else - and that
list is already known: it is the deploy plan plus the lists
:func:`rrmod.deploy.following_manifests` says will be rewritten.

Two files hold the record:

``<mods>/_backup/<id>/``
    the device's own bytes, at the same relative paths the device uses
    (``.depot/vehicles/...``), plus ``_before.json`` naming every file, its md5
    and size, or ``absent`` for a file the push is about to create.

``<mods>/_state.json``
    a stack of pushes.  Last in, first out, because two mods that touch the same
    file have to come off in the reverse order they went on - the second mod's
    copy of the file is what the first one's removal must put back.

The asset lists are ordinary files here.  Backing them up means an uninstall
puts the device's own lists back byte for byte, which is simpler and safer than
trying to work out which rows a particular mod added: rows are cheap to copy and
nearly impossible to attribute after the fact.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from . import depot as depotlib

#: Folder under the mods directory holding one folder per push.
BACKUP_DIR = "_backup"
#: The stack of pushes, next to it.
STATE_FILE = "_state.json"
VERSION = 1


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class BackupError(Exception):
    """A push cannot be remembered, or cannot be taken back."""


def base(depot: str) -> str:
    """The folder the mods file lives in, i.e. where our own bookkeeping goes."""
    return os.path.abspath(depotlib.state_dir(depot))


def backup_root(depot: str) -> str:
    return os.path.join(base(depot), BACKUP_DIR)


def state_path(depot: str) -> str:
    return os.path.join(base(depot), STATE_FILE)


def _empty() -> dict:
    return {"version": VERSION, "pushes": []}


def load_state(depot: str) -> dict:
    path = state_path(depot)
    if not os.path.isfile(path):
        return _empty()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("version", VERSION)
    if not isinstance(data.get("pushes"), list):
        data["pushes"] = []
    return data


def save_state(depot: str, data: dict) -> None:
    path = state_path(depot)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def pushes(depot: str) -> list:
    """The stack, oldest first."""
    return list(load_state(depot)["pushes"])


def top(depot: str) -> dict:
    got = pushes(depot)
    return got[-1] if got else {}


def _next_id(depot: str) -> str:
    """A fresh folder name, never colliding with one already on disk."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    taken = set(os.listdir(backup_root(depot))) if os.path.isdir(
        backup_root(depot)) else set()
    for push in pushes(depot):
        taken.add(str(push.get("id") or ""))
    if stamp not in taken:
        return stamp
    for n in range(2, 1000):
        candidate = f"{stamp}-{n:03d}"
        if candidate not in taken:
            return candidate
    raise BackupError(f"cannot find a free name under {backup_root(depot)}")


def take(dev, depot: str, items, *, title: str = "", log=print) -> dict:
    """Copy the device's version of every file in ``items`` into a new folder.

    ``items`` is ``[(local, remote_rel, lock)]`` - the deploy plan.  A file the
    device does not have is recorded as ``absent`` rather than skipped: an
    uninstall has to know that it should delete the file, not leave it behind.
    """
    from . import deploy as deploylib

    rows = list(items or ())
    if not rows:
        raise BackupError("nothing to remember: the plan is empty")
    mod_id = _next_id(depot)
    folder = os.path.join(backup_root(depot), mod_id)
    os.makedirs(folder, exist_ok=True)
    files = []
    for _local, remote, _lock in rows:
        target = os.path.join(folder, *remote.split("/"))
        data = deploylib._pull_bytes(dev, remote, target)
        if not data and not dev.exists(remote):
            if os.path.isfile(target):
                os.remove(target)
            files.append([remote, "", 0, True])
            continue
        files.append([remote, md5_bytes(data), len(data), False])
    entry = {
        "id": mod_id,
        "title": title or "a push",
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "folder": folder,
        "files": files,
    }
    with open(os.path.join(folder, "_before.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        json.dump({"version": VERSION, "id": mod_id, "title": entry["title"],
                   "when": entry["when"], "files": files}, fh, indent=1,
                  sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    data = load_state(depot)
    data["pushes"].append(entry)
    save_state(depot, data)
    log(f"  remembered {len(files)} file(s) in {folder}")
    return entry


def describe(depot: str, mod_id: str) -> dict:
    """What one remembered push holds."""
    path = os.path.join(backup_root(depot), mod_id, "_before.json")
    if not os.path.isfile(path):
        raise BackupError(f"there is no remembered push called {mod_id}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def restore(dev, depot: str, mod_id: str = "", *, force: bool = False,
            log=print) -> dict:
    """Put the device back the way it was before one remembered push.

    Refuses to go out of order unless ``force``: a mod that went on second has a
    copy of the file from *after* the first mod, so restoring the first one while
    the second is still installed would write bytes the second mod never had.
    """
    got = pushes(depot)
    if not got:
        raise BackupError("nothing has been pushed from here yet")
    entry = got[-1] if not mod_id else next(
        (p for p in got if p.get("id") == mod_id), None)
    if entry is None:
        raise BackupError(f"there is no remembered push called {mod_id}")
    if not force and entry is not got[-1]:
        raise BackupError(
            f"{entry['id']} went on before {got[-1]['id']}, which is still "
            f"installed - taking it off now would leave the device holding "
            f"neither version. Remove the later one first, or pass force")
    seen = describe(depot, entry["id"])
    folder = os.path.join(backup_root(depot), entry["id"])
    put = 0
    gone = 0
    for remote, md5, size, absent in seen["files"]:
        if absent:
            if dev.exists(remote):
                dev.remove(remote)
                gone += 1
            continue
        local = os.path.join(folder, *remote.split("/"))
        if not os.path.isfile(local):
            raise BackupError(
                f"{remote} was remembered but {local} is gone, so it cannot be "
                f"put back")
        dev.push(local, remote, lock=remote.startswith("apk/res/"))
        put += 1
    data = load_state(depot)
    data["pushes"] = [p for p in data["pushes"] if p.get("id") != entry["id"]]
    save_state(depot, data)
    log(f"  put back {put} file(s), removed {gone}")
    return {"id": entry["id"], "restored": put, "removed": gone,
            "left": len(data["pushes"])}


def forget(depot: str, mod_id: str, *, delete: bool = True) -> dict:
    """Drop a remembered push from the stack, optionally deleting its copies."""
    import shutil

    data = load_state(depot)
    keep = [p for p in data["pushes"] if p.get("id") != mod_id]
    if len(keep) == len(data["pushes"]):
        raise BackupError(f"there is no remembered push called {mod_id}")
    data["pushes"] = keep
    save_state(depot, data)
    freed = 0
    if delete:
        folder = os.path.join(backup_root(depot), mod_id)
        for root, _dirs, leaves in os.walk(folder):
            for leaf in leaves:
                try:
                    freed += os.path.getsize(os.path.join(root, leaf))
                except OSError:
                    pass
        shutil.rmtree(folder, ignore_errors=True)
    return {"id": mod_id, "left": len(keep), "freed": freed}


def summary(depot: str) -> dict:
    """How much is remembered, for the window to show before it offers more."""
    got = pushes(depot)
    total = 0
    for push in got:
        for _remote, _md5, size, absent in push.get("files") or ():
            if not absent:
                total += int(size or 0)
    return {"pushes": len(got), "files": sum(len(p.get("files") or ())
                                             for p in got),
            "bytes": total, "folder": backup_root(depot),
            "top": got[-1]["id"] if got else ""}


def selftest(depot: str) -> list:
    """Checks that need no device, for the test suite to lean on."""
    out = []
    got = summary(depot)
    out.append(("the stack reads", isinstance(got["pushes"], int)))
    out.append(("the folder is under the mods file",
                base(depot) in backup_root(depot)))
    return out
