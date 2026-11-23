"""Per car spec files and the small fixed-record vehicle tables.

Three things live here:

``Spec``
    ``vehicles/data/<id>_<name>.bin.nct`` - one record per car, ~870 bytes of
    mixed numbers and strings, containing the physics/audio/display data.  The
    format is "a stream of length prefixed tokens", some of which are strings
    and some are raw little endian words.  We do not know what most of them
    mean, so this class only exposes the handful that have been verified by
    experiment, and keeps everything else byte exact.

``Cardesc``
    ``cardesc.list.nct`` - the master list, just ``u32 len + "<id>_<name>.bin"``
    repeated 540 times, sorted by id.

``FixedTable``
    ``suspensionbehaviour.suspensiondata.nct`` (140 byte records) and
    ``cardamagethresholds.damage.nct`` (116 byte records).  Both are
    "u32 id + N floats" and both are indexed by car id.

WHY TOKEN STREAMS
-----------------
The spec is not a struct: a string token is ``u32 len + chars`` and a numeric
token is just ``u32``, so a parser cannot tell them apart without heuristics.
The heuristic used here is the one that has worked on all 540 shipped files:
if the next four bytes read as a small length (1..200) and the bytes after it
are all printable ASCII, it is a string.  Round tripping every shipped spec
byte for byte is asserted in :func:`selftest`.
"""

from __future__ import annotations

import os
import re
import struct

from . import nct

SPEC_DIR = "vehicles/data"
CARDESC = "vehicles/data/cardesc.list.nct"
SUSPENSION = "vehicles/data/suspensionbehaviour.suspensiondata.nct"
DAMAGE = "vehicles/data/cardamagethresholds.damage.nct"

#: Legacy token index of the appearance record id.
#:
#: WRONG ON MOST FILES - kept only as a last resort fallback.  The tokenizer
#: splits a string as ``u32 len`` + exactly ``len`` bytes, but the file pads
#: every string to a 4 byte boundary, so the padding shows up as extra zero
#: valued tokens.  The number of those depends on how long the car's strings
#: are, so the appearance id lands on a different token index in every car
#: (measured: 84..112, and index 86 is only right on 30 of 188 joinable specs).
#: Use :meth:`Spec.appearance_id` instead, which locates the field by shape.
TOKEN_APPEARANCE = 86
#: Token index of the display name key, e.g. ``CAR_NAME_LFA`` (also unreliable
#: for the same padding reason - use :meth:`Spec.display_name_key`).
TOKEN_DISPLAY_NAME = 105
#: Token index of the manufacturer key, e.g. ``CAR_MANUFACTURER_LEXUS``.
TOKEN_MANUFACTURER = 104

#: The flag that makes active aerodynamics deploy.  It must replace the empty
#: token in front of ``generic_race`` **in place** - inserting a token shifts
#: every later index and the engine then dereferences a null at +0x18.
AERO_FLAG = b"DeployWhenBraking"

#: Every behaviour token the shipped specs use, counted over all 540 of them.
#:
#: ``DeployWhenBraking`` (35 cars) lifts the wing on the brakes; 32 carry no
#: numbers and three add ``speed, speed`` (the speed the wing drops back at).
#: ``DeployAtSpeed`` (11) is the drag-reduction case: the wing flattens above a
#: speed and comes back above a lower one.  ``BrakeAndSpeedCombo`` (7) does
#: both, which is what the Senna, the Jesko and the Battistas use.
#: ``NascarAirBrake`` (42) is the NASCAR flap, which takes no numbers.
#:
#: The numbers are not interchangeable: ``BrakeAndSpeedCombo, 180, 170`` means
#: "flatten at 180, back at 170", so the first is always the higher one.
AERO_KINDS = (
    b"DeployWhenBraking",
    b"DeployAtSpeed",
    b"BrakeAndSpeedCombo",
    b"NascarAirBrake",
)

#: The behaviours that take two numbers after the name.
AERO_PARAMETRIC = (b"DeployAtSpeed", b"BrakeAndSpeedCombo")

#: Where the performance block sits, as fixed token indices.
#:
#: The first 35 tokens of every shipped spec are the same sequence of kinds -
#: MonkeyTool reads them positionally too (``kHead`` in ``nfsnl_rr3car.cpp`` is
#: ``"nnsssns" "nnnnnnnnnnnnn" "s" "sssnnnnssnnns" "s"``, which lands on exactly
#: these indices).  Nothing before the aspiration strings varies, so no search is
#: needed here; the fields that *do* move (the engine block, the price, the PR)
#: are found by shape in :meth:`Spec.stats`.
STAT_INDEX = {
    "car_class": 6,
    "weight_lb": 9,
    "top_speed": 10,
    "top_speed_max": 11,
    "accel": 14,
    "accel_max": 15,
    "braking": 16,
    "braking_max": 17,
    "grip": 18,
    "grip_max": 19,
}

#: Which of those are integers rather than floats.
_STAT_U32 = ("weight_lb", "top_speed", "top_speed_max")

#: The class string (``Race``/``Supercar``/``Prod``), also at a fixed index.
STAT_CLASS = 6

#: The drivetrain string (``RWD``/``AWD``/``FWD``/``RLY``), also fixed.
STAT_DRIVETRAIN = 20

#: Token index of the engine block, relative to the gear count.  MonkeyTool
#: anchors on the aspiration/layout strings and then reads ``+0`` gears,
#: ``+3`` final drive, ``+4`` power and so on; the count is found by scanning.
STAT_ENGINE_OFFSETS = {
    "gears": 0,
    "final_drive": 3,
    "power_hp": 4,
    "power_rpm": 5,
    "torque": 6,
    "torque_rpm": 7,
    "redline": 8,
    "limiter": 9,
    "shift_up": 10,
    "shift_down": 11,
}

#: A route key is a short name; anything longer is a mis-read offset.
_ROUTE_MAX = 48

#: The aspiration strings the game understands.  They are not free text: the
#: engine block is found *by* one of these, so an unknown value hides the whole
#: engine from every reader in this file.
ASPIRATIONS = (b"Nat", b"Turbo", b"Super", b"None", b"Electric", b"Hybrid")

#: The drivetrain layouts.  Same rule - ``_engine_index`` reads the token after
#: the aspiration and requires it to be at most two characters.
LAYOUTS = (b"F", b"M", b"R", b"FM")

#: The driven-wheel words, counted over the 541 shipped specs: ``RWD`` 443,
#: ``AWD`` 82, ``FWD`` 12 and ``RLY`` 3 (the three rally cars - the i20 WRC, the
#: Yaris WRC and the Puma Rally1 - which use their own handling model).  Unlike
#: :data:`LAYOUTS` this is *not* what the engine block is found by, so a wrong
#: value does not hide anything; it still changes how the car drives, so only
#: these four are offered.
DRIVETRAINS = (b"RWD", b"AWD", b"FWD", b"RLY")

#: The three strings the game's class filter uses, in the order its screen does.
CLASSES = (b"Race", b"Supercar", b"Prod")

#: Longest unlock string seen in the shipped files is 101 bytes; the limit is
#: loose on purpose, because the point is only to reject a runaway length.
_UNLOCK_MAX = 200

#: Token index of the engine-sound triple (accel, decel, idle).  Identical in all
#: 435 shipped specs that have one; the other 105 have no audio string at all.
STAT_SOUND = 21


def _sound_family(text: str) -> str:
    """``audio/Vehicles/v10_04/id_88_accel`` -> ``v10_04``."""
    parts = [p for p in text.split("/") if p]
    if len(parts) >= 3 and parts[0] == "audio" and parts[1] == "Vehicles":
        return parts[2]
    return ""


#: Which engine figures are integers rather than floats.
_ENGINE_U32 = ("gears", "torque", "power_rpm", "torque_rpm", "redline", "limiter",
               "shift_up", "shift_down")

#: Bounds for the writable engine figures.  Wide enough for any real car, narrow
#: enough that a typo is refused instead of producing a car that will not start.
ENGINE_LIMITS = {
    "final_drive": (0.5, 12.0),
    "power_hp": (10.0, 3000.0),
    "power_rpm": (500, 20000),
    "torque": (10, 3000),
    "torque_rpm": (500, 20000),
    "redline": (500, 20000),
    "limiter": (500, 20000),
    "shift_up": (500, 20000),
    "shift_down": (500, 20000),
}

_AERO_EMPTY = b"\x00\x00\x00\x00\x0c\x00\x00\x00generic_race"


def _generic_positions(plain: bytes) -> list:
    """Offsets of every length-prefixed ``generic_*`` string in ``plain``.

    Four spellings ship - ``generic_race`` (the usual one), ``generic_road``
    (Senna), ``generic_carb`` (Nevera, the Battistas) and ``generic_carbon``
    (everything with a carbon body).  The behaviour token always sits
    immediately in front of one of them, so the search is for the shape rather
    than for a fixed list of names.
    """
    out = []
    for m in re.finditer(rb"generic_[a-z]+", plain):
        at = m.start()
        if at < 4:
            continue
        if struct.unpack_from("<I", plain, at - 4)[0] != len(m.group(0)):
            continue
        out.append(at)
    return out


class SpecError(Exception):
    pass


# ---------------------------------------------------------------- token stream
def tokenize(data: bytes) -> list[list]:
    """Split a spec into ``[kind, offset, length, payload]`` tokens."""
    out: list[list] = []
    i = 0
    n = len(data)
    while i < n:
        if i + 4 <= n:
            ln = struct.unpack_from("<I", data, i)[0]
            if 1 <= ln <= 200 and i + 4 + ln <= n:
                chunk = data[i + 4:i + 4 + ln]
                if all(32 <= c < 127 for c in chunk):
                    out.append(["s", i, ln, chunk])
                    i += 4 + ln
                    continue
        if i + 4 > n:
            out.append(["n", i, None, data[i:]])
            break
        out.append(["n", i, None, data[i:i + 4]])
        i += 4
    return out


def detokenize(tokens) -> bytes:
    buf = bytearray()
    for kind, _off, _ln, payload in tokens:
        if kind == "s":
            buf += struct.pack("<I", len(payload)) + payload
        else:
            buf += payload
    return bytes(buf)


def word(tokens, index: int) -> int:
    """Read token ``index`` as a u32."""
    kind, _off, _ln, payload = tokens[index]
    if kind != "n" or len(payload) != 4:
        raise SpecError(f"token {index} is not a u32 word")
    return struct.unpack("<I", payload)[0]


