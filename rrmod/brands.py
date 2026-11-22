"""Brands: the manufacturers the game files cars under, and the ones we add.

A "brand" in this game is nothing but a string.  The spec's third token is the
manufacturer as the player sees it (``Lexus``, ``Aston Martin``, ``Formula_E``),
and 502 of the 540 shipped specs also carry a ``CAR_MANUFACTURER_*`` key that
points into the text tables.  Nothing in the data model says a brand has to
exist anywhere first, so adding one is not a matter of inventing a record - it
is a matter of picking the string, and (optionally) giving it a picture.

The pictures are already there: ``gui_assets/<size>/common/manufacturer_logos/``
holds 60 ``logo_<stem>.png`` pictures and every one of the 53 makes in this
install has one.  This module reads them, and can add one more - the same
"a new picture becomes a page of its own" trick the career cards use, because
the sheets are packed edge to edge and there is no free space inside them.

Nothing here imports Qt; pictures come back as ``(w, h, channels, bytes)``.
"""

from __future__ import annotations

import os
import re

from . import atlas as atlaslib

#: Where the brand logos live, relative to ``gui_assets/<size>``.
FOLDER = "common/manufacturer_logos"

#: The atlas file name every one of those folders uses.
ATLAS = "sprites.android.atlas"

#: Prefix and suffix of a logo picture: ``logo_alfa_romeo.png``.
PREFIX = "logo_"
SUFFIX = ".png"

#: The text key a manufacturer name is read from, if the spec carries one.
TEXT_PREFIX = "GAMETEXT_CAR_MANUFACTURER_"


class BrandError(Exception):
    pass


def stem_of(name: str) -> str:
    """``Aston Martin`` -> ``aston_martin``; the way the art files spell it."""
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    while out and out[-1] == "_":
        out.pop()
    return "".join(out) or "custom"


def key_of(name: str) -> str:
    """``Aston Martin`` -> ``ASTON_MARTIN``; the way the spec keys spell it."""
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "CUSTOM"


def picture_of(name: str) -> str:
    """The logo file name for a brand, whether or not it exists."""
    return f"{PREFIX}{stem_of(name)}{SUFFIX}"


def atlas_path(depot: str, size: str = "") -> str:
    """The ``manufacturer_logos`` atlas for one screen size, or ``""``."""
    root = atlaslib.gui_root(depot, size)
    if not root:
        return ""
    path = os.path.join(root, *FOLDER.split("/"), ATLAS)
    return path if os.path.isfile(path) else ""


def atlases(depot: str) -> list:
    """Every ``gui_assets/<size>/common/manufacturer_logos/...atlas`` present."""
    out = []
    for size in atlaslib.SIZES:
        path = atlas_path(depot, size)
        if path:
            out.append(path)
    return out


def logos(depot: str) -> dict:
    """``{stem: picture name}`` for every logo picture in the biggest sheet."""
    root = atlaslib.gui_root(depot)
    if not root:
        return {}
    folder = os.path.join(root, *FOLDER.split("/"))
    if not os.path.isdir(folder):
        return {}
    out = {}
    for name in atlaslib.names(depot, FOLDER):
        if not (name.startswith(PREFIX) and name.endswith(SUFFIX)):
            continue
        out[name[len(PREFIX):-len(SUFFIX)]] = name
    return out


def logo(depot: str, name: str, *, size: str = "") -> tuple:
    """One brand's logo as ``(w, h, channels, pixels)``; raises when absent."""
    picture = picture_of(name)
    if not atlaslib.has(depot, FOLDER, picture, size=size):
        raise BrandError(f"{name} has no logo picture ({picture})")
    return atlaslib.sprite_at(depot, FOLDER, picture, size=size)


def has_logo(depot: str, name: str, *, size: str = "") -> bool:
    return atlaslib.has(depot, FOLDER, picture_of(name), size=size)


def brands(inv, texts=None, *, ours=()) -> list:
    """Every brand this install files a car under, most cars first.

    ``inv`` is a :class:`rrmod.depot.Inventory`.  ``texts`` is a
    :class:`rr3lib.texts.Texts` when the caller already has one - the display
    name comes from ``GAMETEXT_CAR_MANUFACTURER_<KEY>`` when that key exists, and
    from the make string itself otherwise.  38 shipped specs carry no key at all,
    so the fallback is the common case for older cars.

    ``ours`` names the brands this program added; they are listed even when no
    car uses them yet, because that is the point of adding one.
    """
    counts = {}
    for entry in inv.cars:
        make = (entry.make or "").strip()
        if make:
            counts[make] = counts.get(make, 0) + 1
    have = logos(inv.depot)
    out = []
    for name in set(counts) | {str(b) for b in ours}:
        key = key_of(name)
        text_key = TEXT_PREFIX + key
        shown = name
        if texts is not None and texts.has(text_key):
            shown = texts.get(text_key) or name
        out.append({
            "name": name,
            "shown": shown.replace("_", " ") if "_" in shown and " " not in shown
                     else shown,
            "key": key,
            "text_key": text_key,
            "has_text": bool(texts is not None and texts.has(text_key)),
            "picture": picture_of(name),
            "has_logo": stem_of(name) in have,
            "cars": counts.get(name, 0),
            "ours": name in set(ours),
        })
    out.sort(key=lambda b: (-b["cars"], b["name"].lower()))
    return out


