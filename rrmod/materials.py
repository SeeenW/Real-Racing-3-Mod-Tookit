"""A panel for the parts' materials, and the library they are chosen from.

Every mesh in a car's ``.m3g`` carries a material name, but the game does not
read it from the model: it looks the mesh up in the car's livery tables and uses
*that* material, falling back to a hard coded one.  So a part that should look
like carbon, or a tyre that lives in ``vehicles/common``, is decided by a row in
``<car>.liveries.bin.nct``, not by the export.

There are two independent things a row can say, and a car uses both:

``materials``
    *this mesh slot uses that material name*.  A tyre pointed at
    ``car_tires`` looks like a tyre even though its atlas is somebody else's.

``textures``
    *this texture slot loads this file*.  The meshes that share a tag
    (``_mm_tyre``, ``_mm_rotor``, ``_mm_wheel``, ``_mm_mat00`` ...) all sample
    one page, and pointing that page somewhere else changes all of them at
    once.  That is how a car gets a different tread, a different disc or a
    different carbon weave without touching its meshes.

Both are written here, and the picker only lists what the game can actually be
told to use: a material with no slot in ``liveryStringTable.bin.nct`` cannot be
named by the engine, so offering it would be offering a name that does nothing.
"""

from __future__ import annotations

import os
import re

from rr3lib import livery as liverylib

#: Materials that are car paint, in the order a person thinks of them.  Kept
#: here rather than derived, because "is this paint" is a naming convention, not
#: a field: ``car_paint_matte`` and ``car_bumper_paint_black`` are both paints
#: but only the first belongs in a finish dropdown.
PAINT_PREFIX = "car_paint_"

#: Families worth grouping in the picker, longest prefix first.  These are the
#: prefixes the shipped ``materials.bin`` actually uses - ``car_rim``,
#: ``car_brake``, ``car_caliper``, ``car_chassis`` and ``car_carbon`` do not
#: exist, which is why a caliper is painted with ``car_flat`` and a disc with
#: ``car_rotor``.
GROUPS = (
    ("car_bumper_paint_", "Bumper paint"),
    ("car_paint_", "Car paint"),
    ("car_wheels_", "Wheels"),
    ("car_tires", "Tyres"),
    ("car_rotor", "Brakes"),
    ("car_glass", "Glass"),
    ("car_led_lights", "Lights"),
    ("car_light", "Lights"),
    ("car_lights", "Lights"),
    ("car_tail_light", "Lights"),
    ("car_badge_", "Badges"),
    ("car_bumper_badge_", "Badges"),
    ("car_body_plastic", "Badges"),
    ("car_bumper_body_plastic", "Badges"),
    ("car_bumper_", "Bumpers"),
    ("car_mirror", "Mirrors"),
    ("car_dash_", "Interior"),
    ("car_arms", "Interior"),
    ("car_cloth", "Interior"),
    ("car_stitching", "Interior"),
    ("car_nascar_net", "Interior"),
    ("car_grill", "Trim"),
    ("car_flat", "Trim"),
    ("car_gloss", "Trim"),
    ("car_matte", "Trim"),
    ("car_windscreen_cracks", "Glass"),
    ("car_alpha", "Effects"),
    ("add", "Effects"),
)

#: The texture slots the string table has, with what each one paints.  They are
#: a fixed set: a car either names one of these or it does not have that page.
TEXTURE_LABELS = {
    "ext_chassis": "Chassis",
    "ext_windows": "Windows",
    "ext_windows_cracked": "Windows, cracked",
    "ext_windows_shattered": "Windows, shattered",
    "ext_tyre": "Tyre tread",
    "ext_tyre_flipped": "Tyre tread, flipped",
    "ext_rotor": "Brake discs",
    "ext_wheel": "Wheels",
    "ext_wheel_blur": "Wheels, blurred",
    "ext_banner": "Banner",
    "ext_scratches": "Scratches",
    "ext_headlight_glow": "Lamp glow",
    "ext_cloak": "Cloak",
    "ext_ext": "Body (this scheme)",
    "ext_lights": "Lights",
    "ext_misc": "Miscellaneous",
    "ext_badges": "Badges",
    "ext_cab": "Cabin",
    "int_ext": "Interior body",
    "int_int": "Interior",
    "int_sw": "Steering wheel",
    "int_windows": "Interior windows",
    "int_windows_cracked": "Interior windows, cracked",
    "int_windows_shattered": "Interior windows, shattered",
    "int_banner": "Interior banner",
}
for _i in range(8):
    TEXTURE_LABELS[f"int_mat{_i:02d}"] = f"Interior material {_i:02d}"
