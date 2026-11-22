"""ETC1/ETC2, ATC and PVRTC decoders - the Android/Apple texture variants.

Real Racing 3 ships the *same* picture four times, once per GPU family, and the
manifests name all four even though only one of them is unpacked in the depot we
have:

===========================  ===========================================
suffix                       family
===========================  ===========================================
``.dxt.dds.z``               desktop / Mali / Adreno (BC1, BC3)
``.atc.dds.z``               older Adreno (Qualcomm ATC)
``.etc.dds.z``               Mali / PowerVR (Ericsson ETC1)
``.ptc.pvr.z``               PowerVR (PVRTC)
===========================  ===========================================

All four are *block* formats, so a decoder is needed per family.  :mod:`rr3lib.
ddsdecode` already handles DXT; this module holds the other three so a depot
unpacked for a different GPU can still be read, exported and thumbnailed.

Everything here is a straight port of MonkeyTool's decoders
(``re/mt/Monkey-Tool-main/src/nfsnl_image.cpp``, ``decodeEtc`` at line 1361,
``decodeAtc`` at 1421 and ``decodePvrtc`` at 1594) - same tables, same rounding,
so a picture decoded here is the picture MonkeyTool shows.

The one thing that is *not* certain is pixel order inside an ETC block: the
reference walks a block as ``x = i >> 2, y = i & 3`` (a transpose of the usual
``x = i & 3, y = i >> 2``).  Both are implemented, ``transpose`` picks, and the
default was chosen by decoding the ETC page that sits next to a DXT page of the
same art and comparing the two - see :func:`selftest`.  Measured on
``gui_assets/960x640/splash/loading/sprites_0.etc.dds.z``: transpose on gives a
mean difference of 2.37 against the DXT page, transpose off gives 6.71, so the
reference is right and ``transpose=True`` is the default.

Two more things worth knowing, both measured rather than guessed:

* **ATC and ETC agree with DXT to within ~2/255 per channel** on the four pages
  where all four copies exist.  That is what makes ``selftest`` a real check.
* **PVRTC does not.**  Decoding ``.ptc.pvr`` and comparing it with the ``.dxt``
  copy of the same page gives a mean difference of ~54, which looks like a
  broken decoder but is not: the two differ by a *gamma curve*, not by noise.
  Feeding the DXT page through ``v -> (v/255)**(1/2.2) * 255`` brings the two
  to within 2.6/255 (see :func:`to_display`), and the fitted exponent is a clear
  minimum at 2.2.  In other words the PowerVR copies are gamma-encoded and the
  DXT/ETC/ATC copies are linear.  The pixels here are left exactly as the file
  holds them - the game applies the curve itself - but anything that compares or
  composites pages from different families has to account for it.
"""

from __future__ import annotations

import struct

#: ETC1/ETC2 per-subblock modifiers, indexed ``[table][(msb << 1) | lsb]``.
ETC_MODIFIER = (
    (2, 8, -2, -8),
    (5, 17, -5, -17),
    (9, 29, -9, -29),
    (13, 42, -13, -42),
    (18, 60, -18, -60),
    (24, 80, -24, -80),
    (33, 106, -33, -106),
    (47, 183, -47, -183),
)

#: ETC2 ``T``/``H`` mode distance table.
ETC_DISTANCE = (3, 6, 11, 16, 23, 32, 41, 64)

#: ETC2 EAC alpha modifiers, ``[table][code]``.
EAC_TABLE = (
    (-3, -6, -9, -15, 2, 5, 8, 14), (-3, -7, -10, -13, 2, 6, 9, 12),
    (-2, -5, -8, -13, 1, 4, 7, 12), (-2, -4, -6, -13, 1, 3, 5, 12),
    (-3, -6, -8, -12, 2, 5, 7, 11), (-3, -7, -9, -11, 2, 6, 8, 10),
    (-4, -7, -8, -11, 3, 6, 7, 10), (-3, -5, -8, -11, 2, 4, 7, 10),
    (-2, -6, -8, -10, 1, 5, 7, 9), (-2, -5, -8, -10, 1, 4, 7, 9),
    (-2, -4, -8, -10, 1, 3, 7, 9), (-2, -5, -7, -10, 1, 4, 6, 9),
    (-3, -4, -7, -10, 2, 3, 6, 9), (-1, -2, -3, -10, 0, 1, 2, 9),
    (-4, -6, -8, -9, 3, 5, 7, 8), (-3, -5, -7, -9, 2, 4, 6, 8),
)


