"""Locate the game's driver assets and decide which pair a car uses.

The driver is not part of a car folder.  ``<depot>/driver/`` holds

* four models - ``driver_lod_a.m3g`` (15 parts), ``driver_lod_b.m3g`` (15 parts,
  the same figure at a lower density), ``driver_lod_c.m3g`` and
  ``driver_lod_d.m3g`` (one mesh each: legs already in the seat), plus twelve
  per-car ``driver_lod_c_<car>.m3g`` / ``driver_lod_d_<car>.m3g`` variants;
* 35 animations - ``driver.banim`` (the generic seated pose) and 35
  ``driver_<car>.banim`` files for cars with their own seating.

``materials.bin`` has no material called ``driver`` and the livery string table
has no ``driver`` slot: the fifteen parts carry the material name ``driver``
straight from the ``.m3g``'s own material list, and the texture is the shared
``vehicles/common/driver.dxt.dds.z`` (nine skins ship: the default plus
``driver_alesi``, ``driver_alonso``, ``driver_berger``, ``driver_ferrari`` and
friends).

The car's own animation is named in the car's data record:
``vehicles/data/<id>_<car>.bin.nct`` carries a length-prefixed string field
holding ``driver_<x>.banim`` (224 of the 540 records have one; the rest fall back
to ``driver.banim``).  Those ``.bin.nct`` files are RC4 encrypted with the
standard ``.nct`` key, so :func:`banim_from_nct` decrypts the record and reads the
field straight out of it - no name guessing.

``vehicles/data/DriverSelection.dat.nct`` is *not* that table: it decrypts fine
but holds the F1 driver portraits used by the car-select screen (names, helmet
and car images), not an animation per car.

When no data record is at hand the pair is still guessed by name: the longest
``driver_<x>.banim`` whose ``<x>`` appears anywhere in the car folder's name
(``driver_caterham`` for ``2013_caterham_seven_620r``), else ``driver.banim``.
"""

from __future__ import annotations

import os
import re
import struct

from . import nct as nctlib

DRIVER_DIR = "driver"
DEFAULT_BANIM = "driver.banim"
BANIM_SUFFIX = ".banim"
DATA_DIR = os.path.join("vehicles", "data")
DEFAULT_TEXTURE = "vehicles/common/driver.dxt.dds.z"
SKIN_PREFIX = "driver_"
LODS = ("a", "b", "c", "d")

#: How many tokens after the ``CAR_NAME_`` string the driver field sits.  Twelve
#: tokens separate the name from the field's own length prefix, in all 540
#: records; the count is written down rather than searched for so a record with a
#: second ``.banim`` string cannot be misread.
FIELD_TOKENS = 12

#: The longest string any record in this data cast holds.  Longer length prefixes
#: are numbers, not strings - the record has no other way to tell them apart.
_MAX_STRING = 200


class DriverError(Exception):
    """A driver field that cannot be read or written as asked."""

