"""Change cars that are already installed: replace models, add files, delete.

Two very different jobs, deliberately kept apart:

``replace``
    The car keeps its id, its tables and its paint schemes.  Only some of its
    files change (a rebuilt ``_a.m3g``, a new ``_wing.banim``, ...).  That means
    three manifests have to learn the new sizes and hashes and nothing else:
    the per car ``asset_list_vehicle_<name>.txt``, the master
    ``asset_list_base.txtCache.txt`` and - for files under ``vehicles/data`` -
    ``asset_list_vehicle_data.txt``.  This is the cheap path and the one that
    "the studio forgot to model the active wing, let me add it" needs.

``new``
    A whole car id, spec, appearance record and so on.  That is
    :func:`rr3lib.car.build_car`, which writes a mirror instead of touching the
    install; this module only needs to merge that mirror in afterwards.

Every write goes through :func:`_backup` first, so a broken edit can be undone
without the pristine reference depot.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time

from rr3lib import livery as liverylib
from rr3lib import manifest as manifestlib
from rr3lib import nct as nctlib
from rr3lib import spec as speclib

from . import depot as depotlib
from . import history as historylib

#: Scratch space for building (the pack mirror lives in ``_rrmod_backup/_build``).
#: The history itself is not nailed here any more - see ``rrmod.history``.
BACKUP_DIR = historylib.BACKUP_DIR


class EditError(Exception):
    pass


# ------------------------------------------------------------------ utilities
def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_SESSION = {"stamp": "", "title": ""}


def _begin(title: str = "") -> str:
    """Start one edit: every backup made from here on shares one folder.

    Without this a single operation that touches six files would leave six
    timestamped folders, which makes "undo that last build" a guessing game.
    Two edits in the same second would collide on the same name and the second
    would overwrite the first, so repeats get a ``-2``, ``-3`` suffix.

    ``title`` is what the history panel shows for the step ("Build the LFA"),
    because a folder name is not a sentence.  The folder itself and its ``.json``
    note appear in :func:`_backup`, which is the first place that knows *which*
    working copy the edit belongs to - and therefore where the history lives.
    """
    _SESSION["stamp"] = historylib.next_stamp()
    _SESSION["title"] = str(title or "")
    return _SESSION["stamp"]


def begin(title: str = "") -> str:
    """Start a new undo step, so what follows can be walked back on its own.

    Every edit function here calls :func:`_begin` itself, but a page that writes
    files and then hands them to :func:`sync_file` one by one (the brand logo is
    the first of those) never enters one of them - and without this its backups
    would land in whatever folder the previous edit opened, so "undo the logo"
    would also undo the car that was edited before it.
    """
    return _begin(title)


#: Suffix a backup entry gets when the file did not exist before the edit.
#: Without it an "undo" could put back everything the edit changed except the
#: files it created, which is exactly the half-undo that makes a broken brand
#: still show up in the list after being undone.
ABSENT = ".absent"


def _backup(root: str, path: str) -> str:
    """Copy ``path`` into the current step before editing it.

    A file the edit is about to *create* has nothing to copy, so an empty marker
    named ``<rel>.absent`` is written instead.  Restoring a step then knows to
    delete that file rather than leaving it behind - a brand whose logo page was
    added and then undone must not keep the page.

    The first copy of a file in a step wins.  An edit that touches one file
    several times (the logo writes the atlas, then the manifest row for it, then
    another page's row) would otherwise overwrite its own backup with the state
    the edit had already produced, and the undo would restore the edit.

    Where the step lives is :mod:`rrmod.history`'s business, so this is also the
    first place that can open the folder: it is the only caller that knows the
    working copy.
    """
    stamp = _SESSION["stamp"] or _begin()
    rel = os.path.relpath(path, root).replace("\\", "/")
    dst = os.path.join(historylib.dir_for(root), stamp, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    historylib.begin(root, _SESSION.get("title", ""), stamp=stamp)
    historylib.note(root, stamp, rel,
                    size=os.path.getsize(path) if os.path.isfile(path) else 0)
    if os.path.isfile(dst) or os.path.exists(dst + ABSENT):
        return dst
    if os.path.isfile(path):
        shutil.copyfile(path, dst)
    else:
        with open(dst + ABSENT, "wb"):
            pass
    return dst


def backup_for_undo(root: str, path: str) -> str:
    """Record ``path`` as it is *now*, so an undo can put it back.

    Pages that write a file themselves and then call :func:`sync_file` (the brand
    logo does) have to say so: :func:`sync_file` only touches manifests, and a
    file it never saw appear would survive the undo that removes its row - a page
    on disk nothing points at.  A file that does not exist yet gets the
    ``.absent`` marker, which is what makes undo delete it.
    """
    return _backup(root, path)


def backup_before_write(root: str, path: str) -> str:
    """Record the state of a file a page is about to write itself.

    :func:`_backup` is called before an edit changes a file it can still read.
    A helper that writes the file itself (the logo builder writes the atlas and
    a new page) has to say so separately.  **It must be called before the write**,
    which is why the helpers that write take a ``backup`` callback: an edit is
    written straight into the install now, so calling this afterwards would copy
    the *new* bytes into the history and the undo would restore the edit.  A file
    that does not exist yet gets an ``.absent`` marker, so an undo deletes it
    rather than leaving a page nothing points at on disk for ever.
    """
    stamp = _SESSION["stamp"] or _begin()
    rel = os.path.relpath(path, root).replace("\\", "/")
    dst = os.path.join(historylib.dir_for(root), stamp, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    historylib.begin(root, _SESSION.get("title", ""), stamp=stamp)
    historylib.note(root, stamp, rel,
                    size=os.path.getsize(path) if os.path.isfile(path) else 0)
    install = _install_of(root)
    original = os.path.join(install, *rel.split("/")) if install else ""
    if original and os.path.isfile(original):
        shutil.copyfile(original, dst)
    elif not os.path.exists(dst + ABSENT):
        with open(dst + ABSENT, "wb"):
            pass
    return dst


def backups(root: str) -> list:
    """The steps of this working copy, newest first."""
    return historylib.stamps(root)


def restore_backup(root: str, stamp: str, *, base: str = "") -> int:
    """Put every file from one step back where it came from.

    A file the edit created is deleted instead - its ``.absent`` marker is the
    only record that it was not there before.  Returns how many files changed.
    ``base`` overrides where the steps live; :mod:`rrmod.history` passes its own
    folder so a history kept outside the working copy still restores.
    """
    src = os.path.join(base or historylib.dir_for(root), stamp)
    if not os.path.isdir(src):
        raise EditError(f"no backup named {stamp}")
    n = 0
    for dirpath, _dirs, files in os.walk(src):
        for f in files:
            p = os.path.join(dirpath, f)
            if f.endswith(ABSENT):
                gone = os.path.join(root, os.path.relpath(p[:-len(ABSENT)], src))
                if os.path.isfile(gone):
                    os.remove(gone)
                    n += 1
                continue
            rel = os.path.relpath(p, src)
            dst = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(p, dst)
            n += 1
    return n


def car_manifest_path(root: str, name: str) -> str:
    return os.path.join(root, "apk", "res", f"asset_list_vehicle_{name}.txt")


def _asset_path(root: str, name: str, filename: str) -> str:
    return os.path.join(root, ".depot", "vehicles", name, filename)


def _is_data_path(rel: str) -> bool:
    return rel.startswith("/vehicles/data/")


# ------------------------------------------------------------- manifest sync
#: The two books :func:`sync_file` has always updated by hand, because each has
#: its own shape: the registry is a 13 byte header plus two columns, and the
#: vehicle data list is one flat sorted block of ``/vehicles/data/`` paths.
#: ``asset_list_startup.txt`` used to be listed here too, which was a bug: no
#: other branch handled it, so a change to ``/materials/materials.bin`` - the one
#: file that list mostly exists for - was staged and then never booked, and the
#: engine would have wanted to download it.  It is a plain four column list, so
#: the generic path below owns it now.
_OWN_BOOKS = ("asset_list_vehicle_data.txt", "asset_list_base.txt")



def _install_of(root: str) -> str:
    """The install a working copy was made from, from its own ``pending.json``.

    There is no working copy any more: an edit is written into the install, so
    the install *is* the root and that is what this answers.  A ``pending.json``
    left behind by an older version is still honoured, because a user who kept
    one should not have their files read against the wrong tree.

    The working copy only mirrored what an edit was about to touch, so a list an
    edit needs could be missing from it while the install had it.  Copying it in
    on demand is what kept :func:`sync_file` working for the folders no page has
    opened yet - a brand's logo sheet was the first of those.
    """
    path = os.path.join(root, "pending.json")
    if not os.path.isfile(path):
        return root
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return root
    return str(data.get("install") or "") or root


#: Where the game keeps the pages several cars share.
COMMON_DIR = "vehicles/common"
#: The list that claims them, and the only one whose stems always carry four rows.
COMMON_LIST = "asset_list_vehicle_common.txt"


def _common_stem(rel_path: str) -> str:
    """``/vehicles/common/car_windows_04.dxt.dds.z`` -> ``car_windows_04``."""
    from . import deps as depslib

    return depslib.stem_of(rel_path).rsplit("/", 1)[-1]


def _sync_common_page(root: str, *, rel_path: str, md5: str, size: int,
                      out: dict) -> bool:
    """Add the four family rows one shared page needs; True when it did.

    ``asset_list_vehicle_common.txt`` lists every page **four times**, once per
    GPU family, in four contiguous runs of 298 rows each.  A page added with one
    row would be the only ragged stem in the list, so the four rows go in
    together, each inside its own run at its sorted place.

    Only the family we actually copied gets its true hash.  The other three
    describe files this build never shipped - exactly the state all 298 shipped
    pages are in - so they carry the same numbers rather than a row that claims a
    file exists with a hash nobody can check.  The registry, which the engine
    reads for "is this file present", gets one row: the ``.dxt.dds.z`` one.
    """
    if not rel_path.startswith(f"/{COMMON_DIR}/"):
        return False
    leaf = COMMON_LIST
    path = manifestlib.asset_list_path(root, leaf)
    if not os.path.isfile(path):
        install = _install_of(root)
        src = (manifestlib.asset_list_path(install, leaf) if install else "")
        if not src or not os.path.isfile(src):
            raise EditError(f"{leaf} is not in the working copy and not in the "
                            f"install either")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(src, path)
        out["list_seeded"] = leaf
        manifestlib.forget()
    al = manifestlib.load_asset_list(root, leaf)
    stem = _common_stem(rel_path)
    added = []
    for suffix in manifestlib.FAMILIES:
        row_path = f"/{COMMON_DIR}/{stem}{suffix}"
        if al.get(row_path) is None:
            al.insert(row_path, md5, size, size)
            added.append(row_path)
    if not added:
        out["list"] = f"{leaf} (same)"
        return True
    _backup(root, path)
    manifestlib.save_asset_list(al, path)
    out["list"] = f"{leaf} ({len(added)} rows)"
    out["list_rows"] = added
    manifestlib.forget()
    return True


#: Where the game keeps the pages several tracks share.
TRACK_COMMON_DIR = "Tracks/common"


def _track_list_for(index, rel_path: str) -> str:
    """Which of the nineteen ``asset_list_track_common_*`` lists owns a path.

    The exact path answers when the page already exists; a page that does not
    exist yet is filed by its folder, because the nineteen lists are keyed by the
    top folder (``mat``, ``gnd``, ``surface``, ...) and a new page belongs in the
    list of the folder it sits in.  ``list_for`` walks up the parents, so a new
    subfolder such as ``mat/rrmod_metal/`` still lands in the ``mat`` list, and a
    new *top* folder lands in the root list - the one that already claims
    ``/Tracks/common/common.bin`` and so is the only list the game reads for that
    level.

    Nothing is guessed: if no ancestor folder is listed at all the call raises,
    because the folder a page lives in *is* how the game finds its list, and a
    page in a folder no list knows would be a file the engine never asks for.
    """
    leaf = index.owner_of(rel_path)
    if leaf:
        return leaf
    leaf = index.list_for(rel_path)
    if leaf:
        return leaf
    raise EditError(
        f"no asset list claims {rel_path}, and none of its folders are listed "
        f"either, so the game would never find it")


def _sync_track_page(root: str, *, rel_path: str, md5: str, size: int,
                     out: dict) -> bool:
    """Add the four family rows one track page needs; True when it did.

    The track side is laid out like ``vehicles/common`` - every page is four
    rows, one per GPU family, in four contiguous runs - but it is spread over
    nineteen lists, one per top folder (``mat``, ``gnd``, ``surface``, ...), and
    which one owns a path depends on that folder.  See :func:`_track_list_for`.
    """
    if not rel_path.startswith(f"/{TRACK_COMMON_DIR}/"):
        return False
    index = manifestlib.asset_index(root)
    try:
        leaf = _track_list_for(index, rel_path)
    except EditError:
        # A working copy mirrors only the lists an edit has needed so far, so ask
        # the install before giving up: it knows which list owns the folder even
        # when the copy has not seeded that list yet.
        install_root = _install_of(root)
        if not install_root:
            raise
        leaf = _track_list_for(manifestlib.asset_index(install_root), rel_path)
    path = manifestlib.asset_list_path(root, leaf)
    if not os.path.isfile(path):
        install = _install_of(root)
        src = (manifestlib.asset_list_path(install, leaf) if install else "")
        if not src or not os.path.isfile(src):
            raise EditError(f"{leaf} is not in the working copy and not in the "
                            f"install either")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(src, path)
        out["list_seeded"] = leaf
        manifestlib.forget()
    al = manifestlib.load_asset_list(root, leaf)
    stem = rel_path
    for suffix in manifestlib.FAMILIES:
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    added = []
    for suffix in manifestlib.FAMILIES:
        row_path = f"{stem}{suffix}"
        if al.get(row_path) is None:
            al.insert(row_path, md5, size, size)
            added.append(row_path)
    if not added:
        out["list"] = f"{leaf} (same)"
        return True
    _backup(root, path)
    manifestlib.save_asset_list(al, path)
    out["list"] = f"{leaf} ({len(added)} rows)"
    out["list_rows"] = added
    manifestlib.forget()
    return True


def _sync_other_list(root: str, *, name: str, rel_path: str, md5: str,
                     size: int, create: bool, out: dict) -> None:
    """Update whichever of the other ~1,230 asset lists claims this path.

    This is the bug that made adding a brand trigger a download: a logo page
    lives in ``asset_list_gui_assets_core.txt``, which nothing here used to
    touch, so the engine saw a file on disk that no list mentioned and went
    looking for the rest of the download.  The index is cheap enough to build on
    demand (0.3 s for 1,236 lists) and knows which list claims every path, so
    the answer is looked up rather than guessed from the folder name.

    A car's own list is never touched here - :func:`sync_file` already rewrites
    it a few lines above, and doing it twice was a hard error: the second write
    tried to *insert* a row the first one had just appended.
    """
    try:
        index = manifestlib.asset_index(root)
    except manifestlib.ManifestError as exc:
        raise EditError(str(exc)) from exc
    if name and rel_path.startswith(f"/vehicles/{name}/"):
        # A car's own folder is claimed by that car's list, which
        # :func:`sync_file` has just written two dozen lines above.  Doing it
        # again here was a hard error - the second write tried to *insert* a row
        # the first one had appended.  For a brand new car nothing claims the
        # folder yet, so the folder vote cannot answer either; the per car list
        # is the right book in both cases.
        out["list"] = "n/a"
        return
    if rel_path.startswith(f"/{COMMON_DIR}/"):
        # Shared pages are the one case where one file needs four rows, in four
        # different runs of one list.  The generic path below would add a single
        # row and leave the stem ragged.
        _sync_common_page(root, rel_path=rel_path, md5=md5, size=size, out=out)
        return
    if rel_path.startswith(f"/{TRACK_COMMON_DIR}/"):
        # The track side has the same four-rows-per-page rule, but spread over
        # nineteen lists keyed by the page's top folder.
        _sync_track_page(root, rel_path=rel_path, md5=md5, size=size, out=out)
        return
    leaf = index.owner_of(rel_path)
    if not leaf:
        # A working copy mirrors only the lists an edit has needed so far, so a
        # path whose book has not been copied in yet looks unclaimed here even
        # though the install knows exactly which list owns it.  The install's
        # index answers the same question about the same game path, and the book
        # is seeded from the install a few lines below, so ask it before giving
        # up: that is what turned "clone a material" into a staged file with no
        # row in asset_list_startup.txt.
        install_root = _install_of(root)
        if install_root:
            try:
                leaf = manifestlib.asset_index(install_root).owner_of(rel_path)
            except manifestlib.ManifestError:
                leaf = ""
    creating = False
    if not leaf:
        if not create:
            out["list"] = "unclaimed"
            return
        leaf = index.list_for(rel_path)
        if not leaf:
            raise EditError(
                f"no asset list claims {rel_path} and none of its folders are "
                f"listed either, so the game would never find it")
        creating = True
    if leaf in _OWN_BOOKS:
        out["list"] = "n/a"
        return
    path = manifestlib.asset_list_path(root, leaf)
    if not os.path.isfile(path):
        # Not mirrored yet.  Seed it from the install and carry on - refusing
        # here is what turned "give this brand a logo" into an error dialog.
        install = _install_of(root)
        src = (manifestlib.asset_list_path(install, leaf) if install else "")
        if not src or not os.path.isfile(src):
            raise EditError(f"{leaf} is not in the working copy and not in the "
                            f"install either")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(src, path)
        out["list_seeded"] = leaf
        manifestlib.forget()
    al = manifestlib.load_asset_list(root, leaf)
    _backup(root, path)
    if creating:
        al.insert(rel_path, md5, size, size)
        out["list"] = f"{leaf} (new row)"
        # The index no longer describes the file on disk, and the next file of
        # the same kind has to be found by the folder vote again.
        manifestlib.forget()
    else:
        out["list"] = (f"{leaf} (updated)"
                       if al.update(rel_path, md5, size, size)
                       else f"{leaf} (same)")
    manifestlib.save_asset_list(al, path)


def sync_file(root: str, *, name: str, rel_path: str, local: str,
              create: bool = False) -> dict:
    """Teach the manifests one file's new size and hash.

    ``rel_path`` is the game path (``/vehicles/<name>/<file>``).  When the file
    is not in the per car manifest yet it is appended (``create``) or the call
    raises - a silently missing row means the engine downloads the whole car
    again.

    Four books are involved and this function keeps all of them in step: the per
    car list, the master registry, ``asset_list_vehicle_data.txt``, and - since
    the brand bug - whichever of the other 1,230 lists owns the path.  A file no
    list claims cannot be created: the game has no way to find it, so that is an
    error rather than a silent no-op.
    """
    _SESSION["stamp"] = _SESSION["stamp"] or _begin()
    md5 = md5_file(local)
    size = os.path.getsize(local)
    out = {"path": rel_path, "md5": md5, "size": size,
           "manifest": "updated", "registry": False, "data_list": "n/a",
           "list": "n/a"}

    car_manifest = car_manifest_path(root, name)
    # The per car manifest only lists the car's own folder.  Files under
    # ``vehicles/data`` (a livery table, a spec) live in the registry and the
    # vehicle data list instead, so they are not looked for here.
    own = rel_path.startswith(f"/vehicles/{name}/")
    if own and os.path.isfile(car_manifest):
        rows = manifestlib.read_car_manifest(car_manifest)
        hit = False
        for i, (p, m, pk, r) in enumerate(rows):
            if p == rel_path:
                rows[i] = (p, md5, size, size)
                hit = True
                break
        if not hit:
            if not create:
                raise EditError(f"{rel_path} is not in {os.path.basename(car_manifest)}")
            rows.append((rel_path, md5, size, size))
            out["manifest"] = "appended"
        _backup(root, car_manifest)
        manifestlib.write_car_manifest(rows, car_manifest)
    elif own and create:
        raise EditError(f"no per car manifest for {name}")
    elif not own:
        out["manifest"] = "n/a"

    reg = manifestlib.load_registry(os.path.join(root, ".depot"))
    if reg.set(rel_path, md5):
        out["registry"] = True
    # The registry is a book like any other, and it is the one the *engine*
    # compares the lists against: restoring the per car manifest without it
    # leaves the install claiming a file no manifest lists, which is the
    # "registry disagrees with the manifest" state.  So it is copied aside too.
    _backup(root, os.path.join(root, ".depot", manifestlib.REGISTRY))
    manifestlib.save_registry(reg, os.path.join(root, ".depot",
                                                manifestlib.REGISTRY))

    if _is_data_path(rel_path):
        dl = manifestlib.load_data_list(root)
        if rel_path in set(dl.paths()):
            out["data_list"] = "updated" if dl.update(rel_path, md5, size, size) else "same"
        elif create:
            dl.insert(rel_path, md5, size, size)
            out["data_list"] = "inserted"
        _backup(root, os.path.join(root, *manifestlib.VEHICLE_DATA_LIST.split("/")))
        manifestlib.save_data_list(dl, os.path.join(root, *manifestlib.VEHICLE_DATA_LIST.split("/")))

    _sync_other_list(root, name=name, rel_path=rel_path, md5=md5, size=size,
                     create=create, out=out)
    return out


def forget_file(root: str, *, name: str, rel_path: str) -> dict:
    """Remove one file from the manifests (and from disk)."""
    out = {"path": rel_path, "removed": False}
    car_manifest = car_manifest_path(root, name)
    if os.path.isfile(car_manifest):
        rows = [r for r in manifestlib.read_car_manifest(car_manifest)
                if r[0] != rel_path]
        _backup(root, car_manifest)
        manifestlib.write_car_manifest(rows, car_manifest)
        out["removed"] = True
    reg = manifestlib.load_registry(os.path.join(root, ".depot"))
    if reg.remove(rel_path):
        out["registry"] = True
    _backup(root, os.path.join(root, ".depot", manifestlib.REGISTRY))
    manifestlib.save_registry(reg, os.path.join(root, ".depot",
                                                manifestlib.REGISTRY))
    if _is_data_path(rel_path):
        dl = manifestlib.load_data_list(root)
        if rel_path in set(dl.paths()):
            dl.remove(rel_path)
            _backup(root, os.path.join(root, *manifestlib.VEHICLE_DATA_LIST.split("/")))
            manifestlib.save_data_list(
                dl, os.path.join(root, *manifestlib.VEHICLE_DATA_LIST.split("/")))
            out["data_list"] = "removed"
    return out


# ------------------------------------------------------------ replace files
def replace_file(root: str, name: str, lod: str, source: str) -> dict:
    """Put ``source`` in place as the car's LOD file, then fix the manifests.

    ``lod`` is ``A``..``H``, ``shared``, ``int_a``, ``int_b`` or ``frontend``.
    """
    _begin(f"Put a new {lod} model on {name}")
    suffix = lod.lower() if len(lod) == 1 else lod.lower()
    target = _asset_path(root, name, f"{name}_{suffix}.m3g")
    if not os.path.isfile(target):
        raise EditError(f"{name} has no _{suffix}.m3g to replace")
    if os.path.abspath(source) != os.path.abspath(target):
        _backup(root, target)
        shutil.copyfile(source, target)
    rel = f"/vehicles/{name}/{name}_{suffix}.m3g"
    info = sync_file(root, name=name, rel_path=rel, local=target)
    info["target"] = target
    return info


def add_file(root: str, name: str, source: str, *, rename: str = "") -> dict:
    """Add a brand new file to an existing car folder (a banim, an xml, ...)."""
    _begin(f"Add {rename or os.path.basename(source)} to {name}")
    base = rename or os.path.basename(source)
    target = _asset_path(root, name, base)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.abspath(source) != os.path.abspath(target):
        # ``_backup`` writes an ``.absent`` marker when the file is new, so
        # undoing this edit deletes it again instead of leaving a banim or an
        # xml behind that nothing refers to.
        _backup(root, target)
        shutil.copyfile(source, target)
    rel = f"/vehicles/{name}/{base}"
    info = sync_file(root, name=name, rel_path=rel, local=target, create=True)
    info["target"] = target
    return info


def add_slot_names(root: str, names, *, log=print) -> dict:
    """Append part or material names to ``liveryStringTable.bin.nct``.

    A part the game has never heard of cannot be pointed at a material: the
    engine looks the *whole mesh name* up in this table, gets nothing, and draws
    the part with no material at all.  That is why a hand made wing needs its own
    name in here before any livery row can mention it.

    Appending is the only safe change - a slot **is** its position, so inserting
    in the middle would renumber every slot above it and every one of the 540
    livery tables would then point at the wrong part.  Names already present keep
    their slot, which makes this safe to call twice.
    """
    wanted = [str(n) for n in names if str(n)]
    if not wanted:
        raise EditError("no names to add")
    depot = os.path.join(root, ".depot")
    path = liverylib.slot_table_path(depot)
    if not os.path.isfile(path):
        raise EditError(f"no livery string table at {path}")
    table = liverylib.load_slot_table(depot)
    before = len(table)
    added = []
    slots = {}
    for name in wanted:
        was = table.slot(name)
        slot = table.append(name)
        slots[name] = slot
        if was is None:
            added.append(name)
    out = {"path": path, "before": before, "after": len(table),
           "added": added, "kept": [n for n in wanted if n not in added],
           "slots": slots, "saved": False}
    if not added:
        return out
    _backup(root, path)
    liverylib.save_slot_table(table, path)
    out["saved"] = True
    sync_file(root, name="",
              rel_path=f"/vehicles/data/liveries/liveryStringTable.bin.nct",
              local=path)
    log(f"  {len(added)} name(s) added, slots {before}..{len(table) - 1}")
    return out


def add_common_page(root: str, source: str, *, stem: str = "",
                    log=print) -> dict:
    """Put a texture into ``vehicles/common`` and book all four family rows.

    ``common/`` is where a page several cars share belongs: it is written once
    and every livery table that names it reads the same file.  The cost is that
    removing it later has to know who still wants it, which is what
    :mod:`rrmod.deps` records.

    ``stem`` is the name without a suffix (``car_windows_s2_lemans``); left out
    it is taken from the file name.  The suffix is kept as it is: this build
    ships ``.dxt.dds.z`` and the game reads whichever family the device asks for,
    so converting a page to another family is a separate job.
    """
    from . import deps as depslib

    if not os.path.isfile(source):
        raise EditError(f"{source} does not exist")
    base = os.path.basename(source)
    suffix = ""
    for known in (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z"):
        if base.lower().endswith(known):
            suffix = base[-len(known):]
            break
    if not suffix:
        raise EditError(f"{base} is not a game texture (expected .dxt.dds.z, "
                        f".etc.dds.z, .atc.dds.z or .ptc.pvr.z)")
    stem = (stem or base[:-len(suffix)]).strip("/")
    if not stem:
        raise EditError("a shared page needs a name")
    if "/" in stem:
        raise EditError(f"{stem!r} cannot have a folder in it - shared pages all "
                        f"live directly under vehicles/common")
    _begin(f"Add the shared page {stem}")
    depot = os.path.join(root, ".depot")
    folder = os.path.join(depot, *COMMON_DIR.split("/"))
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, stem + suffix)
    # Ask before the copy: afterwards the working copy has the file either way,
    # so "is this one of the game's own pages" would always answer yes.
    was_shipped = os.path.isfile(target)
    if os.path.abspath(source) != os.path.abspath(target):
        _backup(root, target)
        shutil.copyfile(source, target)
    rel = f"/{COMMON_DIR}/{stem}{suffix}"
    out = sync_file(root, name="", rel_path=rel, local=target, create=True)
    out["target"] = target
    out["stem"] = f"common/{stem}"
    out["recorded"] = depslib.record(
        depot, f"common/{stem}", "<this mod>", files=[rel],
        source=os.path.basename(source), shipped=was_shipped)
    log(f"  {rel} ({os.path.getsize(target):,} B)")
    return out


def remove_common_page(root: str, stem: str, *, force: bool = False) -> dict:
    """Delete a shared page, refusing while anything still names it.

    A page the game shipped is never deleted: the engine may ask for it by a path
    this program has not seen, and there is no way to get it back without a fresh
    download of the whole install.  ``force`` only overrides the "somebody still
    names it" check, never the shipped check.
    """
    from . import deps as depslib

    key = depslib.stem_of(stem)
    depot = os.path.join(root, ".depot")
    state = depslib.status(depot, key, refresh=True)
    if state["shipped"]:
        raise EditError(f"{key} is one of the game's own pages - it is never "
                        f"deleted, whatever names it")
    if state["live"] and not force:
        names = ", ".join(state["live"][:4])
        more = f" and {len(state['live']) - 4} more" if len(state["live"]) > 4 else ""
        raise EditError(f"{key} is still named by {names}{more}; point those cars "
                        f"at another page first, or pass force")
    _begin(f"Remove the shared page {key}")
    folder = os.path.join(depot, *COMMON_DIR.split("/"))
    leaf = key.rsplit("/", 1)[-1]
    gone = []
    for suffix in (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z"):
        path = os.path.join(folder, leaf + suffix)
        if os.path.isfile(path):
            _backup(root, path)
            os.remove(path)
            gone.append(path)
    # and its rows in the list, all four of them
    path = manifestlib.asset_list_path(root, COMMON_LIST)
    dropped = []
    if os.path.isfile(path):
        al = manifestlib.load_asset_list(root, COMMON_LIST)
        for suffix in manifestlib.FAMILIES:
            row_path = f"/{COMMON_DIR}/{leaf}{suffix}"
            if al.get(row_path) is not None:
                al.remove(row_path)
                dropped.append(row_path)
        if dropped:
            _backup(root, path)
            manifestlib.save_asset_list(al, path)
            manifestlib.forget()
    reg = manifestlib.load_registry(depot)
    unregistered = 0
    for suffix in manifestlib.FAMILIES:
        if reg.remove(f"/{COMMON_DIR}/{leaf}{suffix}"):
            unregistered += 1
    if unregistered:
        _backup(root, os.path.join(depot, manifestlib.REGISTRY))
        manifestlib.save_registry(reg, os.path.join(depot, manifestlib.REGISTRY))
    depslib.drop(depot, key)
    depslib.forget()
    return {"stem": key, "files": gone, "rows": dropped,
            "registry": unregistered}


def add_track_page(root: str, source: str, *, rel: str = "",
                   log=print) -> dict:
    """Put a texture under ``Tracks/common`` and book all four family rows.

    The track side mirrors the car side: one page, four rows, one per GPU
    family.  What differs is the folder.  A track page is filed by where it
    belongs - ``mat/``, ``gnd/``, ``surface/``, ``overlay/`` - and each of those
    folders has its own list, so ``rel`` is the path below ``Tracks/common``
    rather than a bare name.  Left out, it is taken from the source file's own
    path when that path is already under ``Tracks/common``, and rejected
    otherwise: a page at the root of ``Tracks/common`` would be a name no track
    model asks for.

    The suffix is kept as it is.  This build ships ``.dxt.dds.z`` and the game
    reads whichever family the device asks for, so converting a page to another
    family is a separate job.
    """
    from . import deps as depslib

    if not os.path.isfile(source):
        raise EditError(f"{source} does not exist")
    base = os.path.basename(source)
    suffix = ""
    for known in (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z"):
        if base.lower().endswith(known):
            suffix = base[-len(known):]
            break
    if not suffix:
        raise EditError(f"{base} is not a game texture (expected .dxt.dds.z, "
                        f".etc.dds.z, .atc.dds.z or .ptc.pvr.z)")
    stem = (rel or base[:-len(suffix)]).strip("/").replace("\\", "/")
    if not stem:
        raise EditError("a track page needs a name")
    if "/" not in stem:
        raise EditError(
            f"{stem!r} has no folder in it - track pages live under a category "
            f"folder such as mat/, gnd/ or surface/, and that folder is what "
            f"decides which asset list files the page")
    if stem.startswith("common/"):
        raise EditError(f"{stem!r} is not a track page path")
    _begin(f"Add the track page {stem}")
    depot = os.path.join(root, ".depot")
    folder = os.path.join(depot, *TRACK_COMMON_DIR.split("/"))
    target = os.path.join(folder, *stem.split("/")) + suffix
    os.makedirs(os.path.dirname(target), exist_ok=True)
    # Ask before the copy: afterwards the working copy has the file either way,
    # so "is this one of the game's own pages" would always answer yes.
    was_shipped = os.path.isfile(target)
    if os.path.abspath(source) != os.path.abspath(target):
        _backup(root, target)
        shutil.copyfile(source, target)
    game_path = f"/{TRACK_COMMON_DIR}/{stem}{suffix}"
    out = sync_file(root, name="", rel_path=game_path, local=target, create=True)
    out["target"] = target
    out["stem"] = depslib.TRACK_PREFIX + stem.lower()
    out["recorded"] = depslib.record(
        depot, out["stem"], "<this mod>", files=[game_path],
        source=os.path.basename(source), shipped=was_shipped)
    log(f"  {game_path} ({os.path.getsize(target):,} B)")
    return out


def remove_track_page(root: str, stem: str, *, force: bool = False) -> dict:
    """Delete a track page, refusing while any track model still names it.

    Same rules as :func:`remove_common_page`: a page the game shipped is never
    deleted, and a page a track's own model still points at is only deleted with
    ``force``.  ``stem`` may be given either way round - with the
    ``tracks/common/`` prefix the record uses, or as the path below
    ``Tracks/common`` that the file system uses - because a person reading the
    page off disk and a person reading it off the Dependencies tab write it
    differently.
    """
    from . import deps as depslib

    key = depslib.track_key(stem)
    depot = os.path.join(root, ".depot")
    state = depslib.track_status(depot, key, refresh=True)
    if state["shipped"]:
        raise EditError(f"{key} is one of the game's own pages - it is never "
                        f"deleted, whatever names it")
    if state["live"] and not force:
        names = ", ".join(state["live"][:4])
        more = f" and {len(state['live']) - 4} more" if len(state["live"]) > 4 else ""
        raise EditError(f"{key} is still named by {names}{more}; point those "
                        f"tracks at another page first, or pass force")
    _begin(f"Remove the track page {key}")
    folder = os.path.join(depot, *TRACK_COMMON_DIR.split("/"))
    rel = key[len(depslib.TRACK_PREFIX):]
    gone = []
    for suffix in (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z"):
        path = os.path.join(folder, *rel.split("/")) + suffix
        if os.path.isfile(path):
            _backup(root, path)
            os.remove(path)
            gone.append(path)
    # and its rows in whichever of the nineteen lists owns it
    index = manifestlib.asset_index(root)
    game_row = f"/{TRACK_COMMON_DIR}/{rel}.dxt.dds.z"
    try:
        leaf = _track_list_for(index, game_row)
    except EditError:
        install_root = _install_of(root)
        leaf = ""
        if install_root:
            try:
                leaf = _track_list_for(manifestlib.asset_index(install_root),
                                       game_row)
            except EditError:
                leaf = ""
        if not leaf:
            # Nothing claims the folder, so there is no row to drop either.  The
            # file still has to go, which is what the caller asked for.
            depslib.drop(depot, key)
            depslib.forget()
            return {"stem": key, "list": "", "files": gone, "rows": [],
                    "registry": 0}
    dropped = []
    path = manifestlib.asset_list_path(root, leaf)
    if os.path.isfile(path):
        al = manifestlib.load_asset_list(root, leaf)
        for suffix in manifestlib.FAMILIES:
            row_path = f"/{TRACK_COMMON_DIR}/{rel}{suffix}"
            if al.get(row_path) is not None:
                al.remove(row_path)
                dropped.append(row_path)
        if dropped:
            _backup(root, path)
            manifestlib.save_asset_list(al, path)
            manifestlib.forget()
    reg = manifestlib.load_registry(depot)
    unregistered = 0
    for suffix in manifestlib.FAMILIES:
        if reg.remove(f"/{TRACK_COMMON_DIR}/{rel}{suffix}"):
            unregistered += 1
    if unregistered:
        _backup(root, os.path.join(depot, manifestlib.REGISTRY))
        manifestlib.save_registry(reg, os.path.join(depot, manifestlib.REGISTRY))
    depslib.drop(depot, key)
    depslib.forget()
    return {"stem": key, "list": leaf, "files": gone, "rows": dropped,
            "registry": unregistered}


def set_identity(root: str, name: str, *, display_name: str = "",
                 make: str = "", model: str = "") -> dict:
    """Change what an *installed* car is called and which brand files it.

    Three strings, three different homes, and only one of them is obvious:

    * **the name** is normally a ``CAR_NAME_*`` key into the text tables, so it
      is renamed where the game looks it up - every language, one line each -
      and the spec is not touched at all.  A car built here has a literal string
      in the spec instead (that is what :meth:`Spec.set_display_name` writes), so
      for those the literal is what changes.  33 shipped cars have no name field
      at all; they are named from year/make/model and the caller is told so.
    * **the brand** is the make string *and* the ``CAR_MANUFACTURER_*`` key that
      502 specs carry.  Writing only the make is the bug this function exists to
      avoid: the brand list reads the key first, so the car would keep appearing
      under its old manufacturer.
    * **the model** is the third string (``718 RSK``).

    Empty arguments are left alone, so a caller can change one of the three.
    Everything lands in one undo step.
    """
    from rr3lib import texts as textslib

    depot = os.path.join(root, ".depot")
    if not os.path.isdir(os.path.join(depot, "vehicles", name)):
        raise EditError(f"{name} is not installed")
    from . import stats as statlib

    spec = statlib.load(root, name)
    if spec is None:
        raise EditError(f"{name} has no spec file to change")
    spec_path = statlib.spec_path(root, name)
    texts = textslib.Texts.load(depot)
    before = {"name": "", "make": spec.make(), "model": spec.model(),
              "manufacturer": spec.manufacturer_key()}
    key = spec.display_name_key()
    before["name"] = (texts.get(key) if key.startswith("CAR_NAME_")
                      and texts.has(key) else key)

    _begin(f"Rename {name}")
    out = {"car": name, "spec": spec_path, "before": before, "after": {},
           "changed": [], "note": ""}
    text_touched = False
    spec_touched = False

    # ---- the name -----------------------------------------------------
    wanted = (display_name or "").strip()
    if wanted and wanted != before["name"]:
        if key.startswith("CAR_NAME_") and texts.has(key):
            # keep the key: the game looks the name up in thirteen text files
            texts.set(key, wanted)
            text_touched = True
            out["how"] = f"the {key} text"
        elif spec.set_display_name(wanted):
            spec_touched = True
            out["how"] = "the spec's own name string"
        else:
            out["note"] = ("this car has no name field - it is named from its "
                           "year, make and model, so change the model instead")

    # ---- the brand ----------------------------------------------------
    wanted = (make or "").strip()
    if wanted and wanted != before["make"]:
        from . import brands as brandlib

        if spec.set_make(wanted):
            spec_touched = True
        new_key = brandlib.key_of(wanted)
        if spec.manufacturer_key():
            if spec.set_manufacturer("CAR_MANUFACTURER_" + new_key):
                spec_touched = True
        # A brand the game has no word for gets one, so the list and the
        # showroom show the same name the spec does.  An existing brand's word
        # is left alone - it is the game's own translation.
        text_key = "CAR_MANUFACTURER_" + new_key
        if not texts.has(text_key):
            texts.set(text_key, wanted)
            text_touched = True

    # ---- the model ----------------------------------------------------
    wanted = (model or "").strip()
    if wanted and wanted != before["model"]:
        if spec.set_model(wanted):
            spec_touched = True

    # ---- write it -----------------------------------------------------
    if text_touched:
        # The text files are backed up before anything is written, and only the
        # ones that actually change: a rename touches 13 files and an undo of it
        # has to put all 13 back.
        for leaf in texts.changed():
            path = os.path.join(depot, leaf)
            if os.path.isfile(path):
                _backup(root, path)
        texts.save(depot, only_changed=True)
        # The names are cached per depot for a whole session; without this the
        # car keeps showing its old name until the program is restarted.
        depotlib.forget_names(depot)
    if spec_touched:
        _backup(root, spec_path)
        speclib.save_spec(spec, spec_path)
        sync_file(root, name=name,
                  rel_path=f"/vehicles/data/{os.path.basename(spec_path)}",
                  local=spec_path)
    after_key = spec.display_name_key()
    out["after"] = {"name": (texts.get(after_key)
                             if after_key.startswith("CAR_NAME_")
                             and texts.has(after_key) else after_key),
                    "make": spec.make(), "model": spec.model(),
                    "manufacturer": spec.manufacturer_key()}
    out["changed"] = [k for k in ("name", "make", "model")
                      if out["after"][k] != before[k]]
    return out


def set_aero_flag(root: str, name: str, enable: bool = True, *,
                  kind: bytes = b"", params=()) -> dict:
    """Turn the spec's active aero behaviour on or off, or change which one.

    This is the flag that makes the game try to move a wing at all: a car
    without it never plays its ``_wing.banim``, however good the curves are.
    Adding a wing to a car the studio left out therefore needs this, the banim,
    the xml and the livery rows - all four.

    ``kind`` picks the behaviour - ``DeployWhenBraking`` (wing up under braking),
    ``DeployAtSpeed`` (wing flattens above a speed: drag reduction), or
    ``BrakeAndSpeedCombo`` (both, which is what the Senna and the Jesko do).
    ``params`` are the two speeds, high one first; the shipped cars only ever
    write them for the last two behaviours.
    """
    from rr3lib import spec as speclib

    _begin(f"Set the wing behaviour of {name}")
    depot = os.path.join(root, ".depot")
    inv = depotlib.scan(root)
    entry = inv.get(name)
    if entry is None:
        raise EditError(f"{name} is not installed")
    path = os.path.join(depot, *speclib.SPEC_DIR.split("/"),
                        f"{entry.spec_stem}.bin.nct")
    spec = speclib.load_spec(depot, entry.spec_stem)
    out = {"spec": path, "before": spec.aero_text(),
           "after": "", "changed": False}
    if spec.set_aero(enable, kind=kind, params=params):
        _backup(root, path)
        speclib.save_spec(spec, path)
        out["changed"] = True
        sync_file(root, name=name, rel_path=f"/vehicles/data/{entry.spec_stem}"
                                            f".bin.nct", local=path)
    out["after"] = spec.aero_text()
    return out



def _driver_dir(root: str) -> str:
    """The ``.depot`` that holds ``driver/``, preferring the working copy.

    Returns the depot root, not the folder itself, because every reader in
    :mod:`rr3lib.driver` takes a depot and appends ``driver`` to it.

    No car edit writes into that folder - it holds the poses and their models,
    shared by every car - so the working copy normally has no copy of it and the
    install's is the right one to read.  Only if something ever does write there
    does the working copy take precedence.
    """
    local = os.path.join(root, ".depot", "driver")
    if os.path.isdir(local) and os.listdir(local):
        return os.path.join(root, ".depot")
    install = _install_of(root)
    if install:
        shared = os.path.join(install, ".depot", "driver")
        if os.path.isdir(shared):
            return os.path.join(install, ".depot")
    return ""


def set_driver_pose(root: str, name: str, banim: str = "") -> dict:
    """Point a car at another driver animation, or at none of its own.

    ``banim`` is a ``driver_<x>.banim`` name, with or without the ``.banim``
    suffix; ``""`` clears the field so the car falls back to ``driver.banim``.

    The field lives in the car's data record (``vehicles/data/<id>_<car>.bin.nct``),
    not in the spec: that record is what the game reads when it seats a driver.
    A car whose pose has no low-poly model of its own still loads - the generic
    ``driver_lod_c`` is used and the figure simply holds a pose nobody modelled
    for it - so this never refuses on that ground, it only reports it.
    """
    from rr3lib import driver as driverlib

    depot = os.path.join(root, ".depot")
    if not os.path.isdir(os.path.join(depot, "vehicles", name)):
        raise EditError(f"{name} is not installed")
    record = driverlib.car_record(depot, name)
    if record is None:
        raise EditError(f"{name} has no data record, so it has no driver field "
                        f"to change")
    folder = driverlib.driver_dir(_driver_dir(root) or depot)
    wanted = (banim or "").strip()
    if wanted and not wanted.endswith(driverlib.BANIM_SUFFIX):
        wanted += driverlib.BANIM_SUFFIX
    if wanted and folder and not os.path.isfile(os.path.join(folder, wanted)):
        raise EditError(f"there is no {wanted} in driver/ - pick one the game ships")

    _begin(f"Seat the driver of {name} differently")
    before = driverlib.field_in_record(record)
    out = {"record": record, "before": before or "", "after": "",
           "changed": False, "low_poly": ""}
    if driverlib.set_field(record, wanted):
        _backup(root, record)
        out["changed"] = True
        sync_file(root, name=name,
                  rel_path=f"/vehicles/data/{os.path.basename(record)}",
                  local=record)
    out["after"] = driverlib.field_in_record(record) or ""
    if folder and out["after"]:
        stem = out["after"][: -len(driverlib.BANIM_SUFFIX)]
        own = os.path.join(folder, f"driver_lod_c_{stem[len(driverlib.SKIN_PREFIX):]}.m3g")
        out["low_poly"] = own if os.path.isfile(own) else ""
    return out


def _decal_path(root: str) -> str:
    """The decal table in the working copy, seeded from the install if needed.

    It is written like every other table: the working copy is what gets edited,
    and the install stays a backup.  A missing copy is taken from the install
    rather than created empty, because an empty decal list is not a valid one -
    the vinyl editor would come up with nothing in it.
    """
    from rr3lib import decals as decallib

    rel = decallib.DECALS
    target = os.path.join(root, ".depot", *rel.split("/"))
    if os.path.isfile(target):
        return target
    src = _install_abs(root, rel)
    if not src or not os.path.isfile(src):
        raise EditError(f"{rel} is not in the install, so there is no decal "
                        f"list to edit")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(src, target)
    return target


def _save_decals(root: str, table, path: str, what: str) -> dict:
    """Write the list back and book it in the asset lists that name it."""
    from rr3lib import decals as decallib

    _backup(root, path)
    before = os.path.getsize(path)
    decallib.save(table, path)
    rel = "/" + decallib.DECALS
    out = sync_file(root, name="", rel_path=rel, local=path)
    out["what"] = what
    out["before_bytes"] = before
    out["after_bytes"] = os.path.getsize(path)
    return out


def set_decal(root: str, decal_id: int, *, name: bytes = None,
              category: bytes = None, code_point=None, glyph: bytes = None,
              page: bytes = None, three=None, extra: bytes = None,
              tail: bytes = None) -> dict:
    """Change one record of ``custom.decals.nct``.

    ``None`` means "leave that field alone", so a rename does not have to know
    the record's glyph.  ``glyph`` sets the raw bytes and is the only way to put
    a spelling back exactly: the shipped list writes the same character as
    ``b"0x0029"`` in 148 records and as ``b")"`` in 81, and neither is canonical.
    """
    from rr3lib import decals as decallib

    path = _decal_path(root)
    table = decallib.load(os.path.join(root, ".depot"))
    before = table.by_id(decal_id)
    if before is None:
        raise EditError(f"there is no decal {decal_id}")
    was = before.describe()
    _begin(f"Change the decal {decal_id}")
    try:
        decallib.set_record(table, decal_id, name=name, category=category,
                            code_point=code_point, glyph=glyph, page=page,
                            three=three, extra=extra, tail=tail)
    except decallib.DecalError as exc:
        raise EditError(str(exc)) from exc
    after = table.by_id(decal_id).describe()
    changed = [k for k in after if after.get(k) != was.get(k)]
    out = {"id": decal_id, "before": was, "after": after,
           "changed": changed, "saved": False}
    if changed:
        out.update(_save_decals(root, table, path, f"decal {decal_id}"))
        out["saved"] = True
    return out


def add_decal(root: str, *, category: bytes, name: bytes,
              code_point=None, glyph: bytes = b"", page: bytes = b"",
              three=(0, 0, 0), extra: bytes = b"0", tail=None,
              position: int = -1) -> dict:
    """Append one record to the decal list, or put it at ``position``.

    A record draws either a glyph or a page and never both - that is how the
    file itself is written, 187 glyphs and 42 pages with nothing in between.
    """
    from rr3lib import decals as decallib

    path = _decal_path(root)
    table = decallib.load(os.path.join(root, ".depot"))
    if glyph is None:
        glyph = b""
    if code_point is not None:
        glyph = decallib.code_point_text(code_point)
    kwargs = {"category": category, "name": name, "glyph": glyph,
              "page": page, "three": three, "extra": extra}
    if tail is not None:
        kwargs["tail"] = tail
    _begin(f"Add the decal {name.decode('latin-1')}")
    try:
        made = decallib.add(table, **kwargs)
    except decallib.DecalError as exc:
        raise EditError(str(exc)) from exc
    if position >= 0:
        decallib.move(table, made.id, position)
    out = {"id": made.id, "record": made.describe()}
    out.update(_save_decals(root, table, path, f"new decal {made.id}"))
    out["saved"] = True
    return out


def remove_decal(root: str, decal_id: int) -> dict:
    """Drop one record from the decal list."""
    from rr3lib import decals as decallib

    path = _decal_path(root)
    table = decallib.load(os.path.join(root, ".depot"))
    before = table.by_id(decal_id)
    if before is None:
        raise EditError(f"there is no decal {decal_id}")
    was = before.describe()
    _begin(f"Remove the decal {decal_id}")
    decallib.remove(table, decal_id)
    out = {"id": decal_id, "record": was}
    out.update(_save_decals(root, table, path, f"removed decal {decal_id}"))
    out["saved"] = True
    return out


def move_decal(root: str, decal_id: int, position: int) -> dict:
    """Move one record to another place in the list, which is the menu order."""
    from rr3lib import decals as decallib

    path = _decal_path(root)
    table = decallib.load(os.path.join(root, ".depot"))
    before = table.by_id(decal_id)
    if before is None:
        raise EditError(f"there is no decal {decal_id}")
    was = [x.id for x in table.decals].index(decal_id)
    _begin(f"Move the decal {decal_id}")
    decallib.move(table, decal_id, position)
    now = [x.id for x in table.decals].index(decal_id)
    out = {"id": decal_id, "was": was, "now": now, "changed": was != now}
    if out["changed"]:
        out.update(_save_decals(root, table, path, f"moved decal {decal_id}"))
        out["saved"] = True
    return out


def _decal_font_path(root: str) -> str:
    """``r3_decals.ttf`` in the working copy, seeded from the install.

    It sits at the root of ``.depot``, not under ``vehicles``, which is why
    ``ensure_data`` has to mirror it separately - and why a decal edit that only
    thought about ``vehicles/data`` used to be unable to touch a glyph.
    """
    from rr3lib import decals as decallib

    rel = decallib.FONT
    target = os.path.join(root, ".depot", rel)
    if os.path.isfile(target):
        return target
    src = _install_abs(root, rel)
    if not src or not os.path.isfile(src):
        raise EditError(f"{rel} is not in the install, so there is no font to "
                        f"add a shape to")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(src, target)
    return target


def add_decal_shape(root: str, *, code_point: int, contours,
                    advance: int = 0, category: bytes = b"",
                    name: bytes = b"", position: int = -1) -> dict:
    """Add a shape: a glyph in the font *and* the record that names it.

    Both halves are written in one undo step, because either one alone is a
    fault: a record with no glyph draws nothing, and a glyph with no record is
    invisible.  The font is written first - if the record cannot be written
    afterwards the font still has a spare glyph, which harms nothing, whereas a
    record pointing at a code point that never got drawn is the exact bug the
    Decals page exists to report.
    """
    from rr3lib import decals as decallib
    from rr3lib import ttf as ttflib

    if not contours or not any(contours):
        raise EditError("a shape needs at least one contour with points in it")
    font_path = _decal_font_path(root)
    table_path = _decal_path(root)
    _begin(f"Add the shape U+{code_point:04X}")

    font = ttflib.load(font_path)
    had = font.glyph_of(code_point)
    font.add_glyph(code_point, contours, advance=advance)
    _backup(root, font_path)
    before_font = os.path.getsize(font_path)
    ttflib.save(font, font_path)
    sync_file(root, name="", rel_path="/" + decallib.FONT, local=font_path)

    table = decallib.load(os.path.join(root, ".depot"))
    if category == b"":
        category = b"GAMETEXT_CUSTOMISATION_DECALS_SHAPES_NAME"
    if name == b"":
        name = f"GAMETEXT_RRMOD_SHAPE_{code_point:04X}".encode("ascii")
    made = decallib.add(table, category=category, name=name,
                        glyph=decallib.code_point_text(code_point))
    if position >= 0:
        decallib.move(table, made.id, position)
    out = {"id": made.id, "record": made.describe(),
           "code_point": code_point, "replaced": had is not None,
           "font_before": before_font, "font_after": os.path.getsize(font_path)}
    out.update(_save_decals(root, table, table_path, f"new shape {code_point:04X}"))
    out["saved"] = True
    return out


def remove_decal_shape(root: str, decal_id: int) -> dict:
    """Drop the record, and empty the glyph if nothing else names it.

    The glyph index is kept, only its outline is cleared, so every other record
    and every other code point keeps the index it had.  A code point another
    record still names is left alone.
    """
    from rr3lib import decals as decallib
    from rr3lib import ttf as ttflib

    table_path = _decal_path(root)
    table = decallib.load(os.path.join(root, ".depot"))
    got = table.by_id(decal_id)
    if got is None:
        raise EditError(f"there is no decal {decal_id}")
    code = got.code_point
    _begin(f"Remove the decal {decal_id}")
    decallib.remove(table, decal_id)
    out = {"id": decal_id, "record": got.describe(), "cleared": False}
    if code is not None:
        still = [d for d in table.decals if d.code_point == code]
        if not still:
            font_path = _decal_font_path(root)
            font = ttflib.load(font_path)
            if font.remove_glyph(code):
                _backup(root, font_path)
                ttflib.save(font, font_path)
                sync_file(root, name="", rel_path="/" + decallib.FONT,
                          local=font_path)
                out["cleared"] = True
    out.update(_save_decals(root, table, table_path, f"removed decal {decal_id}"))
    out["saved"] = True
    return out


def set_wing_paint(root: str, name: str, *,
                   wing_part: str = "LOD_A_WING_REAR_mm_ext",
                   body_part: str = "LOD_A_BODY_mm_ext") -> dict:
    """Make a newly added wing use the body paint, per paint scheme."""
    _begin(f"Give the wing of {name} the body paint")
    depot = os.path.join(root, ".depot")
    L = liverylib.load_car(depot, name)
    table = liverylib.load_slot_table(depot)
    info = L.copy_body_paint(wing_part, body_part=body_part, table=table)
    path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                        f"{name}.liveries.bin.nct")
    _backup(root, path)
    liverylib.save(L, path)
    info["saved"] = path
    sync_file(root, name=name,
              rel_path=f"/vehicles/data/liveries/{name}.liveries.bin.nct",
              local=path)
    return info


def wing_parts(root: str, name: str, lod: str = "A") -> list:
    """The wing meshes a car's LOD A actually carries, in file order.

    Read from the model rather than guessed from a table: a car the studio gave
    a wing has meshes named ``LOD_A_WING_*``, one the studio left out has none,
    and only the file can tell the two apart.
    """
    from rr3lib import m3g as m3glib

    path = os.path.join(root, ".depot", "vehicles", name,
                        f"{name}_{lod.lower()}.m3g")
    if not os.path.isfile(path):
        return []
    out = []
    for obj in m3glib.M3G(path).of_type(14):
        mesh = obj.data.get("name") or ""
        if isinstance(mesh, bytes):
            mesh = mesh.decode("utf-8", "replace")
        if "WING" in mesh.upper() and mesh not in out:
            out.append(mesh)
    return out


def sync_wing_paint(root: str, name: str, *,
                    body_part: str = "LOD_A_BODY_mm_ext",
                    parts=None, log=print) -> dict:
    """Give a newly added wing the body's paint, but only where the car has none.

    The paint a part wears is decided by the livery table, not by the model: a
    wing slot with no row of its own falls back to ``car_flat``, which has no
    specular colour and a pure black fresnel ramp - the part renders nearly
    black.  Every shipped car with a body coloured wing solves it by writing the
    body's material into the wing's slot, scheme by scheme.

    ``parts`` limits the work to the meshes that were just added, which is what
    the two build branches pass: a shipped car that already carries a wing keeps
    the rows the studio gave it, and only a wing this program brought in gets
    new ones.  Slots the car already covers are left alone either way, so a wing
    with its own paint (a carbon one, say) keeps it.
    """
    _begin(f"Give a wing of {name} new paint rows")
    depot = os.path.join(root, ".depot")
    table = liverylib.load_slot_table(depot)
    L = liverylib.load_car(depot, name)
    out = {"car": name, "parts": [], "added": [], "kept": [], "no_slot": [],
           "changed": [], "saved": ""}
    wanted = list(parts) if parts is not None else wing_parts(root, name)
    for part in wanted:
        out["parts"].append(part)
        slot = table.part_slot(part)
        if slot is None:
            out["no_slot"].append(part)
            continue
        covered = any(p.material_of(slot) is not None for p in L.paints)
        if covered:
            out["kept"].append(part)
            continue
        try:
            info = L.copy_body_paint(part, body_part=body_part, table=table)
        except liverylib.LiveryError as exc:
            out["no_slot"].append(part)
            log(f"  {part}: {exc}")
            continue
        out["added"].append(part)
        out["changed"].extend(info["changed"])
        log(f"  {part} <- {body_part} in {len(info['changed'])} scheme(s)")
    if not out["added"]:
        return out
    path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                        f"{name}.liveries.bin.nct")
    _backup(root, path)
    liverylib.save(L, path)
    out["saved"] = path
    sync_file(root, name=name,
              rel_path=f"/vehicles/data/liveries/{name}.liveries.bin.nct",
              local=path)
    return out


# --------------------------------------------------------------- whole cars
def set_paint_finish(root: str, name: str, *, material: str = "",
                     colours=None, body_part: str = "LOD_A_BODY_mm_ext",
                     wing_part: str = "LOD_A_WING_REAR_mm_ext",
                     per_paint=None) -> dict:
    """Give a car's paint schemes a different finish, and/or a new colour.

    ``material`` is one of the finishes ``custom.paints.nct`` lists
    (``car_paint_matte`` and friends); it is written into the body slot of every
    scheme, and into the wing slot when the car has one, so the wing keeps
    matching the body.

    ``colours`` maps a paint index to ``(r, g, b)``.  It only sets the colour the
    game's customiser starts from - the shipped atlases still draw the car - so
    leaving a scheme out keeps whatever colour it already had.

    ``per_paint`` maps a paint index to a material name and overrides ``material``
    for that scheme alone, which is what a car with one gloss and one matte
    factory colour needs.  A scheme not mentioned keeps the donor's material.
    """
    _begin(f"Change the paint finish of {name}")
    depot = os.path.join(root, ".depot")
    L = liverylib.load_car(depot, name)
    table = liverylib.load_slot_table(depot)
    out = {"car": name, "material": material, "body_slot": None,
           "wing_slot": None, "recoloured": [], "unknown_material": ""}
    if material:
        mat_slot = table.material_slot(material)
        if mat_slot is None:
            out["unknown_material"] = material
            raise EditError(f"{material!r} is not in the livery string table, so "
                            f"no mesh can be pointed at it")
        body_slot = table.part_slot(body_part)
        if body_slot is None:
            raise EditError(f"{body_part!r} has no slot")
        wing_slot = table.part_slot(wing_part)
        out["body_slot"] = body_slot
        out["wing_slot"] = wing_slot
        for p in L.paints:
            p.set_material(body_slot, mat_slot)
            if wing_slot is not None:
                p.set_material(wing_slot, mat_slot)
    for index, wanted in (per_paint or {}).items():
        index = int(index)
        if not wanted or not 0 <= index < len(L.paints):
            continue
        mat_slot = table.material_slot(wanted)
        if mat_slot is None:
            raise EditError(f"{wanted!r} is not in the livery string table, so "
                            f"no mesh can be pointed at it")
        body_slot = table.part_slot(body_part)
        wing_slot = table.part_slot(wing_part)
        paint = L.paints[index]
        if body_slot is not None:
            paint.set_material(body_slot, mat_slot)
        if wing_slot is not None:
            paint.set_material(wing_slot, mat_slot)
        out.setdefault("per_paint", {})[paint.name()] = wanted
    for index, rgb in (colours or {}).items():
        index = int(index)
        if not 0 <= index < len(L.paints):
            continue
        r, g, b = (max(0, min(255, int(v))) for v in tuple(rgb)[:3])
        paint = L.paints[index]
        if bytes((r, g, b)) != paint.rgb:
            paint.rgb = bytes((r, g, b))
            out["recoloured"].append(paint.name())
    path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                        f"{name}.liveries.bin.nct")
    _backup(root, path)
    liverylib.save(L, path)
    out["saved"] = path
    out["paints"] = len(L.paints)
    sync_file(root, name=name,
              rel_path=f"/vehicles/data/liveries/{name}.liveries.bin.nct",
              local=path)
    return out


def set_livery_texture(root: str, name: str, *, source: str,
                       paint: int | None = None, slot: int = 1932) -> dict:
    """Point one paint scheme's atlas at a picture of your own.

    ``slot`` is a texture slot in the livery string table - 1932 is the body
    atlas (``ext_ext``), 1939 the interior's copy of it.  ``paint`` is the index
    of the scheme, or ``None`` for every scheme at once.

    The picture is copied into the car's ``livery/`` folder under the name the
    game expects (``<car>_ext_<stem><suffix>``), so the override names a file
    that exists.  The suffix is kept from the source: the four GPU families are
    told apart by it, and a car whose other atlases are ``.ptc.pvr.z`` should
    keep that family.
    """
    depot = os.path.join(root, ".depot")
    if not os.path.isfile(source):
        raise EditError(f"{source} does not exist")
    L = liverylib.load_car(depot, name)
    table = liverylib.load_slot_table(depot)
    if slot >= len(table):
        raise EditError(f"texture slot {slot} is not in the livery string table")
    suffix = ""
    low = os.path.basename(source).lower()
    for known in (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z",
                  ".dds.z", ".pvr.z"):
        if low.endswith(known):
            suffix = os.path.basename(source)[-len(known):]
            break
    if not suffix:
        raise EditError(f"{os.path.basename(source)} is not a game texture "
                        f"(expected .dxt.dds.z, .etc.dds.z, .atc.dds.z or .ptc.pvr.z)")
    stem = os.path.basename(source)[:-len(suffix)]
    # keep the scheme's own stem when only one scheme is being changed, so two
    # schemes cannot overwrite each other's file
    if paint is not None:
        try:
            stem = L.paints[int(paint)].name().rsplit(".", 1)[0]
        except (IndexError, AttributeError):
            pass
    target_rel = f"livery/{name}_ext_{stem}{suffix}"
    target = os.path.join(depot, "vehicles", name, *target_rel.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    _begin(f"Change a texture page of {name}")
    if os.path.isfile(target):
        _backup(root, target)
    shutil.copyfile(source, target)
    rel_bytes = target_rel.encode("ascii", "replace")
    out = {"car": name, "slot": slot, "file": target, "rel": target_rel,
           "changed": []}
    for i, p in enumerate(L.paints):
        if paint is not None and i != int(paint):
            continue
        if p.set_texture(slot, rel_bytes):
            out["changed"].append(p.name())
    if out["changed"]:
        path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                            f"{name}.liveries.bin.nct")
        _backup(root, path)
        liverylib.save(L, path)
        out["saved"] = path
        sync_file(root, name=name,
                  rel_path=f"/vehicles/data/liveries/{name}.liveries.bin.nct",
                  local=path)
    sync_file(root, name=name,
              rel_path=f"/vehicles/{name}/{target_rel}", local=target,
              create=True)
    return out


def _write_page(root: str, car: str, rel: str, source: str, *,
                prefer: str = "", family_key: str = "") -> dict:
    """Put ``source`` at ``rel`` in the car's folder, encoding a picture.

    One place for "a picture or a page becomes the file the game loads", used by
    the build's texture table and by a paint scheme's own pictures.  The picture
    is encoded into the family ``prefer`` names when that family can be written
    (it is the copy the livery already asks for), otherwise into the family the
    settings name.  A page is copied as it is.
    """
    from rr3lib import texport as texlib

    from . import texslots as texlib2

    depot = os.path.join(root, ".depot")
    target = os.path.join(depot, "vehicles", car, *rel.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    _backup(root, target)
    if texlib2.is_picture(source):
        suffix = texlib2.page_suffix(rel) or texlib2.family_suffix(
            root, prefer=prefer, key=family_key)
        if not rel.lower().endswith(suffix.lower()):
            raise EditError(f"{rel} is not a {suffix} name")
        made = texlib.import_picture(source, target, suffix=suffix)
        # the art is kept beside the working copy, so a publish can carry the
        # picture rather than this device's encoding of it
        try:
            from . import textures as texmod

            made["source"] = texmod.keep_source(
                root, f"vehicles/{car}/{rel}", source)
        except Exception:                        # noqa: BLE001 - not fatal
            made["source"] = ""
    else:
        shutil.copyfile(source, target)
        made = {"path": target, "bytes": os.path.getsize(target),
                "width": 0, "height": 0, "suffix": texlib2.page_suffix(rel)}
    sync_file(root, name=car, rel_path=f"/vehicles/{car}/{rel}",
              local=target, create=True)
    made["target"] = target
    made["rel"] = rel
    return made


def install_textures(root: str, car: str, items, *, family_key: str = "",
                     log=print) -> dict:
    """Fill the car's own texture slots from a build folder.

    ``items`` is ``[{slot, stem, source, place}]`` - ``place`` is ``"car"`` for a
    page of the car's own (the only kind this writes).  The target name is the
    game's: ``misc.png`` becomes ``<car>_misc.dxt.dds.z``, the same rule
    :mod:`rrmod.slots` applies to ``LOD_A.m3g``.

    A picture is encoded here, at build time, never when the folder was scanned:
    a build the user cancels must not have written a byte.  The livery row is
    pointed at the file that was actually written, because the row may have named
    a PVRTC copy this depot does not hold and PVRTC cannot be encoded.
    """
    from . import texslots as texlib2

    depot = os.path.join(root, ".depot")
    out = {"car": car, "written": [], "slots": [], "saved": ""}
    if not items:
        return out
    L = liverylib.load_car(depot, car)
    path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                        f"{car}.liveries.bin.nct")
    changed = False
    for item in items:
        source = item.get("source") or ""
        stem = str(item.get("stem") or "").strip()
        if not source or not stem or not os.path.isfile(source):
            continue
        suffix = (texlib2.page_suffix(source) if not texlib2.is_picture(source)
                  else "")
        prefer = ""
        slot = item.get("slot")
        if slot is not None:
            for s, raw in L.textures:
                if int(s) == int(slot):
                    prefer = texlib2.page_suffix(raw.decode("utf-8", "replace"))
                    break
        if not suffix:
            suffix = texlib2.family_suffix(root, prefer=prefer, key=family_key)
        rel = texlib2.target_rel(car, stem, suffix, place="car")
        made = _write_page(root, car, rel, source, prefer=prefer,
                           family_key=family_key)
        out["written"].append(made)
        if slot is not None and L.set_texture(int(slot),
                                              rel.encode("ascii", "replace")):
            changed = True
            out["slots"].append(texlib2._slot_name(depot, slot) or str(slot))
        log(f"  {os.path.basename(source):32s} -> {rel}")
    if changed:
        _backup(root, path)
        liverylib.save(L, path)
        out["saved"] = path
        sync_file(root, name=car,
                  rel_path=f"/vehicles/data/liveries/{car}.liveries.bin.nct",
                  local=path)
    return out


def set_paint_pictures(root: str, car: str, paint: int, pictures: dict, *,
                       tag: str = "", family_key: str = "",
                       log=print) -> dict:
    """Give one paint scheme its own pictures.

    ``pictures`` is ``{key: source}`` where ``key`` is ``"body"`` for the body
    atlas or a page stem (``"wheel"``, ``"misc"``) for a slot the scheme
    overrides.  The body key writes one file and points **both** slots at it -
    ``ext_ext`` and ``int_ext`` - which is what every shipped scheme does.

    A scheme's body picture lives in the car's ``livery/`` folder as
    ``<car>_ext_<tag><suffix>``, ``tag`` being the colour word (``red``,
    ``dark_blue``), so the name says what the picture is.  Any other slot goes
    in the car's own folder as ``<car>_<page>_<tag><suffix>``, which is where
    the shipped schemes keep theirs (``2013_astonmartin_vantage_wheel_
    lightweight``).  ``tag`` left out is taken from the scheme's own colour.

    A picture is encoded when this runs, which is what makes the Build dialog
    convert on Build and the Cars page convert on Save.
    """
    from . import texslots as texlib2

    depot = os.path.join(root, ".depot")
    L = liverylib.load_car(depot, car)
    if not 0 <= int(paint) < len(L.paints):
        raise EditError(f"paint scheme {paint} does not exist "
                        f"({car} has {len(L.paints)})")
    row = L.paints[int(paint)]
    tag = tag or texlib2.colour_word(row.rgb)
    tag = texlib2.clean_stem(tag) or "paint"
    body = texlib2.body_slot(depot)
    interior = texlib2.interior_slot(depot)
    by_stem = {r["stem"]: r for r in texlib2.car_pages(depot, car)}
    out = {"car": car, "paint": int(paint), "name": row.name(),
           "written": [], "slots": [], "saved": ""}
    changed = False
    for key, source in (pictures or {}).items():
        source = str(source or "")
        if not source or not os.path.isfile(source):
            continue
        if key == "body":
            slots = [body, interior]
            stem = f"ext_{tag}"
            place = "livery"
        else:
            row_info = by_stem.get(str(key))
            if row_info is None or row_info.get("slot") is None:
                raise EditError(f"{car} has no texture slot called {key!r}")
            slots = [int(row_info["slot"])]
            # the car's own folder, next to the page it stands in for: that is
            # where every shipped scheme keeps a wheel or a badge of its own
            stem = f"{key}_{tag}"
            place = "car"
        prefer = ""
        for s, raw in row.overrides:
            if int(s) in slots:
                prefer = texlib2.page_suffix(raw.decode("utf-8", "replace"))
                break
        if not prefer:
            for s, raw in L.textures:
                if int(s) in slots:
                    prefer = texlib2.page_suffix(raw.decode("utf-8", "replace"))
                    break
        suffix = (texlib2.page_suffix(source) if not texlib2.is_picture(source)
                  else texlib2.family_suffix(root, prefer=prefer,
                                             key=family_key))
        rel = texlib2.target_rel(car, stem, suffix, place=place)
        made = _write_page(root, car, rel, source, prefer=prefer,
                           family_key=family_key)
        made["key"] = key
        out["written"].append(made)
        for slot in slots:
            if row.set_texture(int(slot), rel.encode("ascii", "replace")):
                changed = True
                out["slots"].append(texlib2._slot_name(depot, slot) or str(slot))
        log(f"  {os.path.basename(source):32s} -> {rel}")
    if changed:
        path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                            f"{car}.liveries.bin.nct")
        _backup(root, path)
        liverylib.save(L, path)
        out["saved"] = path
        sync_file(root, name=car,
                  rel_path=f"/vehicles/data/liveries/{car}.liveries.bin.nct",
                  local=path)
    return out


def add_common_picture(root: str, picture: str, *, label: str = "",
                       stem: str = "", family_key: str = "",
                       log=print) -> dict:
    """Encode a picture and add it to ``vehicles/common`` under a label.

    The label is what makes the name: shipped pages are ``car_tyre_slick_03``,
    ``car_windows_cracked_02``, so a picture added under ``tyre`` becomes
    ``car_tyre_04`` - the next free number of that label - and the Dependencies
    page can say what it is.  A ``stem`` given by the caller wins, which is how
    a page that already has a name keeps it.
    """
    from rr3lib import texport as texlib

    from . import texslots as texlib2

    if not os.path.isfile(picture):
        raise EditError(f"{picture} does not exist")
    depot = os.path.join(root, ".depot")
    suffix = texlib2.family_suffix(root, key=family_key)
    folder = os.path.join(depot, *COMMON_DIR.split("/"))
    os.makedirs(folder, exist_ok=True)
    name = texlib2.clean_stem(stem) if stem else ""
    if not name:
        word = texlib2.clean_stem(label) or "page"
        taken = {texlib2.stem_of(leaf) for leaf in os.listdir(folder)}
        n = 1
        while f"car_{word}_{n:02d}" in taken:
            n += 1
        name = f"car_{word}_{n:02d}"
    staged = os.path.join(historylib.scratch(root), "_page_" + name + suffix)
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    made = texlib.import_picture(picture, staged, suffix=suffix)
    try:
        got = add_common_page(root, staged, stem=name, log=log)
    finally:
        try:
            os.remove(staged)
        except OSError:
            pass
    try:
        from . import textures as texmod

        made["source"] = texmod.keep_source(
            root, f"common/{name}{suffix}", picture)
    except Exception:                            # noqa: BLE001
        made["source"] = ""
    got.update({"name": name, "suffix": suffix, "width": made["width"],
                "height": made["height"], "bytes": made["bytes"],
                "label": texlib2.clean_stem(label)})
    return got


def add_paint_scheme(root: str, name: str, *, livery_name: str = "",
                     copy_from: int = 0, source: str = "",
                     slot: int = 1932, pictures: dict | None = None,
                     tag: str = "", family_key: str = "") -> dict:
    """Add a paint scheme to a car, optionally pointing it at pictures.

    A scheme is one row of ``<car>.liveries.bin.nct``; the game reads however
    many rows there are, so adding one is a matter of appending a copy and (if
    you want it to look different) giving it its own body atlas.  The copy
    starts from ``copy_from`` - colour, finish and materials come along - so the
    new scheme is immediately usable and only the parts you change differ.

    ``livery_name`` is the row's own name (``07_<car>.livery``); left empty it
    continues the numbering of the shipped rows.  ``source`` is a game texture
    to use as this scheme's body atlas, copied into the car's ``livery/`` folder
    by :func:`set_livery_texture`; ``pictures`` is the newer form - ``{key:
    picture}`` with ``"body"`` and any page stem - and is applied by
    :func:`set_paint_pictures`, which also encodes a PNG.

    Returns ``{"index", "name", "atlas", "saved"}``.
    """
    depot = os.path.join(root, ".depot")
    path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                        f"{name}.liveries.bin.nct")
    if not os.path.isfile(path):
        raise EditError(f"{name} has no livery table to add a scheme to")
    L = liverylib.load_car(depot, name)
    _begin(f"Add a paint scheme to {name}")
    # An empty name continues the shipped numbering; cloning without one would
    # leave two rows called 02_<car>.livery, and the frontend keys the list by
    # that string.
    paint = L.clone_paint(int(copy_from),
                          name=livery_name or L.next_paint_name())
    index = len(L.paints) - 1
    _backup(root, path)
    liverylib.save(L, path)
    out = {"car": name, "index": index, "name": paint.name(),
           "atlas": "", "saved": path}
    sync_file(root, name=name,
              rel_path=f"/vehicles/data/liveries/{name}.liveries.bin.nct",
              local=path)
    if pictures:
        got = set_paint_pictures(root, name, index, pictures, tag=tag,
                                 family_key=family_key)
        out["pictures"] = got
        out["atlas"] = next((w["rel"] for w in got["written"]
                             if w.get("key") == "body"), out["atlas"])
        out["saved"] = got.get("saved") or path
    if source:
        got = set_livery_texture(root, name, source=source, paint=index,
                                 slot=slot)
        out["atlas"] = got.get("rel", "")
        out["saved"] = got.get("saved", path)
    return out


def remove_paint_scheme(root: str, name: str, indexes) -> dict:
    """Drop one or more paint schemes from a car.

    The game reads however many rows the livery table has, in order, and nothing
    else in the file refers to a scheme by index - so removing one is a matter
    of writing the table without it.  **The last scheme is refused**: a car with
    no rows at all comes out of the showroom unpainted, which is not something
    an "undo" button can explain afterwards.

    The atlases the removed schemes pointed at are left on disk: two schemes can
    share one picture, and a file nothing names costs a few kilobytes while a
    picture deleted out from under a scheme that still uses it is a car with a
    white body.
    """
    depot = os.path.join(root, ".depot")
    path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                        f"{name}.liveries.bin.nct")
    if not os.path.isfile(path):
        raise EditError(f"{name} has no livery table")
    L = liverylib.load_car(depot, name)
    total = len(L.paints)
    wanted = sorted({int(i) for i in indexes})
    if not wanted:
        raise EditError("no paint scheme was chosen")
    for index in wanted:
        if not 0 <= index < total:
            raise EditError(f"paint scheme {index} does not exist "
                            f"({name} has {total})")
    if len(wanted) >= total:
        raise EditError(
            f"{name} has {total} paint scheme(s) and all of them were chosen - a "
            f"car needs at least one, so nothing was removed")
    _begin(f"Remove {len(wanted)} paint scheme(s) from {name}")
    _backup(root, path)
    gone = [L.paints[i] for i in wanted]
    L.paints = [p for i, p in enumerate(L.paints) if i not in set(wanted)]
    liverylib.save(L, path)
    sync_file(root, name=name,
              rel_path=f"/vehicles/data/liveries/{name}.liveries.bin.nct",
              local=path)
    return {"car": name, "removed": [p.name() for p in gone],
            "indexes": wanted, "left": len(L.paints), "saved": path}


def set_texture_slot(root: str, name: str, slot: int, source: str, *,
                     paint: int | None = None) -> dict:
    """Point one *texture slot* at a page of your own.

    This is the other half of "a different tyre, disc or carbon weave": a mesh
    tag like ``_mm_tyre`` samples ``ext_tyre`` (slot 4), and every mesh that
    shares the tag reads the same page.  Writing the slot changes all of them,
    and leaves the materials alone.

    ``source`` is a game texture (``.dxt.dds.z``, ``.etc.dds.z``,
    ``.atc.dds.z`` or ``.ptc.pvr.z``).  It is copied into the car's folder under
    a name built from the slot, so several slots can be changed at once without
    colliding.  ``paint`` limits the change to one scheme; left out the car-wide
    row is written, which is what a tyre or a disc wants.
    """
    depot = os.path.join(root, ".depot")
    if not os.path.isfile(source):
        raise EditError(f"{source} does not exist")
    L = liverylib.load_car(depot, name)
    table = liverylib.load_slot_table(depot)
    slot = int(slot)
    if not 0 <= slot < len(table):
        raise EditError(f"texture slot {slot} is not in the livery string table")
    suffix = ""
    low = os.path.basename(source).lower()
    for known in (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z",
                  ".dds.z", ".pvr.z"):
        if low.endswith(known):
            suffix = os.path.basename(source)[-len(known):]
            break
    if not suffix:
        raise EditError(f"{os.path.basename(source)} is not a game texture "
                        f"(expected .dxt.dds.z, .etc.dds.z, .atc.dds.z or .ptc.pvr.z)")
    stem = table[slot]
    if paint is not None:
        try:
            stem = f"{stem}_{L.paints[int(paint)].name().rsplit('.', 1)[0]}"
        except (IndexError, AttributeError):
            pass
    target_rel = f"livery/{name}_{stem}{suffix}"
    target = os.path.join(depot, "vehicles", name, *target_rel.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    _begin(f"Change a texture page of {name}")
    if os.path.isfile(target):
        _backup(root, target)
    shutil.copyfile(source, target)
    rel_bytes = target_rel.encode("ascii", "replace")
    out = {"car": name, "slot": slot, "slot_name": table[slot],
           "file": target, "rel": target_rel, "changed": []}
    if paint is not None:
        index = int(paint)
        if 0 <= index < len(L.paints) and L.paints[index].set_texture(slot, rel_bytes):
            out["changed"].append(L.paints[index].name())
    elif L.set_texture(slot, rel_bytes):
        out["changed"].append("(every scheme)")
    if out["changed"]:
        path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                            f"{name}.liveries.bin.nct")
        _backup(root, path)
        liverylib.save(L, path)
        out["saved"] = path
        sync_file(root, name=name,
                  rel_path=f"/vehicles/data/liveries/{name}.liveries.bin.nct",
                  local=path)
    sync_file(root, name=name,
              rel_path=f"/vehicles/{name}/{target_rel}", local=target,
              create=True)
    return out


def set_texture_slot_page(root: str, name: str, slot: int, page: str, *,
                          paint: int | None = None) -> dict:
    """Point a texture slot at a page the game already ships.

    This is the same edit as :func:`set_texture_slot` without the copy: the
    picture is already in ``vehicles/common``, so all that changes is the row in
    the car's livery table.  A different tyre, disc or interior weave is
    therefore free - no new bytes go into the car's folder and nothing has to be
    pushed but the livery table itself.

    ``page`` is a stem (``common/car_tyre_slick_michelin_03``) or a leaf
    (``car_tyre_slick_michelin_03.dxt.dds.z``); the GPU family is taken from the
    row the slot holds now, then from the shipped default table, because the
    engine resolves a page by its stem and the family is only which copy of it
    the device unpacks.
    """
    depot = os.path.join(root, ".depot")
    L = liverylib.load_car(depot, name)
    table = liverylib.load_slot_table(depot)
    slot = int(slot)
    if not 0 <= slot < len(table):
        raise EditError(f"texture slot {slot} is not in the livery string table")
    stem = str(page or "").strip().replace("\\", "/").lstrip("/")
    if stem.startswith("vehicles/"):
        stem = stem[len("vehicles/"):]
    if not stem.startswith("common/"):
        raise EditError(f"{page!r} is not a page of vehicles/common")
    stem = stem[len("common/"):]
    for suffix in (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z",
                   ".rgb.pvr.z", ".dds.z", ".pvr.z"):
        if stem.lower().endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    folder = os.path.join(depot, "vehicles", "common")
    found = ""
    # ``.rgb.pvr.z`` is in the list because the shared folder is not all block
    # data: a few pages ship as plain PVRTC, and leaving that suffix out made a
    # page that is plainly there read as "vehicles/common holds no page called
    # ...".  Measured on the retail depot: 304 shared pages, all of them DXT, but
    # a modded install can hold either.
    for suffix in PAGE_FAMILIES:
        if os.path.isfile(os.path.join(folder, stem + suffix)):
            found = stem + suffix
            break
    if not found:
        raise EditError(f"vehicles/common holds no page called {stem}")
    family = ""
    current = dict(L.textures).get(slot)
    if current:
        family = _family_of_page(current.decode("ascii", "replace"))
    if not family:
        try:
            shipped = dict(liverylib.load_default(depot).textures).get(slot)
        except Exception:                        # noqa: BLE001
            shipped = None
        if shipped:
            family = _family_of_page(shipped.decode("ascii", "replace"))
    # The family the row *names* is not always the family the depot *has*: a
    # livery authored for the PTC build says ``.ptc.pvr.z`` and the unpacked
    # install holds the DXT set.  Writing the inherited name then points the slot
    # at a file nobody has, and the game draws the part as nothing - so the file
    # that is really there wins over the name that was expected.
    if family and not os.path.isfile(os.path.join(folder, stem + family)):
        family = os.path.splitext(os.path.splitext(found)[0])[1] or family
        family = found[len(stem):]
    if not family:
        family = found[len(stem):]
    rel = f"common/{stem}{family}"
    rel_bytes = rel.encode("ascii", "replace")
    _begin(f"Point a texture page of {name} at a shared one")
    out = {"car": name, "slot": slot, "slot_name": table[slot],
           "page": rel, "on_disk": f"vehicles/common/{found}", "changed": []}
    if paint is not None:
        index = int(paint)
        if 0 <= index < len(L.paints) and L.paints[index].set_texture(slot, rel_bytes):
            out["changed"].append(L.paints[index].name())
    elif L.set_texture(slot, rel_bytes):
        out["changed"].append("(every scheme)")
    if out["changed"]:
        path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                            f"{name}.liveries.bin.nct")
        _backup(root, path)
        liverylib.save(L, path)
        out["saved"] = path
        sync_file(root, name=name,
                  rel_path=f"/vehicles/data/liveries/{name}.liveries.bin.nct",
                  local=path)
    return out


def _family_of_page(page: str) -> str:
    """The GPU family suffix of a page name, or ``""``."""
    low = page.lower()
    for suffix in PAGE_FAMILIES:
        if low.endswith(suffix):
            return page[-len(suffix):]
    return ""


#: Every suffix a page can carry, longest first so ``.dxt.dds.z`` is not read as
#: ``.z``.  One list, because three places had their own and one of them was
#: missing ``.rgb.pvr.z`` - which made a page that was plainly on disk report as
#: missing.
PAGE_FAMILIES = (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z",
                 ".rgb.pvr.z")


#: Where a page can live, in the words the UI uses.
#:
#: ``common/`` is shared with every car that names it, so it is written once and
#: costs nothing per car - but a car cannot own it, and deleting it later has to
#: ask who still wants it.  A car's own folder is the opposite: it belongs to
#: that car alone, which is what a one-off page (a caliper, a badge, a livery
#: detail) should be.
PAGE_PLACES = ("common", "car")


def page_rel_of(leaf: str, where: str = "common") -> str:
    """``("car_windows_04.dxt.dds.z", "common")`` -> ``common/car_windows_04...``.

    The row a livery table holds is the path **relative to the vehicle folder**:
    ``common/x.dxt.dds.z`` for a shared page, ``<car>_misc.dxt.dds.z`` for one of
    the car's own.  Paint schemes are the exception and live under ``livery/``,
    which this never produces - a scheme is chosen by the paint UI, not here.
    """
    leaf = str(leaf or "").strip().replace("\\", "/").lstrip("/")
    if leaf.startswith("vehicles/"):
        leaf = leaf[len("vehicles/"):]
    if leaf.startswith("common/"):
        return leaf
    if where == "car":
        return leaf
    return "common/" + leaf


def set_texture_page(root: str, car: str, slot: int, rel: str, *,
                     paint: int | None = None) -> dict:
    """Point a texture slot at any page path - shared or the car's own.

    :func:`set_texture_slot_page` is the common-only case of this, kept because
    it also picks the GPU family from the row it is replacing.  Here the path is
    taken as given, which is what the page picker needs: the user has already
    chosen *which* file and *where* it lives, and second-guessing either would
    write a row that names a page nobody can find.

    ``rel`` is relative to the vehicle folder, exactly as a livery stores it.
    It is checked against the working copy before the row is written, because a
    row naming a missing page is a texture the game draws as nothing at all -
    and the check is the only thing that tells the two apart.
    """
    depot = os.path.join(root, ".depot")
    L = liverylib.load_car(depot, car)
    table = liverylib.load_slot_table(depot)
    slot = int(slot)
    if not 0 <= slot < len(table):
        raise EditError(f"texture slot {slot} is not in the livery string table")
    rel = str(rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise EditError("a page needs a path")
    if ".." in rel.split("/"):
        raise EditError(f"refusing a path that climbs out: {rel}")
    bases = [os.path.join(depot, "vehicles", car), os.path.join(depot, "vehicles")]
    found = ""
    for base in bases:
        candidate = os.path.join(base, *rel.split("/"))
        if os.path.isfile(candidate):
            found = candidate
            break
    if not found:
        # The row names one GPU family and the install holds another: a livery
        # written for the PTC build says ``.ptc.pvr.z`` while the unpacked depot
        # has the DXT set.  Naming a file nobody has makes the game draw the slot
        # as nothing, so the same stem in a family that *is* here is written
        # instead - the picture is the same one, only the copy differs.
        stem = rel
        for suffix in PAGE_FAMILIES:
            if rel.lower().endswith(suffix):
                stem = rel[:-len(suffix)]
                break
        if stem != rel:
            for base in bases:
                for suffix in PAGE_FAMILIES:
                    candidate = os.path.join(base, *stem.split("/")) + suffix
                    if os.path.isfile(candidate):
                        found = candidate
                        rel = os.path.relpath(candidate, base).replace("\\", "/")
                        if base.endswith("vehicles"):
                            rel = rel.split("/", 1)[-1] if "/" in rel else rel
                        break
                if found:
                    break
    if not found:
        raise EditError(f"{rel} is not in the install, so the game would "
                        f"draw this slot as nothing")
    rel_bytes = rel.encode("ascii", "replace")
    _begin(f"Point a texture page of {car} at {rel}")
    out = {"car": car, "slot": slot, "slot_name": table[slot], "page": rel,
           "path": found, "changed": []}
    if paint is not None:
        index = int(paint)
        if 0 <= index < len(L.paints) and L.paints[index].set_texture(slot, rel_bytes):
            out["changed"].append(L.paints[index].name())
    elif L.set_texture(slot, rel_bytes):
        out["changed"].append("(every scheme)")
    if out["changed"]:
        path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                            f"{car}.liveries.bin.nct")
        _backup(root, path)
        liverylib.save(L, path)
        out["saved"] = path
        sync_file(root, name=car,
                  rel_path=f"/vehicles/data/liveries/{car}.liveries.bin.nct",
                  local=path)
    return out


def add_car_page(root: str, car: str, source: str, *, stem: str = "",
                 log=print) -> dict:
    """Put a texture into the car's own folder and book it in that car's list.

    The mirror image of :func:`add_common_page`: the page belongs to one car, so
    it goes next to that car's ``.m3g`` files and its row goes in
    ``asset_list_vehicle_<car>.txt``.  Nothing else in the game learns about it,
    which is the point - a page only this car needs should not have to be shared
    with 539 others.

    ``source`` is a finished game texture (already encoded); the family comes
    from its suffix.
    """
    if not os.path.isfile(source):
        raise EditError(f"{source} does not exist")
    base = os.path.basename(source)
    suffix = ""
    for known in (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z"):
        if base.lower().endswith(known):
            suffix = base[-len(known):]
            break
    if not suffix:
        raise EditError(f"{base} is not a game texture (expected .dxt.dds.z, "
                        f".etc.dds.z, .atc.dds.z or .ptc.pvr.z)")
    stem = (stem or base[:-len(suffix)]).strip("/")
    if not stem:
        raise EditError("a page needs a name")
    if "/" in stem:
        raise EditError(f"{stem!r} cannot have a folder in it - a page of the "
                        f"car's own lives directly beside its models")
    _begin(f"Add the page {stem} to {car}")
    depot = os.path.join(root, ".depot")
    folder = os.path.join(depot, "vehicles", car)
    os.makedirs(folder, exist_ok=True)
    leaf = stem + suffix
    target = os.path.join(folder, leaf)
    if os.path.abspath(source) != os.path.abspath(target):
        _backup(root, target)
        shutil.copyfile(source, target)
    rel = f"/vehicles/{car}/{leaf}"
    out = sync_file(root, name=car, rel_path=rel, local=target, create=True)
    out["target"] = target
    out["stem"] = stem
    out["rel"] = leaf
    out["where"] = "car"
    log(f"  {rel} ({os.path.getsize(target):,} B)")
    return out


def set_part_material(root: str, name: str, mesh_slot: int, material: str, *,
                      paints=None) -> dict:
    """Point one mesh at a material, for the car or for named paint schemes.

    ``mesh_slot`` is the livery slot of the *mesh* (``LOD_A_BODY_mm_ext`` is 30),
    not of the material.  ``paints`` is a list of scheme indices to change; left
    empty the car-wide row is written, which every scheme inherits unless it
    overrides it.

    This is the answer to "the tyre texture lives in ``common/``": the material
    name is what the engine looks up, and the mesh's own material name in the
    ``.m3g`` is ignored.
    """
    depot = os.path.join(root, ".depot")
    L = liverylib.load_car(depot, name)
    table = liverylib.load_slot_table(depot)
    mat_slot = table.material_slot(material)
    if mat_slot is None:
        raise EditError(f"{material!r} is not in the livery string table")
    _begin(f"Give a part of {name} another material")
    out = {"car": name, "mesh_slot": int(mesh_slot), "material": material,
           "material_slot": mat_slot, "changed": []}
    if paints:
        for index in paints:
            index = int(index)
            if not 0 <= index < len(L.paints):
                continue
            if L.paints[index].set_material(int(mesh_slot), mat_slot):
                out["changed"].append(L.paints[index].name())
    elif L.set_material(int(mesh_slot), mat_slot):
        out["changed"].append("(every scheme)")
    if out["changed"]:
        path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                            f"{name}.liveries.bin.nct")
        _backup(root, path)
        liverylib.save(L, path)
        out["saved"] = path
        sync_file(root, name=name,
                  rel_path=f"/vehicles/data/liveries/{name}.liveries.bin.nct",
                  local=path)
    return out


def add_material(root: str, source: str, new_name: str, *,
                 template: str = "", rgba=None, flags=None,
                 log=print) -> dict:
    """Clone a material in ``materials.bin`` under a new name.

    The game's material library is one flat record stream of two tables - 296
    material instances, then 186 shader bindings - and a material *is* the first
    table's record block.  So a new material is a copy of an existing block with
    its instance name changed: everything else (application, cull and blend
    modes, stencil, flags) describes how the engine draws it, and copying them is
    what makes the clone an instance of the same template rather than an
    unbound name the shader lookup cannot resolve.

    ``template`` points the clone at another shader binding - that is how a
    matte-looking material can be made to shade like gloss.  ``rgba`` and
    ``flags`` override the two fields that are usually worth changing; ``flags``
    is a sequence of names (``("FOG", "SPEC_TEXTURE")``).

    The clone is appended at the end of the material table, which leaves every
    existing block where it was - the engine keys both tables by name, so order
    within a table does not matter, and appending is the only edit that cannot
    corrupt an offset.

    The file is rewritten whole and booked into ``asset_list_startup.txt`` and
    the registry, because a livery row naming a material the engine cannot find
    is a car that does not draw.
    """
    from rr3lib import gamematerial as matlib

    depot = os.path.join(root, ".depot")
    path = os.path.join(depot, *matlib.MATERIALS_BIN.split("/"))
    if not os.path.isfile(path):
        raise EditError(f"this install has no {matlib.MATERIALS_BIN}")
    new_name = (new_name or "").strip()
    if not new_name:
        raise EditError("a new material needs a name")
    if not all(32 <= ord(c) < 127 for c in new_name):
        raise EditError(f"{new_name!r} has characters the material table cannot "
                        f"hold; use plain ASCII")
    recs = matlib.load_records(path)
    spans = {n for _a, _b, n in matlib.block_spans(recs) if n}
    if source not in spans:
        raise EditError(f"there is no material called {source}")
    if new_name in spans:
        raise EditError(f"{new_name} is already a material")
    if template and template not in spans:
        raise EditError(f"there is no material called {template} to take the "
                        f"shader binding from")

    overrides = {}
    if rgba is not None:
        got = tuple(int(v) for v in rgba)
        if len(got) != 4 or not all(0 <= v <= 255 for v in got):
            raise EditError(f"{rgba!r} is not four numbers from 0 to 255")
        overrides[matlib.K_RGBA] = ", ".join(str(v) for v in got).encode("ascii")
    if flags is not None:
        wanted = [str(f).strip() for f in flags if str(f).strip()]
        overrides[matlib.K_FLAGS] = ", ".join(wanted).encode("ascii")

    _begin(f"Add the material {new_name}")
    blob = matlib.clone_block(recs, source, new_name,
                              template=template, overrides=overrides)
    grown = matlib.insert_block(recs, blob)
    was = 0
    install = _install_abs(root, matlib.MATERIALS_BIN)
    if install and os.path.isfile(install):
        was = os.path.getsize(install)
    _backup(root, path)
    with open(path, "wb") as fh:
        fh.write(grown)

    out = sync_file(root, name="", rel_path=f"/{matlib.MATERIALS_BIN}",
                    local=path)
    out["path"] = path
    out["material"] = new_name
    out["from"] = source
    out["template"] = template or source
    out["bytes"] = len(grown)
    out["added"] = len(grown) - was if was else 0
    out["slot"] = None
    # A material with no livery slot cannot be written into any car's table, so
    # the slot is added here rather than left for the caller to remember.
    try:
        table = liverylib.load_slot_table(depot)
        if table.slot(new_name) is None:
            added = add_slot_names(root, [new_name], log=log)
            out["slot"] = added.get("slots", {}).get(new_name)
            out["slot_saved"] = bool(added.get("saved"))
        else:
            out["slot"] = table.slot(new_name)
    except Exception as exc:                      # noqa: BLE001 - report, do not fail
        out["slot_error"] = str(exc)
    # The name has to be written down: an edit lands in the install, so "is this
    # one of the game's own" can no longer be answered by comparing with a
    # working copy, and a material that is not on this list is one this program
    # will refuse to remove.
    try:
        from . import publish as publishlib

        publishlib.mark_mine(root, new_name)
    except Exception as exc:                      # noqa: BLE001 - never fail a clone
        out["record_error"] = str(exc)
    log(f"  {new_name} ({out['added']:+,} B, copied from {source})")
    return out


def _install_abs(root: str, rel: str) -> str:
    """A path inside the install a working copy was made from, or ``""``.

    ``rel`` is a ``.depot`` relative path (``materials/materials.bin``); the
    ``.depot`` folder itself is added here, because the install root is the
    folder that holds ``.depot`` and ``apk`` side by side.
    """
    install = _install_of(root)
    if not install:
        return ""
    return os.path.join(install, ".depot", *rel.split("/"))


def remove_material(root: str, name: str, *, force: bool = False) -> dict:
    """Delete a material this program added, refusing while a car names it.

    A material the game shipped is never removed: the shipped ``materials.bin``
    has no free slot for it to come back to, and one that a car's livery row
    still points at is a car that stops drawing.
    """
    from rr3lib import gamematerial as matlib

    depot = os.path.join(root, ".depot")
    path = os.path.join(depot, *matlib.MATERIALS_BIN.split("/"))
    if not os.path.isfile(path):
        raise EditError(f"this install has no {matlib.MATERIALS_BIN}")
    # What the game shipped can no longer be read off the tree - the install *is*
    # the tree - so three answers, in order of how much they can prove:
    #   * a working copy left over from an older version can still compare;
    #   * otherwise the record of clones decides, and anything it does not name
    #     is treated as the game's own;
    #   * a folder with no record at all proves nothing, so `force` is the only
    #     way through - a material cloned before the record existed lands here.
    from . import publish as publishlib

    recorded = set(publishlib.mine(root))
    install = _install_abs(root, matlib.MATERIALS_BIN)
    shipped = set()
    if install and os.path.isfile(install) \
            and os.path.abspath(install) != os.path.abspath(path):
        shipped = {n for _a, _b, n in
                   matlib.block_spans(matlib.load_records(install)) if n}
        ours = name not in shipped
    elif recorded:
        ours = name in recorded
    else:
        ours = False
    if not ours and not force:
        raise EditError(
            f"{name} is one of the game's own materials - it is never removed, "
            f"whatever a car does with it. (A material this program cloned is "
            f"named in {os.path.basename(publishlib.mine_path(root))}; pass force "
            f"to remove one it does not name.)")
    recs = matlib.load_records(path)
    spans = {n: (a, b) for a, b, n in matlib.block_spans(recs)}
    if name not in spans:
        raise EditError(f"there is no material called {name}")
    users = _material_users(root, name)
    if users and not force:
        raise EditError(f"{name} is still used by {', '.join(users[:4])}"
                        + (f" and {len(users) - 4} more" if len(users) > 4 else "")
                        + "; point them at another material first, or pass force")
    _begin(f"Remove the material {name}")
    a, b = spans[name]
    kept = recs[:a] + recs[b:]
    _backup(root, path)
    with open(path, "wb") as fh:
        fh.write(matlib.encode_records(kept))
    out = sync_file(root, name="", rel_path=f"/{matlib.MATERIALS_BIN}", local=path)
    out["material"] = name
    out["users"] = users
    publishlib.unmark_mine(root, name)
    return out


def _material_users(root: str, name: str) -> list:
    """Which cars' livery tables name this material, as ``"<car>"`` strings."""
    depot = os.path.join(root, ".depot")
    folder = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"))
    if not os.path.isdir(folder):
        return []
    out = []
    try:
        table = liverylib.load_slot_table(depot)
    except Exception:                             # noqa: BLE001 - no table, no users
        return []
    slot = table.slot(name)
    if slot is None:
        return []
    for leaf in sorted(os.listdir(folder)):
        if not leaf.endswith(".liveries.bin.nct"):
            continue
        if leaf == "default.liveries.bin.nct":
            continue
        car = leaf[:-len(".liveries.bin.nct")]
        try:
            L = liverylib.load(os.path.join(folder, leaf))
        except Exception:                         # noqa: BLE001 - one bad table is not fatal
            continue
        if slot in set(s for _mesh, s in (L.materials or ())):
            out.append(car)
            continue
        for paint in L.paints or ():
            if slot in set(s for _mesh, s in (paint.materials or ())):
                out.append(car)
                break
    return out


def install_pack(root: str, pack, *, new_id: int = 0, donor: str = "",
                 name: str = "", aero: bool = True, appearance_id: int = 0,
                 model_token: str = "", aliases: bool = True,
                 paints=None, car_class: str = "", make: str = "",
                 slot_files: dict | None = None,
                 aero_kind: bytes = b"", aero_params=(),
                 wheel_sizes=None, log=print) -> dict:
    """Build a whole new car from a ``car.json`` pack and merge it in place.

    The build itself is :func:`rr3lib.car.build_car`, which writes a mirror;
    merging the mirror means copying its files over and recomputing the three
    manifests from what landed on disk, which is more robust than trusting the
    mirror's own bookkeeping.
    """
    from rr3lib import car as carlib

    name = name or pack.name
    donor = donor or pack.donor
    if not donor:
        raise EditError("a new car needs a donor")
    ident = pack.identity
    # A caller-supplied value wins over the pack's, so the dialog can offer the
    # fields without the pack having to carry them.
    if model_token:
        ident = dict(ident, model_token=model_token)
    if pack.kind == "new" and depotlib.scan(root).get(name) is not None:
        raise EditError(f"{name} is already installed - use the replace branch "
                        f"to change an existing car")
    new_id = new_id or 0
    if not new_id:
        inv_ids = carlib.used_ids(os.path.join(root, ".depot"))
        new_id = max(inv_ids) + 1
    if new_id in carlib.used_ids(os.path.join(root, ".depot")):
        raise EditError(f"car id {new_id} is already used")

    # ``tempfile.mkdtemp`` creates the folder with mode 0700, and on this Windows
    # host a directory made that way ends up with an ACL that refuses writes
    # inside it - every ``makedirs`` below then fails with WinError 5.  A plain
    # directory with the default ACL works, so the staging folder is made by hand
    # and removed by hand.
    _begin(f"Build {name}")
    staging = os.path.join(historylib.scratch(root), "_build")
    tmp = os.path.join(staging, "pack_" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    try:
        out = carlib.build_car(
            os.path.join(root, ".depot"), root, tmp,
            new_id=new_id, new_name=name, donor_name=donor,
            body_m3g=pack.body() or None,
            extra=[p for k, p in pack.files().items()
                   if k not in ("A", "B", "C", "D", "E", "F", "G", "H",
                                "shared", "int_a", "int_b", "frontend")],
            display_key=ident.get("display_key", ""),
            model_token=ident.get("model_token", ""),
            appearance_id=int(appearance_id) or None,
            aero=aero, aliases=aliases, paints=paints, car_class=car_class,
            make=make, slot_files=slot_files,
            aero_kind=aero_kind, aero_params=aero_params,
            wheel_sizes=wheel_sizes, log=log)
        merged = _merge_mirror(root, tmp, name)
        # the build wrote its paths against the staging folder, which is about to
        # be deleted - point them at the copies that just landed in the install
        for key in ("spec", "livery"):
            if out.get(key):
                out[key] = os.path.join(root, os.path.relpath(out[key], tmp))
        if out.get("folder", {}).get("dir"):
            out["folder"]["dir"] = os.path.join(
                root, os.path.relpath(out["folder"]["dir"], tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out["merged"] = merged
    # A part whose name is not in the string table is skipped by the engine, and
    # the only symptom is a part that is not there.  Say so while the build is
    # still on screen; the Parts tab is where it gets fixed (borrow a shipped
    # name), not here.
    try:
        from . import materials as matlib

        found = matlib.audit(root, name)
        out["skipped_parts"] = found["skipped"]
        for row in found["skipped"][:10]:
            log(f"  ! {row['mesh']} ({row['model']}) has no livery slot - "
                f"the engine will skip it")
        extra = len(found["skipped"]) - 10
        if extra > 0:
            log(f"  ! ... and {extra} more; see the Parts tab")
    except Exception:                           # noqa: BLE001
        pass
    return out


def set_wheel_sizes(root: str, name: str, values: dict, *,
                    log=print) -> dict:
    """Write a car's front/rear wheel radii into its appearance record.

    ``values`` maps float index to metres: ``1``/``2`` the front tyre and rim
    radius, ``5``/``6`` the rear.  This is the *only* place the game reads the
    drawn wheel size from - the mesh supplies proportions, not size - so a car
    whose wheels came out too small is fixed here and nowhere else.

    Returns the before/after block so the caller can report what moved.
    """
    from rr3lib import wheelsize as wheelsizelib

    if not values:
        return {}
    _begin(f"Size the wheels of {name}")
    out = wheelsizelib.write_appearance_wheel_block(
        os.path.join(root, ".depot"), name, values)
    log(f"  wheels: {[round(v, 4) for v in out['from']]} -> "
        f"{[round(v, 4) for v in out['to']]}")
    return out


def install_slots(root: str, name: str, mapping: dict, *,
                  log=print) -> dict:
    """Put a slot table's files into an *existing* car folder, renaming them.

    This is the "replace" branch of a build: the export folder names its files
    ``LOD_A.m3g`` and ``SHARED.m3g``, the game wants ``<car>_a.m3g`` and
    ``<car>_shared.m3g``.  Every mapped file is copied under the name the game
    expects, the old one is backed up first, and the three manifests learn the
    new sizes.

    Files the table does not mention are left exactly as they are - a pack that
    only carries LOD A does not delete the other seven.
    """
    from rr3lib import car as carlib

    entry = depotlib.scan(root).get(name)
    if entry is None:
        raise EditError(f"{name} is not installed")
    car_dir = os.path.join(root, ".depot", "vehicles", name)
    if not os.path.isdir(car_dir):
        raise EditError(f"{name} has no folder")
    _begin(f"Install the files of {name}")
    out = {"car": name, "placed": [], "missing": [], "synced": 0}
    for key, source, target in _slot_plan(mapping, name):
        if not os.path.isfile(source):
            out["missing"].append(key)
            continue
        dest = os.path.join(car_dir, target)
        if os.path.isfile(dest) and os.path.abspath(dest) == os.path.abspath(source):
            out["placed"].append({"slot": key, "file": target, "same": True})
            continue
        # Always record the state first, even when the file is new: a copy that
        # only backs up what it *replaces* leaves every file it created behind
        # after an undo, and the manifests then claim rows for files nobody has.
        _backup(root, dest)
        shutil.copyfile(source, dest)
        sync_file(root, name=name, rel_path=f"/vehicles/{name}/{target}",
                  local=dest, create=True)
        out["synced"] += 1
        out["placed"].append({"slot": key, "file": target, "same": False})
        log(f"  {key:12s} -> {target}")
    return out


def _slot_plan(mapping: dict, car: str) -> list:
    """``[(key, source, target)]`` without importing the UI's module graph."""
    from . import slots as slotlib

    return slotlib.plan(mapping, car)


def _merge_mirror(root: str, mirror: str, name: str) -> dict:
    """Copy a build mirror onto the real install and re-sync the manifests."""
    copied = 0
    for dirpath, _dirs, files in os.walk(mirror):
        for f in files:
            src = os.path.join(dirpath, f)
            rel = os.path.relpath(src, mirror)
            dst = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            # ``_backup`` writes an ``.absent`` marker when the file is new, which
            # is what makes an undo delete it instead of leaving a stray copy.
            _backup(root, dst)
            shutil.copyfile(src, dst)
            copied += 1
    # every file we just landed, in the manifests
    touched = []
    car_dir = os.path.join(root, ".depot", "vehicles", name)
    if os.path.isdir(car_dir):
        # walk the whole car folder: the livery atlases live in ``livery/`` and
        # their registry rows carry their own md5, so a flat listing misses them
        for dirpath, _dirs, files in os.walk(car_dir):
            sub = os.path.relpath(dirpath, car_dir).replace(os.sep, "/")
            for f in files:
                p = os.path.join(dirpath, f)
                rel = f"/vehicles/{name}/{f}" if sub == "." else \
                      f"/vehicles/{name}/{sub}/{f}"
                touched.append(sync_file(root, name=name, rel_path=rel,
                                         local=p, create=True))
    return {"copied": copied, "synced": len(touched)}


def remove_car(root: str, name: str, *, keep_folder: bool = False) -> dict:
    """Delete a mod: folder, spec, appearance record, livery and manifest rows."""
    from rr3lib import appearance as appearlib

    _begin(f"Remove {name}")
    depot = os.path.join(root, ".depot")
    out = {"name": name}
    entry = None
    try:
        inv = depotlib.scan(root)
        entry = inv.get(name)
    except depotlib.DepotError:
        inv = None
    if entry is None:
        raise EditError(f"{name} is not installed")

    # 1. spec
    spec_path = os.path.join(depot, *speclib.SPEC_DIR.split("/"),
                             f"{entry.spec_stem}.bin.nct")
    if os.path.isfile(spec_path):
        _backup(root, spec_path)
        os.remove(spec_path)
        out["spec"] = True
        reg = manifestlib.load_registry(depot)
        reg.remove(f"/vehicles/data/{entry.spec_stem}.bin.nct")
        manifestlib.save_registry(reg, os.path.join(depot, manifestlib.REGISTRY))
        dl = manifestlib.load_data_list(root)
        rel = f"/vehicles/data/{entry.spec_stem}.bin.nct"
        if rel in set(dl.paths()):
            dl.remove(rel)
            manifestlib.save_data_list(
                dl, os.path.join(root, *manifestlib.VEHICLE_DATA_LIST.split("/")))

    # 1b. the three id-keyed tables
    #
    # A build writes a row into ``cardesc``, ``suspensionbehaviour`` and
    # ``cardamagethresholds`` for the new car id, and none of them is derived
    # from the spec file - so deleting the spec frees the id while the rows
    # stay behind.  The next build then picks the same id (it is the lowest one
    # free) and dies on "already listed".  Removing them here is what makes
    # remove-then-install work, which is the loop a mod is developed in.
    car_id = int(entry.car_id or 0)
    if car_id:
        try:
            desc = speclib.load_cardesc(depot)
            if f"{car_id}_{name}.bin".encode() in desc.entries:
                path = os.path.join(depot, *speclib.CARDESC.split("/"))
                _backup(root, path)
                desc.remove(f"{car_id}_{name}.bin")
                speclib.save_cardesc(desc, path)
                out["cardesc"] = True
        except Exception as exc:            # noqa: BLE001 - never block a removal
            out["cardesc"] = f"skipped: {exc}"
        for kind, loader, rel in (
                ("suspension", speclib.load_suspension, speclib.SUSPENSION),
                ("damage", speclib.load_damage, speclib.DAMAGE)):
            try:
                table = loader(depot)
                if car_id not in table.ids():
                    continue
                path = os.path.join(depot, *rel.split("/"))
                _backup(root, path)
                table.remove(car_id)
                nctlib.write(path, table.to_bytes())
                out[kind] = True
            except Exception as exc:        # noqa: BLE001
                out[kind] = f"skipped: {exc}"

    # 2. appearance record
    count, recs = appearlib.load(depot)
    before = len(recs)
    appearlib.remove(recs, entry.appearance_id)
    if len(recs) != before:
        path = os.path.join(depot, *appearlib.APPEARANCES.split("/"))
        _backup(root, path)
        appearlib.save(len(recs), recs, path)
        out["appearance"] = True

    # 3. livery file
    lv = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                      f"{name}.liveries.bin.nct")
    if os.path.isfile(lv):
        _backup(root, lv)
        os.remove(lv)
        out["livery"] = True

    # 4. manifest rows
    cm = car_manifest_path(root, name)
    if os.path.isfile(cm):
        _backup(root, cm)
        os.remove(cm)
        out["car_manifest"] = True

    # 5. folder
    folder = os.path.join(depot, "vehicles", name)
    if os.path.isdir(folder) and not keep_folder:
        trash = os.path.join(root, BACKUP_DIR, time.strftime("%Y%m%d-%H%M%S"),
                             "removed", name)
        os.makedirs(os.path.dirname(trash), exist_ok=True)
        shutil.move(folder, trash)
        out["folder"] = trash

    depotlib.unregister_mod(depot, name)
    out["ok"] = True
    return out


def adopt(root: str, name: str) -> dict:
    """Take an unknown car into the mod list (it was installed by another tool)."""
    inv = depotlib.scan(root)
    entry = inv.get(name)
    if entry is None:
        raise EditError(f"{name} is not installed")
    depotlib.register_mod(os.path.join(root, ".depot"), entry, kind="adopted")
    return {"name": name, "id": entry.car_id}


def _is_other_platform(path: str) -> bool:
    """True for the texture variants this depot does not ship.

    The manifests list one row per GPU family - ``.dxt.dds.z`` (which we have),
    ``.atc.dds.z`` and ``.etc.dds.z`` (Adreno / PowerVR, absent), and
    ``.ptc.pvr.z``.  A depot unpacks only the copy its build targets, so those
    rows are expected to point at nothing and must not be reported as damage.

    This stays true now that :mod:`rr3lib.etcdecode` can read all three: being
    able to decode a variant is not the same as the file being on disk, and a
    missing variant is still normal.
    """
    low = path.lower()
    return any(tag in low for tag in (".atc.", ".etc.", ".ptc."))


def verify(root: str, name: str = "") -> list:
    """Compare the manifests against the files on disk, one car or all."""
    depot = os.path.join(root, ".depot")
    problems = []
    inv = depotlib.scan(root)
    cars = [c for c in inv.cars if not name or c.name == name]
    reg = manifestlib.load_registry(depot)
    for c in cars:
        cm = car_manifest_path(root, c.name)
        if not os.path.isfile(cm):
            problems.append(f"{c.name}: no per car manifest")
            continue
        rows = manifestlib.read_car_manifest(cm)
        for path, md5, _pk, _raw in rows:
            local = os.path.join(depot, *path.strip("/").split("/"))
            if not os.path.isfile(local):
                if _is_other_platform(path):
                    continue          # other GPU platform variants we do not ship
                problems.append(f"{c.name}: manifest lists a missing file {path}")
                continue
            if reg.get(path) != md5:
                problems.append(f"{c.name}: registry disagrees with the manifest "
                                f"on {path}")
    return problems
