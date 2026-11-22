"""Taking a texture out of the game, editing it, and putting it back.

The manager already had one half of this: :mod:`rr3lib.texport` decodes any of
the four GPU families and writes a PNG.  What was missing is the other half -
turning a picture back into a page the game loads - and a place to do it.

Two facts shape the design:

* **a page is shared.**  ``ext_wheel`` is one file that every wheel mesh in the
  car reads, and ``common/car_rotor_05.ptc.pvr.z`` is shared by cars that have
  nothing else in common.  So a page is addressed by the path the car's livery
  names, never by a mesh, and the caller sees which meshes read it before
  writing.
* **three of the four families can be written.**  DXT, ETC1 and ATC each have a
  block encoder, and a page is written back into whichever family the file on
  disk is in, because that is the copy the engine will load.  PVRTC cannot be:
  its blocks interpolate their endpoints across block edges, so encoding one
  block correctly needs the whole picture solved at once.  That one is refused
  rather than written approximately.

Nothing here resizes.  A page has to stay the size the game allocated for it, so
a picture of the wrong size is reported and left alone.
"""

from __future__ import annotations

import os
import shutil

from rr3lib import ddsdecode as ddslib
from rr3lib import pvr as pvrlib
from rr3lib import texport as texlib

from . import edit as editlib
from . import materials as matlib

#: The container a picture is written back into.
WRITE_SUFFIX = ".dxt.dds.z"

#: Every family a livery can name.  The depot only unpacks one of them.
SUFFIXES = (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z",
            ".dxt.dds.bin", ".dds.z", ".pvr.z", ".dds", ".pvr")

#: What :func:`rrmod.series.read_picture` can open.
PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

#: Where the picture a page was last made from is kept, inside the working copy.
#:
#: A page on disk is a finished GPU file - DXT, ETC or ATC - and only one of the
#: four families is unpacked.  Publishing that file would hand the receiver a
#: page encoded for *this* device, which renders as garbage on a phone with a
#: different GPU.  Keeping the source picture means a pack can carry the art and
#: let the far side encode it for whatever it has.  It is not a game path, so it
#: lives beside the working copy rather than inside ``.depot``.
SOURCE_DIR = "_rrmod_source"


class TextureError(Exception):
    """Raised when a page cannot be read, exported or replaced."""


def _depot(root: str) -> str:
    """``<root>/.depot`` for either an install root or a depot."""
    return root if os.path.basename(root) == ".depot" else os.path.join(root, ".depot")


def page_path(root: str, rel: str, *, car: str = "") -> str:
    """The file on disk for a page named the way the livery names it.

    Two things have to be reconciled before a page can be opened:

    * **where it lives.**  A livery stores the path relative to the vehicle
      folder - ``livery/<car>_ext_x.dxt.dds.z`` for a page of the car's own,
      ``common/car_windows_04.ptc.pvr.z`` for one shared by every car - so the
      search is the car's own folder, then the shared one.
    * **which family is unpacked.**  The livery names whichever copy the game
      will load on the device it was authored for, and the depot only unpacks
      one of the four.  A livery that says ``.ptc.pvr.z`` on an install holding
      the DXT set is normal, not a broken install, so every known suffix is
      tried before giving up.
    """
    rel = str(rel or "").strip().lstrip("/").replace("\\", "/")
    if not rel:
        raise TextureError("a page needs a path")
    if ".." in rel.split("/"):
        raise TextureError(f"refusing a path that climbs out: {rel}")
    depot = _depot(root)
    bases = ([os.path.join(depot, "vehicles", car)] if car else []) + [
        os.path.join(depot, "vehicles"), depot]
    names = [rel]
    stem = rel
    for suffix in SUFFIXES:
        if rel.lower().endswith(suffix):
            stem = rel[:-len(suffix)]
            break
    if stem != rel:
        names += [stem + other for other in SUFFIXES]
    for base in bases:
        for name in names:
            candidate = os.path.join(base, *name.split("/"))
            if os.path.isfile(candidate):
                return candidate
    raise TextureError(f"{rel} is not in this install, in any of the four GPU "
                       f"families")


def on_disk(root: str, rel: str, *, car: str = "") -> str:
    """The path relative to the depot of the file :func:`page_path` found."""
    path = page_path(root, rel, car=car)
    depot = _depot(root)
    return os.path.relpath(path, depot).replace("\\", "/")