#: Every GPU family the driver skins are written for.  A depot unpacked for
#: Mali holds ``driver.etc.dds.z`` where this one holds ``driver.dxt.dds.z``;
#: both decode (see :mod:`rr3lib.etcdecode`).
TEXTURE_SUFFIXES = (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z")

#: ``driver_919_lmp1`` matches ``2019_mclaren_919_lmp1``; the year prefix is not
#: part of the name.
_YEAR = re.compile(r"^\d{4}_")


def driver_dir(depot):
    """``<depot>/driver`` when it exists, else None."""
    if not depot:
        return None
    path = os.path.join(depot, DRIVER_DIR)
    return path if os.path.isdir(path) else None


def model_for(depot, lod="a", car=None, banim_stem=""):
    """Path of ``driver_lod_<lod>.m3g``, preferring the right variant.

    ``driver_lod_c_mclaren_mp4x.m3g`` wins over ``driver_lod_c.m3g`` for that
    car; the plain file is the fallback for every other car.

    ``banim_stem`` is the ``<x>`` of the ``driver_<x>.banim`` the car actually
    animates with, and it is the better key when it is known: a car's pose and
    its own mesh ship together, so the mesh that goes with a special animation is
    the one named after it.  The depot proves the point - ``driver_lod_c_*.m3g``
    exists for exactly the 12 stems that also have a special ``.banim``, and for
    no others.  Matching is by containment in both directions, because the names
    are not spelled the same way: ``driver_renault_dezirconcept.banim`` belongs
    with ``driver_lod_c_dezirconcept.m3g``.
    """
    folder = driver_dir(depot)
    if folder is None:
        return None
    lod = (lod or "a").lower()

    def own(stem):
        path = os.path.join(folder, f"driver_lod_{lod}_{stem}.m3g")
        return path if os.path.isfile(path) else None

    if banim_stem:
        hit = own(banim_stem)
        if hit:
            return hit
        key = _norm(banim_stem)
        if key:
            best = None
            for name in sorted(os.listdir(folder)):
                if not (name.startswith(f"driver_lod_{lod}_")
                        and name.endswith(".m3g")):
                    continue
                stem = name[len(f"driver_lod_{lod}_"):-len(".m3g")]
                other = _norm(stem)
                if not other:
                    continue
                if other in key or key in other:
                    if best is None or len(other) > len(best[1]):
                        best = (os.path.join(folder, name), other)
            if best is not None:
                return best[0]

    if car:
        hit = own(car)
        if hit:
            return hit
        stem = _YEAR.sub("", car)
        if stem != car:
            hit = own(stem)
            if hit:
                return hit
    plain = os.path.join(folder, f"driver_lod_{lod}.m3g")
    return plain if os.path.isfile(plain) else None


def available_lods(depot):
    """The driver levels that ship, finest first."""
    folder = driver_dir(depot)
    if folder is None:
        return []
    return [c.upper() for c in LODS
            if os.path.isfile(os.path.join(folder, f"driver_lod_{c}.m3g"))]


def _norm(text):
    """Letters and digits only, lower case - the depot is inconsistent here."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def data_dir(depot):
    """``<depot>/vehicles/data`` when it exists, else None."""
    if not depot:
        return None
    path = os.path.join(depot, DATA_DIR)
    return path if os.path.isdir(path) else None


def car_record(depot, car):
    """The car's data record, ``vehicles/data/<id>_<car>.bin.nct``, or None.

    The record names the car inside its filename, and the name there does not
    always equal the folder's (``2014_toyota_ts040`` is
    ``2014_toyota_ts040_hybrid`` in the data, ``1971_lamborghini_miurap400sv`` is
    ``1971_lamborghini_miura``), so an exact hit is tried first and then the
    shortest name that is a prefix of the other.  That resolves 266 of the 463
    body folders; the remaining 197 simply have no record in this data cast.
    """
    folder = data_dir(depot)
    if folder is None or not car:
        return None
    key = _norm(car)
    records = [n for n in sorted(os.listdir(folder)) if n.endswith(".bin.nct")]
    exact, prefix = None, None
    for name in records:
        stem = name[: -len(".bin.nct")]
        car_name = stem.split("_", 1)[1] if "_" in stem else stem
        nk = _norm(car_name)
        if nk == key:
            exact = name
            break
        if nk.startswith(key) or key.startswith(nk):
            if prefix is None or len(nk) < len(_norm(prefix)):
                prefix = name
    return os.path.join(folder, exact or prefix) if (exact or prefix) else None


def _token_size(raw, i):
    """How many bytes one token occupies at ``i``, by the record's own rule."""
    n = len(raw)
    if i + 4 <= n:
        ln = struct.unpack_from("<I", raw, i)[0]
        if 1 <= ln <= _MAX_STRING and i + 4 + ln <= n:
            chunk = raw[i + 4:i + 4 + ln]
            if all(32 <= c < 127 for c in chunk):
                return 4 + ln
    return 4 if i + 4 <= n else n - i


def field_offset(raw):
    """Byte offset of the length prefix of the driver field, or None.

    The field is not found by scanning for a ``.banim`` name - that guesses, and
    it breaks the moment a record holds another string ending in ``.banim``.
    It is the **thirteenth token after the ``CAR_NAME_`` string**, and that holds
    for all 540 records, including the 33 whose ``CAR_NAME_`` is not itself a
    token (they hold a shorter name whose length prefix happens to be readable as
    a number) and the 9 whose field sits inside what a naive tokenizer calls a
    number.  Walking token by token from the name lands on it every time.
    """
    key = raw.find(b"CAR_NAME_")
    if key < 4:
        return None
    ln = struct.unpack_from("<I", raw, key - 4)[0]
    if not (1 <= ln <= _MAX_STRING) or key + ln > len(raw):
        return None
    at = key + ln
    for _ in range(FIELD_TOKENS):
        at += _token_size(raw, at)
        if at + 4 > len(raw):
            return None
    return at


