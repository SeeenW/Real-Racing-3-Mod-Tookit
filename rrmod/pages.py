"""Which page a part samples, where that file lives, and how to add one.

Three facts decide everything here, and two of them used to be written down
wrong in this program:

**The page is chosen by the tag, not by the part.**  ``LOD_A_BRAKE_CALIPER_
FRONT_LEFT_mm_misc`` ends in ``_mm_misc``, so the engine looks up the region
name ``ext_misc`` and loads whatever row *that* has.  A texture row on the
part's own slot is read by nothing - the caliper had four of them, all pointing
at its own art, and kept drawing the car's misc page.  So every function here
addresses the **region slot**, and :func:`rrmod.materials.parts` reports the
part row separately, as something that exists and is ignored.

**A page is a file in one of two places.**  ``common/`` is shared with every car
that names it; the car's own folder belongs to that car alone.  The livery row
holds the path relative to the vehicle folder, so the same picture in the two
places is ``common/x.dxt.dds.z`` and ``x.dxt.dds.z`` - two different rows.

**A family is which copy of a page a device loads.**  DXT, ETC1 and ATC can be
encoded; PVRTC cannot (its blocks interpolate across block edges), so it is
offered as read-only with the reason attached rather than hidden.
"""

from __future__ import annotations

import os
import re
import shutil

from . import edit as editlib
from . import textures as texmod

#: The families a page can be written in, in the order the picker shows them.
#:
#: ``writable`` is not a preference - it is whether an encoder exists.  PVRTC's
#: blocks interpolate their endpoints across block boundaries, so encoding one
#: block correctly needs the whole picture solved at once, and a block encoder
#: would write something that decodes and looks wrong.
FORMATS = (
    {"label": "DXT - Adreno, and most Android devices",
     "suffix": ".dxt.dds.z", "writable": True,
     "note": "The family this install unpacks, and the one every page here is "
             "already in. DXT1 for a page without alpha, DXT5 with."},
    {"label": "ETC1 - Mali and older PowerVR",
     "suffix": ".etc.dds.z", "writable": True,
     "note": "For a device that would otherwise download the ETC copy. Smaller "
             "than DXT but no alpha channel beyond ETC1's punch-through."},
    {"label": "ATC - Adreno, older drivers",
     "suffix": ".atc.dds.z", "writable": True,
     "note": "Rarely the one a device asks for; here because a livery can name "
             "it and the game will then look for it."},
    {"label": "PVRTC - iOS and PowerVR",
     "suffix": ".ptc.pvr.z", "writable": False,
     "note": "Cannot be written: PVRTC interpolates across block edges, so a "
             "block encoder produces a page that decodes and looks wrong. "
             "Pages in this family can be exported and edited, not replaced."},
)

#: The suffix a picture is encoded into when nobody says otherwise.
DEFAULT_SUFFIX = ".dxt.dds.z"

#: Every suffix a page can have on disk, longest first so a match is exact.
SUFFIXES = (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z",
            ".dxt.dds.bin", ".rgb.pvr.z", ".dds.z", ".pvr.z")

#: What a page name may contain.  The shipped names are lowercase with
#: underscores; anything else would be a name the engine's token matching never
#: sees, so a new name is folded into that shape rather than refused.
_NAME_RE = re.compile(r"[^a-z0-9_]+")


class PageError(Exception):
    """Raised when a page cannot be listed, imported or pointed at."""


def suffix_of(path: str) -> str:
    """The GPU-family suffix of a file name, or ``""``."""
    low = str(path or "").lower()
    for suffix in SUFFIXES:
        if low.endswith(suffix):
            return suffix
    return ""


def stem_of(path: str) -> str:
    """``common/car_tyre_03.dxt.dds.z`` -> ``common/car_tyre_03``."""
    rel = str(path or "").replace("\\", "/").lstrip("/")
    suffix = suffix_of(rel)
    return rel[:-len(suffix)] if suffix else rel


def family_of(path: str) -> str:
    """``dxt`` / ``etc`` / ``atc`` / ``pvrtc`` for a page path, or ``""``."""
    suffix = suffix_of(path)
    if not suffix:
        return ""
    if suffix.endswith(".pvr.z"):
        return "pvrtc"
    return suffix.split(".")[1]


