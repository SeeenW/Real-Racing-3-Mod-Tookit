"""Converting a picture to a texture and back, outside the game's folders.

The manager already had both halves of this, scattered:

* :mod:`rr3lib.texport` decodes the game's own containers (``.dxt.dds.z``,
  ``.etc.dds.z``, ``.rgb.pvr.z`` …) to PNG or a raw DDS, and
  :func:`rr3lib.texport.import_picture` writes a PNG back into one of them;
* :mod:`rr3lib.ddsdecode` and :mod:`rr3lib.ddsencode` read and write a plain
  ``.dds`` on their own, with no game container involved.

What was missing is the thing a person actually wants: *drop a file here, pick a
format, get the converted file*.  That is all this module is - no Qt, no page, so
it can be tested headless and called from a script.  :mod:`rrmod.ui.texui` is the
window over it.

Three families, and the difference matters:

``png`` / ``jpg``
    an ordinary picture.  Qt reads it (``rrmod.series.read_picture``); the pixels
    are already top-down, so nothing is flipped on the way in.
``dds``
    a plain DDS.  The blocks are decoded by :mod:`rr3lib.ddsdecode`, which
    handles DXT1/3/5, ETC and ATC, and written by :mod:`rr3lib.ddsencode` as
    DXT1 (no alpha) or DXT5 (alpha).
``.dxt.dds.z`` and friends
    the game's own container.  These are the same picture with a container and a
    zlib layer around it, which is why a texture can be converted to a PNG and
    back without touching the depot.

**The flip.**  Every texture the game ships is stored bottom-up; a PNG or a DDS
from any other tool is top-down.  ``flip`` defaults to on for a game texture and
off for everything else, which is right for the ordinary case, and the window
exposes it because "right for the ordinary case" is not the same as "always".
"""

from __future__ import annotations

import os

from rr3lib import ddsdecode as ddslib
from rr3lib import ddsencode as ddsenc
from rr3lib import pvr as pvrlib
from rr3lib import texport as texlib

#: What the window offers, in the order it offers it.  The key is what a caller
#: passes as ``fmt``; the value is the sentence the window shows.
FORMATS = {
    "png": "PNG picture",
    "dds": "DDS, DXT1/DXT5",
    "game-dxt": "Game texture, .dxt.dds.z",
    "game-etc": "Game texture, .etc.dds.z",
    "game-atc": "Game texture, .atc.dds.z",
}

#: ``fmt`` -> the suffix the file gets.  A game format keeps the container name
#: in the file name, because the engine picks its decoder from it.
SUFFIXES = {
    "png": ".png",
    "dds": ".dds",
    "game-dxt": ".dxt.dds.z",
    "game-etc": ".etc.dds.z",
    "game-atc": ".atc.dds.z",
}

#: Formats that are game textures, so the default flip is on for them.
GAME_FORMATS = frozenset(("game-dxt", "game-etc", "game-atc"))

