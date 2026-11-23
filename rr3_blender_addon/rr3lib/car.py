"""Add a whole new car to the game: every shared table, the folder and the lists.

Adding a car is not one file.  The engine keys almost everything off two numbers -
the **car id** (a spec file ``<id>_<name>.bin.nct`` plus a row in six tables) and
the **appearance id** (a record in ``carappearances.appearances.nct`` whose name
*is* the asset folder name).  Both must be consistent or the car never appears.

What this module writes, all derived from a donor car that already works:

===========================  ===============================================
``<id>_<name>.bin.nct``      the spec: id, model token, display key, appearance
                             id, and the active-aero behaviour token
``cardesc.list.nct``         the ``<id>_<name>.bin`` list, kept id sorted
``suspensiondata.nct``       140 byte record, cloned from the donor
``cardamagethresholds``      116 byte record, cloned from the donor
``appearances.nct``          a new record whose name is the new folder name
``liveries/<name>...nct``    the paint schemes, with the wing material fixed up
``vehicles/<name>/``         every donor file renamed, plus donor-named aliases
``asset_list_vehicle_<n>``   the per car manifest
``asset_list_vehicle_data``  the data manifest row for the new spec
``asset_list_base.txtCache`` the master registry rows
===========================  ===============================================

Two details cost a full day each when missed, so they are enforced here:

* **The donor-named alias copies.**  The engine opens textures by the *donor*
  base name (``2012_lexus_lfa_lights.dxt.dds.z``) even when the mesh lives in the
  new folder, because the name is baked into the m3g.  Without aliases every
  texture comes out magenta.
* **The active aero token.**  ``DeployWhenBraking`` must replace the empty token
  in front of ``generic_race`` *in place*.  Inserting a token shifts the stream
  and the engine dereferences null at ``+0x18``.
"""

from __future__ import annotations

import hashlib
import os
import shutil

from . import appearance as appearlib
from . import livery as liverylib
from . import manifest as manifestlib
from . import nct as nctlib
from . import spec as speclib


class CarError(Exception):
    pass


# ---------------------------------------------------------------- validation
def find_spec(depot: str, name: str) -> tuple[int, str]:
    """``(car_id, stem)`` for a car folder name, e.g. ``2012_lexus_lfa``."""
    folder = os.path.join(depot, *speclib.SPEC_DIR.split("/"))
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".bin.nct") or not f.split("_")[0].isdigit():
            continue
        stem = f[: -len(".bin.nct")]
        if stem.split("_", 1)[1] == name:
            return int(stem.split("_")[0]), stem
    raise CarError(f"no spec file for car {name!r} in {folder}")


def used_ids(depot: str) -> set[int]:
    folder = os.path.join(depot, *speclib.SPEC_DIR.split("/"))
    out = set()
    for f in os.listdir(folder):
        if f.endswith(".bin.nct") and f.split("_")[0].isdigit():
            out.add(int(f.split("_")[0]))
    return out


def free_car_id(depot: str) -> int:
    ids = used_ids(depot)
    return max(ids) + 1


def check_name(name: str) -> None:
    """The folder name is also the asset prefix, so keep it filesystem safe."""
    if not name or any(c in name for c in '\\/:*?"<>|'):
        raise CarError(f"bad car name {name!r}")
    if not name[0].isdigit():
        raise CarError(
            f"{name!r} should start with the model year (e.g. 2012_lexus_lfa)")


# ------------------------------------------------------------------ the spec
def build_spec(depot: str, *, donor_name: str, new_id: int, new_name: str,
               display_key: str = "", model_token: str = "",
               appearance_id: int | None = None, aero: bool = True,
               make: str = "", aero_kind: bytes = b"", aero_params=()):
    """Clone the donor spec and retarget every number and string in it."""
    _donor_id, stem = find_spec(depot, donor_name)
    spec = speclib.load_spec(depot, stem)

    old_model = spec.model()
    if not model_token:
        # <year>_<make>_<model>, so the token is the part after the make
        parts = new_name.split("_")
        model_token = "_".join(parts[2:]).upper() if len(parts) > 2 else old_model
    if not display_key:
        display_key = new_name.replace("_", "-")

    if appearance_id is None:
        count, recs = appearlib.load(depot)
        appearance_id = appearlib.free_id(recs)

    spec.set_car_id(int(new_id))
    spec.set_model(model_token)
    spec.set_display_name(display_key)
    spec.set_appearance_id(int(appearance_id))
    if aero:
        # ``aero_kind`` picks which behaviour: braking only, speed only, both
        # (which is what the Senna and the Jesko do) or the NASCAR air brake.
        # Left empty, the donor's own behaviour is kept.
        spec.set_aero(True, kind=aero_kind, params=aero_params)
    if make:
        # The manufacturer is one string and nothing else refers to it, so
        # naming a brand that has never existed costs nothing: the car becomes
        # the first one filed under it.
        spec.set_make(make)
    return spec, appearance_id, display_key, model_token


