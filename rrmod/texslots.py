"""Which picture fills which texture slot of a car, worked out from the files.

A car's folder holds a dozen pages of its own - ``<car>_misc``, ``<car>_wheel``,
``<car>_lights`` - and the livery table is what names them.  The Blender side
writes ``misc.png`` and stops, exactly as it writes ``LOD_A.m3g``, so this
module turns a folder of pictures into the same kind of slot table
:mod:`rrmod.slots` builds for the models:

* **the slot is read, not guessed.**  ``liveryStringTable`` has a name for each
  page (``ext_misc``), and the car's own livery table says which file it loads
  for that name.  The stem - ``misc`` - is what the exporter's file name has to
  match.
* **the target name is the game's.**  ``misc.png`` becomes
  ``<car>_misc.dxt.dds.z``, the same way ``LOD_A.m3g`` becomes
  ``<car>_a.m3g``.
* **a picture is converted, not refused.**  The game cannot load a PNG, so a
  picture is encoded into the family the settings name (or the family the page
  already is) at the moment the build runs - never before, because a build the
  user cancels must not have touched anything.

Two kinds of page are told apart, and they are written to different places:

* **a page of the car's own** lives in the car's folder and every paint scheme
  loads it unless it overrides the slot.
* **a livery page** lives in ``<car>/livery/`` and belongs to one paint scheme.
  There are exactly two such slots in every car (``ext_ext`` the body and
  ``int_ext`` its interior copy), and a scheme that has one always names both.

Nothing here imports Qt or writes anything.
"""

from __future__ import annotations

import os
import re

from rr3lib import livery as liverylib

#: Suffixes a finished page is stored under, longest first so ``.dxt.dds.z`` is
#: never read as ``.dds.z``.
PAGE_SUFFIXES = (".dxt.dds.z", ".dxt.dds.bin", ".etc.dds.z", ".atc.dds.z",
                 ".ptc.pvr.z", ".rgb.pvr.z", ".dds.z", ".pvr.z", ".dds", ".pvr")

#: What a picture can be.  A file with one of these is encoded when the build
#: runs; anything else is a page already.
PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tga", ".tif",
                    ".tiff")

#: The folder whose pages every car can point at.  Its files are named after
#: what they are (``car_tyre_slick_03``), because no table says so.
COMMON_FOLDER = "vehicles/common"

#: The pages a car keeps in its own folder, in the order a person thinks of
#: them.  ``(stem, label)``.  This is only the *fallback* list: the truth comes
#: from the car's livery table, because a car that has no ``wheel_blur`` page
#: should not be offered one.
STANDARD = (
    ("misc", "Miscellaneous parts - calipers, grilles, small trim"),
    ("wheel", "Wheels"),
    ("wheel_blur", "Wheels, blurred - used while the car is moving"),
    ("mask", "Paint mask - which parts the paint colour reaches"),
    ("lights", "Lights"),
    ("cab", "Cockpit shell"),
    ("int", "Interior"),
    ("sw", "Steering wheel"),
    ("sha", "Shading and ambient occlusion"),
    ("badges", "Badges"),
    ("ext_shadows_high", "Shadow map, exterior"),
    ("int_shadows", "Shadow map, interior"),
)

#: The slot the body of a paint scheme is drawn from, and the interior's copy of
#: the same page.  Every shipped car names both, always at the same file.
BODY_SLOT = 1932            # ``ext_ext``
INT_BODY_SLOT = 1939        # ``int_ext``

#: The label the body slot gets in a table.
BODY_LABEL = "Body - the picture the paint scheme draws with"


class TexSlotError(Exception):
    """Raised when a slot table cannot be built."""


# ------------------------------------------------------------------ suffixes
def page_suffix(name: str) -> str:
    """The page suffix ``name`` ends with, or ``""``."""
    low = str(name or "").lower()
    for suffix in PAGE_SUFFIXES:
        if low.endswith(suffix):
            return name[-len(suffix):]
    return ""


def picture_suffix(name: str) -> str:
    """The picture suffix ``name`` ends with, or ``""``."""
    low = str(name or "").lower()
    for suffix in PICTURE_SUFFIXES:
        if low.endswith(suffix):
            return name[-len(suffix):]
    return ""


def is_picture(name: str) -> bool:
    """True for a file the build has to encode before the game can load it."""
    return bool(picture_suffix(name))


