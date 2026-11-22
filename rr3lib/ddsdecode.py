"""Pure-Python (with optional numpy) DDS decoder for the block formats RR3 ships.

Every car texture in the depot is either **DXT1** (6,248 files) or **DXT5**
(1,598 files); nothing else appears under ``vehicles/``.  The decoder exists so
the exporter - and the Blender importer - do not have to rely on anyone else's
DDS support: the pixels are unpacked here and written as PNG.

Only mip 0 is decoded.  Supported layouts:

* ``DXT1`` - 8 byte blocks, 1-bit alpha (three-colour mode makes pixel 3 clear)
* ``DXT3`` - 8 byte explicit 4-bit alpha block + 8 byte colour block
* ``DXT5`` - 8 byte interpolated alpha block + 8 byte colour block

The output is always RGBA (4 channels), top-down, tightly packed.

numpy is used when it is importable (Blender and the bundled Python both ship
it); the pure-Python path is the fallback and produces identical bytes.
"""
from __future__ import annotations

import struct

DDS_MAGIC = b"DDS "

#: DDS pixel-format four-character codes this decoder understands.
FOURCC = {
    b"DXT1": "DXT1",
    b"DXT3": "DXT3",
    b"DXT5": "DXT5",
    # The other GPU families the depot ships the same art for; the blocks
    # themselves are decoded in :mod:`rr3lib.etcdecode`.
    b"ETC ": "ETC1",
    b"ETC1": "ETC1",
    b"ETC2": "ETC2",
    b"ETCA": "ETC2+EAC",
    b"ATC ": "ATC ",
    b"ATCA": "ATCA",
    b"ATCI": "ATCI",
}

#: Fourccs whose payload is a block format :mod:`rr3lib.etcdecode` handles.
BLOCK_FOURCC = frozenset((b"ETC ", b"ETC1", b"ETC2", b"ETCA",
                          b"ATC ", b"ATCA", b"ATCI"))

try:  # numpy makes a 1024x1024 DXT1 decode ~100x faster
    import numpy as _np
except Exception:  # noqa: BLE001 - the fallback is exact, just slower
    _np = None


class DdsError(Exception):
    pass


def _expand565(value: int) -> tuple:
    """RGB565 -> (r, g, b) at 8 bits per channel."""
    r5 = (value >> 11) & 0x1F
    g6 = (value >> 5) & 0x3F
    b5 = value & 0x1F
    return ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2))


def _clamp8(value: int) -> int:
    return 0 if value < 0 else (255 if value > 255 else value)


