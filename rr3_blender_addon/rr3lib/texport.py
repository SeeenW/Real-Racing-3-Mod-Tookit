"""Export the game's private texture containers to PNG or plain DDS.

RR3 wraps every texture in one of a handful of containers.  The ``.z`` suffix
always means *zlib*, but the layer under it differs per format:

======================  ====================================================
suffix                  layout
======================  ====================================================
``.dxt.dds.z``          ``u32 rawSize`` + zlib stream -> complete DDS
``.dxt.dds.z.bin``      ``u32 0xFFFFFFFF, u32 version, u32 frames, u32 flags``
                        then per frame ``u32 compSize, u32 rawSize`` + zlib
                        stream -> a complete DDS per frame (shadow maps ship
                        22..43 near-identical frames)
``.dxt.dds.bin``        ``u32 rawSize`` + raw (uncompressed) DDS
``.rgb.pvr.z``          ``u32 rawSize`` + zlib stream -> complete PVR
``.ptc.pvr.z``          same as ``.rgb.pvr.z``
``.atc.dds.z``          ``u32 rawSize`` + zlib stream -> DDS with ATC fourcc
``.etc.dds.z``          ``u32 rawSize`` + zlib stream -> DDS with ETC fourcc
``.rgb.pvr``            plain PVR, no container
``.dxt.dds``            plain DDS, no container
======================  ====================================================

The ``.bin`` variant is the one that matters in practice: 924 files under
``vehicles/`` are ``_ext_shadows_high`` / ``_int_shadows`` shadow maps, and every
one of them is a *chunked* container rather than a single zlib stream - the
``0xFFFFFFFF`` first word is not a size, which is why :func:`rr3lib.texture.read_dds_z`
cannot open them.

Two output formats are offered: ``png`` (decoded through
:mod:`rr3lib.ddsdecode`, no Blender needed) and ``dds`` (the raw container
payload, for anyone who wants the original block data).

Every image the game ships is stored **bottom-up** - row 0 of the file is the
bottom of the picture.  MonkeyTool's ``decodeImageAuto`` flips them at decode
time and then tells the model readers not to flip V (``loadM3g(..., flipV =
false)``), which is the pair that makes the whole thing come out upright.  So
:func:`export_png` flips the rows by default; ``flip_v=False`` gives the raw
order for anyone comparing against the file itself.
"""
from __future__ import annotations

import os
import struct
import zlib

from . import ddsdecode
from . import pvr as pvrlib

#: ``u32 rawSize`` + zlib stream (the common case).
Z_SUFFIXES = (".dxt.dds.z", ".atc.dds.z", ".etc.dds.z", ".ptc.pvr.z", ".rgb.pvr.z")
#: ``u32 rawSize`` + uncompressed payload.
BIN_SUFFIXES = (".dxt.dds.bin",)
#: Chunked ``0xFFFFFFFF`` container.
CHUNKED_SUFFIXES = (".dxt.dds.z.bin",)
#: No container at all.
PLAIN_SUFFIXES = (".dxt.dds", ".rgb.pvr", ".pvr")

ALL_SUFFIXES = Z_SUFFIXES + BIN_SUFFIXES + CHUNKED_SUFFIXES + PLAIN_SUFFIXES

CHUNKED_MAGIC = 0xFFFFFFFF

#: The game stores textures bottom-up, so exports are turned over by default.
FLIP_V = True


class TextureError(Exception):
    pass


def suffix_of(path: str) -> str:
    """The longest known container suffix of ``path`` (``""`` when unknown)."""
    low = path.lower()
    for suffix in sorted(ALL_SUFFIXES, key=len, reverse=True):
        if low.endswith(suffix):
            return suffix
    return ""


def is_texture(path: str) -> bool:
    return bool(suffix_of(path))


def _inflate(raw: bytes, what: str) -> bytes:
    if len(raw) < 4:
        raise TextureError(f"{what}: too small for a size word")
    declared = struct.unpack_from("<I", raw, 0)[0]
    try:
        data = zlib.decompress(raw[4:])
    except zlib.error as exc:
        raise TextureError(f"{what}: {exc}") from exc
    if declared and len(data) != declared:
        raise TextureError(
            f"{what}: declared {declared} bytes but zlib produced {len(data)}")
    return data


