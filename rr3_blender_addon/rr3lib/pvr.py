"""``.pvr`` (PowerVR) reader for the small 1-D lookup tables in ``vehicles/shaders``.

The game's car shader is driven by two 1024x1 ramps per material: a fresnel LUT
and a specular LUT (see ``docs/materials-格式.md`` §3.1).  They are plain
uncompressed PVR files - 52 byte header, then raw pixels - so they are easy to
read and easy to turn into a PNG that Blender can load.

Only the two layouts the shipped files actually use are supported:

* ``bpp = 24`` -> 3 bytes per pixel (RGB)
* ``bpp = 32`` -> 4 bytes per pixel (RGBA)

Both are stored top-down, tightly packed, and only mip 0 is read.
"""
from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass

PVR_MAGIC = b"PVR!"
HEADER_SIZE = 52


class PvrError(Exception):
    pass


@dataclass
class Pvr:
    """One decoded PVR image."""

    width: int
    height: int
    channels: int
    pixels: bytes

    @property
    def has_alpha(self) -> bool:
        return self.channels == 4

    def rgb(self, x: int = 0, y: int = 0) -> tuple:
        """One pixel as ``(r, g, b)``."""
        ch = self.channels
        off = (y * self.width + x) * ch
        return tuple(self.pixels[off:off + 3])

    def sample(self, t: float) -> tuple:
        """Sample the ramp at ``t`` in 0..1 (the LUTs are one row tall)."""
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        x = int(round(t * (self.width - 1)))
        return self.rgb(x, 0)

    def ramp(self, count: int = 16) -> list:
        """``count`` evenly spaced samples along the ramp."""
        if count < 2:
            count = 2
        return [self.sample(i / (count - 1)) for i in range(count)]


def read(path: str) -> Pvr:
    """Decode a ``.pvr`` file (a ``.pvr.z`` container is inflated first)."""
    with open(path, "rb") as fh:
        data = fh.read()
    if path.lower().endswith(".z"):
        data = inflate_z(data, path)
    return read_bytes(data, path)


def inflate_z(raw: bytes, path: str = "<bytes>") -> bytes:
    """Strip the ``u32 rawSize`` + zlib wrapper the ``.z`` containers use."""
    if len(raw) < 4:
        raise PvrError(f"{path}: too small for a size word")
    declared = struct.unpack_from("<I", raw, 0)[0]
    data = zlib.decompress(raw[4:])
    if declared and len(data) != declared:
        raise PvrError(
            f"{path}: declared {declared} bytes but zlib produced {len(data)}")
    return data