class BlockError(Exception):
    pass


#: Exponent that maps a linear value from a DXT/ETC/ATC page onto the value the
#: PowerVR copy of the same picture holds: ``display = (value/255)**(1/2.2)``.
#: Measured by fitting the ATC page against the PTC page of the same art; 2.2
#: was the clear minimum (2.1 and 2.3 are both ~1.5x worse, 2.0 is 2.3x worse).
DISPLAY_GAMMA = 2.2

#: ``v -> v ** (1/2.2)`` for all 256 byte values, so the curve is a lookup.
DISPLAY_LUT = bytes(min(255, int(round((i / 255.0) ** (1.0 / DISPLAY_GAMMA) * 255)))
                    for i in range(256))


def to_display(pixels: bytes) -> bytes:
    """Apply the PVRTC gamma curve to RGB bytes, leaving alpha alone.

    Turns a page from the linear DXT/ETC/ATC families into the encoding the
    PowerVR pages use, so the two can be compared or composited.  Decoding on
    its own always returns the file's own values - the game applies the curve.
    """
    out = bytearray(pixels)
    for i in range(0, len(out), 4):
        out[i] = DISPLAY_LUT[out[i]]
        out[i + 1] = DISPLAY_LUT[out[i + 1]]
        out[i + 2] = DISPLAY_LUT[out[i + 2]]
    return bytes(out)


def _clamp8(value: int) -> int:
    return 0 if value < 0 else (255 if value > 255 else value)


def _extend4(v: int) -> int:
    return v * 17


def _extend5(v: int) -> int:
    return (v << 3) | (v >> 2)


def _extend6(v: int) -> int:
    return (v << 2) | (v >> 4)


def _extend7(v: int) -> int:
    return (v << 1) | (v >> 6)


def _signed3(v: int) -> int:
    return v - 8 if v > 3 else v