def set_word(tokens, index: int, value: int) -> None:
    kind, _off, _ln, payload = tokens[index]
    if kind != "n" or len(payload) != 4:
        raise SpecError(f"token {index} is not a u32 word")
    tokens[index][3] = struct.pack("<I", value & 0xFFFFFFFF)


def set_string(tokens, index: int, value: bytes) -> None:
    kind, _off, _ln, payload = tokens[index]
    if kind != "s":
        raise SpecError(f"token {index} is not a string")
    tokens[index][3] = value


def find_string(tokens, value: bytes) -> list[int]:
    return [i for i, t in enumerate(tokens) if t[0] == "s" and t[3] == value]


def _string_after_manufacturer(raw: bytes) -> bytes | None:
    """The length-prefixed string that follows ``CAR_MANUFACTURER_*`` in ``raw``.

    Used to re-find the display-name token after :meth:`Spec.set_display_name`
    replaced its ``CAR_NAME_*`` key with a literal display string.  Returns None
    when the manufacturer key is missing (33 of the 540 shipped specs).
    """
    at = raw.find(b"CAR_MANUFACTURER_")
    if at < 0:
        return None
    end = raw.find(b"\x00", at)
    if end < 0:
        return None
    # the string's own length prefix sits 4 bytes before it; the next string
    # starts right after the manufacturer payload
    p = end + 1
    while p + 4 <= len(raw):
        ln = struct.unpack_from("<I", raw, p)[0]
        if 1 <= ln <= 200 and p + 4 + ln <= len(raw):
            chunk = raw[p + 4:p + 4 + ln]
            if all(32 <= c < 127 for c in chunk):
                return chunk
        p += 1
    return None


# ------------------------------------------------------- appearance id locator
# The appearance record id is a u32 that sits in a very recognisable hole in the
# token stream:
#
#     <printable ASCII string>  00 00 00 00  <id>  00 00 00 00 00 ...
#
# Its *token index* is not fixed, because the file pads every string to a four
# byte boundary while the tokenizer reads exact lengths, so the padding turns
# into extra zero tokens whose count depends on the car's string lengths.
# Measured over the 188 cars whose spec can be joined to an appearance record by
# folder name, the index ranges from 84 to 112.  So we locate the field by its
# shape in BYTE space instead, which is stable for every shipped car.
#: Accepted range for the appearance record id.
#:
#: The lower bound used to be 2, on the assumption that ids 0 and 1 could not be
#: real references.  They can: ``69_2008_lamborghini_gallardo_lp560-4`` points at
#: record **1** (``2010_lamborghini_gallardo``), and with the bound at 2 the scan
#: skipped past it and latched onto a stray ``256`` further down the file - which
#: made the Gallardo and a Nissan GT-R look like the same car.  Allowing 1 fixes
#: that and leaves every other spec alone (measured: 477 distinct records instead
#: of 476, and the one duplicate pair disappears).
_APPEARANCE_LO = 1
_APPEARANCE_HI = 2000


def _zero_run_after(raw: bytes, offset: int) -> int:
    i = offset + 4
    while i < len(raw) and raw[i] == 0:
        i += 1
    return i - offset - 4


def _zero_run_before(raw: bytes, offset: int) -> int:
    i = offset - 1
    while i >= 0 and raw[i] == 0:
        i -= 1
    return offset - 1 - i


def _printable_run_before(raw: bytes, offset: int) -> int:
    i = offset - 1
    while i >= 0 and raw[i] == 0:
        i -= 1
    n = 0
    while i >= 0 and 32 <= raw[i] < 127:
        n += 1
        i -= 1
    return n


def _string_length_after(raw: bytes, offset: int) -> int:
    """Length of the string token that follows ``offset``, or 0."""
    if offset + 8 > len(raw):
        return 0
    n = struct.unpack_from("<I", raw, offset + 4)[0]
    if not (1 <= n <= 200) or offset + 8 + n > len(raw):
        return 0
    if all(32 <= c < 127 for c in raw[offset + 8:offset + 8 + n]):
        return n
    return 0


def appearance_candidates(raw: bytes) -> list[tuple[int, int]]:
    """Every ``(byte offset, value)`` that looks like the appearance id field."""
    out = []
    for offset in range(0, len(raw) - 3):
        value = struct.unpack_from("<I", raw, offset)[0]
        if not (_APPEARANCE_LO <= value <= _APPEARANCE_HI):
            continue
        if _zero_run_before(raw, offset) < 4:
            continue
        if _printable_run_before(raw, offset) < 3:
            continue
        if (_zero_run_after(raw, offset) >= 4
                or _string_length_after(raw, offset)):
            out.append((offset, value))
    return out


def _word_at(tokens, index: int) -> int | None:
    """``tokens[index]`` as a u32, or None when it is not a plain word."""
    if index < 0 or index >= len(tokens):
        return None
    kind, _off, _ln, payload = tokens[index]
    if kind != "n" or len(payload) != 4:
        return None
    return struct.unpack("<I", payload)[0]


def appearance_by_pattern(tokens) -> int | None:
    """Last-resort appearance id locator for specs the byte scan rejects.

    The byte scan in :func:`locate_appearance` demands a printable ASCII run
    immediately before the id.  Cars whose display data ends with a numeric
    block instead (all Formula 1 and NASCAR bodies, plus a few concepts) fail
    that test, so the scan returns None and the caller would fall back to id 0 -
    the same record as ``2010_porsche_gt3``, which is why 63 cars used to show
    up as one Porsche in the manager.

    This second locator works on the token stream and uses only the *shape* of
    the hole, never the neighbouring bytes::

        <u32 id in 1..2000>  0  0  0  0  0  <u32 non-zero> ...

    Five zero words in a row followed by a non-zero one is a signature no other
    field in a shipped spec shares.  Measured on the 540 shipped specs: it
    agrees with :func:`locate_appearance` on all 379 specs where both fire (0
    conflicts), and resolves 62 of the 63 specs the byte scan rejects.  The one
    hold-out is ``49_2010_porsche_911_gt3_rs``, whose spec has no such hole at
    all; it still resolves through its ``.link`` redirect.
    """
    found = appearance_offset_by_pattern(tokens)
    return None if found is None else found[1]


def appearance_offset_by_pattern(tokens) -> tuple[int, int] | None:
    """``(byte offset, value)`` of the appearance id, found by token shape."""
    for i in range(len(tokens)):
        value = _word_at(tokens, i)
        if value is None or not (_APPEARANCE_LO <= value <= _APPEARANCE_HI):
            continue
        following = [_word_at(tokens, i + k) for k in range(1, 7)]
        if any(w is None for w in following):
            continue
        if following[:5] == [0, 0, 0, 0, 0] and following[5]:
            return tokens[i][1], value
    return None


def locate_appearance(raw: bytes) -> int | None:
    """Byte offset of the appearance record id inside a spec, or None.

    ``None`` means the car has no appearance record at all (the field is zero):
    63 of the 540 shipped specs are like that, all of them cars that reuse
    another car's body (Formula 1, NASCAR liveries and a few concepts).
    """
    cand = appearance_candidates(raw)
    if not cand:
        return None
    if len(cand) == 1:
        return cand[0][0]

    def score(item):
        offset, _value = item
        return (-min(_zero_run_after(raw, offset), 20),
                -min(_string_length_after(raw, offset), 200),
                -min(_zero_run_before(raw, offset), 16),
                offset)

    return sorted(cand, key=score)[0][0]


def patch_appearance_id(raw: bytes, value: int, *,
                        old: int | None = None,
                        at: int | None = None) -> bytes:
    """Return ``raw`` with the appearance id replaced by ``value``.

    The field is found by shape.  ``old`` is only a cross check: when the word at
    the located offset does not hold ``old`` we fall back to searching for
    ``old`` and picking the occurrence with the longest zero run after it (some
    cars repeat their id as a plain number elsewhere in the file).

    ``at`` overrides the byte scan with an offset the caller already knows -
    :func:`appearance_offset_by_pattern` supplies one for the 62 specs whose
    field the scan cannot see.
    """
    offset = at if at is not None else locate_appearance(raw)
    if at is None and offset is not None and old is not None:
        if struct.unpack_from("<I", raw, offset)[0] != int(old):
            offset = None
    if offset is None and old is not None:
        pat = struct.pack("<I", int(old))
        hits = []
        i = raw.find(pat)
        while i >= 0:
            hits.append(i)
            i = raw.find(pat, i + 1)
        scored = [h for h in hits if _zero_run_before(raw, h) >= 4]
        if scored:
            offset = sorted(scored,
                            key=lambda h: (-_zero_run_after(raw, h), h))[0]
    if offset is None:
        raise SpecError("cannot find the appearance id in this spec")
    return raw[:offset] + struct.pack("<I", value & 0xFFFFFFFF) + raw[offset + 4:]


