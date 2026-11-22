"""Sprites out of any of the game's ``sprites.android.atlas`` folders.

Every folder under ``gui_assets/<size>/`` that has pictures is laid out the same
way: one XML file naming each picture with its page, position and size, plus one
``sprites_N.rgb.pvr.z`` (or ``.dxt.dds.z``) per page.  ``rrmod.thumbs`` already
reads that format, but only for car sales pictures - it hard-codes the folder and
the ``car_sales_car_<id>.png`` name.

This module does the same job for any folder, so the career editor can show a
track picture or an event card.  ``rrmod.thumbs`` stays as it is: it is used by
the Cars page and has its own caching story, and rewriting it to sit on top of
this would gain nothing.

Nothing here imports Qt; the pixels come back as ``(w, h, channels, bytes)``.
"""

from __future__ import annotations

import os
import re

from rr3lib import texport

#: Same order as :mod:`rrmod.thumbs`: biggest first, because a thumbnail
#: downscales well and the page is decoded once per session either way.
SIZES = ("2048x1536", "960x640", "480x320")

#: An ``<image>`` element and the ``<pos>`` that follows it.  The game writes
#: them one after the other with no other elements in between.
_IMAGE_RE = re.compile(
    r'<image\s+name="([^"]+)"\s+ver="(\d+)"\s+width="(\d+)"\s+height="(\d+)"\s*>\s*'
    r'<pos\s+id="(\d+)"\s+x="(-?\d+)"\s+y="(-?\d+)"\s*/>',
    re.S)

_INDEX: dict = {}
_PIXELS: dict = {}

#: Page families this module can *write*.  ``.ptc.pvr`` is absent on purpose:
#: PVRTC interpolates its endpoints across block edges, so a block encoder
#: produces a page that decodes and looks wrong.
PAGE_FORMATS = frozenset((".rgb.pvr", ".dxt.dds", ".etc.dds", ".atc.dds"))


class AtlasError(Exception):
    pass


def gui_root(depot: str, size: str = "") -> str:
    """The ``gui_assets/<size>`` folder, or ``""`` when it is not installed."""
    base = os.path.join(depot, "gui_assets")
    if size:
        path = os.path.join(base, size)
        return path if os.path.isdir(path) else ""
    for candidate in SIZES:
        path = os.path.join(base, candidate)
        if os.path.isdir(path):
            return path
    return ""