# ------------------------------------------------------------- the six tables
def build_cardesc(depot: str, *, new_id: int, new_name: str):
    desc = speclib.load_cardesc(depot)
    desc.add(f"{new_id}_{new_name}.bin")
    return desc


def build_suspension(depot: str, *, donor_id: int, new_id: int):
    table = speclib.load_suspension(depot)
    rec = bytearray(table.get(donor_id))
    rec[0:4] = int(new_id).to_bytes(4, "little")
    table.add(bytes(rec))
    return table


def build_damage(depot: str, *, donor_id: int, new_id: int):
    table = speclib.load_damage(depot)
    rec = bytearray(table.get(donor_id))
    rec[0:4] = int(new_id).to_bytes(4, "little")
    table.add(bytes(rec))
    return table


def build_appearance(depot: str, *, donor_name: str, new_name: str,
                     new_id: int | None = None, wheel_sizes=None):
    """Clone the donor's appearance record under the new folder name.

    ``wheel_sizes`` overrides the record's first eight floats - the wheel block.
    They are **absolute metres**: ``f1``/``f5`` are the tyre radius the engine
    draws and ``f2``/``f6`` the rim radius, both 1:1.  That is why a pack whose
    wheel mesh was normalised to the shared template (so one model can serve both
    axles) still comes out at the car's own tyre size: the size lives here, not
    in the mesh.  Accepts ``{index: value}`` or any eight-item sequence; zero or
    ``None`` keeps the donor's value.
    """
    count, recs = appearlib.load(depot)
    rec = appearlib.add_record(recs, donor_name, new_id=new_id,
                               new_name=new_name.encode("ascii"))
    if wheel_sizes:
        values = list(rec.wheel_sizes())
        pairs = (wheel_sizes.items() if isinstance(wheel_sizes, dict)
                 else enumerate(wheel_sizes))
        for i, x in pairs:
            i = int(i)
            if not (0 <= i < 8) or x is None:
                continue
            x = float(x)
            if x > 0:
                values[i] = x
        rec.set_wheel_sizes(values)
    return count + 1, recs, rec


def build_livery(depot: str, *, donor_name: str, new_name: str,
                 wing_part: str = "LOD_A_WING_REAR_mm_ext",
                 body_part: str = "LOD_A_BODY_mm_ext",
                 copy_body_paint: bool = True, paints=None):
    """Copy the donor's paint schemes and make the wing follow the body paint.

    The wing material is the one thing a donor clone cannot inherit: the donor
    has no wing part, so its livery tables have no row for it and the engine
    falls back to ``car_flat``.  Writing ``wing -> body`` per scheme is exactly
    what the shipped cars with a body coloured wing do.

    ``paints`` is a list of donor paint indices to keep, in the order they should
    appear.  ``None`` keeps every scheme.  Dropping one is safe - the game reads
    the list in order and nothing else in the file refers to a paint by index -
    but a car with no schemes at all shows up unpainted, so an empty list is
    refused.
    """
    L = liverylib.load_car(depot, donor_name)
    L.car = new_name.encode("ascii")
    # texture overrides point into the car folder; keep them pointing at files
    # that exist under the new name (the builder also writes donor aliases)
    for i, (slot, path) in enumerate(L.textures):
        L.textures[i] = (slot, path.replace(donor_name.encode(), new_name.encode()))
    for p in L.paints:
        for i, (slot, path) in enumerate(p.overrides):
            p.overrides[i] = (slot, path.replace(donor_name.encode(),
                                                 new_name.encode()))
    dropped = 0
    if paints is not None:
        wanted = [int(i) for i in paints]
        if not wanted:
            raise CarError("a car needs at least one paint scheme")
        for index in wanted:
            if not 0 <= index < len(L.paints):
                raise CarError(
                    f"paint scheme {index} does not exist "
                    f"(the donor has {len(L.paints)})")
        kept = [L.paints[i] for i in wanted]
        dropped = len(L.paints) - len(kept)
        L.paints = kept
    table = liverylib.load_slot_table(depot)
    info = {"wing": None, "changed": [], "skipped": [], "dropped": dropped}
    if copy_body_paint:
        info = L.copy_body_paint(wing_part, body_part=body_part, table=table)
        info["dropped"] = dropped
    return L, table, info