# ---------------------------------------------------------------------- Spec
class Spec:
    """One car's spec file."""

    def __init__(self, tokens: list[list], raw: bytes = b""):
        self.tokens = tokens
        self.raw = raw
        # The display-name token is remembered by index because rewriting it
        # replaces the ``CAR_NAME_`` key with a literal string, after which a
        # search for the ``CAR_NAME_`` prefix would no longer find it.
        self._name_index: int | None = None
        self._name_value: bytes | None = None
        self._locate_name()

    def _locate_name(self) -> None:
        """Find the display-name token.

        Three shapes occur in practice:

        * a shipped spec holds the localisation key ``CAR_NAME_*``;
        * a spec written by :meth:`set_display_name` holds the literal display
          string in its place, so the prefix is gone;
        * some cars carry two ``CAR_NAME_*`` tokens (``CAR_NAME_XX`` plus
          ``CAR_NAME_XX_SHORT``); the first one is the display name.

        For the renamed case the token is taken as the string that follows
        ``CAR_MANUFACTURER_*`` - that is where the shipped files put the key
        (502 of 540 cars).  Two small groups stay unreadable and report "":
        the 33 cars that never had a display-name token, and the 5 whose
        manufacturer string is stored as a run of number tokens instead of one
        string token.  The name is still correct in those files; only this
        reader cannot point at it.
        """
        manuf_next: int | None = None
        for i, t in enumerate(self.tokens):
            if t[0] == "s" and t[3].startswith(b"CAR_MANUFACTURER_"):
                nxt = self.tokens[i + 1] if i + 1 < len(self.tokens) else None
                if nxt is not None and nxt[0] == "s":
                    manuf_next = i + 1
                break
        name_first: int | None = None
        for i, t in enumerate(self.tokens):
            if t[0] == "s" and t[3].startswith(b"CAR_NAME_"):
                name_first = i
                break

        if manuf_next is not None:
            # the token right after the manufacturer key is the display name, on
            # both shipped specs (where it is ``CAR_NAME_*``) and renamed ones
            # (where it is the literal display string)
            self._name_index = manuf_next
        else:
            self._name_index = name_first
        self._name_value = (self.tokens[self._name_index][3]
                            if self._name_index is not None else None)

    def _reindex_name(self) -> None:
        """Re-find the display-name token after the token list was rebuilt."""
        if self._name_value is not None:
            for i, t in enumerate(self.tokens):
                if t[0] == "s" and t[3] == self._name_value:
                    self._name_index = i
                    return
        self._locate_name()

    def _refresh(self) -> None:
        """Recompute every token's byte offset from the current payloads.

        A token's payload can be rewritten in place (the make, the model, the
        class, the display name), and that changes the file's length without
        moving the byte offsets the later tokens remember.  Every reader that
        addresses the file by offset - the engine block, the appearance record,
        and :meth:`_splice` itself - then looks at the wrong place.

        This recomputes the offsets from the token list rather than running
        :func:`tokenize` again, because the tokenizer is a heuristic that can
        mis-split a file whose lengths just changed (see :meth:`_splice`).  The
        parse that produced this list was correct; only the offsets are stale.
        """
        out = []
        at = 0
        for kind, _off, _ln, payload in self.tokens:
            if kind == "s":
                out.append(["s", at, len(payload), payload])
                at += 4 + len(payload)
            else:
                out.append(["n", at, None, payload])
                at += len(payload)
        self.tokens = out
        self.raw = detokenize(out)
        self._reindex_name()

    def _retokenize(self, plain: bytes) -> None:
        """Re-split a file this object has just rewritten, keeping the anchors.

        ``tokenize`` alone is not enough after a write.  It decides "is this word
        a string length?" by looking at what follows, and the word in front of a
        brand key is a ``1`` - which, next to a 32-byte key, reads as a one-byte
        string and shifts every token after it by four bytes.  The file is still
        valid (the engine reads it by schema) but this reader loses the name, the
        brand and the PR.

        :func:`parse_spec` anchors that when a file is loaded; a file re-split
        after a write needs the same treatment, which is what this does.  It also
        refuses a split that would not detokenize back to the same bytes, so a
        writer cannot leave the object describing a file it does not have.
        """
        tokens = _anchor_car_strings(tokenize(plain), plain)
        if detokenize(tokens) != plain:
            raise SpecError("the file did not re-split cleanly after the write, "
                            "so nothing was written")
        self.tokens = tokens
        self.raw = plain
        self._reindex_name()

    # ---- reading -------------------------------------------------------
    @property
    def car_id(self) -> int:
        return word(self.tokens, 1)

    def set_car_id(self, value: int) -> None:
        set_word(self.tokens, 1, value)

    def year(self) -> str:
        return self.tokens[2][3].decode("ascii", "replace")

    def make(self) -> str:
        return self.tokens[3][3].decode("ascii", "replace")

    def model(self) -> str:
        return self.tokens[4][3].decode("ascii", "replace")

    def appearance_id(self) -> int:
        """The appearance record id, or 0 when the car has none.

        Two locators run, in order: the byte-shape scan
        (:func:`locate_appearance`), then the token-shape scan
        (:func:`appearance_by_pattern`) for the 63 specs the byte scan rejects.
        Neither uses a fixed token index, because that index varies from car to
        car.
        """
        blob = self.to_bytes()
        offset = locate_appearance(blob)
        if offset is not None:
            return struct.unpack_from("<I", blob, offset)[0]
        value = appearance_by_pattern(self.tokens)
        return 0 if value is None else value

    def appearance_offset(self) -> int | None:
        """Byte offset of the appearance id, or None when the car has none."""
        offset = locate_appearance(self.to_bytes())
        if offset is not None:
            return offset
        found = appearance_offset_by_pattern(self.tokens)
        return None if found is None else found[0]

    def set_appearance_id(self, value: int) -> bool:
        """Point the spec at another appearance record; False when unchanged.

        One shipped spec (``49_2010_porsche_911_gt3_rs``) has no appearance
        field at all - its body comes from a ``.link`` redirect - so writing
        into it is refused rather than guessed: :func:`patch_appearance_id`
        raises.
        """
        value = int(value)
        old = self.appearance_id()
        if value == old:
            return False
        blob = self.to_bytes()
        at = self.appearance_offset()
        patched = patch_appearance_id(blob, value,
                                      old=old or None, at=at)
        if patched == blob:
            return False
        self._retokenize(patched)
        return True

    def display_name_key(self) -> str:
        """The current display-name token, or "" when the car has none.

        On a shipped spec this is the ``CAR_NAME_*`` localisation key.  After
        :meth:`set_display_name` it is the literal display string instead, so the
        accessor keeps returning something usable in both states.
        """
        if self._name_value is None:
            return ""
        return self._name_value.decode("ascii", "replace")

    def aero_flag(self) -> bytes:
        """The active aero behaviour token, empty when the car has none.

        The token is the whole string, numbers included: a Speedtail reports
        ``b"DeployWhenBraking, 160.934, 241.401"``.  Use :meth:`aero_kind` when
        only the behaviour matters.
        """
        return self._aero_raw()

    def aero_kind(self) -> bytes:
        """Just the behaviour word, without any numbers after it."""
        raw = self._aero_raw()
        return raw.split(b",", 1)[0].strip() if raw else b""

    def aero_params(self) -> tuple:
        """The numbers written after the behaviour word, as floats."""
        raw = self._aero_raw()
        if not raw or b"," not in raw:
            return ()
        out = []
        for part in raw.split(b",")[1:]:
            try:
                out.append(float(part.strip()))
            except ValueError:
                break
        return tuple(out)

    def aero_text(self) -> str:
        """The whole token as text, e.g. ``"BrakeAndSpeedCombo, 180, 170"``."""
        return self._aero_raw().decode("ascii", "replace")

    def _aero_raw(self) -> bytes:
        """The behaviour token sitting in front of ``generic_*``, or b""."""
        slot = self._aero_slot()
        if slot is None:
            return b""
        _start, _end, text = slot
        return text

    def _aero_slot(self):
        """``(start, end, text)`` of the behaviour token, or None.

        The token is a single length-prefixed string whose first word is one of
        :data:`AERO_KINDS`, optionally followed by ``", 180, 170"``.  It sits in
        the slot in front of a length-prefixed ``generic_*``/``prototype_*``
        string, and when a car has no active aero that slot holds a zero length
        word instead.

        Read off the raw bytes rather than the token list: the tokenizer treats
        any ``u32`` in 1..200 followed by that many printable bytes as a string,
        and the length word in front of the behaviour token is often a small
        number, so the token stream sometimes splits the token into garbage.
        """
        plain = detokenize(self.tokens)
        for kind in AERO_KINDS:
            at = plain.find(kind)
            while at >= 0:
                if at >= 4:
                    size = struct.unpack_from("<I", plain, at - 4)[0]
                    end = at + size
                    if (4 < size <= 200 and end <= len(plain)
                            and plain[at + len(kind):end].strip()[:1] in
                            (b"", b",")):
                        return (at - 4, end, plain[at:end])
                at = plain.find(kind, at + 1)
        # No behaviour written: find the empty slot so one can be added.
        for g in _generic_positions(plain):
            end = g - 4
            if end >= 4 and plain[end - 4:end] == b"\x00\x00\x00\x00":
                return (end - 4, end, b"")
        return None

    def set_aero(self, enable: bool, *, kind: bytes = b"", params=()) -> bool:
        """Turn active aero on or off, or change which behaviour it uses.

        The token is written into the slot in front of ``generic_*``, in place:
        its length word and the bytes after it are replaced, so nothing else in
        the file shifts.  ``kind`` and ``params`` let a car switch between the
        four behaviours - the numbers go after the name with a comma, the way the
        shipped files do it, so the token stays one string.
        """
        slot = self._aero_slot()
        if slot is None:
            raise SpecError(
                "this spec has no behaviour slot in front of a 'generic_*' "
                "string, so active aero cannot be written")
        start, end, current = slot
        if kind:
            want = kind.decode("ascii")
            if params:
                want += ", " + ", ".join("%g" % float(p) for p in params)
            if current == want.encode("ascii"):
                return False
            return self._write_aero(start, end, want.encode("ascii"))
        if not enable:
            if not current:
                return False
            return self._write_aero(start, end, b"")
        if current:
            return False
        return self._write_aero(start, end, AERO_FLAG)

    def _write_aero(self, start: int, end: int, text: bytes) -> bool:
        """Replace the behaviour token in ``[start, end)`` with ``text``."""
        plain = detokenize(self.tokens)
        head = plain[:start]
        tail = plain[end:]
        if text:
            body = struct.pack("<I", len(text)) + text
        else:
            body = b"\x00\x00\x00\x00"
        self._retokenize(head + body + tail)
        return True

    # ---- performance ---------------------------------------------------
    #
    # Everything below reads the numbers the game's car screen shows: weight, top
    # speed, 0-60, braking, grip, the PR, the engine and the drivetrain.  Two
    # groups behave differently:
    #
    # * the first 35 tokens are laid out identically in every shipped file, so
    #   the block at ``STAT_INDEX`` and the drivetrain string are read straight
    #   off fixed indices (MonkeyTool's ``kHead`` does the same);
    # * the engine block, the price and the PR sit after a variable-length run of
    #   strings, so they are found by shape - a run of numbers of the right
    #   length, or the numbers beside the ``CAR_NAME_*`` key.
    #
    # Writing is deliberately narrow: only the fields whose position is certain
    # are writable.  A wrong write here silently changes how the car drives, and
    # nothing in the file lets us check it afterwards.  The engine block and the
    # starting PR have their own writers (:meth:`set_engine`, :meth:`set_pr`)
    # because they are addressed by shape rather than by index; the gear count
    # stays read-only because it decides the length of the block.

    def _stat_token(self, key: str):
        index = STAT_INDEX[key]
        if index >= len(self.tokens):
            return None
        token = self.tokens[index]
        return token if token[0] == "n" and len(token[3]) >= 4 else None

    def stats(self) -> dict:
        """The numbers the game shows for this car, as a plain dict.

        Missing fields come back as ``None`` rather than raising: 33 shipped
        specs have no display-name key, which also costs them their PR, and
        three cars have a performance block the reader does not recognise.
        """
        out = {}
        for key in STAT_INDEX:
            token = self._stat_token(key)
            if token is None:
                out[key] = None
            elif key in _STAT_U32:
                out[key] = struct.unpack("<I", token[3][:4])[0]
            else:
                out[key] = struct.unpack("<f", token[3][:4])[0]
        if STAT_CLASS < len(self.tokens):
            token = self.tokens[STAT_CLASS]
            out["car_class"] = (token[3].decode("ascii", "replace")
                                if token[0] == "s" else "")
        else:
            out["car_class"] = ""
        if len(self.tokens) > STAT_DRIVETRAIN:
            token = self.tokens[STAT_DRIVETRAIN]
            out["drivetrain"] = (token[3].decode("ascii", "replace")
                                 if token[0] == "s" else "")
        else:
            out["drivetrain"] = ""
        out.update(self._engine_stats())
        out.update(self._pr_stats())
        out.update(self.tail())
        return out

    def _engine_index(self) -> int:
        """Token index of the gear count, or -1.

        The engine block starts right after the ``aspiration``/``layout`` string
        pair, and the first number there is the gear count.  MonkeyTool scans for
        the pair; so does this, because the padding tokens before it vary.
        """
        for i in range(STAT_DRIVETRAIN, len(self.tokens) - 2):
            token = self.tokens[i]
            if token[0] != "s" or token[3] not in (
                    b"Turbo", b"Nat", b"Super", b"None", b"Electric", b"Hybrid"):
                continue
            nxt = self.tokens[i + 1]
            if nxt[0] != "s" or len(nxt[3]) > 2:
                continue
            if i + 2 >= len(self.tokens):
                continue
            gears = self.tokens[i + 2]
            if gears[0] != "n" or len(gears[3]) < 4:
                continue
            if 1 <= struct.unpack("<I", gears[3][:4])[0] <= 12:
                return i + 2
        return -1

    def _engine_stats(self) -> dict:
        """Read the engine block straight out of the bytes.

        Not off the token list: the gear ratios are floats, and a float's bytes
        can look like a string length prefix, so the tokenizer splits them into
        fake strings (the P1's ``7`` gears is followed by a token that reads as
        the string ``"3"``).  Token *offsets* survive that, so the block is
        addressed by byte offset and read as raw numbers.
        """
        index = self._engine_index()
        if index < 0:
            return {}
        plain = detokenize(self.tokens)
        base = self.tokens[index][1]
        out = {}
        for key, offset in STAT_ENGINE_OFFSETS.items():
            at = base + offset * 4
            if at + 4 > len(plain):
                continue
            if key in ("gears", "torque", "power_rpm", "torque_rpm", "redline",
                       "limiter", "shift_up", "shift_down"):
                out[key] = struct.unpack_from("<I", plain, at)[0]
            else:
                out[key] = struct.unpack_from("<f", plain, at)[0]
        return out

    def _pr_index(self) -> int:
        """Token index of the PR, or -1.

        The PR is the first number after the ``CAR_NAME_*`` key (MonkeyTool
        reads ``iNameKey + 4``).  That offset is fixed only because the two
        strings and two numbers in between never move, so it is checked by shape
        here rather than trusted.
        """
        for i, token in enumerate(self.tokens):
            if token[0] != "s" or not token[3].startswith(b"CAR_NAME_"):
                continue
            for offset in (4, 5):
                at = i + offset
                if at >= len(self.tokens):
                    continue
                num = self.tokens[at]
                if num[0] != "n" or len(num[3]) < 4:
                    continue
                value = struct.unpack("<f", num[3][:4])[0]
                if 0.0 < value < 250.0:
                    return at
            return -1
        return -1

    def _pr_stats(self) -> dict:
        at = self._pr_index()
        if at < 0:
            return {"pr": None, "pr_max": None}
        out = {"pr": struct.unpack("<f", self.tokens[at][3][:4])[0]}
        if at + 1 < len(self.tokens) and self.tokens[at + 1][0] == "n":
            out["pr_max"] = struct.unpack("<f", self.tokens[at + 1][3][:4])[0]
        else:
            out["pr_max"] = None
        return out

    def set_engine(self, changes: dict) -> list:
        """Write engine figures by byte offset; returns the keys that changed.

        The engine block is a run of numbers whose start is found by shape (see
        :meth:`_engine_index`), so it is addressed the same way the reader
        addresses it: from the gear count's *byte offset*, never from a token
        index.  A token index cannot work here because the gear ratios are floats
        and a float's bytes can look like a string length prefix, which makes the
        tokenizer split the block into fake strings - the token *offsets* survive
        that, the token *count* does not.

        ``gears`` cannot be changed: it decides how many gear ratios follow it, so
        writing a different number would make the reader - and the game - read the
        rest of the block at the wrong stride.  Changing the count of gears means
        rebuilding the block, which is a different job.

        Values are checked against :data:`ENGINE_LIMITS` first, because a zero
        redline or a 40 000 rpm limiter produces a car that cannot leave the line
        and gives no hint why.
        """
        index = self._engine_index()
        if index < 0:
            raise SpecError("the engine block could not be found in this file")
        plain = detokenize(self.tokens)
        base = self.tokens[index][1]
        changed = []
        for key, value in changes.items():
            if key == "gears":
                raise SpecError("the gear count cannot be changed in place - "
                                "it decides how many ratios follow it")
            offset = STAT_ENGINE_OFFSETS.get(key)
            if offset is None:
                raise SpecError(f"{key} is not an engine figure")
            low, high = ENGINE_LIMITS[key]
            number = float(value)
            if not low <= number <= high:
                raise SpecError(f"{key}: {number:g} is outside {low:g}..{high:g}")
            at = base + offset * 4
            if at + 4 > len(plain):
                raise SpecError(f"{key} is past the end of the file")
            if key in _ENGINE_U32:
                packed = struct.pack("<I", int(number) & 0xFFFFFFFF)
            else:
                packed = struct.pack("<f", number)
            if plain[at:at + 4] == packed:
                continue
            plain = plain[:at] + packed + plain[at + 4:]
            changed.append(key)
        if changed:
            self._retokenize(plain)
        return changed

    def gear_ratios(self) -> list:
        """The ratio list exactly as the file holds it, or ``[]``.

        The count is the last word of the thirteen-word engine block and the
        ratios follow it, so this reads ``count`` floats from there.  The last
        one is not a forward gear - see :meth:`set_gears` - and a one-ratio car's
        single entry is its final drive.
        """
        index = self._engine_index()
        if index < 0:
            return []
        plain = detokenize(self.tokens)
        base = self.tokens[index][1]
        if base + 4 > len(plain):
            return []
        count = struct.unpack_from("<I", plain, base)[0]
        if not 1 <= count <= 12 or base + 4 * (13 + count) > len(plain):
            return []
        return [struct.unpack_from("<f", plain, base + 4 * (13 + i))[0]
                for i in range(count)]

    def set_gears(self, count: int) -> bool:
        """Change how many gear ratios the car has; returns whether it changed.

        The gear count cannot be written on its own the way the other engine
        figures can: it decides how many ratio floats follow it, so a different
        number read in place would make the game walk the rest of the block at
        the wrong stride.  What this does instead is rebuild the ratio list -
        ``count`` floats right after the thirteen-word block, the last of which
        is the reverse ratio - and then rewrite the count in front of it.

        A new gear is interpolated geometrically between the two ratios it is
        squeezed into, because that is the shape a real gearbox has (each gear a
        constant fraction shorter than the one below) and it keeps the top gear
        where the designer put it.  Removing a gear drops the one below the top.
        The reverse ratio and the thirteen words in front are left alone.

        The whole file shifts by four bytes per gear, so everything after it is
        re-parsed and checked against what it said before: if the name, the
        figures, the prices or the upgrade route no longer read back, the change
        is refused rather than written.
        """
        count = int(count)
        if not 1 <= count <= 12:
            raise SpecError(f"{count} gears is not a count the game can read "
                            "(1 to 12)")
        index = self._engine_index()
        if index < 0:
            raise SpecError("the engine block could not be found in this file")
        plain = detokenize(self.tokens)
        base = self.tokens[index][1]
        old = struct.unpack_from("<I", plain, base)[0]
        if old == count:
            return False
        if base + 4 * (13 + old) > len(plain):
            raise SpecError("the gear ratios run past the end of the file")
        ratios = [struct.unpack_from("<f", plain, base + 4 * (13 + i))[0]
                  for i in range(old)]
        # The last entry is not a forward gear: every shipped car's list ends on
        # a number larger than the one before it, and a one-ratio car's single
        # entry is its final drive.  Only the forward ratios are rebuilt.
        forward, tail_ratio = ratios[:-1], ratios[-1:]
        if not forward:
            raise SpecError(
                f"{count} gears from {old}: this car has a single ratio and no "
                "forward gear list to rebuild")
        if count > old:
            extra = count - old
            top = forward[-1]
            low = forward[-2] if len(forward) > 1 else top * 2.2
            if low <= top:                      # odd data; keep it a step down
                low = top * 1.35
            step = (top / low) ** (1.0 / (extra + 1))
            new = [low * step ** (i + 1) for i in range(extra)]
            forward = forward[:-1] + new + [top]
        else:
            drop = old - count
            if drop >= len(forward):
                raise SpecError(f"{old} gears cannot be cut to {count}: there is "
                                "nothing left but the trailing ratio")
            # Take the gears just below the top, not the top itself, so the car
            # keeps the top speed the designer gave it and simply has bigger
            # steps between what is left.  It also makes "one more gear" and
            # "one fewer" undo each other, which is what a dialog offers.
            forward = forward[:-1 - drop] + forward[-1:]
        rebuilt = forward + list(tail_ratio)
        before = self.stats()
        body = b"".join(struct.pack("<f", value) for value in rebuilt)
        plain = (plain[:base + 4 * 13] + body
                 + plain[base + 4 * (13 + old):])
        plain = plain[:base] + struct.pack("<I", count) + plain[base + 4:]
        self._retokenize(plain)
        self._verify_gears(before, count)
        return True

    def _verify_gears(self, before: dict, count: int) -> None:
        """Refuse the rebuild unless the rest of the file still reads back.

        Four bytes per gear went in or came out, so every token after the ratio
        list moved.  The reader finds the block by shape and the name by its
        anchor, so a mis-split would show up here as a field that changed when it
        should not have - and a spec written in that state is a car the game
        loads with the wrong numbers.
        """
        after = self.stats()
        if after.get("gears") != count:
            raise SpecError("the gear count did not read back after the rebuild")
        for key in ("pr", "pr_max", "power_hp", "torque", "redline", "limiter",
                    "final_drive", "aspiration", "layout", "route", "unlock",
                    "cash", "gold", "weight_lb", "top_speed"):
            if key in before and before.get(key) != after.get(key):
                raise SpecError(
                    f"rebuilding the gears changed {key} as well "
                    f"({before.get(key)!r} -> {after.get(key)!r}), so nothing "
                    "was written")

    # ---- the engine sound ----------------------------------------------
    #
    # Three strings in a row name the audio the car plays: the acceleration take,
    # the deceleration take and the idle.  They point into
    # ``audio/Vehicles/<family>/``, and every car in a family shares the family's
    # own ``<family>_accel.wav`` / ``_decel.wav`` / ``_idle.wav`` unless a per-car
    # ``id_<n>_accel.decomp`` override exists.
    #
    # 435 of the 540 shipped specs have them at tokens 21/22/23.  The other 105
    # have no audio string at all - old F1 cars, the NASCARs, some concepts - and
    # the game falls back to something of its own; those report "" and refuse to
    # be written rather than guessing a position.

    def sound(self) -> dict:
        """The engine sound this car asks for: ``{accel, decel, idle, family}``."""
        out = {"accel": "", "decel": "", "idle": "", "family": ""}
        if len(self.tokens) <= STAT_SOUND:
            return out
        for key, index in (("accel", STAT_SOUND), ("decel", STAT_SOUND + 1),
                           ("idle", STAT_SOUND + 2)):
            if index >= len(self.tokens):
                continue
            token = self.tokens[index]
            if token[0] == "s":
                out[key] = token[3].decode("ascii", "replace")
        out["family"] = _sound_family(out["accel"]) or _sound_family(out["idle"])
        return out

    def set_sound(self, family: str, *, car_id: int | None = None) -> bool:
        """Point the car at another engine-sound family; returns whether it changed.

        Only the three strings are rewritten, and only when the car already has
        them: a car with no audio fields has nowhere to put them, and inventing an
        offset there would overwrite whatever actually lives at token 21.

        ``family`` is a folder name under ``audio/Vehicles/`` (``v10_04``,
        ``ttv8_01``, ``f1_02`` ...).  The per-car file name is rebuilt from the
        car's own id, which is what the shipped files do - so pointing a car at
        another family keeps its own ``id_<n>_accel`` override name.
        """
        family = (family or "").strip()
        if not family:
            raise SpecError("an engine sound needs a family name")
        if "/" in family or "\\" in family:
            raise SpecError(f"{family!r} is not a family name")
        if not self.sound()["accel"]:
            raise SpecError("this car has no engine sound fields to rewrite")
        ident = self.car_id if car_id is None else int(car_id)
        wanted = (f"audio/Vehicles/{family}/id_{ident}_accel",
                  f"audio/Vehicles/{family}/id_{ident}_decel",
                  f"{family}_idle")
        changed = False
        for offset, text in enumerate(wanted):
            token = self.tokens[STAT_SOUND + offset]
            new = text.encode("ascii")
            if token[3] == new:
                continue
            token[3] = new
            changed = True
        return changed

    def set_pr(self, value) -> bool:
        """Write the starting PR; returns whether anything changed.

        Position comes from :meth:`_pr_index`, which finds the ``CAR_NAME_*`` key
        and then checks the shape of the two numbers after it - so this writes
        only where the reader already agreed there is a PR.  33 shipped specs
        have no display-name key at all and therefore no PR; those return
        ``False`` rather than guessing.

        See :meth:`set_pr_max` for what the second float is and why it is
        offered as an override rather than derived.
        """
        at = self._pr_index()
        if at < 0:
            return False
        token = self.tokens[at]
        if token[0] != "n" or len(token[3]) < 4:
            return False
        packed = struct.pack("<f", float(value))
        if token[3][:4] == packed:
            return False
        self.tokens[at][3] = packed + token[3][4:]
        return True

    def set_pr_max(self, value) -> bool:
        """Write the fully-upgraded PR; returns whether anything changed.

        This is the number the showroom shows next to the base one, and it is a
        float of its own - the next word after the base PR, found the same way.

        It is *derived* data in the game's own pipeline: PR is a function of the
        car's figures, and the maximum is the same function applied after the
        upgrade route's percentages have been applied.  Two shipped cars with
        byte-identical figures always carry the same pair of numbers (11 such
        groups exist), which is how we know it is computed rather than chosen.
        The formula itself could not be recovered - a quadratic fit over the
        figures of all 540 cars is still off by three PR points on average - so
        this writes the number the game displays instead of pretending to
        recompute it.  A value that does not match what the route and the
        figures add up to is a car whose upgrade screen disagrees with its card.
        """
        at = self._pr_index()
        if at < 0:
            return False
        at += 1
        if at >= len(self.tokens):
            return False
        token = self.tokens[at]
        if token[0] != "n" or len(token[3]) < 4:
            return False
        packed = struct.pack("<f", float(value))
        if token[3][:4] == packed:
            return False
        self.tokens[at][3] = packed + token[3][4:]
        return True

    # ---- aspiration, layout, unlock and price ----------------------------
    #
    # Everything from the gear count onwards is a flat run of numbers and
    # strings, so these are found by walking that run rather than by index:
    #
    #     aspiration  layout  gears  <engine block>  route  unlock
    #     4 x u32  extra-string  4 x u32  cash  gold  ...
    #
    # The two strings that end the head of the run (the upgrade route and the
    # unlock rule) are variable length, which is why the money is addressed from
    # the *end of the unlock string* and not from the start of the file.
    #
    # The four words before the extra string are ``0, 0, 0, <a small id>`` and
    # the four after it are all zero on every shipped car.  The extra string is
    # empty on 532 of them and holds ``r3_spec_logo.xml`` on the eight "R3"
    # specials, so it has to be skipped by its own length prefix - assuming it is
    # absent puts the money 20 bytes late on exactly those eight cars.

    def aspiration(self) -> str:
        """``Nat`` / ``Turbo`` / ``Super`` / ``None``, or ``""``."""
        index = self._engine_index()
        if index < 2:
            return ""
        token = self.tokens[index - 2]
        return token[3].decode("ascii", "replace") if token[0] == "s" else ""

    def layout(self) -> str:
        """``F`` / ``M`` / ``R`` / ``FM``, or ``""``."""
        index = self._engine_index()
        if index < 1:
            return ""
        token = self.tokens[index - 1]
        return token[3].decode("ascii", "replace") if token[0] == "s" else ""

    def _tail_offset(self) -> int:
        """Byte offset just past the unlock string, or -1."""
        at = self._route_offset()
        if at < 0:
            return -1
        plain = detokenize(self.tokens)
        for _ in range(2):                       # the route key, then the unlock
            if at + 4 > len(plain):
                return -1
            length = struct.unpack_from("<I", plain, at)[0]
            if length > _UNLOCK_MAX or at + 4 + length > len(plain):
                return -1
            at += 4 + length
        return at if at + 4 <= len(plain) else -1

    def _money_offset(self) -> int:
        """Byte offset of the cash price, or -1."""
        at = self._tail_offset()
        if at < 0:
            return -1
        plain = detokenize(self.tokens)
        at += 16                                  # four words: 0, 0, 0, id
        if at + 4 > len(plain):
            return -1
        length = struct.unpack_from("<I", plain, at)[0]
        if length > _UNLOCK_MAX or at + 4 + length > len(plain):
            return -1
        at += 4 + length + 16                     # extra string, four zero words
        return at if at + 8 <= len(plain) else -1

    def tail(self) -> dict:
        """``{aspiration, layout, unlock, extra, cash, gold}``.

        ``cash`` and ``gold`` are the two prices the showroom reads; a car that
        cannot be bought has both at zero (8 shipped cars), and 280 have both set
        because the game shows the gold price and keeps a cash price behind it.
        """
        out = {"aspiration": self.aspiration(), "layout": self.layout(),
               "unlock": "", "extra": "", "cash": 0, "gold": 0}
        at = self._tail_offset()
        if at < 0:
            return out
        plain = detokenize(self.tokens)
        at = self._route_offset()
        for key in ("route", "unlock"):
            length = struct.unpack_from("<I", plain, at)[0]
            chunk = plain[at + 4:at + 4 + length]
            if key == "unlock":
                out["unlock"] = chunk.decode("ascii", "replace")
            at += 4 + length
        at += 16
        length = struct.unpack_from("<I", plain, at)[0]
        out["extra"] = plain[at + 4:at + 4 + length].decode("ascii", "replace")
        money = self._money_offset()
        if money >= 0:
            out["cash"], out["gold"] = struct.unpack_from("<II", plain, money)
        return out

    def _splice(self, at: int, remove: int, insert: bytes) -> None:
        """Replace ``remove`` bytes at ``at`` with a new string token.

        The token list is **not** rebuilt by re-tokenizing.  :func:`tokenize` is
        a heuristic - it decides whether four bytes are a string length by
        checking whether the bytes after them are printable - and the byte in
        front of a string is very often ``01 00 00 00``, a count of one.  Writing
        a 32-byte string where a 24-byte one was puts ``0x20`` (a space) right
        after that count, the heuristic then reads "a one-byte string", and every
        token after it is off by four bytes: the manufacturer key disappears, the
        display name disappears, and the file is quietly ruined.  So the tokens
        are moved by hand instead: everything before keeps its place, the
        replaced token becomes the new payload, and everything after shifts by
        the length difference.
        """
        plain = detokenize(self.tokens)
        new_plain = plain[:at] + insert + plain[at + remove:]
        delta = len(insert) - remove
        payload = insert[4:]
        tokens = []
        placed = False
        for kind, off, ln, old in self.tokens:
            end = off + (4 + ln if kind == "s" else len(old))
            if end <= at:
                tokens.append([kind, off, ln, old])
            elif off == at:
                tokens.append(["s", at, len(payload), payload])
                placed = True
            elif off > at:
                tokens.append([kind, off + delta, ln, old])
            # a token that straddles the cut cannot exist for a well-formed
            # replacement; dropping it is better than keeping a wrong offset
        if not placed:
            tokens.append(["s", at, len(payload), payload])
            tokens.sort(key=lambda t: t[1])
        self.tokens = tokens
        self.raw = new_plain
        self._reindex_name()

    def _string_token(self, index: int):
        if index < 0 or index >= len(self.tokens):
            return None
        token = self.tokens[index]
        return token if token[0] == "s" else None

    def set_aspiration(self, name: str) -> bool:
        """Write the aspiration; returns whether it changed.

        Only the six values in :data:`ASPIRATIONS` are accepted, because the
        engine block is located by one of them: an unknown string would hide the
        gear count, the power figures and the upgrade route from every reader
        here, and the game would show a car with no tuning screen.
        """
        wanted = name.encode("ascii", "replace")
        if wanted not in ASPIRATIONS:
            raise SpecError(f"{name!r} is not an aspiration the game knows")
        index = self._engine_index()
        token = self._string_token(index - 2) if index >= 2 else None
        if token is None:
            raise SpecError("this file has no aspiration where one belongs")
        if token[3] == wanted:
            return False
        self._splice(token[1], 4 + len(token[3]),
                     struct.pack("<I", len(wanted)) + wanted)
        return True

    def set_layout(self, name: str) -> bool:
        """Write the drivetrain layout (``F`` / ``M`` / ``R`` / ``FM``)."""
        wanted = name.encode("ascii", "replace")
        if wanted not in LAYOUTS:
            raise SpecError(f"{name!r} is not a layout the game knows")
        index = self._engine_index()
        token = self._string_token(index - 1) if index >= 1 else None
        if token is None:
            raise SpecError("this file has no layout where one belongs")
        if token[3] == wanted:
            return False
        self._splice(token[1], 4 + len(token[3]),
                     struct.pack("<I", len(wanted)) + wanted)
        return True

    def set_unlock(self, text: str) -> bool:
        """Write the unlock rule; returns whether it changed.

        The rule is a short ASCII string such as ``NOTLOCKED``, ``QUEST:...`` or
        ``LTS:SERIES_TITLE_LTS``.  An empty string means "no rule" and 160 shipped
        cars have one, so writing ``""`` is allowed.  Everything after it moves
        when its length changes, which is fine: the rest of the file is read
        sequentially, and this rebuilds the token list so the readers here follow.
        """
        wanted = text.encode("ascii", "replace")
        if len(wanted) > _UNLOCK_MAX:
            raise SpecError(f"an unlock rule cannot be {len(wanted)} bytes long")
        if not all(32 <= c < 127 for c in wanted):
            raise SpecError(f"{text!r} is not printable ASCII")
        at = self._tail_offset()
        if at < 0:
            raise SpecError("this file has no unlock rule where one belongs")
        plain = detokenize(self.tokens)
        start = self._route_offset()
        length = struct.unpack_from("<I", plain, start)[0]
        start += 4 + length
        current = struct.unpack_from("<I", plain, start)[0]
        if plain[start + 4:start + 4 + current] == wanted:
            return False
        self._splice(start, 4 + current, struct.pack("<I", len(wanted)) + wanted)
        return True

    def set_price(self, cash=None, gold=None) -> bool:
        """Write the cash price and the gold price; returns whether either moved.

        Both are plain u32s and neither is derived from anything, so this is the
        one price edit that is exact.  ``None`` leaves a field alone; ``0`` means
        "not for sale that way", which is what 252 shipped cars do with gold.
        """
        money = self._money_offset()
        if money < 0:
            raise SpecError("this file has no price where one belongs")
        plain = detokenize(self.tokens)
        current = struct.unpack_from("<II", plain, money)
        new = list(current)
        for slot, value in enumerate((cash, gold)):
            if value is None:
                continue
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise SpecError(f"{value!r} is not a price") from None
            if not 0 <= number <= 0xFFFFFFFF:
                raise SpecError(f"{number} does not fit in a price field")
            new[slot] = number
        if tuple(new) == current:
            return False
        plain = (plain[:money] + struct.pack("<II", *new)
                 + plain[money + 8:])
        self._retokenize(plain)
        return True

    # ---- the upgrade route ----------------------------------------------
    #
    # A car's upgrade tree is not in its spec.  The spec names a *key* - a short
    # ASCII string such as ``PROD_03`` or ``2022_FORMULA_1`` - and
    # ``carupgrade.upgrades.nct`` holds the block that key names.  So retuning a
    # car's upgrade path is a one-string edit here; nothing in the table moves.
    #
    # The key sits at a fixed distance from the gear count: twelve numbers, then
    # one ratio per gear *plus reverse*, then the key.  That is
    # ``4 * (13 + gears)`` past the gear count's byte offset, and it reads as a
    # printable string or an empty slot on all 540 shipped specs.  75 of them
    # leave it empty, which is why an empty key is legal here.

    def upgrade_route(self) -> str:
        """The upgrade-route key this car asks for, or ``""``."""
        at = self._route_offset()
        if at < 0:
            return ""
        plain = detokenize(self.tokens)
        length = struct.unpack_from("<I", plain, at)[0]
        if length == 0 or length > _ROUTE_MAX:
            return ""
        if at + 4 + length > len(plain):
            return ""
        chunk = plain[at + 4:at + 4 + length]
        if not all(32 <= c < 127 for c in chunk):
            return ""
        return chunk.decode("ascii")

    def _route_offset(self) -> int:
        """Byte offset of the route key, or -1."""
        index = self._engine_index()
        if index < 0:
            return -1
        plain = detokenize(self.tokens)
        base = self.tokens[index][1]
        if base + 4 > len(plain):
            return -1
        gears = struct.unpack_from("<I", plain, base)[0]
        if not 1 <= gears <= 12:
            return -1
        at = base + 4 * (13 + gears)
        return at if at + 4 <= len(plain) else -1

    def set_upgrade_route(self, key: str) -> bool:
        """Point the car at another upgrade route; returns whether it changed.

        ``key`` must name a block in ``carupgrade.upgrades.nct`` - use
        :meth:`rr3lib.upgrades.Upgrades.get` to check, because a key that names
        nothing gives the car no upgrade tree at all and the game shows an empty
        tuning screen rather than refusing to load.  An empty ``key`` is allowed
        and means "no route", which 75 shipped cars do.

        Only the one string is rewritten, so every other field keeps its offset.
        """
        if len(key.encode("ascii", "replace")) > _ROUTE_MAX:
            raise SpecError(f"{key!r} is too long to be a route key")
        if not all(32 <= ord(c) < 127 for c in key):
            raise SpecError(f"{key!r} is not printable ASCII")
        at = self._route_offset()
        if at < 0:
            raise SpecError("this file has no route key where one belongs")
        plain = detokenize(self.tokens)
        length = struct.unpack_from("<I", plain, at)[0]
        if length <= _ROUTE_MAX and at + 4 + length <= len(plain):
            current = plain[at + 4:at + 4 + length]
        else:
            raise SpecError("the route key in this file does not read as a string")
        wanted = key.encode("ascii")
        if current == wanted:
            return False
        plain = plain[:at] + struct.pack("<I", len(wanted)) + wanted + plain[at + 4 + length:]
        self._retokenize(plain)
        return True

    def set_stat(self, key: str, value) -> bool:
        """Write one fixed-index field; returns whether anything changed.

        Only the fields in :data:`STAT_INDEX` are writable, because those are the
        ones whose position is identical in every shipped file.  The engine block
        and ``pr_max`` stay read-only: their position depends on the length of the
        strings around them, and a mis-write there changes the car's handling with
        no way to notice.  The starting PR has its own method (:meth:`set_pr`)
        because it is found by shape rather than by index.
        """
        if key not in STAT_INDEX:
            raise SpecError(f"{key} is not a writable stat")
        token = self._stat_token(key)
        if token is None:
            return False
        if key in _STAT_U32:
            packed = struct.pack("<I", int(value) & 0xFFFFFFFF)
        else:
            packed = struct.pack("<f", float(value))
        if token[3][:4] == packed:
            return False
        self.tokens[STAT_INDEX[key]][3] = packed + token[3][4:]
        return True

    def set_class(self, name: str) -> bool:
        """Write the class string (``Race``/``Supercar``/``Prod``).

        The class is a string token at a fixed index, not a number, so it cannot
        go through :meth:`set_stat`.  It is safe to write because the index is
        identical in all 540 shipped files and the three legal values are the
        same length as each other only by luck - which is why the file length
        changes and the caller has to save the whole spec afterwards.
        """
        if STAT_CLASS >= len(self.tokens):
            return False
        token = self.tokens[STAT_CLASS]
        if token[0] != "s":
            return False
        new = name.encode("ascii")
        if token[3] == new:
            return False
        self.tokens[STAT_CLASS][3] = new
        self._refresh()
        return True

    def set_drivetrain(self, name: str) -> bool:
        """Write the driven-wheel word (``RWD``/``AWD``/``FWD``/``RLY``).

        This is a different field from :meth:`set_layout`, and the two are easy
        to confuse: the layout is *where the engine sits* (``F`` front, ``M``
        mid, ``R`` rear, ``FM`` front-mid) and the drivetrain is *which wheels
        it turns*.  A 911 is ``R``/``AWD``; a mid-engined Ferrari is ``M``/``RWD``.

        Only the four words the game ships are accepted, because this one feeds
        the physics code directly.  One shipped spec (the 2019 Formula 1 AMG GT-R
        safety car) holds a number where the word belongs; that file is refused
        rather than guessed at, since there is nowhere to put the string.
        """
        wanted = name.encode("ascii")
        if wanted not in DRIVETRAINS:
            raise SpecError(f"{name!r} is not a drivetrain the game knows")
        if STAT_DRIVETRAIN >= len(self.tokens):
            raise SpecError("this file is too short to hold a drivetrain")
        token = self.tokens[STAT_DRIVETRAIN]
        if token[0] != "s":
            raise SpecError(
                "this file has no drivetrain string where one belongs - the "
                "slot holds a number instead")
        if token[3] == wanted:
            return False
        self._splice(token[1], 4 + len(token[3]),
                     struct.pack("<I", len(wanted)) + wanted)
        return True

    def manufacturer_key(self) -> str:
        """The ``CAR_MANUFACTURER_*`` token, or ``""`` when there is none.

        502 of the 540 shipped specs carry one; the rest name the brand in the
        make string alone, which is what a car built here does.
        """
        for token in self.tokens:
            if token[0] == "s" and token[3].startswith(b"CAR_MANUFACTURER_"):
                return token[3].decode("ascii", "replace")
        return ""

    def set_manufacturer(self, key: str) -> bool:
        """Point the manufacturer key at another brand (``CAR_MANUFACTURER_FERRARI``).

        The brand a car is filed under is the make string (token 3) *and*, on the
        502 specs that have one, this key.  Writing only the make leaves the old
        key in place, and the game's brand list reads the key first - so a car
        re-branded that way still shows up under its old manufacturer.  Both are
        written together by :func:`rrmod.edit.set_identity`.

        A spec with no key is left alone and ``False`` is returned: inserting one
        shifts every later field, which the engine cannot survive.
        """
        wanted = key.encode("ascii")
        if not wanted:
            return False
        for i, token in enumerate(self.tokens):
            if token[0] == "s" and token[3].startswith(b"CAR_MANUFACTURER_"):
                if token[3] == wanted:
                    return False
                self._splice(token[1], 4 + len(token[3]),
                             struct.pack("<I", len(wanted)) + wanted)
                return True
        return False

    def set_display_name(self, key: str) -> int:
        """Rewrite the display-name token and return how many tokens changed.

        The shipped value is a ``CAR_NAME_*`` localisation key; the replacement
        is normally the literal display string (``2026-test-clone``).  Both live
        in the same token, so the length of the file changes and every later
        field shifts - that is safe because the spec is written to a brand new
        file, but it is why the token is addressed by index and not by offset.

        33 of the 540 shipped specs have no display-name token at all; those cars
        are named straight from the year/make/model strings.  We do **not**
        insert one: inserting a token shifts every later field and the engine
        then reads garbage, so such a spec is left alone and 0 is returned.
        """
        if self._name_index is None or self._name_value is None:
            return 0
        new = key.encode("ascii")
        if new == self._name_value:
            return 0
        self.tokens[self._name_index][3] = new
        self._name_value = new
        self._refresh()
        return 1

    def set_model(self, model: str) -> int:
        """Rewrite the model token (``LFA`` -> ``LFA_AnimTest``)."""
        old = self.model()
        if old == model:
            return 0
        n = 0
        for t in self.tokens:
            if t[0] == "s" and t[3] == old.encode("ascii"):
                t[3] = model.encode("ascii")
                n += 1
        if n:
            self._refresh()
        return n

    def set_make(self, make: str) -> bool:
        """Rewrite the manufacturer token (``Lexus`` -> ``Nonesuch Motors``).

        This is the whole of "what brand is this car": the game files a car
        under this string and nothing else, so a new brand needs no record -
        only a car that names it.  The token is addressed by index (3) rather
        than by value, because a make can appear again elsewhere in the file and
        rewriting those copies would be a different edit.  Returns whether the
        file changed; the caller must save the whole spec, since a longer name
        moves every later field.
        """
        new = make.encode("ascii")
        if not new:
            return False
        if self.tokens[3][0] != "s":
            return False
        if self.tokens[3][3] == new:
            return False
        self.tokens[3][3] = new
        self._refresh()
        return True

    def strings(self) -> list[str]:
        return [t[3].decode("ascii", "replace") for t in self.tokens if t[0] == "s"]

    # ---- bytes ---------------------------------------------------------
    def to_bytes(self) -> bytes:
        return detokenize(self.tokens)

    def summary(self) -> str:
        return (f"id {self.car_id}  {self.year()} {self.make()} {self.model()}  "
                f"appearance {self.appearance_id()}  "
                f"aero {'yes' if self.aero_flag() else 'no'}  "
                f"{len(self.tokens)} tokens, {len(self.to_bytes())} bytes")