del _i

#: ``ext_<tag>`` / ``int_<tag>``, which is what a texture slot is called.
_TEXTURE_RE = re.compile(r"^(ext|int)_([a-z0-9_]+)$")

#: ``LOD_A_BODY_mm_ext`` -> ``ext``.  A mesh's tag is the last part of its name.
_TAG_RE = re.compile(r"_mm_([a-z0-9_]+)$")

#: The eight interior pages, which are numbered on purpose.
_INTERIOR_RE = re.compile(r"^mat0[0-7]$")

#: The files a car can be made of, in the order the picker shows them.
MODELS = (
    ("A", "Body LOD A"),
    ("B", "Body LOD B"),
    ("C", "Body LOD C"),
    ("D", "Body LOD D"),
    ("E", "Body LOD E"),
    ("F", "Body LOD F"),
    ("G", "Body LOD G"),
    ("H", "Body LOD H"),
    ("shared", "Shared (wheels, brakes, lamps)"),
    ("int_a", "Interior LOD A"),
    ("int_b", "Interior LOD B"),
    ("frontend", "Front end (menus)"),
)


class MaterialError(Exception):
    pass


def group_of(name: str) -> str:
    """Which family a material belongs to, for grouping the dropdown."""
    low = name.lower()
    for prefix, label in GROUPS:
        if low.startswith(prefix):
            return label
    return "Other"


def library(depot: str) -> list:
    """Every material a mesh can actually be pointed at, sorted by group.

    ``SlotTable.materials()`` is the authority: those are the names the livery
    string table has slots for, and a material with no slot cannot be written.
    """
    table = liverylib.load_slot_table(depot)
    names = sorted(set(table.materials()))
    return sorted(names, key=lambda n: (group_of(n) != "Car paint",
                                        group_of(n), n.lower()))


def choices(depot: str, *, paints_only: bool = False) -> list:
    """``[(label, material)]`` for a dropdown, grouped by family."""
    out = []
    last = ""
    for name in library(depot):
        if paints_only and not name.startswith(PAINT_PREFIX):
            continue
        group = group_of(name)
        if group != last:
            out.append((f"--- {group} ---", ""))
            last = group
        out.append((name, name))
    return out


def paint_choices(depot: str) -> list:
    """Only the materials that are car paint (for a finish dropdown)."""
    return choices(depot, paints_only=True)


# ------------------------------------------------------------------ textures
def tag_of(mesh: str) -> str:
    """The texture tag of a mesh name: ``LOD_A_BODY_mm_ext`` -> ``ext``."""
    got = _TAG_RE.search(mesh or "")
    return got.group(1) if got else ""


def texture_slot_of(mesh: str, table) -> tuple:
    """``(slot, name)`` of the page a mesh samples, or ``(None, "")``.

    The rule is the one the shipped cars follow: ``ext_<tag>`` when the table
    has it, otherwise ``int_<tag>``.  A tag with neither (``chassis`` on most
    cars) has no page of its own and is drawn from the body atlas.

    **A trailing number on the tag is not part of the page name.**  The shipped
    models carry names like ``LOD_A_INT_GLASS_LEFT_mm_windows001`` and
    ``LOD_A_INT_STEERING_WHEEL_mm_mat002``; they read the *same* page as
    ``_mm_windows`` and ``_mm_mat00``, which is why the string table holds
    ``ext_windows`` and never ``ext_windows001``.  The digits are there to keep
    the two meshes apart, and stripping them is what lets a second pane of
    glass use the shared window atlas.

    The eight interior slots are the one place a number is meaningful, so
    ``mat00``..``mat07`` are tried before the number is stripped.
    """
    tag = tag_of(mesh)
    if not tag:
        return None, ""
    for candidate in (f"ext_{tag}", f"int_{tag}"):
        slot = table.slot(candidate)
        if slot is not None:
            return slot, candidate
    bare = _unumbered(tag)
    if bare and bare != tag:
        for candidate in (f"ext_{bare}", f"int_{bare}"):
            slot = table.slot(candidate)
            if slot is not None:
                return slot, candidate
    return None, ""