def describe(root: str, rel: str, *, car: str = "") -> dict:
    """What a page is: size, format, frame count, and the bytes on disk."""
    path = page_path(root, rel, car=car)
    info = texlib.describe(path)
    first = (info.get("images") or [{}])[0]
    found = os.path.relpath(path, _depot(root)).replace("\\", "/")
    return {
        "rel": rel,
        "found": found,
        "path": path,
        "bytes": os.path.getsize(path),
        "frames": info.get("frames", 1),
        "width": first.get("width", 0),
        "height": first.get("height", 0),
        "channels": channels_of(first),
        "format": first.get("format", "") or first.get("blockFormat", ""),
        "writable": writable(found),
        "family": family_of(found),
    }


#: Block formats that carry an alpha channel.
ALPHA_FORMATS = ("DXT3", "DXT5", "ETC2", "ETC2+EAC", "ATC+explicit",
                 "ATC+interpolated")


def channels_of(image: dict) -> int:
    """How many channels a page carries, from its header alone.

    Reading the header is enough and reading the pixels is not free: a 2048
    square page is four million pixels through a pure Python decoder.
    """
    bits = int(image.get("bitsPerPixel") or 0)
    if bits in (24, 32):
        return 4 if bits == 32 else 3
    name = str(image.get("format") or image.get("blockFormat") or "")
    return 4 if name in ALPHA_FORMATS else 3


def family_of(rel: str) -> str:
    """``"dxt"``, ``"etc"``, ``"atc"``, ``"pvrtc"`` or ``""`` for a page path."""
    low = str(rel or "").lower()
    for tag in ("dxt", "etc", "atc", "ptc"):
        if f".{tag}." in low:
            return "pvrtc" if tag == "ptc" else tag
    if low.endswith(".pvr.z") or low.endswith(".pvr"):
        return "pvrtc"
    return ""


def writable(rel: str) -> bool:
    """Whether the file at ``rel`` can be written back in place.

    Three of the four families can be encoded - DXT, ETC1 and ATC - so this asks
    about the file **on disk**, not about the name the livery uses.  Those are not
    the same thing: a shipped livery names whichever copy its device would load
    (``..._ext_passionate_pink.ptc.pvr.z``) while a depot unpacked for an Adreno
    device holds the DXT copy of the very same page.  The game picks the family
    when it loads, so writing the copy that is actually here is the right thing
    and the livery needs no edit at all.

    PVRTC stays read-only: its blocks interpolate their endpoints across block
    boundaries, so encoding one block correctly is not possible without solving
    the whole picture, and a block encoder would write something that decodes to
    a picture that looks wrong.
    """
    low = str(rel or "").lower()
    return (low.endswith(".dxt.dds.z") or low.endswith(".dxt.dds.bin")
            or low.endswith(".etc.dds.z") or low.endswith(".atc.dds.z"))


def export(root: str, rel: str, out_path: str, *, frame: int = 0,
           car: str = "") -> dict:
    """Decode one page to a PNG; returns what was written."""
    path = page_path(root, rel, car=car)
    folder = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(folder, exist_ok=True)
    width, height, channels, _pixels = texlib.decode_frame(path, frame)
    texlib.export_png(path, out_path, frame)
    return {"rel": rel, "path": out_path, "width": width, "height": height,
            "channels": channels, "bytes": os.path.getsize(out_path)}


def build(picture: str, *, expect: tuple = (), suffix: str = WRITE_SUFFIX) -> dict:
    """Turn a picture into page bytes without touching an install.

    ``expect`` is ``(width, height)`` of the page being replaced; a mismatch is
    refused because the game allocates by size.
    """
    from .series import read_picture

    width, height, channels, pixels = read_picture(picture)
    if expect and (width, height) != tuple(expect):
        raise TextureError(
            f"{os.path.basename(picture)} is {width}x{height} but the page it "
            f"would replace is {expect[0]}x{expect[1]} - resize it first, this "
            f"does not rescale")
    blob = texlib.build_texture(width, height, channels, pixels, suffix=suffix)
    return {"width": width, "height": height, "channels": channels,
            "bytes": len(blob), "blob": blob, "suffix": suffix}