def _chunked(raw: bytes, what: str) -> list:
    """Split the ``0xFFFFFFFF`` container into one payload per frame."""
    if len(raw) < 16:
        raise TextureError(f"{what}: too small for the chunked header")
    magic, _version, _frames, _flags = struct.unpack_from("<4I", raw, 0)
    if magic != CHUNKED_MAGIC:
        raise TextureError(f"{what}: not a chunked container ({magic:#x})")
    out = []
    off = 16
    while off + 8 <= len(raw):
        comp, plain = struct.unpack_from("<2I", raw, off)
        if comp < 4 or off + 8 + comp - 4 > len(raw):
            break
        try:
            data = zlib.decompress(raw[off + 8:off + 8 + comp - 4])
        except zlib.error as exc:
            raise TextureError(f"{what}: frame {len(out)}: {exc}") from exc
        if plain and len(data) != plain:
            raise TextureError(
                f"{what}: frame {len(out)} declared {plain} but produced {len(data)}")
        out.append(data)
        off += 8 + comp - 4
    if not out:
        raise TextureError(f"{what}: the chunked container holds no frame")
    return out


def payloads(path: str) -> list:
    """Every DDS/PVR payload inside ``path`` (one per frame for ``.bin``)."""
    suffix = suffix_of(path)
    what = os.path.basename(path)
    if not suffix:
        raise TextureError(f"{what}: unknown texture container")
    with open(path, "rb") as fh:
        raw = fh.read()
    if suffix in CHUNKED_SUFFIXES:
        return _chunked(raw, what)
    if suffix in BIN_SUFFIXES:
        # repeated [u32 rawSize][raw DDS] records - one per frame, no zlib
        out = []
        off = 0
        while off + 4 <= len(raw):
            size = struct.unpack_from("<I", raw, off)[0]
            if size == 0 or off + 4 + size > len(raw):
                break
            out.append(raw[off + 4:off + 4 + size])
            off += 4 + size
        if not out:
            raise TextureError(f"{what}: the uncompressed container holds no frame")
        return out
    if suffix in PLAIN_SUFFIXES:
        return [raw]
    return [_inflate(raw, what)]


def describe(path: str) -> dict:
    """Header facts about every frame in ``path``."""
    suffix = suffix_of(path)
    frames = payloads(path)
    out = {
        "path": path,
        "suffix": suffix,
        "frames": len(frames),
        "bytes": os.path.getsize(path),
        "images": [],
    }
    for data in frames:
        if data[:4] == ddsdecode.DDS_MAGIC:
            meta = ddsdecode.info(data)
            meta.pop("masks", None)
            if meta["fourcc"] in ddsdecode.BLOCK_FOURCC:
                from . import etcdecode
                meta["format"] = etcdecode.dds_format(meta["fourcc"]) or meta["format"]
            out["images"].append(meta)
        elif len(data) >= 52 and data[44:48] == pvrlib.PVR_MAGIC:
            (hdr, height, width, mips, flags, datasize, bpp) = struct.unpack_from(
                "<7I", data, 0)
            out["images"].append({
                "format": "PVR",
                "width": width,
                "height": height,
                "mipmaps": mips,
                "bitsPerPixel": bpp,
                "blockFormat": _pvr_block_name(flags),
                "bytes": len(data),
            })
        else:
            out["images"].append({"format": "?", "bytes": len(data)})
    return out


def _pvr_block_name(flags: int) -> str:
    """A readable name for a PVR ``flags`` word that holds a block codec."""
    from . import etcdecode
    kind = flags & 0xFF
    if kind not in etcdecode.PVR_KINDS:
        return ""
    return "PVRTC 2bpp" if etcdecode.PVR_KINDS[kind][1].get("two_bpp") else "PVRTC 4bpp"


def decode_frame(path: str, frame: int = 0) -> tuple:
    """Decode one frame; returns ``(width, height, channels, pixels)``."""
    frames = payloads(path)
    if frame < 0 or frame >= len(frames):
        raise TextureError(
            f"{os.path.basename(path)}: frame {frame} of {len(frames)}")
    data = frames[frame]
    if data[:4] == ddsdecode.DDS_MAGIC:
        return ddsdecode.decode(data)
    if len(data) >= 52 and data[44:48] == pvrlib.PVR_MAGIC:
        img = pvrlib.read_bytes(data)
        return img.width, img.height, img.channels, img.pixels
    raise TextureError(f"{os.path.basename(path)}: unknown payload")


def flip_rows(width: int, height: int, channels: int, pixels: bytes) -> bytes:
    """Turn a bottom-up image top-down (or back), one row at a time."""
    stride = width * channels
    out = bytearray(len(pixels))
    for y in range(height):
        src = (height - 1 - y) * stride
        out[y * stride:(y + 1) * stride] = pixels[src:src + stride]
    return bytes(out)


