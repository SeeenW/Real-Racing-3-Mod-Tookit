"""Publishing: turning a finished piece of work into one file with its needs.

This is the page the studio ends on.  Everything before it edits a working copy;
this takes that work and writes a ``.rr3mod`` - the format
:mod:`rrmod.pack` reads - with a dependency list attached, so the person who
installs it is told what has to be there *before* they find out the hard way.

What each kind gathers, and why
------------------------------
``car``
    The car's whole folder (every LOD, the interior, ``livery/``), its spec
    under ``vehicles/data``, its livery table, and - the part that is easy to
    forget - every ``common/`` page its livery names, because those live
    outside the car folder and a share without them renders magenta on a machine
    that does not have the page.  Pages that ship with the game are *not*
    copied; they become requirements instead, since every install already has
    them.

``career``
    The fourteen files a career edit touches.  A career pack **merges**: the
    receiver's own series and events are kept and the pack's are added, because
    replacing the file would wipe every series that person added.  That is a
    property of the kind, not a choice offered at install time.

``brand``
    The logo pages plus the rows in ``asset_list_gui_assets_core.txt``.  The
    atlas is one file per size, so all three sizes go in or a screen size shows
    the old logo.

``driver``
    One pose (``driver_<x>.banim``) and the low-poly body that can wear it, if
    there is one.  A pose without a body is legal but looks wrong on the small
    screen, so it is written into the manifest as a note rather than refused.

``pages``
    Shared texture pages: the page file plus its four asset list rows.  This is
    the pack a "here are some tyres I made" upload is.

``track``
    A circuit picture and its map, which is all this program can make of a
    track today (importing geometry is still open).

Everything here reads the *working copy* when the caller passes one, so a pack
made right after an edit contains the edit.
"""

from __future__ import annotations

import json
import os

from . import deps as depslib
from . import depot as depotlib
from . import edit as editlib
from . import pack as packlib
from . import share as sharelib
from rr3lib import livery as liverylib

#: Kinds this module knows how to gather, in menu order.
KINDS = ("car", "driver", "career", "brand", "pages", "material", "track")

#: Folders under ``vehicles/`` that are not a car.
_NOT_CARS = ("data", "common", "shaders", "wheels", "decals")


class PublishError(Exception):
    pass


def _depot(root: str) -> str:
    return os.path.join(root, ".depot")


def _walk(folder: str, rel_root: str) -> list:
    """``[(game path, local path)]`` for every file under ``folder``."""
    out = []
    if not os.path.isdir(folder):
        return out
    for dirpath, _dirs, files in os.walk(folder):
        sub = os.path.relpath(dirpath, folder).replace(os.sep, "/")
        for f in sorted(files):
            rel = f"{rel_root}/{f}" if sub == "." else f"{rel_root}/{sub}/{f}"
            out.append((rel, os.path.join(dirpath, f)))
    return out


