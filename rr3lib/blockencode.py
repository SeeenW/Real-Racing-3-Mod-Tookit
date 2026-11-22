"""ETC1 and ATC block encoders - the two families that can be written.

The game ships every page four times, once per GPU family, and until now only the
DXT copy could be produced: :mod:`rr3lib.ddsencode` has the block encoder for it
and :mod:`rr3lib.etcdecode` only reads the other three.  That is fine on an Adreno
device, where the ``.dxt.dds.z`` copy is the one the engine loads, but a depot
unpacked for a Mali or an older Adreno device ships only ``.etc`` or ``.atc``, and
a page replaced there would have to be encoded in that family or not at all.

So this module holds the two block encoders that are small enough to get exactly
right:

* **ETC1** - 8 bytes per 4x4 block: two subblocks of 8 pixels, each with a base
  colour and one of eight modifier tables.  The base is either four bits per
  channel (the two subblocks independent) or five bits per channel plus a signed
  three bit delta (the second subblock relative to the first).  Both are tried
  per block and the closer one wins, which is what the format is for.
* **ATC** - 8 bytes per 4x4 block: two endpoint colours and two bits per pixel.
  The endpoints are the block's darkest and brightest pixels, and the four
  palette entries are the endpoints and two blends between them.

**PVRTC is deliberately absent.**  Its 4 bpp blocks do not hold two endpoints for
their own 4x4 area: the endpoints are bilinearly interpolated *across* blocks, so
encoding one block changes its neighbours' pixels, and a correct encoder has to
solve the whole picture at once rather than block by block.  A block-at-a-time
encoder produces something that decodes to a picture and looks wrong, which is
worse than refusing - so :func:`rr3lib.texport.build_texture` still refuses
``.ptc.pvr.z``, and says why.

Both encoders here take and return what :mod:`rr3lib.ddsdecode` and
:mod:`rr3lib.etcdecode` do: top-down RGBA pixels in, raw block bytes out, so a
round trip can be measured by decoding the result and comparing.
"""

from __future__ import annotations

from .etcdecode import ETC_DISTANCE, ETC_MODIFIER, _extend4, _extend5, _extend6

__all__ = ["BlockEncodeError", "encode_etc", "encode_atc", "header_etc",
           "header_atc", "selftest"]


class BlockEncodeError(Exception):
    """A picture that cannot be encoded in this family."""


def _clamp8(value: int) -> int:
    if value < 0:
        return 0
    if value > 255:
        return 255
    return value


def _rgba(width: int, height: int, channels: int, pixels: bytes) -> bytes:
    if channels not in (3, 4):
        raise BlockEncodeError(f"cannot encode {channels} channel pixels")
    need = width * height * channels
    if len(pixels) != need:
        raise BlockEncodeError(
            f"{width}x{height}x{channels} needs {need} bytes, got {len(pixels)}")
    if channels == 4:
        return bytes(pixels)
    out = bytearray(width * height * 4)
    out[0::4] = pixels[0::3]
    out[1::4] = pixels[1::3]
    out[2::4] = pixels[2::3]
    out[3::4] = b"\xff" * (width * height)
    return bytes(out)


def _block_pixels(rgba: bytes, width: int, height: int, bx: int, by: int) -> list:
    """The 16 pixels of a block, in the order the decoders index them.

    ``etcdecode`` walks a block as ``x = i >> 2, y = i & 3`` for ETC and
    ``x = i & 3, y = i >> 2`` for ATC, and both of those are the *same* list here
    because this returns ``[(x, y, r, g, b, a)]`` and each caller places them
    itself.  Pixels past the edge repeat the last real one, which is what the
    decoders would clamp to anyway.
    """
    out = []
    for y in range(4):
        py = min(height - 1, by * 4 + y)
        for x in range(4):
            px = min(width - 1, bx * 4 + x)
            at = (py * width + px) * 4
            out.append((x, y, rgba[at], rgba[at + 1], rgba[at + 2], rgba[at + 3]))
    return out


# ---------------------------------------------------------------------------
# ETC1
# ---------------------------------------------------------------------------
def _etc_subblock_error(pixels, base, table) -> tuple:
    """Best index for each pixel and the total squared error for one table."""
    total = 0
    chosen = []
    for _x, _y, r, g, b, _a in pixels:
        best = 0
        best_error = None
        for index in range(4):
            delta = table[index]
            dr = _clamp8(base[0] + delta) - r
            dg = _clamp8(base[1] + delta) - g
            db = _clamp8(base[2] + delta) - b
            error = dr * dr + dg * dg + db * db
            if best_error is None or error < best_error:
                best_error = error
                best = index
        total += best_error
        chosen.append(best)
    return total, chosen


def _etc_best_table(pixels, base) -> tuple:
    """The table with the lowest error, and the indices it gives."""
    best_total = None
    best_table = 0
    best_chosen = None
    for index, table in enumerate(ETC_MODIFIER):
        total, chosen = _etc_subblock_error(pixels, base, table)
        if best_total is None or total < best_total:
            best_total = total
            best_table = index
            best_chosen = chosen
    return best_total, best_table, best_chosen