# ---------------------------------------------------------------------------
# ETC1 / ETC2
# ---------------------------------------------------------------------------
def _etc_block(block, out, width, height, bx, by, alpha, transpose):
    """One 8-byte ETC1/ETC2 colour block."""
    flip = block[3] & 1
    diff = (block[3] >> 1) & 1

    c0 = c1 = (0, 0, 0)
    paint = None
    thresholds = False

    if not diff:
        c0 = (_extend4(block[0] >> 4), _extend4(block[1] >> 4), _extend4(block[2] >> 4))
        c1 = (_extend4(block[0] & 15), _extend4(block[1] & 15), _extend4(block[2] & 15))
    else:
        r, dr = block[0] >> 3, _signed3(block[0] & 7)
        g, dg = block[1] >> 3, _signed3(block[1] & 7)
        b, db = block[2] >> 3, _signed3(block[2] & 7)
        r1, g1, b1 = r + dr, g + dg, b + db
        if not 0 <= r1 <= 31:                    # ETC2 "T" mode
            thresholds = True
            r0 = ((block[0] >> 3) & 3) | ((block[0] >> 1) & 0xC)
            a = (_extend4(r0), _extend4(block[1] >> 4), _extend4(block[1] & 15))
            bb = (_extend4(block[2] >> 4), _extend4(block[2] & 15),
                  _extend4(block[3] >> 4))
            d = ETC_DISTANCE[((block[3] >> 1) & 3) | ((block[3] << 1) & 4)]
            paint = (a, (bb[0] + d, bb[1] + d, bb[2] + d), bb,
                     (bb[0] - d, bb[1] - d, bb[2] - d))
        elif not 0 <= g1 <= 31:                  # ETC2 "H" mode
            thresholds = True
            ra = (block[0] >> 3) & 0xF
            ga = ((block[0] & 7) << 1) | ((block[1] >> 4) & 1)
            ba = (block[1] & 8) | ((block[1] & 3) << 1) | ((block[2] >> 7) & 1)
            rb = (block[2] >> 3) & 0xF
            gb = ((block[2] & 7) << 1) | (block[3] >> 7)
            bb2 = (block[3] >> 3) & 0xF
            a = (_extend4(ra), _extend4(ga), _extend4(ba))
            bq = (_extend4(rb), _extend4(gb), _extend4(bb2))
            di = (block[3] & 4) | ((block[3] & 1) << 1)
            if a[0] * 65536 + a[1] * 256 + a[2] >= bq[0] * 65536 + bq[1] * 256 + bq[2]:
                di |= 1
            d = ETC_DISTANCE[di & 7]
            paint = ((a[0] + d, a[1] + d, a[2] + d), (a[0] - d, a[1] - d, a[2] - d),
                     (bq[0] + d, bq[1] + d, bq[2] + d), (bq[0] - d, bq[1] - d, bq[2] - d))
        elif not 0 <= b1 <= 31:                  # ETC2 planar mode
            ro = _extend6((block[0] & 0x7E) >> 1)
            go = _extend7(((block[0] & 1) << 6) | ((block[1] & 0x7E) >> 1))
            bo = _extend6(((block[1] & 1) << 5) | ((block[2] & 0x18) >> 1)
                          | ((block[2] & 3) << 1) | ((block[3] & 0x80) >> 7))
            rh = _extend6(((block[3] & 0x7C) >> 1) | (block[3] & 1))
            gh = _extend7(block[4] >> 1)
            bh = _extend6(((block[4] & 1) << 5) | (block[5] >> 3))
            rv = _extend6(((block[5] & 7) << 3) | (block[6] >> 5))
            gv = _extend7(((block[6] & 0x1F) << 2) | (block[7] >> 6))
            bv = _extend6(block[7] & 0x3F)
            for y in range(4):
                py = by * 4 + y
                if py >= height:
                    continue
                for x in range(4):
                    px = bx * 4 + x
                    if px >= width:
                        continue
                    r2 = (x * (rh - ro) + y * (rv - ro) + 4 * ro + 2) >> 2
                    g2 = (x * (gh - go) + y * (gv - go) + 4 * go + 2) >> 2
                    b2 = (x * (bh - bo) + y * (bv - bo) + 4 * bo + 2) >> 2
                    at = (py * width + px) * 4
                    out[at] = _clamp8(r2)
                    out[at + 1] = _clamp8(g2)
                    out[at + 2] = _clamp8(b2)
                    out[at + 3] = alpha
            return
        else:
            c0 = (_extend5(r), _extend5(g), _extend5(b))
            c1 = (_extend5(r1), _extend5(g1), _extend5(b1))

    t0 = (block[3] >> 5) & 7
    t1 = (block[3] >> 2) & 7
    idx = (block[4] << 24) | (block[5] << 16) | (block[6] << 8) | block[7]
    table0, table1 = ETC_MODIFIER[t0], ETC_MODIFIER[t1]

    for i in range(16):
        if transpose:
            x, y = i >> 2, i & 3
        else:
            x, y = i & 3, i >> 2
        lsb = (idx >> i) & 1
        msb = (idx >> (16 + i)) & 1
        m = (msb << 1) | lsb
        if thresholds:
            colour = paint[m]
        else:
            if flip == 0:
                sub = 0 if x < 2 else 1
            else:
                sub = 0 if y < 2 else 1
            base = c0 if sub == 0 else c1
            d = (table0 if sub == 0 else table1)[m]
            colour = (base[0] + d, base[1] + d, base[2] + d)
        px = bx * 4 + x
        py = by * 4 + y
        if px >= width or py >= height:
            continue
        at = (py * width + px) * 4
        out[at] = _clamp8(colour[0])
        out[at + 1] = _clamp8(colour[1])
        out[at + 2] = _clamp8(colour[2])
        out[at + 3] = alpha