# --------------------------------------------------------------- car
#: The four texture families a shared page can be stored in.
FAMILIES = (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z")


def _page_on_disk(depot: str, stem: str) -> tuple:
    """``(game path, local path)`` for a shared page, or ``("", "")``.

    A stem has no suffix (``common/car_windows_04``), and the four families are
    different files, so each one is tried in turn.  ``os.path.splitext`` is no
    use here: ``.dxt.dds.z`` is three parts, not two.
    """
    base = os.path.join(depot, "vehicles", *stem.split("/"))
    for suffix in FAMILIES:
        if os.path.isfile(base + suffix):
            return f"vehicles/{stem}{suffix}", base + suffix
    return "", ""


def _page_pictures(root: str, stems) -> list:
    """``[(game path, local picture)]`` for shared pages this program edited.

    A page on disk is finished GPU data - whichever family this install was
    unpacked for.  Carrying that file would hand the receiver a DXT page on a
    phone that decodes ETC, so instead the *picture* the page was made from
    travels and the far side encodes it for what it has
    (:func:`rrmod.publish.install`).  A page nobody edited has no picture and is
    not carried at all - the game ships it.

    Returns the pages that have a picture, in the order asked for.
    """
    from . import textures as texlib

    depot = _depot(root)
    out = []
    for stem in stems:
        rel, _local = _page_on_disk(depot, stem)
        if not rel:
            continue
        picture = texlib.source_of(root, rel)
        if picture:
            out.append((rel, picture))
    return out


def car_pages(root: str, name: str) -> tuple:
    """``(inside, outside)`` - the pages a car's livery names, split by where.

    ``inside`` are pages in the car's own ``livery/`` folder (they travel with
    the car).  ``outside`` are ``common/`` pages, which are either shipped with
    the game (a requirement) or added by this program (a file to carry).
    """
    depot = _depot(root)
    table = os.path.join(depot, "vehicles", "data", "liveries",
                         f"{name}.liveries.bin.nct")
    inside, outside = [], []
    if not os.path.isfile(table):
        return inside, outside
    try:
        lf = liverylib.load(table)
    except Exception:                            # noqa: BLE001 - a bad table
        return inside, outside
    seen = set()
    for path in _pages_of(lf):
        if path in seen:
            continue
        seen.add(path)
        if path.startswith("common/"):
            outside.append(path)
        else:
            inside.append(path)
    return sorted(inside), sorted(outside)


def _pages_of(lf) -> list:
    """Every page a livery file names, as strings."""
    out = []
    for _slot, page in getattr(lf, "textures", []) or []:
        out.append(_text(page))
    for paint in getattr(lf, "paints", []) or []:
        for _slot, page in getattr(paint, "overrides", []) or []:
            out.append(_text(page))
    return [p for p in out if p]


def _text(page) -> str:
    if isinstance(page, bytes):
        return page.decode("ascii", "replace")
    return str(page or "")


def car_requirements(root: str, name: str, *, donor: str = "") -> list:
    """What a car pack needs from the receiving side.

    The base car (for a car that replaces or clones one), any ``common/`` page
    that ships with the game, and the driver pose the car's record names - which
    the receiver may not have.
    """
    reqs = []
    base = donor or name
    inv = depotlib.scan(root)
    if inv.get(base) is None:
        # A brand new car: its donor is the requirement, not itself.
        base = donor or ""
    if base:
        reqs.append({"kind": "car", "name": base})
    game = depslib.shipped(_depot(root), install=root)
    _inside, outside = car_pages(root, name)
    for page in outside:
        stem = depslib.stem_of(page)
        if stem in game:
            reqs.append({"kind": "page", "name": stem,
                         "note": "ships with the game"})
    for req in _driver_requirement(root, name):
        reqs.append(req)
    for req in _material_requirements(root, name):
        reqs.append(req)
    return _unique(reqs)


def _driver_requirement(root: str, name: str) -> list:
    """The pose a car's record names, when it names one of its own."""
    from rr3lib import driver as driverlib

    depot = _depot(root)
    try:
        entry = depotlib.scan(root).get(name)
        if entry is None:
            return []
        nct = os.path.join(depot, "vehicles", "data",
                           f"{entry.spec_stem}.bin.nct")
        got = driverlib.banim_in_record(nct)
    except Exception:                            # noqa: BLE001
        return []
    if not got:
        return []
    stem = got[:-len(".banim")] if got.endswith(".banim") else got
    if stem == "driver":
        return []                                # the game's own default pose
    return [{"kind": "driver", "name": f"{stem}.banim"}]


def _material_requirements(root: str, name: str) -> list:
    """Materials the car's meshes wear that this program did not ship."""
    from rr3lib import gamematerial as gamelib

    depot = _depot(root)
    try:
        lib = gamelib.load(depot)
    except Exception:                            # noqa: BLE001
        return []
    out = []
    for mat in _materials_of(root, name):
        md = lib.material(mat)
        if md is None:
            out.append({"kind": "material", "name": mat})
    return out


def _materials_of(root: str, name: str) -> list:
    """Every material name the car's livery table points a mesh at.

    The table stores slots, not names - ``(meshSlot, matSlot)`` both ways - so
    each id is looked up in ``liveryStringTable.bin.nct``.  A slot past the end
    of the table is skipped: it is a broken row, and inventing a name for it
    would turn a livery bug into a phantom dependency.
    """
    depot = _depot(root)
    table = os.path.join(depot, "vehicles", "data", "liveries",
                         f"{name}.liveries.bin.nct")
    if not os.path.isfile(table):
        return []
    try:
        lf = liverylib.load(table)
        slots = liverylib.load_slot_table(depot)
    except Exception:                            # noqa: BLE001
        return []
    ids = set()
    for _mesh_slot, mat_slot in getattr(lf, "materials", []) or []:
        ids.add(mat_slot)
    for paint in getattr(lf, "paints", []) or []:
        for _mesh_slot, mat_slot in getattr(paint, "materials", []) or []:
            ids.add(mat_slot)
    out = set()
    for slot in ids:
        got = _material_name(slots, slot)
        if got:
            out.add(got)
    return sorted(out)


def _material_name(slots, slot: int) -> str:
    try:
        if slot < 0 or slot >= len(slots):
            return ""
        return slots.name(slot) or ""
    except Exception:                            # noqa: BLE001
        return ""


def _unique(rows: list) -> list:
    out, seen = [], set()
    for row in rows:
        key = (row.get("kind"), row.get("name"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def car_plan(root: str, name: str, *, donor: str = "") -> dict:
    """What a car pack would hold, without writing anything."""
    inv = depotlib.scan(root)
    entry = inv.get(name)
    files = sharelib.car_files(root, name)
    inside, outside = car_pages(root, name)
    game = depslib.shipped(_depot(root), install=root)
    carried = []
    for page in outside:
        stem = depslib.stem_of(page)
        if stem in game:
            continue                             # a requirement, not a file
        rel, local = _page_on_disk(_depot(root), stem)
        if rel:
            carried.append((rel, local))
    pictures = _page_pictures(root, [depslib.stem_of(p) for p in outside])
    total = sum(os.path.getsize(p) for _r, p in files)
    total += sum(os.path.getsize(p) for _r, p in pictures)
    return {
        "kind": "car",
        "name": name,
        "car_id": entry.car_id if entry else 0,
        "appearance_id": entry.appearance_id if entry else 0,
        "files": files,
        "pictures": pictures,
        "carried_pages": [rel for rel, _p in carried],
        "pictured_pages": [rel for rel, _p in pictures],
        "inside_pages": inside,
        "outside_pages": outside,
        "requires": car_requirements(root, name, donor=donor),
        "count": len(files) + len(pictures),
        "bytes": total,
    }


def car(root: str, name: str, out_path: str, *, note: str = "",
        donor: str = "", title: str = "", log=print) -> dict:
    """Write a car pack; returns the summary plus the manifest.

    The car's own files travel as they are - every LOD, the interior, ``livery/``,
    the spec and the livery table.  A ``common/`` page the car names travels as
    the *picture* it was made from, if this program edited it, so the receiver
    encodes it for their own GPU; a page nobody edited becomes a requirement
    instead of a file, because every install already has it.
    """
    plan = car_plan(root, name, donor=donor)
    if not plan["files"] and not plan["pictures"]:
        raise PublishError(f"{name} has no files to publish")
    manifest = packlib.make(
        kind="car", name=name, title=title or name, note=note,
        files=plan["files"], pictures=plan["pictures"],
        requires=plan["requires"],
        provides={"cars": [name], "pages": plan["carried_pages"]},
        extra={"car_id": plan["car_id"],
               "appearance_id": plan["appearance_id"]})
    made = packlib.write(out_path, manifest, plan["files"],
                         pictures=plan["pictures"], log=log)
    made["plan"] = plan
    return made


# --------------------------------------------------------------- pages
def pages(root: str, stems, out_path: str, *, note: str = "",
          title: str = "", log=print) -> dict:
    """Publish shared texture pages: the art plus its four asset list rows.

    A page this program edited travels as its source picture, so the receiver
    encodes it into their own GPU family; that is the whole point of the picture
    prefix.  A page that was never edited has no picture, and shipping the
    finished file would pin the pack to one device, so it is reported as missing
    rather than written.
    """
    depot = _depot(root)
    pictures, provided, missing, plain = [], [], [], []
    for raw in stems:
        stem = depslib.stem_of(raw)
        rel, local = _page_on_disk(depot, stem)
        if not rel:
            missing.append(stem)
            continue
        picture = _page_pictures(root, [stem])
        if picture:
            pictures.append(picture[0])
        else:
            plain.append((rel, local))
        provided.append(stem)
    if not pictures and not plain:
        raise PublishError("none of those pages are on disk")
    manifest = packlib.make(
        kind="pages", name=title or f"{len(provided)} page(s)", title=title,
        note=note, files=plain, pictures=pictures,
        provides={"pages": provided})
    made = packlib.write(out_path, manifest, plain, pictures=pictures, log=log)
    made["missing"] = missing
    made["without_a_picture"] = [rel for rel, _p in plain]
    return made


# --------------------------------------------------------------- driver
def drivers(root: str, stem: str, out_path: str, *, note: str = "",
            title: str = "", log=print) -> dict:
    """Publish one driver pose and the low-poly body that can wear it.

    The naming is not uniform in the game's own folder: the pose is
    ``driver_<x>.banim`` while the small-screen body is ``driver_lod_c_<x>.m3g``
    with the same ``<x>`` but no second ``driver_`` in front of it.  Both are
    tried with and without the prefix so either spelling the caller uses works.
    """
    from rr3lib import driver as driverlib

    depot = _depot(root)
    folder = driverlib.driver_dir(depot)
    bare = stem[:-len(".banim")] if stem.endswith(".banim") else stem
    short = bare[len("driver_"):] if bare.startswith("driver_") else bare
    wanted = [f"{bare}.banim", f"driver_{short}.banim"]
    for x in (short, bare):
        wanted.extend([f"driver_lod_c_{x}.m3g", f"driver_lod_d_{x}.m3g"])
    files, provided, seen = [], [], set()
    for name in wanted:
        if name in seen:
            continue
        seen.add(name)
        local = os.path.join(folder, name)
        if os.path.isfile(local):
            files.append((f"driver/{name}", local))
            provided.append(name)
    if not any(rel.endswith(".banim") for rel, _p in files):
        raise PublishError(f"there is no {short}.banim in {folder}")
    has_body = any(rel.endswith(".m3g") for rel, _p in files)
    if not has_body:
        note = (note + "\n\n" if note else "") + (
            f"This pose has no low-poly body of its own, so a car that uses it "
            f"wears the generic one on the small screen.")
    manifest = packlib.make(
        kind="driver", name=short, title=title or short, note=note,
        files=files, provides={"drivers": provided})
    return packlib.write(out_path, manifest, files, log=log)


# --------------------------------------------------------------- brand
def brands(root: str, name: str, out_path: str, *, note: str = "",
           title: str = "", log=print) -> dict:
    """Publish a manufacturer's logo pages and their asset list rows."""
    from . import brands as brandlib

    depot = _depot(root)
    stem = brandlib.stem_of(name)
    files = []
    for size in ("2048x1536", "960x640", "480x320"):
        folder = os.path.join(depot, "gui_assets", size, "common",
                              "manufacturer_logos")
        for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if f.startswith(f"logo_{stem}.") or f == "sprites.android.atlas":
                files.append((f"gui_assets/{size}/common/manufacturer_logos/{f}",
                              os.path.join(folder, f)))
    if not files:
        raise PublishError(f"no logo picture for {name}")
    manifest = packlib.make(
        kind="brand", name=name, title=title or name, note=note, files=files,
        provides={"brands": [name]})
    return packlib.write(out_path, manifest, files, log=log)


# --------------------------------------------------------------- career
def career(root: str, out_path: str, *, note: str = "", title: str = "",
           log=print) -> dict:
    """Publish the career files as a pack that **merges** on the far side."""
    from . import series as serieslib

    depot = _depot(root)
    files = []
    for leaf in serieslib.career_leaves():
        local = os.path.join(depot, *leaf.split("/"))
        if os.path.isfile(local):
            files.append((leaf, local))
    if not files:
        raise PublishError("there is no career file to publish")
    manifest = packlib.make(
        kind="career", name=title or "career", title=title or "Career edit",
        note=(note + "\n\n" if note else "") + (
            "A career pack is merged, not replaced: the series and events "
            "already on the receiving side are kept."),
        files=files, provides={})
    return packlib.write(out_path, manifest, files, log=log)


# --------------------------------------------------------------- track
def track(root: str, name: str, out_path: str, *, note: str = "",
          title: str = "", log=print) -> dict:
    """Publish a circuit's picture and map, which is all this program makes."""
    from . import maps as maplib
    from . import tracks as tracklib

    depot = _depot(root)
    files = []
    picture = maplib.stored(depot, name)
    if picture and os.path.isfile(picture):
        rel = os.path.relpath(picture, depot).replace(os.sep, "/")
        files.append((rel, picture))
    if not files:
        raise PublishError(
            f"{name} has no picture of its own - only the game's own art, "
            f"which is already on every install")
    manifest = packlib.make(
        kind="track", name=tracklib.normalise(name), title=title or name,
        note=note, files=files, provides={"tracks": [name]})
    return packlib.write(out_path, manifest, files, log=log)


# --------------------------------------------------------------- material
def cloned_materials(root: str) -> list:
    """Materials this game folder holds that the game did not ship.

    A material pack is about the ones a mod added: the game's own 296 are on
    every install already, so shipping them again would be 135 KB of nothing.

    A working copy used to answer this by comparing itself with the install it
    came from.  Edits land in the install now, so that comparison would be a file
    with itself - the answer has to be the record :func:`mark_mine` keeps when a
    material is cloned.  A folder that has no record yet (one built by an older
    version) falls back to the comparison, which is what it was written for.
    """
    from rr3lib import gamematerial as gamelib

    depot = _depot(root)
    path = os.path.join(depot, *gamelib.MATERIALS_BIN.split("/"))
    if not os.path.isfile(path):
        return []
    here = {n for _a, _b, n in gamelib.block_spans(gamelib.load_records(path)) if n}
    recorded = set(mine(root))
    if recorded:
        # Only the ones still in the library: a name that was removed again is
        # not something a pack can carry.
        return sorted(recorded & here)
    install = editlib._install_of(root)
    theirs = set()
    if install and os.path.abspath(install) != os.path.abspath(root):
        src = os.path.join(install, ".depot", *gamelib.MATERIALS_BIN.split("/"))
        if os.path.isfile(src):
            theirs = {n for _a, _b, n
                      in gamelib.block_spans(gamelib.load_records(src)) if n}
    return sorted(here - theirs)


#: Where the names of the materials this program cloned are kept, beside
#: ``rr3mods.json`` and ``deps.json`` so all three travel with the install.
MINE_FILE = "materials.json"


def mine_path(root: str) -> str:
    return os.path.join(depotlib.state_dir(_depot(root)), MINE_FILE)


def mine(root: str) -> list:
    """The material names this program cloned into ``materials.bin``."""
    try:
        with open(mine_path(root), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [str(n) for n in (data.get("names") or []) if n]


def mark_mine(root: str, name: str) -> list:
    """Remember that ``name`` is a clone, not one of the game's own."""
    names = mine(root)
    if name and name not in names:
        names.append(name)
        names.sort()
        _write_mine(root, names)
    return names


def unmark_mine(root: str, name: str) -> list:
    names = [n for n in mine(root) if n != name]
    _write_mine(root, names)
    return names


def _write_mine(root: str, names) -> None:
    path = mine_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"names": list(names)}, fh, indent=1, sort_keys=True)


def materials(root: str, names, out_path: str, *, note: str = "",
              title: str = "", log=print) -> dict:
    """Publish cloned materials.

    The pack carries the whole library, because a material block is a fragment of
    one record stream and has no meaning on its own, plus the names it is adding.
    Install merges: only the named blocks are spliced into the receiver's library,
    so two people who each cloned a material end up with both.
    """
    from rr3lib import gamematerial as gamelib

    depot = _depot(root)
    path = os.path.join(depot, *gamelib.MATERIALS_BIN.split("/"))
    if not os.path.isfile(path):
        raise PublishError(f"this working copy has no {gamelib.MATERIALS_BIN}")
    have = set(cloned_materials(root))
    wanted = [str(n).strip() for n in (names if isinstance(names, (list, tuple))
                                       else [names]) if str(n).strip()]
    if not wanted:
        raise PublishError("no material was named")
    unknown = [n for n in wanted if n not in have]
    if unknown:
        raise PublishError(
            f"{', '.join(unknown[:4])} is not a material this working copy added"
            + (f" and {len(unknown) - 4} more" if len(unknown) > 4 else ""))
    files = [(gamelib.MATERIALS_BIN, path)]
    manifest = packlib.make(
        kind="material", name=title or wanted[0], title=title or wanted[0],
        note=note, files=files, provides={"materials": wanted})
    return packlib.write(out_path, manifest, files, log=log)


# ------------------------------------------------- material (install side)
def _merge_materials(root: str, source: str, names) -> list:
    """Splice named material blocks from ``source`` into the working library.

    Returns the names that were actually added.  A name the receiver already has
    is left alone: their copy may be tuned differently, and overwriting it would
    change how their own cars look.
    """
    from rr3lib import gamematerial as gamelib

    depot = _depot(root)
    target = os.path.join(depot, *gamelib.MATERIALS_BIN.split("/"))
    if not os.path.isfile(target):
        raise PublishError(f"this working copy has no {gamelib.MATERIALS_BIN}")
    src_recs = gamelib.load_records(source)
    src_spans = {n: (a, b) for a, b, n in gamelib.block_spans(src_recs)}
    recs = gamelib.load_records(target)
    have = {n for _a, _b, n in gamelib.block_spans(recs) if n}
    blobs = []
    added = []
    for name in names:
        if name in have or name not in src_spans:
            continue
        a, b = src_spans[name]
        blobs.append(gamelib.encode_records(src_recs[a:b]))
        added.append(name)
    if not added:
        return []
    # Every block goes on the end of the material table in one go: inserting them
    # one at a time and re-reading in between would be the same bytes for a lot
    # more work, and the table's own order carries no meaning.
    grown = gamelib.insert_blocks(recs, blobs)
    editlib._backup(root, target)
    with open(target, "wb") as fh:
        fh.write(grown)
    editlib.sync_file(root, name="", rel_path=f"/{gamelib.MATERIALS_BIN}",
                      local=target)
    for name in added:
        try:
            editlib.add_slot_names(root, [name], log=lambda _m: None)
        except Exception:                        # noqa: BLE001 - slot is a bonus
            pass
    return added


# --------------------------------------------------------------- install
#: The GPU families a picture can be encoded into, in the order a menu offers
#: them.  ``auto`` means "whichever family this install already holds".
TEXTURE_FAMILIES = ("auto", "dxt", "etc", "atc")

#: Family name -> the suffix a page in that family is stored under.
FAMILY_SUFFIX = {"dxt": ".dxt.dds.z", "etc": ".etc.dds.z", "atc": ".atc.dds.z"}


def _existing_family(depot: str, rel: str) -> str:
    """Which family a page is already stored in here, or ``""``.

    ``rel`` is the game path the pack names, which ends in *some* family - but
    not necessarily the one this install holds, because the pack's author may
    have been on a different device.  All four are tried.
    """
    from . import textures as texlib

    stem = rel
    for suffix in FAMILIES:
        if rel.lower().endswith(suffix):
            stem = rel[:-len(suffix)]
            break
    base = os.path.join(depot, *stem.split("/"))
    for name, suffix in (("dxt", ".dxt.dds.z"), ("etc", ".etc.dds.z"),
                         ("atc", ".atc.dds.z"), ("ptc", ".ptc.pvr.z")):
        if os.path.isfile(base + suffix):
            return "pvrtc" if name == "ptc" else name
    return ""


def _encode_picture(picture: str, rel: str, *, family: str,
                    expect: tuple = ()) -> tuple:
    """``(game path, page bytes)`` for one picture, in the family asked for."""
    from . import textures as texlib

    made = texlib.build(picture, expect=expect,
                        suffix=FAMILY_SUFFIX.get(family, texlib.WRITE_SUFFIX))
    stem = rel
    for suffix in FAMILIES:
        if rel.lower().endswith(suffix):
            stem = rel[:-len(suffix)]
            break
    return stem + FAMILY_SUFFIX.get(family, texlib.WRITE_SUFFIX), made["blob"]


def _size_of_page(path: str) -> tuple:
    """``(width, height)`` of a page already on disk, or ``()``."""
    from rr3lib import texport as texlib

    try:
        info = texlib.describe(path)
    except Exception:                            # noqa: BLE001 - unreadable
        return ()
    first = (info.get("images") or [{}])[0]
    return (first.get("width", 0), first.get("height", 0))


def install(root: str, path: str, *, family: str = "", keep: bool = True,
            log=print) -> dict:
    """Install a pack into the working copy.

    A ``career`` pack merges (its series are added, the receiver's kept); every
    other kind replaces the files it names.  The three manifests are re-hashed
    per file, so nothing is left pointing at a file that is not there.

    ``family`` is how a carried *picture* becomes a page: ``dxt``, ``etc``,
    ``atc``, or empty for "the family this install already holds for that page".
    A picture is not a game file, so it is encoded here rather than copied, and
    the page it produces is named with the family's own suffix - a DXT page
    called ``.etc.dds.z`` would decode to garbage.

    ``keep`` decides whether the files being replaced are copied first.  It
    defaults to yes: an install that cannot be walked back is a trap, and the
    cost is only the size of the files it overwrites, not of the install.  With
    ``keep=False`` the step still exists in the history panel but holds nothing,
    so undoing it cannot bring the old bytes back.
    """
    import shutil
    import zipfile

    info = packlib.check(root, path)
    if info["problems"]:
        raise PublishError("; ".join(info["problems"]))
    editlib._begin(f"Install {info['title'] or info['name']}")
    written = []
    depot = _depot(root)
    pictures = packlib.pictures_of(packlib.read_manifest(path))

    def land(rel: str, source: str) -> None:
        local = os.path.join(depot, *rel.split("/"))
        os.makedirs(os.path.dirname(local), exist_ok=True)
        if keep:
            editlib._backup(root, local)
        shutil.copyfile(source, local)
        written.append((rel, local))

    def unpack(rel: str, scratch: str, *, prefix: str = packlib.PREFIX) -> str:
        """Extract one member of the pack to ``scratch`` and return its path."""
        member = prefix + rel
        try:
            with zipfile.ZipFile(path) as zf:
                zf.extract(member, scratch)
        except KeyError:
            raise PublishError(
                f"{os.path.basename(path)} is missing {rel}") from None
        return os.path.join(scratch, *member.split("/"))

    if info["kind"] == "material":
        # A material pack is a library fragment, not a file to drop in.  Copying
        # its materials.bin over the receiver's would take their own 296
        # materials and every clone they made away with it, so only the blocks
        # the pack names are spliced in.
        names = (info.get("provides") or {}).get("materials") or [info["name"]]
        scratch = os.path.join(root, editlib.BACKUP_DIR, "_pack")
        os.makedirs(scratch, exist_ok=True)
        try:
            if os.path.isdir(path):
                source = os.path.join(path, *info["files"][0].split("/"))
            else:
                source = unpack(info["files"][0], scratch)
            added = _merge_materials(root, source, names)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        # The names are ours now, and the record is the only thing that can say
        # so: the library is the install's, so "not in the stock table" cannot be
        # asked of a file that this merge just changed.
        for name in added:
            mark_mine(root, name)
        log(f"  {info['title'] or info['name']}: {len(added)} material(s) added")
        return {"name": info["name"], "kind": info["kind"], "written": len(added),
                "files": [], "note": info.get("note", ""), "materials": added,
                "pictures": 0, "family": ""}

    if os.path.isdir(path):
        for rel in info["files"]:
            land(rel, os.path.join(path, *rel.split("/")))
    else:
        scratch = os.path.join(root, editlib.BACKUP_DIR, "_pack")
        os.makedirs(scratch, exist_ok=True)
        try:
            for rel in info["files"]:
                land(rel, unpack(rel, scratch))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    # Pictures last: each becomes a page in a family chosen for this install.
    made_pages = []
    if pictures:
        scratch = os.path.join(root, editlib.BACKUP_DIR, "_pack")
        os.makedirs(scratch, exist_ok=True)
        try:
            for rel in pictures:
                source = (os.path.join(path, packlib.PICTURES, *rel.split("/"))
                          if os.path.isdir(path) else
                          unpack(rel, scratch, prefix=packlib.PICTURES))
                want = family if family in FAMILY_SUFFIX else \
                    _existing_family(depot, rel) or "dxt"
                if want not in FAMILY_SUFFIX:
                    want = "dxt"
                # Keep the page the size the game allocated for it: the shipped
                # one is the only thing that knows, so it is measured first.
                expect = ()
                stem = rel
                for suffix in FAMILIES:
                    if rel.lower().endswith(suffix):
                        stem = rel[:-len(suffix)]
                        break
                for suffix in FAMILIES:
                    probe = os.path.join(depot, *stem.split("/")) + suffix
                    if os.path.isfile(probe):
                        expect = _size_of_page(probe)
                        break
                page_rel, blob = _encode_picture(source, rel, family=want,
                                                 expect=expect)
                local = os.path.join(depot, *page_rel.split("/"))
                os.makedirs(os.path.dirname(local), exist_ok=True)
                if keep:
                    editlib._backup(root, local)
                with open(local, "wb") as handle:
                    handle.write(blob)
                written.append((page_rel, local))
                made_pages.append({"rel": page_rel, "family": want,
                                   "bytes": len(blob)})
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    for rel, local in written:
        editlib.sync_file(root, name=_car_of(rel), rel_path="/" + rel,
                          local=local, create=True)
    log(f"  {info['title'] or info['name']}: {len(written)} file(s) written")
    return {"name": info["name"], "kind": info["kind"], "written": len(written),
            "files": written, "note": info.get("note", ""),
            "pictures": len(made_pages), "pages": made_pages}


def _car_of(rel: str) -> str:
    """The car a game path belongs to, for the manifest row."""
    parts = rel.split("/")
    if len(parts) > 2 and parts[0] == "vehicles" and parts[1] not in _NOT_CARS:
        return parts[1]
    return ""


def selftest(root: str = "") -> int:
    """The gathering rules, on whatever install is given."""
    if not root or not os.path.isdir(os.path.join(root, ".depot")):
        print("publish selftest: no install")
        return 2
    bad = 0
    inv = depotlib.scan(root)
    if not inv.cars:
        print("publish selftest: no cars")
        return 2
    name = inv.cars[0].name
    plan = car_plan(root, name)
    print(f"car plan : {name}: {plan['count']} file(s), "
          f"{len(plan['requires'])} requirement(s)")
    if plan["count"] < 2:
        print(f"FAIL {name} gathered only {plan['count']} file(s)")
        bad += 1
    if not any(r["kind"] == "car" for r in plan["requires"]):
        print("FAIL a car pack does not require its own car")
        bad += 1
    print(f"pages    : {len(plan['inside_pages'])} inside, "
          f"{len(plan['outside_pages'])} outside")
    print(f"publish  : {'ok' if not bad else str(bad) + ' bad'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