def _colour_palette(c0: int, c1: int, four_colour: bool) -> list:
    """The four colours of one DXT colour block, as ``(r, g, b, a)`` tuples."""
    r0, g0, b0 = _expand565(c0)
    r1, g1, b1 = _expand565(c1)
    if four_colour:
        return [
            (r0, g0, b0, 255),
            (r1, g1, b1, 255),
            (_clamp8((2 * r0 + r1) // 3), _clamp8((2 * g0 + g1) // 3),
             _clamp8((2 * b0 + b1) // 3), 255),
            (_clamp8((r0 + 2 * r1) // 3), _clamp8((g0 + 2 * g1) // 3),
             _clamp8((b0 + 2 * b1) // 3), 255),
        ]
    return [
        (r0, g0, b0, 255),
        (r1, g1, b1, 255),
        (_clamp8((r0 + r1) // 2), _clamp8((g0 + g1) // 2),
         _clamp8((b0 + b1) // 2), 255),
        (0, 0, 0, 0),
    ]


def _alpha_palette(a0: int, a1: int) -> list:
    """The eight alpha values of one DXT5 alpha block."""
    if a0 > a1:
        return [a0, a1] + [
            _clamp8(((7 - i) * a0 + i * a1) // 7) for i in range(1, 7)
        ]
    return [a0, a1] + [
        _clamp8(((5 - i) * a0 + i * a1) // 5) for i in range(1, 5)
    ] + [0, 255]


# ---------------------------------------------------------------------------
# numpy path
# ---------------------------------------------------------------------------
def _blocks_numpy(data: bytes, offset: int, width: int, height: int,
                  block_size: int):
    bx = (width + 3) // 4
    by = (height + 3) // 4
    need = bx * by * block_size
    if len(data) < offset + need:
        raise DdsError(
            f"truncated: {width}x{height} needs {need} bytes at {offset}, "
            f"file holds {len(data) - offset}")
    raw = _np.frombuffer(data, dtype=_np.uint8, count=need, offset=offset)
    return raw.reshape(by, bx, block_size), bx, by


def _palette_numpy(c0, c1, four_colour):
    """``(nblocks, 4, 4)`` uint8 palette table."""
    def exp(v):
        r = ((v >> 11) & 0x1F).astype(_np.uint16)
        g = ((v >> 5) & 0x3F).astype(_np.uint16)
        b = (v & 0x1F).astype(_np.uint16)
        return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))

    r0, g0, b0 = exp(c0)
    r1, g1, b1 = exp(c1)
    n = c0.shape[0]
    pal = _np.empty((n, 4, 4), dtype=_np.uint8)
    pal[:, 0, 0] = r0
    pal[:, 0, 1] = g0
    pal[:, 0, 2] = b0
    pal[:, 0, 3] = 255
    pal[:, 1, 0] = r1
    pal[:, 1, 1] = g1
    pal[:, 1, 2] = b1
    pal[:, 1, 3] = 255

    mid = four_colour
    # four-colour mode: 2/3 c0 + 1/3 c1 and 1/3 c0 + 2/3 c1
    c2r = ((2 * r0.astype(_np.uint16) + r1) // 3)
    c2g = ((2 * g0.astype(_np.uint16) + g1) // 3)
    c2b = ((2 * b0.astype(_np.uint16) + b1) // 3)
    c3r = ((r0.astype(_np.uint16) + 2 * r1) // 3)
    c3g = ((g0.astype(_np.uint16) + 2 * g1) // 3)
    c3b = ((b0.astype(_np.uint16) + 2 * b1) // 3)
    # three-colour mode: average, then transparent black
    h2r = ((r0.astype(_np.uint16) + r1) // 2)
    h2g = ((g0.astype(_np.uint16) + g1) // 2)
    h2b = ((b0.astype(_np.uint16) + b1) // 2)

    pal[:, 2, 0] = _np.where(mid, c2r, h2r)
    pal[:, 2, 1] = _np.where(mid, c2g, h2g)
    pal[:, 2, 2] = _np.where(mid, c2b, h2b)
    pal[:, 2, 3] = 255
    pal[:, 3, 0] = _np.where(mid, c3r, 0)
    pal[:, 3, 1] = _np.where(mid, c3g, 0)
    pal[:, 3, 2] = _np.where(mid, c3b, 0)
    pal[:, 3, 3] = _np.where(mid, 255, 0).astype(_np.uint8)
    return pal


def _indices_numpy(bits, count, bits_per):
    """Expand packed 2-bit (or 3-bit) indices to ``(nblocks, 16)``."""
    shifts = _np.arange(16, dtype=_np.uint64) * bits_per
    mask = (1 << bits_per) - 1
    out = (bits.astype(_np.uint64)[:, None] >> shifts) & mask
    return out.astype(_np.uint8)


def _assemble(patch, bx, by, width, height):
    """``(by, bx, 16, 4)`` patches -> ``(height, width, 4)`` uint8 image."""
    img = patch.reshape(by, bx, 4, 4, 4)
    img = img.transpose(0, 2, 1, 3, 4).reshape(by * 4, bx * 4, 4)
    return _np.ascontiguousarray(img[:height, :width])


def _decode_numpy(data: bytes, offset: int, width: int, height: int,
                  fmt: str) -> bytes:
    if fmt == "DXT1":
        blocks, bx, by = _blocks_numpy(data, offset, width, height, 8)
        flat = blocks.reshape(-1, 8)
        c0 = flat[:, 0].astype(_np.uint16) | (flat[:, 1].astype(_np.uint16) << 8)
        c1 = flat[:, 2].astype(_np.uint16) | (flat[:, 3].astype(_np.uint16) << 8)
        bits = flat[:, 4:8].copy().view(_np.uint32).reshape(-1)
        pal = _palette_numpy(c0, c1, c0 > c1)
        idx = _indices_numpy(bits, 16, 2)
        patch = _np.take_along_axis(pal, idx[:, :, None], axis=1)
        return _assemble(patch, bx, by, width, height).tobytes()
    if fmt == "DXT5":
        blocks, bx, by = _blocks_numpy(data, offset, width, height, 16)
        flat = blocks.reshape(-1, 16)
        a0 = flat[:, 0].astype(_np.int16)
        a1 = flat[:, 1].astype(_np.int16)
        abits = _np.zeros(flat.shape[0], dtype=_np.uint64)
        for i in range(6):
            abits |= flat[:, 2 + i].astype(_np.uint64) << _np.uint64(8 * i)
        shifts = _np.arange(16, dtype=_np.uint64) * _np.uint64(3)
        aidx = ((abits[:, None] >> shifts) & _np.uint64(7)).astype(_np.uint8)
        apal = _alpha_palette_numpy(a0, a1)
        alpha = _np.take_along_axis(apal, aidx, axis=1).astype(_np.uint8)
        c0 = flat[:, 8].astype(_np.uint16) | (flat[:, 9].astype(_np.uint16) << 8)
        c1 = flat[:, 10].astype(_np.uint16) | (flat[:, 11].astype(_np.uint16) << 8)
        bits = flat[:, 12:16].copy().view(_np.uint32).reshape(-1)
        pal = _palette_numpy(c0, c1, _np.ones_like(c0, dtype=bool))
        idx = _indices_numpy(bits, 16, 2)
        rgb = _np.take_along_axis(pal, idx[:, :, None], axis=1)
        rgb[:, :, 3] = alpha
        return _assemble(rgb, bx, by, width, height).tobytes()
    if fmt == "DXT3":
        blocks, bx, by = _blocks_numpy(data, offset, width, height, 16)
        flat = blocks.reshape(-1, 16)
        abits = _np.zeros(flat.shape[0], dtype=_np.uint64)
        for i in range(8):
            abits |= flat[:, i].astype(_np.uint64) << _np.uint64(8 * i)
        shifts = _np.arange(16, dtype=_np.uint64) * _np.uint64(4)
        nib = ((abits[:, None] >> shifts) & _np.uint64(0xF)).astype(_np.uint16)
        alpha = (nib * 17).astype(_np.uint8)
        c0 = flat[:, 8].astype(_np.uint16) | (flat[:, 9].astype(_np.uint16) << 8)
        c1 = flat[:, 10].astype(_np.uint16) | (flat[:, 11].astype(_np.uint16) << 8)
        bits = flat[:, 12:16].copy().view(_np.uint32).reshape(-1)
        pal = _palette_numpy(c0, c1, _np.ones_like(c0, dtype=bool))
        idx = _indices_numpy(bits, 16, 2)
        rgb = _np.take_along_axis(pal, idx[:, :, None], axis=1)
        rgb[:, :, 3] = alpha
        return _assemble(rgb, bx, by, width, height).tobytes()
    raise DdsError(f"{fmt} is not a block format this decoder handles")


def _alpha_palette_numpy(a0, a1):
    """``(nblocks, 8)`` uint8 alpha palette."""
    n = a0.shape[0]
    pal = _np.empty((n, 8), dtype=_np.uint16)
    pal[:, 0] = a0
    pal[:, 1] = a1
    eight = a0 > a1
    a0f = a0.astype(_np.uint16)
    a1f = a1.astype(_np.uint16)
    for i in range(1, 7):
        v8 = ((7 - i) * a0f + i * a1f) // 7
        pal[:, 1 + i] = _np.where(eight, v8, pal[:, 1 + i])
    for i in range(1, 5):
        v6 = ((5 - i) * a0f + i * a1f) // 5
        pal[:, 1 + i] = _np.where(eight, pal[:, 1 + i], v6)
    pal[:, 6] = _np.where(eight, pal[:, 6], 0)
    pal[:, 7] = _np.where(eight, pal[:, 7], 255)
    return pal.astype(_np.uint8)


# ---------------------------------------------------------------------------
# pure-Python fallback
# ---------------------------------------------------------------------------
def _decode_dxt1(data: bytes, offset: int, width: int, height: int) -> bytearray:
    out = bytearray(width * height * 4)
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    pos = offset
    for by in range(blocks_y):
        for bx in range(blocks_x):
            if pos + 8 > len(data):
                raise DdsError("truncated DXT1 blocks")
            c0, c1, bits = struct.unpack_from("<HHI", data, pos)
            pos += 8
            pal = _colour_palette(c0, c1, c0 > c1)
            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    continue
                row = (y * width + bx * 4) * 4
                code = (bits >> (py * 8)) & 0xFF
                for px in range(4):
                    x = bx * 4 + px
                    if x >= width:
                        continue
                    r, g, b, a = pal[(code >> (px * 2)) & 0x03]
                    i = row + px * 4
                    out[i] = r
                    out[i + 1] = g
                    out[i + 2] = b
                    out[i + 3] = a
    return out


def _decode_dxt5(data: bytes, offset: int, width: int, height: int) -> bytearray:
    out = bytearray(width * height * 4)
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    pos = offset
    for by in range(blocks_y):
        for bx in range(blocks_x):
            if pos + 16 > len(data):
                raise DdsError("truncated DXT5 blocks")
            a0, a1 = data[pos], data[pos + 1]
            alpha_bits = int.from_bytes(data[pos + 2:pos + 8], "little")
            c0, c1, bits = struct.unpack_from("<HHI", data, pos + 8)
            pos += 16
            pal = _colour_palette(c0, c1, True)
            apal = _alpha_palette(a0, a1)
            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    continue
                row = (y * width + bx * 4) * 4
                code = (bits >> (py * 8)) & 0xFF
                acode = (alpha_bits >> (py * 12)) & 0xFFF
                for px in range(4):
                    x = bx * 4 + px
                    if x >= width:
                        continue
                    r, g, b, _a = pal[(code >> (px * 2)) & 0x03]
                    a = apal[(acode >> (px * 3)) & 0x07]
                    i = row + px * 4
                    out[i] = r
                    out[i + 1] = g
                    out[i + 2] = b
                    out[i + 3] = a
    return out


def _decode_dxt3(data: bytes, offset: int, width: int, height: int) -> bytearray:
    out = bytearray(width * height * 4)
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    pos = offset
    for by in range(blocks_y):
        for bx in range(blocks_x):
            if pos + 16 > len(data):
                raise DdsError("truncated DXT3 blocks")
            alpha_bits = int.from_bytes(data[pos:pos + 8], "little")
            c0, c1, bits = struct.unpack_from("<HHI", data, pos + 8)
            pos += 16
            pal = _colour_palette(c0, c1, True)
            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    continue
                row = (y * width + bx * 4) * 4
                code = (bits >> (py * 8)) & 0xFF
                for px in range(4):
                    x = bx * 4 + px
                    if x >= width:
                        continue
                    r, g, b, _a = pal[(code >> (px * 2)) & 0x03]
                    nib = (alpha_bits >> ((py * 4 + px) * 4)) & 0xF
                    i = row + px * 4
                    out[i] = r
                    out[i + 1] = g
                    out[i + 2] = b
                    out[i + 3] = nib * 17
    return out


def _decode_raw(data: bytes, offset: int, width: int, height: int,
                bits: int, masks) -> bytearray:
    """Uncompressed RGBA/BGRA.  ``masks`` are the DDS r/g/b/a bit masks."""
    out = bytearray(width * height * 4)
    step = max(1, bits // 8)
    shifts = []
    for mask in masks:
        if mask == 0:
            shifts.append(None)
            continue
        shift = (mask & -mask).bit_length() - 1
        top = mask >> shift
        shifts.append((shift, top))
    pos = offset
    for y in range(height):
        for x in range(width):
            if pos + step > len(data):
                return out
            value = int.from_bytes(data[pos:pos + step], "little")
            pos += step
            i = (y * width + x) * 4
            for ch in range(4):
                info = shifts[ch]
                if info is None:
                    out[i + ch] = 255
                    continue
                shift, top = info
                raw = (value & (top << shift)) >> shift
                out[i + ch] = _clamp8(raw * 255 // top if top else 0)
    return out


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def info(data: bytes) -> dict:
    """Parse the DDS header without decoding the pixels."""
    if len(data) < 128 or data[:4] != DDS_MAGIC:
        raise DdsError("not a DDS file")
    (size, flags, height, width, pitch, depth, mips) = struct.unpack_from("<7I", data, 4)
    (pf_size, pf_flags, fourcc, bits, rm, gm, bm, am) = struct.unpack_from("<8I", data, 76)
    tag = fourcc.to_bytes(4, "little")
    fmt = FOURCC.get(tag) or (tag.rstrip(b"\0").decode("ascii", "replace") or "RGBA")
    offset = 128
    if fmt == "DX10" and len(data) >= 148:
        offset = 148
    return {
        "width": width,
        "height": height,
        "mipmaps": mips or 1,
        "fourcc": tag,
        "format": fmt,
        "bitsPerPixel": bits,
        "masks": (rm, gm, bm, am),
        "dataOffset": offset,
        "bytes": len(data),
    }


def decode(data: bytes) -> tuple:
    """Decode mip 0 of ``data``; returns ``(width, height, channels, pixels)``."""
    meta = info(data)
    width, height = meta["width"], meta["height"]
    if width <= 0 or height <= 0:
        raise DdsError(f"bad dimensions {width}x{height}")
    fmt = meta["format"]
    offset = meta["dataOffset"]
    if fmt in ("DXT1", "DXT3", "DXT5"):
        if _np is not None:
            pixels = _decode_numpy(data, offset, width, height, fmt)
        elif fmt == "DXT1":
            pixels = bytes(_decode_dxt1(data, offset, width, height))
        elif fmt == "DXT5":
            pixels = bytes(_decode_dxt5(data, offset, width, height))
        else:
            pixels = bytes(_decode_dxt3(data, offset, width, height))
    elif meta["fourcc"] in BLOCK_FOURCC:
        # ETC1/ETC2 and ATC live in their own module: they are the Android/older
        # Adreno copies of the very same pictures the DXT files hold.
        from . import etcdecode
        return etcdecode.decode_dds(data)
    elif fmt == "DX10":
        raise DdsError("DX10 headers are not supported")
    else:
        pixels = bytes(_decode_raw(data, offset, width, height,
                                   meta["bitsPerPixel"] or 32, meta["masks"]))
    return width, height, 4, pixels


def backend() -> str:
    """``"numpy"`` or ``"pure"`` - which decoder path :func:`decode` uses."""
    return "numpy" if _np is not None else "pure"