def _unumbered(tag: str) -> str:
    """``windows001`` -> ``windows``; the interior slots keep their number.

    ``mat00``..``mat07`` are eight different pages, so a tag that already names
    one of them is left alone.  Anything else loses its trailing digits, which
    is what lets ``windows001`` read the shared window page - the shipped
    ``LOD_A_INT_GLASS_LEFT_mm_windows001`` does exactly that.
    """
    low = str(tag or "")
    if _INTERIOR_RE.match(low):
        return low
    stripped = low.rstrip("0123456789")
    return stripped if stripped != low else ""


def texture_slots(depot: str) -> list:
    """Every texture slot the string table has: ``[(slot, name, label)]``."""
    table = liverylib.load_slot_table(depot)
    out = []
    for slot in range(len(table)):
        name = table[slot]
        if not _TEXTURE_RE.match(name):
            continue
        out.append((slot, name, TEXTURE_LABELS.get(name, name)))
    return out


def textures(root: str, car: str, *, model: str = "") -> list:
    """Every texture slot, with the file the car loads for it.

    ``from`` is ``"this car"`` when the file sits in the car's own folder,
    ``"common"`` when it is shared with every other car that names it, and
    ``"none"`` when the car does not name a page at all.

    ``model`` picks which file the *readers* column is read from, and defaults
    to every file the car has.  The page list itself is the same either way -
    a slot is a slot - but which meshes read it depends on the file, and a
    panel that showed the body's meshes while the interior was on screen was
    answering a question nobody asked.
    """
    depot = os.path.join(root, ".depot")
    table = liverylib.load_slot_table(depot)
    L = liverylib.load_car(depot, car)
    have = {}
    for slot, path in L.textures:
        have[slot] = path.decode("ascii", "replace")
    if model:
        models = [model]
    else:
        models = ["shared", "A", "int_a", "int_b"]
    users: dict = {}
    for name in models:
        try:
            rows = parts(root, car, model=name)
        except Exception:                      # noqa: BLE001 - a file may be absent
            continue
        for row in rows:
            slot, _slot_name = texture_slot_of(row["mesh"], table)
            if slot is not None:
                users.setdefault(slot, []).append(row["mesh"])
    out = []
    for slot, name, label in texture_slots(depot):
        path = have.get(slot, "")
        where = "none"
        if path:
            where = "common" if path.startswith("common/") else "this car"
        out.append({"slot": slot, "name": name, "label": label,
                    "path": path, "from": where,
                    "meshes": sorted(users.get(slot, []))})
    return out


def textures_summary(root: str, car: str, *, model: str = "") -> dict:
    rows = textures(root, car, model=model)
    return {"car": car, "slots": len(rows),
            "named": sum(1 for r in rows if r["path"]),
            "own": sum(1 for r in rows if r["from"] == "this car"),
            "common": sum(1 for r in rows if r["from"] == "common")}


# ------------------------------------------------------------------- models
def models(root: str, car: str) -> list:
    """The model files this car actually has: ``[(key, label, path)]``."""
    depot = os.path.join(root, ".depot")
    folder = os.path.join(depot, "vehicles", car)
    out = []
    for key, label in MODELS:
        name = f"{car}_{key.lower()}.m3g"
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            out.append((key, label, path))
    return out