def export_png(path: str, out_path: str, frame: int = 0,
               flip_v: bool | None = None) -> str:
    """Decode ``path`` and write an 8-bit PNG to ``out_path``.

    The game stores every texture bottom-up (MonkeyTool flips them at decode
    time and then tells the model readers *not* to flip V), so the rows are
    turned over here by default.  Pass ``flip_v=False`` for the raw order.
    """
    width, height, channels, pixels = decode_frame(path, frame)
    if FLIP_V if flip_v is None else flip_v:
        pixels = flip_rows(width, height, channels, pixels)
    if channels == 3:
        rgba = bytearray(width * height * 4)
        for i in range(width * height):
            rgba[i * 4:i * 4 + 3] = pixels[i * 3:i * 3 + 3]
            rgba[i * 4 + 3] = 255
        img = pvrlib.Pvr(width, height, 4, bytes(rgba))
    else:
        img = pvrlib.Pvr(width, height, channels, pixels)
    return pvrlib.write_png(img, out_path)


def export_dds(path: str, out_path: str, frame: int = 0) -> str:
    """Write the raw DDS payload of one frame (no decoding)."""
    frames = payloads(path)
    data = frames[frame]
    if data[:4] != ddsdecode.DDS_MAGIC:
        raise TextureError(f"{os.path.basename(path)}: frame {frame} is not a DDS")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(data)
    return out_path


def export(path: str, out_dir: str, fmt: str = "png", frame: int = 0) -> str:
    """Export one texture; returns the written path."""
    stem = os.path.basename(path)
    suffix = suffix_of(path)
    if suffix and stem.lower().endswith(suffix):
        stem = stem[:len(stem) - len(suffix)]
    os.makedirs(out_dir, exist_ok=True)
    if fmt == "dds":
        return export_dds(path, os.path.join(out_dir, stem + ".dds"), frame)
    if fmt == "png":
        return export_png(path, os.path.join(out_dir, stem + ".png"), frame)
    raise TextureError(f"unknown output format {fmt!r}")


def export_tree(src_dir: str, out_dir: str, fmt: str = "png",
                skip_existing: bool = True) -> dict:
    """Export every texture under ``src_dir``; returns a small report."""
    done, failed, skipped = [], [], []
    for root, _dirs, files in os.walk(src_dir):
        for name in sorted(files):
            if not is_texture(name):
                continue
            src = os.path.join(root, name)
            rel = os.path.relpath(src, src_dir)
            stem = os.path.basename(rel)
            suffix = suffix_of(rel)
            if suffix and stem.lower().endswith(suffix):
                stem = stem[:len(stem) - len(suffix)]
            dst_dir = os.path.join(out_dir, os.path.dirname(rel))
            dst = os.path.join(dst_dir, stem + ("." + fmt))
            if skip_existing and os.path.isfile(dst):
                skipped.append(rel)
                continue
            try:
                export(src, dst_dir, fmt)
                done.append(rel)
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop
                failed.append((rel, str(exc)[:120]))
    return {"written": done, "failed": failed, "skipped": skipped}


# --------------------------------------------------------------------------
# putting a picture back in
# --------------------------------------------------------------------------

def container(suffix: str, plain: bytes) -> bytes:
    """Wrap a finished DDS/PVR payload the way the game's ``.z`` files do."""
    low = suffix.lower()
    if low.endswith(".z"):
        return pvrlib.wrap_z(plain)
    if low.endswith(".bin"):
        return struct.pack("<I", len(plain)) + plain
    return plain


def build_texture(width: int, height: int, channels: int, pixels: bytes, *,
                  suffix: str = ".dxt.dds.z", alpha: bool | None = None,
                  flip_v: bool | None = None) -> bytes:
    """Turn a picture into a file the game can load.

    ``suffix`` decides the container and, with it, which GPU family the result
    is for.  Three of the four can be written: ``.dxt.dds.z`` and
    ``.dxt.dds.bin`` go through :mod:`rr3lib.ddsencode`, ``.etc.dds.z`` through
    :mod:`rr3lib.blockencode`'s ETC1 encoder and ``.atc.dds.z`` through its ATC
    one.  PVRTC still cannot be: its blocks interpolate their endpoints across
    block boundaries, so a block-at-a-time encoder writes something that decodes
    and looks wrong, and refusing is better than that.
    """
    from . import blockencode, ddsencode

    low = suffix.lower()
    if not low:
        raise TextureError("a texture needs a suffix")
    if low.endswith(".ptc.pvr.z") or low.endswith(".rgb.pvr.z") \
            or low.endswith(".pvr.z"):
        raise TextureError(
            f"{suffix} is a PVRTC page.  PVRTC's blocks interpolate their colours "
            f"across block edges, so encoding it needs a whole-picture solver "
            f"rather than a block encoder; write .dxt.dds.z, .etc.dds.z or "
            f".atc.dds.z instead")
    if flip_v is None:
        flip_v = FLIP_V
    if flip_v:
        pixels = flip_rows(width, height, channels, pixels)
    if low.endswith(".etc.dds.z"):
        plain = blockencode.header_etc(width, height) + blockencode.encode_etc(
            width, height, channels, pixels, alpha=bool(alpha))
        return container(suffix, plain)
    if low.endswith(".atc.dds.z"):
        plain = blockencode.header_atc(width, height) + blockencode.encode_atc(
            width, height, channels, pixels, alpha=bool(alpha))
        return container(suffix, plain)
    if not (low.endswith(".dxt.dds.z") or low.endswith(".dxt.dds.bin")
            or low == ".dds" or low.endswith(".dds")):
        raise TextureError(
            f"{suffix} is not a container this can write (use .dxt.dds.z, "
            f".etc.dds.z or .atc.dds.z)")
    plain = ddsencode.encode(width, height, channels, pixels, alpha=alpha)
    return container(suffix, plain)