def _anchor_car_strings(tokens: list, raw: bytes) -> list:
    """Make sure the two ``CAR_*`` markers are whole string tokens.

    :func:`tokenize` decides "is this four bytes a length?" by checking whether
    what follows is printable, and that guess can be wrong: the field in front of
    the manufacturer key is a count of ``1``, so ``01 00 00 00`` followed by a
    string whose length byte is a printable character (32..126 - a 32-character
    brand key hits it exactly) reads as "a one-byte string", and every token
    after that point is off by four bytes.  The file is still valid - the engine
    reads it by schema, not by guessing - but every reader here loses the car's
    name, its brand key and its PR.

    The two markers are fixed text and unique enough to find in the bytes, so
    they are re-anchored: the string that contains the marker becomes a token of
    its own and the bytes either side are tokenized separately.  Nothing else is
    touched, and the result still detokenizes to the same file byte for byte.
    """
    for marker in (b"CAR_MANUFACTURER_", b"CAR_NAME_"):
        pos = raw.find(marker)
        if pos < 4:
            continue
        start = pos - 4
        length = struct.unpack_from("<I", raw, start)[0]
        end = start + 4 + length
        if not 1 <= length <= 200 or end > len(raw):
            continue
        if any(t[0] == "s" and t[1] == start for t in tokens):
            continue                      # already a proper token
        head = tokenize(raw[:start])
        middle = ["s", start, length, raw[pos:pos + length]]
        tail = [[kind, off + end, ln, payload]
                for kind, off, ln, payload in tokenize(raw[end:])]
        tokens = head + [middle] + tail
    return tokens