# ------------------------------------------------------------------ reading
def _model_path(root: str, car: str, model: str) -> str:
    depot = os.path.join(root, ".depot")
    return os.path.join(depot, "vehicles", car, f"{car}_{model.lower()}.m3g")


def parts(root: str, car: str, *, lod: str = "A", model: str = "") -> list:
    """Every mesh of one model, with the material the game will give it.

    ``model`` picks the file: ``""`` (or a letter) is a body LOD, ``"shared"``
    is the wheels/brakes/lamps file that every LOD borrows from, ``"int_a"`` and
    ``"int_b"`` are the interior.  The shared file is where the tyres, discs and
    calipers live, so a panel that only reads the body cannot change them.

    ``mesh slot`` is the number the livery file indexes by, so it is what a row
    is written against.  ``source`` says where the material came from:
    ``paint`` (this scheme overrides it), ``car`` (the car's own table),
    ``default`` (the shipped fallback table) or ``none``.
    """
    from rr3lib import m3g as m3glib

    depot = os.path.join(root, ".depot")
    key = (model or lod).lower()
    path = _model_path(root, car, key)
    if not os.path.isfile(path):
        raise MaterialError(f"{car} has no {key} model")
    table = liverylib.load_slot_table(depot)
    L = liverylib.load_car(depot, car)
    try:
        default = liverylib.load_default(depot)
    except Exception:                           # noqa: BLE001
        default = None
    out = []
    seen = set()
    # A part's own slot can carry a texture row, and it is **not** what chooses
    # the page.  The engine resolves the page from the tag (``_mm_misc`` ->
    # ``ext_misc``) and never consults the part row; our own caliper proved it,
    # with rows on slots 88/90/92/94 pointing at its own art while it kept
    # drawing the car's misc page.  So the row is read only to report that it
    # exists and is ignored - showing it as the page would have the panel
    # contradict the screen, which is worse than showing nothing.
    by_slot = {}
    for row in getattr(L, "textures", ()) or ():
        try:
            by_slot[int(row[0])] = row[1].decode("ascii", "replace")
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
    doc = m3glib.M3G(path)
    for obj in doc.of_type(14):
        data = obj.data
        name = (data.get("name") or "")
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        if not name or name in seen:
            continue
        seen.add(name)
        mesh_slot = table.part_slot(name)
        tex_slot, tex_name = texture_slot_of(name, table)
        # Reported, never used: the page comes from the tag, full stop.
        part_row = by_slot.get(mesh_slot, "") if mesh_slot is not None else ""
        if mesh_slot is None:
            out.append({"mesh": name, "slot": None, "material": "",
                        "source": "no slot", "paints": {},
                        "texture_slot": tex_slot, "texture": tex_name,
                        "texture_from": "tag" if tex_slot is not None else "none",
                        "part_row": part_row, "tag": tag_of(name), "model": key})
            continue
        mat_slot, source = liverylib.resolve_material(L, mesh_slot, default)
        material = (table.name(mat_slot)
                    if mat_slot is not None and mat_slot < len(table) else "")
        paints = {}
        for paint in L.paints:
            got = paint.material_of(mesh_slot)
            if got is not None and got < len(table):
                paints[paint.name()] = table.name(got)
        out.append({"mesh": name, "slot": mesh_slot, "material": material,
                    "source": source, "paints": paints,
                    "texture_slot": tex_slot, "texture": tex_name,
                    "texture_from": "tag" if tex_slot is not None else "none",
                    "part_row": part_row, "tag": tag_of(name), "model": key})
    return out


def audit(root: str, car: str) -> dict:
    """Meshes the engine will refuse to draw, across every model of a car.

    A part name the string table does not hold has no slot, so no livery row can
    reach it *and* the engine's per-car reference list does not carry it - it is
    skipped at load with ``contains unreferenced mesh`` in the log.  That is
    worth saying out loud at build time, because the alternative is a part that
    is simply not there and no error to explain it.

    Returns ``{"skipped": [{"model", "mesh"}], "checked": n}``.
    """
    skipped = []
    checked = 0
    for key in MODEL_KEYS:
        if not os.path.isfile(_model_path(root, car, key)):
            continue
        try:
            rows = parts(root, car, model=key)
        except Exception:                       # noqa: BLE001
            continue
        for row in rows:
            checked += 1
            if row["slot"] is None:
                skipped.append({"model": key, "mesh": row["mesh"]})
    return {"skipped": skipped, "checked": checked}


