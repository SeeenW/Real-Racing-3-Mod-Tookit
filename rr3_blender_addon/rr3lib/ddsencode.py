"""Write DXT1 and DXT5 blocks - the reverse of :mod:`rr3lib.ddsdecode`.

The game ships four encodes of every texture and the depot only unpacks one of
them, so "put my own picture back" has to know how to make the one that is on
disk.  DXT1 (no alpha) and DXT5 (with alpha) cover every car and UI page in the
Adreno copy of the data; the ETC/ATC/PVRTC copies are read-only here, because
writing them means a block encoder for each and the DXT copy is what the game
on this machine reads.

The encoder is deliberately simple: a block's two endpoints are the per-channel
bounding box of its sixteen pixels, and each pixel takes the nearest of the four
interpolated colours.  That is within a couple of levels of what the shipped
pages look like (measured on the splash pages, see :func:`selftest`), and it is
small enough to be obviously correct.  It is not a rate-distortion optimiser and
does not try to be.

Both paths are vectorised with numpy when it is importable and fall back to plain
Python otherwise, the same arrangement :mod:`rr3lib.ddsdecode` uses.
"""

from __future__ import annotations

import struct

try:                                            # pragma: no cover - platform dependent
    import numpy as _np
except Exception:                               # noqa: BLE001 - numpy is optional
    _np = None


DDS_MAGIC = b"DDS "
HEADER_SIZE = 128

#: ``DDS_PIXELFORMAT.dwFlags``: DDPF_FOURCC.
DDPF_FOURCC = 0x4
#: ``DDS_HEADER.dwFlags``: CAPS | HEIGHT | WIDTH | PIXELFORMAT | LINEARSIZE.
DDS_FLAGS = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
#: ``DDS_HEADER.dwFlags``: DDSD_MIPMAPCOUNT, set only when a chain is written.
DDS_MIPMAPCOUNT = 0x20000


class DdsEncodeError(Exception):
    """Raised when a picture cannot be turned into a DDS."""


def _clamp8(value: int) -> int:
    if value < 0:
        return 0
    if value > 255:
        return 255
    return value


def _to565(r: int, g: int, b: int) -> int:
    return ((_clamp8(r) >> 3) << 11) | ((_clamp8(g) >> 2) << 5) | (_clamp8(b) >> 3)


