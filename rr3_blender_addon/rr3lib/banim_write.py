"""RR3 ``.banim`` writer: build an animation clip from curves, or edit one.

The reader is :mod:`rr3lib.banim`.  This module mirrors it and, like the
``.points`` writer, round-trips every shipped file byte for byte
(:func:`selftest`) so a rebuilt clip is indistinguishable from the original.

WHAT A ``.banim`` IS
--------------------
A flat list of ``(time_ms, value)`` pairs plus a table saying which slice of
that list belongs to which curve of which track::

    u32 magic        0x7F7F00 | variant        (0x00, 0x01, 0x10, 0x11 seen)
    u32 version      only when variant & 0x10, always 3
    u32 fieldA       always 30
    u32 numTracks
    f32 durationMs
    u32 dataOffset   == headerSize + numTracks * 116

    numTracks x 116 bytes:
        u32 trackIndex            (variant 0x10 stores trackIndex << 16)
        14 x (u32 numKeys, u32 startKey)      startKey is a GLOBAL key index

    keys: totalKeys x (f32 timeMs, f32 value)

    optional trailer:   u32 n + n x 8 bytes     (unknown, copied verbatim)
    optional names:     u32 n + n x (u32 len, bytes)   AE_* event names
    optional props:     u32 n + n x (cstr, cstr)

The 14 curve slots per track are laid out as **two interleaved curves per
channel**, 6 channels in total::

    slot 0, 1   channel 0   position X
    slot 2, 3   channel 1   position Y
    slot 4, 5   channel 2   position Z
    slot 6, 7   channel 3   rotation X
    slot 8, 9   channel 4   rotation Y
    slot 10,11  channel 5   rotation Z
    slot 12,13  unused (0 keys)

The shipped files use two different key densities in the pair (the McLaren P1
has 61 keys in the even slot and 120 in the odd one), so the writer keeps both
slots independent - build a clip with :func:`single_curve_track` when you do not
care and want the simple one-curve-per-channel form.

UNITS
-----
* channels 0..2 (position)  raw = metres * 65536
* channels 3..5 (rotation)  raw = radians * 32768 / pi  (32768 == 180 deg)
* time is milliseconds

Axes are animation space ``(x right, y forward, z up)``, which is *not* the
mesh space ``(x right, y up, z forward)``; :data:`rr3lib.parts.ANIM_TO_MODEL`
does the swap.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

from . import banim as banimlib

#: metres -> raw position units.
POS_SCALE = 65536.0
#: radians -> raw rotation units.
ROT_SCALE = 32768.0 / math.pi
#: raw rotation units -> degrees.
DEG_PER_RAW = banimlib.DEG_PER_RAW

CHANNELS = ("pos_x", "pos_y", "pos_z", "rot_x", "rot_y", "rot_z")
CHANNEL_UNITS = ("m", "m", "m", "deg", "deg", "deg")


class BanimWriteError(Exception):
    pass


# ---------------------------------------------------------------- conversion
def metres_to_raw(v: float) -> float:
    return v * POS_SCALE


def raw_to_metres(v: float) -> float:
    return v / POS_SCALE


def radians_to_raw(v: float) -> float:
    return v * ROT_SCALE


def raw_to_radians(v: float) -> float:
    return v / ROT_SCALE


def channel_to_raw(channel: int, value: float) -> float:
    """Convert a user facing value (metres or degrees) to the stored raw unit."""
    if channel < 3:
        return value * POS_SCALE
    return math.radians(value) * ROT_SCALE


def channel_from_raw(channel: int, raw: float) -> float:
    """Convert a stored raw unit back to metres (ch 0..2) or degrees (ch 3..5)."""
    if channel < 3:
        return raw / POS_SCALE
    return raw * DEG_PER_RAW


# --------------------------------------------------------------------- model
@dataclass
class CurveData:
    """One curve: a list of ``(time_ms, value)`` in *user* units.

    ``channel`` is 0..5 (position XYZ, rotation XYZ); ``slot`` is 0 or 1 and
    picks which of the two curves of that channel this is.  Most files only use
    slot 0, but the shipped McLaren P1 populates both.
    """

    channel: int
    keys: list[tuple[float, float]] = field(default_factory=list)
    slot: int = 0

    def add(self, time_ms: float, value: float) -> None:
        self.keys.append((float(time_ms), float(value)))

    def sample(self, time_ms: float) -> float:
        """Linear interpolation, clamped at both ends."""
        if not self.keys:
            return 0.0
        ks = self.keys
        if time_ms <= ks[0][0]:
            return ks[0][1]
        if time_ms >= ks[-1][0]:
            return ks[-1][1]
        lo, hi = 0, len(ks) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if ks[mid][0] <= time_ms:
                lo = mid
            else:
                hi = mid
        t0, v0 = ks[lo]
        t1, v1 = ks[hi]
        if t1 == t0:
            return v0
        return v0 + (v1 - v0) * (time_ms - t0) / (t1 - t0)


@dataclass
class TrackData:
    """One animated part: up to 6 channels x 2 curve slots."""

    index: int = 0
    curves: list[CurveData] = field(default_factory=list)
    #: The ``trackIndex`` word exactly as stored.  ``None`` means "derive it",
    #: which is ``index`` for a plain file and ``index << 16`` when the variant
    #: has the 0x10 bit.  Kept so an edit round-trips byte for byte.
    index_raw: int | None = None

    def curve(self, channel: int, slot: int = 0) -> CurveData:
        for c in self.curves:
            if c.channel == channel and c.slot == slot:
                return c
        c = CurveData(channel=channel, slot=slot)
        self.curves.append(c)
        return c

    def set_linear(self, channel: int, start: float, end: float,
                   keys: int = 2, slot: int = 0) -> CurveData:
        """Replace one channel with a straight ramp ``start -> end``."""
        c = self.curve(channel, slot)
        c.keys = []
        if keys <= 1:
            c.keys = [(0.0, start)]
            return c
        for i in range(keys):
            c.keys.append((i / (keys - 1.0), start + (end - start) * (i / (keys - 1.0))))
        return c

    def constant(self, channel: int, value: float, slot: int = 0) -> CurveData:
        c = self.curve(channel, slot)
        c.keys = [(0.0, value)]
        return c

    def channels(self) -> dict[int, list[CurveData]]:
        out: dict[int, list[CurveData]] = {}
        for c in self.curves:
            out.setdefault(c.channel, []).append(c)
        for lst in out.values():
            lst.sort(key=lambda c: c.slot)
        return out


@dataclass
class BanimDoc:
    """A whole ``.banim`` file."""

    tracks: list[TrackData] = field(default_factory=list)
    duration_ms: float = 0.0
    variant: int = 0x00
    #: Only written when ``variant & 0x10``; shipped files use 3, but 1 and 2
    #: also appear, so it is kept rather than assumed.
    version: int = 3
    field_a: int = 30
    #: The ``magic`` word exactly as stored.  The third byte is 0x7F in most
    #: files but 0x00 in a handful, and the low byte is the variant, so it
    #: cannot be derived from the variant alone.  ``None`` means 0x7F7F7F00|variant.
    magic: int | None = None
    #: Everything between the key data and the event-name table, verbatim:
    #: the per-track trailer, its zero padding and the property block.  Its
    #: layout is not fully understood, so edits keep it and new files omit it.
    tail_raw: bytes = b""
    #: AE_* event names, usually only on cinematic clips
    names: list[str] = field(default_factory=list)
    properties: list[tuple[str, str]] = field(default_factory=list)

    # ---- convenience ---------------------------------------------------
    def add_track(self, index: int | None = None) -> TrackData:
        t = TrackData(index=len(self.tracks) if index is None else index)
        self.tracks.append(t)
        return t

    def resolve_duration(self) -> float:
        """The longest key time, used when ``duration_ms`` is left at 0."""
        best = 0.0
        for t in self.tracks:
            for c in t.curves:
                if c.keys:
                    best = max(best, c.keys[-1][0])
        return best


# ------------------------------------------------------------------ building
def _scale_time(keys, factor: float):
    return [(t * factor, v) for t, v in keys]


def build(doc: BanimDoc) -> bytes:
    """Serialise a :class:`BanimDoc`."""
    variant = doc.variant & 0xFF
    has_version = bool(variant & 0x10)
    # The shipped files use 0x7F7F7F00 | variant, not 0x7F7F0000 | variant: the
    # third byte is 0x7F too.  All 53 rear-wing files, all 25 driver rigs and
    # the 385 cinematic files carry it; only one track file in the whole depot
    # (Tracks/Laguna_Seca/.../cs_tutorial_orbit.banim) has the 0x00 third byte,
    # and the engine will not play a wing animation without the 0x7F one.
    magic = doc.magic if doc.magic is not None else (0x7F7F7F00 | variant)

    # ---- lay out the global key list, track by track -------------------
    # Keys are packed back to back in track order and the curve slots point at
    # them with a global index; empty slots point at the *next* key, which is
    # what the shipped files do (see the (0, 1) pairs in any track).
    key_list: list[tuple[float, float]] = []
    table: list[list[tuple[int, int]]] = []   # per track: 14 x (numKeys, startKey)
    for track in doc.tracks:
        pairs: list[tuple[int, int]] = []
        by_channel = track.channels()
        for slot_index in range(14):
            ch = slot_index // 2
            sub = slot_index % 2
            cands = by_channel.get(ch, [])
            cur = next((c for c in cands if c.slot == sub), None)
            if cur is None or not cur.keys:
                pairs.append((0, len(key_list)))
                continue
            start = len(key_list)
            for t, v in cur.keys:
                key_list.append((float(t), channel_to_raw(ch, v)))
            pairs.append((len(cur.keys), start))
        table.append(pairs)

    duration = float(doc.duration_ms) or doc.resolve_duration()

    header = bytearray()
    header += struct.pack("<I", magic)
    if has_version:
        header += struct.pack("<I", doc.version)
    header += struct.pack("<II", doc.field_a, len(doc.tracks))
    header += struct.pack("<fI", duration, 0)   # dataOffset patched below

    header_size = len(header)
    data_offset = header_size + len(doc.tracks) * banimlib.TRACK_RECORD_BYTES
    struct.pack_into("<I", header, header_size - 4, data_offset)

    out = bytearray(header)
    for track, pairs in zip(doc.tracks, table):
        if track.index_raw is not None:
            raw_index = track.index_raw
        elif has_version:
            raw_index = track.index << 16
        else:
            raw_index = track.index
        out += struct.pack("<I", raw_index)
        for n, s in pairs:
            out += struct.pack("<II", n, s)

    for t, v in key_list:
        out += struct.pack("<ff", t, v)

    if doc.tail_raw:
        out += doc.tail_raw

    if doc.names:
        out += struct.pack("<I", len(doc.names))
        for n in doc.names:
            b = n.encode("ascii", "replace") + b"\0"
            out += struct.pack("<I", len(b)) + b

    return bytes(out)


def save(doc: BanimDoc, path: str) -> int:
    blob = build(doc)
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)


# ------------------------------------------------------------------- reading
def from_banim(b: banimlib.Banim, raw: bytes | None = None) -> BanimDoc:
    """Convert a parsed file into an editable document (metres / degrees).

    ``raw`` is the original file bytes; when given, everything between the key
    data and the event-name table (per-track trailer, zero padding, property
    block) is copied verbatim so an edit round-trips byte for byte.
    """
    tail = b""
    if raw is not None and b.layout == "validated":
        end = b.names_offset or len(raw)
        if 0 <= b.key_end <= end <= len(raw):
            tail = raw[b.key_end:end]
    doc = BanimDoc(duration_ms=b.duration_ms, variant=b.variant,
                   version=b.version or 3, field_a=b.field_a, magic=b.magic,
                   tail_raw=tail, names=list(b.names),
                   properties=list(b.properties))
    for tr in b.tracks:
        t = doc.add_track(tr.index)
        t.index_raw = tr.index_raw
        for slot_index, cur in enumerate(tr.curves):
            if not cur.num_keys:
                continue
            ch = slot_index // 2
            sub = slot_index % 2
            vals = b.keys[cur.start_key:cur.start_key + cur.num_keys]
            c = t.curve(ch, sub)
            c.keys = [(float(tm), channel_from_raw(ch, raw_v)) for tm, raw_v in vals]
    return doc


def load(path: str) -> BanimDoc:
    raw = open(path, "rb").read()
    return from_banim(banimlib.load(path), raw)


# --------------------------------------------------------------- authoring
def single_curve_track(index: int = 0, keys: int = 2) -> TrackData:
    """A track with one curve per channel (slot 0), ready to fill in."""
    t = TrackData(index=index)
    for ch in range(6):
        t.curve(ch, 0)
    return t


def simple_wing(duration_ms: float = 990.0, *,
                start_pos=(0.0, 0.0, 0.0), end_pos=(0.0, 0.0, 0.0),
                start_deg=(0.0, 0.0, 0.0), end_deg=(0.0, 0.0, 0.0),
                keys: int = 2, tracks: int = 1,
                variant: int = 0x00) -> BanimDoc:
    """A minimal aero clip: every track ramps from the start to the end pose.

    This is the shape the game needs for active aero - a ``_wing.banim`` whose
    tracks move the wing parts from the rest pose to the deployed pose.  The
    paired ``_animations.xml`` then says which frame range plays when.
    """
    doc = BanimDoc(duration_ms=duration_ms, variant=variant)
    for i in range(tracks):
        t = single_curve_track(i, keys)
        for ch in range(3):
            t.set_linear(ch, start_pos[ch], end_pos[ch], keys)
        for ch in range(3):
            t.set_linear(3 + ch, start_deg[ch], end_deg[ch], keys)
        doc.tracks.append(t)
    return doc


def retime(doc: BanimDoc, factor: float) -> BanimDoc:
    """Scale every key time and the duration by ``factor`` (in place)."""
    for t in doc.tracks:
        for c in t.curves:
            c.keys = [(tm * factor, v) for tm, v in c.keys]
    doc.duration_ms = doc.resolve_duration()
    return doc


def clamp_to(doc: BanimDoc, duration_ms: float) -> BanimDoc:
    """Clip every curve to ``duration_ms``, adding an interpolated end key."""
    for t in doc.tracks:
        for c in t.curves:
            if not c.keys:
                continue
            if c.keys[0][0] > duration_ms:
                c.keys = [(0.0, c.keys[0][1])]
                continue
            out = [(tm, v) for tm, v in c.keys if tm <= duration_ms]
            last_t = out[-1][0]
            if last_t < duration_ms:
                out.append((duration_ms, c.sample(duration_ms)))
            c.keys = out
    doc.duration_ms = duration_ms
    return doc


def summary(doc: BanimDoc) -> str:
    """One line per track: the start and end pose of every channel."""
    lines = [f"tracks={len(doc.tracks)}  duration={doc.duration_ms:g} ms  "
             f"variant={doc.variant:#04x}"]
    for t in doc.tracks:
        bits = []
        for ch, curves in sorted(t.channels().items()):
            c = curves[0]
            if not c.keys:
                continue
            a = c.keys[0][1]
            b = c.keys[-1][1]
            unit = CHANNEL_UNITS[ch]
            bits.append(f"{CHANNELS[ch]} {a:+.4g}->{b:+.4g}{unit}"
                        f"({len(c.keys)}k)")
        lines.append(f"  track {t.index}: " + "; ".join(bits))
    return "\n".join(lines)


# ----------------------------------------------------------------- self test
def selftest(depot: str | None = None, limit: int = 0) -> int:
    """Round-trip every shipped ``.banim`` and report mismatches."""
    import glob
    import os

    if not depot:
        depot = os.environ.get("RR3_DEPOT", "")
    if not depot or not os.path.isdir(depot):
        print("banim_write selftest: no depot (set RR3_DEPOT)")
        return 2
    files = sorted(glob.glob(os.path.join(depot, "**", "*.banim"), recursive=True))
    if limit:
        files = files[:limit]
    bad = 0
    for p in files:
        raw = open(p, "rb").read()
        try:
            doc = load(p)
            back = build(doc)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {os.path.basename(p)}: {exc}")
            bad += 1
            continue
        if back != raw:
            n = min(len(back), len(raw))
            at = next((i for i in range(n) if back[i] != raw[i]), n)
            print(f"FAIL {os.path.basename(p)}: {len(raw)} -> {len(back)}, "
                  f"first diff at {at}")
            bad += 1
    print(f"banim_write selftest: {len(files)} files, {bad} failures")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