def stem_of(name: str, car: str = "") -> str:
    """``2012_lexus_lfa_misc.dxt.dds.z`` -> ``misc``.

    Both spellings are accepted: the exporter may write ``misc.png`` or a file
    that already carries the car's name.  A suffix is dropped whether it is a
    page's or a picture's.
    """
    leaf = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = page_suffix(leaf) or picture_suffix(leaf)
    stem = leaf[:-len(suffix)] if suffix else leaf
    if car and stem.startswith(car + "_"):
        stem = stem[len(car) + 1:]
    return stem


def clean_stem(name: str) -> str:
    """Fold a name into the shape shipped page names have.

    ``My Wheel.png`` -> ``my_wheel``.  The engine's token matching is
    lowercase-with-underscores, and a name that is not that shape is a name
    nothing will find.
    """
    stem = stem_of(name)
    stem = stem.lower().replace("-", "_").replace(" ", "_")
    stem = re.sub(r"[^a-z0-9_]+", "_", stem)
    return re.sub(r"_{2,}", "_", stem).strip("_")


# ------------------------------------------------------------------- the slots
def car_pages(depot: str, car: str) -> list:
    """Every page of ``car``'s own folder, as the livery table names it.

    A row is ``{slot, name, stem, rel, suffix, path}``.  ``slot`` is the id in
    ``liveryStringTable`` (``None`` for a row taken from :data:`STANDARD` when
    the car has no livery table at all), ``rel`` the path the livery names
    (relative to the car folder) and ``path`` where the file is, or ``""``.

    ``common/`` rows are left out on purpose: those are shared pages, they are
    not part of the car's export, and the Dependencies page is where they are
    managed.  ``livery/`` rows are left out too - they are per-scheme, and
    :func:`livery_pages` is what returns those.
    """
    rows = []
    L = None
    try:
        L = liverylib.load_car(depot, car)
    except Exception:                            # noqa: BLE001 - no table, fall back
        L = None
    if L is not None:
        rows = []
        seen = set()
        # Two slots can name the same page - ``int_sw`` and ``int_mat05`` both
        # load ``<car>_sw`` - so the region slots are read first and a stem is
        # only kept once.  The page is one file; two rows for it would offer the
        # same slot twice in every table.
        ordered = sorted(L.textures, key=lambda row: _slot_rank(depot, row[0]))
        for slot, raw in ordered:
            rel = raw.decode("utf-8", "replace").replace("\\", "/")
            if not rel or rel.startswith("common/") or rel.startswith("livery/"):
                continue
            suffix = page_suffix(rel)
            if not suffix:
                continue
            stem = stem_of(rel, car)
            if not stem or stem in seen:
                continue
            seen.add(stem)
            path = _page_on_disk(depot, car, stem)
            rows.append({"slot": int(slot), "name": _slot_name(depot, slot),
                         "stem": stem, "rel": rel, "suffix": suffix,
                         "path": path})
        if rows:
            return rows
    # No livery table (or none of its rows is a page of the car's own): the
    # standard list is the best guess, and it is only used to *show* what a
    # build could fill - the target name is computed from the stem anyway.
    for stem, _label in STANDARD:
        rows.append({"slot": None, "name": "", "stem": stem,
                     "rel": "", "suffix": "", "path": ""})
    return rows


def livery_pages(depot: str, car: str) -> list:
    """The two per-scheme pages: the body atlas and the interior's copy."""
    rows = []
    try:
        L = liverylib.load_car(depot, car)
    except Exception:                            # noqa: BLE001
        L = None
    if L is not None:
        for slot, raw in L.textures:
            rel = raw.decode("utf-8", "replace").replace("\\", "/")
            if not rel.startswith("livery/"):
                continue
            if int(slot) == INT_BODY_SLOT:
                continue                          # the same file as the body
            rows.append({"slot": int(slot), "name": _slot_name(depot, slot),
                         "rel": rel, "suffix": page_suffix(rel)})
    if not rows:
        rows = [{"slot": BODY_SLOT, "name": "ext_ext", "rel": "", "suffix": ""}]
    return rows


def _slot_name(depot: str, slot: int) -> str:
    try:
        return liverylib.load_slot_table(depot).name(int(slot))
    except Exception:                            # noqa: BLE001
        return ""


def _slot_rank(depot: str, slot: int) -> int:
    """0 for a region slot (``ext_sw``), 1 for a material one (``int_mat05``).

    Both can name the same page; the region slot is the one a person thinks of
    when they say "the steering wheel".
    """
    name = _slot_name(depot, slot)
    if not name:
        return 1
    tail = name.rsplit("_", 1)[-1]
    return 0 if not (len(tail) == 5 and tail.startswith("mat")) else 1