def format_row(suffix: str) -> dict:
    """The :data:`FORMATS` entry for a suffix, or a blank one."""
    for row in FORMATS:
        if row["suffix"] == suffix:
            return dict(row)
    return {"label": suffix or "unknown", "suffix": suffix,
            "writable": False, "note": ""}


#: Family key -> the suffix a page in that family is stored under.  The keys are
#: what the install dialog stores (see :func:`rrmod.ui.settings.texture_family`).
FAMILY_SUFFIX = {"dxt": ".dxt.dds.z", "etc": ".etc.dds.z", "atc": ".atc.dds.z",
                 "pvrtc": ".ptc.pvr.z"}


def suffix_for_family(key: str) -> str:
    """The suffix for ``dxt``/``etc``/``atc``, or ``""`` for "auto".

    Empty means "no opinion", which the caller should read as "keep whatever
    was already chosen" - a page is always encoded in *some* family, and a
    setting that says nothing must not silently become DXT.
    """
    return FAMILY_SUFFIX.get(str(key or "").strip().lower(), "")


def clean_stem(name: str) -> str:
    """Fold a name into the shape the engine's token matching expects.

    A picture's extension is dropped first: ``My Caliper.png`` is a picture, not
    a page called ``my_caliper_png``.
    """
    stem = str(name or "").strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
    for ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tga", ".tif",
                ".tiff", ".gif"):
        if stem.endswith(ext):
            stem = stem[:-len(ext)]
            break
    stem = stem.replace("-", "_").replace(" ", "_")
    stem = _NAME_RE.sub("_", stem).strip("_")
    return re.sub(r"_{2,}", "_", stem)


def _depot(root: str) -> str:
    return root if os.path.basename(root) == ".depot" else os.path.join(root, ".depot")


def library(root: str, car: str = "", *, where: str = "") -> list:
    """Every page this install could point a slot at.

    Reads ``vehicles/common`` and - when ``car`` is given - that car's own
    folder.  ``where`` filters to ``"common"`` or ``"car"``; left empty both are
    listed, and each row says which it is.

    ``rel`` is the path a livery row would hold, which is what
    :func:`point` needs; ``path`` is where the file actually is.
    """
    depot = _depot(root)
    folders = []
    if where in ("", "common"):
        folders.append(("common", os.path.join(depot, "vehicles", "common")))
    if car and where in ("", "car"):
        folders.append(("car", os.path.join(depot, "vehicles", car)))
    out = []
    for place, folder in folders:
        if not os.path.isdir(folder):
            continue
        for leaf in sorted(os.listdir(folder)):
            path = os.path.join(folder, leaf)
            if not os.path.isfile(path) or not suffix_of(leaf):
                continue
            stem = stem_of(leaf)
            out.append({"stem": stem, "leaf": leaf, "path": path,
                        "where": place, "family": family_of(leaf),
                        "rel": editlib.page_rel_of(leaf, place),
                        "bytes": os.path.getsize(path),
                        "kind": texmod._kind_of(leaf)})
    return out


def _temp_dir(root: str) -> str:
    """A scratch folder inside the working copy, so nothing lands in temp."""
    folder = os.path.join(root, "_rrmod_incoming")
    os.makedirs(folder, exist_ok=True)
    return folder