# ---------------------------------------------------------------- the folder
def build_folder(depot: str, out_dir: str, *, donor_name: str, new_name: str,
                 body_m3g: str | None = None, extra: list[str] | None = None,
                 aliases: bool = True, slot_files: dict | None = None):
    """Copy the donor folder under the new name.

    ``body_m3g`` replaces ``<donor>_a.m3g`` (the body LOD, i.e. the model you
    edited).  ``extra`` files are copied in by basename.  With ``aliases`` every
    copied file also gets a second copy under its original donor basename, which
    is what the engine looks up: texture names are baked into the .m3g, so a car
    whose folder only holds renamed textures loads them as flat magenta.

    ``slot_files`` is ``{the name the game expects: source path}`` and is how a
    file called ``LOD_C.m3g`` in an export folder becomes ``<car>_c.m3g`` here.
    It wins over the donor's copy of the same file, so a build that brings its
    own ``_shared.m3g`` gets that one and not the donor's.
    """
    src = os.path.join(depot, "vehicles", donor_name)
    if not os.path.isdir(src):
        raise CarError(f"donor folder missing: {src}")
    dst = os.path.join(out_dir, new_name)
    if os.path.isdir(dst):
        shutil.rmtree(dst)

    #: target file name -> source, so the donor's copy can be skipped
    overrides = dict(slot_files or {})
    copied = 0
    pairs = []                       # (new path, donor basename)
    for dirpath, _dirs, files in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        for f in files:
            s = os.path.join(dirpath, f)
            target = f.replace(donor_name, new_name, 1)
            t = os.path.join(dst, target) if rel == "." else os.path.join(dst, rel, target)
            os.makedirs(os.path.dirname(t), exist_ok=True)
            if rel == "." and target in overrides:
                shutil.copyfile(overrides.pop(target), t)
            elif body_m3g and f == f"{donor_name}_a.m3g":
                shutil.copyfile(body_m3g, t)
            else:
                shutil.copyfile(s, t)
            copied += 1
            if target != f:
                pairs.append((t, os.path.join(os.path.dirname(t), f)))

    n_alias = 0
    if aliases:
        for t, alias in pairs:
            if not os.path.exists(alias):
                shutil.copyfile(t, alias)
                n_alias += 1

    for e in extra or []:
        name = os.path.basename(e).replace(donor_name, new_name, 1)
        shutil.copyfile(e, os.path.join(dst, name))
        copied += 1

    # whatever the donor did not have at all (a wing animation, an extra LOD)
    for name, source in overrides.items():
        shutil.copyfile(source, os.path.join(dst, name))
        copied += 1
    return {"files": copied, "aliases": n_alias, "dir": dst}


# --------------------------------------------------------------- the manifests
def build_car_manifest(pkg: str, out_path: str, *, donor_name: str,
                       new_name: str, extra: list[str] | None = None):
    src = os.path.join(pkg, "apk", "res", f"asset_list_vehicle_{donor_name}.txt")
    if not os.path.exists(src):
        raise CarError(f"donor manifest missing: {src}")
    rows = manifestlib.read_car_manifest(src)
    rows = manifestlib.rename_car_manifest(rows, donor_name, new_name, extra)
    manifestlib.write_car_manifest(rows, out_path)
    return rows


def build_registry(depot: str, out_path: str, *, new_rows, changed: dict,
                   vehicle_dir: str | None = None):
    """Merge the new rows and the changed table hashes into the registry."""
    reg = manifestlib.load_registry(depot)
    added = 0
    for path, md5, _p, _r in new_rows:
        if vehicle_dir and path.startswith("/vehicles/"):
            local = os.path.join(vehicle_dir, path.rsplit("/", 1)[1])
            if not os.path.exists(local):
                continue            # the donor lists .atc/.etc variants we do not ship
        if reg.set(path, md5):
            added += 1
    updated = 0
    for path, (md5, _p, _r) in changed.items():
        if reg.set(path, md5):
            updated += 1
    manifestlib.save_registry(reg, out_path)
    return {"added": added, "updated": updated, "total": len(reg)}