def field_in_record(nct_path):
    """The driver field of a record: a name, ``""`` when it names none, or None.

    ``""`` and ``None`` are different answers and the difference matters to
    :func:`banim_for`: an empty field means the car really has no pose of its own
    and falls back to ``driver.banim``, while ``None`` means the record could not
    be read at all.
    """
    if not nct_path or not os.path.isfile(nct_path):
        return None
    try:
        plain = nctlib.read(nct_path)
    except Exception:  # noqa: BLE001 - an unreadable record is simply no answer
        return None
    at = field_offset(plain)
    if at is None:
        return None
    ln = struct.unpack_from("<I", plain, at)[0]
    if not (0 <= ln <= _MAX_STRING) or at + 4 + ln > len(plain):
        return None
    return plain[at + 4:at + 4 + ln].decode("ascii", "replace")


def banim_in_record(nct_path):
    """The ``driver_<x>.banim`` a car's data record names, or None.

    This is the game's own answer: 224 of the 540 records carry one, and every
    name they give exists in ``driver/``.
    """
    got = field_in_record(nct_path)
    if not got:
        return None
    return got


def set_field(nct_path, name):
    """Point a car's record at ``name`` (``""`` clears it).  True if it changed.

    The field is a length-prefixed string in the middle of the record, so the
    splice shifts everything after it - which is fine, because the record is a
    stream of self-describing tokens rather than a table of fixed offsets.  The
    file is re-encrypted only if it was encrypted to begin with.
    """
    name = (name or "").strip()
    if name and not name.lower().endswith(BANIM_SUFFIX):
        raise DriverError(f"{name} is not a .banim name")
    if name and not (name.isascii() and all(32 <= ord(c) < 127 for c in name)):
        raise DriverError(f"{name} is not plain ASCII")
    if not nct_path or not os.path.isfile(nct_path):
        raise DriverError(f"no data record at {nct_path}")
    blob = open(nct_path, "rb").read()
    encrypted = nctlib.looks_encrypted(blob)
    plain = nctlib.read(nct_path)
    at = field_offset(plain)
    if at is None:
        raise DriverError(f"{os.path.basename(nct_path)} has no driver field")
    old_len = struct.unpack_from("<I", plain, at)[0]
    if not (0 <= old_len <= _MAX_STRING):
        raise DriverError(f"{os.path.basename(nct_path)} has a broken driver field")
    old = plain[at + 4:at + 4 + old_len].decode("ascii", "replace")
    if old == name:
        return False
    raw = name.encode("ascii")
    plain = plain[:at] + struct.pack("<I", len(raw)) + raw + plain[at + 4 + old_len:]
    nctlib.write(nct_path, plain, encrypt=encrypted)
    return True


def banims(depot):
    """Every ``driver*.banim`` the depot ships, as ``(stem, path)``, sorted."""
    folder = driver_dir(depot)
    if folder is None:
        return []
    out = []
    for name in sorted(os.listdir(folder)):
        if name.endswith(BANIM_SUFFIX) and name.startswith("driver"):
            out.append((name[: -len(BANIM_SUFFIX)], os.path.join(folder, name)))
    return out


def _strings(raw, minimum=3):
    """Printable ASCII runs, which is how every string in these records is stored."""
    out, cur = [], bytearray()
    for byte in raw:
        if 32 <= byte < 127:
            cur.append(byte)
        else:
            if len(cur) >= minimum:
                out.append(bytes(cur).decode("ascii"))
            cur.clear()
    if len(cur) >= minimum:
        out.append(bytes(cur).decode("ascii"))
    return out


def banim_for(depot, car=None):
    """The animation a car uses, from its data record, else by name, else generic.

    Returns ``(path, matched)``; ``matched`` is the ``<x>`` of a ``driver_<x>``
    file, ``""`` when the record named the animation (its answer is not a guess),
    or ``None`` for the generic file.

    Order of preference:

    1. the ``driver_<x>.banim`` named by ``vehicles/data/<id>_<car>.bin.nct`` -
       the game's own field, so nothing is guessed;
    2. otherwise the longest ``driver_<x>.banim`` whose ``<x>`` appears anywhere
       in the car folder's name (``driver_caterham`` for
       ``2013_caterham_seven_620r``).  The name in the data is often a trim level
       the folder drops, so this catches what the record cannot;
    3. otherwise ``driver.banim``.
    """
    folder = driver_dir(depot)
    if folder is None:
        return None, None
    plain = os.path.join(folder, DEFAULT_BANIM)
    if not car:
        return (plain if os.path.isfile(plain) else None), None

    record = car_record(depot, car)
    named = banim_in_record(record)
    if named:
        path = os.path.join(folder, named)
        if os.path.isfile(path):
            return path, named[len(SKIN_PREFIX):-len(BANIM_SUFFIX)]

    stem = _YEAR.sub("", car).lower()
    best = None
    for name in sorted(os.listdir(folder)):
        if not (name.startswith(SKIN_PREFIX) and name.endswith(BANIM_SUFFIX)):
            continue
        key = name[len(SKIN_PREFIX):-len(BANIM_SUFFIX)].lower()
        if key == "lod_a" or key.startswith("lod_"):
            continue
        if key in stem and (best is None or len(key) > len(best[1])):
            best = (os.path.join(folder, name), key)
    if best is not None:
        return best
    return (plain if os.path.isfile(plain) else None), None