def parse_spec(data: bytes) -> Spec:
    toks = _anchor_car_strings(tokenize(data), data)
    if detokenize(toks) != data:
        raise SpecError("token round trip failed - not a spec file?")
    return Spec(toks, data)


def load_spec(depot: str, car_id: int | str) -> Spec:
    """Load a spec by numeric id or by ``<id>_<name>`` stem."""
    folder = os.path.join(depot, *SPEC_DIR.split("/"))
    if isinstance(car_id, int):
        hits = [f for f in os.listdir(folder)
                if f.endswith(".bin.nct") and f.split("_")[0].isdigit()
                and int(f.split("_")[0]) == car_id]
        if not hits:
            raise SpecError(f"no spec for car id {car_id}")
        path = os.path.join(folder, hits[0])
    elif str(car_id).endswith(".bin.nct"):
        path = os.path.join(folder, car_id)
    else:
        path = os.path.join(folder, car_id + ".bin.nct")
    return parse_spec(nct.read(path))


def save_spec(spec: Spec, path: str) -> int:
    blob = spec.to_bytes()
    nct.write(path, blob)
    return len(blob)


def spec_stem(depot: str, car_id: int) -> str:
    """``611_2012_lexus_lfa_animtest`` for a car id."""
    folder = os.path.join(depot, *SPEC_DIR.split("/"))
    for f in os.listdir(folder):
        if f.endswith(".bin.nct") and f.split("_")[0].isdigit():
            if int(f.split("_")[0]) == car_id:
                return f[:-len(".bin.nct")]
    raise SpecError(f"no spec for car id {car_id}")