def summary(inv, texts=None, *, ours=()) -> dict:
    found = brands(inv, texts, ours=ours)
    return {
        "brands": len(found),
        "with_logo": sum(1 for b in found if b["has_logo"]),
        "with_text": sum(1 for b in found if b["has_text"]),
        "cars": sum(b["cars"] for b in found),
        "ours": sum(1 for b in found if b["ours"]),
    }


def read_picture(path: str) -> tuple:
    """``(w, h, channels, top-down pixels)`` for a logo file the user picked.

    Delegates to :func:`rrmod.series.read_picture`, which knows both Qt and the
    plain-PNG path, so this works from a script with no ``QGuiApplication``.
    """
    from . import series as serieslib

    return serieslib.read_picture(path)


def add_logo(depot: str, name: str, picture: str, *, out_dir: str,
             backup=None, log=print) -> dict:
    """Turn a picture into ``logo_<stem>.png`` and write it next to the atlas.

    Every screen size gets the picture at that size's own logo height, so a
    2048x1536 build and a 480x320 build both look right.  Returns
    ``{"picture", "files": [(local, remote_rel)], "sizes"}``.

    ``backup`` is called with each path *before* it is written.  That ordering is
    the whole point: an edit lands in the game folder now, so a caller that
    records the previous state afterwards records the new one instead and the
    undo restores the edit.  The brand page passes
    :func:`rrmod.edit.backup_before_write` here.
    """
    if not name.strip():
        raise BrandError("a brand needs a name")
    sheets = atlases(depot)
    if not sheets:
        raise BrandError(
            f"no gui_assets/<size>/{FOLDER}/{ATLAS} was found")
    picture_name = picture_of(name)
    width, height, channels, pixels = read_picture(picture)
    if channels != 4:
        raise BrandError("the picture has no alpha channel")
    files = []
    for atlas_path in sheets:
        size = os.path.basename(os.path.dirname(os.path.dirname(
            os.path.dirname(atlas_path))))
        target_w, target_h = _logo_box(atlas_path)
        if target_w and target_h:
            use_w, use_h = _fit(width, height, target_w, target_h)
        else:
            use_w, use_h = width, height
        use = atlaslib.resize(width, height, channels, pixels, use_w, use_h)
        try:
            xml, leaf, page = atlaslib.add_picture(
                atlas_path, picture_name, use_w, use_h, channels, use)
        except atlaslib.AtlasError as exc:
            raise BrandError(str(exc)) from exc
        rel_dir = f"gui_assets/{size}/{FOLDER}"
        xml_local = os.path.join(out_dir, *rel_dir.split("/"), ATLAS)
        os.makedirs(os.path.dirname(xml_local), exist_ok=True)
        for target in (xml_local,
                       os.path.join(out_dir, *rel_dir.split("/"), leaf)):
            if backup is not None:
                backup(target)
        with open(xml_local, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(xml)
        page_local = os.path.join(out_dir, *rel_dir.split("/"), leaf)
        with open(page_local, "wb") as fh:
            fh.write(page)
        files.append((xml_local, f".depot/{rel_dir}/{ATLAS}"))
        files.append((page_local, f".depot/{rel_dir}/{leaf}"))
        log(f"  logo {picture_name}: {use_w}x{use_h} on {size} as {leaf} "
            f"({len(page):,} bytes)")
    return {"picture": picture_name, "files": files, "sizes": len(sheets),
            "width": width, "height": height}


def _logo_box(atlas_path: str) -> tuple:
    """The commonest logo size in one sheet, used as the box to fit into."""
    try:
        found = atlaslib.read_atlas(atlas_path)
    except atlaslib.AtlasError:
        return 0, 0
    sizes = {}
    for name, (_page, _x, _y, w, h) in found.items():
        if name.startswith(PREFIX) and name.endswith(SUFFIX):
            sizes[(w, h)] = sizes.get((w, h), 0) + 1
    if not sizes:
        return 0, 0
    return max(sizes.items(), key=lambda kv: kv[1])[0]


def _fit(width: int, height: int, box_w: int, box_h: int) -> tuple:
    """Scale ``width``x``height`` down to fit the box, keeping its aspect.

    Logos are wide and cards are square-ish, so a straight resize would squash
    them; the box is a bound, not a size.
    """
    if width <= 0 or height <= 0:
        return box_w, box_h
    scale = min(box_w / width, box_h / height)
    out_w = max(1, int(round(width * scale)))
    out_h = max(1, int(round(height * scale)))
    return min(out_w, box_w), min(out_h, box_h)


def selftest(depot: str) -> int:
    """Read every logo in the biggest sheet and report anything unreadable."""
    bad = 0
    have = logos(depot)
    for stem, picture in sorted(have.items()):
        try:
            w, h, channels, pixels = atlaslib.sprite_at(depot, FOLDER, picture)
        except atlaslib.AtlasError as exc:
            print(f"  {picture:<40} FAILED {exc}")
            bad += 1
            continue
        if not pixels or w <= 0 or h <= 0:
            print(f"  {picture:<40} empty")
            bad += 1
    print(f"  {len(have)} logo picture(s), {bad} unreadable")
    return bad