def skins(depot):
    """Every ``vehicles/common/driver*`` texture, default first.

    A depot only unpacks the copy its build targets, so the suffix is whichever
    of :data:`TEXTURE_SUFFIXES` is on disk; a skin is one *name*, not one file.
    """
    if not depot:
        return []
    folder = os.path.join(depot, "vehicles", "common")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    found = {}
    for name in names:
        if not name.startswith("driver"):
            continue
        if name.startswith("driver_body") or name.startswith("driver_glove"):
            continue
        for suffix in TEXTURE_SUFFIXES:
            if name.endswith(suffix):
                stem = name[:-len(suffix)]
                # The first suffix in TEXTURE_SUFFIXES wins when a depot holds
                # more than one family.
                found.setdefault(stem, os.path.join(folder, name))
                break
    out = [found[stem] for stem in sorted(found)]
    out.sort(key=lambda p: (os.path.basename(p) != _default_skin_name(),
                            os.path.basename(p)))
    return out


def _default_skin_name():
    """File name of the default skin, whichever suffix it has."""
    for suffix in TEXTURE_SUFFIXES:
        if DEFAULT_TEXTURE.endswith(suffix):
            return os.path.basename(DEFAULT_TEXTURE)
    return os.path.basename(DEFAULT_TEXTURE)


def texture_for(depot, skin=""):
    """The driver texture, optionally a named skin (``alesi``/``ferrari``/...).

    ``skin`` is accepted with or without the ``driver_`` prefix and with or
    without the container suffix, so ``alesi``, ``driver_alesi``,
    ``driver_alesi.dxt.dds.z`` and ``driver_alesi.etc.dds.z`` all resolve to the
    same picture, whichever GPU family this depot ships.
    """
    folder = os.path.join(depot or "", "vehicles", "common")
    if not skin:
        for suffix in TEXTURE_SUFFIXES:
            path = os.path.join(depot or "", "vehicles", "common",
                                "driver" + suffix)
            if os.path.isfile(path):
                return path
        return None
    stem = skin
    for suffix in TEXTURE_SUFFIXES:
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    if not stem.startswith(SKIN_PREFIX):
        stem = SKIN_PREFIX + stem
    for suffix in TEXTURE_SUFFIXES:
        path = os.path.join(folder, stem + suffix)
        if os.path.isfile(path):
            return path
    return None


def summary(depot, car=None):
    """One-line description of what a car would get, for reports and tests."""
    model = model_for(depot, "a", car)
    banim, matched = banim_for(depot, car)
    texture = texture_for(depot)
    return {
        "model": model,
        "banim": banim,
        "banim_matched": matched,
        "texture": texture,
        "lods": available_lods(depot),
        "skins": len(skins(depot)),
    }


def selftest(depot):
    """Check every car can be paired with a model and an animation."""
    vehicles = os.path.join(depot, "vehicles")
    cars = sorted(c for c in os.listdir(vehicles)
                  if os.path.isfile(os.path.join(vehicles, c, c + "_a.m3g")))
    no_model, no_banim, own = [], [], 0
    for car in cars:
        if model_for(depot, "a", car) is None:
            no_model.append(car)
        banim, matched = banim_for(depot, car)
        if banim is None:
            no_banim.append(car)
        elif matched:
            own += 1
    print(f"driver: {len(cars)} cars, {own} with their own .banim, "
          f"{len(no_model)} without a model, {len(no_banim)} without an animation")
    print(f"driver: {len(skins(depot))} skins, lods {available_lods(depot)}")
    return len(no_model) + len(no_banim)