def build_data_list(pkg: str, out_path: str, *, new_files, changed: dict):
    """Update the hashes of shipped tables and insert the brand new files.

    ``changed`` may only hold paths the list already carries; anything new goes
    through ``new_files`` as ``(path, local file)`` pairs.
    """
    dl = manifestlib.load_data_list(pkg)
    known = set(dl.paths())
    updated = 0
    for path, (md5, packed, raw) in changed.items():
        if path not in known:
            continue
        if dl.update(path, md5, packed, raw):
            updated += 1
    inserted = 0
    for path, local in new_files:
        if path in known:
            if dl.update(path, manifestlib.md5_file(local),
                         os.path.getsize(local), os.path.getsize(local)):
                updated += 1
            continue
        size = os.path.getsize(local)
        dl.insert(path, manifestlib.md5_file(local), size, size)
        inserted += 1
    manifestlib.save_data_list(dl, out_path)
    return {"updated": updated, "inserted": inserted, "rows": len(dl)}


# ------------------------------------------------------------------ one shot
def build_car(depot: str, pkg: str, out_dir: str, *, new_id: int,
              new_name: str, donor_name: str, body_m3g: str | None = None,
              extra: list[str] | None = None, display_key: str = "",
              model_token: str = "", appearance_id: int | None = None,
              aero: bool = True, aliases: bool = True, seed_shared: bool = True,
              paints=None, car_class: str = "", make: str = "",
              slot_files: dict | None = None,
              aero_kind: bytes = b"", aero_params=(),
              wheel_sizes=None, log=print) -> dict:
    """Write every file a new car needs under ``out_dir`` (a ``files/`` mirror).

    ``out_dir`` is written as a mirror of the game's ``files`` folder, so the
    result can be read back with the same readers and pushed as is::

        <out_dir>/.depot/vehicles/data/...      the six tables and the spec
        <out_dir>/.depot/vehicles/<name>/       the car folder
        <out_dir>/.depot/asset_list_base.txtCache.txt
        <out_dir>/apk/res/asset_list_vehicle_<name>.txt
        <out_dir>/apk/res/asset_list_vehicle_data.txt

    ``seed_shared`` also copies the two shared livery tables
    (``liveryStringTable.bin.nct`` and ``default.liveries.bin.nct``) into the
    mirror, which makes it a self-contained depot the tools can read back; the
    deploy step does not need to push them.
    """
    check_name(new_name)
    donor_id, _stem = find_spec(depot, donor_name)
    if new_id in used_ids(depot):
        raise CarError(f"car id {new_id} is already used")

    out_depot = os.path.join(out_dir, ".depot")
    data = os.path.join(out_depot, *speclib.SPEC_DIR.split("/"))
    res = os.path.join(out_dir, "apk", "res")
    os.makedirs(data, exist_ok=True)
    os.makedirs(os.path.join(data, "liveries"), exist_ok=True)
    os.makedirs(res, exist_ok=True)
    out = {"new_id": new_id, "new_name": new_name, "donor": donor_name,
           "out_depot": out_depot, "out_pkg": out_dir}

    if seed_shared:
        lv_src = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"))
        lv_dst = os.path.join(data, "liveries")
        for f in (os.path.basename(liverylib.SLOT_TABLE),
                  os.path.basename(liverylib.DEFAULT_LIVERY)):
            src = os.path.join(lv_src, f)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(lv_dst, f))
        log(f"  shared      : livery string table + default livery copied")

    # 1. spec
    spec, appearance_id, display_key, model_token = build_spec(
        depot, donor_name=donor_name, new_id=new_id, new_name=new_name,
        display_key=display_key, model_token=model_token,
        appearance_id=appearance_id, aero=aero, make=make,
        aero_kind=aero_kind, aero_params=aero_params)
    class_changed = False
    if car_class:
        class_changed = spec.set_class(car_class)
    spec_path = os.path.join(data, f"{new_id}_{new_name}.bin.nct")
    speclib.save_spec(spec, spec_path)
    out.update(spec=spec_path, appearance_id=appearance_id,
               display_key=display_key, model_token=model_token,
               car_class=car_class, class_changed=class_changed, make=make)
    log(f"  spec        : {os.path.basename(spec_path)} "
        f"(appearance {appearance_id}, aero {'on' if aero else 'off'}"
        f"{', class ' + car_class if class_changed else ''}"
        f"{', make ' + make if make else ''})")

    # 2. cardesc / suspension / damage
    desc = build_cardesc(depot, new_id=new_id, new_name=new_name)
    speclib.save_cardesc(desc, os.path.join(data, "cardesc.list.nct"))
    susp = build_suspension(depot, donor_id=donor_id, new_id=new_id)
    nctlib.write(os.path.join(data, "suspensionbehaviour.suspensiondata.nct"),
                 susp.to_bytes())
    dmg = build_damage(depot, donor_id=donor_id, new_id=new_id)
    nctlib.write(os.path.join(data, "cardamagethresholds.damage.nct"),
                 dmg.to_bytes())
    log(f"  cardesc     : {desc.summary()}")
    log(f"  suspension  : {susp.summary()}")
    log(f"  damage      : {dmg.summary()}")

    # 3. appearance record
    count, recs, rec = build_appearance(depot, donor_name=donor_name,
                                        new_name=new_name,
                                        new_id=appearance_id,
                                        wheel_sizes=wheel_sizes)
    appearlib.save(count, recs, os.path.join(data, "carappearances.appearances.nct"))
    log(f"  appearances : {count} records, new id {rec.id} name {rec.name.decode()}")

    # 4. liveries
    L, table, info = build_livery(depot, donor_name=donor_name,
                                  new_name=new_name, paints=paints)
    livery_path = os.path.join(data, "liveries", f"{new_name}.liveries.bin.nct")
    liverylib.save(L, livery_path)
    out.update(livery=livery_path, wing_material=info)
    log(f"  liveries    : {len(L.paints)} scheme(s), wing material written for "
        f"{len(info['changed'])}/{len(L.paints)}"
        f"{', dropped ' + str(info['dropped']) if info.get('dropped') else ''}")

    # 5. folder
    folder = build_folder(depot, os.path.join(out_depot, "vehicles"),
                          donor_name=donor_name, new_name=new_name,
                          body_m3g=body_m3g, extra=extra, aliases=aliases,
                          slot_files=slot_files)
    out["folder"] = folder
    log(f"  folder      : {folder['files']} files + {folder['aliases']} aliases")

    # 6. manifests
    rows = build_car_manifest(pkg, os.path.join(
        res, f"asset_list_vehicle_{new_name}.txt"),
        donor_name=donor_name, new_name=new_name, extra=extra)
    out["manifest_rows"] = len(rows)

    changed = {}
    for name in ("cardesc.list.nct",
                 "suspensionbehaviour.suspensiondata.nct",
                 "cardamagethresholds.damage.nct",
                 "carappearances.appearances.nct"):
        fp = os.path.join(data, name)
        if os.path.exists(fp):
            blob = open(fp, "rb").read()
            changed[f"/vehicles/data/{name}"] = (
                hashlib.md5(blob).hexdigest(), len(blob), len(blob))

    new_data = [(f"/vehicles/data/{new_id}_{new_name}.bin.nct", spec_path),
                (f"/vehicles/data/liveries/{new_name}.liveries.bin.nct",
                 livery_path)]

    # the new spec and livery go into the registry as well
    reg_entries = dict(changed)
    for path, fp in new_data:
        blob = open(fp, "rb").read()
        reg_entries[path] = (hashlib.md5(blob).hexdigest(), len(blob), len(blob))

    vehicle_dir = os.path.join(out_depot, "vehicles", new_name)
    reg = build_registry(depot,
                         os.path.join(out_depot, "asset_list_base.txtCache.txt"),
                         new_rows=rows, changed=reg_entries, vehicle_dir=vehicle_dir)
    out["registry"] = reg
    log(f"  registry    : +{reg['added']} rows, ~{reg['updated']} updated, "
        f"{reg['total']} total")

    dl = build_data_list(pkg, os.path.join(res, "asset_list_vehicle_data.txt"),
                         new_files=new_data, changed=changed)
    out["data_list"] = dl
    log(f"  data list   : ~{dl['updated']} updated, +{dl['inserted']} new, "
        f"{dl['rows']} rows")
    return out


# --------------------------------------------------------------- paint helper
def set_part_material(depot: str, car: str, part: str, material: str,
                      paints: list[int] | None = None):
    """Give one part one material in a car's livery tables, then save it."""
    L = liverylib.load_car(depot, car)
    table = liverylib.load_slot_table(depot)
    info = L.paint_part(part, material, table=table, paints=paints)
    liverylib.save(L, os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                                   f"{car}.liveries.bin.nct"))
    return info


def audit_paint(depot: str, car: str, meshes: list[str],
                paint_index: int | None = None):
    """Which material each of ``meshes`` ends up with, and where it came from."""
    L = liverylib.load_car(depot, car)
    table = liverylib.load_slot_table(depot)
    default = liverylib.load_default(depot)
    return liverylib.audit(L, table, default, meshes, paint_index)