#: Picture suffixes the reader can open.  Qt knows more; these are the ones the
#: file dialog offers, and the ones a user actually has.
PICTURES = (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tif", ".tiff")


class ConvertError(Exception):
    pass


# --------------------------------------------------------------------- reading
def kind_of(path: str) -> str:
    """``"game"``, ``"dds"``, ``"picture"`` or ``""`` for a file it cannot read."""
    low = path.lower()
    if texlib.suffix_of(path):
        return "game"
    if low.endswith(".dds"):
        return "dds"
    if low.endswith(PICTURES):
        return "picture"
    return ""


def can_read(path: str) -> bool:
    return bool(kind_of(path))


def read(path: str, *, flip: bool | None = None) -> tuple:
    """``(width, height, channels, top-down pixels)`` for anything readable.

    ``flip`` turns the rows over on the way in.  Left out, it is on for a game
    texture (they are stored bottom-up) and off for a PNG or a plain DDS.
    """
    kind = kind_of(path)
    if not kind:
        raise ConvertError(
            f"{os.path.basename(path)} is not a picture or a texture this can read")
    if flip is None:
        flip = kind == "game"
    if kind == "picture":
        from . import series as serieslib

        width, height, channels, pixels = serieslib.read_picture(path)
    elif kind == "dds":
        with open(path, "rb") as fh:
            width, height, channels, pixels = ddslib.decode(fh.read())
    else:
        width, height, channels, pixels = texlib.decode_frame(path, 0)
    if flip:
        pixels = texlib.flip_rows(width, height, channels, pixels)
    return width, height, channels, pixels


def describe(path: str) -> dict:
    """What a file is, without decoding the whole picture."""
    kind = kind_of(path)
    out = {"path": path, "kind": kind, "bytes": 0, "width": 0, "height": 0,
           "format": "", "suffix": texlib.suffix_of(path) if kind == "game" else ""}
    if not kind:
        return out
    out["bytes"] = os.path.getsize(path)
    try:
        if kind == "game":
            meta = texlib.describe(path)
            images = meta.get("images") or [{}]
            out["format"] = images[0].get("format", "")
            out["width"] = images[0].get("width", 0)
            out["height"] = images[0].get("height", 0)
            out["frames"] = len(images)
        elif kind == "dds":
            with open(path, "rb") as fh:
                meta = ddslib.info(fh.read())
            out["format"] = meta["format"]
            out["width"] = meta["width"]
            out["height"] = meta["height"]
            out["frames"] = 1
        else:
            from . import series as serieslib

            width, height, _ch, _px = serieslib.read_picture(path)
            out["format"] = os.path.splitext(path)[1].lstrip(".").upper()
            out["width"] = width
            out["height"] = height
            out["frames"] = 1
    except Exception as exc:                     # noqa: BLE001 - describing, not converting
        out["error"] = str(exc)[:160]
    return out


# --------------------------------------------------------------------- writing
def write(width: int, height: int, channels: int, pixels: bytes, out_path: str,
          fmt: str, *, flip: bool | None = None, alpha: bool | None = None) -> dict:
    """Encode ``pixels`` (top-down) into ``out_path`` in ``fmt``."""
    if fmt not in FORMATS:
        raise ConvertError(f"unknown format {fmt!r}")
    if flip is None:
        flip = fmt in GAME_FORMATS
    folder = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(folder, exist_ok=True)
    if fmt == "png":
        body = pixels if not flip else texlib.flip_rows(width, height, channels, pixels)
        image = pvrlib.Pvr(width, height, channels, body)
        pvrlib.write_png(image, out_path)
        written = os.path.getsize(out_path)
    elif fmt == "dds":
        body = pixels if not flip else texlib.flip_rows(width, height, channels, pixels)
        blob = ddsenc.encode(width, height, channels, body, alpha=alpha)
        with open(out_path, "wb") as fh:
            fh.write(blob)
        written = len(blob)
    else:
        # ``build_texture`` does its own flip, and refuses PVRTC pages: a
        # block-at-a-time encoder cannot write them, and silently producing a
        # page that decodes wrong is worse than saying so.
        blob = texlib.build_texture(width, height, channels, pixels,
                                    suffix=SUFFIXES[fmt], alpha=alpha,
                                    flip_v=flip)
        with open(out_path, "wb") as fh:
            fh.write(blob)
        written = len(blob)
    return {"path": out_path, "bytes": written, "width": width, "height": height,
            "format": fmt}


#: Block formats that carry an alpha channel.  Anything else is a colour-only
#: page, and re-encoding it as DXT5 would double its size and hand the engine a
#: format that slot was never authored for - so the source's own answer wins.
ALPHA_FORMATS = ("DXT3", "DXT5", "DXT2", "DXT4", "ETC2", "ETC2+EAC",
                 "ATC+explicit", "ATC+interpolated", "RGBA", "BGRA")


def source_alpha(path: str) -> bool | None:
    """Did the source carry alpha?  ``None`` when the file cannot say.

    A PNG answers with its channel count, but every decoder here hands back four
    channels whatever the file held, so the *format* is the only honest answer
    for a DDS or a game texture: a DXT1 page is opaque even after being decoded
    into an RGBA buffer.
    """
    kind = kind_of(path)
    if kind not in ("game", "dds"):
        return None
    fmt = (describe(path).get("format") or "").upper()
    if not fmt:
        return None
    return any(fmt.startswith(name) for name in ALPHA_FORMATS)


def target_for(source: str, out_dir: str, fmt: str) -> str:
    """Where a conversion of ``source`` into ``fmt`` should land."""
    stem = os.path.basename(source)
    for suffix in sorted(texlib.ALL_SUFFIXES, key=len, reverse=True):
        if stem.lower().endswith(suffix):
            stem = stem[:len(stem) - len(suffix)]
            break
    else:
        stem = os.path.splitext(stem)[0]
    return os.path.join(out_dir, stem + SUFFIXES[fmt])


def convert(source: str, out_dir: str, fmt: str, *, flip: bool | None = None,
            alpha: bool | None = None, out_path: str = "") -> dict:
    """Convert one file.  Returns what was written."""
    width, height, channels, pixels = read(source, flip=flip)
    if alpha is None:
        # A DXT1 page is opaque and its decoded buffer is still four channels, so
        # "four channels means alpha" would quietly turn it into a DXT5 page of
        # twice the size.  The source format decides when it can.
        alpha = source_alpha(source)
    target = out_path or target_for(source, out_dir, fmt)
    if os.path.abspath(target) == os.path.abspath(source):
        raise ConvertError(
            f"{os.path.basename(source)} would be written over itself - pick "
            f"another output folder")
    got = write(width, height, channels, pixels, target, fmt, flip=flip,
                alpha=alpha)
    got["source"] = source
    got["channels"] = channels
    got["alpha"] = alpha
    return got


def convert_many(paths, out_dir: str, fmt: str, *, flip: bool | None = None,
                 alpha: bool | None = None, log=print) -> dict:
    """Convert a list of files, keeping going when one of them fails."""
    done, failed = [], []
    for path in paths:
        try:
            got = convert(path, out_dir, fmt, flip=flip, alpha=alpha)
            done.append(got)
            log(f"  {os.path.basename(path)} -> {os.path.basename(got['path'])} "
                f"({got['width']}x{got['height']}, {got['bytes']:,} bytes)")
        except Exception as exc:                 # noqa: BLE001 - one bad file only
            failed.append((path, str(exc)[:200]))
            log(f"  {os.path.basename(path)}: {exc}")
    return {"done": done, "failed": failed, "out_dir": out_dir, "format": fmt}


def files_in(folder: str, *, recursive: bool = True) -> list:
    """Every readable file under ``folder``, so "a whole folder" is one press."""
    out = []
    if recursive:
        for dirpath, _dirs, names in os.walk(folder):
            for name in sorted(names):
                if can_read(name):
                    out.append(os.path.join(dirpath, name))
    else:
        for name in sorted(os.listdir(folder)):
            full = os.path.join(folder, name)
            if os.path.isfile(full) and can_read(name):
                out.append(full)
    return out