def replace(root: str, rel: str, picture: str, *, car: str = "",
            log=print) -> dict:
    """Write ``picture`` over the page ``rel``, backing up what was there.

    The picture is also kept, next to the working copy, so a later publish can
    carry the art rather than this device's encoding of it.  See
    :data:`SOURCE_DIR`.
    """
    info = describe(root, rel, car=car)
    if not info["writable"]:
        raise TextureError(
            f"{info['found'] or rel} is a {info['format'] or 'non-DXT'} page, "
            f"which this can only read - export it, edit it, and put it back as "
            f"a DXT, ETC or ATC page instead")
    # Encode back into the family the file on disk is in.  A depot unpacked for a
    # Mali device holds only the ETC copy, and writing a DXT file under an .etc
    # name would produce a page the engine decodes as garbage.
    made = build(picture, expect=(info["width"], info["height"]),
                 suffix=texlib.suffix_of(info["found"]) or WRITE_SUFFIX)
    editlib._begin()
    editlib._backup(root, info["path"])
    with open(info["path"], "wb") as handle:
        handle.write(made["blob"])
    kept = keep_source(root, info["found"], picture)
    out = {"rel": rel, "found": info["found"], "path": info["path"],
           "width": made["width"], "height": made["height"],
           "bytes": made["bytes"], "before": info["bytes"],
           "after": made["bytes"], "source": kept}
    if log:
        log(f"  {info['found']}: {info['bytes']:,} -> {made['bytes']:,} bytes")
    return out


def source_dir(root: str) -> str:
    """Where the pictures behind edited pages are kept."""
    return os.path.join(root, SOURCE_DIR)


def keep_source(root: str, found: str, picture: str) -> str:
    """Copy ``picture`` in as the source of the page ``found``; returns its path.

    The page path is flattened to a file name, because the folder it lives in is
    not part of its identity: ``vehicles/common/car_windows_04.dxt.dds.z`` and
    ``Tracks/common/mat/metal/mat_metal_black.dxt.dds.z`` can both have a
    picture and the flattened name keeps them apart.
    """
    folder = source_dir(root)
    os.makedirs(folder, exist_ok=True)
    stem = str(found or "").replace("\\", "/").lstrip("/")
    for suffix in SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    ext = os.path.splitext(picture)[1].lower() or ".png"
    if ext not in PICTURE_SUFFIXES:
        ext = ".png"
    target = os.path.join(folder, stem.replace("/", "__") + ext)
    shutil.copyfile(picture, target)
    return target


def source_of(root: str, found: str) -> str:
    """The kept picture for a page, or ``""`` when there is none."""
    stem = str(found or "").replace("\\", "/").lstrip("/")
    for suffix in SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    base = os.path.join(source_dir(root), stem.replace("/", "__"))
    for ext in PICTURE_SUFFIXES:
        if os.path.isfile(base + ext):
            return base + ext
    return ""


def meshes_for(root: str, car: str, rel: str) -> list:
    """Which meshes of ``car`` read the page ``rel``.

    ``rel`` is matched the way the livery names it *and* the way the file is
    found on disk, because the two differ whenever the livery names a family
    the depot did not unpack.
    """
    want = str(rel or "").replace("\\", "/").lstrip("/")
    for row in matlib.textures(root, car):
        named = (row.get("path") or "").replace("\\", "/").lstrip("/")
        if named == want or (row.get("onDisk") or "") == want:
            return list(row.get("meshes") or [])
        try:
            if on_disk(root, named, car=car) == want:
                return list(row.get("meshes") or [])
        except TextureError:
            continue
    return []


def car_pages(root: str, car: str, *, model: str = "") -> list:
    """Every page the car names, with its slot, source and readers.

    This is :func:`rrmod.materials.textures` with the writable flag filled in,
    so the page can show "export" on everything and "import" only on the
    families it can actually write.

    ``model`` is passed straight through, so the "meshes that read it" column
    follows the file the panel is showing rather than always the body.
    """
    out = []
    for row in matlib.textures(root, car, model=model):
        row = dict(row)
        rel = row.get("path") or ""
        row["onDisk"] = ""
        row["writable"] = False
        row["family"] = ""
        if rel:
            try:
                found = on_disk(root, rel, car=car)
            except TextureError:
                found = ""
            row["onDisk"] = found
            row["writable"] = bool(found) and writable(found)
            row["family"] = family_of(found)
        out.append(row)
    return out