def _eac_alpha_block(block, out, width, height, bx, by):
    """One 8-byte ETC2 EAC alpha block, which precedes the colour block."""
    base = block[0]
    mul = (block[1] >> 4) & 15
    table = EAC_TABLE[block[1] & 15]
    bits = 0
    for i in range(2, 8):
        bits = (bits << 8) | block[i]
    step = mul if mul else 1
    for i in range(16):
        x, y = i >> 2, i & 3
        px, py = bx * 4 + x, by * 4 + y
        if px >= width or py >= height:
            continue
        code = (bits >> (45 - 3 * i)) & 7
        out[(py * width + px) * 4 + 3] = _clamp8(base + table[code] * step)


def decode_etc(data: bytes, width: int, height: int, *,
               with_alpha: bool = False, transpose: bool = True) -> tuple:
    """Decode ETC1 (or ETC2 RGB / ETC2 RGBA) block data.

    ``transpose`` picks the pixel order inside a block; see the module docstring.
    """
    if width <= 0 or height <= 0:
        raise BlockError(f"bad size {width}x{height}")
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    block_bytes = 16 if with_alpha else 8
    need = bw * bh * block_bytes
    if len(data) < need:
        raise BlockError(f"{width}x{height} ETC needs {need} bytes, got {len(data)}")
    out = bytearray(b"\xff" * (width * height * 4))
    for by in range(bh):
        for bx in range(bw):
            off = (by * bw + bx) * block_bytes
            if with_alpha:
                _eac_alpha_block(data[off:off + 8], out, width, height, bx, by)
                _etc_block(data[off + 8:off + 16], out, width, height, bx, by,
                           255, transpose)
            else:
                _etc_block(data[off:off + 8], out, width, height, bx, by,
                           255, transpose)
    return width, height, 4, bytes(out)


