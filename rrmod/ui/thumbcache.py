"""Car pictures as Qt pixmaps, cut from the game's own atlases.

Cutting a sprite means decoding a 2048x2048 DXT5 page (about a quarter of a
second) and then copying one 1800x814 rectangle out of it.  Doing that while a
list scrolls is hopeless, so the first time a car is asked for, the thumbnail is
rendered once into ``<state>/thumbs/<carId>.png`` at a size that suits a list;
after that it is a 20 kB file read.

The cache lives next to ``rr3mods.json``, so it follows the install and survives
a restart without touching the read-only depot.
"""

from __future__ import annotations

from ..i18n import tr

import os

from PySide6.QtGui import QImage, QPixmap

from .. import thumbs

#: Width the cached PNG is rendered at.  Big enough for a detail pane, small
#: enough that a list of 500 is 10 MB rather than 2 GB.
CACHE_WIDTH = 480

_mem: dict = {}


def cache_dir(state_dir: str) -> str:
    return os.path.join(state_dir, "thumbs")


def _fit(width: int, height: int, target: int) -> tuple:
    if width <= target:
        return width, height
    scale = target / float(width)
    return target, max(1, int(round(height * scale)))


def render(depot: str, car_id: int, out_path: str, *, width: int = CACHE_WIDTH) -> str:
    """Write one thumbnail PNG, downscaled to ``width``."""
    w, h, channels, pixels = thumbs.sprite(depot, car_id)
    tw, th = _fit(w, h, width)
    if (tw, th) != (w, h):
        pixels = _box_downscale(w, h, channels, pixels, tw, th)
        w, h = tw, th
    thumbs.write_png_bytes(out_path, w, h, channels, pixels)
    return out_path


def _box_downscale(w: int, h: int, channels: int, pixels: bytes,
                   tw: int, th: int) -> bytes:
    """Average each source block into one destination pixel (no Qt needed)."""
    out = bytearray(tw * th * channels)
    stride = w * channels
    xmap = [min(w - 1, x * w // tw) for x in range(tw)]
    for ty in range(th):
        y0 = ty * h // th
        y1 = max(y0 + 1, (ty + 1) * h // th)
        rows = [pixels[y * stride:(y + 1) * stride] for y in range(y0, y1)]
        n = len(rows)
        base = ty * tw * channels
        for tx, sx in enumerate(xmap):
            off = sx * channels
            dst = base + tx * channels
            for c in range(channels):
                total = 0
                for row in rows:
                    total += row[off + c]
                out[dst + c] = total // n
    return bytes(out)


def build(depot: str, out_dir: str, *, width: int = CACHE_WIDTH,
          only=None, progress=None, log=None) -> dict:
    """Render every missing thumbnail.  Returns a small report."""
    os.makedirs(out_dir, exist_ok=True)
    idx = thumbs.index(depot)
    ids = sorted(idx) if only is None else [i for i in sorted(idx) if i in only]
    made = skipped = failed = 0
    total = len(ids) or 1
    for i, car_id in enumerate(ids):
        if progress and i % 10 == 0:
            progress(i / total)
        path = os.path.join(out_dir, f"{car_id}.png")
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            skipped += 1
            continue
        try:
            render(depot, car_id, path, width=width)
            made += 1
        except Exception as exc:                 # noqa: BLE001 - one car, not the run
            failed += 1
            if log:
                log(f"{car_id}: {exc}")
    if progress:
        progress(1.0)
    return {"cars": len(ids), "made": made, "skipped": skipped,
            "failed": failed, "dir": out_dir}


def pixmap(depot: str, car_id: int, out_dir: str, *,
           width: int = CACHE_WIDTH) -> QPixmap:
    """The thumbnail for one car, rendering it on first use."""
    key = (out_dir, car_id, width)
    hit = _mem.get(key)
    if hit is not None:
        return hit
    path = os.path.join(out_dir, f"{car_id}.png")
    if not os.path.isfile(path):
        try:
            render(depot, car_id, path, width=width)
        except Exception:                        # noqa: BLE001
            return QPixmap()
    pm = QPixmap(path)
    _mem[key] = pm
    return pm


def qimage(depot: str, car_id: int) -> QImage:
    """The full size picture, for the detail pane."""
    w, h, channels, pixels = thumbs.sprite(depot, car_id)
    fmt = QImage.Format_RGBA8888 if channels == 4 else QImage.Format_RGB888
    img = QImage(pixels, w, h, w * channels, fmt)
    return img.copy()


def forget() -> None:
    _mem.clear()