def _etc_subblocks(pixels, flip: int) -> list:
    if flip == 0:
        return ([p for p in pixels if p[0] < 2], [p for p in pixels if p[0] >= 2])
    return ([p for p in pixels if p[1] < 2], [p for p in pixels if p[1] >= 2])


def _mean(pixels) -> tuple:
    count = len(pixels)
    return (sum(p[2] for p in pixels) // count,
            sum(p[3] for p in pixels) // count,
            sum(p[4] for p in pixels) // count)


def _etc_block(pixels, flip: int) -> tuple:
    """Encode one block with a fixed ``flip``; returns ``(error, 8 bytes)``."""
    first, second = _etc_subblocks(pixels, flip)

    # Individual mode: four bits per channel, the two subblocks unrelated.
    bases4 = []
    for half in (first, second):
        mean = _mean(half)
        bases4.append(tuple(mean[i] >> 4 for i in range(3)))
    individual_total = 0
    individual_tables = []
    individual_chosen = []
    for half, base4 in zip((first, second), bases4):
        base = tuple(_extend4(v) for v in base4)
        total, table, chosen = _etc_best_table(half, base)
        individual_total += total
        individual_tables.append(table)
        individual_chosen.append(chosen)

    # Differential mode: five bits per channel plus a signed three bit delta.
    bases5 = []
    for half in (first, second):
        mean = _mean(half)
        bases5.append(tuple(min(31, max(0, mean[i] >> 3)) for i in range(3)))
    delta = tuple(bases5[1][i] - bases5[0][i] for i in range(3))
    differential_total = None
    differential_tables = []
    differential_chosen = []
    if all(-4 <= d <= 3 for d in delta):
        differential_total = 0
        for half, base5 in zip((first, second), bases5):
            base = tuple(_extend5(v) for v in base5)
            total, table, chosen = _etc_best_table(half, base)
            differential_total += total
            differential_tables.append(table)
            differential_chosen.append(chosen)

    if differential_total is not None and differential_total < individual_total:
        head = bytearray(3)
        for i in range(3):
            head[i] = (bases5[0][i] << 3) | (delta[i] & 7)
        tables = differential_tables
        chosen = differential_chosen
        error = differential_total
        diff_bit = 1
    else:
        head = bytearray(3)
        for i in range(3):
            head[i] = (bases4[0][i] << 4) | bases4[1][i]
        tables = individual_tables
        chosen = individual_chosen
        error = individual_total
        diff_bit = 0

    control = (flip & 1) | ((diff_bit & 1) << 1) | ((tables[1] & 7) << 2) \
        | ((tables[0] & 7) << 5)
    # The decoder walks a block as ``x = i >> 2, y = i & 3`` (its ``transpose``
    # default, which is the one the game's pages need), so a pixel's bit position
    # is ``(x << 2) | y`` rather than its place in a row major list.
    low_bits = 0
    high_bits = 0
    for half_index, half_chosen in enumerate(chosen):
        for pixel, modifier in zip(
                [p for p in pixels
                 if ((p[0] < 2) if flip == 0 else (p[1] < 2)) == (half_index == 0)],
                half_chosen):
            bit = (pixel[0] << 2) | pixel[1]
            low_bits |= (modifier & 1) << bit
            high_bits |= ((modifier >> 1) & 1) << bit
    word = low_bits | (high_bits << 16)
    return error, bytes(head) + bytes([control]) + word.to_bytes(4, "big")


def encode_etc(width: int, height: int, channels: int, pixels: bytes, *,
               alpha: bool = False) -> bytes:
    """Raw ETC1 block data for a picture (top-down, ``channels`` per pixel).

    ETC1 has no alpha channel, so a four channel picture is encoded on its colour
    alone and the alpha is dropped.  ``alpha`` is accepted so callers can share
    one signature with the DXT encoder, and raises if set, because silently
    dropping an alpha channel that someone asked for is how a texture ends up
    looking solid when it should be a decal.
    """
    if alpha:
        raise BlockEncodeError(
            "ETC1 carries no alpha; the game's .etc pages are ETC1, so an alpha "
            "page has to stay in the DXT family")
    if width <= 0 or height <= 0:
        raise BlockEncodeError(f"bad dimensions {width}x{height}")
    rgba = _rgba(width, height, channels, pixels)
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    out = bytearray()
    for by in range(bh):
        for bx in range(bw):
            block = _block_pixels(rgba, width, height, bx, by)
            flat = _etc_block(block, 0)
            other = _etc_block(block, 1)
            out += flat[1] if flat[0] <= other[0] else other[1]
    return bytes(out)


# ---------------------------------------------------------------------------
# ATC
# ---------------------------------------------------------------------------
def _atc_pack_a(colour) -> int:
    return ((_clamp8(colour[0]) >> 3) << 10) | ((_clamp8(colour[1]) >> 3) << 5) \
        | (_clamp8(colour[2]) >> 3)


def _atc_pack_d(colour) -> int:
    return ((_clamp8(colour[0]) >> 3) << 11) | ((_clamp8(colour[1]) >> 2) << 5) \
        | (_clamp8(colour[2]) >> 3)


def _atc_palette(a: int, d: int) -> list:
    """The four colours ``_atc_colours`` would build, in the same order."""
    first = (_extend5((a >> 10) & 31), _extend5((a >> 5) & 31), _extend5(a & 31))
    last = (_extend5((d >> 11) & 31), _extend6((d >> 5) & 63), _extend5(d & 31))
    return [first,
            tuple((5 * first[i] + 3 * last[i]) // 8 for i in range(3)),
            tuple((3 * first[i] + 5 * last[i]) // 8 for i in range(3)),
            last]


def _atc_block(pixels) -> bytes:
    # The endpoints are the block's darkest and brightest pixels: the palette is
    # a straight line between them, so the two pixels furthest apart are the ones
    # that leave the least of the block outside the line.
    low = min(pixels, key=lambda p: p[2] * 299 + p[3] * 587 + p[4] * 114)
    high = max(pixels, key=lambda p: p[2] * 299 + p[3] * 587 + p[4] * 114)
    a = _atc_pack_a((low[2], low[3], low[4]))
    d = _atc_pack_d((high[2], high[3], high[4]))
    palette = _atc_palette(a, d)
    word = 0
    for x, y, r, g, b, _alpha in pixels:
        best = 0
        best_error = None
        for index, colour in enumerate(palette):
            dr = colour[0] - r
            dg = colour[1] - g
            db = colour[2] - b
            error = dr * dr + dg * dg + db * db
            if best_error is None or error < best_error:
                best_error = error
                best = index
        word |= best << (2 * ((y << 2) | x))
    return (bytes([a & 0xFF, (a >> 8) & 0xFF, d & 0xFF, (d >> 8) & 0xFF])
            + word.to_bytes(4, "little"))


def encode_atc(width: int, height: int, channels: int, pixels: bytes, *,
               alpha: bool = False) -> bytes:
    """Raw ATC RGB block data for a picture (top-down, ``channels`` per pixel).

    ATC has three variants - plain RGB, explicit alpha and interpolated alpha -
    and the game's ``.atc`` pages are the plain one, so this writes that and
    refuses the other two rather than writing a file whose fourcc claims an alpha
    channel the bytes do not carry.
    """
    if alpha:
        raise BlockEncodeError(
            "the game's .atc pages are ATC RGB with no alpha; an alpha page has "
            "to stay in the DXT family")
    if width <= 0 or height <= 0:
        raise BlockEncodeError(f"bad dimensions {width}x{height}")
    rgba = _rgba(width, height, channels, pixels)
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    out = bytearray()
    for by in range(bh):
        for bx in range(bw):
            out += _atc_block(_block_pixels(rgba, width, height, bx, by))
    return bytes(out)


# ---------------------------------------------------------------------------
# headers
# ---------------------------------------------------------------------------
def header_etc(width: int, height: int) -> bytes:
    """A 128 byte DDS header carrying the ``ETC `` fourcc."""
    from .ddsencode import header

    return header(width, height, alpha=False, fourcc=b"ETC ")


def header_atc(width: int, height: int) -> bytes:
    """A 128 byte DDS header carrying the ``ATC `` fourcc."""
    from .ddsencode import header

    return header(width, height, alpha=False, fourcc=b"ATC ")


# ---------------------------------------------------------------------------
# self test
# ---------------------------------------------------------------------------
def selftest(depot: str, pages=()) -> int:
    """Encode, decode and compare, for both families; returns the problems found.

    ``pages`` defaults to the four pages the depot keeps in all four families
    under ``gui_assets/960x640``.  The comparison is against the DXT copy of the
    same page, which is what makes this a real check: a block encoder that is
    merely self consistent (encodes and decodes with the same mistake) would pass
    a round trip against itself.
    """
    import os

    from . import ddsdecode, etcdecode, texport

    if not pages:
        base = os.path.join(depot, "gui_assets", "960x640")
        pages = [os.path.join(base, "splash", "loading", "sprites_0"),
                 os.path.join(base, "common", "manufacturer_logos", "sprites_0")]
    problems = 0
    for stem in pages:
        dxt = stem + ".dxt.dds.z"
        if not os.path.isfile(dxt):
            print(f"  {os.path.basename(stem):40s} no DXT copy, skipped")
            continue
        width, height, channels, want = ddsdecode.decode(
            texport.payloads(dxt)[0])
        for label, encode, header, decode in (
                ("ETC1", encode_etc, header_etc, etcdecode.decode_etc),
                ("ATC", encode_atc, header_atc, etcdecode.decode_atc)):
            body = encode(width, height, channels, want)
            blob = header(width, height) + body
            got_w, got_h, got_c, got = decode(blob[128:], width, height)
            total = 0
            count = 0
            for i in range(0, len(want), 4):
                for c in range(3):
                    total += abs(want[i + c] - got[i + c])
                    count += 1
            mean = total / max(1, count)
            print(f"  {label:5s} {os.path.basename(stem):34s} "
                  f"{width}x{height} mean difference {mean:.2f}")
            if mean > 8.0:
                print(f"        {label} is too far off the DXT copy")
                problems += 1
    return problems