def read_atlas(path: str) -> dict:
    """``{name: (page, x, y, w, h)}`` for one ``.atlas`` file."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        raise AtlasError(f"{path}: {exc}") from exc
    out = {}
    for m in _IMAGE_RE.finditer(text):
        name, _ver, w, h, page, x, y = m.groups()
        out[name] = (int(page), int(x), int(y), int(w), int(h))
    return out


def index(depot: str, folder: str, *, size: str = "") -> dict:
    """``{name: (atlas folder, page, x, y, w, h)}`` for a relative folder.

    ``folder`` is relative to ``gui_assets/<size>``, e.g.
    ``events/daily_race/regular``.  Both separators are accepted.
    """
    folder = folder.replace("\\", "/").strip("/")
    key = (depot, folder, size)
    if key in _INDEX:
        return _INDEX[key]
    out = {}
    root = gui_root(depot, size)
    if not root:
        _INDEX[key] = out
        return out
    path = os.path.join(root, *folder.split("/"))
    if not os.path.isdir(path):
        _INDEX[key] = out
        return out
    # Some folders hold one atlas; the quest folders hold one per stage, so a
    # walk is what actually finds them all.
    for dirpath, _dirnames, filenames in os.walk(path):
        for leaf in filenames:
            if not leaf.endswith(".atlas"):
                continue
            try:
                found = read_atlas(os.path.join(dirpath, leaf))
            except AtlasError:
                continue
            for name, (page, x, y, w, h) in found.items():
                out.setdefault(name, (dirpath, page, x, y, w, h))
    _INDEX[key] = out
    return out


def page_path(atlas_dir: str, page: int) -> str:
    """The page holding ``page``, whatever GPU family this depot was unpacked for.

    The game writes the same page four times - ``.dxt`` (desktop/Adreno),
    ``.atc`` (older Adreno), ``.etc`` (Mali/PowerVR) and ``.ptc`` (PVRTC) - and
    a depot only unpacks the one its build targets.  All four are tried.
    """
    for suffix in (".rgb.pvr.z", ".dxt.dds.z", ".ptc.pvr.z", ".etc.dds.z",
                   ".atc.dds.z", ".dds.z"):
        path = os.path.join(atlas_dir, f"sprites_{page}{suffix}")
        if os.path.isfile(path):
            return path
    return ""


def _page_pixels(path: str) -> tuple:
    if path in _PIXELS:
        return _PIXELS[path]
    width, height, channels, pixels = texport.decode_frame(path, 0)
    # Textures are stored bottom-up; every exporter in this project flips them.
    pixels = texport.flip_rows(width, height, channels, pixels)
    _PIXELS[path] = (width, height, channels, pixels)
    return _PIXELS[path]


def sprite_at(depot: str, folder: str, name: str, *,
              size: str = "") -> tuple:
    """Crop one named picture; returns ``(w, h, channels, pixels)``."""
    entry = index(depot, folder, size=size).get(name)
    if entry is None:
        raise AtlasError(f"{folder}: no picture called {name}")
    atlas_dir, page, x, y, w, h = entry
    path = page_path(atlas_dir, page)
    if not path:
        raise AtlasError(f"{folder}: page {page} of {atlas_dir} is missing")
    pw, ph, channels, pixels = _page_pixels(path)
    if x < 0 or y < 0 or x + w > pw or y + h > ph:
        raise AtlasError(
            f"{folder}/{name}: {w}x{h} at ({x},{y}) does not fit in {pw}x{ph}")
    stride = pw * channels
    row_bytes = w * channels
    out = bytearray(row_bytes * h)
    for row in range(h):
        src = (y + row) * stride + x * channels
        out[row * row_bytes:(row + 1) * row_bytes] = pixels[src:src + row_bytes]
    return w, h, channels, bytes(out)


def has(depot: str, folder: str, name: str, *, size: str = "") -> bool:
    return name in index(depot, folder, size=size)


def names(depot: str, folder: str, *, size: str = "", like: str = "") -> list:
    """Every picture in a folder, optionally only those containing ``like``."""
    found = sorted(index(depot, folder, size=size))
    if like:
        low = like.lower()
        found = [n for n in found if low in n.lower()]
    return found


def summary(depot: str, folder: str, *, size: str = "") -> dict:
    found = index(depot, folder, size=size)
    return {
        "root": gui_root(depot, size),
        "folder": folder,
        "images": len(found),
        "atlases": len({a for a, *_r in found.values()}),
        "pages": len({(a, p) for a, p, *_r in found.values()}),
    }


def forget() -> None:
    _INDEX.clear()
    _PIXELS.clear()


# ---------------------------------------------------------------- writing
#
# The game's sprite pages are plain 32 bpp PVRs, and an atlas is just an XML
# list of pictures pointing into them.  Adding a picture therefore means adding
# a whole new page: the existing pages are packed edge to edge with no room
# left, so there is nowhere to put a new rectangle.  MonkeyTool does exactly
# this (``rr3AtlasAddPicture`` in ``nfsnl_rr3career.cpp``) - one picture per new
# page, at (0, 0), with the next free page id.

#: The page suffix every ``.atlas`` names in its ``texture_formats`` attribute.
_FORMAT_RE = re.compile(r'texture_formats="([^"]+)"')
_POS_ID_RE = re.compile(r'<pos\s+id="(\d+)"')


def texture_format(atlas_path: str) -> str:
    """``.rgb.pvr`` for the atlases this module can add a page to."""
    with open(atlas_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    m = _FORMAT_RE.search(text)
    if not m:
        raise AtlasError(f"{atlas_path}: no texture_formats attribute")
    return m.group(1).split(",")[0].strip()


def card_size(atlas_path: str) -> tuple:
    """The size the atlas uses for its ``*_card.png`` pictures.

    The career atlas packs 680x942 cards on a 2048x1536 sheet; the 960x640 one
    uses a different size.  Reading it from the atlas keeps a new card the same
    size as the ones already there, which is what the layout expects.
    """
    found = read_atlas(atlas_path)
    for name, (_page, _x, _y, w, h) in found.items():
        if name.endswith("_card.png"):
            return w, h
    return 0, 0


def resize(width: int, height: int, channels: int, pixels: bytes,
           new_width: int, new_height: int) -> bytes:
    """Box-average downscale, nearest-neighbour upscale, no dependencies.

    Cards are 680x942 and a user's picture is rarely that shape, so both
    directions matter.  Averaging on the way down avoids the speckle a nearest
    sample would leave in a photograph.
    """
    if (width, height) == (new_width, new_height):
        return bytes(pixels)
    if new_width <= 0 or new_height <= 0:
        raise AtlasError(f"cannot resize to {new_width}x{new_height}")
    out = bytearray(new_width * new_height * channels)
    if new_width <= width and new_height <= height:
        for y in range(new_height):
            y0 = (y * height) // new_height
            y1 = max(y0 + 1, ((y + 1) * height) // new_height)
            for x in range(new_width):
                x0 = (x * width) // new_width
                x1 = max(x0 + 1, ((x + 1) * width) // new_width)
                total = [0] * channels
                count = 0
                for sy in range(y0, y1):
                    base = sy * width
                    for sx in range(x0, x1):
                        off = (base + sx) * channels
                        for ch in range(channels):
                            total[ch] += pixels[off + ch]
                        count += 1
                dst = (y * new_width + x) * channels
                for ch in range(channels):
                    out[dst + ch] = (total[ch] + count // 2) // count
        return bytes(out)
    for y in range(new_height):
        sy = min(height - 1, (y * height) // new_height)
        for x in range(new_width):
            sx = min(width - 1, (x * width) // new_width)
            off = (sy * width + sx) * channels
            dst = (y * new_width + x) * channels
            out[dst:dst + channels] = pixels[off:off + channels]
    return bytes(out)


def add_picture(atlas_path: str, name: str, width: int, height: int,
                channels: int, pixels: bytes) -> tuple:
    """Add ``name`` as a page of its own; returns ``(xml, leaf, page_bytes)``.

    ``xml`` is the whole new ``.atlas`` text, ``leaf`` the file name the page
    must be written as (next to the atlas) and ``page_bytes`` its contents,
    already wrapped the way every ``.z`` page is.

    The entry is written the way the one shipped mod that adds a picture does
    it: a new page index, no ``<hash>`` element of its own, and the root
    ``hash="..."`` attribute dropped - that attribute is a checksum of the
    sheet the shipped file describes, so keeping it while changing the contents
    is a lie the loader may or may not believe.  (A made-up per-picture hash is
    worse: the reference mod has none, so none is the only shape known to load.)

    The page is encoded in the atlas's own family, so this works on a depot
    unpacked for DXT, ETC or ATC.  A ``.ptc.pvr`` depot is refused: PVRTC cannot
    be encoded block by block (see :func:`rr3lib.texport.build_texture`).
    """
    from rr3lib import pvr as pvrlib

    fmt = texture_format(atlas_path)
    if fmt not in PAGE_FORMATS:
        raise AtlasError(
            f"{os.path.basename(atlas_path)}: pages are {fmt}, which cannot be "
            f"written ({', '.join(sorted(PAGE_FORMATS))} can)")
    with open(atlas_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if f'name="{name}"' in text:
        raise AtlasError(f"{name} is already in {os.path.basename(atlas_path)}")
    ids = [int(m) for m in _POS_ID_RE.findall(text)]
    page = (max(ids) + 1) if ids else 0
    closing = text.rfind("</atlas_images>")
    if closing < 0:
        raise AtlasError(f"{os.path.basename(atlas_path)}: no closing tag")
    entry = (
        f'  <image name="{name}" ver="0" width="{width}" height="{height}">\n'
        f'    <pos id="{page}" x="0" y="0"/>\n'
        f'  </image>\n')
    new_xml = _drop_root_hash(text[:closing] + entry + text[closing:])
    if fmt == ".rgb.pvr":
        page_bytes = pvrlib.wrap_z(
            pvrlib.encode(width, height, channels, pixels, flip_v=True))
    else:
        from rr3lib import texport

        page_bytes = texport.build_texture(
            width, height, channels, pixels, suffix=fmt + ".z", flip_v=True)
    return new_xml, f"sprites_{page}{fmt}.z", page_bytes


def _drop_root_hash(text: str) -> str:
    """Remove ``hash="..."`` from the ``<atlas_images>`` opening tag."""
    head_end = text.find(">")
    if head_end < 0:
        return text
    head = re.sub(r'\s+hash="[^"]*"', "", text[:head_end])
    return head + text[head_end:]