def _page_on_disk(depot: str, car: str, stem: str) -> str:
    """Where a page of the car's own is, in whichever family this depot holds.

    The livery names whichever copy its device would load - ``.ptc.pvr.z`` - and
    a depot unpacked for another GPU holds the same page as ``.dxt.dds.z``.  That
    is normal, not a broken install, so every known suffix is tried.
    """
    folder = os.path.join(depot, "vehicles", car)
    for suffix in PAGE_SUFFIXES:
        path = os.path.join(folder, f"{car}_{stem}{suffix}")
        if os.path.isfile(path):
            return path
    for suffix in PAGE_SUFFIXES:
        path = os.path.join(folder, f"{stem}{suffix}")
        if os.path.isfile(path):
            return path
    return ""


def body_slot(depot: str) -> int:
    """The id of ``ext_ext`` in this install's table, or 1932."""
    try:
        table = liverylib.load_slot_table(depot)
    except Exception:                            # noqa: BLE001
        return BODY_SLOT
    got = table.slot("ext_ext")
    return int(got) if got is not None else BODY_SLOT


def interior_slot(depot: str) -> int:
    """The id of ``int_ext`` - the interior's copy of the body page."""
    try:
        table = liverylib.load_slot_table(depot)
    except Exception:                            # noqa: BLE001
        return INT_BODY_SLOT
    got = table.slot("int_ext")
    return int(got) if got is not None else INT_BODY_SLOT


def scheme_slots(depot: str, car: str) -> list:
    """Every slot one paint scheme can give a picture of its own.

    The body comes first and is the only one a new scheme must set; the rest are
    the car's own pages (a scheme may override any of them - 196 shipped schemes
    point the wheels at another page, 71 the windows).  ``key`` is what the
    dialog and :func:`rrmod.edit.set_livery_textures` speak: ``"body"`` for the
    pair ``ext_ext``/``int_ext``, and the page stem for everything else.
    """
    out = [{"key": "body", "slot": body_slot(depot), "name": "ext_ext",
            "label": BODY_LABEL, "stem": "ext", "required": True}]
    for row in car_pages(depot, car):
        if not row["stem"]:
            continue
        out.append({"key": row["stem"], "slot": row["slot"],
                    "name": row["name"] or ("ext_" + row["stem"]),
                    "label": row["stem"].replace("_", " ").capitalize(),
                    "stem": row["stem"], "required": False})
    return out


# ------------------------------------------------------------------ the folder
def folder_pictures(folder: str, car: str = "") -> list:
    """Every texture and picture in an export folder, recognised.

    A row is ``{path, leaf, stem, suffix, picture, place}`` where ``place`` is
    ``"car"`` for a file at the top of the folder and ``"livery"`` for one in
    its ``livery/`` subfolder.  Anything that is neither a page nor a picture is
    left out - an export folder also holds models and anchors.
    """
    out = []
    if not folder or not os.path.isdir(folder):
        return out
    for place, sub in (("car", ""), ("livery", "livery")):
        base = os.path.join(folder, sub) if sub else folder
        if not os.path.isdir(base):
            continue
        for leaf in sorted(os.listdir(base)):
            path = os.path.join(base, leaf)
            if not os.path.isfile(path):
                continue
            suffix = page_suffix(leaf) or picture_suffix(leaf)
            if not suffix:
                continue
            out.append({"path": path, "leaf": leaf,
                        "stem": stem_of(leaf, car), "suffix": suffix,
                        "picture": is_picture(leaf), "place": place})
    return out


def guess(folder: str, car: str, rows) -> dict:
    """``{stem: file row}`` for the car pages a folder can fill.

    A file is matched to a slot by its stem, and a file already named for the
    car wins over a bare one (``2012_lexus_lfa_misc.png`` over ``misc.png``),
    because that is the one the exporter meant.
    """
    want = {row["stem"] for row in rows if row["stem"]}
    out: dict = {}
    for item in folder_pictures(folder, car):
        if item["place"] != "car" or item["stem"] not in want:
            continue
        if item["stem"] in out and not item["leaf"].startswith(car + "_"):
            continue
        out[item["stem"]] = item
    return out