def import_picture(source: str, out_path: str, *, suffix: str = ".dxt.dds.z",
                   flip_v: bool | None = None) -> dict:
    """Write ``source`` (PNG, JPEG, anything Qt reads) as a game texture.

    The picture is encoded as-is: no resizing and no format change.  A page has
    to stay the size the game expects, so a picture of the wrong size is
    reported by the caller rather than quietly scaled here.
    """
    from rrmod.series import read_picture

    width, height, channels, pixels = read_picture(source)
    blob = build_texture(width, height, channels, pixels, suffix=suffix,
                         flip_v=flip_v)
    folder = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(folder, exist_ok=True)
    with open(out_path, "wb") as handle:
        handle.write(blob)
    return {"path": out_path, "width": width, "height": height,
            "channels": channels, "bytes": len(blob), "suffix": suffix}



def selftest(depot: str | None = None) -> int:
    """Decode one file of every container kind; returns the failure count.

    ``.ptc.pvr.z`` and ``.atc.dds.z`` hold PVRTC/ATC block data, which only
    appears under ``gui_assets`` and never on a car.  They are reported as
    skipped rather than failed, so a green run really means "every container a
    car can use decodes".
    """
    if depot is None:
        depot = os.environ.get(
            "RR3_DEPOT",
            r"E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot")
    samples = {
        ".dxt.dds.z": os.path.join(
            depot, "vehicles", "2014_mclaren_p1", "livery",
            "2014_mclaren_p1_ext_yellow.dxt.dds.z"),
        ".dxt.dds.z.bin": os.path.join(
            depot, "vehicles", "1951_ferrari_f1_f375",
            "1951_ferrari_f1_f375_ext_shadows_high.dxt.dds.z.bin"),
        ".dxt.dds.bin": os.path.join(
            depot, "vehicles", "2006_porsche_carrera_gt",
            "2006_porsche_carrera_gt_int_shadow.dxt.dds.bin"),
        ".rgb.pvr.z": os.path.join(
            depot, "effects", "exhaust_flame", "effect_exhaust_flame.rgb.pvr.z"),
        ".ptc.pvr.z": os.path.join(
            depot, "gui_assets", "2048x1536", "events", "super_groups",
            "sprites_0.ptc.pvr.z"),
        ".atc.dds.z": os.path.join(
            depot, "gui_assets", "2048x1536", "events", "super_groups",
            "sprites_0.atc.dds.z"),
    }
    # block formats no car ever uses - recognised on purpose, not decoded
    unsupported = {".ptc.pvr.z", ".atc.dds.z"}
    bad = 0
    skipped = 0
    for suffix, path in samples.items():
        name = os.path.basename(path)
        if not os.path.isfile(path):
            print(f"  {suffix:16s} missing {name}")
            continue
        try:
            meta = describe(path)
            w, h, ch, px = decode_frame(path)
            print(f"  {suffix:16s} {meta['frames']} frame(s) "
                  f"{w}x{h}x{ch} {meta['images'][0]['format']} "
                  f"({len(px)} bytes) {name}")
        except Exception as exc:  # noqa: BLE001
            if suffix in unsupported:
                skipped += 1
                print(f"  {suffix:16s} skipped (block format) {name}")
            else:
                bad += 1
                print(f"  {suffix:16s} FAILED {name}: {exc}")
    print(f"{len(samples) - bad - skipped}/{len(samples) - skipped} container kinds "
          f"decoded ({skipped} skipped)")
    return bad
