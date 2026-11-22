"""Car thumbnails cut out of the game's own atlas pages.

The game ships a picture of every car it sells, in
``gui_assets/<size>/car_sales/cars/build_*/``: one XML atlas per batch, plus one
DDS page per ``<pos id="N">``.  The image names are the useful part - they are
``car_sales_car_<carId>.png``, so a thumbnail can be found from a car id alone
without any lookup table.

That is 510 of our 540 cars, which is better than any external gallery: it is
the right car, in the right paint, at the right angle, and there is no
licensing question.

Only the crop is done here.  Turning pixels into a ``QImage`` lives in the UI
layer, so this module stays importable without Qt.
"""

from __future__ import annotations

import os
import re
import struct

from rr3lib import ddsdecode, texport

#: Screen sizes that ship ``gui_assets``.  Biggest first: thumbnails downscale
#: well and the atlas is decoded once per session either way.
SIZES = ("2048x1536", "960x640", "480x320")

ATLAS_DIR = ("gui_assets", "{size}", "car_sales", "cars")
_IMAGE_RE = re.compile(
    r'<image\s+name="([^"]+)"\s+ver="(\d+)"\s+width="(\d+)"\s+height="(\d+)"\s*>\s*'
    r'<pos\s+id="(\d+)"\s+x="(-?\d+)"\s+y="(-?\d+)"\s*/>',
    re.S)

_cache: dict = {}


class ThumbError(Exception):
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