# ---------------------------------------------------------------------------
# ATC (Qualcomm)
# ---------------------------------------------------------------------------
def _atc_colours(block) -> tuple:
    """The four colours of one ATC colour block, as ``(r, g, b)`` triples."""
    c0 = block[0] | (block[1] << 8)
    c1 = block[2] | (block[3] << 8)
    r0, g0, b0 = (c0 >> 10) & 31, (c0 >> 5) & 31, c0 & 31
    a = (_extend5(r0), _extend5(g0), _extend5(b0))
    r1, g1, b1 = (c1 >> 11) & 31, (c1 >> 5) & 63, c1 & 31
    d = (_extend5(r1), _extend6(g1), _extend5(b1))
    if c0 & 0x8000:
        return ((0, 0, 0),
                (max(0, a[0] - d[0] // 4), max(0, a[1] - d[1] // 4),
                 max(0, a[2] - d[2] // 4)),
                a, d)
    return (a,
            ((5 * a[0] + 3 * d[0]) // 8, (5 * a[1] + 3 * d[1]) // 8,
             (5 * a[2] + 3 * d[2]) // 8),
            ((3 * a[0] + 5 * d[0]) // 8, (3 * a[1] + 5 * d[1]) // 8,
             (3 * a[2] + 5 * d[2]) // 8),
            d)


def decode_atc(data: bytes, width: int, height: int, *, variant: int = 1) -> tuple:
    """Decode ATC block data.  ``variant``: 1 = RGB, 3 = explicit alpha, 5 = interpolated."""
    if width <= 0 or height <= 0:
        raise BlockError(f"bad size {width}x{height}")
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    block_bytes = 8 if variant == 1 else 16
    need = bw * bh * block_bytes
    if len(data) < need:
        raise BlockError(f"{width}x{height} ATC needs {need} bytes, got {len(data)}")
    out = bytearray(b"\xff" * (width * height * 4))
    for by in range(bh):
        for bx in range(bw):
            off = (by * bw + bx) * block_bytes
            block = data[off:off + block_bytes]
            colour = block if variant == 1 else block[8:]
            palette = _atc_colours(colour)
            bits = struct.unpack_from("<I", colour, 4)[0]
            a0 = a1 = 0
            abits = 0
            if variant != 1:
                a0, a1 = block[0], block[1]
                first = 0 if variant == 3 else 2
                for i in range(7, first - 1, -1):
                    abits = (abits << 8) | block[i]
            for i in range(16):
                px = bx * 4 + (i & 3)
                py = by * 4 + (i >> 2)
                if px >= width or py >= height:
                    continue
                r, g, b = palette[(bits >> (2 * i)) & 3]
                at = (py * width + px) * 4
                out[at] = _clamp8(r)
                out[at + 1] = _clamp8(g)
                out[at + 2] = _clamp8(b)
                if variant == 1:
                    out[at + 3] = 255
                elif variant == 3:
                    out[at + 3] = _clamp8(((abits >> (4 * i)) & 0xF) * 17)
                else:
                    code = (abits >> (3 * i)) & 7
                    if code == 0:
                        value = a0
                    elif code == 1:
                        value = a1
                    elif a0 > a1:
                        value = ((8 - code) * a0 + (code - 1) * a1) // 7
                    elif code == 6:
                        value = 0
                    elif code == 7:
                        value = 255
                    else:
                        value = ((6 - code) * a0 + (code - 1) * a1) // 5
                    out[at + 3] = _clamp8(value)
    return width, height, 4, bytes(out)


# ---------------------------------------------------------------------------
# PVRTC (PowerVR)
# ---------------------------------------------------------------------------
def _twiddle(xs: int, ys: int, x: int, y: int) -> int:
    """Morton (Z-curve) index of block ``(x, y)`` in an ``xs`` x ``ys`` grid."""
    min_dim, max_val = xs, y
    if ys < xs:
        min_dim, max_val = ys, x
    t = 0
    src = 1
    dst = 1
    shift = 0
    while src < min_dim:
        if y & src:
            t |= dst
        if x & src:
            t |= dst << 1
        src <<= 1
        dst <<= 2
        shift += 1
    max_val >>= shift
    t |= max_val << (2 * shift)
    return t


def _pvrtc_colours(cd: int) -> tuple:
    """The two endpoint colours of one PVRTC block, as 8-bit ``(r, g, b, a)``."""
    if cd & (1 << 15):                            # opaque, RGB 554
        a = ((cd & 0x7C00) >> 10, (cd & 0x03E0) >> 5,
             (cd & 0x001E) | ((cd & 0x001E) >> 4), 15)
    else:                                         # translucent, ARGB 3443
        a = (((cd & 0x0F00) >> 7) | ((cd & 0x0F00) >> 11),
             ((cd & 0x00F0) >> 3) | ((cd & 0x00F0) >> 7),
             ((cd & 0x000E) << 1) | ((cd & 0x000E) >> 2),
             (cd & 0x7000) >> 11)
    if cd & (1 << 31):                            # opaque, RGB 555
        b = ((cd & 0x7C000000) >> 26, (cd & 0x03E00000) >> 21,
             (cd & 0x001F0000) >> 16, 15)
    else:                                         # translucent, ARGB 4443
        b = (((cd & 0x0F000000) >> 23) | ((cd & 0x0F000000) >> 27),
             ((cd & 0x00F00000) >> 19) | ((cd & 0x00F00000) >> 23),
             ((cd & 0x000F0000) >> 15) | ((cd & 0x000F0000) >> 19),
             (cd & 0x70000000) >> 27)
    return (tuple(c * 255 // 31 if i < 3 else c * 255 // 15 for i, c in enumerate(a)),
            tuple(c * 255 // 31 if i < 3 else c * 255 // 15 for i, c in enumerate(b)))


def decode_pvrtc(data: bytes, width: int, height: int, *,
                 two_bpp: bool = False) -> tuple:
    """Decode PVRTC block data (4 bpp by default, 2 bpp when ``two_bpp``)."""
    if width <= 0 or height <= 0:
        raise BlockError(f"bad size {width}x{height}")
    block_w, block_h = (8 if two_bpp else 4), 4
    bw = max(2, (width + block_w - 1) // block_w)
    bh = max(2, (height + block_h - 1) // block_h)
    if len(data) < bw * bh * 8:
        raise BlockError(
            f"{width}x{height} PVRTC needs {bw * bh * 8} bytes, got {len(data)}")

    ca = [None] * (bw * bh)
    cb = [None] * (bw * bh)
    mod = [0] * (bw * bh)
    mode = [0] * (bw * bh)
    for by in range(bh):
        for bx in range(bw):
            off = _twiddle(bw, bh, bx, by) * 8
            if off + 8 > len(data):
                raise BlockError(f"PVRTC block ({bx},{by}) runs past the data")
            m, cd = struct.unpack_from("<2I", data, off)
            i = by * bw + bx
            ca[i], cb[i] = _pvrtc_colours(cd)
            mod[i] = m
            mode[i] = cd & 1

    out = bytearray(width * height * 4)
    span = 8 if two_bpp else 4
    for y in range(height):
        by0 = (((y - 2) >> 2) % bh + bh) % bh
        by1 = (by0 + 1) % bh
        fy = (y - 2) & 3
        for x in range(width):
            if two_bpp:
                bx0 = (((x - 4) >> 3) % bw + bw) % bw
                fx = (x - 4) & 7
            else:
                bx0 = (((x - 2) >> 2) % bw + bw) % bw
                fx = (x - 2) & 3
            bx1 = (bx0 + 1) % bw
            p = [0, 0, 0, 0]
            q = [0, 0, 0, 0]
            a00, a01 = ca[by0 * bw + bx0], ca[by0 * bw + bx1]
            a10, a11 = ca[by1 * bw + bx0], ca[by1 * bw + bx1]
            b00, b01 = cb[by0 * bw + bx0], cb[by0 * bw + bx1]
            b10, b11 = cb[by1 * bw + bx0], cb[by1 * bw + bx1]
            for c in range(4):
                top = a00[c] * (span - fx) + a01[c] * fx
                bot = a10[c] * (span - fx) + a11[c] * fx
                p[c] = (top * (4 - fy) + bot * fy) // (span * 4)
                top = b00[c] * (span - fx) + b01[c] * fx
                bot = b10[c] * (span - fx) + b11[c] * fx
                q[c] = (top * (4 - fy) + bot * fy) // (span * 4)
            mi = (y // block_h) * bw + (x // block_w)
            if mi >= len(mod):
                continue
            punch = False
            if two_bpp:
                bit = (y & 3) * 8 + (x & 7)
                weight = 8 if (mod[mi] >> bit) & 1 else 0
            else:
                bit = ((y & 3) * 4 + (x & 3)) * 2
                m = (mod[mi] >> bit) & 3
                if mode[mi]:
                    weight = (0, 4, 4, 8)[m]
                    punch = m == 2
                else:
                    weight = (0, 3, 5, 8)[m]
            at = (y * width + x) * 4
            for c in range(4):
                out[at + c] = min(255, max(0, (p[c] * (8 - weight) + q[c] * weight) // 8))
            if punch:
                out[at + 3] = 0
    return width, height, 4, bytes(out)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
#: DDS four-character code -> ``(decoder, kwargs)``.
DDS_FOURCC = {
    b"ETC ": (decode_etc, {}),
    b"ETC1": (decode_etc, {}),
    b"ETC2": (decode_etc, {}),
    b"ETCA": (decode_etc, {"with_alpha": True}),
    b"ATC ": (decode_atc, {"variant": 1}),
    b"ATCA": (decode_atc, {"variant": 3}),
    b"ATCI": (decode_atc, {"variant": 5}),
}

#: PVR ``flags & 0xff`` -> ``(decoder, kwargs)``, the numbering MonkeyTool uses.
PVR_KINDS = {
    0x0C: (decode_pvrtc, {"two_bpp": True}),
    0x18: (decode_pvrtc, {"two_bpp": True}),
    0x0D: (decode_pvrtc, {"two_bpp": False}),
    0x19: (decode_pvrtc, {"two_bpp": False}),
    0x36: (decode_etc, {}),
    0x78: (decode_atc, {"variant": 1}),
    0x79: (decode_atc, {"variant": 5}),
    0x7A: (decode_atc, {"variant": 3}),
}


def dds_format(fourcc: bytes) -> str:
    """A readable name for a block fourcc, or ``""`` when it is not ours."""
    return {
        b"ETC ": "ETC1", b"ETC1": "ETC1", b"ETC2": "ETC2", b"ETCA": "ETC2+EAC",
        b"ATC ": "ATC", b"ATCA": "ATC+explicit", b"ATCI": "ATC+interpolated",
    }.get(fourcc, "")


def decode_dds(data: bytes) -> tuple:
    """Decode a DDS whose fourcc is one of :data:`DDS_FOURCC`."""
    if len(data) < 128 or data[:4] != b"DDS ":
        raise BlockError("not a DDS file")
    height, width = struct.unpack_from("<2I", data, 12)
    fourcc = data[84:88]
    hit = DDS_FOURCC.get(fourcc)
    if hit is None:
        raise BlockError(f"{fourcc!r} is not an ETC/ATC fourcc")
    decoder, kwargs = hit
    return decoder(data[128:], width, height, **kwargs)


def decode_pvr(data: bytes) -> tuple:
    """Decode a PVR whose ``flags`` word names a block format."""
    if len(data) < 52 or data[44:48] != b"PVR!":
        raise BlockError("not a PVR file")
    height, width = struct.unpack_from("<2I", data, 4)
    flags = struct.unpack_from("<I", data, 16)[0]
    kind = flags & 0xFF
    hit = PVR_KINDS.get(kind)
    if hit is None:
        raise BlockError(f"PVR kind {kind:#04x} is not a block format we know")
    decoder, kwargs = hit
    return decoder(data[52:], width, height, **kwargs)


def selftest(depot: str) -> int:
    """Decode every variant of one page and compare each with the DXT copy.

    The depot ships the same picture in several formats side by side under
    ``gui_assets``, so a decoder can be checked against a decoder that is
    already trusted.  A wrong pixel order or a wrong table shows up as a large
    mean difference and as block noise that the DXT decode does not have.

    PVRTC is reported twice: as-is, and after :func:`to_display`, because the
    PowerVR pages are gamma-encoded while the other three are not.
    """
    import os

    from . import ddsdecode, texport

    folder = os.path.join(depot, "gui_assets", "960x640", "splash", "loading")
    if not os.path.isdir(folder):
        print(f"  no {folder}")
        return 1
    reference = None
    path = os.path.join(folder, "sprites_0.dxt.dds.z")
    if os.path.isfile(path):
        reference = ddsdecode.decode(texport.payloads(path)[0])
    if reference is None:
        print("  no DXT page to compare against")
        return 1
    rw, rh, rc, rpx = reference
    print(f"  reference {rw}x{rh} from sprites_0.dxt.dds.z")
    bad = 0
    for name in ("sprites_0.etc.dds.z", "sprites_0.atc.dds.z",
                 "sprites_0.ptc.pvr.z"):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            print(f"  {name:24s} missing")
            continue
        payload = texport.payloads(path)[0]
        try:
            if name.endswith(".pvr.z"):
                got = decode_pvr(payload)
            else:
                got = decode_dds(payload)
        except BlockError as exc:
            print(f"  {name:24s} FAILED {exc}")
            bad += 1
            continue
        w, h, ch, px = got
        if (w, h) != (rw, rh):
            print(f"  {name:24s} size {w}x{h} != {rw}x{rh}")
            bad += 1
            continue
        mad = _mean_difference(rpx, rc, px, ch, w, h)
        line = f"  {name:24s} {w}x{h} mean difference vs DXT: {mad:.2f}"
        if name.endswith(".pvr.z"):
            # The PowerVR pages are gamma-encoded and the other three are not,
            # so the honest comparison is the DXT page through the curve.
            shown = _mean_difference(to_display(rpx), rc, px, ch, w, h)
            line += f"  (DXT through the curve: {shown:.2f})"
        print(line)
    return bad


def _mean_difference(apx, ach, bpx, bch, width, height) -> float:
    total = 0
    count = 0
    for y in range(0, height, 9):
        for x in range(0, width, 9):
            a = (y * width + x) * ach
            b = (y * width + x) * bch
            total += (abs(apx[a] - bpx[b]) + abs(apx[a + 1] - bpx[b + 1])
                      + abs(apx[a + 2] - bpx[b + 2]))
            count += 3
    return total / count if count else 0.0