# ------------------------------------------------------------------ cardesc
class Cardesc:
    """``cardesc.list.nct``: the ``<id>_<name>.bin`` list."""

    def __init__(self, entries: list[bytes]):
        self.entries = entries

    def __len__(self) -> int:
        return len(self.entries)

    def ids(self) -> list[int]:
        return [int(e.split(b"_")[0]) for e in self.entries]

    def add(self, entry: str | bytes, *, at: int | None = None) -> int:
        b = entry.encode("ascii") if isinstance(entry, str) else entry
        if any(e == b for e in self.entries):
            raise SpecError(f"{b!r} is already listed")
        new_id = int(b.split(b"_")[0])
        pos = at
        if pos is None:
            pos = len(self.entries)
            for i, e in enumerate(self.entries):
                if int(e.split(b"_")[0]) > new_id:
                    pos = i
                    break
        self.entries.insert(pos, b)
        return pos

    def remove(self, entry: str | bytes) -> int:
        b = entry.encode("ascii") if isinstance(entry, str) else entry
        i = self.entries.index(b)
        self.entries.pop(i)
        return i

    def to_bytes(self) -> bytes:
        out = bytearray()
        for e in self.entries:
            out += struct.pack("<I", len(e)) + e
        return bytes(out)

    def summary(self) -> str:
        ids = self.ids()
        return f"{len(self.entries)} entries, ids {min(ids)}..{max(ids)}"