def _from565(value: int) -> tuple:
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _palette(c0: int, c1: int, four_colour: bool) -> list:
    a = _from565(c0)
    b = _from565(c1)
    if four_colour:
        return [a, b,
                tuple((2 * a[i] + b[i]) // 3 for i in range(3)),
                tuple((a[i] + 2 * b[i]) // 3 for i in range(3))]
    return [a, b,
            tuple((a[i] + b[i]) // 2 for i in range(3)),
            (0, 0, 0)]


def _nearest(pixel: tuple, colours: list) -> int:
    best = 0
    best_distance = None
    for index, colour in enumerate(colours):
        distance = sum((pixel[i] - colour[i]) ** 2 for i in range(3))
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = index
    return best


# --------------------------------------------------------------------------
# numpy path
# --------------------------------------------------------------------------

def _blocks_numpy(pixels: bytes, width: int, height: int):
    """``(bh, bw, 16, 4)`` view of the picture, padded to whole blocks."""
    data = _np.frombuffer(pixels, dtype=_np.uint8).reshape(height, width, 4)
    pad_h = (-height) % 4
    pad_w = (-width) % 4
    if pad_h or pad_w:
        data = _np.pad(data, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
    rows, cols = data.shape[0] // 4, data.shape[1] // 4
    return data.reshape(rows, 4, cols, 4, 4).transpose(0, 2, 1, 3, 4).reshape(
        rows, cols, 16, 4)


def _encode_colour_numpy(blocks):
    """``(u16 c0, u16 c1, u32 indices)`` per block, from ``(bh, bw, 16, 4)``."""
    rgb = blocks[..., :3].astype(_np.int32)
    high = rgb.max(axis=2)
    low = rgb.min(axis=2)
    packed_high = (((high[..., 0] >> 3) << 11) | ((high[..., 1] >> 2) << 5)
                   | (high[..., 2] >> 3)).astype(_np.uint16)
    packed_low = (((low[..., 0] >> 3) << 11) | ((low[..., 1] >> 2) << 5)
                  | (low[..., 2] >> 3)).astype(_np.uint16)
    # DXT1 reads c0 > c1 as "four colours"; swapping keeps it in that mode.
    swap = packed_high <= packed_low
    c0 = _np.where(swap, packed_low, packed_high).astype(_np.uint16)
    c1 = _np.where(swap, packed_high, packed_low).astype(_np.uint16)

    def expand(value):
        r = (value.astype(_np.int32) >> 11) & 0x1F
        g = (value.astype(_np.int32) >> 5) & 0x3F
        b = value.astype(_np.int32) & 0x1F
        return _np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4),
                          (b << 3) | (b >> 2)], axis=-1)

    p0 = expand(c0)
    p1 = expand(c1)
    palette = _np.stack([p0, p1,
                         (2 * p0 + p1) // 3,
                         (p0 + 2 * p1) // 3], axis=2)          # (bh,bw,4,3)
    distance = ((rgb[:, :, :, None, :] - palette[:, :, None, :, :]) ** 2).sum(axis=4)
    index = distance.argmin(axis=3).astype(_np.uint32)         # (bh,bw,16)
    bits = _np.zeros(index.shape[:2], dtype=_np.uint32)
    for slot in range(16):
        bits |= index[:, :, slot] << _np.uint32(2 * slot)
    return c0, c1, bits


def _encode_alpha_numpy(blocks):
    """``(u8 a0, u8 a1, 6 bytes of 3-bit indices)`` per block."""
    alpha = blocks[..., 3].astype(_np.int32)
    a0 = alpha.max(axis=2).astype(_np.uint8)
    a1 = alpha.min(axis=2).astype(_np.uint8)
    swap = a0 <= a1
    high = _np.where(swap, a1, a0).astype(_np.int32)
    low = _np.where(swap, a0, a1).astype(_np.int32)
    a0 = high.astype(_np.uint8)
    a1 = low.astype(_np.uint8)
    palette = [high, low]
    for i in range(1, 7):
        palette.append(((7 - i) * high + i * low) // 7)
    palette = _np.stack(palette, axis=2)                       # (bh,bw,8)
    distance = (alpha[:, :, :, None] - palette[:, :, None, :]) ** 2
    index = distance.argmin(axis=3).astype(_np.uint64)         # (bh,bw,16)
    bits = _np.zeros(index.shape[:2], dtype=_np.uint64)
    for slot in range(16):
        bits |= index[:, :, slot] << _np.uint64(3 * slot)
    return a0, a1, bits


def _encode_numpy(pixels: bytes, width: int, height: int, alpha: bool) -> bytes:
    blocks = _blocks_numpy(pixels, width, height)
    c0, c1, colour_bits = _encode_colour_numpy(blocks)
    rows, cols = c0.shape
    if not alpha:
        out = bytearray(rows * cols * 8)
        offset = 0
        for y in range(rows):
            for x in range(cols):
                struct.pack_into("<HHI", out, offset, int(c0[y, x]),
                                 int(c1[y, x]), int(colour_bits[y, x]))
                offset += 8
        return bytes(out)
    a0, a1, alpha_bits = _encode_alpha_numpy(blocks)
    out = bytearray(rows * cols * 16)
    offset = 0
    for y in range(rows):
        for x in range(cols):
            out[offset] = int(a0[y, x])
            out[offset + 1] = int(a1[y, x])
            value = int(alpha_bits[y, x])
            for byte in range(6):
                out[offset + 2 + byte] = (value >> (8 * byte)) & 0xFF
            struct.pack_into("<HHI", out, offset + 8, int(c0[y, x]),
                             int(c1[y, x]), int(colour_bits[y, x]))
            offset += 16
    return bytes(out)


# --------------------------------------------------------------------------
# plain Python path
# --------------------------------------------------------------------------

def _encode_pure(pixels: bytes, width: int, height: int, alpha: bool) -> bytes:
    out = bytearray()
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            block = []
            for y in range(4):
                for x in range(4):
                    px = min(bx + x, width - 1)
                    py = min(by + y, height - 1)
                    at = (py * width + px) * 4
                    block.append((pixels[at], pixels[at + 1], pixels[at + 2],
                                  pixels[at + 3]))
            if alpha:
                values = [p[3] for p in block]
                high, low = max(values), min(values)
                if high == low:
                    table = [high] * 8
                    indices = [0] * 16
                else:
                    table = [high, low] + [((7 - i) * high + i * low) // 7
                                           for i in range(1, 7)]
                    indices = [_nearest_alpha(p[3], table) for p in block]
                out.append(high)
                out.append(low)
                packed = 0
                for slot, index in enumerate(indices):
                    packed |= index << (3 * slot)
                out += packed.to_bytes(6, "little")
            high = (max(p[0] for p in block), max(p[1] for p in block),
                    max(p[2] for p in block))
            low = (min(p[0] for p in block), min(p[1] for p in block),
                   min(p[2] for p in block))
            c0 = _to565(*high)
            c1 = _to565(*low)
            if c0 < c1:
                c0, c1 = c1, c0
            colours = _palette(c0, c1, True)
            packed = 0
            for slot, pixel in enumerate(block):
                packed |= _nearest(pixel[:3], colours) << (2 * slot)
            out += struct.pack("<HHI", c0, c1, packed)
    return bytes(out)


def _nearest_alpha(value: int, table: list) -> int:
    best = 0
    best_distance = None
    for index, entry in enumerate(table):
        distance = (value - entry) ** 2
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = index
    return best


# --------------------------------------------------------------------------
# public
# --------------------------------------------------------------------------

def encode_blocks(width: int, height: int, channels: int, pixels: bytes, *,
                  alpha: bool = False) -> bytes:
    """The raw DXT payload for ``pixels`` (top-down, ``channels`` per pixel)."""
    if width <= 0 or height <= 0:
        raise DdsEncodeError(f"bad dimensions {width}x{height}")
    if channels not in (3, 4):
        raise DdsEncodeError(f"cannot encode {channels} channel pixels")
    need = width * height * channels
    if len(pixels) != need:
        raise DdsEncodeError(
            f"{width}x{height}x{channels} needs {need} bytes, got {len(pixels)}")
    if channels == 3:
        if alpha:
            raise DdsEncodeError("DXT5 needs an alpha channel")
        rgba = bytearray(width * height * 4)
        rgba[0::4] = pixels[0::3]
        rgba[1::4] = pixels[1::3]
        rgba[2::4] = pixels[2::3]
        rgba[3::4] = b"\xff" * (width * height)
        pixels = bytes(rgba)
    if _np is not None:
        return _encode_numpy(pixels, width, height, alpha)
    return _encode_pure(pixels, width, height, alpha)


def header(width: int, height: int, *, alpha: bool,
           fourcc: bytes = b"", mipmaps: int = 1) -> bytes:
    """A 128 byte DDS header carrying the DXT1 or DXT5 fourcc.

    ``fourcc`` overrides the code in the pixel format block, which is how the
    ETC and ATC encoders in :mod:`rr3lib.blockencode` produce a header for their
    own family.  Those two store eight bytes per block exactly as DXT1 does, so
    the pitch and the flags stay the same and only the four characters change.

    ``mipmaps`` is the number of levels actually written after the header.  The
    shipped pages carry the full chain (a 512 square page has ten), and the
    header has to say so twice - ``dwMipMapCount`` and the two capability bits -
    or a reader that trusts either one sees a texture it cannot sample.
    """
    if width <= 0 or height <= 0:
        raise DdsEncodeError(f"bad dimensions {width}x{height}")
    if not fourcc:
        fourcc = b"DXT5" if alpha else b"DXT1"
    elif len(fourcc) != 4:
        raise DdsEncodeError(f"a fourcc is four bytes, not {len(fourcc)}")
    block = 16 if alpha else 8
    pitch = max(1, (width + 3) // 4) * block
    flags = DDS_FLAGS
    caps = 0x1000
    if mipmaps > 1:
        flags |= DDS_MIPMAPCOUNT
        caps |= 0x8 | 0x400000        # DDSCAPS_COMPLEX | DDSCAPS_MIPMAP
    return struct.pack(
        "<4s7I44x", DDS_MAGIC, 124, flags, height, width, pitch, 0, max(1, mipmaps)
    ) + struct.pack(
        "<8I", 32, DDPF_FOURCC, int.from_bytes(fourcc, "little"), 0, 0, 0, 0, 0
    ) + struct.pack("<5I", caps, 0, 0, 0, 0)


def halve(width: int, height: int, channels: int, pixels: bytes):
    """``(w, h, pixels)`` at half size, averaging each 2x2 block.

    A box filter is what a mip chain wants and what every DXT mip of the shipped
    data looks like.  An odd edge reuses the last row/column rather than
    dropping it, so a non-square page keeps its aspect.
    """
    w = max(1, width // 2)
    h = max(1, height // 2)
    if _np is not None:
        arr = _np.frombuffer(pixels, dtype=_np.uint8).reshape(height, width, channels)
        if height % 2:
            arr = _np.concatenate([arr, arr[-1:]], axis=0)
        if width % 2:
            arr = _np.concatenate([arr, arr[:, -1:]], axis=1)
        small = (arr[0::2, 0::2].astype(_np.uint16)
                 + arr[1::2, 0::2] + arr[0::2, 1::2] + arr[1::2, 1::2] + 2) // 4
        # The padding above adds a row and a column for an odd edge, so the
        # averaged block is one larger than the answer on that axis - 15 -> 8
        # rather than 7.  Trimming to (h, w) is what keeps the caller's stride
        # right; without it a 15x7 page came back as 8 rows of 8 pixels and the
        # next level's reshape failed.
        small = small[:h, :w]
        return w, h, small.astype(_np.uint8).tobytes()
    out = bytearray(w * h * channels)
    for y in range(h):
        y0 = min(2 * y, height - 1)
        y1 = min(2 * y + 1, height - 1)
        for x in range(w):
            x0 = min(2 * x, width - 1)
            x1 = min(2 * x + 1, width - 1)
            base = (y * w + x) * channels
            for c in range(channels):
                total = (pixels[(y0 * width + x0) * channels + c]
                         + pixels[(y0 * width + x1) * channels + c]
                         + pixels[(y1 * width + x0) * channels + c]
                         + pixels[(y1 * width + x1) * channels + c])
                out[base + c] = (total + 2) // 4
    return w, h, bytes(out)


def encode(width: int, height: int, channels: int, pixels: bytes, *,
           alpha: bool | None = None, mipmaps: bool = True) -> bytes:
    """A complete DDS file for ``pixels``.

    ``alpha`` picks DXT5 over DXT1; left out, a four channel picture gets DXT5
    and a three channel one gets DXT1.

    ``mipmaps`` writes the whole chain down to 1x1, which is what the shipped
    pages carry.  A single level page still loads, but the GPU then samples a
    512 square page at full resolution at every distance and the result crawls
    badly, so the default is on.
    """
    if alpha is None:
        alpha = channels == 4
    levels = [(width, height, pixels)]
    if mipmaps:
        w, h, px = width, height, pixels
        while w > 1 or h > 1:
            w, h, px = halve(w, h, channels, px)
            levels.append((w, h, px))
    body = b"".join(encode_blocks(w, h, channels, px, alpha=alpha)
                    for w, h, px in levels)
    return header(width, height, alpha=alpha, mipmaps=len(levels)) + body


def selftest(depot: str, pages=()) -> int:
    """Decode, re-encode and decode again; prints the round trip difference.

    ``pages`` defaults to the four-encode sample pages the depot keeps under
    ``gui_assets``.  Returns the number of problems (0 when all is well).
    """
    import os

    from . import ddsdecode

    if not pages:
        base = os.path.join(depot, "gui_assets", "960x640", "splash", "loading")
        for name in ("sprites_0.dxt.dds.z", "sprites_0.etc.dds.z"):
            candidate = os.path.join(base, name)
            if os.path.isfile(candidate):
                pages = list(pages) + [candidate]
    problems = 0
    for path in pages:
        if not os.path.isfile(path):
            print(f"  missing {path}")
            problems += 1
            continue
        with open(path, "rb") as handle:
            raw = handle.read()
        if raw[:4] != DDS_MAGIC:
            raw = ddsdecode._inflate_z(raw) if hasattr(ddsdecode, "_inflate_z") else raw
        try:
            width, height, channels, pixels = ddsdecode.decode(raw)
        except Exception as exc:                # noqa: BLE001 - report and carry on
            print(f"  {os.path.basename(path)}: {exc}")
            problems += 1
            continue
        for alpha in (False, True):
            packed = encode(width, height, channels, pixels, alpha=alpha)
            width2, height2, channels2, again = ddsdecode.decode(packed)
            if (width2, height2, channels2) != (width, height, channels):
                print(f"  {os.path.basename(path)}: shape changed "
                      f"{width2}x{height2}x{channels2}")
                problems += 1
                continue
            total = 0
            for i in range(0, len(pixels), 4):
                for channel in range(3 if alpha else 4):
                    total += abs(pixels[i + channel] - again[i + channel])
            steps = (len(pixels) // 4) * (3 if alpha else 4)
            print(f"  {os.path.basename(path)} {width}x{height} "
                  f"{'DXT5' if alpha else 'DXT1'} "
                  f"mean difference vs the original: {total / steps:.2f}")
    return problems


if __name__ == "__main__":                      # pragma: no cover - manual run
    import sys
    depot = sys.argv[1] if len(sys.argv) > 1 else ""
    raise SystemExit(1 if selftest(depot) else 0)