def index(depot: str, size: str = "") -> dict:
    """``{car id: (atlas path, page index, x, y, width, height)}``.

    Built once per depot.  Reading 111 small XML files is cheap; decoding the
    DDS pages is not, so pages are loaded lazily by :func:`sprite`.
    """
    key = (depot, size)
    if key in _cache:
        return _cache[key]
    out = {}
    root = gui_root(depot, size)
    if not root:
        _cache[key] = out
        return out
    folder = os.path.join(root, "car_sales", "cars")
    if not os.path.isdir(folder):
        _cache[key] = out
        return out
    for batch in sorted(os.listdir(folder)):
        batch_dir = os.path.join(folder, batch)
        atlas = os.path.join(batch_dir, "sprites.android.atlas")
        if not os.path.isfile(atlas):
            continue
        try:
            with open(atlas, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in _IMAGE_RE.finditer(text):
            name, _ver, w, h, page, x, y = m.groups()
            hit = re.fullmatch(r"car_sales_car_(\d+)\.png", name)
            if not hit:
                continue
            out.setdefault(int(hit.group(1)),
                           (batch_dir, int(page), int(x), int(y), int(w), int(h)))
    _cache[key] = out
    return out


def has(depot: str, car_id: int) -> bool:
    return car_id in index(depot)


def page_path(batch_dir: str, page: int) -> str:
    """The page holding ``page``, whatever GPU family this depot was unpacked for.

    Real Racing 3 ships each page four times (``.dxt`` / ``.atc`` / ``.etc`` /
    ``.ptc``) and a depot keeps only the one its build targets, so all four are
    tried before giving up.
    """
    for suffix in (".dxt.dds.z", ".rgb.pvr.z", ".ptc.pvr.z", ".etc.dds.z",
                   ".atc.dds.z", ".dds.z"):
        path = os.path.join(batch_dir, f"sprites_{page}{suffix}")
        if os.path.isfile(path):
            return path
    return ""


def _page_pixels(path: str) -> tuple:
    """``(width, height, channels, pixels)`` for a whole atlas page."""
    if path in _cache:
        return _cache[path]
    width, height, channels, pixels = texport.decode_frame(path, 0)
    # the game stores textures bottom-up; every other exporter in this project
    # flips them, and an unflipped car sprite is upside down
    pixels = texport.flip_rows(width, height, channels, pixels)
    _cache[path] = (width, height, channels, pixels)
    return _cache[path]


def sprite(depot: str, car_id: int, *, size: str = "") -> tuple:
    """Crop one car's picture; returns ``(width, height, channels, pixels)``.

    ``channels`` is 4 (RGBA) for DXT5 pages, which is what all the car sales
    pages are.  Raises :class:`ThumbError` when the car has no picture.
    """
    entry = index(depot, size).get(car_id)
    if entry is None:
        raise ThumbError(f"car {car_id} has no sales picture")
    batch_dir, page, x, y, w, h = entry
    path = page_path(batch_dir, page)
    if not path:
        raise ThumbError(f"car {car_id}: page {page} of {batch_dir} is missing")
    pw, ph, channels, pixels = _page_pixels(path)
    if x < 0 or y < 0 or x + w > pw or y + h > ph:
        raise ThumbError(
            f"car {car_id}: {w}x{h} at ({x},{y}) does not fit in {pw}x{ph}")
    stride = pw * channels
    row_bytes = w * channels
    out = bytearray(row_bytes * h)
    for row in range(h):
        src = (y + row) * stride + x * channels
        out[row * row_bytes:(row + 1) * row_bytes] = pixels[src:src + row_bytes]
    return w, h, channels, bytes(out)


def write_png(depot: str, car_id: int, out_path: str, *, size: str = "") -> str:
    """Save one thumbnail as a PNG (no Qt needed, for the CLI and for tests)."""
    w, h, channels, pixels = sprite(depot, car_id, size=size)
    write_png_bytes(out_path, w, h, channels, pixels)
    return out_path


def write_png_bytes(out_path: str, w: int, h: int, channels: int,
                    pixels: bytes) -> None:
    import zlib
    if channels == 4:
        colour = 6
    elif channels == 3:
        colour = 2
    else:
        colour = 0
    raw = bytearray()
    stride = w * channels
    for row in range(h):
        raw.append(0)
        raw += pixels[row * stride:(row + 1) * stride]
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    header = struct.pack(">2I5B", w, h, 8, colour, 0, 0, 0)
    body = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(body)


def summary(depot: str, size: str = "") -> dict:
    idx = index(depot, size)
    pages = {}
    for batch_dir, page, *_rest in idx.values():
        pages.setdefault(os.path.join(batch_dir, f"sprites_{page}"), 0)
    return {
        "root": gui_root(depot, size),
        "cars": len(idx),
        "batches": len({b for b, *_r in idx.values()}),
        "pages": len(pages),
    }


def selftest(depot: str) -> int:
    info = summary(depot)
    print(info)
    if not info["cars"]:
        print("no car sales atlas found")
        return 1
    car_id = sorted(index(depot))[0]
    w, h, channels, pixels = sprite(depot, car_id)
    print(f"car {car_id}: {w}x{h}x{channels}, {len(pixels)} bytes")
    return 0


# ---------------------------------------------------------------- writing
#
# The game shows a car in the showroom and in the career lists by cutting a
# ``car_sales_car_<id>.png`` sprite out of the ``car_sales/cars`` atlases.  A car
# this program built has no sprite, so the list falls back to a placeholder -
# which is why setting one is a build step rather than a cosmetic extra.

#: The box a new picture is drawn in when the atlas has no car picture to copy
#: the size from.  Every shipped sprite on the 2048x1536 sheet is 1800x814.
DEFAULT_BOX = (1800, 814)

#: The ``name`` a car's sprite must carry for the engine (and :func:`index`) to
#: find it.
def sprite_name(car_id: int) -> str:
    return f"car_sales_car_{int(car_id)}.png"


def _to_rgba(width: int, height: int, channels: int, pixels: bytes) -> bytes:
    """Grow a 3-channel picture to RGBA with an opaque alpha, or pass 4 through."""
    if channels == 4:
        return pixels
    if channels != 3:
        raise ThumbError(f"a {channels}-channel picture cannot become a sprite")
    out = bytearray(width * height * 4)
    for i in range(width * height):
        src = i * 3
        dst = i * 4
        out[dst] = pixels[src]
        out[dst + 1] = pixels[src + 1]
        out[dst + 2] = pixels[src + 2]
        out[dst + 3] = 255
    return bytes(out)


def _batch_dirs(folder: str) -> list:
    out = []
    for batch in sorted(os.listdir(folder)):
        path = os.path.join(folder, batch)
        if os.path.isfile(os.path.join(path, "sprites.android.atlas")):
            out.append(path)
    return out


def _commonest_box(folder: str) -> tuple:
    """The size most of this sheet's car pictures use, so a new one matches."""
    counts: dict = {}
    for batch in _batch_dirs(folder):
        atlas = os.path.join(batch, "sprites.android.atlas")
        try:
            with open(atlas, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in _IMAGE_RE.finditer(text):
            name, _ver, w, h, _page, _x, _y = m.groups()
            if name.startswith("car_sales_car_"):
                counts[(int(w), int(h))] = counts.get((int(w), int(h)), 0) + 1
    if not counts:
        return DEFAULT_BOX
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _suffix_of_page(path: str) -> str:
    """``sprites_3.dxt.dds.z`` -> ``.dxt.dds.z``."""
    base = os.path.basename(path)
    dot = base.find(".")
    return base[dot:] if dot >= 0 else ""


def _blit(page_w: int, page_h: int, page: bytes, channels: int,
          box_w: int, box_h: int, x: int, y: int,
          pic_w: int, pic_h: int, pic: bytes, pic_ch: int) -> bytes:
    """Copy ``pic`` into ``page`` at ``(x, y)``, box-averaged to ``box_w x box_h``."""
    from . import atlas as atlaslib

    if pic_ch != channels:
        raise ThumbError(f"the page is {channels}-channel and the picture "
                         f"{pic_ch}-channel; cannot mix")
    fitted = atlaslib.resize(pic_w, pic_h, pic_ch, pic, box_w, box_h)
    out = bytearray(page)
    stride = page_w * channels
    row_bytes = box_w * channels
    for row in range(box_h):
        dst = (y + row) * stride + x * channels
        out[dst:dst + row_bytes] = fitted[row * row_bytes:(row + 1) * row_bytes]
    return bytes(out)


def set_picture(root: str, car_id: int, picture: str, *, out_dir: str = "",
                backup=None, log=print) -> dict:
    """Give one car a sales picture of its own, in every screen size installed.

    A car that already has a sprite keeps its place: the picture is drawn into
    the same rectangle of the same page, so nothing else in the atlas moves and
    no list has to learn a new name.  A car with no sprite gets a page of its
    own appended to a batch, which is the shape the one shipped mod that adds a
    picture uses.

    ``backup`` is called with each path *before* it is written - the caller
    passes :func:`rrmod.edit.backup_before_write`, because an edit lands in the
    game folder now and a backup taken afterwards would record the new bytes.

    Returns ``{"car", "sizes", "files": [(local, game_path)], "box"}``.
    """
    from . import atlas as atlaslib
    from . import brands as brandlib

    depot = os.path.join(root, ".depot")
    if not os.path.isdir(depot):
        raise ThumbError(f"{root} has no .depot folder")
    pic_w, pic_h, pic_ch, pic = brandlib.read_picture(picture)
    if pic_ch not in (3, 4):
        raise ThumbError(f"{os.path.basename(picture)} is not a colour picture")
    name = sprite_name(car_id)
    # ``.depot`` and not the install root: every game path the caller hands to
    # ``sync_file`` is relative to the depot, and a sheet written one level too
    # high is a sheet the game never reads.
    out_root = out_dir or depot
    files = []
    boxes = []
    skipped = []
    for size in SIZES:
        folder = os.path.join(depot, "gui_assets", size, "car_sales", "cars")
        if not os.path.isdir(folder):
            continue
        entry = index(depot, size).get(int(car_id))
        if entry:
            batch_dir, page, x, y, box_w, box_h = entry
            path = page_path(batch_dir, page)
            suffix = _suffix_of_page(path) if path else ""
            if not path or suffix.startswith(".ptc") or suffix.startswith(".rgb"):
                skipped.append((size, suffix or "no page"))
                continue
            page_w, page_h, channels, pixels = _page_pixels(path)
            if x + box_w > page_w or y + box_h > page_h:
                skipped.append((size, "the sprite does not fit its page"))
                continue
            body = _blit(page_w, page_h, pixels, channels, box_w, box_h, x, y,
                         pic_w, pic_h,
                         _to_rgba(pic_w, pic_h, pic_ch, pic), 4)
            from rr3lib import texport

            blob = texport.build_texture(page_w, page_h, channels, body,
                                         suffix=suffix, flip_v=True)
            rel_dir = f"gui_assets/{size}/car_sales/cars/{os.path.basename(batch_dir)}"
            leaf = os.path.basename(path)
        else:
            batch_dir = (_batch_dirs(folder) or [""])[-1]
            if not batch_dir:
                skipped.append((size, "no atlas"))
                continue
            atlas_path = os.path.join(batch_dir, "sprites.android.atlas")
            box_w, box_h = _commonest_box(folder)
            fitted = atlaslib.resize(pic_w, pic_h, pic_ch, pic, box_w, box_h)
            try:
                xml, leaf, blob = atlaslib.add_picture(
                    atlas_path, name, box_w, box_h, 4,
                    _to_rgba(box_w, box_h, pic_ch, fitted))
            except atlaslib.AtlasError as exc:
                skipped.append((size, str(exc)[:80]))
                continue
            rel_dir = f"gui_assets/{size}/car_sales/cars/{os.path.basename(batch_dir)}"
            xml_local = os.path.join(out_root, *rel_dir.split("/"),
                                     "sprites.android.atlas")
            os.makedirs(os.path.dirname(xml_local), exist_ok=True)
            if backup is not None:
                backup(xml_local)
            with open(xml_local, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(xml)
            files.append((xml_local, "/" + rel_dir + "/sprites.android.atlas"))
        local = os.path.join(out_root, *rel_dir.split("/"), leaf)
        os.makedirs(os.path.dirname(local), exist_ok=True)
        if backup is not None:
            backup(local)
        with open(local, "wb") as fh:
            fh.write(blob)
        files.append((local, "/" + rel_dir + "/" + leaf))
        boxes.append(f"{size}: {box_w}x{box_h}")
        log(f"  {name} on {size}: {box_w}x{box_h} into {leaf} "
            f"({len(blob):,} bytes)")
    if not files:
        why = "; ".join(f"{size} ({why_})" for size, why_ in skipped) or "no size"
        raise ThumbError(f"no car sales sheet could take the picture: {why}")
    forget()
    return {"car": int(car_id), "name": name, "sizes": len(boxes),
            "files": files, "box": ", ".join(boxes), "skipped": skipped}


def forget() -> None:
    """Drop the cached indexes, so a picture just written is seen at once."""
    _cache.clear()
    _page_cache_clear()


def _page_cache_clear() -> None:
    try:
        from . import atlas as atlaslib

        atlaslib.forget()
    except Exception:                            # noqa: BLE001 - cosmetic only
        pass