def import_page(root: str, car: str, picture: str, *, stem: str = "",
                where: str = "common", suffix: str = DEFAULT_SUFFIX,
                log=None) -> dict:
    """Encode a picture and add it as a page, in ``common/`` or the car folder.

    The picture is **not resized**: a page has to stay the size the art was
    authored for, and quietly scaling it is how a page ends up looking right in
    a preview and wrong in the game.  A non-power-of-two size is reported but
    allowed, because a page nothing mipmaps is legal.

    ``stem`` is the page name without a suffix.  Left out it comes from the
    picture's file name, folded to the shape shipped names have.

    Returns the row a livery would hold (``rel``), the file, and the encoding
    numbers, so the caller can report what it did.
    """
    if not os.path.isfile(picture):
        raise PageError(f"{picture} does not exist")
    fmt = format_row(suffix)
    if not fmt["writable"]:
        raise PageError(f"{suffix or 'that family'} cannot be written: "
                        f"{fmt['note'] or 'no encoder'}")
    if where not in editlib.PAGE_PLACES:
        raise PageError(f"{where!r} is not a place a page can live")
    if not car:
        raise PageError("a page needs to know which car it is for")
    stem = clean_stem(stem or os.path.splitext(os.path.basename(picture))[0])
    if not stem:
        raise PageError("a page needs a name")

    made = texmod.build(picture, suffix=suffix)
    width, height = made["width"], made["height"]
    scratch = _temp_dir(root)
    staged = os.path.join(scratch, stem + suffix)
    with open(staged, "wb") as handle:
        handle.write(made["blob"])
    try:
        if where == "common":
            got = editlib.add_common_page(root, staged, stem=stem,
                                          log=log or (lambda _m: None))
            rel = got["stem"] + suffix          # ``common/<stem><suffix>``
            target = got["target"]
        else:
            got = editlib.add_car_page(root, car, staged, stem=stem,
                                       log=log or (lambda _m: None))
            rel = got["rel"]
            target = got["target"]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    kept = texmod.keep_source(root, rel, picture)
    return {"rel": rel, "stem": stem, "where": where, "suffix": suffix,
            "family": family_of(suffix), "path": target,
            "width": width, "height": height, "channels": made["channels"],
            "bytes": made["bytes"], "source": kept,
            "pot": _is_pot(width) and _is_pot(height),
            "list": got.get("list"), "manifest": got.get("manifest")}


def _is_pot(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def point(root: str, car: str, slot: int, rel: str) -> dict:
    """Point one region slot at a page, wherever that page lives.

    Thin wrapper over :func:`rrmod.edit.set_texture_page` so the UI has one
    import for "read the pages" and "use this one".
    """
    return editlib.set_texture_page(root, car, slot, rel)


def remove(root: str, car: str, rel: str, *, force: bool = False) -> dict:
    """Delete a page this program added, refusing while anything names it.

    A page in ``common/`` goes through :func:`rrmod.edit.remove_common_page`,
    which knows which cars still point at it.  A page of the car's own is only
    ever deleted from that car, so the check is that car's livery table.
    """
    depot = _depot(root)
    if str(rel or "").startswith("common/"):
        return editlib.remove_common_page(root, rel, force=force)
    from rr3lib import livery as liverylib

    leaf = str(rel or "").replace("\\", "/").lstrip("/").rsplit("/", 1)[-1]
    L = liverylib.load_car(depot, car)
    named = [s for s, p in L.textures
             if p.decode("ascii", "replace").rsplit("/", 1)[-1] == leaf]
    if named and not force:
        raise PageError(f"{leaf} is still named by slot(s) "
                        f"{', '.join(str(s) for s in named)} of {car}")
    path = os.path.join(depot, "vehicles", car, leaf)
    if not os.path.isfile(path):
        raise PageError(f"{leaf} is not in {car}'s folder")
    editlib.begin(f"Remove the page {leaf} from {car}")
    editlib._backup(root, path)
    os.remove(path)
    return {"removed": path, "slots": named}


def selftest(root: str, car: str) -> int:
    """Encode one small picture in every writable family; returns failures.

    Does not touch an install: the pages are built in memory and decoded back,
    which is the part that can be wrong.  Writing them, booking the manifest
    rows and pointing a slot are covered by ``tools/test_rrmod.py``.
    """
    import tempfile

    from rr3lib import texport as texlib

    bad = 0
    scratch = tempfile.mkdtemp(prefix="rrmod_pages_")
    try:
        picture = os.path.join(scratch, "probe.png")
        try:
            from PySide6.QtGui import QImage

            image = QImage(64, 64, QImage.Format_RGBA8888)
            image.fill(0xFF2040C0)
            image.save(picture)
        except Exception:                        # noqa: BLE001 - no Qt, skip
            print("  no Qt to write a probe picture with")
            return 0
        for row in FORMATS:
            if not row["writable"]:
                continue
            made = texmod.build(picture, suffix=row["suffix"])
            path = os.path.join(scratch, "probe" + row["suffix"])
            with open(path, "wb") as handle:
                handle.write(made["blob"])
            width, height, channels, _pixels = texlib.decode_frame(path)
            ok = (width, height) == (made["width"], made["height"])
            print(f"  {row['suffix']:12} {width}x{height}x{channels} "
                  f"{made['bytes']:6} B  {'ok' if ok else 'MISMATCH'}")
            bad += 0 if ok else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return bad