def parse_cardesc(data: bytes) -> Cardesc:
    entries = []
    pos = 0
    while pos < len(data):
        ln = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        entries.append(data[pos:pos + ln])
        pos += ln
    if pos != len(data):
        raise SpecError("cardesc: length mismatch")
    return Cardesc(entries)


def load_cardesc(depot: str) -> Cardesc:
    return parse_cardesc(nct.read(os.path.join(depot, *CARDESC.split("/"))))


def save_cardesc(c: Cardesc, path: str) -> int:
    blob = c.to_bytes()
    nct.write(path, blob)
    return len(blob)


# -------------------------------------------------------------- fixed tables
class FixedTable:
    """A table of ``u32 id`` prefixed fixed size records, sorted by id.

    ``header`` is the number of bytes before the first record and ``count_at``
    is where the record count lives inside that header - they differ per table:
    suspension has ``[u32 1][u32 count]`` (header 8, count at 4) while damage
    has just ``[u32 count]`` (header 4, count at 0).  ``prefix`` keeps the bytes
    of the header that are not the count, so a rebuild is byte exact.
    """

    def __init__(self, records: list[bytes], *, header: int, record: int,
                 count_at: int, name: str = "", prefix: bytes = b""):
        self.records = records
        self.header = header
        self.record = record
        self.count_at = count_at
        self.name = name
        self.prefix = prefix

    def __len__(self) -> int:
        return len(self.records)

    def ids(self) -> list[int]:
        return [struct.unpack_from("<I", r, 0)[0] for r in self.records]

    def get(self, rid: int) -> bytes:
        for r in self.records:
            if struct.unpack_from("<I", r, 0)[0] == rid:
                return r
        raise SpecError(f"{self.name}: no record with id {rid}")

    def add(self, rec: bytes, *, rid: int | None = None) -> int:
        if len(rec) != self.record:
            raise SpecError(f"{self.name}: record must be {self.record} bytes")
        rid = struct.unpack_from("<I", rec, 0)[0] if rid is None else rid
        ids = self.ids()
        if rid in ids:
            raise SpecError(f"{self.name}: id {rid} already present")
        pos = 0
        while pos < len(ids) and ids[pos] < rid:
            pos += 1
        self.records.insert(pos, rec)
        return pos

    def remove(self, rid: int) -> int:
        ids = self.ids()
        i = ids.index(rid)
        self.records.pop(i)
        return i

    def to_bytes(self) -> bytes:
        head = bytearray(self.prefix) if self.prefix else bytearray(self.header)
        struct.pack_into("<I", head, self.count_at, len(self.records))
        return bytes(head) + b"".join(self.records)

    def summary(self) -> str:
        return (f"{self.name}: {len(self.records)} x {self.record} bytes, "
                f"ids {min(self.ids())}..{max(self.ids())}")