def read_bytes(data: bytes, path: str = "<bytes>") -> Pvr:
    """Decode a PVR already in memory.

    Three pixel layouts appear in the depot: 32 bpp (RGBA8888), 16 bpp
    (ARGB4444, the header carries the masks) and 8 bpp (luminance).  Anything
    with a smaller bpp is a *block* format - the 4 bpp PVRTC pages under
    ``gui_assets``, or ETC1/ATC in a build written for another GPU - and is
    handed to :func:`rr3lib.etcdecode.decode_pvr`, which knows those decoders.
    """
    if len(data) < HEADER_SIZE:
        raise PvrError(f"{path}: too small for a PVR header")
    if data[44:48] != PVR_MAGIC:
        raise PvrError(f"{path}: no PVR! magic (got {data[44:48]!r})")
    (hdr, height, width, _mips, _flags, datasize, bpp) = struct.unpack_from(
        "<7I", data, 0)
    if hdr != HEADER_SIZE:
        raise PvrError(f"{path}: header is {hdr} bytes, expected {HEADER_SIZE}")
    if bpp == 32:
        channels = 4
    elif bpp == 24:
        channels = 3
    elif bpp in (8, 16):
        channels = 4  # expanded below
    else:
        # 4 bpp and below is a block format - PVRTC for the ``.ptc.pvr`` pages,
        # ETC1 or ATC for builds written for other GPUs.  Those live in
        # :mod:`rr3lib.etcdecode` because they need the real decoders.
        from . import etcdecode
        try:
            width, height, channels, pixels = etcdecode.decode_pvr(data)
        except etcdecode.BlockError as exc:
            raise PvrError(f"{path}: {bpp} bpp is a block format ({exc})") from exc
        return Pvr(width=width, height=height, channels=channels, pixels=pixels)
    need = width * height * (bpp // 8)
    if datasize < need:
        raise PvrError(
            f"{path}: {width}x{height}x{bpp // 8} needs {need} bytes, "
            f"header says {datasize}")
    start = HEADER_SIZE
    if len(data) < start + need:
        raise PvrError(f"{path}: truncated ({len(data)} bytes)")
    raw = data[start:start + need]
    if bpp == 8:
        return Pvr(width=width, height=height, channels=4,
                   pixels=_expand_luminance(raw, width, height))
    if bpp == 16:
        masks = struct.unpack_from("<4I", data, 28)
        return Pvr(width=width, height=height, channels=4,
                   pixels=_expand_4444(raw, masks, width, height))
    return Pvr(width=width, height=height, channels=channels, pixels=raw)


def _expand_luminance(raw: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    for i, value in enumerate(raw):
        out[i * 4] = value
        out[i * 4 + 1] = value
        out[i * 4 + 2] = value
        out[i * 4 + 3] = 255
    return bytes(out)


def _expand_4444(raw: bytes, masks, width: int, height: int) -> bytes:
    """Expand a 16 bpp masked format (ARGB4444 / RGB565) to RGBA8888."""
    if not any(masks):
        masks = (0xF000, 0x0F00, 0x00F0, 0x000F)  # the depot's usual ARGB4444
    order = [masks[1], masks[2], masks[3], masks[0]]  # header is a, r, g, b
    shifts = []
    for mask in order:
        if mask == 0:
            shifts.append(None)
            continue
        shift = (mask & -mask).bit_length() - 1
        top = mask >> shift
        shifts.append((shift, top))
    out = bytearray(width * height * 4)
    count = min(len(raw) // 2, width * height)
    for i in range(count):
        value = raw[i * 2] | (raw[i * 2 + 1] << 8)
        for ch in range(4):
            info = shifts[ch]
            if info is None:
                out[i * 4 + ch] = 255
                continue
            shift, top = info
            part = (value & (top << shift)) >> shift
            out[i * 4 + ch] = (part * 255 + top // 2) // top if top else 0
    return bytes(out)


def write_png(img: Pvr, path: str) -> str:
    """Write ``img`` as an 8-bit PNG (no external dependencies)."""
    colour_type = 6 if img.has_alpha else 2
    ch = img.channels
    raw = bytearray()
    for y in range(img.height):
        raw.append(0)  # filter: none
        raw += img.pixels[y * img.width * ch:(y + 1) * img.width * ch]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", img.width, img.height,
                                      8, colour_type, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(png)
    return path


def to_png(src: str, out_dir: str) -> str:
    """Decode ``src`` and write ``<out_dir>/<name>.png``; returns the path."""
    img = read(src)
    stem = os.path.basename(src)
    if stem.lower().endswith(".pvr"):
        stem = stem[:-4]
    return write_png(img, os.path.join(out_dir, stem + ".png"))


def encode(width: int, height: int, channels: int, pixels: bytes, *,
           flip_v: bool = True) -> bytes:
    """Build a PVR the way the game's own sprite pages are built.

    The pages under ``gui_assets`` are 52-byte-header, uncompressed, 32 bpp
    (or 24 bpp for the ``.rgb.pvr`` pages that carry no alpha) and are stored
    **bottom-up** - the same order OpenGL reads them in.  MonkeyTool writes new
    pages exactly like this (``rr3AtlasAddPicture`` in ``nfsnl_rr3career.cpp``),
    which is why the header below carries ``0x00010012`` in the flags word.

    ``pixels`` is top-down RGBA (or RGB) as an ordinary image reader produces
    it; ``flip_v`` turns it over on the way out.
    """
    if channels not in (3, 4):
        raise PvrError(f"cannot write a {channels} channel image")
    need = width * height * channels
    if len(pixels) != need:
        raise PvrError(
            f"{width}x{height}x{channels} needs {need} bytes, got {len(pixels)}")
    row = width * channels
    if flip_v:
        body = b"".join(pixels[y * row:(y + 1) * row]
                        for y in range(height - 1, -1, -1))
    else:
        body = bytes(pixels)
    header = struct.pack(
        "<7I", HEADER_SIZE, height, width, 0, 0x00010012, need,
        channels * 8)
    header += struct.pack("<4I", 0, 0, 0, 0)
    header += PVR_MAGIC + struct.pack("<I", 1)
    if len(header) != HEADER_SIZE:
        raise PvrError(f"header came out {len(header)} bytes")
    return header + body


def wrap_z(plain: bytes) -> bytes:
    """``u32 rawSize`` + zlib stream, the ``.z`` container every page uses."""
    return struct.pack("<I", len(plain)) + zlib.compress(plain, 9)


def describe(path: str) -> dict:
    img = read(path)
    return {
        "path": path,
        "width": img.width,
        "height": img.height,
        "channels": img.channels,
        "ramp": img.ramp(8),
    }
