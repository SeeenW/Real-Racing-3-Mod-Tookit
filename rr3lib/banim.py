"""RR3 ``.banim`` (binary animation) reader.

Reverse engineered from the retail assets - there is no public specification.

Container layout, little endian::

    u32  magic          0x7F7F00 | variant     variant seen: 0x00 0x01 0x10 0x11
                                               (magic high half 0x7F7F00, the third
                                                byte is 0x7F in most files and
                                                0x00 in a few; both occur)
    u32  version        ONLY when variant & 0x10, always 3 so far
    u32  fieldA         always 30 in every sampled file (meaning unknown)
    u32  numTracks      15 = full driver rig, 46 = track/cinematic, 3 = rear wing
    f32  durationMs     e.g. 1980.0, 1485.0
    u32  dataOffset     first keyframe byte; == headerSize + numTracks * 116

    numTracks x track record (116 bytes = 29 u32):
        u32  trackIndex            variant with 0x10 stores trackIndex << 16
        x14  u32 numKeys, u32 startKey      (unused slots are (0, endKey))

    keyframe data: ``totalKeys`` x (f32 timeMs, f32 value), 8 bytes per key.
    startKey is a *global* key index across the whole file, so track 1 starts
    where track 0 ended.  Times restart at 0 inside every curve, therefore they
    are not monotonic in the file.

Optional per-track trailer (present on most files)::

    u32  n                       normally == numTracks
    n x 8 bytes                  meaning unknown, dumped raw

Optional event name table (comes last)::

    u32  nameCount
    nameCount x (u32 lengthIncludingNUL, bytes)

The reader validates that the key data + trailer lands exactly on the event
name table or on EOF.  If it does not, the file is marked
``layout="structural"`` and the leftover bytes are dumped instead of being
silently reinterpreted.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

#: one raw rotation unit, converted to degrees (raw / 32768 rad)
DEG_PER_RAW = 180.0 / 32768.0   # 32768 counts = 180 deg

TRACK_RECORD_BYTES = 116
TRACK_RECORD_WORDS = 29
PAIRS_PER_TRACK = 14
KEY_BYTES = 8


class BanimError(Exception):
    pass


@dataclass
class Curve:
    index: int
    num_keys: int
    start_key: int
    end_key: int = 0


@dataclass
class Track:
    index: int
    index_raw: int
    curves: list[Curve] = field(default_factory=list)

    @property
    def key_count(self) -> int:
        return max((c.end_key for c in self.curves), default=0)

    @property
    def first_key(self) -> int:
        used = [c.start_key for c in self.curves if c.num_keys]
        return min(used) if used else 0


@dataclass
class Banim:
    path: Path
    size: int
    magic: int
    variant: int
    version: int | None
    field_a: int
    num_tracks: int
    duration_ms: float
    data_offset: int
    header_size: int
    tracks: list[Track] = field(default_factory=list)
    keys: list[tuple[float, float]] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    trailer_words: list[int] = field(default_factory=list)
    trailer_offset: int = 0
    trailer_pad: int = 0
    layout: str = "validated"
    key_end: int = 0
    names_offset: int = 0
    footer: bytes = b""
    properties: list[tuple[str, str]] = field(default_factory=list)
    leftover: bytes = b""
    warnings: list[str] = field(default_factory=list)

    @property
    def total_keys(self) -> int:
        return max((t.key_count for t in self.tracks), default=0)


def _name_table_len(d: bytes, pos: int) -> int:
    """Return the end offset if a plausible event name table starts at ``pos``."""
    if pos + 8 > len(d):
        return 0
    count = struct.unpack_from("<I", d, pos)[0]
    if not 0 < count <= 4096:
        return 0
    p = pos + 4
    for _ in range(count):
        if p + 4 > len(d):
            return 0
        ln = struct.unpack_from("<I", d, p)[0]
        if not 1 <= ln <= 512 or p + 4 + ln > len(d):
            return 0
        s = d[p + 4 : p + 4 + ln]
        if s[-1] != 0:
            return 0
        if any(b < 32 or b >= 127 for b in s[:-1]):
            return 0
        p += 4 + ln
    return p


def _skip_padding(d: bytes, pos: int, size: int) -> tuple[int, int]:
    """Skip zero padding, then report the event name table end (0 if none)."""
    p = pos
    while p < size and d[p] == 0 and p - pos < 4096:
        p += 1
    end = _name_table_len(d, p)
    return p - pos, (end if end else 0)


def _parse_string_pairs(reg: bytes) -> list[tuple[str, str]] | None:
    """Decode ``u32 n`` followed by ``n`` x (cstr, cstr), after zero padding.

    Returns ``None`` when the region does not fill exactly, so the caller can
    fall back to a raw dump instead of inventing structure.
    """
    p = 0
    while p < len(reg) and reg[p] == 0:
        p += 1
    if p + 4 > len(reg):
        return None
    n = struct.unpack_from("<I", reg, p)[0]
    if not 0 < n <= 256:
        return None
    p += 4
    out: list[tuple[str, str]] = []
    for _ in range(n):
        pair = []
        for _ in range(2):
            end = reg.find(b"\0", p)
            if end < 0:
                return None
            s = reg[p:end]
            if any(b < 32 or b >= 127 for b in s):
                return None
            pair.append(s.decode("ascii", "replace"))
            p = end + 1
        out.append((pair[0], pair[1]))
    if any(reg[p:]):
        return None
    return out


def load(path: str | Path) -> Banim:
    path = Path(path)
    return parse(path.read_bytes(), path)


def parse(d: bytes, path: str | Path = "<bytes>") -> Banim:
    """Parse banim bytes.  ``path`` is only recorded, for the reports."""
    path = Path(path)
    warnings: list[str] = []
    size = len(d)
    if size < 20:
        raise BanimError("file too small for a .banim container")

    magic = struct.unpack_from("<I", d, 0)[0]
    if (magic & 0xFFFF0000) != 0x7F7F0000:
        raise BanimError(f"not a RR3 .banim (magic {magic:#010x})")
    variant = magic & 0xFF
    if (magic & 0xFF00) not in (0x7F00, 0x0000):
        warnings.append(f"unusual magic third byte: {magic:#010x}")

    pos = 4
    version = None
    if variant & 0x10:
        if pos + 4 > size:
            raise BanimError("truncated version field")
        version = struct.unpack_from("<I", d, pos)[0]
        pos += 4
    if pos + 16 > size:
        raise BanimError("truncated header")
    field_a, num_tracks = struct.unpack_from("<II", d, pos)
    duration, data_offset = struct.unpack_from("<fI", d, pos + 8)
    header_size = pos + 16

    if not 0 < num_tracks <= 4096:
        raise BanimError(f"implausible track count {num_tracks}")
    need = header_size + num_tracks * TRACK_RECORD_BYTES
    if need > size:
        raise BanimError(f"track table needs {need} bytes, file has {size}")
    if data_offset != need:
        warnings.append(
            f"dataOffset {data_offset} != header + track table ({need})"
        )
    if data_offset > size:
        raise BanimError(f"dataOffset {data_offset} is past EOF")

    tracks: list[Track] = []
    p = header_size
    for ti in range(num_tracks):
        w = struct.unpack_from("<%dI" % TRACK_RECORD_WORDS, d, p)
        p += TRACK_RECORD_BYTES
        raw = w[0]
        idx = raw >> 16 if raw > 0xFF and variant & 0x10 else raw
        if idx != raw:
            pass
        t = Track(index=idx, index_raw=raw)
        for k in range(PAIRS_PER_TRACK):
            nk, sk = w[1 + 2 * k], w[2 + 2 * k]
            t.curves.append(Curve(k, nk, sk, sk + nk))
        tracks.append(t)

    total_keys = max((t.key_count for t in tracks), default=0)
    key_end = data_offset + total_keys * KEY_BYTES
    if key_end > size:
        warnings.append(
            f"track table claims {total_keys} keys ({total_keys * KEY_BYTES} bytes) "
            f"but only {size - data_offset} bytes follow dataOffset"
        )
        key_end = size
        total_keys = (size - data_offset) // KEY_BYTES
        layout = "structural"
    else:
        layout = "validated"

    # --- event name table (last thing in the file) ----------------------
    names_offset = 0
    names: list[str] = []
    footer = b""
    properties: list[tuple[str, str]] = []
    nl = _name_table_len(d, key_end)
    if not nl:
        p = key_end
        while p + 8 <= size:
            if _name_table_len(d, p) == size:
                nl = size
                names_offset = p
                footer = d[key_end:p]
                break
            p += 1
    if nl:
        if not names_offset:
            names_offset = key_end
        cnt = struct.unpack_from("<I", d, names_offset)[0]
        q = names_offset + 4
        for _ in range(cnt):
            ln = struct.unpack_from("<I", d, q)[0]
            names.append(d[q + 4 : q + 4 + ln].split(b"\0")[0].decode("utf-8", "replace"))
            q += 4 + ln
    elif key_end != size:
        footer = d[key_end:size]

    # --- optional per-track trailer -------------------------------------
    # Observed shapes, always directly after the key data:
    #   u32 n + n*4 bytes    (n == numTracks, the usual case)
    #   u32 n + n*8 bytes    (the rear-wing style file)
    # The block is followed by zero padding, sometimes by a small string
    # property block, and then by the event name table or EOF.
    trailer_offset = key_end
    trailer_words: list[int] = []
    trailer_pad = 0
    region = footer
    if layout == "validated" and len(region) >= 4:
        n = struct.unpack_from("<I", region, 0)[0]
        for entry_words in (1, 2):
            if not 0 < n <= 4096:
                break
            used = 4 + n * 4 * entry_words
            if used > len(region):
                continue
            pad = 0
            while 4 + n * 4 * entry_words + pad < len(region) and region[used + pad] == 0:
                pad += 1
            rest = region[used + pad :]
            if not rest or _parse_string_pairs(rest) is not None:
                trailer_words = list(
                    struct.unpack_from("<%dI" % (n * entry_words), region, 4)
                )
                trailer_pad = pad
                region = rest
                break
    if region:
        props = _parse_string_pairs(region)
        if props is not None:
            properties = props
        elif layout == "validated":
            warnings.append(
                f"{len(region)} bytes after the key data are not decoded "
                "(dumped raw)"
            )
    footer = region

    if layout == "validated" and not nl and key_end != size and not properties:
        if not trailer_words:
            warnings.append(
                f"{size - key_end} bytes after the key data do not form a name "
                "table"
            )
            layout = "structural"

    keys: list[tuple[float, float]] = []
    nkeys = min(total_keys, max(0, (trailer_offset - data_offset) // KEY_BYTES))
    if nkeys:
        vals = struct.unpack_from("<%df" % (nkeys * 2), d, data_offset)
        keys = list(zip(vals[0::2], vals[1::2]))
    elif layout == "validated":
        warnings.append("no keyframe data (0 keys)")

    leftover = b""
    if layout != "validated":
        leftover = d[trailer_offset:trailer_offset + 4096]
        if size - trailer_offset > 4096:
            warnings.append("leftover region truncated to 4096 bytes")

    b = Banim(
        path=path,
        size=size,
        magic=magic,
        variant=variant,
        version=version,
        field_a=field_a,
        num_tracks=num_tracks,
        duration_ms=duration,
        data_offset=data_offset,
        header_size=header_size,
        tracks=tracks,
        keys=keys,
        names=names,
        trailer_words=trailer_words,
        trailer_offset=trailer_offset,
        trailer_pad=trailer_pad,
        layout=layout,
        key_end=key_end,
        names_offset=names_offset,
        footer=footer,
        properties=properties,
        leftover=leftover,
        warnings=warnings,
    )
    if layout == "validated":
        for t in tracks:
            for c in t.curves:
                if c.num_keys and c.end_key > len(keys):
                    warnings.append(
                        f"track {t.index} curve {c.index} points past the keys"
                    )
                    break
    return b


# --------------------------------------------------------------------------
# textual report
# --------------------------------------------------------------------------


def format_report(b: Banim, max_keys: int = 0, per_curve: bool = True) -> str:
    out: list[str] = []
    a = out.append
    a("# RR3 .banim dump")
    a(f"file: {b.path}")
    a(f"bytes: {b.size}")
    a(f"magic: {b.magic:#010x}  variant: {b.variant:#04x}")
    a(f"version: {b.version if b.version is not None else '(absent)'}")
    a(f"fieldA: {b.field_a}")
    a(f"numTracks: {b.num_tracks}")
    a(f"durationMs: {b.duration_ms:g}")
    a(f"dataOffset: {b.data_offset} ({b.data_offset:#x})")
    a(f"headerSize: {b.header_size}")
    a(f"trackRecordBytes: {TRACK_RECORD_BYTES}")
    a(f"layout: {b.layout}")
    a(f"totalKeys: {b.total_keys}  (8 bytes each -> {b.total_keys * 8} bytes)")
    a(f"keyRange: {b.data_offset:#x}..{b.key_end:#x}")
    a("")
    a("track table (29 u32 per track: index then 14 x (numKeys, startKey)):")
    for t in b.tracks:
        a(
            f"  track {t.index:3d}  rawIndexWord={t.index_raw:#010x}  "
            f"keyRange=[{t.first_key}, {t.key_count})"
        )
        for c in t.curves:
            if c.num_keys == 0 and c.start_key == 0:
                continue
            a(
                f"    curve {c.index:2d}: numKeys={c.num_keys:5d} "
                f"startKey={c.start_key:6d} endKey={c.end_key:6d}"
            )
    if b.trailer_words:
        a("")
        n = len(b.trailer_words)
        esz = 8 if n > b.num_tracks else 4
        a(
            f"per-track trailer at {b.trailer_offset:#x}: u32 n={n} then "
            f"{n} x {esz} bytes ({n * esz} bytes), zero padding after: {b.trailer_pad}"
        )
        for i in range(n):
            w0 = b.trailer_words[i]
            f0 = struct.unpack("<f", struct.pack("<I", w0))[0]
            a(f"  [{i:3d}] {w0:#010x}   as f32 {f0:14.7g}")
    a("")
    if b.keys:
        a("")
        a("channel summary  (channel c = curves 2c and 2c+1 inside a track;")
        a("                  ch0..2 = position, ch3..5 = rotation)")
        a("  deg = raw * 180 / 32768 (32768 counts = 180 degrees)")
        a("  pos is listed for BOTH observed scales: /32768 (driver rig joints)")
        a("  and /65536 (vehicle aero pivots); the file itself stores neither unit")
        for t in b.tracks:
            a(f"  track {t.index}:")
            for ch in range(6):
                prim = [c for c in t.curves if c.index == 2 * ch and c.num_keys]
                cs = prim or [c for c in t.curves
                              if (c.index // 2) == ch and c.num_keys]
                if not cs:
                    continue
                ts: list[float] = []
                vs: list[float] = []
                for c in cs:
                    for k in range(c.start_key, c.end_key):
                        if k < len(b.keys):
                            ts.append(b.keys[k][0])
                            vs.append(b.keys[k][1])
                if not vs:
                    continue
                lo, hi = min(vs), max(vs)
                axis = f"pos {'xyz'[ch]}" if ch < 3 else f"rot {'xyz'[ch - 3]}"
                if ch < 3:
                    extra = (
                        f"{lo / 32768.0:9.4f}..{hi / 32768.0:9.4f} m @1/32768"
                        f"   {lo / 65536.0:9.4f}..{hi / 65536.0:9.4f} m @1/65536"
                    )
                else:
                    extra = f"{lo * DEG_PER_RAW:8.2f}..{hi * DEG_PER_RAW:8.2f} deg"
                a(
                    f"    ch{ch} {axis}  keys={len(vs):5d}  "
                    f"t={min(ts):7.1f}..{max(ts):7.1f} ms  "
                    f"raw {lo:12.1f}..{hi:12.1f}   {extra}"
                )
    if b.keys:
        a("")
        a(f"keyframes ({len(b.keys)} keys, (timeMs, raw value); rotation curves")
        a("also show deg = raw / 32768 rad converted to degrees):")
        shown = 0
        stop = False
        for t in b.tracks:
            if stop:
                break
            for c in t.curves:
                if c.num_keys == 0:
                    continue
                a(
                    f"  track {t.index} curve {c.index}: "
                    f"{c.num_keys} keys [{c.start_key}..{c.end_key})"
                )
                if per_curve:
                    for k in range(c.start_key, c.end_key):
                        if k >= len(b.keys):
                            break
                        if max_keys and shown >= max_keys:
                            a(f"    ... {len(b.keys) - shown} more keys not listed")
                            stop = True
                            break
                        tm, v = b.keys[k]
                        raw = struct.unpack("<I", struct.pack("<f", v))[0]
                        suffix = ""
                        if (c.index // 2) >= 3:
                            suffix = f"  deg={v * DEG_PER_RAW:9.3f}"
                        a(f"    [{k:6d}] t={tm:10.4f}  v={v:14.6f}{suffix}"
                          f"  vBits={raw:#010x}")
                        shown += 1
                if max_keys and shown >= max_keys:
                    stop = True
                    break
    else:
        a("no keyframe data decoded")
    if b.properties:
        a("")
        a("footer properties (u32 count then count x (name, value)):")
        for i, (k, v) in enumerate(b.properties):
            a(f"  [{i:2d}] {k!r} = {v!r}")
    if b.footer and not b.properties:
        a("")
        a(f"undecoded footer: {len(b.footer)} bytes (raw)")
        base = b.key_end + len(b.footer)
        for o in range(0, len(b.footer), 16):
            chunk = b.footer[o : o + 16]
            a(f"  {o:08x}  {chunk.hex(' ')}")
    if b.names:
        a("")
        a(f"event names: {len(b.names)} (at {b.names_offset:#x})")
        for i, n in enumerate(b.names):
            a(f"  [{i:2d}] {n}")
    if b.leftover:
        a("")
        a(f"unparsed region: {len(b.leftover)} bytes shown")
        for o in range(0, len(b.leftover), 16):
            chunk = b.leftover[o : o + 16]
            a(f"  {b.key_end + o:#08x}  {chunk.hex(' ')}")
    if b.warnings:
        a("")
        a("warnings:")
        for w in b.warnings:
            a(f"  ! {w}")
    return "\n".join(out) + "\n"