def parse_fixed(data: bytes, *, header: int, record: int, count_at: int = 0,
                name: str = "") -> FixedTable:
    n = struct.unpack_from("<I", data, count_at)[0]
    if header + n * record != len(data):
        raise SpecError(
            f"{name}: {header} + {n} * {record} != {len(data)}")
    recs = [data[header + i * record:header + (i + 1) * record]
            for i in range(n)]
    return FixedTable(recs, header=header, record=record, count_at=count_at,
                      name=name, prefix=data[:header])


def load_suspension(depot: str) -> FixedTable:
    return parse_fixed(nct.read(os.path.join(depot, *SUSPENSION.split("/"))),
                       header=8, record=140, count_at=4, name="suspension")


def load_damage(depot: str) -> FixedTable:
    return parse_fixed(nct.read(os.path.join(depot, *DAMAGE.split("/"))),
                       header=4, record=116, count_at=0, name="damage")


#: The 34 four-byte fields of a suspension record are **not** all floats.
#: Reading the record as ``<34f`` makes fields ``10..20`` and ``25..31`` look
#: like zeros, because they are small ``u32`` values (5..100) that decode as
#: denormals (``8.6881e-44`` and friends).  They are per-axle percentages,
#: stored front/rear in pairs.  Real floats: ``0 1 2 3 6 7 8 9 21 22 23 24 32
#: 33``; always zero: ``4 5``.
SUSP_INT_FIELDS = (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
                   25, 26, 27, 28, 29, 30, 31)

#: Index of the front/rear tyre **diameter** in a suspension record's floats.
SUSP_TYRE_FRONT = 21
SUSP_TYRE_REAR = 22


def suspension_percent(rec: bytes, index: int) -> int:
    """One of the per-axle percentage fields (see :data:`SUSP_INT_FIELDS`)."""
    if index not in SUSP_INT_FIELDS:
        raise ValueError(f"{index} is not a u32 field; see SUSP_INT_FIELDS")
    return struct.unpack_from("<I", rec, 4 + 4 * index)[0]



def suspension_tyre_diameter(rec: bytes) -> tuple[float, float]:
    """Front and rear tyre diameter in metres, straight from the table."""
    return (struct.unpack_from("<f", rec, 4 + 4 * SUSP_TYRE_FRONT)[0],
            struct.unpack_from("<f", rec, 4 + 4 * SUSP_TYRE_REAR)[0])


def set_suspension_tyre(rec: bytes, front: float | None = None,
                        rear: float | None = None) -> bytes:
    b = bytearray(rec)
    if front is not None:
        struct.pack_into("<f", b, 4 + 4 * SUSP_TYRE_FRONT, float(front))
    if rear is not None:
        struct.pack_into("<f", b, 4 + 4 * SUSP_TYRE_REAR, float(rear))
    return bytes(b)


#: Index of the front/rear suspension **travel** in a suspension record's
#: floats, in metres.  Measured over all 541 cars: 0.003 .. 0.150 for anything
#: sane, median 0.039 front and 0.041 rear.
#:
#: These two numbers are the *upward* half of the ride-height slider and nothing
#: else.  Proved on screen on 2026-11-23: the Silvia reads +10/+15 at the shipped
#: 0.010/0.015, +180/+180 at 0.180/0.180 and +5/+4 at 0.005/0.005, while the
#: *downward* half stayed at -9/-14 through all three.  The down half is not
#: stored - see :func:`suspension_down_travel`.
SUSP_TRAVEL_FRONT = 23
SUSP_TRAVEL_REAR = 24

#: What the shipped cars use, as a guard rail rather than a limit: the highest
#: sane value is the 1966 Cobra's 0.150.  One car, the Essenza SCV12, carries
#: 0.632 - and that turns out not to be a typo: its down travel is 0, so the
#: whole slider sits above zero and 63 cm up is what the car actually gets.
SUSP_TRAVEL_SANE = (0.0, 0.20)


def suspension_travel(rec: bytes) -> tuple[float, float]:
    """Front and rear suspension travel in metres, straight from the table."""
    return (struct.unpack_from("<f", rec, 4 + 4 * SUSP_TRAVEL_FRONT)[0],
            struct.unpack_from("<f", rec, 4 + 4 * SUSP_TRAVEL_REAR)[0])


def set_suspension_travel(rec: bytes, front: float | None = None,
                          rear: float | None = None) -> bytes:
    """Write the front and/or rear travel, leaving every other float alone."""
    b = bytearray(rec)
    if front is not None:
        struct.pack_into("<f", b, 4 + 4 * SUSP_TRAVEL_FRONT, float(front))
    if rear is not None:
        struct.pack_into("<f", b, 4 + 4 * SUSP_TRAVEL_REAR, float(rear))
    return bytes(b)


def suspension_down_travel(rec: bytes, loaded_front: float,
                           loaded_rear: float) -> tuple[float, float]:
    """The **downward** half of the ride-height slider, in metres.

    It is not stored as a number anywhere.  The engine derives it from the
    tyre: ``diameter - 2 * loaded_radius``, i.e. twice the tyre's static
    deflection.  ``diameter`` is this record's f21/f22, and ``loaded_radius``
    is f1/f5 of the car's appearance block (``rr3lib.appearance``), which is
    the squashed radius the wheel is drawn at.

    Proved twice on screen on 2026-11-23, and both proofs turn on the float
    truncation the UI applies:

    * Silvia (id 114): 0.634 - 2*0.312 = 0.00999999 -> shows **-9**,
      0.639 - 2*0.312 = 0.01499999 -> shows **-14**.  Editing f23/f24 to 0.180
      or 0.005 leaves both numbers alone, which is what pointed here.
    * Essenza SCV12 (id 418): 0.612 - 2*0.306 = 1.1e-8 -> shows **0**, and
      0.672 - 2*0.336 = 9e-9 -> shows **0**; the car cannot be lowered at all,
      even though its f23/f24 read 0.632/0.634 and it can rise 63 cm.

    For 280 of the 341 cars the two tables were authored consistently, so this
    comes out equal to f23/f24 and the difference is invisible - which is why
    the down half looked like "travel minus one" for a while.
    """
    dia = suspension_tyre_diameter(rec)
    return (dia[0] - 2.0 * float(loaded_front),
            dia[1] - 2.0 * float(loaded_rear))


def as_float32(value: float) -> float:
    """The value as the table would store it."""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def display_mm(metres: float) -> int:
    """What the ride-height slider prints for a length in metres.

    The game truncates rather than rounds, which is the whole reason a car
    whose numbers look like 10 and 15 reads as ``+10 / -9`` and ``+15 / -14``:
    ``0.015`` is stored as ``0.014999999664`` and ``int(14.999999 * 1000)``
    is 14.
    """
    return int(as_float32(metres) * 1000)


def diameter_for_down(loaded: float, down: float) -> float:
    """The tyre diameter that makes the downward travel show as ``down``.

    ``down`` is in metres and is rounded to whole millimetres first, because
    that is the resolution the slider has.  The search runs in float32 - the
    obvious answer ``2 * loaded + down`` is a hair too small once it is stored:
    ``0.649 - 2*0.312`` is ``0.0249999`` and prints as 24, not 25.
    """
    want = int(round(float(down) * 1000.0))
    two = as_float32(2.0 * as_float32(loaded))
    if want <= 0:
        return two
    v = as_float32(two + want / 1000.0)
    for _ in range(400):
        if int(as_float32(as_float32(v) - two) * 1000) >= want:
            return v
        v = as_float32(v + 0.000002)
    return v


def suspension_range(rec: bytes, loaded, *,
                     up=None, down=None) -> bytes:
    """Write the ride-height range as the user thinks of it.

    ``up`` and ``down`` are ``(front, rear)`` in metres, or ``None`` to leave
    that half alone.  ``loaded`` is the car's loaded tyre radius, front and rear
    - appearance record floats 1 and 5 (``appearance.Record.tyre_radius()``),
    which the down half is measured from.

    The two halves are independent fields, so writing one never disturbs the
    other: up is f23/f24, down is the tyre diameter f21/f22.
    """
    b = rec
    if up is not None:
        b = set_suspension_travel(b, front=up[0], rear=up[1])
    if down is not None:
        b = set_suspension_tyre(
            b,
            front=diameter_for_down(loaded[0], down[0]),
            rear=diameter_for_down(loaded[1], down[1]))
    return b


def suspension_range_mm(rec: bytes, loaded) -> tuple[int, int, int, int]:
    """The range in whole millimetres: up front, up rear, down front, down rear.

    The up half is rounded, the down half is truncated, and that is not an
    oversight: the down half is solved for so truncation lands on the wanted
    number, while the upper half is stored exactly as asked and the game prints
    it inconsistently (a shipped 0.010 reads as +10, our 0.025 read as +24).
    Rounding at least makes the shipped cars report what the screen says.
    """
    up = suspension_travel(rec)
    down = suspension_down_travel(rec, loaded[0], loaded[1])
    return (int(round(up[0] * 1000.0)), int(round(up[1] * 1000.0)),
            display_mm(down[0]), display_mm(down[1]))


# ------------------------------------------------------------------ selftest
def selftest(depot: str | None = None) -> int:
    depot = depot or os.environ.get("RR3_DEPOT", "")
    if not depot:
        print("spec selftest: no depot (set RR3_DEPOT)")
        return 2
    folder = os.path.join(depot, *SPEC_DIR.split("/"))
    files = sorted(f for f in os.listdir(folder)
                   if f.endswith(".bin.nct") and f.split("_")[0].isdigit())
    bad = 0
    for f in files:
        plain = nct.read(os.path.join(folder, f))
        try:
            s = parse_spec(plain)
        except SpecError as exc:
            print(f"FAIL {f}: {exc}")
            bad += 1
            continue
        if s.to_bytes() != plain:
            print(f"FAIL {f}: round trip differs")
            bad += 1
    print(f"spec selftest: {len(files)} files, {len(files) - bad} ok, {bad} failures")

    c = load_cardesc(depot)
    print(f"cardesc: {c.summary()}")
    if c.to_bytes() != nct.read(os.path.join(depot, *CARDESC.split("/"))):
        print("FAIL cardesc round trip")
        bad += 1
    for tbl, loader in (("suspension", load_suspension), ("damage", load_damage)):
        t = loader(depot)
        print(t.summary())
        if t.to_bytes() != nct.read(
                os.path.join(depot, *(SUSPENSION if tbl == "suspension"
                                      else DAMAGE).split("/"))):
            print(f"FAIL {tbl} round trip")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