def livery_pictures(folder: str, car: str) -> list:
    """The pictures in a folder that belong to a paint scheme, not the car.

    Two rules, in order:

    * a file in the ``livery/`` subfolder is a paint picture, whatever it is
      called - that is where the game keeps them;
    * a file at the top called ``ext_*`` or ``int_*`` is one too, because those
      are the two region names the body slots use.  This is what the Blender
      exporter writes when it does not make a subfolder.

    Returns ``[{path, leaf, stem, suffix, picture, slot, tag}]`` where ``tag``
    is the colour word the name carries (``ext_red`` -> ``red``), which is what
    a new scheme is named after.
    """
    out = []
    for item in folder_pictures(folder, car):
        stem = item["stem"]
        head, _, tag = stem.partition("_")
        slot = None
        if item["place"] == "livery":
            slot = BODY_SLOT if head != "int" else INT_BODY_SLOT
        elif head in ("ext", "int") and tag:
            slot = BODY_SLOT if head == "ext" else INT_BODY_SLOT
        if slot is None:
            continue
        out.append(dict(item, slot=slot, tag=tag or stem))
    return out


# ---------------------------------------------------------------- the target
def target_rel(car: str, stem: str, suffix: str, *, place: str = "car") -> str:
    """The path the game will load ``stem`` from, relative to the car folder."""
    name = f"{car}_{stem}{suffix}"
    return f"livery/{name}" if place == "livery" else name


def family_suffix(root: str, *, prefer: str = "", key: str = "") -> str:
    """The page suffix a converted picture should be written as.

    ``prefer`` (a page already on disk for the same slot) wins when it is one of
    the three families that can be encoded, because writing the copy the engine
    already asks for means the livery table needs no edit at all.  Otherwise
    ``key`` - the answer from Settings, passed in so this module stays free of
    Qt - decides, and the install's own family is the fallback, with DXT last:
    it is the one every depot in this project ships.
    """
    if prefer and _writable_suffix(prefer):
        return prefer
    got = {"dxt": ".dxt.dds.z", "etc": ".etc.dds.z",
           "atc": ".atc.dds.z"}.get(str(key or "").lower(), "")
    if got:
        return got
    try:
        from . import depot as depotlib

        detected = depotlib.detect_texture_family(root)
    except Exception:                            # noqa: BLE001
        detected = ""
    return {"dxt": ".dxt.dds.z", "etc": ".etc.dds.z",
            "atc": ".atc.dds.z"}.get(detected, "") or ".dxt.dds.z"


def _writable_suffix(suffix: str) -> bool:
    low = str(suffix or "").lower()
    return (low.endswith(".dxt.dds.z") or low.endswith(".dxt.dds.bin")
            or low.endswith(".etc.dds.z") or low.endswith(".atc.dds.z"))


# ------------------------------------------------------------------- colours
#: The words the game itself puts in these names - 141 ``_ext_red`` files, 139
#: ``_ext_white``, 130 ``_ext_black`` and so on - so a scheme named after its
#: colour reads like the shipped ones instead of like ``_ext_ff0000``.
COLOURS = (
    ("black", (0, 0, 0)),
    ("white", (255, 255, 255)),
    ("silver", (192, 192, 192)),
    ("grey", (128, 128, 128)),
    ("dark_grey", (64, 64, 64)),
    ("red", (200, 24, 24)),
    ("dark_red", (120, 16, 16)),
    ("maroon", (88, 20, 28)),
    ("orange", (232, 120, 24)),
    ("yellow", (240, 208, 32)),
    ("gold", (200, 168, 72)),
    ("bronze", (140, 104, 56)),
    ("brown", (96, 64, 40)),
    ("beige", (216, 200, 168)),
    ("champagne", (208, 190, 160)),
    ("green", (32, 140, 64)),
    ("dark_green", (20, 80, 40)),
    ("lime", (150, 210, 60)),
    ("teal", (0, 128, 128)),
    ("blue", (40, 96, 200)),
    ("dark_blue", (16, 40, 96)),
    ("navy", (12, 24, 56)),
    ("light_blue", (120, 180, 230)),
    ("purple", (104, 48, 152)),
    ("pink", (232, 128, 176)),
    ("magenta", (200, 32, 140)),
    ("copper", (168, 96, 56)),
)


def colour_word(rgb) -> str:
    """``(200, 24, 24)`` -> ``red``.  The nearest name in :data:`COLOURS`.

    Distance is weighted the way an eye sees it - green decides lightness and
    blue decides warmth - so ``(120, 60, 60)`` reads as ``dark_red`` rather
    than as ``grey``, which an unweighted distance would pick.
    """
    try:
        want = tuple(int(v) for v in list(rgb)[:3])
    except (TypeError, ValueError):
        return "paint"
    while len(want) < 3:
        want += (0,)
    best, best_d = "paint", None
    for name, ref in COLOURS:
        dr = want[0] - ref[0]
        dg = want[1] - ref[1]
        db = want[2] - ref[2]
        d = 3 * dr * dr + 4 * dg * dg + 2 * db * db
        if best_d is None or d < best_d:
            best, best_d = name, d
    return best