def summary(root: str, car: str, *, lod: str = "A", model: str = "") -> dict:
    rows = parts(root, car, lod=lod, model=model)
    used: dict = {}
    for row in rows:
        if row["material"]:
            used[row["material"]] = used.get(row["material"], 0) + 1
    return {"car": car, "lod": lod, "model": model or lod, "meshes": len(rows),
            "with_slot": sum(1 for r in rows if r["slot"] is not None),
            "materials": len(used),
            "most_used": sorted(used.items(), key=lambda kv: -kv[1])[:8]}


# ------------------------------------------------------------------ identities
#: Every model file a car can carry.  A part name is unique across all of them
#: as far as the engine is concerned: the reference list it checks is per car,
#: not per file.
#:
#: This used to be called ``MODELS`` as well, which silently replaced the
#: ``(key, label)`` tuple above - every caller of :func:`models` then died
#: unpacking ``"a"`` into ``key, label``, and the Parts pane's model dropdown
#: came up empty for every car.  Two different things, two names.
MODEL_KEYS = ("a", "b", "c", "d", "e", "f", "g", "h", "shared",
              "int_a", "int_b", "frontend")


def used_meshes(root: str, car: str) -> set:
    """Every mesh name the car's models actually use.

    Read from the files, not from the livery table: a name can be in the table
    and still be unused by this car, which is exactly what makes it borrowable.
    """
    from rr3lib import m3g as m3glib

    out: set = set()
    for key in MODEL_KEYS:
        path = _model_path(root, car, key)
        if not os.path.isfile(path):
            continue
        try:
            doc = m3glib.M3G(path)
        except Exception:                       # noqa: BLE001
            continue
        for obj in doc.of_type(m3glib.T_MESH):
            name = obj.data.get("name") or ""
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            if name:
                out.add(name)
    return out


def free_names(root: str, car: str, *, lod: str = "A", tag: str = "",
               limit: int = 0) -> list:
    """Shipped part names this car does not use - identities a part can borrow.

    The engine keeps a **per-car reference list of part names** and silently
    skips a mesh that is not on it (the log says ``contains unreferenced
    mesh``).  Appending a name to ``liveryStringTable`` gives it a slot but does
    *not* put it on that list, so an invented ``LOD_A_FOO_mm_calipers`` is never
    drawn however many rows are written for it.  Borrowing a shipped name that
    this car happens to leave empty is the only way a custom part gets an
    identity of its own.

    ``lod`` filters to one LOD letter (``""`` for all), ``tag`` to one
    ``_mm_<tag>`` (``""`` for all).  Ordered so the most useful come first:
    same tag, then same LOD, then the rest.
    """
    depot = os.path.join(root, ".depot")
    table = liverylib.load_slot_table(depot)
    used = used_meshes(root, car)
    out = []
    for name in table.names:
        if not name.startswith("LOD_") or name in used:
            continue
        parts_ = name.split("_")
        if len(parts_) < 3:
            continue
        if lod and parts_[1] != lod.upper():
            continue
        if tag and not name.endswith("_mm_" + tag):
            continue
        out.append(name)
    if limit:
        out = out[:limit]
    return out


def selftest(depot: str) -> int:
    """Read every car's LOD A and count the ones that would not resolve."""
    from . import depot as depotlib

    inv = depotlib.scan(depot)
    bad = 0
    for entry in inv.cars:
        if not entry.has_body:
            continue
        try:
            rows = parts(inv.root, entry.name)
        except Exception:                       # noqa: BLE001
            bad += 1
            continue
        if not rows:
            bad += 1
    return bad