def shipped_pages(root: str, rel: str = "") -> list:
    """The pages in ``vehicles/common`` a slot could be pointed at instead.

    ``rel`` is the page the car names now.  The list is filtered down to the
    same *kind* of page, because that is what makes the swap safe: ``ext_tyre``
    wants a ``car_tyre_*``, ``int_mat00`` a weave or a hide, and pointing a
    window slot at a tyre would render the car's glass as tread.

    The kind is the leading part of the name with its trailing number and
    material suffix taken off, so ``car_tyre_slick_michelin_03`` groups with
    ``car_tyre_tread`` and ``car_tyre_slick_pirelli_f1_2019``.  A car that names
    no page at all gets the whole list.
    """
    depot = _depot(root)
    folder = os.path.join(depot, "vehicles", "common")
    if not os.path.isdir(folder):
        return []
    want = _kind_of(rel)
    out = []
    for leaf in sorted(os.listdir(folder)):
        stem = leaf
        for suffix in SUFFIXES:
            if leaf.lower().endswith(suffix):
                stem = leaf[:-len(suffix)]
                break
        kind = _kind_of(stem)
        if want and kind != want:
            continue
        out.append({"stem": "common/" + stem, "leaf": leaf,
                    "path": os.path.join(folder, leaf),
                    "kind": kind, "now": bool(want) and kind == want})
    return out


def _kind_of(name: str) -> str:
    """The family a page belongs to: ``car_tyre_slick_michelin_03`` -> tyre.

    Two rules, in order.  A page ending in ``_mat`` and two digits belongs to
    that interior slot (``carbon_fibre_black_mat00`` is an ``int_mat00`` page and
    nothing else), so the digits are the kind - otherwise every interior slot
    would be offered all 298 pages.  Everything else is grouped by its leading
    words, which is what separates a tyre from a disc from a banner.
    """
    stem = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    for suffix in SUFFIXES:
        if stem.lower().endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    stem = stem.lower()
    tail = stem.rsplit("_", 1)[-1]
    if len(tail) == 5 and tail.startswith("mat") and tail[3:].isdigit():
        return tail
    if "banner" in stem:
        return "banner"
    if stem.startswith("car_tyre") or "_tyre" in stem:
        return "tyre"
    if stem.startswith("car_rotor") or "_rotor" in stem:
        return "rotor"
    if "windows_cracked" in stem:
        return "windows_cracked"
    if "windows_shattered" in stem:
        return "windows_shattered"
    if stem.startswith("car_windows") or "_windows" in stem:
        return "windows"
    if stem.startswith("car_chassis") or "_chassis" in stem:
        return "chassis"
    if stem.startswith("car_scratches") or "_scratches" in stem:
        return "scratches"
    if stem.startswith("car_headlight") or "_headlight" in stem:
        return "headlight"
    if stem.startswith("car_cloak") or "_cloak" in stem:
        return "cloak"
    if stem.startswith("driver"):
        return "driver"
    if stem.startswith("arms"):
        return "arms"
    return ""


def selftest(depot: str) -> int:
    """Decode, rebuild and decode one shipped page; returns the failure count."""
    sample = os.path.join(depot, "gui_assets", "960x640", "splash", "loading",
                          "sprites_0.dxt.dds.z")
    if not os.path.isfile(sample):
        print("  no sample page to try")
        return 1
    width, height, channels, pixels = texlib.decode_frame(sample)
    # decode_frame hands back the stored order, which is already the way the
    # game wants it, so the flip that a PNG round trip needs is turned off here.
    blob = texlib.build_texture(width, height, channels, pixels,
                                suffix=WRITE_SUFFIX, flip_v=False)
    plain = pvrlib.inflate_z(blob) if WRITE_SUFFIX.endswith(".z") else blob
    again = ddslib.decode(plain)
    if again[:3] != (width, height, channels):
        print(f"  rebuilt page came out {again[0]}x{again[1]}x{again[2]}")
        return 1
    total = 0
    for i in range(0, len(pixels), 4):
        for k in range(3):
            total += abs(pixels[i + k] - again[3][i + k])
    steps = (len(pixels) // 4) * 3
    print(f"  {os.path.basename(sample)} {width}x{height} rebuilt, "
          f"mean difference {total / steps:.2f}")
    return 0