def free_name(stem: str, tag: str, taken) -> str:
    """``wheel``+``red`` -> ``wheel_red``, ``wheel_red_2`` if that is taken."""
    base = f"{stem}_{tag}" if stem else tag
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


# ------------------------------------------------------- vehicles/common
#
# A page in ``vehicles/common`` is named after what it *is*, because no car's
# livery table says so - the name is the only record.  Measured over the 304
# pages the build ships, two shapes cover all of them:
#
#   car_<part>[_<free words>]      car_tyre_slick_michelin_03, car_rotor_00,
#                                  car_chassis, car_headlight_glow_white
#   <material>_<finish>_mat<NN>    leather_black_mat03, carbon_fibre_grey_mat00,
#                                  suede_grey_mat02, fabric_beige_mat07
#
# The ``_matNN`` tail is which of the eight interior material slots the page
# belongs to, so a new interior page picks the next free number of its own
# material rather than counting pages.
COMMON_LABELS = (
    ("tyre", "a tyre - car_tyre_01"),
    ("windows", "glass, banners - car_windows_01"),
    ("rotor", "a brake disc - car_rotor_10"),
    ("chassis", "the shared chassis page - car_chassis"),
    ("headlight_glow", "the glow a headlight throws - car_headlight_glow_white"),
    ("scratches", "wear and scratches - car_scratches_02"),
    ("ambient_shadow", "the shadow under the car - car_ambient_shadow"),
    ("leather", "interior leather - leather_black_mat00"),
    ("suede", "interior suede - suede_grey_mat02"),
    ("stitching", "interior stitching - stitching_red_mat01"),
    ("carbon_fibre", "interior carbon - carbon_fibre_black_mat00"),
    ("fabric", "interior fabric - fabric_grey_mat07"),
    ("plastic", "interior plastic - plastic_black_mat00"),
    ("carpet", "interior carpet - carpet_black_mat00"),
    ("aluminium", "interior aluminium - aluminium_metal_mat07"),
)

#: The labels whose pages carry a ``_matNN`` tail instead of a free number.
MATERIAL_LABELS = frozenset({
    "leather", "suede", "stitching", "carbon_fibre", "fabric", "plastic",
    "carpet", "aluminium", "speaker", "driver", "arms",
})

#: How many interior material slots the game's shaders read.
MATERIAL_SLOTS = 8


def is_material_label(label: str) -> bool:
    """True for an interior material, whose page ends ``_mat00``."""
    return clean_stem(label) in MATERIAL_LABELS


def common_name(label: str, taken=(), *, kind: str = "") -> str:
    """The next free name for a page added under ``label``.

    ``tyre`` becomes ``car_tyre_01`` (the next free number), ``leather`` becomes
    ``leather_black_mat00``'s shape - ``leather_mat00`` - because an interior
    page is named after its material and the slot it feeds, not after a count.
    ``kind`` forces one shape or the other when the label is ambiguous.
    """
    word = clean_stem(label) or "page"
    taken = {clean_stem(t) for t in taken}
    material = kind == "material" or (kind != "part" and is_material_label(word))
    if material:
        for n in range(MATERIAL_SLOTS):
            name = f"{word}_mat{n:02d}"
            if name not in taken:
                return name
        n = MATERIAL_SLOTS
        while f"{word}_mat{n:02d}" in taken:
            n += 1
        return f"{word}_mat{n:02d}"
    n = 1
    while f"car_{word}_{n:02d}" in taken:
        n += 1
    return f"car_{word}_{n:02d}"


def common_taken(depot: str) -> set:
    """The stems already in ``vehicles/common``, for :func:`common_name`."""
    folder = os.path.join(depot, *COMMON_FOLDER.split("/"))
    try:
        leaves = os.listdir(folder)
    except OSError:
        return set()
    return {stem_of(leaf) for leaf in leaves}


def common_pages(depot: str) -> list:
    """``[{stem, leaf, rel, suffix, path}]`` - every page in vehicles/common."""
    folder = os.path.join(depot, *COMMON_FOLDER.split("/"))
    out = []
    try:
        leaves = sorted(os.listdir(folder))
    except OSError:
        return out
    for leaf in leaves:
        suffix = page_suffix(leaf)
        if not suffix:
            continue
        out.append({"stem": stem_of(leaf), "leaf": leaf,
                    "rel": f"common/{leaf}", "suffix": suffix,
                    "path": os.path.join(folder, leaf)})
    return out
